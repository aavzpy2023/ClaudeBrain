import json
import pathlib

from brain import mcp_launch, mcp_setup
from brain.ingest import ingest

from conftest import SID, rec, session_records, write_jsonl


def test_config_merge_keeps_other_servers_and_is_reversible():
    config = {"mcpServers": {"other": {"command": "x"}}, "globalShortcut": "Ctrl+Space"}
    entry = mcp_setup.server_entry()
    on = mcp_setup.with_server(json.loads(json.dumps(config)), entry)
    assert on["mcpServers"] == {"other": {"command": "x"}, "claude-brain": entry}
    assert mcp_setup.with_server(json.loads(json.dumps(on)), entry) == on  # idempotent
    assert mcp_setup.without_server(on) == config


def test_entry_points_at_stable_launcher():
    entry = mcp_setup.server_entry()
    assert pathlib.Path(entry["command"]).is_file()
    assert entry["args"] == [mcp_setup.launcher_path().as_posix()]
    assert mcp_setup.server_entry(no_redact=True)["args"][-1] == "--no-redact"


def test_enable_disable_desktop_config(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(mcp_setup.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))

    mcp_setup.enable()
    config = json.loads(path.read_text())
    assert set(config["mcpServers"]) == {"other", "claude-brain"} and config["theme"] == "dark"
    assert mcp_setup.launcher_path().read_text() == mcp_setup.LAUNCHER_SOURCE.read_text()
    assert (mcp_setup.state_dir() / "root").read_text().strip() == str(mcp_setup.REPO)
    assert path.with_name(path.name + ".bak-claudebrain").is_file()

    mcp_setup.disable()
    assert json.loads(path.read_text()) == {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
    mcp_setup.disable()
    assert "nothing to do" in capsys.readouterr().out


def test_desktop_config_path_per_os(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_setup.platform, "system", lambda: "Darwin")
    assert mcp_setup.desktop_config_path().parts[-4:] == ("Library", "Application Support", "Claude",
                                                          "claude_desktop_config.json")
    monkeypatch.setattr(mcp_setup.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert mcp_setup.desktop_config_path() == tmp_path / "Claude" / "claude_desktop_config.json"


def test_record_root_refreshes_an_installed_launcher_only():
    mcp_setup.record_root()
    assert not mcp_setup.launcher_path().exists()  # never installs it unasked
    mcp_setup.launcher_path().write_text("old launcher")
    mcp_setup.record_root()
    assert mcp_setup.launcher_path().read_text() == mcp_setup.LAUNCHER_SOURCE.read_text()


def test_launcher_command(tmp_path):
    cmd = mcp_launch.command(tmp_path, "/bin/uv", ["--no-redact"])
    assert cmd[:4] == ["/bin/uv", "run", "--quiet", "--no-project"]
    assert "mcp>=2.3,<3" in cmd and cmd[-2:] == [str(tmp_path / "brain" / "mcp_server.py"), "--no-redact"]


def test_server_answers_locally_with_redaction(root, tmp_path, monkeypatch):
    from brain import db, mcp_server

    records = session_records() + [rec("k1", "user", [{"type": "text", "text":
        "token ghp_" + "A1b2" * 9}], "2026-10-01T10:00:09Z")]
    write_jsonl(root / "p" / f"{SID}.jsonl", records)
    ingest(db.connect(), root)

    assert "mlvsgnn" in mcp_server.projects()
    hits = mcp_server.search("token")
    assert "[REDACTED:github-token]" in hits and "ghp_" not in hits
    assert "GNN training" in mcp_server.project("gnn")
    assert "Entrena el modelo" in mcp_server.session(SID[:8])
    assert mcp_server.session("nope").startswith("error:")
    assert "1 shell command(s)" in mcp_server.blame("train.py", "gnn")  # `python train.py`
    assert "1 session across 1 project" in mcp_server.stats()
