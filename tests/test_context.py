import io
import json

from brain import context
from brain.db import connect
from brain.ingest import ingest

from conftest import CWD, SID, SID2, rec, session_records, write_jsonl


def _archive(root):
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    write_jsonl(root / "p" / f"{SID2}.jsonl", [
        rec("x1", "user", "Plot the ablation results", "2026-10-05T09:00:00Z", sid=SID2),
        {"type": "ai-title", "aiTitle": "Ablation plots", "sessionId": SID2},
    ])
    conn = connect()
    ingest(conn, root)
    return conn


def _hook(monkeypatch, capsys, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    context.run_hook()
    return capsys.readouterr().out


def test_off_by_default_prints_nothing(root, monkeypatch, capsys):
    _archive(root).close()
    assert context.configured_count() == 0
    assert _hook(monkeypatch, capsys, {"cwd": CWD, "source": "startup"}) == ""


def test_on_lists_latest_sessions_of_this_project_newest_first(root, monkeypatch, capsys):
    _archive(root).close()
    context.main(["on", "2"])
    capsys.readouterr()

    out = json.loads(_hook(monkeypatch, capsys, {"cwd": CWD, "source": "startup", "session_id": "new"}))
    text = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert '"mlvsgnn"' in text
    lines = text.splitlines()
    assert "Ablation plots" in lines[1] and SID2[:8] in lines[1]
    assert "GNN training" in lines[2]
    assert "not instructions" in lines[-1]


def test_skips_the_current_session_resumes_and_other_projects(root, monkeypatch, capsys):
    _archive(root).close()
    context.main(["on", "5"])
    capsys.readouterr()

    text = json.loads(_hook(monkeypatch, capsys, {"cwd": CWD, "source": "clear", "session_id": SID2})
                      )["hookSpecificOutput"]["additionalContext"]
    assert SID2[:8] not in text and SID[:8] in text
    assert _hook(monkeypatch, capsys, {"cwd": CWD, "source": "resume"}) == ""
    assert _hook(monkeypatch, capsys, {"cwd": "/home/u/elsewhere", "source": "startup"}) == ""


def test_broken_input_never_breaks_session_start(root, monkeypatch, capsys):
    _archive(root).close()
    context.main(["on"])
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    context.run_hook()
    assert capsys.readouterr().out == ""


def test_off_removes_the_setting(capsys):
    context.main(["on", "4"])
    assert context.configured_count() == 4
    context.main(["off"])
    assert context.configured_count() == 0
    context.main(["status"])
    assert "off" in capsys.readouterr().out


def test_untitled_throwaway_sessions_are_left_out(root, monkeypatch, capsys):
    conn = _archive(root)
    write_jsonl(root / "p" / "33333333-aaaa-bbbb-cccc-000000000003.jsonl", [
        rec("y1", "user", "hola", "2026-10-09T09:00:00Z", sid="33333333-aaaa-bbbb-cccc-000000000003")])
    ingest(conn, root)
    text = context.briefing(conn, CWD, 5)
    conn.close()
    assert "33333333" not in text and "(untitled)" not in text


def _tool(uuid, name, args, ts):
    return rec(uuid, "assistant", [{"type": "tool_use", "name": name, "input": args}], ts)


def _left_session(root):
    """SID worked in CWD, edited two files, then the user ran /clear."""
    write_jsonl(root / "p" / f"{SID}.jsonl", [
        rec("u1", "user", "Add early stopping to the GNN trainer", "2026-10-01T10:00:00Z"),
        {"type": "ai-title", "aiTitle": "Early stopping", "sessionId": SID},
        _tool("e1", "Edit", {"file_path": f"{CWD}/src/train.py", "old_string": "x"}, "2026-10-01T10:01:00Z"),
        rec("u2", "user", "si", "2026-10-01T10:02:00Z"),
        _tool("e2", "Write", {"file_path": f"{CWD}/tests/test_train.py", "content": "y"}, "2026-10-01T10:03:00Z"),
        rec("a1", "assistant", [{"type": "text", "text": "Done: patience 5, tests pass."}], "2026-10-01T10:04:00Z"),
    ])


def test_clear_hands_over_the_session_just_left(root, monkeypatch, capsys):
    _left_session(root)
    conn = connect()
    ingest(conn, root)
    conn.close()
    context.main(["on"])
    capsys.readouterr()
    # The last reply wasn't archived yet (the async Stop hook may still be running): caught up.
    write_jsonl(root / "p" / f"{SID}.jsonl", [
        rec("u3", "user", "Now plot the validation loss curve", "2026-10-01T10:05:00Z")])

    out = _hook(monkeypatch, capsys, {"cwd": CWD, "source": "clear", "session_id": "new-session",
                                      "transcript_path": str(root / "p" / "new-session.jsonl")})
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "handoff" in text and '"Early stopping"' in text and SID[:8] in text
    assert "Add early stopping" in text and "plot the validation loss" in text
    assert '"si"' not in text  # too short to mean anything here
    assert "Done: patience 5" in text
    assert "Files it edited: tests/test_train.py, src/train.py" in text
    assert f"claude-brain session {SID[:8]} --after 2026-10-01T10:00:00" in text
    assert "not instructions" in text


def test_clear_without_a_previous_transcript_falls_back_to_the_briefing(root, monkeypatch, capsys):
    _archive(root).close()
    context.main(["on"])
    capsys.readouterr()
    text = json.loads(_hook(monkeypatch, capsys, {"cwd": CWD, "source": "clear", "session_id": "x"})
                      )["hookSpecificOutput"]["additionalContext"]
    assert "latest sessions" in text


def test_compaction_points_at_the_verbatim_transcript(root, monkeypatch, capsys):
    _left_session(root)
    connect().close()
    context.main(["on"])
    capsys.readouterr()
    out = _hook(monkeypatch, capsys, {"cwd": CWD, "source": "compact", "session_id": SID,
                                      "transcript_path": str(root / "p" / f"{SID}.jsonl")})
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "compacted" in text and f"claude-brain session {SID[:8]}" in text
    assert "src/train.py" in text


def _usage_transcript(path, *sizes, sidechain_last=None):
    records = [rec(f"a{i}", "assistant", [{"type": "text", "text": "ok"}], f"2026-10-01T10:{i:02d}:00Z",
                   message={"role": "assistant", "content": "ok",
                            "usage": {"input_tokens": 2, "cache_read_input_tokens": n - 2,
                                      "cache_creation_input_tokens": 0, "output_tokens": 0}})
               for i, n in enumerate(sizes)]
    if sidechain_last:
        records.append({**records[-1], "isSidechain": True, "message": {
            "role": "assistant", "usage": {"input_tokens": sidechain_last}}})
    write_jsonl(path, records)


def _stop(monkeypatch, capsys, transcript):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"session_id": SID, "transcript_path": str(transcript)})))
    context.run_stop_hook()
    out = capsys.readouterr().out
    return json.loads(out)["systemMessage"] if out else None


