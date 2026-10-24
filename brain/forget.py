"""`claude-brain forget`: remove sessions, or a leaked string, from the archive and the cloud.

A dry run unless --yes. Forgotten sessions leave a tombstone, so neither ingest (even --full)
nor import brings them back, and the next sync deletes them from Neon and from the other
computers' archives. A string is replaced by [REDACTED:manual] everywhere it appears, here and
(next sync) in Neon. Claude Code's own transcripts stay on disk — `claude --resume` keeps
working — unless --transcripts.
"""
import argparse
import shutil
import sys
from pathlib import Path

from brain.db import connect
from brain.ingest import DEFAULT_ROOT
from brain.query import resolve_project, resolve_session

REDACTED = "[REDACTED:manual]"
MIN_TEXT = 6  # shorter strings would redact ordinary words all over the archive
FULL_ID = 36


def _in(ids) -> str:
    return ",".join("?" * len(ids))


def sessions_to_forget(conn, kind: str, targets: list[str]) -> tuple[list[dict], list[str]]:
    """(sessions archived here, full ids of sessions not archived here — another computer's)."""
    if kind == "project":
        name = resolve_project(conn, targets[0])
        ids = [r[0] for r in conn.execute("SELECT session_id FROM sessions WHERE project = ?", (name,))]
        elsewhere = []
    else:
        ids, elsewhere = [], []
        for target in targets:
            try:
                ids.append(resolve_session(conn, target))
            except LookupError:
                if len(target) != FULL_ID:
                    raise LookupError(f"session {target!r} isn't archived on this computer; to forget "
                                      f"one from another computer, give its full id") from None
                elsewhere.append(target)
    rows = [dict(r) for r in conn.execute(
        f"SELECT session_id, project, title, first_ts, msg_count FROM sessions WHERE session_id IN ({_in(ids)}) "
        "ORDER BY first_ts", ids)]
    return rows, elsewhere


def forget_sessions(conn, ids, synced: bool = False) -> int:
    """Delete the sessions' messages, rows and session digests, and tombstone them. Returns the
    number of messages deleted. `synced`: the cloud already knows (tombstone pulled from it)."""
    ids = list(ids)
    if not ids:
        return 0
    deleted = conn.execute(f"DELETE FROM messages WHERE session_id IN ({_in(ids)})", ids).rowcount
    conn.execute(f"DELETE FROM sessions WHERE session_id IN ({_in(ids)})", ids)
    conn.execute(f"DELETE FROM digests WHERE scope = 'session' AND key IN ({_in(ids)})", ids)
    conn.executemany("INSERT OR IGNORE INTO forgotten (session_id, synced) VALUES (?, ?)",
                     [(i, int(synced)) for i in ids])
    conn.commit()
    return deleted


def forget_project_digests(conn, project: str) -> int:
    n = conn.execute("DELETE FROM digests WHERE scope = 'project' AND key = ?", (project,)).rowcount
    conn.execute("INSERT OR IGNORE INTO pending_remote (op, arg) VALUES ('project_digests', ?)", (project,))
    conn.commit()
    return n


