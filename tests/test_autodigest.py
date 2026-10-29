import os
import stat

import pytest

from brain import autodigest
from brain.ingest import ingest
from brain.query import latest_digest, save_digest

from conftest import SID, rec, session_records, write_jsonl

PROJECT = "mlvsgnn"


@pytest.fixture(autouse=True)
def default_db_is_the_conn_fixture_db(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_BRAIN_DB", str(tmp_path / "brain.db"))  # run() opens connect() itself


def _tool(uuid, name, ts, **inp):
    return rec(uuid, "assistant", [{"type": "tool_use", "name": name, "input": inp}], ts)


def _archive(conn, root, extra=()):
    write_jsonl(root / "p" / f"{SID}.jsonl", [*session_records(), *extra])
    ingest(conn, root)


def _fake_claude(tmp_path, body):
    path = tmp_path / "fake-claude"
    path.write_text(f"#!/bin/sh\ncat >/dev/null\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_read_only_session_is_not_due(conn, root):
    _archive(conn, root)  # only a Bash call and a few messages
    assert not autodigest.due(conn, PROJECT)


def test_one_edit_makes_it_due(conn, root):
    _archive(conn, root, [_tool("e1", "Edit", "2026-10-01T10:01:00Z", file_path="a.py")])
    assert autodigest.due(conn, PROJECT)


def test_git_commit_counts_as_work(conn, root):
    _archive(conn, root, [_tool("g1", "Bash", "2026-10-01T10:01:00Z", command="git commit -m x")])
    assert autodigest.due(conn, PROJECT)


def test_long_conversation_without_edits_is_due(conn, root):
    talk = [rec(f"x{i}", "user" if i % 2 else "assistant", [{"type": "text", "text": f"msg {i}"}],
                f"2026-10-01T11:{i:02d}:00Z") for i in range(autodigest.MIN_PROSE)]
    _archive(conn, root, talk)
    assert autodigest.due(conn, PROJECT)


def test_recent_digest_blocks_even_with_new_edits(conn, root):
    _archive(conn, root, [_tool("e1", "Edit", "2026-10-01T10:01:00Z", file_path="a.py")])
    save_digest(conn, "project", PROJECT, "old", covers_until_ts="2026-10-01T10:00:00Z")
    assert not autodigest.due(conn, PROJECT)  # created just now: inside MIN_INTERVAL


def test_activity_before_the_digest_does_not_count(conn, root):
    _archive(conn, root, [_tool("e1", "Edit", "2026-10-01T10:01:00Z", file_path="a.py")])
    save_digest(conn, "project", PROJECT, "old")  # covers everything archived
    conn.execute("UPDATE digests SET created_at = '2020-01-01T00:00:00.000Z'")
    assert not autodigest.due(conn, PROJECT)


def test_build_prompt_keeps_newest_and_reports_cover_ts(conn, root, monkeypatch):
    monkeypatch.setattr(autodigest, "MAX_PROMPT_CHARS", 200)
    big = rec("b1", "assistant", [{"type": "text", "text": "old " * 500}], "2026-10-01T12:00:00Z")
    last = rec("b2", "assistant", [{"type": "text", "text": "NEWEST decision"}], "2026-10-01T12:00:01Z")
    _archive(conn, root, [big, last])
    rows = autodigest.new_activity(conn, PROJECT, "")
    prompt, covers = autodigest.build_prompt(PROJECT, "prev digest", rows)
    assert "NEWEST decision" in prompt and "prev digest" in prompt
    assert covers == "2026-10-01T12:00:01Z"


def test_run_stores_marked_digest_and_releases_lock(conn, root, tmp_path):
    _archive(conn, root, [_tool("e1", "Edit", "2026-10-01T10:01:00Z", file_path="a.py")])
    claude = _fake_claude(tmp_path, "echo 'Goal: train GNN.'")
    assert autodigest.run(PROJECT, claude)
    digest = latest_digest(conn, "project", PROJECT)
    assert digest["content"] == "[auto] Goal: train GNN."
    assert digest["covers_until_ts"] == "2026-10-01T10:01:00Z"
    assert not autodigest._lock_path().exists()


def test_failed_model_call_stores_nothing(conn, root, tmp_path):
    _archive(conn, root, [_tool("e1", "Edit", "2026-10-01T10:01:00Z", file_path="a.py")])
    assert not autodigest.run(PROJECT, _fake_claude(tmp_path, "exit 1"))
    assert not autodigest.run(PROJECT, _fake_claude(tmp_path, "true"))  # empty output
    assert latest_digest(conn, "project", PROJECT) is None


def test_held_lock_skips_the_run(conn, root, tmp_path):
    _archive(conn, root, [_tool("e1", "Edit", "2026-10-01T10:01:00Z", file_path="a.py")])
    assert autodigest._take_lock()
    assert not autodigest.run(PROJECT, _fake_claude(tmp_path, "echo hi"))
    assert latest_digest(conn, "project", PROJECT) is None


def test_maybe_spawn_respects_guard_and_spawns_when_due(conn, root, monkeypatch):
    _archive(conn, root, [_tool("e1", "Edit", "2026-10-01T10:01:00Z", file_path="a.py")])
    spawned = []
    monkeypatch.setattr(autodigest.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    autodigest.maybe_spawn(conn, None)  # conftest sets the guard
    assert spawned == []
    monkeypatch.delenv(autodigest.ENV_GUARD)
    autodigest.maybe_spawn(conn, None)
    assert spawned and spawned[0][-2:] == ["brain.autodigest", PROJECT]
