"""Query the brain database: search, sessions, project timelines and digests.

Usage: python3 brain/query.py <command> [options]   (see --help)
"""
import argparse
import functools
import io
import re
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import connect, load_aliases, normalize_name, set_alias

DEFAULT_ROLES = ("user", "assistant", "summary")


# Light, language-agnostic stemming for Spanish/English-style endings: strip the first suffix
# that leaves at least STEM_MIN letters, then match by prefix, so 'regresiones', 'regresión' and
# 'regression' all reach each other. Mirrored by brain_stem() in remote/schema.sql — keep in sync.
STEM_SUFFIXES = (
    "aciones", "imientos", "amientos", "iciones", "iones", "acion", "icion", "mente",
    "ando", "iendo", "ados", "adas", "idos", "idas", "ings",
    "ado", "ada", "ido", "ida", "ion", "ing", "es", "ar", "er", "ir", "ed", "s", "a", "e", "o",
)
STEM_MIN = 4
PREFIX_MIN = 3  # shorter words match exactly: 'de'* would match half the archive
_QUERY_TOKEN = re.compile(r'"[^"]*"|\S+')


def stem(word: str) -> str:
    for suffix in STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= STEM_MIN:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> list[str]:
    """Lowercase, accent-free words, split like FTS5's unicode61 tokenizer does."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", plain)


def _term(token: str) -> str | None:
    if len(token) >= 2 and token[0] == token[-1] == '"':  # "exact phrase": no stemming
        words = _words(token[1:-1])
        return f'"{" ".join(words)}"' if words else None
    words = _words(token)
    if not words:
        return None
    words[-1] = stem(words[-1])
    return f'"{" ".join(words)}"' + ("*" if len(words[-1]) >= PREFIX_MIN else "")


def fts_query(text: str) -> str:
    """Search syntax → FTS5: words are ANDed and match their variants (stem + prefix);
    `a OR b` for alternatives, "quoted" for an exact phrase, -word to exclude.
    Every term is quoted, so no input can produce an FTS5 syntax error."""
    groups: list[list[str]] = []
    excluded: list[str] = []
    join_next = False
    for token in _QUERY_TOKEN.findall(text):
        if token == "OR":
            join_next = bool(groups)
            continue
        negate = token.startswith("-") and len(token) > 1
        term = _term(token[1:] if negate else token)
        if term is None:
            continue
        if negate:
            excluded.append(term)
        elif join_next:
            groups[-1].append(term)
        else:
            groups.append([term])
        join_next = False
    if not groups:
        return ""
    expr = " AND ".join(g[0] if len(g) == 1 else "(" + " OR ".join(g) + ")" for g in groups)
    return expr + "".join(f" NOT {t}" for t in excluded)


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
    marks: tuple[str, str] = ("[", "]"),
) -> list[dict]:
    sql = """
        SELECT m.uuid, m.session_id, m.ts, m.role, m.entrypoint, s.project, s.title,
               snippet(messages_fts, 0, ?, ?, '…', 24) AS snippet
        FROM messages_fts
        JOIN messages m ON m.rowid = messages_fts.rowid
        JOIN sessions s ON s.session_id = m.session_id
        WHERE messages_fts MATCH ? AND m.role IN ({})""".format(",".join("?" * len(roles)))
    match = q if raw else fts_query(q)
    if not match:
        return []
    params: list = [*marks, match, *roles]
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
    messages, truncated = take_within(conn.execute(sql, params), max_chars)
    return {"session": meta, "messages": messages, "truncated": truncated}


def take_within(rows, max_chars: int) -> tuple[list[dict], bool]:
    """Messages until max_chars; always at least one (clipped), or paging with --after would loop."""
    messages, used, truncated = [], 0, False
    for r in rows:
        m = dict(r)
        if used + len(m["text"]) > max_chars:
            truncated = True
            if messages:
                break
            m["text"] = m["text"][:max_chars] + "…"
        messages.append(m)
        used += len(m["text"])
        if truncated:
            break
    return messages, truncated


def resolve_project(conn: sqlite3.Connection, name: str) -> str:
    names = [r[0] for r in conn.execute("SELECT DISTINCT project FROM sessions WHERE project IS NOT NULL")]
    return match_project(name, names)


def match_project(name: str, names: list[str]) -> str:
    """Exact project name, else a unique partial match ('gnn' -> 'mlvsgnn')."""
    key = normalize_name(name)
    if key in names:
        return key
    matches = sorted(n for n in names if key and key in n)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(f"no project matches {name!r}")
    raise LookupError(f"{name!r} is ambiguous: {', '.join(matches)}")


def file_mentions(conn: sqlite3.Connection, project: str, needles: list[str]) -> list[dict]:
    """Messages of a project containing any of `needles` (exact substrings), oldest first."""
    match = " OR ".join("instr(m.text, ?) > 0" for _ in needles)
    return [dict(r) for r in conn.execute(
        f"""SELECT m.session_id, m.ts, m.role, m.text FROM messages m JOIN sessions s USING (session_id)
            WHERE s.project = ? AND ({match}) ORDER BY m.ts""", (project, *needles))]


def sessions_meta(conn: sqlite3.Connection, ids: list[str]) -> list[dict]:
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM sessions WHERE session_id IN ({','.join('?' * len(ids))})", ids)]


def user_prompts(conn: sqlite3.Connection, ids: list[str]) -> list[dict]:
    """The user's own messages (no subagents) in these sessions, oldest first, clipped."""
    return [dict(r) for r in conn.execute(
        f"""SELECT session_id, ts, substr(text, 1, 400) AS text FROM messages
            WHERE role = 'user' AND is_sidechain = 0 AND session_id IN ({','.join('?' * len(ids))})
            ORDER BY ts""", ids)]


