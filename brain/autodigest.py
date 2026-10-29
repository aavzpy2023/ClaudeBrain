"""Refresh a project's digest in the background when real work has piled up since the last one."""
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from brain.db import connect, db_path
from brain.query import latest_digest, save_digest

ENV_GUARD = "CLAUDE_BRAIN_AUTODIGEST"  # set on the child so its own Stop hook cannot re-trigger us
MARK = "[auto] "
MIN_PROSE = 30  # user/assistant messages that justify a digest even with no edit
MIN_INTERVAL = 3 * 3600  # seconds between digests of one project
MAX_PROMPT_CHARS = 30000
LOCK_STALE = 900
RUN_TIMEOUT = 300
EDIT_MARKERS = ("[tool:Edit]", "[tool:Write]", "[tool:MultiEdit]", "[tool:NotebookEdit]", "git commit")

PROMPT = """You maintain the project digest for "{project}": a standalone summary a future session reads \
instead of the history. Update it with the new activity below.

Write at most 250 words (hard limit, it is cut at 3000 characters), English, plain markdown without a \
top-level title, with: goal, decisions and why (later ones supersede \
earlier ones; say so), current state, files/symbols involved (exact paths), open issues. Keep what \
is still true from the previous digest. Output only the digest.

## Previous digest
{previous}

## New activity (oldest first; [tool:*] lines are clipped tool calls)
{activity}
"""


def _since(conn: sqlite3.Connection, project: str) -> tuple[str, dict | None]:
    digest = latest_digest(conn, "project", project)
    return (digest["covers_until_ts"] or "") if digest else "", digest


def new_activity(conn: sqlite3.Connection, project: str, since: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT m.ts, m.role, m.text FROM messages m JOIN sessions s USING(session_id)
           WHERE s.project = ? AND m.is_sidechain = 0 AND m.ts > ? AND m.role != 'summary'
           ORDER BY m.ts""",
        (project, since),
    ).fetchall()


def worth_digesting(rows) -> bool:
    prose = sum(1 for r in rows if r["role"] in ("user", "assistant"))
    edited = any(marker in r["text"] for r in rows for marker in EDIT_MARKERS)
    return edited or prose >= MIN_PROSE


def due(conn: sqlite3.Connection, project: str, now: float | None = None) -> bool:
    since, digest = _since(conn, project)
    if digest:
        created = datetime.fromisoformat(digest["created_at"].replace("Z", "+00:00")).timestamp()
        if (now or time.time()) - created < MIN_INTERVAL:
            return False
    return worth_digesting(new_activity(conn, project, since))


def newest_project(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT project FROM sessions WHERE msg_count > 0 ORDER BY last_ts DESC LIMIT 1").fetchone()
    return row[0] if row else None


def build_prompt(project: str, previous: str, rows) -> tuple[str, str]:
    """Return (prompt, ts of the newest message it covers); keeps the most recent activity if too long."""
    lines = [f"[{r['role']}] {r['text']}" for r in rows]
    budget, kept = MAX_PROMPT_CHARS, []
    for line in reversed(lines):
        if budget <= 0:
            break
        kept.append(line[:budget])
        budget -= len(line)
    activity = "\n\n".join(reversed(kept))
    return PROMPT.format(project=project, previous=previous or "(none yet)", activity=activity), rows[-1]["ts"]


def _lock_path() -> Path:
    return db_path().parent / "autodigest.lock"


def _take_lock() -> bool:
    path = _lock_path()
    try:
        if time.time() - path.stat().st_mtime > LOCK_STALE:
            path.unlink()
    except OSError:
        pass
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL))
        return True
    except FileExistsError:
        return False


def run(project: str, claude: str | None = None) -> bool:
    """Generate and store the digest; return whether one was saved. Never raises on a failed model call."""
    if not _take_lock():
        return False
    conn = None
    try:
        conn = connect()
        since, digest = _since(conn, project)
        rows = new_activity(conn, project, since)
        if not rows:
            return False
        prompt, covers = build_prompt(project, digest["content"] if digest else "", rows)
        claude = claude or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
        cmd = [claude, "-p", "--no-session-persistence", "--tools", ""]
        if os.environ.get("CLAUDE_BRAIN_DIGEST_MODEL"):
            cmd += ["--model", os.environ["CLAUDE_BRAIN_DIGEST_MODEL"]]
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=RUN_TIMEOUT,
                             env={**os.environ, ENV_GUARD: "1"}, cwd=db_path().parent)
        text = out.stdout.strip()
        if out.returncode != 0 or not text:
            return False
        save_digest(conn, "project", project, MARK + text, covers_until_ts=covers)
        return True
    finally:
        if conn:
            conn.close()
        _lock_path().unlink(missing_ok=True)


def maybe_spawn(conn: sqlite3.Connection, log) -> None:
    """Called by the Stop hook after ingest: start a detached worker when the newest project is due."""
    if os.environ.get(ENV_GUARD):
        return
    project = newest_project(conn)
    if not project or not due(conn, project):
        return
    subprocess.Popen([sys.executable, "-m", "brain.autodigest", project], stdout=subprocess.DEVNULL,
                     stderr=log, start_new_session=True, cwd=Path(__file__).resolve().parent.parent)


def main(argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit("usage: python -m brain.autodigest <project>")
    run(args[0])


if __name__ == "__main__":
    main()
