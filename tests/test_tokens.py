from brain import query
from brain.db import connect
from brain.ingest import ingest

from conftest import SID, SID2, rec, session_records, write_jsonl


def reply(uuid, msg_id, ts, content, sid=SID, model="claude-sonnet-5-5", **usage):
    r = rec(uuid, "assistant", content, ts, sid=sid)
    counters = {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 900,
                "output_tokens": 10, **usage}
    r["message"].update({"id": msg_id, "model": model, "usage": counters})
    return r


def _text(t):
    return [{"type": "text", "text": t}]


def _tokens(conn, *argv):
    return query.render(conn, query.build_parser().parse_args(["tokens", *argv]))


def _archive(conn, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", [
        *session_records(),
        # One reply streamed as three records: same id, usage repeated, output growing.
        reply("r1", "msg_1", "2026-10-01T10:01:00Z", [{"type": "thinking", "thinking": "hm"}], output_tokens=5),
        reply("r2", "msg_1", "2026-10-01T10:01:01Z", _text("first"), output_tokens=40),
        reply("r3", "msg_1", "2026-10-01T10:01:02Z", [{"type": "tool_use", "name": "Bash", "input": {}}],
              output_tokens=40),
        reply("r4", "msg_2", "2026-10-01T10:02:00Z", _text("second"), cache_read_input_tokens=1900),
    ])
    ingest(conn, root)


def test_a_reply_streamed_in_blocks_is_counted_once_with_its_final_output(conn, root):
    _archive(conn, root)
    rows = conn.execute("SELECT msg_id, output, cache_read FROM usage ORDER BY msg_id").fetchall()
    assert [tuple(r) for r in rows] == [("msg_1", 40, 900), ("msg_2", 10, 1900)]
    ingest(conn, root, full=True)  # re-reading changes nothing
    assert conn.execute("SELECT COUNT(*), SUM(output) FROM usage").fetchone()[:] == (2, 50)


def test_synthetic_and_subagent_replies(conn, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", [
        reply("s1", "msg_s", "2026-10-01T10:00:00Z", _text("x"), model="<synthetic>"),
        reply("a1", "msg_a", "2026-10-01T10:00:01Z", _text("y"), isSidechain=True) | {"isSidechain": True},
    ])
    ingest(conn, root)
    rows = conn.execute("SELECT msg_id, is_sidechain FROM usage").fetchall()
    assert [tuple(r) for r in rows] == [("msg_a", 1)]


def test_report_shows_totals_models_and_the_opening_cost(conn, root):
    _archive(conn, root)
    text = _tokens(conn)
    assert "2 replies in 1 session" in text
    assert "Output 50" in text and "cache read 2,800" in text
    assert "claude-sonnet-5-5 100%" in text
    assert "median 1,002" in text  # first reply's context: 2 + 100 + 900
    assert "2026-W40" in text


def test_report_is_scoped_by_project_and_date(conn, root):
    _archive(conn, root)
    assert "project mlvsgnn" in _tokens(conn, "--project", "mlvsgnn")
    assert "no token usage" in _tokens(conn, "--since", "2030-01-01")


def test_openings_ignore_subagents_and_take_the_earliest_reply(conn, root):
    write_jsonl(root / "p" / f"{SID2}.jsonl", [
        reply("b1", "msg_b", "2026-10-01T10:05:00Z", _text("later"), sid=SID2, cache_read_input_tokens=9000),
        reply("b0", "msg_c", "2026-10-01T10:00:00Z", _text("earlier"), sid=SID2),
        reply("b2", "msg_d", "2026-10-01T10:00:01Z", _text("agent"), sid=SID2, cache_read_input_tokens=50000)
        | {"isSidechain": True},
    ])
    ingest(conn, root)
    from brain import tokens
    rows = conn.execute("""SELECT u.session_id, u.ts, u.model, u.is_sidechain, u.input, u.cache_write,
                                  u.cache_read, u.output, s.project FROM usage u JOIN sessions s USING (session_id)""").fetchall()
    assert tokens.compute(rows)["openings"] == [1002]


def test_existing_archive_is_backfilled_once_when_usage_appears(tmp_path, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", [reply("r1", "msg_1", "2026-10-01T10:01:00Z", _text("hi"))])
    path = tmp_path / "old.db"
    old = connect(path)
    ingest(old, root)
    old.execute("DROP TABLE usage")  # an archive from before this table existed
    old.commit()
    old.close()
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0  # offsets forgotten
    ingest(conn, root)
    assert conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1  # no duplicates
    conn.close()


def test_forgetting_a_session_drops_its_usage(conn, root):
    from brain import forget
    _archive(conn, root)
    forget.forget_sessions(conn, [SID])
    assert conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 0
