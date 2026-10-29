"""Push the local brain to Neon Postgres, redacting secrets. Safe to run offline (no-op).

Usage: uv run brain/sync.py [--setup | --status | --init | --reader-password] [--quiet]
       python3 brain/sync.py --claude-ai [--project-id ID]   (no database access, no psycopg)
Every run first upgrades the cloud schema if it is older than this version (never if newer).
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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import utf8_output
from brain.db import connect, relabel_sessions

ENV_FILE = Path.home() / ".config" / "claude-brain" / ".env"
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "remote" / "schema.sql"
INSTRUCTIONS_FILE = SCHEMA_FILE.with_name("claude_ai_instructions.md")
PSYCOPG = "psycopg[binary]>=3.2"
BATCH = 2000
SCHEMA_LOCK = 4862101  # pg_advisory_xact_lock key: machines upgrading at once take turns

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


def direct_url(url: str) -> str:
    """Neon's pooled endpoint (host 'ep-…-pooler.…') runs PgBouncer in transaction mode: session
    state such as SET ROLE leaks to whoever reuses the server connection next. A short-lived sync
    needs no pooling, so always connect to the direct endpoint."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if "-pooler." not in host:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.replace(host, host.replace("-pooler.", ".", 1))))


WAKE_ATTEMPTS = 3
WAKE_TIMEOUT = 8  # per address: a suspended compute usually answers within seconds of the first try
WAKE_PAUSE = 2


def failure_kind(exc: Exception) -> str:
    """Why a connection failed, in a word, so ingest.log tells a sleeping Neon from a blocked network."""
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "closed the connection" in text:
        return "closed by the server"
    if "authentication" in text:
        return "authentication"
    if "translate host" in text or "name or service" in text or "name resolution" in text:
        return "dns"
    return "refused or other"


def connect_awake(url: str, attempts: int = WAKE_ATTEMPTS, timeout: int = WAKE_TIMEOUT,
                  pause: float = WAKE_PAUSE, log=None):
    """Connect to Neon, retrying so a suspended compute has time to wake; every failure is logged with its
    kind. Raises the last psycopg.OperationalError."""
    import psycopg

    log = log or sys.stderr
    for n in range(1, attempts + 1):
        try:
            return psycopg.connect(direct_url(url), connect_timeout=timeout)
        except psycopg.OperationalError as exc:
            print(f"{_now()} neon unreachable, attempt {n}/{attempts}: {failure_kind(exc)}", file=log)
            if n == attempts:
                raise
            time.sleep(pause)


def find_uv() -> str | None:
    """uv on PATH, else where its installers put it (hooks may run with a minimal PATH)."""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "uv", Path.home() / ".cargo" / "bin" / "uv"):
        if candidate.is_file():
            return str(candidate)
    return None


def uv_script(uv: str, script: Path, *args: str) -> list[str]:
    """Run a script with psycopg supplied by uv, without creating a venv inside the repo
    (a plugin's install folder is replaced on every update)."""
    return [uv, "run", "--quiet", "--no-project", "--with", PSYCOPG, str(script), *args]


def uv_command(uv: str, *args: str) -> list[str]:
    return uv_script(uv, Path(__file__).resolve(), *args)


def claude_ai_instructions(project_id: str) -> str:
    """The connector URL + project instructions for claude.ai, filled with the user's project."""
    return INSTRUCTIONS_FILE.read_text().replace("{{NEON_PROJECT_ID}}", project_id)


def env_problems(env_file: Path | None = None) -> list[str]:
    """Why the credentials file is unsafe or unusable, as fixes to run. POSIX only: Windows
    keeps it private through the user profile's ACLs."""
    path = env_file or ENV_FILE
    if os.name == "nt" or not path.exists():
        return []
    st = path.stat()
    problems = []
    if st.st_uid != os.getuid():
        problems.append(f"{path} belongs to another user: sudo chown \"$USER\": {path}")
    if st.st_mode & 0o077:
        problems.append(f"{path} is readable by other users: chmod 600 {path}")
    return problems


