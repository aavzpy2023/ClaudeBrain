from brain import hook

from conftest import SID, session_records, write_jsonl


def test_hook_ingests_and_never_raises(tmp_path, monkeypatch, root):
    monkeypatch.setenv("CLAUDE_BRAIN_DB", str(tmp_path / "brain.db"))
    monkeypatch.setenv("NEON_URL", "postgresql://u:p@127.0.0.1:9/none")  # fake: sync path, no network
    monkeypatch.setattr(hook, "DEFAULT_ROOT", root)
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())

    hook.main(["--sync", "--uv", str(tmp_path / "no-such-uv")])  # sync failure must be swallowed

    from brain.db import connect
    assert connect().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 6
    assert "no-such-uv" in (tmp_path / "ingest.log").read_text()


def test_hook_is_local_only_without_neon(tmp_path, monkeypatch, root):
    monkeypatch.setenv("CLAUDE_BRAIN_DB", str(tmp_path / "brain.db"))
    monkeypatch.setattr(hook, "DEFAULT_ROOT", root)
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    hook.main(["--sync", "--uv", str(tmp_path / "no-such-uv")])
    assert (tmp_path / "ingest.log").read_text() == ""  # never tried to sync
