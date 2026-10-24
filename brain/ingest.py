"""Incrementally archive Claude Code JSONL transcripts into the brain database.

Usage: python3 brain/ingest.py [--root DIR] [--full] [--quiet]
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import connect, forgotten_ids, load_aliases, project_for, resolve_repos

DEFAULT_ROOT = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
TOOL_INPUT_CHARS = 300
TOOL_RESULT_CHARS = 200

# Injected context that is noise for recall; command tags are unwrapped instead of dropped.
_DROP_TAGS = re.compile(
    r"<(system-reminder|ide_selection|ide_opened_file|local-command-caveat|local-command-stdout)>"
    r".*?</\1>",
    re.S,
)
_UNWRAP_TAGS = re.compile(r"</?(command-name|command-message|command-args)>")
# Records whose JSON starts with a top-level "type" are bookkeeping (api blobs, snapshots...);
# skipping them before json.loads avoids parsing multi-MB base64 payloads.
_BOOKKEEPING_PREFIX = b'{"type":"'
_TITLE_PREFIXES = (b'{"type":"ai-title"', b'{"type":"custom-title"')


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def _clean_user_text(text: str) -> str:
    text = _DROP_TAGS.sub("", text)
    text = _UNWRAP_TAGS.sub("", text)
    return text.strip()


def _tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def extract(record: dict) -> tuple[str, str] | None:
    """Return (role, text) for a transcript record worth archiving, else None."""
    kind = record.get("type")
    if kind == "system":
        if record.get("subtype") == "away_summary" and record.get("content"):
            return "summary", str(record["content"]).strip()
        return None
    if kind not in ("user", "assistant") or record.get("isMeta"):
        return None

    message = record.get("message") or {}
    content = message.get("content")
    if record.get("isCompactSummary"):
        text = content if isinstance(content, str) else _tool_result_text(content)
        return ("summary", text.strip()) if text.strip() else None

    if isinstance(content, str):
        if content.lstrip().startswith("<task-notification>"):
            return None
        text = _clean_user_text(content) if kind == "user" else content.strip()
        return (kind, text) if text else None

    parts: list[str] = []
    has_prose = False
    for block in content or []:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            text = _clean_user_text(text) if kind == "user" else text.strip()
            has_prose = has_prose or bool(text)
            parts.append(text)
        elif btype == "tool_use":
            args = json.dumps(block.get("input", {}), ensure_ascii=False)
            parts.append(f"[tool:{block.get('name')}] {_clip(args, TOOL_INPUT_CHARS)}")
        elif btype == "tool_result":
            body = _clip(_tool_result_text(block.get("content")), TOOL_RESULT_CHARS)
            status = "error" if block.get("is_error") else "result"
            parts.append(f"[{status}] {body}")
    text = "\n".join(p for p in parts if p)
    # Tool-only records go under "tool" so default transcripts show just the conversation.
    return (kind if has_prose else "tool", text) if text else None


def _upsert_session(conn: sqlite3.Connection, record: dict, aliases) -> None:
    cwd = record.get("cwd")
    conn.execute(
        """INSERT INTO sessions(session_id, project, project_cwd, entrypoint, git_branch)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
             project_cwd = COALESCE(sessions.project_cwd, excluded.project_cwd),
             project     = CASE WHEN sessions.project_cwd IS NULL
                                THEN excluded.project ELSE sessions.project END,
             entrypoint  = COALESCE(sessions.entrypoint, excluded.entrypoint),
             git_branch  = COALESCE(sessions.git_branch, excluded.git_branch)""",
        (
            record["sessionId"],
            project_for(cwd, aliases) if cwd else None,
            cwd,
            record.get("entrypoint"),
            record.get("gitBranch"),
        ),
    )


def ingest_file(conn: sqlite3.Connection, path: Path, start: int, aliases, touched: set,
                forgotten: frozenset | set = frozenset()) -> int:
    """Ingest complete lines from byte offset `start`; return the new offset. Sessions in
    `forgotten` are skipped, even if they go on."""
    offset = start
    with path.open("rb") as fh:
        fh.seek(start)
        for raw in fh:
            if not raw.endswith(b"\n"):
                break  # partial line still being written; pick it up next run
            offset += len(raw)
            if raw.startswith(_BOOKKEEPING_PREFIX) and not raw.startswith(_TITLE_PREFIXES):
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            session_id = record.get("sessionId")
            if not session_id or session_id in forgotten:
                continue

            if record.get("type") in ("ai-title", "custom-title"):
                custom = record["type"] == "custom-title"
                title = record.get("customTitle" if custom else "aiTitle")
                if title:
                    # A /rename by the user wins over any later auto-generated title.
                    conn.execute(
                        """INSERT INTO sessions(session_id, title, title_is_custom) VALUES (?, ?, ?)
                           ON CONFLICT(session_id) DO UPDATE SET
                             title = excluded.title, title_is_custom = excluded.title_is_custom
                           WHERE excluded.title_is_custom = 1 OR sessions.title_is_custom = 0""",
                        (session_id, title, int(custom)),
                    )
                    touched.add(session_id)
                continue

            extracted = extract(record)
            if not extracted or not record.get("uuid"):
                continue
            role, text = extracted
            _upsert_session(conn, record, aliases)
            conn.execute(
                """INSERT OR IGNORE INTO messages
                   (uuid, session_id, ts, role, entrypoint, cwd, is_sidechain, text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["uuid"],
                    session_id,
                    record.get("timestamp"),
                    role,
                    record.get("entrypoint"),
                    record.get("cwd"),
                    1 if record.get("isSidechain") else 0,
                    text,
                ),
            )
            touched.add(session_id)
    return offset


