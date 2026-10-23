"""Query the brain database: search, sessions, project timelines and digests.

Usage: python3 brain/query.py <command> [options]   (see --help)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import connect, load_aliases, normalize_name, project_for

DEFAULT_ROLES = ("user", "assistant", "summary")


def fts_query(text: str) -> str:
    """Quote each term so user input never trips FTS5 syntax (implicit AND between terms)."""
    terms = [t.replace('"', '""') for t in text.split()]
    return " ".join(f'"{t}"' for t in terms if t)


def search(
    conn: sqlite3.Connection,
    q: str,
    project: str | None = None,
    source: str | None = None,
    since: str | None = None,
    limit: int = 20,
    sidechain: bool = False,
    raw: bool = False,
    roles: tuple[str, ...] = DEFAULT_ROLES,
) -> list[dict]:
    sql = """
        SELECT m.session_id, m.ts, m.role, m.entrypoint, s.project, s.title,
               snippet(messages_fts, 0, '[', ']', '…', 24) AS snippet
        FROM messages_fts
        JOIN messages m ON m.rowid = messages_fts.rowid
        JOIN sessions s ON s.session_id = m.session_id
        WHERE messages_fts MATCH ? AND m.role IN ({})""".format(",".join("?" * len(roles)))
    params: list = [q if raw else fts_query(q), *roles]
    if project:
        sql += " AND s.project = ?"
        params.append(resolve_project(conn, project))
    if source:
        sql += " AND m.entrypoint = ?"
        params.append(source)
    if since:
        sql += " AND m.ts >= ?"
        params.append(since)
    if not sidechain:
        sql += " AND m.is_sidechain = 0"
    sql += " ORDER BY bm25(messages_fts) LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def recent(conn: sqlite3.Connection, project: str | None = None, limit: int = 10) -> list[dict]:
    sql = "SELECT * FROM sessions WHERE msg_count > 0"
    params: list = []
    if project:
        sql += " AND project = ?"
        params.append(resolve_project(conn, project))
    sql += " ORDER BY last_ts DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def resolve_session(conn: sqlite3.Connection, prefix: str) -> str:
    rows = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id LIKE ? LIMIT 2", (prefix + "%",)
    ).fetchall()
    if len(rows) != 1:
        raise LookupError(f"session prefix {prefix!r} matched {len(rows) or 'no'} sessions")
    return rows[0][0]


def session(
    conn: sqlite3.Connection,
    session_id: str,
    after: str | None = None,
    roles: tuple[str, ...] = DEFAULT_ROLES,
    sidechain: bool = False,
    max_chars: int = 40000,
) -> dict:
    """Condensed transcript of one session; `truncated` tells whether max_chars cut it short."""
    session_id = resolve_session(conn, session_id)
    meta = dict(conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone())
    sql = f"""SELECT ts, role, text FROM messages
              WHERE session_id = ? AND role IN ({','.join('?' * len(roles))})"""
    params: list = [session_id, *roles]
    if after:
        sql += " AND ts > ?"
        params.append(after)
    if not sidechain:
        sql += " AND is_sidechain = 0"
    sql += " ORDER BY ts, rowid"
    messages, used, truncated = [], 0, False
    for r in conn.execute(sql, params):
        m = dict(r)
        if used + len(m["text"]) > max_chars:
            truncated = True
            if messages:
                break
            m["text"] = m["text"][:max_chars] + "…"  # always advance, or --after would loop
        messages.append(m)
        used += len(m["text"])
        if truncated:
            break
    return {"session": meta, "messages": messages, "truncated": truncated}


def resolve_project(conn: sqlite3.Connection, name: str) -> str:
    """Exact project name, else a unique partial match ('gnn' -> 'mlvsgnn')."""
    key = normalize_name(name)
    names = [r[0] for r in conn.execute("SELECT DISTINCT project FROM sessions WHERE project IS NOT NULL")]
    if key in names:
        return key
    matches = sorted(n for n in names if key and key in n)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(f"no project matches {name!r}")
    raise LookupError(f"{name!r} is ambiguous: {', '.join(matches)}")


def projects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT project, COUNT(*) AS sessions, SUM(msg_count) AS messages,
                  MAX(last_ts) AS last_ts, GROUP_CONCAT(DISTINCT project_cwd) AS folders
           FROM sessions WHERE msg_count > 0 AND project IS NOT NULL
           GROUP BY project ORDER BY last_ts DESC"""
    )
    return [dict(r) for r in rows]


