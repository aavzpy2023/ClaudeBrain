"""Push the local brain to Neon Postgres, redacting secrets. Safe to run offline (no-op).

Usage: uv run brain/sync.py [--init] [--reader-password] [--quiet]
       python3 brain/sync.py --claude-ai [--project-id ID]   (no database access, no psycopg)
Reads NEON_URL (and NEON_PROJECT_ID) from the environment or ~/.config/claude-brain/.env.
"""
import argparse
import os
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import connect, relabel_sessions

ENV_FILE = Path.home() / ".config" / "claude-brain" / ".env"
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "remote" / "schema.sql"
INSTRUCTIONS_FILE = SCHEMA_FILE.with_name("claude_ai_instructions.md")
PSYCOPG = "psycopg[binary]>=3.2"
BATCH = 2000

_SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED:private-key]"),
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{20,}"), "[REDACTED:api-key]"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
     "[REDACTED:github-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws-key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED:google-key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED:slack-token]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED:jwt]"),
    # Credentials embedded in URLs: keep scheme and user, drop the password.
    (re.compile(r"\b([a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s]+@", re.I), r"\1[REDACTED]@"),
    (re.compile(r"(?i)\b((?:password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*)[\"']?[^\s\"',]{8,}"),
     r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


def env_value(key: str, env_file: Path | None = None) -> str | None:
    """A setting from the environment, else from the .env file (KEY=value, quotes optional)."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        content = (env_file or ENV_FILE).read_text()  # looked up per call, so tests can redirect it
    except OSError:
        return None
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*[\"']?([^\"'\s]+)", content, re.M)
    return match[1] if match else None


def neon_url(env_file: Path | None = None) -> str | None:
    return env_value("NEON_URL", env_file)


def find_uv() -> str | None:
    """uv on PATH, else where its installers put it (hooks may run with a minimal PATH)."""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "uv", Path.home() / ".cargo" / "bin" / "uv"):
        if candidate.is_file():
            return str(candidate)
    return None


def uv_command(uv: str, *args: str) -> list[str]:
    """Run this script with psycopg supplied by uv, without creating a venv inside the repo
    (a plugin's install folder is replaced on every update)."""
    return [uv, "run", "--quiet", "--no-project", "--with", PSYCOPG, str(Path(__file__).resolve()), *args]


def claude_ai_instructions(project_id: str) -> str:
    """The connector URL + project instructions for claude.ai, filled with the user's project."""
    return INSTRUCTIONS_FILE.read_text().replace("{{NEON_PROJECT_ID}}", project_id)


def set_reader_password(remote) -> None:
    """Give brain_reader a random password: the Neon connector logs in as that role. Never shown;
    Neon hands it to the connector itself. Re-running rotates it (reconnect the connector)."""
    from psycopg import sql

    remote.execute(sql.SQL("ALTER ROLE brain_reader WITH LOGIN PASSWORD {}").format(
        sql.Literal(secrets.token_urlsafe(32))))
    remote.commit()


def _watermark(local: sqlite3.Connection, key: str) -> int:
    row = local.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else 0


def _set_watermark(local: sqlite3.Connection, key: str, value: int) -> None:
    local.execute("INSERT OR REPLACE INTO sync_state(key, value) VALUES (?, ?)", (key, value))
    local.commit()


def push_messages(local: sqlite3.Connection, remote) -> int:
    """Append-only: messages never change, so a rowid watermark is enough."""
    sent = 0
    while True:
        last = _watermark(local, "messages")
        rows = local.execute(
            """SELECT rowid, uuid, session_id, ts, role, entrypoint, cwd, is_sidechain, text
               FROM messages WHERE rowid > ? ORDER BY rowid LIMIT ?""",
            (last, BATCH),
        ).fetchall()
        if not rows:
            return sent
        with remote.cursor() as cur:
            cur.executemany(
                """INSERT INTO messages (uuid, session_id, ts, role, entrypoint, cwd, is_sidechain, text)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (uuid) DO NOTHING""",
                [(*r[1:8], redact(r[8])) for r in rows],
            )
        remote.commit()
        _set_watermark(local, "messages", rows[-1][0])
        sent += len(rows)


def push_sessions(local: sqlite3.Connection, remote) -> None:
    """Sessions mutate (titles, stats, alias relabels); upsert all, only rewriting changed rows."""
    rows = local.execute(
        """SELECT session_id, project, project_cwd, entrypoint, git_branch, title,
                  first_ts, last_ts, msg_count, repo FROM sessions"""
    ).fetchall()
    with remote.cursor() as cur:
        cur.executemany(
            """INSERT INTO sessions AS s (session_id, project, project_cwd, entrypoint, git_branch,
                                          title, first_ts, last_ts, msg_count, repo)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (session_id) DO UPDATE SET
                 project = excluded.project, project_cwd = excluded.project_cwd,
                 entrypoint = excluded.entrypoint, git_branch = excluded.git_branch,
                 title = excluded.title, first_ts = excluded.first_ts,
                 last_ts = excluded.last_ts, msg_count = excluded.msg_count, repo = excluded.repo
               WHERE (s.project, s.title, s.last_ts, s.msg_count, s.repo)
                     IS DISTINCT FROM (excluded.project, excluded.title, excluded.last_ts,
                                       excluded.msg_count, excluded.repo)""",
            [tuple(r) for r in rows],
        )
    remote.commit()


def push_digests(local: sqlite3.Connection, remote) -> int:
    host = socket.gethostname()
    last = _watermark(local, "digests")
    rows = local.execute(
        "SELECT id, scope, key, covers_until_ts, content, created_at FROM digests WHERE id > ? ORDER BY id",
        (last,),
    ).fetchall()
    if rows:
        with remote.cursor() as cur:
            cur.executemany(
                """INSERT INTO digests (origin, scope, key, covers_until_ts, content, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (origin) DO NOTHING""",
                [(f"{host}:{r[0]}", *r[1:4], redact(r[4]), r[5]) for r in rows],
            )
        remote.commit()
        _set_watermark(local, "digests", rows[-1][0])
    return len(rows)


def merge_aliases(local: dict, remote: dict) -> tuple[dict, dict]:
    """Last write wins per folder. Inputs map folder -> (project, updated_at); returns the rows
    each side is missing or has older: (to_local, to_remote)."""
    to_local = {f: v for f, v in remote.items() if f not in local or v[1] > local[f][1]}
    to_remote = {f: v for f, v in local.items() if f not in remote or v[1] > remote[f][1]}
    return to_local, to_remote


def sync_aliases(local: sqlite3.Connection, remote) -> int:
    """Share folder aliases between machines; returns local sessions relabelled."""
    import psycopg

    try:
        remote_rows = {r[0]: (r[1], r[2]) for r in remote.execute(
            "SELECT folder, project, updated_at FROM aliases")}
    except psycopg.errors.UndefinedTable:
        remote.rollback()  # mirror predates aliases; `sync.py --init` adds the table
        return 0
    local_rows = {r[0]: (r[1], r[2]) for r in local.execute(
        "SELECT folder, project, updated_at FROM folder_aliases")}
    to_local, to_remote = merge_aliases(local_rows, remote_rows)

    if to_remote:
        with remote.cursor() as cur:
            cur.executemany(
                """INSERT INTO aliases (folder, project, updated_at) VALUES (%s, %s, %s)
                   ON CONFLICT (folder) DO UPDATE SET project = excluded.project,
                     updated_at = excluded.updated_at
                   WHERE excluded.updated_at > aliases.updated_at""",
                [(f, *v) for f, v in to_remote.items()],
            )
        remote.commit()
    if not to_local:
        return 0
    local.executemany(
        "INSERT OR REPLACE INTO folder_aliases (folder, project, updated_at) VALUES (?, ?, ?)",
        [(f, *v) for f, v in to_local.items()],
    )
    return relabel_sessions(local)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--init", action="store_true", help="create/upgrade the remote schema first")
    parser.add_argument("--reader-password", action="store_true",
                        help="set a random password on brain_reader (needed once by the connector)")
    parser.add_argument("--claude-ai", action="store_true",
                        help="print the claude.ai connector setup for your Neon project and exit")
    parser.add_argument("--project-id", help="Neon project id (default: NEON_PROJECT_ID)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.claude_ai:
        project_id = args.project_id or env_value("NEON_PROJECT_ID")
        if not project_id:
            sys.exit(f"error: pass --project-id or set NEON_PROJECT_ID (env or {ENV_FILE}); "
                     "it's in the Neon console, Settings → General")
        print(claude_ai_instructions(project_id))
        return

    url = neon_url()
    if not url:
        sys.exit(f"error: NEON_URL not set (env or {ENV_FILE})")

    import psycopg  # only the sync needs it; ingest/query stay stdlib-only

    started = time.monotonic()
    try:
        remote = psycopg.connect(url, connect_timeout=10)
    except psycopg.OperationalError as exc:
        # Offline is normal: the watermarks stay put and the next run catches up.
        if not args.quiet:
            print(f"offline, skipping sync: {exc}".splitlines()[0])
        return

    local = connect()
    with remote:
        if args.init:
            remote.execute(SCHEMA_FILE.read_text())
            remote.commit()
        if args.reader_password:
            set_reader_password(remote)
            if not args.quiet:
                print("brain_reader has a new password (not shown); reconnect the claude.ai connector "
                      "if it was already set up")
        sync_aliases(local, remote)  # before sessions, so relabelled projects go up in this run
        sent = push_messages(local, remote)
        push_sessions(local, remote)
        digests = push_digests(local, remote)
    local.close()
    if not args.quiet:
        print(f"synced {sent} message(s), {digests} digest(s) in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