def write_env(updates: dict[str, str], env_file: Path | None = None) -> Path:
    """Set keys in the .env file, keeping its other lines; created private (0600)."""
    path = env_file or ENV_FILE
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [l for l in lines if l.split("=", 1)[0].strip() not in updates]
    lines += [f"{key}={value}" for key, value in updates.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    if os.name != "nt":
        os.chmod(path, 0o600)  # O_CREAT's mode doesn't apply to an existing file
    return path


def schema_version(sql_text: str | None = None) -> int:
    """The version declared in schema.sql's header (`-- schema_version: N`)."""
    match = re.search(r"^-- schema_version: (\d+)", sql_text or SCHEMA_FILE.read_text(), re.M)
    return int(match[1]) if match else 0


def _meta(remote, key: str) -> str | None:
    row = remote.execute("SELECT value FROM brain_meta WHERE key = %s", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(remote, key: str, value: str) -> None:
    remote.execute(
        "INSERT INTO brain_meta (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", (key, value))


def remote_version(remote) -> int | None:
    """None for an empty database, 0 for a mirror from before versioning (≤0.13), else the
    recorded schema version."""
    has_meta, has_messages = remote.execute(
        "SELECT to_regclass('brain_meta') IS NOT NULL, to_regclass('messages') IS NOT NULL").fetchone()
    if has_meta:
        return int(_meta(remote, "schema_version") or 0)
    return 0 if has_messages else None


def schema_plan(local: int, found: int | None, force: bool = False) -> str:
    """'apply', 'current', or 'newer' — a newer cloud schema is never overwritten, even forced:
    a machine running an older ClaudeBrain would roll back the search functions."""
    if found is not None and found > local:
        return "newer"
    return "apply" if found is None or found < local or force else "current"


def ensure_schema(remote, force: bool = False) -> tuple[str, int | None]:
    """Bring the cloud schema up to this version if needed; returns (action, version found)."""
    local = schema_version()
    found = remote_version(remote)
    if schema_plan(local, found, force) == "apply":
        remote.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
        found = remote_version(remote)  # another machine may have upgraded it meanwhile
    action = schema_plan(local, found, force)
    if action == "apply":
        remote.execute(SCHEMA_FILE.read_text())
        _set_meta(remote, "schema_version", str(local))
        if found == 0 and _meta(remote, "reader_password") is None:
            # A pre-versioning mirror was set up by hand, its connector presumably working:
            # never let `cloud setup` rotate that password.
            _set_meta(remote, "reader_password", "assumed")
    remote.commit()
    return action, found


def reader_ready(remote) -> bool:
    return _meta(remote, "reader_password") is not None


def set_reader_password(remote) -> None:
    """Give brain_reader a random password: the Neon connector logs in as that role. Never shown;
    Neon hands it to the connector itself. Re-running rotates it (reconnect the connector)."""
    from psycopg import sql

    remote.execute(sql.SQL("ALTER ROLE brain_reader WITH LOGIN PASSWORD {}").format(
        sql.Literal(secrets.token_urlsafe(32))))
    _set_meta(remote, "reader_password", _now())
    remote.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_sync(remote) -> None:
    _set_meta(remote, f"synced:{socket.gethostname()}", _now())
    remote.commit()


def sync_forgotten(local: sqlite3.Connection, remote) -> int:
    """Apply `forget` to the cloud and pull other machines' tombstones; returns sessions
    dropped locally because another machine forgot them."""
    from brain.forget import REDACTED, forget_sessions

    pending = [r[0] for r in local.execute("SELECT session_id FROM forgotten WHERE synced = 0")]
    if pending:
        remote.execute("INSERT INTO forgotten (session_id, forgotten_at) SELECT unnest(%s::text[]), %s "
                       "ON CONFLICT DO NOTHING", (pending, _now()))
        remote.execute("DELETE FROM messages WHERE session_id = ANY(%s)", (pending,))
        remote.execute("DELETE FROM sessions WHERE session_id = ANY(%s)", (pending,))
        remote.execute("DELETE FROM digests WHERE scope = 'session' AND key = ANY(%s)", (pending,))
        remote.commit()
        local.executemany("UPDATE forgotten SET synced = 1 WHERE session_id = ?", [(i,) for i in pending])
        local.commit()
    for op, arg in local.execute("SELECT op, arg FROM pending_remote").fetchall():
        if op == "redact":
            remote.execute("UPDATE messages SET text = replace(text, %s, %s) WHERE strpos(text, %s) > 0",
                           (arg, REDACTED, arg))
            remote.execute("UPDATE digests SET content = replace(content, %s, %s) WHERE strpos(content, %s) > 0",
                           (arg, REDACTED, arg))
            remote.execute("UPDATE sessions SET title = replace(title, %s, %s) WHERE strpos(title, %s) > 0",
                           (arg, REDACTED, arg))
        elif op == "project_digests":
            remote.execute("DELETE FROM digests WHERE scope = 'project' AND key = %s", (arg,))
        remote.commit()
        local.execute("DELETE FROM pending_remote WHERE op = ? AND arg = ?", (op, arg))
        local.commit()
    known = {r[0] for r in local.execute("SELECT session_id FROM forgotten")}
    theirs = [r[0] for r in remote.execute("SELECT session_id FROM forgotten") if r[0] not in known]
    remote.commit()
    forget_sessions(local, theirs, synced=True)
    return len(theirs)


def remote_status(remote) -> list[str]:
    local, found = schema_version(), remote_version(remote)
    if found is None:
        return ["schema     none — the database is empty: run `claude-brain cloud setup`"]
    note = {"newer": "  ← update ClaudeBrain on this machine", "apply": "  ← upgraded on the next sync",
            "current": ""}[schema_plan(local, found)]
    lines = [f"schema     v{found} in Neon, v{local} here{note}"]
    messages = remote.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    lines.append(f"stored     {messages} messages")
    synced = {}
    if found == 0:
        lines.append("connector  set up before 0.14 (password not managed here)")
    else:
        reader = _meta(remote, "reader_password")
        lines.append("connector  " + {None: "no password yet: run `claude-brain cloud setup`",
                                      "assumed": "set up before 0.14 (password not managed here)"}
                     .get(reader, f"password set {reader[:10] if reader else ''}"))
        synced = {k.split(":", 1)[1]: v for k, v in remote.execute(
            "SELECT key, value FROM brain_meta WHERE key LIKE 'synced:%'")}
    for host, sessions, last in remote.execute(
            "SELECT host, COUNT(*), MAX(last_ts) FROM sessions GROUP BY host ORDER BY 3 DESC NULLS LAST"):
        when = f", last sync {synced[host][:16].replace('T', ' ')}" if host in synced else ""
        lines.append(f"  {host or '(before 0.10: no host)':<24} {sessions:>5} sessions, last activity "
                     f"{(last or '—')[:10]}{when}")
    remote.rollback()
    return lines


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
                  first_ts, last_ts, msg_count, repo, ? FROM sessions""", (socket.gethostname(),)
    ).fetchall()
    with remote.cursor() as cur:
        cur.executemany(
            """INSERT INTO sessions AS s (session_id, project, project_cwd, entrypoint, git_branch,
                                          title, first_ts, last_ts, msg_count, repo, host)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (session_id) DO UPDATE SET
                 project = excluded.project, project_cwd = excluded.project_cwd,
                 entrypoint = excluded.entrypoint, git_branch = excluded.git_branch,
                 title = excluded.title, first_ts = excluded.first_ts,
                 last_ts = excluded.last_ts, msg_count = excluded.msg_count, repo = excluded.repo,
                 host = excluded.host
               WHERE (s.project, s.title, s.last_ts, s.msg_count, s.repo, s.host)
                     IS DISTINCT FROM (excluded.project, excluded.title, excluded.last_ts,
                                       excluded.msg_count, excluded.repo, excluded.host)""",
            [tuple(r) for r in rows],
        )
    remote.commit()


def push_digests(local: sqlite3.Connection, remote) -> int:
    host = socket.gethostname()
    last = _watermark(local, "digests")
    rows = local.execute(
        "SELECT id, scope, key, covers_until_ts, content, created_at FROM digests "
        "WHERE id > ? AND origin IS NULL ORDER BY id",  # pulled digests must not go back up
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


def pull_digests(local: sqlite3.Connection, remote) -> int:
    """Bring other computers' project digests down, so every machine opens a session with the newest one.
    Their original created_at is kept (readers order by it, not by local id)."""
    since = local.execute("SELECT MAX(created_at) FROM digests WHERE origin IS NOT NULL").fetchone()[0] or ""
    with remote.cursor() as cur:
        cur.execute(
            """SELECT origin, key, covers_until_ts, content, created_at FROM digests
               WHERE scope = 'project' AND origin IS NOT NULL AND NOT starts_with(origin, %s)
               AND created_at > %s ORDER BY created_at""",
            (f"{socket.gethostname()}:", since),
        )
        rows = cur.fetchall()
    for origin, key, covers, content, created in rows:
        local.execute(
            """INSERT OR IGNORE INTO digests(scope, key, covers_until_ts, content, created_at, origin)
               VALUES ('project', ?, ?, ?, ?, ?)""",
            (key, covers, content, created, origin),
        )
    local.commit()
    return len(rows)


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
    utf8_output()  # run by uv as its own process, printing straight to the caller's console
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--setup", action="store_true",
                        help="first-time or new-machine setup: schema, connector password only if "
                             "missing, upload")
    parser.add_argument("--status", action="store_true", help="show the cloud's state, push nothing")
    parser.add_argument("--init", action="store_true",
                        help="re-apply the schema even if its version is current (repair)")
    parser.add_argument("--reader-password", action="store_true",
                        help="give brain_reader a new random password (rotates it: reconnect the "
                             "claude.ai connector afterwards)")
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
        remote = connect_awake(url)
    except psycopg.OperationalError as exc:
        # Offline is normal: the watermarks stay put and the next run catches up.
        if not args.quiet:
            print(f"offline, skipping sync: {exc}".splitlines()[0])
        return

    with remote:
        if args.status:
            print("\n".join(remote_status(remote)))
            return
        action, found = ensure_schema(remote, force=args.init)
        say = (lambda *a: None) if args.quiet else print
        if action == "apply":
            say(f"cloud schema {'created' if found is None else f'upgraded v{found} → v{schema_version()}'}")
        elif action == "newer":
            say(f"note: the cloud schema (v{found}) is newer than this ClaudeBrain's "
                f"(v{schema_version()}): update ClaudeBrain here. Syncing continues.")
        first_time = False
        if args.reader_password:
            set_reader_password(remote)
            say("brain_reader has a new password (not shown); reconnect the claude.ai connector if "
                "it was already set up")
        elif args.setup and not reader_ready(remote):
            set_reader_password(remote)
            first_time = True
            say("connector password set for the read-only role (not shown)")
        elif args.setup:
            say("read-only role already has its password — left alone, so the claude.ai connector "
                "keeps working")
        local = connect()
        sync_forgotten(local, remote)  # first, so nothing forgotten is pushed again
        sync_aliases(local, remote)  # before sessions, so relabelled projects go up in this run
        sent = push_messages(local, remote)
        push_sessions(local, remote)
        digests = push_digests(local, remote)
        pulled = pull_digests(local, remote)
        record_sync(remote)
        local.close()
    say(f"synced {sent} message(s), {digests} digest(s) up, {pulled} down in {time.monotonic() - started:.1f}s")
    if args.setup:
        say("next: `claude-brain cloud instructions` — add the connector and the project on claude.ai"
            if first_time else "claude.ai needs nothing more: its connector reads this same database")


if __name__ == "__main__":
    main()
