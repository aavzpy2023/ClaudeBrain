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
