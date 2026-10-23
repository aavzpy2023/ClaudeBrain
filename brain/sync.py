"""Push the local brain to Neon Postgres, redacting secrets. Safe to run offline (no-op).

Usage: uv run brain/sync.py [--init] [--quiet]
Reads NEON_URL from the environment or ~/.config/claude-brain/.env.
"""
import argparse
import os
import re
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


def neon_url(env_file: Path = ENV_FILE) -> str | None:
    if os.environ.get("NEON_URL"):
        return os.environ["NEON_URL"]
    try:
        content = env_file.read_text()
    except OSError:
        return None
    match = re.search(r"^\s*NEON_URL\s*=\s*[\"']?([^\"'\s]+)", content, re.M)
    return match[1] if match else None


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
                  first_ts, last_ts, msg_count FROM sessions"""
    ).fetchall()
    with remote.cursor() as cur:
        cur.executemany(
            """INSERT INTO sessions AS s (session_id, project, project_cwd, entrypoint, git_branch,
                                          title, first_ts, last_ts, msg_count)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (session_id) DO UPDATE SET
                 project = excluded.project, project_cwd = excluded.project_cwd,
                 entrypoint = excluded.entrypoint, git_branch = excluded.git_branch,
                 title = excluded.title, first_ts = excluded.first_ts,
                 last_ts = excluded.last_ts, msg_count = excluded.msg_count
               WHERE (s.project, s.title, s.last_ts, s.msg_count)
                     IS DISTINCT FROM (excluded.project, excluded.title, excluded.last_ts, excluded.msg_count)""",
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
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

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
        sync_aliases(local, remote)  # before sessions, so relabelled projects go up in this run
        sent = push_messages(local, remote)
        push_sessions(local, remote)
        digests = push_digests(local, remote)
    local.close()
    if not args.quiet:
        print(f"synced {sent} message(s), {digests} digest(s) in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
