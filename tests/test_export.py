from types import SimpleNamespace

from brain import export, query
from brain.ingest import ingest

from conftest import SID, rec, session_records, write_jsonl


def _args(out, **kw):
    return SimpleNamespace(project="gnn", all=False, out=str(out), since=None, tools=False,
                           no_redact=False, **kw)


def _loaded(conn, root):
    records = session_records() + [rec("k1", "user", [{"type": "text", "text":
        "usa la clave sk-ant-api03-" + "x" * 40 + " por favor"}], "2026-10-01T10:00:09Z")]
    write_jsonl(root / "p" / f"{SID}.jsonl", records)
    ingest(conn, root)
    return conn


def test_export_writes_notes_index_and_is_idempotent(conn, root, tmp_path):
    _loaded(conn, root)
    out = tmp_path / "vault"
    export.run(conn, query, _args(out))
    folder = out / "mlvsgnn"
    notes = sorted(p.name for p in folder.iterdir())
    assert notes == ["2026-10-01_gnn-training_11111111.md", "mlvsgnn.md"]

    note = (folder / notes[0]).read_text()
    assert note.startswith('---\nsession_id: "11111111-aaaa-bbbb-cccc-000000000001"\nproject: "mlvsgnn"')
    assert "### 🧑 User · 2026-10-01 10:00\n\nEntrena el modelo GNN con regresión" in note
    assert "> [!summary] Summary" in note and "secret plan" not in note
    assert "sk-ant" not in note and "[REDACTED:api-key]" in note
    assert "[tool:" not in note
    assert "[GNN training](2026-10-01_gnn-training_11111111.md)" in (folder / "mlvsgnn.md").read_text()

    (out / "mine.md").write_text("my own note")
    before = {p: p.stat().st_mtime_ns for p in folder.iterdir()}
    export.run(conn, query, _args(out))
    assert {p: p.stat().st_mtime_ns for p in folder.iterdir()} == before  # nothing rewritten
    assert (out / "mine.md").read_text() == "my own note"


def test_export_options_tools_and_no_redact(conn, root, tmp_path):
    _loaded(conn, root)
    export.run(conn, query, SimpleNamespace(project=None, all=True, out=str(tmp_path), since=None,
                                            tools=True, no_redact=True))
    note = next((tmp_path / "mlvsgnn").glob("2026-*.md")).read_text()
    assert "> 🔧" in note and "[tool:Bash]" in note
    assert "sk-ant-api03-" in note


def test_slug_handles_accents_and_symbols():
    assert export.slug("Migración PaperDownloader: Flask → FastAPI!") == "migracion-paperdownloader-flask-fastapi"
    assert export.slug("") == "untitled" and export.slug("项目 数据") == "项目-数据"
