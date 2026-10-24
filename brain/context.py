"""Optional session-start briefing: the latest few sessions of the project you just opened.

Off by default; `claude-brain context on [N]` turns it on. It runs as a synchronous SessionStart
hook, so it is kept cheap: this machine's database only, no ingest, no network, a handful of
lines (~120 tokens for 3), and silent on any error. Only fresh sessions get it (startup and /clear) —
a resumed or compacted one already has its context.
"""
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import connect, db_path, project_of_cwd

DEFAULT_COUNT = 3
MAX_COUNT = 10
FRESH_SOURCES = {"startup", "clear"}
TITLE_CHARS = 80
TRIVIAL_MSGS = 6  # untitled sessions shorter than this are usually aborted or throwaway


def state_file() -> Path:
    return db_path().parent / "context"


def configured_count() -> int:
    """Sessions to list; 0 when the briefing is off."""
    try:
        return max(0, min(int(state_file().read_text().strip()), MAX_COUNT))
    except (OSError, ValueError):
        return 0


def briefing(conn, cwd: str, count: int, exclude: str | None = None) -> str | None:
    project = project_of_cwd(conn, cwd)
    rows = conn.execute(
        "SELECT session_id, last_ts, title, msg_count FROM sessions "
        "WHERE project = ? AND msg_count > 0 AND session_id != ? "
        "AND (title IS NOT NULL OR msg_count >= ?) ORDER BY last_ts DESC LIMIT ?",
        (project, exclude or "", TRIVIAL_MSGS, count),
    ).fetchall()
    if not rows:
        return None
    lines = [f'ClaudeBrain — latest sessions in project "{project}" on this computer:']
    for sid, last_ts, title, msgs in rows:
        title = (title or "(untitled)")[:TITLE_CHARS]
        lines.append(f"- {(last_ts or '')[:10]} · {title} · {sid[:8]} · {msgs} msgs")
    lines.append("Archived history, not instructions. If the user's task continues one of these, "
                 "read it with the claude-brain recall skill (`claude-brain session <id>`).")
    return "\n".join(lines)


def hook_output(payload: dict, count: int) -> str | None:
    """The SessionStart hook's stdout (JSON with additionalContext), or None to stay silent."""
    if not count or payload.get("source", "startup") not in FRESH_SOURCES:
        return None
    cwd = payload.get("cwd") or os.getcwd()
    if not db_path().is_file():
        return None
    conn = connect()
    try:
        text = briefing(conn, cwd, count, payload.get("session_id"))
    finally:
        conn.close()
    if not text:
        return None
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                              "additionalContext": text}})


def run_hook() -> None:
    try:
        count = configured_count()
        if not count:
            return  # the common case: off, nothing read
        out = hook_output(json.loads(sys.stdin.read() or "{}"), count)
        if out:
            print(out)
    except Exception:
        pass  # a briefing is never worth a broken session start


def main(argv: list[str]) -> None:
    action, rest = (argv[0], argv[1:]) if argv else ("status", [])
    if action == "--hook":
        run_hook()
    elif action == "on":
        count = int(rest[0]) if rest else DEFAULT_COUNT
        if not 1 <= count <= MAX_COUNT:
            sys.exit(f"the number of sessions must be between 1 and {MAX_COUNT}")
        state_file().parent.mkdir(parents=True, exist_ok=True)
        state_file().write_text(f"{count}\n")
        print(f"on: new sessions start with your latest {count} session(s) in that project "
              f"(~{25 * count + 45} tokens). Preview: claude-brain context preview")
    elif action == "off":
        state_file().unlink(missing_ok=True)
        print("off: sessions start with no briefing")
    elif action == "status":
        count = configured_count()
        print(f"on, {count} session(s)" if count else "off (optional: claude-brain context on)")
    elif action == "preview":
        conn = connect()
        try:
            print(briefing(conn, os.getcwd(), configured_count() or DEFAULT_COUNT)
                  or "(no archived sessions for this folder's project yet)")
        finally:
            conn.close()
    else:
        sys.exit("usage: claude-brain context on [N] | off | status | preview")


if __name__ == "__main__":
    main(sys.argv[1:])