def stats_data(conn: sqlite3.Connection, project: str | None = None, since: str | None = None) -> dict:
    """Aggregates for `stats`: messages per UTC hour × role × project × source (with a word
    count), tool calls by name, and the sessions active in the range. Subagents excluded."""
    where, params = ["m.is_sidechain = 0", "m.ts IS NOT NULL"], []
    if project:
        where.append("s.project = ?")
        params.append(project)
    if since:
        where.append("m.ts >= ?")
        params.append(since)
    scope = "FROM messages m JOIN sessions s USING (session_id) WHERE " + " AND ".join(where)
    hours = conn.execute(
        f"""SELECT substr(m.ts, 1, 13) AS hour, m.role, s.project, m.entrypoint, COUNT(*) AS n,
                   SUM(length(m.text) - length(replace(m.text, ' ', '')) + 1) AS words
            {scope} GROUP BY 1, 2, 3, 4""", params)
    tools = conn.execute(
        f"""SELECT substr(m.text, 7, instr(m.text, ']') - 7) AS name, COUNT(*) AS n
            {scope} AND m.text LIKE '[tool:%' GROUP BY 1""", params)
    sessions = conn.execute(
        "SELECT * FROM sessions WHERE (? IS NULL OR project = ?) AND (? IS NULL OR last_ts >= ?)",
        (project, project, since, since))
    return {"hours": [dict(r) for r in hours], "tools": [dict(r) for r in tools],
            "sessions": [dict(r) for r in sessions]}


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
        "SELECT * FROM digests WHERE scope = ? AND key = ? ORDER BY created_at DESC, id DESC LIMIT 1", (scope, key)
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
    return {"project": key, "digest": digest, "sessions": mark_after_digest(sessions, digest)}


def mark_after_digest(sessions: list[dict], digest: dict | None) -> list[dict]:
    covered = digest["covers_until_ts"] if digest else None
    for s in sessions:
        s["after_digest"] = covered is None or (s["last_ts"] or "") > covered
    return sessions


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


def alias(conn: sqlite3.Connection, folder: str, name: str) -> int:
    """Map a folder name (a path works too: its last folder is used) to a project, on every
    machine once synced; re-labels existing sessions and returns how many changed."""
    return set_alias(conn, folder, name)


def _day(ts: str | None) -> str:
    return (ts or "")[:16].replace("T", " ")


def _host(row: dict) -> str:
    return f"  @{row.get('host') or '?'}" if "host" in row else ""


def _session_line(s: dict) -> str:
    return (
        f"{s['session_id'][:8]}  {_day(s['first_ts'])} → {_day(s['last_ts'])}  "
        f"{s['entrypoint'] or '?'}  {s['msg_count']} msgs  {s['title'] or '(untitled)'}{_host(s)}"
    )


READ_COMMANDS = {"search", "recent", "session", "projects", "project", "export", "blame", "stats"}
REMOTE_OFFLINE = 75  # exit code of brain/remote.py when Neon can't be reached


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="full-text search over messages")
    p.add_argument("query")
    p.add_argument("--project")
    p.add_argument("--source", choices=["cli", "claude-vscode", "claude-desktop", "claude-ai"])
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

    p = sub.add_parser("blame", help="the sessions that edited a file, why, and their commits")
    p.add_argument("file", help="path of the file (relative to here, or absolute)")
    p.add_argument("--project", help="default: the project of the current folder")
    p.add_argument("--limit", type=int, default=10, help="sessions to show, newest first")

    p = sub.add_parser("stats", help="your history in numbers: volume, rhythm, projects, tools")
    p.add_argument("--project")
    p.add_argument("--since", help="ISO date, e.g. 2026-01-01 for a year in review")

    p = sub.add_parser("export", help="write projects as Markdown notes (Obsidian-friendly)")
    p.add_argument("project", nargs="?", help="project name (partial ok); or --all")
    p.add_argument("--all", action="store_true", help="every project")
    p.add_argument("--out", default="brain-export", help="target folder, e.g. your Obsidian vault")
    p.add_argument("--since", help="only sessions active since this date")
    p.add_argument("--tools", action="store_true", help="include tool calls/results")
    p.add_argument("--no-redact", action="store_true", help="keep secrets (default: redacted)")

    p = sub.add_parser("save-digest", help="store a summary read from stdin")
    p.add_argument("scope", choices=["project", "session"])
    p.add_argument("key", help="project name or session id")
    p.add_argument("--covers-until", help="ISO timestamp the summary covers up to")

    p = sub.add_parser("alias", help="map a folder name or git remote to a project; no args lists")
    p.add_argument("folder", nargs="?",
                   help="folder name, git remote (any URL form), or an existing path (its name + its repo)")
    p.add_argument("name", nargs="?")

    for name in READ_COMMANDS:
        sub.choices[name].add_argument(
            "--local", action="store_true",
            help="this machine's archive only (default with the cloud on: every device, via Neon)")
    return parser