def text_hits(conn, text: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT m.session_id, s.title, COUNT(*) AS n FROM messages m LEFT JOIN sessions s USING (session_id)
           WHERE instr(m.text, ?) > 0 GROUP BY m.session_id ORDER BY n DESC""", (text,))]


def redact_text(conn, text: str) -> int:
    """Replace `text` everywhere in the archive; returns messages changed. The FTS index follows
    through its update trigger."""
    n = conn.execute("UPDATE messages SET text = replace(text, ?, ?) WHERE instr(text, ?) > 0",
                     (text, REDACTED, text)).rowcount
    conn.execute("UPDATE digests SET content = replace(content, ?, ?) WHERE instr(content, ?) > 0",
                 (text, REDACTED, text))
    conn.execute("UPDATE sessions SET title = replace(title, ?, ?) WHERE instr(title, ?) > 0",
                 (text, REDACTED, text))
    conn.execute("INSERT OR IGNORE INTO pending_remote (op, arg) VALUES ('redact', ?)", (text,))
    conn.commit()
    return n


def transcripts_of(root: Path, ids) -> list[Path]:
    """Claude Code's files for these sessions: <id>.jsonl and its <id>/ folder (subagents)."""
    found = []
    for sid in ids:
        found += [p for p in root.glob(f"*/{sid}.jsonl")] + [p for p in root.glob(f"*/{sid}") if p.is_dir()]
    return found


def transcripts_containing(root: Path, text: str) -> list[Path]:
    variants = {text.encode(), text.encode("unicode_escape"), repr(text)[1:-1].encode()}
    hits = []
    for path in sorted(root.rglob("*.jsonl")):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(v in data for v in variants):
            hits.append(path)
    return hits


def _cloud_note(say) -> None:
    from brain.sync import neon_url

    if neon_url():
        say("the cloud copy is changed on the next sync (after your next reply, or `claude-brain sync`); "
            "your other computers apply it on their next sync")


def run(args, conn, root: Path = DEFAULT_ROOT, say=print) -> None:
    if args.kind == "text":
        text = " ".join(args.targets)
        if len(text) < MIN_TEXT:
            raise LookupError(f"give at least {MIN_TEXT} characters, or ordinary words would be redacted everywhere")
        hits = text_hits(conn, text)
        files = transcripts_containing(root, text)
        total = sum(h["n"] for h in hits)
        say(f"{'redacted' if args.yes else 'would redact'} it in {total} message(s) of {len(hits)} session(s):")
        for h in hits[:10]:
            say(f"  {h['session_id'][:8]}  {h['n']:>4}×  {h['title'] or '(untitled)'}")
        if args.yes:
            redact_text(conn, text)
            _cloud_note(say)
        if files:
            say(f"\nit is also in {len(files)} of Claude Code's own transcript file(s), which ClaudeBrain "
                "doesn't edit — delete them yourself if needed (that session can't be resumed then):")
            for f in files[:10]:
                say(f"  {f}")
    else:
        rows, elsewhere = sessions_to_forget(conn, args.kind, args.targets)
        files = transcripts_of(root, [r["session_id"] for r in rows]) if args.transcripts else []
        verb = "forgot" if args.yes else "would forget"
        what = f"project {rows[0]['project']} — " if args.kind == "project" and rows else ""
        say(f"{verb} {what}{len(rows)} session(s), {sum(r['msg_count'] for r in rows):,} messages:")
        for r in rows[:15]:
            say(f"  {r['session_id'][:8]}  {(r['first_ts'] or '')[:10]}  {r['msg_count']:>5} msgs  {r['title'] or '(untitled)'}")
        if len(rows) > 15:
            say(f"  … and {len(rows) - 15} more")
        for sid in elsewhere:
            say(f"  {sid[:8]}  (archived on another computer: removed from the cloud and there on sync)")
        if files:
            say(f"{'deleted' if args.yes else 'would delete'} {len(files)} Claude Code transcript file(s)/folder(s) "
                "too — those sessions can't be resumed afterwards")
        if args.yes:
            forget_sessions(conn, [r["session_id"] for r in rows] + elsewhere)
            if args.kind == "project" and rows:
                forget_project_digests(conn, rows[0]["project"])
            for f in files:
                shutil.rmtree(f) if f.is_dir() else f.unlink()
            say("they won't come back: ingest and import skip forgotten sessions")
            _cloud_note(say)
    if not args.yes:
        say("\nnothing changed yet: run the same command with --yes to do it")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="claude-brain forget", description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=["session", "project", "text"])
    parser.add_argument("targets", nargs="+",
                        help="session id(s) or prefixes | a project name | the text to redact")
    parser.add_argument("--yes", action="store_true", help="do it (default: show what would happen)")
    parser.add_argument("--transcripts", action="store_true",
                        help="sessions/projects: also delete Claude Code's transcript files")
    args = parser.parse_args(argv)
    conn = connect()
    try:
        run(args, conn)
    except LookupError as exc:
        sys.exit(f"error: {exc}")
    finally:
        conn.close()
