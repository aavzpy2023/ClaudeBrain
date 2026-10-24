"""Turn ClaudeBrain's MCP server on or off in MCP clients (`claude-brain mcp ...`).

Off by default. `enable` adds one entry, "claude-brain", to the client's config (merging, with a
backup) pointing at a stable launcher next to the database; `disable` removes only that entry.
Claude Desktop is configured automatically; `snippet` prints the entry for any other client.
"""
import json
import os
import platform
import shutil
import sys
from pathlib import Path

from brain.db import db_path

SERVER_NAME = "claude-brain"
REPO = Path(__file__).resolve().parent.parent
LAUNCHER_SOURCE = REPO / "brain" / "mcp_launch.py"


def state_dir() -> Path:
    return db_path().parent


def launcher_path() -> Path:
    return state_dir() / "mcp-launch.py"


def record_root() -> None:
    """Remember where this ClaudeBrain lives (a plugin's folder changes on every update) and keep
    an installed launcher current. Called by the hooks; cheap when nothing changed."""
    state_dir().mkdir(parents=True, exist_ok=True)
    marker = state_dir() / "root"
    if not marker.is_file() or marker.read_text().strip() != str(REPO):
        marker.write_text(str(REPO) + "\n")
    launcher = launcher_path()
    if launcher.is_file() and launcher.read_text() != LAUNCHER_SOURCE.read_text():
        shutil.copyfile(LAUNCHER_SOURCE, launcher)


def desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Claude" / "claude_desktop_config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "Claude" / "claude_desktop_config.json"


def launcher_python() -> str:
    """The launcher needs only a stdlib python3. Prefer the system one: a version manager's
    interpreter (pyenv, conda) can disappear and silently break the client's config."""
    system = Path("/usr/bin/python3")
    if os.name != "nt" and system.is_file():
        return system.as_posix()
    return Path(sys.executable).as_posix()


def server_entry(no_redact: bool = False) -> dict:
    args = [launcher_path().as_posix()] + (["--no-redact"] if no_redact else [])
    return {"command": launcher_python(), "args": args}


def with_server(config: dict, entry: dict) -> dict:
    config.setdefault("mcpServers", {})[SERVER_NAME] = entry
    return config


def without_server(config: dict) -> dict:
    config.get("mcpServers", {}).pop(SERVER_NAME, None)
    return config


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() and path.read_text().strip() else {}


def _save(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copy2(path, path.with_name(path.name + ".bak-claudebrain"))
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def install_launcher() -> None:
    record_root()
    shutil.copyfile(LAUNCHER_SOURCE, launcher_path())


def enable(no_redact: bool = False) -> None:
    install_launcher()
    path = desktop_config_path()
    _save(path, with_server(_load(path), server_entry(no_redact)))
    print(f"enabled in Claude Desktop ({path}). Restart Claude Desktop to load it.")
    print("Each conversation there now carries the tool definitions (~1k tokens); results go to the "
          "model provider" + ("" if no_redact else " with secrets redacted") + ".")
    print("Turn it off any time: claude-brain mcp disable")


def disable() -> None:
    path = desktop_config_path()
    if SERVER_NAME in _load(path).get("mcpServers", {}):
        _save(path, without_server(_load(path)))
        print(f"disabled in Claude Desktop ({path}). Restart Claude Desktop.")
    else:
        print("not enabled in Claude Desktop; nothing to do")


def status() -> None:
    entry = _load(desktop_config_path()).get("mcpServers", {}).get(SERVER_NAME)
    print(f"Claude Desktop  {'on' if entry else 'off'}  ({desktop_config_path()})")
    if entry and "--no-redact" in entry.get("args", []):
        print("                secrets NOT redacted")
    marker = state_dir() / "root"
    print(f"launcher        {launcher_path() if launcher_path().is_file() else 'not installed'}")
    print(f"ClaudeBrain at  {marker.read_text().strip() if marker.is_file() else REPO}")


def snippet(no_redact: bool = False) -> None:
    install_launcher()
    entry = server_entry(no_redact)
    print("# JSON clients (Claude Desktop, Cursor ~/.cursor/mcp.json, Gemini CLI ~/.gemini/settings.json, …):")
    print(json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2))
    print("\n# Codex (~/.codex/config.toml):")
    print(f"[mcp_servers.{SERVER_NAME}]")
    print(f"command = {json.dumps(entry['command'])}")
    print(f"args = {json.dumps(entry['args'])}")


def main(argv: list[str]) -> None:
    action, rest = (argv[0], argv[1:]) if argv else ("status", [])
    no_redact = "--no-redact" in rest
    actions = {"enable": lambda: enable(no_redact), "disable": disable, "status": status,
               "snippet": lambda: snippet(no_redact)}
    if action not in actions:
        sys.exit("usage: claude-brain mcp enable [--no-redact] | disable | status | snippet [--no-redact]")
    actions[action]()