def _try_remote(argv: list[str]) -> bool:
    """With the cloud on, answer read commands from Neon (every device). True if it did; offline
    falls back to the local archive with a note."""
    from brain import sync  # local import: sync is optional plumbing, query must stay standalone

    uv = sync.find_uv() if sync.neon_url() else None
    if not uv:
        return False
    script = Path(__file__).resolve().with_name("remote.py")
    rc = subprocess.call(sync.uv_script(uv, script, *argv))
    if rc == REMOTE_OFFLINE:
        print("[Neon unreachable — showing this machine's archive only]\n")
        return False
    if rc:
        sys.exit(rc)
    return True


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv)
    if args.cmd in READ_COMMANDS and not args.local and _try_remote(argv):
        return
    conn = connect()
    try:
        _run(conn, args)
    except LookupError as exc:
        sys.exit(f"error: {exc}")
    finally:
        conn.close()


def _run(conn, args, api=None) -> None:
    sys.stdout.write(render(conn, args, api))


def render(conn, args, api=None) -> str:
    """A command's output as text. `api` supplies the read functions (this module, or brain.remote
    for Neon); both return the same shapes, so the text is identical. Shared by CLI and MCP."""
    api = api or sys.modules[__name__]
    buffer = io.StringIO()
    say = functools.partial(print, file=buffer)
    if args.cmd == "search":
        roles = DEFAULT_ROLES + (("tool",) if args.tools else ())
        rows = api.search(conn, args.query, args.project, args.source, args.since,
                          args.limit, args.sidechain, args.raw, roles)
        for r in rows:
            say(f"{_day(r['ts'])}  {r['project']}  {r['entrypoint']}  "
                  f"{r['session_id'][:8]}  {r['title'] or '(untitled)'}{_host(r)}")
            say(f"  {r['role']}: {' '.join(r['snippet'].split())}")
        if not rows:
            say("no matches")
    elif args.cmd == "recent":
        for s in api.recent(conn, args.project, args.limit):
            say(f"{s['project']:<20} {_session_line(s)}")
    elif args.cmd == "session":
        roles = DEFAULT_ROLES + (("tool",) if args.tools else ())
        out = api.session(conn, args.session_id, args.after, roles, args.sidechain, args.max_chars)
        s = out["session"]
        repo = f" · {s['repo']}" if s.get("repo") else ""
        say(f"# {s['title'] or '(untitled)'}\n{s['project']} · {s['project_cwd']}{repo} · {_session_line(s)}\n")
        for m in out["messages"]:
            say(f"--- {m['role']} {_day(m['ts'])}\n{m['text']}\n")
        if out["truncated"]:
            last = out["messages"][-1]["ts"] if out["messages"] else args.after
            say(f"[truncated at --max-chars; continue with --after {last}]")
    elif args.cmd == "projects":
        for p in api.projects(conn):
            hosts = f"  @{p['hosts']}" if p.get("hosts") else ""
            say(f"{p['project']:<24} {p['sessions']:>4} sessions {p['messages'] or 0:>6} msgs  "
                  f"last {_day(p['last_ts'])}  {p['folders']}{hosts}")
    elif args.cmd == "project":
        out = api.project(conn, args.name, args.since)
        say(f"# project {out['project']}")
        d = out["digest"]
        if d:
            say(f"\n## latest digest (covers until {d['covers_until_ts']}, saved {d['created_at']})\n")
            say(d["content"])
        else:
            say("\n(no digest yet)")
        say("\n## sessions (* = not covered by the digest)")
        for s in out["sessions"]:
            say(f"{'*' if s['after_digest'] else ' '} {_session_line(s)}")
    elif args.cmd == "blame":
        from brain import blame

        blame.run(conn, api, args, say)
    elif args.cmd == "stats":
        from brain import stats

        stats.run(conn, api, args, say)
    elif args.cmd == "export":
        from brain import export  # imports brain.sync for redaction; keep query's import light

        export.run(conn, api, args, say)
    elif args.cmd == "save-digest":
        d = save_digest(conn, args.scope, args.key, sys.stdin.read(), args.covers_until)
        say(f"saved digest #{d['id']} for {d['scope']} {d['key']} (covers until {d['covers_until_ts']})")
    elif args.cmd == "alias":
        if args.folder and args.name:
            n = alias(conn, args.folder, args.name)
            say(f"alias set; {n} session(s) relabelled")
        else:
            for folder, name in sorted(load_aliases(conn).items(), key=lambda a: a[1]):
                kind = "repo" if "/" in folder else "folder"
                say(f"{name:<26} ← {kind} {folder}")

    return buffer.getvalue()

if __name__ == "__main__":
    main()
