from argparse import Namespace

from brain import forget, query
from brain.db import forgotten_ids
from brain.ingest import ingest

from conftest import SID, SID2, rec, session_records, write_jsonl

SECRET = "npg_S3cr3tPassw0rd"


def _archive(conn, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    write_jsonl(root / "q" / f"{SID2}.jsonl", [
        rec("x1", "user", f"my password is {SECRET}, connect please", "2026-10-02T09:00:00Z",
            sid=SID2, cwd="/home/u/thesis"),
        rec("x2", "assistant", "Connected to the thesis database.", "2026-10-02T09:00:05Z",
            sid=SID2, cwd="/home/u/thesis"),
    ])
    ingest(conn, root)


def _args(kind, *targets, yes=False, transcripts=False):
    return Namespace(kind=kind, targets=list(targets), yes=yes, transcripts=transcripts)


def test_dry_run_changes_nothing(conn, root):
    _archive(conn, root)
    out = []
    forget.run(_args("session", SID[:8]), conn, root, out.append)
    assert "would forget 1 session(s)" in out[0] and "--yes" in out[-1]
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
    assert not forgotten_ids(conn)


def test_forgotten_sessions_never_come_back(conn, root):
    _archive(conn, root)
    query.save_digest(conn, "session", SID, "digest of the session")
    forget.run(_args("session", SID[:8], yes=True), conn, root, lambda *_: None)

    assert forgotten_ids(conn) == {SID}
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (SID,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0
    assert not query.search(conn, "GraphSAGE")  # gone from the full-text index too

    write_jsonl(root / "p" / f"{SID}.jsonl", [rec("late", "user", "still talking", "2026-10-01T11:00:00Z")])
    ingest(conn, root, full=True)
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE session_id = ?", (SID,)).fetchone()[0] == 0
    assert (root / "p" / f"{SID}.jsonl").exists()  # Claude Code's transcript is left alone


def test_forget_project_also_drops_its_digests_and_can_delete_transcripts(conn, root):
    _archive(conn, root)
    query.save_digest(conn, "project", "thesis", "thesis summary")
    forget.run(_args("project", "thesis", yes=True, transcripts=True), conn, root, lambda *_: None)
    assert forgotten_ids(conn) == {SID2}
    assert not (root / "q" / f"{SID2}.jsonl").exists()
    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0
    assert [tuple(r) for r in conn.execute("SELECT op, arg FROM pending_remote")] == [("project_digests", "thesis")]


def test_redact_text_everywhere_and_list_transcripts(conn, root):
    _archive(conn, root)
    out = []
    forget.run(_args("text", SECRET, yes=True), conn, root, out.append)
    assert "redacted it in 1 message(s) of 1 session(s)" in out[0]
    assert any(f"{SID2}.jsonl" in line for line in out)  # still in Claude Code's own file
    text = conn.execute("SELECT text FROM messages WHERE uuid = 'x1'").fetchone()[0]
    assert SECRET not in text and forget.REDACTED in text
    assert not query.search(conn, '"S3cr3tPassw0rd"')
    assert query.search(conn, "connect please")  # the rest of the message stays searchable


def test_short_text_and_unknown_prefix_are_refused(conn, root):
    import pytest

    _archive(conn, root)
    with pytest.raises(LookupError, match="at least"):
        forget.run(_args("text", "pass"), conn, root, lambda *_: None)
    with pytest.raises(LookupError, match="full id"):
        forget.run(_args("session", "ffff"), conn, root, lambda *_: None)
    other = "99999999-aaaa-bbbb-cccc-000000000009"  # another computer's session: tombstone only
    forget.run(_args("session", other, yes=True), conn, root, lambda *_: None)
    assert other in forgotten_ids(conn)
