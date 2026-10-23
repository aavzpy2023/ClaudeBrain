from brain.db import project_for
from brain.ingest import TOOL_RESULT_CHARS, ingest

from conftest import CWD, SID, rec, session_records, write_jsonl


def _messages(conn):
    return {r["uuid"]: dict(r) for r in conn.execute("SELECT * FROM messages")}


def test_keeps_conversation_and_drops_noise(conn, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    ingest(conn, root)
    msgs = _messages(conn)

    assert set(msgs) == {"u1", "a1", "a2", "t1", "s1", "c1"}
    assert msgs["u1"]["text"] == "Entrena el modelo GNN con regresión"
    assert msgs["a2"]["text"].startswith('[tool:Bash] {"command": "python train.py"}')
    assert msgs["t1"]["role"] == msgs["a2"]["role"] == "tool"
    assert len(msgs["t1"]["text"]) <= TOOL_RESULT_CHARS + len("[result] …")
    assert msgs["s1"]["role"] == msgs["c1"]["role"] == "summary"


def test_session_metadata_and_title(conn, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    ingest(conn, root)
    s = dict(conn.execute("SELECT * FROM sessions WHERE session_id = ?", (SID,)).fetchone())

    assert s["title"] == "GNN training"
    assert s["project"] == "mlvsgnn"
    assert s["entrypoint"] == "cli"
    assert s["first_ts"] == "2026-10-01T10:00:00Z"
    assert s["last_ts"] == "2026-10-01T10:00:08Z"
    assert s["msg_count"] == 6


def test_custom_title_beats_later_ai_title(conn, root):
    records = session_records() + [
        {"type": "custom-title", "customTitle": "Mi nombre", "sessionId": SID},
        {"type": "ai-title", "aiTitle": "auto again", "sessionId": SID},
    ]
    write_jsonl(root / "p" / f"{SID}.jsonl", records)
    ingest(conn, root)
    assert conn.execute("SELECT title FROM sessions").fetchone()[0] == "Mi nombre"


def test_rerun_is_idempotent(conn, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    ingest(conn, root)
    assert ingest(conn, root)["files"] == 0  # unchanged file skipped
    ingest(conn, root, full=True)
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 6


def test_incremental_append_and_partial_line(conn, root):
    path = root / "p" / f"{SID}.jsonl"
    late = rec("a9", "assistant", [{"type": "text", "text": "late reply"}], "2026-10-02T09:00:00Z")
    import json
    line = json.dumps(late, separators=(",", ":"))
    write_jsonl(path, session_records(), partial=line[:40])
    ingest(conn, root)
    assert "a9" not in _messages(conn)

    with path.open("a") as fh:
        fh.write(line[40:] + "\n")
    ingest(conn, root)
    assert _messages(conn)["a9"]["text"] == "late reply"
    last = conn.execute("SELECT last_ts FROM sessions WHERE session_id = ?", (SID,)).fetchone()[0]
    assert last == "2026-10-02T09:00:00Z"


def test_sidechain_messages_flagged_and_not_counted(conn, root):
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    sub = rec("x1", "assistant", [{"type": "text", "text": "subagent finding"}],
              "2026-10-01T10:00:09Z", isSidechain=True)
    write_jsonl(root / "p" / SID / "subagents" / "agent-1.jsonl", [sub])
    ingest(conn, root)

    assert _messages(conn)["x1"]["is_sidechain"] == 1
    assert conn.execute("SELECT msg_count FROM sessions").fetchone()[0] == 6


def test_project_for_rules():
    assert project_for("/a/ML-vs-GNN", {}) == project_for("/b/MLvsGNN/", {}) == "mlvsgnn"
    assert project_for("/d/2026-ML vs GNN", {}) == "mlvsgnn"
    assert project_for("/d/20 ctubre 2026", {}) == "20ctubre2026"
    assert project_for("/d/2026", {}) == "2026"
    assert project_for("/a/Tésis_Doctoral", {}) == "tesisdoctoral"
    assert project_for("/tmp/tmpab12", {}) == "tmp"
    assert project_for(CWD, {}) == "mlvsgnn"


def test_aliases_match_folder_names_at_any_depth_deepest_wins():
    aliases = {"tareasasignaturas": "tareasstats", "tarea1": "estadistica"}
    assert project_for("/home/a/Dropbox/Tareas asignaturas/Sem 2/X", aliases) == "tareasstats"
    assert project_for("/home/a/Dropbox/Tareas asignaturas/Sem 2/Tarea 1/sections", aliases) == "estadistica"
    # Same folder name on another machine, different home: same project.
    assert project_for("/Users/b/Box/Tareas asignaturas", aliases) == "tareasstats"
    assert project_for("/home/a/Tareas asignaturas2", aliases) == "tareasasignaturas2"


def test_windows_paths():
    aliases = {"leaicli": "devleaicli"}
    assert project_for(r"C:\Users\Andrey\Projects\leai-cli", aliases) == "devleaicli"
    assert project_for(r"C:\Users\Andrey\Projects\leai-cli\src", aliases) == "devleaicli"
    assert project_for(r"D:\work\ML-vs-GNN", {}) == "mlvsgnn"
    assert project_for("C:\\", {}) == "root"


def test_path_aliases_from_older_versions_are_migrated(tmp_path):
    import sqlite3

    from brain.db import connect, load_aliases

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE project_aliases (path_prefix TEXT PRIMARY KEY, project TEXT NOT NULL)")
    old.execute("INSERT INTO project_aliases VALUES ('/home/u/Projects/leai-cli', 'devleaicli')")
    old.commit()
    old.close()

    assert load_aliases(connect(path)) == {"leaicli": "devleaicli"}


def test_project_names_in_any_script():
    from brain.db import normalize_name

    assert normalize_name("Tésis_Doctoral") == "tesisdoctoral"
    assert normalize_name("Übungen-Straße") == "ubungenstrasse"
    assert normalize_name("机器学习-项目") == "机器学习项目"
    assert normalize_name("Проект 2") == "проект2"
    assert normalize_name("2026-数据分析") == "数据分析"
    assert project_for("/home/李/项目/数据", {}) == "数据"
    assert project_for("/home/u/Проект", {"проект": "russian"}) == "russian"
