"""`claude-brain`: one entry point for every ClaudeBrain command."""
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import importer, ingest, query, sync
from brain.db import connect, db_path

USAGE = """usage: claude-brain <command> [options]

Recall (local):
  search "terms" [--project P] [--since DATE] [--source S] [--limit N] [--tools]
  recent [--project P] [--limit N]
  session <id> [--after TS] [--max-chars N] [--tools]
  projects | project <name> [--since DATE]
  save-digest project|session <key> [--covers-until TS]   (content on stdin)
  alias [<folder name | git remote | path> <project>]
  export <project> | --all [--out DIR] [--since DATE] [--tools] [--no-redact]
                                  Markdown notes per session + project index (Obsidian-friendly)

Archive:
  ingest [--full]                 archive new Claude Code transcripts (the hooks do this)
  import <export> [--inspect]     import a claude.ai data export (zip, folder or json)
  status                          what is archived, pending sync, retention, cloud setup

Session briefing (optional, off by default):
  context on [N] | off            start new sessions with your latest N (default 3) sessions there
  context status | preview        show the setting / what this folder would get

MCP server (optional, off by default; for Claude Desktop and other agents, needs uv):
  mcp enable [--no-redact]        add it to Claude Desktop (restart Desktop afterwards)
  mcp disable | status            remove it / show where it is on
  mcp snippet [--no-redact]       config to paste into any other MCP client

Cloud (optional, needs NEON_URL in ~/.config/claude-brain/.env and uv):
  cloud init                      create/upgrade the Neon schema and read-only role
  cloud reader-password           give the read-only role the password the connector needs
  cloud instructions              print the claude.ai connector + project setup (NEON_PROJECT_ID)
  cloud sync | sync               push now (the Stop hook does this after every reply)

Run `claude-brain <command> --help` for a command's options."""

QUERY_COMMANDS = {"search", "recent", "session", "projects", "project", "save-digest", "alias", "export"}
CLOUD_FLAGS = {"sync": [], "init": ["--init"], "reader-password": ["--reader-password"]}


def cloud(args: list[str]) -> None:
    action, extra = (args[0], args[1:]) if args else ("sync", [])
    if action == "instructions":
        sync.main(["--claude-ai", *extra])
        return
    if action not in CLOUD_FLAGS:
        sys.exit(f"unknown cloud action {action!r}: use init, reader-password, instructions or sync")
    if not sync.neon_url():
        sys.exit(f"cloud is off: put NEON_URL=postgresql://… (your Neon owner connection string) in "
                 f"{sync.ENV_FILE}, chmod 600 — never paste it into a chat")
    uv = sync.find_uv()
    if not uv:
        sys.exit("cloud needs uv to fetch the Postgres driver: https://docs.astral.sh/uv/")
    sys.exit(subprocess.call(sync.uv_command(uv, *CLOUD_FLAGS[action], *extra)))


def _retention_days() -> int | None:
    settings = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    try:
        return json.loads(settings.read_text()).get("cleanupPeriodDays")
    except (OSError, ValueError):
        return None


def status() -> None:
    conn = connect()
    path = db_path()
    total, last = conn.execute("SELECT COUNT(*), MAX(ts) FROM messages").fetchone()
    print(f"database   {path} ({path.stat().st_size / 1e6:.1f} MB)" if path.exists() else f"database   {path}")
    print(f"messages   {total}, last {last or '—'}")
    for source, sessions in conn.execute(
        "SELECT entrypoint, COUNT(*) FROM sessions WHERE msg_count > 0 GROUP BY 1 ORDER BY 2 DESC"
    ):
        print(f"  {source or '?':<16} {sessions} sessions")
    projects = conn.execute("SELECT COUNT(DISTINCT project) FROM sessions WHERE msg_count > 0").fetchone()[0]
    aliases = conn.execute("SELECT COUNT(*) FROM folder_aliases").fetchone()[0]
    print(f"projects   {projects} ({aliases} aliases)")

    days = _retention_days()
    hint = "" if days and days >= 365 else "  ← Claude Code deletes transcripts after this; /brain:setup raises it"
    print(f"retention  cleanupPeriodDays = {days or '30 (default)'}{hint}")

    from brain import context, mcp_setup

    count = context.configured_count()
    print(f"briefing   {f'on, latest {count} session(s)' if count else 'off (optional: claude-brain context on)'}")
    mcp_on = mcp_setup.SERVER_NAME in mcp_setup._load(mcp_setup.desktop_config_path()).get("mcpServers", {})
    print(f"mcp        {'on in Claude Desktop' if mcp_on else 'off (optional: claude-brain mcp enable)'}")

    if not sync.neon_url():
        print("cloud      off (optional: /brain:cloud or `claude-brain cloud init`)")
        return
    synced = conn.execute("SELECT value FROM sync_state WHERE key = 'messages'").fetchone()
    newest = conn.execute("SELECT MAX(rowid) FROM messages").fetchone()[0] or 0
    pending = newest - (synced[0] if synced else 0)
    uv = sync.find_uv()
    print(f"cloud      on — {pending} message(s) pending upload; uv: {uv or 'MISSING, sync disabled'}; "
          f"NEON_PROJECT_ID: {sync.env_value('NEON_PROJECT_ID') or 'unset (needed for `cloud instructions`)'}")


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return
    command, rest = argv[0], argv[1:]
    if command in QUERY_COMMANDS:
        query.main(argv)
    elif command == "ingest":
        ingest.main(rest)
    elif command == "import":
        importer.main(rest)
    elif command == "status":
        status()
    elif command == "context":
        from brain import context

        context.main(rest)
    elif command == "mcp":
        from brain import mcp_setup

        mcp_setup.main(rest)
    elif command == "cloud":
        cloud(rest)
    elif command == "sync":
        cloud(["sync", *rest])
    else:
        sys.exit(f"unknown command {command!r}\n\n{USAGE}")


if __name__ == "__main__":
    main()
