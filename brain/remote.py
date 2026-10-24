"""Read commands answered from the Neon mirror: every device's sessions, not just this one's.

Run by brain/query.py through uv (psycopg) when the cloud is on; same arguments and output as
the local commands, plus the host each session lives on. Exits with query.REMOTE_OFFLINE when
Neon can't be reached, so the caller falls back to the local archive.
"""
import socket
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.rows import dict_row

from brain import query, utf8_output
from brain.query import DEFAULT_ROLES, mark_after_digest, match_project, take_within
from brain.sync import direct_url, neon_url

_SESSION_COLS = "session_id, project, project_cwd, entrypoint, title, first_ts, last_ts, msg_count, repo, host"


def resolve_project(conn, name: str) -> str:
    names = [r["project"] for r in conn.execute(
        "SELECT DISTINCT project FROM sessions WHERE project IS NOT NULL")]
    return match_project(name, names)


def resolve_session(conn, prefix: str) -> str:
    rows = conn.execute("SELECT session_id FROM sessions WHERE session_id LIKE %s LIMIT 2",
                        (prefix + "%",)).fetchall()
    if len(rows) != 1:
        raise LookupError(f"session prefix {prefix!r} matched {len(rows) or 'no'} sessions")
    return rows[0]["session_id"]


def search(conn, q, project=None, source=None, since=None, limit=20, sidechain=False, raw=False,
           roles=DEFAULT_ROLES) -> list[dict]:
    # brain_tsquery parses the same syntax as the local fts_query; `raw` (FTS5 syntax) has no
    # Postgres equivalent and is treated as plain search syntax.
    sql = """SELECT m.session_id, m.ts, m.role, m.entrypoint, s.project, s.title, s.host,
                    ts_headline('simple', brain_unaccent(m.text), q.tq,
                                'StartSel=[, StopSel=], MaxWords=24, MinWords=8, MaxFragments=1') AS snippet
             FROM messages m JOIN sessions s USING (session_id), (SELECT brain_tsquery(%s) AS tq) q
             WHERE m.tsv @@ q.tq AND m.role = ANY(%s)"""
    params: list = [q, list(roles)]
    if project:
        sql += " AND s.project = %s"
        params.append(resolve_project(conn, project))
    if source:
        sql += " AND m.entrypoint = %s"
        params.append(source)
    if since:
        sql += " AND m.ts >= %s"
        params.append(since)
    if not sidechain:
        sql += " AND m.is_sidechain = 0"
    sql += " ORDER BY ts_rank(m.tsv, q.tq) DESC LIMIT %s"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def recent(conn, project=None, limit=10) -> list[dict]:
    sql = f"SELECT {_SESSION_COLS} FROM sessions WHERE msg_count > 0"
    params: list = []
    if project:
        sql += " AND project = %s"
        params.append(resolve_project(conn, project))
    sql += " ORDER BY last_ts DESC LIMIT %s"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def session(conn, session_id, after=None, roles=DEFAULT_ROLES, sidechain=False, max_chars=40000) -> dict:
    session_id = resolve_session(conn, session_id)
    meta = conn.execute(f"SELECT {_SESSION_COLS} FROM sessions WHERE session_id = %s",
                        (session_id,)).fetchone()
    sql = "SELECT ts, role, text FROM messages WHERE session_id = %s AND role = ANY(%s)"
    params: list = [session_id, list(roles)]
    if after:
        sql += " AND ts > %s"
        params.append(after)
    if not sidechain:
        sql += " AND is_sidechain = 0"
    sql += " ORDER BY ts, uuid"
    messages, truncated = take_within(conn.execute(sql, params), max_chars)
    return {"session": meta, "messages": messages, "truncated": truncated}


def file_mentions(conn, project: str, needles: list[str]) -> list[dict]:
    match = " OR ".join("strpos(m.text, %s) > 0" for _ in needles)
    return conn.execute(
        f"""SELECT m.session_id, m.ts, m.role, m.text FROM messages m JOIN sessions s USING (session_id)
            WHERE s.project = %s AND ({match}) ORDER BY m.ts""", (project, *needles)).fetchall()