def latest_digest(conn: sqlite3.Connection, scope: str, key: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM digests WHERE scope = ? AND key = ? ORDER BY id DESC LIMIT 1", (scope, key)
    ).fetchone()
    return dict(row) if row else None


def project(conn: sqlite3.Connection, name: str, since: str | None = None) -> dict:
    """Timeline of a project's sessions plus its latest digest, the starting point for reports."""
    key = resolve_project(conn, name)
    digest = latest_digest(conn, "project", key)
    sql = "SELECT * FROM sessions WHERE project = ? AND msg_count > 0"
    params: list = [key]
    if since:
        sql += " AND last_ts >= ?"
        params.append(since)
    sql += " ORDER BY first_ts"
    sessions = [dict(r) for r in conn.execute(sql, params)]
    covered = digest["covers_until_ts"] if digest else None
    for s in sessions:
        s["after_digest"] = covered is None or (s["last_ts"] or "") > covered
    return {"project": key, "digest": digest, "sessions": sessions}


def save_digest(
    conn: sqlite3.Connection, scope: str, key: str, content: str, covers_until_ts: str | None = None
) -> dict:
    """Store a distilled summary; covers_until_ts defaults to the newest message it could cover."""
    if scope == "project":
        key = resolve_project(conn, key)
        default_ts = conn.execute(
            "SELECT MAX(last_ts) FROM sessions WHERE project = ?", (key,)
        ).fetchone()[0]
    else:
        key = resolve_session(conn, key)
        default_ts = conn.execute(
            "SELECT last_ts FROM sessions WHERE session_id = ?", (key,)
        ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO digests(scope, key, covers_until_ts, content) VALUES (?, ?, ?, ?)",
        (scope, key, covers_until_ts or default_ts, content.strip()),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM digests WHERE id = ?", (cur.lastrowid,)).fetchone())


def alias(conn: sqlite3.Connection, path_prefix: str, name: str) -> int:
    """Map a folder prefix to a project name and re-label existing sessions; returns rows changed."""
    path_prefix = str(Path(path_prefix).expanduser()).rstrip("/")
    conn.execute(
        "INSERT OR REPLACE INTO project_aliases(path_prefix, project) VALUES (?, ?)",
        (path_prefix, normalize_name(name)),
    )
    aliases = load_aliases(conn)
    changed = 0
    for sid, cwd, current in conn.execute(
        "SELECT session_id, project_cwd, project FROM sessions WHERE project_cwd IS NOT NULL"
    ).fetchall():
        new = project_for(cwd, aliases)
        if new != current:
            conn.execute("UPDATE sessions SET project = ? WHERE session_id = ?", (new, sid))
            changed += 1
    conn.commit()
    return changed


def _day(ts: str | None) -> str:
    return (ts or "")[:16].replace("T", " ")


def _session_line(s: dict) -> str:
    return (
        f"{s['session_id'][:8]}  {_day(s['first_ts'])} → {_day(s['last_ts'])}  "
        f"{s['entrypoint'] or '?'}  {s['msg_count']} msgs  {s['title'] or '(untitled)'}"
    )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="full-text search over messages")
    p.add_argument("query")
    p.add_argument("--project")
    p.add_argument("--source", choices=["cli", "claude-vscode", "claude-desktop"])
    p.add_argument("--since", help="ISO date, e.g. 2026-09-01")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--tools", action="store_true", help="include tool calls/results")
    p.add_argument("--sidechain", action="store_true", help="include subagent messages")
    p.add_argument("--raw", action="store_true", help="pass the query as raw FTS5 syntax")

    p = sub.add_parser("recent", help="latest sessions")
    p.add_argument("--project")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("session", help="condensed transcript of one session")
    p.add_argument("session_id", help="full id or unique prefix")
    p.add_argument("--after", help="only messages newer than this ISO timestamp")
    p.add_argument("--tools", action="store_true", help="include tool calls/results")
    p.add_argument("--sidechain", action="store_true", help="include subagent messages")
    p.add_argument("--max-chars", type=int, default=40000)

    sub.add_parser("projects", help="known projects and their activity")

    p = sub.add_parser("project", help="timeline + latest digest of a project")
    p.add_argument("name")
    p.add_argument("--since")

    p = sub.add_parser("save-digest", help="store a summary read from stdin")
    p.add_argument("scope", choices=["project", "session"])
    p.add_argument("key", help="project name or session id")
    p.add_argument("--covers-until", help="ISO timestamp the summary covers up to")

    p = sub.add_parser("alias", help="map a folder (and subfolders) to a project; no args lists")
    p.add_argument("path_prefix", nargs="?")
    p.add_argument("name", nargs="?")

    args = parser.parse_args(argv)
    conn = connect()
    try:
        _run(conn, args)
    except LookupError as exc:
        sys.exit(f"error: {exc}")
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, args) -> None:
    if args.cmd == "search":
        roles = DEFAULT_ROLES + (("tool",) if args.tools else ())
        rows = search(conn, args.query, args.project, args.source, args.since,
                      args.limit, args.sidechain, args.raw, roles)
        for r in rows:
            print(f"{_day(r['ts'])}  {r['project']}  {r['entrypoint']}  "
                  f"{r['session_id'][:8]}  {r['title'] or '(untitled)'}")
            print(f"  {r['role']}: {' '.join(r['snippet'].split())}")
        if not rows:
            print("no matches")
    elif args.cmd == "recent":
        for s in recent(conn, args.project, args.limit):
            print(f"{s['project']:<20} {_session_line(s)}")
    elif args.cmd == "session":
        roles = DEFAULT_ROLES + (("tool",) if args.tools else ())
        out = session(conn, args.session_id, args.after, roles, args.sidechain, args.max_chars)
        s = out["session"]
        print(f"# {s['title'] or '(untitled)'}\n{s['project']} · {s['project_cwd']} · {_session_line(s)}\n")
        for m in out["messages"]:
            print(f"--- {m['role']} {_day(m['ts'])}\n{m['text']}\n")
        if out["truncated"]:
            last = out["messages"][-1]["ts"] if out["messages"] else args.after
            print(f"[truncated at --max-chars; continue with --after {last}]")
    elif args.cmd == "projects":
        for p in projects(conn):
            print(f"{p['project']:<24} {p['sessions']:>4} sessions {p['messages'] or 0:>6} msgs  "
                  f"last {_day(p['last_ts'])}  {p['folders']}")
    elif args.cmd == "project":
        out = project(conn, args.name, args.since)
        print(f"# project {out['project']}")
        d = out["digest"]
        if d:
            print(f"\n## latest digest (covers until {d['covers_until_ts']}, saved {d['created_at']})\n")
            print(d["content"])
        else:
            print("\n(no digest yet)")
        print("\n## sessions (* = not covered by the digest)")
        for s in out["sessions"]:
            print(f"{'*' if s['after_digest'] else ' '} {_session_line(s)}")
    elif args.cmd == "save-digest":
        d = save_digest(conn, args.scope, args.key, sys.stdin.read(), args.covers_until)
        print(f"saved digest #{d['id']} for {d['scope']} {d['key']} (covers until {d['covers_until_ts']})")
    elif args.cmd == "alias":
        if args.path_prefix and args.name:
            n = alias(conn, args.path_prefix, args.name)
            print(f"alias set; {n} session(s) relabelled")
        else:
            for prefix, name in load_aliases(conn):
                print(f"{name:<20} {prefix}")


if __name__ == "__main__":
    main()
