import threading
import urllib.error
import urllib.request

import pytest

from brain import query, web
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


def _local(db):
    return web.Source("local", web.open_readonly(db), query, "?")


def test_pages_render_projects_sessions_and_search(db):
    src = _local(db)
    index = web.index_page(src)
    assert "GNN training" in index and "/project?name=mlvsgnn&amp;src=local" in index.replace("&", "&amp;") or "name=mlvsgnn" in index
    assert "GNN training" in web.project_page(src, "mlvsgnn")[1]
    session = web.session_page(src, SID[:8])[1]
    assert "Decidimos usar GraphSAGE." in session and f"claude --resume {SID}" in session
    assert "1 tool call(s)" in session and "secret plan" not in session
    found = web.search_page(src, "regresion")[1]
    assert "<mark>" in found and f"id={SID}" in found and "#m" in found
    with pytest.raises(LookupError):
        web.project_page(src, "nope")


def test_session_shows_newest_messages_first(db):
    page = web.session_page(_local(db), SID)[1]
    assert page.index("and <code>a&lt;b</code>") < page.index("Decidimos usar GraphSAGE.") < page.index("regresión")


def test_session_order_can_be_flipped(db):
    asc = web.session_page(_local(db), SID, "asc")[1]
    assert asc.index("regresión") < asc.index("Decidimos usar GraphSAGE.") < asc.index("and <code>a&lt;b</code>")
    assert "order=desc" in asc and "Oldest first" in asc
    desc = web.session_page(_local(db), SID)[1]
    assert "order=asc" in desc and "Newest first" in desc


def test_tool_calls_show_one_argument_per_line_even_when_clipped():
    out = web.render_tools(['[tool:Edit] {"file_path": "a.py", "old": "x<y"}\n[result] ok',
                            '[tool:Bash] {"command": "ls\\necho hi", "note": "abc\\'''])
    assert "<b>🔧 Edit</b>" in out and "file_path: a.py\nold: x&lt;y" in out and "↩ result" in out
    assert "<b>🔧 Bash</b>" in out and "command: ls\necho hi\nnote: abc" in out
    assert web.format_args("not json at all") == "not json at all"


def test_switch_marks_the_active_source_and_greys_out_a_missing_cloud():
    both = web.page("t", "", "cloud", cloud=True)
    assert "class='on' href='/?src=cloud'" in both and "href='/?src=local'" in both
    assert "name=src value='cloud'" in both
    local_only = web.page("t", "", "local", cloud=False)
    assert "opacity:.45" in local_only and "href='/?src=cloud'" not in local_only


def test_archived_text_is_escaped_and_code_is_formatted(db):
    page = web.session_page(_local(db), SID)[1]
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/search?q=GraphSAGE&src=cloud") as resp:
            body = resp.read().decode()
            assert resp.headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert "GNN training" in body and "href='/?src=local'" in body  # no cloud here: local answers
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


def test_unreachable_cloud_offers_the_local_archive(db, monkeypatch):
    def down():
        raise OSError("connection refused")
    monkeypatch.setattr(web, "open_cloud", down)
    server = web.bind(db, 0, cloud=True)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/?src=cloud")
        assert err.value.code == 502 and "Use the local archive" in err.value.read().decode()
    finally:
        server.shutdown()
        server.server_close()