def refresh_session_stats(conn: sqlite3.Connection, session_ids) -> None:
    conn.executemany(
        """UPDATE sessions SET
             first_ts  = (SELECT MIN(ts) FROM messages m WHERE m.session_id = sessions.session_id),
             last_ts   = (SELECT MAX(ts) FROM messages m WHERE m.session_id = sessions.session_id),
             msg_count = (SELECT COUNT(*) FROM messages m
                          WHERE m.session_id = sessions.session_id AND m.is_sidechain = 0)
           WHERE session_id = ?""",
        [(s,) for s in session_ids],
    )


def ingest(conn: sqlite3.Connection, root: Path = DEFAULT_ROOT, full: bool = False,
           paths: list[Path] | None = None) -> dict:
    """Archive what's new under `root`, or only in `paths` (a quick catch-up on given files)."""
    aliases = load_aliases(conn)
    if full:  # a full pass also retries folders that looked like non-repos (maybe absent then)
        conn.execute("UPDATE sessions SET repo_root = NULL WHERE repo_root = ''")
    known = {
        r["path"]: (r["size"], r["mtime"], r["offset"])
        for r in conn.execute("SELECT path, size, mtime, offset FROM files")
    }
    stats = {"files": 0, "sessions": 0}
    forgotten = forgotten_ids(conn)
    for path in sorted(root.rglob("*.jsonl")) if paths is None else paths:
        st = path.stat()
        size, mtime, offset = known.get(str(path), (None, None, 0))
        if full or st.st_size < offset:
            offset = 0  # rewritten or truncated file; uuids dedupe the re-read
        elif size == st.st_size and mtime == st.st_mtime:
            continue
        touched: set = set()
        new_offset = ingest_file(conn, path, offset, aliases, touched, forgotten)
        refresh_session_stats(conn, touched)
        conn.execute(
            "INSERT OR REPLACE INTO files(path, size, mtime, offset) VALUES (?, ?, ?, ?)",
            (str(path), st.st_size, st.st_mtime, new_offset),
        )
        conn.commit()  # per file, so an interrupted backfill keeps its progress
        stats["files"] += 1
        stats["sessions"] += len(touched)
    resolve_repos(conn)
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--full", action="store_true", help="re-read every file from the start")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    started = time.monotonic()
    conn = connect()
    stats = ingest(conn, args.root.expanduser(), full=args.full)
    conn.close()
    if not args.quiet:
        print(
            f"ingested {stats['files']} file(s), {stats['sessions']} session(s) "
            f"in {time.monotonic() - started:.1f}s"
        )


if __name__ == "__main__":
    main()
