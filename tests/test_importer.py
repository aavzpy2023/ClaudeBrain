import json
import zipfile

from brain import query
from brain.db import set_alias
from brain.importer import import_export, inspect, iso, load_export, message_text

PROJECTS = [{"uuid": "p-1", "name": "PhD Thesis", "docs": [{"filename": "x.pdf", "content": "…"}]}]
CONVERSATIONS = [
    {
        "uuid": "c-1", "name": "Marco teórico", "project_uuid": "p-1",
        "created_at": "2026-08-01T10:00:00.000000+00:00",
        "chat_messages": [
            {"uuid": "m-1", "sender": "human", "created_at": "2026-08-01T10:00:00Z",
             "text": "ignored when content exists",
             "content": [{"type": "text", "text": "¿Cómo estructuro el marco teórico?"}],
             "attachments": [{"file_name": "notas.txt", "extracted_content": "regresión logística " * 40}],
             "files": [{"file_name": "fig1.png"}]},
            {"uuid": "m-2", "sender": "assistant", "created_at": "2026-08-01T10:00:05.5-03:00",
             "content": [{"type": "thinking", "thinking": "secret"},
                         {"type": "text", "text": "Propongo tres secciones."},
                         {"type": "tool_use", "name": "web_search", "input": {"query": "dengue"}}]},
        ],
    },
    {
        "uuid": "c-2", "name": "", "created_at": "2026-08-02T09:00:00Z",
        "chat_messages": [
            {"uuid": "m-3", "sender": "human", "created_at": "2026-08-02T09:00:00Z",
             "text": "Receta de pan sin gluten", "content": []},
            {"sender": "assistant", "created_at": "2026-08-02T09:00:10Z", "text": "Claro: harina de arroz…"},
            {"uuid": "m-x", "sender": "system", "text": "dropped"},
        ],
    },
]


def write_zip(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("data-2026/conversations.json", json.dumps(CONVERSATIONS))
        zf.writestr("data-2026/projects.json", json.dumps(PROJECTS))
        zf.writestr("data-2026/users.json", "[]")
    return path


def test_message_text_blocks_attachments_and_fallback():
    text = message_text(CONVERSATIONS[0]["chat_messages"][0])
    assert text.startswith("¿Cómo estructuro el marco teórico?")
    assert "ignored when content exists" not in text
    assert "[attachment:notas.txt] regresión logística" in text and "[file:fig1.png]" in text
    reply = message_text(CONVERSATIONS[0]["chat_messages"][1])
    assert "secret" not in reply and '[tool:web_search] {"query": "dengue"}' in reply
    assert message_text(CONVERSATIONS[1]["chat_messages"][0]) == "Receta de pan sin gluten"


def test_iso_normalizes_offsets():
    assert iso("2026-08-01T10:00:05.5-03:00") == "2026-08-01T13:00:05.500Z"
    assert iso("2026-08-01T10:00:00Z") == "2026-08-01T10:00:00.000Z"
    assert iso(None) is None


def test_import_from_zip_maps_projects_and_is_idempotent(conn, tmp_path):
    conversations, projects = load_export(write_zip(tmp_path / "export.zip"))
    stats = import_export(conn, conversations, projects)
    assert stats == {"conversations": 2, "in_projects": 1, "messages": 4}

    sessions = {r["session_id"]: dict(r) for r in conn.execute("SELECT * FROM sessions")}
    assert sessions["c-1"]["project"] == "phdthesis" and sessions["c-1"]["entrypoint"] == "claude-ai"
    assert sessions["c-2"]["project"] == "claudeai"
    assert sessions["c-2"]["title"] == "Receta de pan sin gluten"  # no name → first user message
    assert sessions["c-1"]["msg_count"] == 2 and sessions["c-1"]["last_ts"] == "2026-08-01T13:00:05.500Z"

    assert import_export(conn, conversations, projects)["messages"] == 0
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 4


def test_imported_chats_are_searchable_and_follow_aliases(conn, tmp_path):
    import_export(conn, *load_export(write_zip(tmp_path / "export.zip")))
    hits = query.search(conn, "regresion logistica", source="claude-ai")
    assert [h["session_id"] for h in hits] == ["c-1"]

    set_alias(conn, "PhD Thesis", "tesis-doctoral")
    assert conn.execute("SELECT project FROM sessions WHERE session_id='c-1'").fetchone()[0] == "tesisdoctoral"


def test_load_export_from_folder_and_bare_json(tmp_path):
    (tmp_path / "conversations.json").write_text(json.dumps(CONVERSATIONS))
    assert load_export(tmp_path) == (CONVERSATIONS, [])
    (tmp_path / "projects.json").write_text(json.dumps(PROJECTS))
    assert load_export(tmp_path / "conversations.json") == (CONVERSATIONS, PROJECTS)


def test_inspect_reports_structure(capsys):
    inspect(CONVERSATIONS, PROJECTS)
    out = capsys.readouterr().out
    assert "2 conversations, 5 messages, 1 projects" in out
    assert "conversations linked to a project: 1" in out and "PhD Thesis" in out
