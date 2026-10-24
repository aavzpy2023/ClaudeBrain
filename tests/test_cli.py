import subprocess
import sys

from brain import cli
from brain.install import REPO


def test_usage_and_unknown_command(capsys):
    cli.main([])
    assert "claude-brain <command>" in capsys.readouterr().out
    try:
        cli.main(["frobnicate"])
    except SystemExit as exc:
        assert "unknown command" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_cloud_without_neon_url_explains(monkeypatch, tmp_path):
    monkeypatch.delenv("NEON_URL", raising=False)
    monkeypatch.setattr("brain.sync.ENV_FILE", tmp_path / "missing.env")
    try:
        cli.cloud(["init"])
    except SystemExit as exc:
        assert "NEON_URL" in str(exc) and "never paste" in str(exc)


def test_cloud_instructions_render_project_id(capsys):
    cli.main(["cloud", "instructions", "--project-id", "my-proj-42"])
    out = capsys.readouterr().out
    assert "projectId=my-proj-42&roleName=brain_reader" in out and "{{" not in out


def test_bin_wrapper_runs(tmp_path):
    env = {"CLAUDE_BRAIN_DB": str(tmp_path / "b.db"), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    out = subprocess.run([sys.executable, str(REPO / "bin" / "claude-brain"), "projects"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr


def test_connection_string_is_found_in_what_neon_lets_you_copy():
    from brain.cli import connection_string

    url = "postgresql://owner:pw@ep-x.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert connection_string(url) == url
    assert connection_string(f"  '{url}'\n") == url
    assert connection_string(f"psql '{url}'") == url
    assert connection_string("hunter2") is None


def test_connect_refuses_without_a_terminal_and_writes_nothing(monkeypatch, tmp_path):
    import io

    import pytest

    from brain import cli, sync

    monkeypatch.setattr("sys.stdin", io.StringIO("postgresql://u:p@h/db\n"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["cloud", "connect"])
    assert "own terminal" in str(exc.value) and "cloud connect" in str(exc.value)
    assert not sync.ENV_FILE.exists()


def test_datasette_metadata_matches_the_schema_and_the_db_name(monkeypatch, tmp_path):
    from brain.db import connect

    db = tmp_path / "my-archive.db"
    monkeypatch.setenv("CLAUDE_BRAIN_DB", str(db))
    tables = {r[0] for r in connect().execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    cmd, meta = cli.datasette_command("/usr/bin/uv", port=8123)
    assert set(meta["databases"]) == {"my-archive"}  # Datasette names a database after its file
    assert set(meta["databases"]["my-archive"]["tables"]) <= tables
    assert cmd[:6] == ["/usr/bin/uv", "tool", "run", "--from", cli.DATASETTE, "datasette"]
    assert str(db) in cmd and cmd[-2:] == ["--port", "8123"]
    assert (tmp_path / "datasette.json").is_file()


def test_browse_needs_a_terminal(monkeypatch):
    import io

    import pytest

    monkeypatch.setattr("brain.sync.find_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr("sys.stdout", io.StringIO())
    with pytest.raises(SystemExit, match="own"):
        cli.main(["browse"])