def sessions_meta(conn, ids: list[str]) -> list[dict]:
    return conn.execute(f"SELECT {_SESSION_COLS} FROM sessions WHERE session_id = ANY(%s)", (ids,)).fetchall()


def user_prompts(conn, ids: list[str]) -> list[dict]:
    return conn.execute(
        """SELECT session_id, ts, substr(text, 1, 400) AS text FROM messages
           WHERE role = 'user' AND is_sidechain = 0 AND session_id = ANY(%s) ORDER BY ts""",
        (ids,)).fetchall()


def stats_data(conn, project=None, since=None) -> dict:
    where, params = ["m.is_sidechain = 0", "m.ts IS NOT NULL"], []
    if project:
        where.append("s.project = %s")
        params.append(project)
    if since:
        where.append("m.ts >= %s")
        params.append(since)
    scope = "FROM messages m JOIN sessions s USING (session_id) WHERE " + " AND ".join(where)
    hours = conn.execute(
        f"""SELECT substr(m.ts, 1, 13) AS hour, m.role, s.project, m.entrypoint, COUNT(*) AS n,
                   SUM(length(m.text) - length(replace(m.text, ' ', '')) + 1) AS words
            {scope} GROUP BY 1, 2, 3, 4""", params).fetchall()
    tools = conn.execute(
        f"""SELECT substr(m.text, 7, strpos(m.text, ']') - 7) AS name, COUNT(*) AS n
            {scope} AND m.text LIKE '[tool:%%' GROUP BY 1""", params).fetchall()
    sessions = conn.execute(
        f"""SELECT {_SESSION_COLS} FROM sessions
            WHERE (%s::text IS NULL OR project = %s) AND (%s::text IS NULL OR last_ts >= %s)""",
        (project, project, since, since)).fetchall()
    return {"hours": hours, "tools": tools, "sessions": sessions}


def projects(conn) -> list[dict]:
    return conn.execute(
        """SELECT project, COUNT(*) AS sessions, SUM(msg_count) AS messages, MAX(last_ts) AS last_ts,
                  string_agg(DISTINCT project_cwd, ',') AS folders,
                  string_agg(DISTINCT coalesce(host, '?'), ',') AS hosts
           FROM sessions WHERE msg_count > 0 AND project IS NOT NULL
           GROUP BY project ORDER BY MAX(last_ts) DESC""").fetchall()


def latest_digest(conn, scope: str, key: str) -> dict | None:
    return conn.execute(
        """SELECT * FROM digests WHERE scope = %s AND key = %s
           ORDER BY created_at DESC LIMIT 1""", (scope, key)).fetchone()


def project(conn, name: str, since=None) -> dict:
    key = resolve_project(conn, name)
    digest = latest_digest(conn, "project", key)
    sql = f"SELECT {_SESSION_COLS} FROM sessions WHERE project = %s AND msg_count > 0"
    params: list = [key]
    if since:
        sql += " AND last_ts >= %s"
        params.append(since)
    sql += " ORDER BY first_ts"
    return {"project": key, "digest": digest,
            "sessions": mark_after_digest(conn.execute(sql, params).fetchall(), digest)}


def main(argv=None) -> None:
    utf8_output()  # run by uv as its own process, printing straight to the caller's console
    args = query.build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    url = neon_url()
    try:
        conn = psycopg.connect(direct_url(url), connect_timeout=5, row_factory=dict_row) if url else None
    except psycopg.OperationalError:
        conn = None
    if conn is None:
        sys.exit(query.REMOTE_OFFLINE)
    conn.read_only = True  # owner credentials, but this path only ever reads
    with conn:
        print(f"[all devices, via Neon · this machine: {socket.gethostname()}]\n")
        try:
            query._run(conn, args, api=sys.modules[__name__])
        except LookupError as exc:
            sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
