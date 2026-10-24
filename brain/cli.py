"""`claude-brain`: one entry point for every ClaudeBrain command."""
import getpass
import json
import os
import re
import shlex
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
  stats [--project P] [--since DATE]   your history in numbers (--since 2026-01-01: year in review)
  blame <file> [--project P] [--limit N]
                                  the sessions that edited a file, why (your request), and commits
  export <project> | --all [--out DIR] [--since DATE] [--tools] [--no-redact]
                                  Markdown notes per session + project index (Obsidian-friendly)

Archive:
  forget session <id>… | project <name> | text "<leaked string>"  [--yes] [--transcripts]
                                  remove sessions or a string here and in the cloud (dry run
                                  without --yes; forgotten sessions never come back)
  ingest [--full]                 archive new Claude Code transcripts (the hooks do this)
  import <export> [--inspect]     import a claude.ai data export (zip, folder or json)
  status                          what is archived, pending sync, retention, cloud setup
  browse [--port N]               explore it in your browser (Datasette via uv; your own terminal)

Session continuity (optional, off by default):
  context on [N] | off            briefing of your latest N (default 3) sessions there, handoff
                                  after /clear, heads-up when the context passes 120k tokens
  context warn <K> | off          set or silence that heads-up (thousands of tokens)
  context status | preview        show the setting / what this folder would get

MCP server (optional, off by default; for Claude Desktop and other agents, needs uv):
  mcp enable [--no-redact]        add it to Claude Desktop (restart Desktop afterwards)
  mcp disable | status            remove it / show where it is on
  mcp snippet [--no-redact]       config to paste into any other MCP client

Cloud (optional: your own Neon Postgres, read from claude.ai; needs uv):
  cloud connect                   save the Neon connection string (hidden prompt; your own terminal)
  cloud setup                     schema + connector password (first computer only) + upload;
                                  safe to re-run, and all a second computer needs
  cloud status                    what the cloud holds: schema version, computers, last syncs
  cloud instructions              print the claude.ai connector + project setup (NEON_PROJECT_ID)
  cloud sync | sync               push now (the Stop hook does this after every reply)
  cloud init                      re-apply the schema (repair; upgrades happen on their own)
  cloud reader-password           rotate the connector's password (reconnect it on claude.ai)

Run `claude-brain <command> --help` for a command's options."""

QUERY_COMMANDS = {"search", "recent", "session", "projects", "project", "save-digest", "alias", "export",
                  "blame", "stats"}
CLOUD_FLAGS = {"sync": [], "setup": ["--setup"], "status": ["--status"], "init": ["--init"],
               "reader-password": ["--reader-password"]}


def _self_command() -> str:
    """How to run this CLI from the user's own terminal, where the plugin's bin/ isn't on PATH.
    Windows: PowerShell can't start a command with a quoted path, so rely on `python` instead."""
    script = (Path(__file__).resolve().parent.parent / "bin" / "claude-brain").as_posix()
    if os.name == "nt":
        return f'python "{script}"'
    return f"{shlex.quote(Path(sys.executable).as_posix())} {shlex.quote(script)}"


SELF = _self_command()


def connection_string(pasted: str) -> str | None:
    """The postgresql:// URL inside whatever was pasted: bare, quoted, or Neon's `psql '…'` line."""
    match = re.search(r"postgres(?:ql)?://[^\s'\"]+", pasted)
    return match[0] if match else None


def cloud_connect() -> None:
    if not sys.stdin.isatty():
        sys.exit("`cloud connect` asks for the connection string with hidden input, so run it in your "
                 f"own terminal (never paste the string into a chat):\n  {SELF} cloud connect")
    print("Neon console → your project → Connect: copy the connection string (owner role).")
    url = connection_string(getpass.getpass("Connection string (input hidden): "))
    if not url:
        sys.exit("that isn't a postgresql:// connection string; nothing was saved")
    project_id = input("Project id (Neon → Settings → General; Enter to skip): ").strip()
    path = sync.write_env({"NEON_URL": url, **({"NEON_PROJECT_ID": project_id} if project_id else {})})
    print(f"saved to {path}, readable only by you. Next: claude-brain cloud setup")


DATASETTE = "datasette>=0.65,<1"  # 1.0 moves metadata.json to a new config format


def datasette_command(uv: str, port: int | None = None) -> tuple[list[str], dict]:
    """The `uv tool run datasette` command line for the archive, and the metadata it uses — keyed
    by the database file's name, which is what Datasette calls the database."""
    db = db_path()
    meta = json.loads((Path(__file__).resolve().parent / "datasette.json").read_text())
    meta["databases"] = {db.stem: meta["databases"]["brain"]}
    meta_file = db.parent / "datasette.json"
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    cmd = [uv, "tool", "run", "--from", DATASETTE, "datasette", "serve", str(db),
           "--metadata", str(meta_file), "--setting", "sql_time_limit_ms", "5000", "--open"]
    return cmd + (["--port", str(port)] if port else []), meta


def browse(args: list[str]) -> None:
    uv = sync.find_uv()
    if not uv:
        sys.exit("browse runs Datasette through uv: https://docs.astral.sh/uv/")
    if not sys.stdout.isatty():
        sys.exit(f"browse starts a local web server and runs until Ctrl+C — run it in your own "
                 f"terminal:\n  {SELF} browse")
    port = int(args[args.index("--port") + 1]) if "--port" in args else None
    cmd, _ = datasette_command(uv, port)
    print("ClaudeBrain in your browser (Datasette, this machine only, read-only). Ctrl+C to stop.")
    try:
        subprocess.call(cmd)
    except KeyboardInterrupt:
        pass


def cloud(args: list[str]) -> None:
    action, extra = (args[0], args[1:]) if args else ("sync", [])
    if action == "instructions":
        sync.main(["--claude-ai", *extra])
        return
    if action == "connect":
        cloud_connect()
        return
    if action not in CLOUD_FLAGS:
        sys.exit(f"unknown cloud action {action!r}: use connect, setup, status, instructions, sync, "
                 f"init or reader-password")
    for problem in sync.env_problems():
        print(f"warning: {problem}", file=sys.stderr)
    if not sync.neon_url():
        sys.exit(f"cloud is off: run `{SELF} cloud connect` in your own terminal (or put "
                 f"NEON_URL=… in {sync.ENV_FILE}, chmod 600) — never paste the string into a chat")
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

    for problem in sync.env_problems():
        print(f"cloud      ⚠ {problem}")
    if not sync.neon_url():
        print("cloud      off (optional: /brain:cloud or `claude-brain cloud connect`)")
        return
    synced = conn.execute("SELECT value FROM sync_state WHERE key = 'messages'").fetchone()
    newest = conn.execute("SELECT MAX(rowid) FROM messages").fetchone()[0] or 0
    pending = newest - (synced[0] if synced else 0)
    uv = sync.find_uv()
    print(f"cloud      on — {pending} message(s) pending upload; uv: {uv or 'MISSING, sync disabled'}; "
          f"NEON_PROJECT_ID: {sync.env_value('NEON_PROJECT_ID') or 'unset (needed for `cloud instructions`)'}; "
          f"details: claude-brain cloud status")


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
    elif command == "browse":
        browse(rest)
    elif command == "forget":
        from brain import forget

        forget.main(rest)
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