def test_size_notice_once_per_band_and_again_after_compaction(tmp_path, monkeypatch, capsys):
    context.main(["on"])
    capsys.readouterr()
    t = tmp_path / "s.jsonl"
    _usage_transcript(t, 50_000)
    assert _stop(monkeypatch, capsys, t) is None
    _usage_transcript(t, 125_000, sidechain_last=900_000)  # subagents don't count
    assert "125k" in _stop(monkeypatch, capsys, t)
    _usage_transcript(t, 150_000)
    assert _stop(monkeypatch, capsys, t) is None  # still the same band
    _usage_transcript(t, 161_000)
    assert "161k" in _stop(monkeypatch, capsys, t)
    _usage_transcript(t, 30_000)  # compacted
    assert _stop(monkeypatch, capsys, t) is None
    _usage_transcript(t, 121_000)
    assert "121k" in _stop(monkeypatch, capsys, t)


def test_size_notice_reads_past_large_records_and_can_be_switched_off(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(context, "TAIL_CHUNK", 64)
    t = tmp_path / "s.jsonl"
    _usage_transcript(t, 130_000)
    write_jsonl(t, [{"type": "api-request-blob", "sessionId": SID, "blob": "z" * 5000}])
    assert context.context_tokens(t) == 130_000

    assert _stop(monkeypatch, capsys, t) is None  # off with the briefing
    context.main(["on"])
    context.main(["warn", "off"])
    capsys.readouterr()
    assert _stop(monkeypatch, capsys, t) is None
    context.main(["warn", "100"])
    capsys.readouterr()
    assert "130k" in _stop(monkeypatch, capsys, t)
