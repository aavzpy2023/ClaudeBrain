import pytest

from brain import query
from brain.ingest import ingest

from conftest import CWD2, SID, SID2, rec, session_records, write_jsonl


@pytest.fixture
def loaded(conn, root):
    write_jsonl(root / "a" / f"{SID}.jsonl", session_records())
    write_jsonl(root / "b" / f"{SID2}.jsonl", [
        rec("v1", "user", [{"type": "text", "text": "Revisa la regresion logistica"}],
            "2026-10-05T08:00:00Z", sid=SID2, cwd=CWD2, entry="claude-vscode"),
        rec("v2", "assistant", [{"type": "text", "text": "Hecho, AUC 0.88"}],
            "2026-10-05T08:01:00Z", sid=SID2, cwd=CWD2, entry="claude-vscode"),
    ])
    ingest(conn, root)
    return conn


def test_search_ignores_accents_and_syntax(loaded):
    hits = query.search(loaded, "regresion")
    assert {h["session_id"] for h in hits} == {SID, SID2}
    assert query.search(loaded, "regresión logística")[0]["session_id"] == SID2
    assert query.search(loaded, 'GraphSAGE"; -- (x') == []  # no FTS syntax error
    assert "[GraphSAGE]" in query.search(loaded, "graphsage")[0]["snippet"]


def test_search_filters(loaded):
    assert {h["session_id"] for h in query.search(loaded, "regresion", source="claude-vscode")} == {SID2}
    assert {h["session_id"] for h in query.search(loaded, "regresion", since="2026-10-03")} == {SID2}
    assert not query.search(loaded, "python train")  # tool calls hidden by default
    tools = query.DEFAULT_ROLES + ("tool",)
    assert query.search(loaded, "python train", project="gnn", roles=tools)  # partial project name


def test_folders_with_same_name_form_one_project(loaded):
    (p,) = query.projects(loaded)
    assert p["project"] == "mlvsgnn" and p["sessions"] == 2


def test_session_transcript_and_truncation(loaded):
    out = query.session(loaded, SID[:8])
    assert [m["role"] for m in out["messages"]] == ["user", "assistant", "summary", "summary"]
    assert "tool" in [m["role"] for m in query.session(loaded, SID, roles=query.DEFAULT_ROLES + ("tool",))["messages"]]
    assert not out["truncated"]

    out = query.session(loaded, SID, max_chars=5)
    assert out["truncated"] and len(out["messages"]) == 1
    nxt = query.session(loaded, SID, after=out["messages"][0]["ts"], max_chars=5)
    assert nxt["messages"][0]["ts"] > out["messages"][0]["ts"]


def test_digest_roundtrip_marks_newer_sessions(loaded):
    d = query.save_digest(loaded, "project", "mlvsgnn", "Usamos GraphSAGE.", "2026-10-02T00:00:00Z")
    out = query.project(loaded, "gnn")
    assert out["digest"]["id"] == d["id"]
    flags = {s["session_id"]: s["after_digest"] for s in out["sessions"]}
    assert flags == {SID: False, SID2: True}

    d2 = query.save_digest(loaded, "project", "mlvsgnn", "Todo cubierto.")
    assert d2["covers_until_ts"] == "2026-10-05T08:01:00Z"
    assert not any(s["after_digest"] for s in query.project(loaded, "mlvsgnn")["sessions"])


def test_alias_relabels_and_applies_to_new_ingests(loaded, root):
    assert query.alias(loaded, "/home/u/Dropbox/PhD", "thesis") == 1
    assert {p["project"] for p in query.projects(loaded)} == {"mlvsgnn", "thesis"}
    assert [s["session_id"] for s in query.recent(loaded, project="thesis")] == [SID2]


def test_ambiguous_or_missing_project(loaded):
    query.alias(loaded, "/home/u/Dropbox/PhD", "gnnthesis")
    with pytest.raises(LookupError, match="ambiguous"):
        query.resolve_project(loaded, "gnn")
    with pytest.raises(LookupError, match="no project"):
        query.resolve_project(loaded, "nothing")


def test_fts_query_syntax():
    q = query.fts_query
    assert q("regresiones") == q("regresión") == q("regresion") == '"regres"*'
    assert q("descargar") == q("descarga") == '"descarg"*'
    assert q("rendimiento OR performance OR lento") == '("rendimient"* OR "performanc"* OR "lent"*)'
    assert q('"Paper Downloader" -flask') == '"paper downloader" NOT "flask"*'
    assert q("papers.sqlite") == '"papers sqlit"*'
    assert q("de datos") == '"de" AND "dato"*'  # short words match exactly
    assert q("OR -") == "" and q("") == ""


def test_variants_and_alternatives_find_more(loaded):
    # 'regresión' in one session, 'regresion' in another: both reached from the plural form
    assert {h["session_id"] for h in query.search(loaded, "regresiones")} == {SID, SID2}
    assert {h["session_id"] for h in query.search(loaded, "GraphSAGE OR AUC")} == {SID, SID2}
    # exclusions apply per message: the only 'logistica' message also says 'revisa'
    assert query.search(loaded, "logistica") and query.search(loaded, "logistica -revisa") == []
    assert query.search(loaded, "OR") == []


def _fake_cloud(monkeypatch, rc, calls):
    monkeypatch.setenv("NEON_URL", "postgresql://u:p@h/db")
    monkeypatch.setattr("brain.sync.find_uv", lambda: "/fake/uv")
    monkeypatch.setattr("brain.query.subprocess.call", lambda cmd: calls.append(cmd) or rc)


def test_read_commands_go_to_neon_when_cloud_is_on(monkeypatch, capsys, conn):
    calls = []
    _fake_cloud(monkeypatch, 0, calls)
    query.main(["projects"])
    assert calls and calls[0][-2:] == [str(query.Path(query.__file__).with_name("remote.py")), "projects"]
    assert capsys.readouterr().out == ""  # remote printed it; nothing local


def test_offline_falls_back_to_local_with_a_note(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CLAUDE_BRAIN_DB", str(tmp_path / "b.db"))
    calls = []
    _fake_cloud(monkeypatch, query.REMOTE_OFFLINE, calls)
    query.main(["recent"])
    assert "Neon unreachable" in capsys.readouterr().out and calls


def test_local_flag_and_writes_never_go_remote(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_BRAIN_DB", str(tmp_path / "b.db"))
    calls = []
    _fake_cloud(monkeypatch, 0, calls)
    query.main(["projects", "--local"])
    query.main(["alias"])
    assert calls == []


def test_host_shown_only_for_remote_rows():
    row = {"session_id": "abcdef123", "first_ts": "2026-10-01T10:00", "last_ts": "2026-10-01T11:00",
           "entrypoint": "cli", "msg_count": 3, "title": "t"}
    assert "@" not in query._session_line(row)
    assert query._session_line({**row, "host": "work-pc"}).endswith("@work-pc")
    assert query._session_line({**row, "host": None}).endswith("@?")
