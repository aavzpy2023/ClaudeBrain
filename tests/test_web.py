import threading
import urllib.error
import urllib.request

import pytest

from brain import web
from brain.db import connect
from brain.ingest import ingest

from conftest import CWD, SID, rec, session_records, write_jsonl


@pytest.fixture
def db(root, tmp_path):
    write_jsonl(root / "p" / f"{SID}.jsonl", session_records() + [
        rec("x1", "user", "Is <script>alert(1)</script> escaped?", "2026-10-01T10:01:00Z"),
        rec("x2", "assistant", [{"type": "text", "text": "Yes:\n```python\nprint('<b>')\n```\nand `a<b`."}],
            "2026-10-01T10:02:00Z"),
    ])
    path = tmp_path / "brain.db"
    conn = connect(path)
    ingest(conn, root)
    conn.close()
    return path


def test_pages_render_projects_sessions_and_search(db):
    conn = web.open_readonly(db)
    index = web.index_page(conn)
    assert "GNN training" in index and "/project?name=mlvsgnn" in index
    assert "GNN training" in web.project_page(conn, "mlvsgnn")
    session = web.session_page(conn, SID[:8])
    assert "Decidimos usar GraphSAGE." in session and f"claude --resume {SID}" in session
    assert "1 tool call(s)" in session and "secret plan" not in session
    found = web.search_page(conn, "regresion")
    assert "<mark>" in found and f"/session?id={SID}#m" in found
    with pytest.raises(LookupError):
        web.project_page(conn, "nope")


def test_archived_text_is_escaped_and_code_is_formatted(db):
    page = web.session_page(web.open_readonly(db), SID)
    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<pre><code>print(&#x27;&lt;b&gt;&#x27;)</code></pre>" in page
    assert "<code>a&lt;b</code>" in page


def test_database_is_opened_read_only(db):
    conn = web.open_readonly(db)
    with pytest.raises(Exception, match="readonly"):
        conn.execute("DELETE FROM messages")


def test_server_answers_localhost_only(db):
    server = web.bind(db, 0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/search?q=GraphSAGE") as resp:
            body = resp.read().decode()
            assert resp.headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert "GNN training" in body
        evil = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.example:80"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(evil)
        assert err.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_web_refuses_without_a_terminal(db, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_BRAIN_DB", str(db))
    with pytest.raises(SystemExit, match="your own terminal"):
        web.main([])
