"""`claude-brain web`: read your conversations in the browser — projects, sessions, search.

Listens on 127.0.0.1 (this computer only), opens every database read-only and refuses requests
whose Host header isn't localhost, so another website can't read it through DNS rebinding. Every
piece of archived text is HTML-escaped. A switch picks the source per request: "local" (this
computer's SQLite, standard library only) or "cloud" (Neon, live, every computer). Cloud needs
psycopg, so with the cloud configured the server re-runs itself through uv, like remote.py.
"""
import html
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import query, utf8_output
from brain.db import db_path

DEFAULT_PORT = 8765
PORTS_TRIED = 10
RECENT = 15
RESULTS = 50
HIT_OPEN, HIT_CLOSE = "\x02", "\x03"  # snippet markers that can't occur in archived text
ROLE_LABEL = {"user": "🧑 You", "assistant": "🤖 Claude", "summary": "📝 Summary", "tool": "🔧 Tools"}

CSS = """
:root { --bg:#fbfaf8; --fg:#1d1d1f; --muted:#6b6b70; --line:#e4e2dd; --card:#fff; --you:#eef3fb;
  --accent:#c4613f; --code:#f3f1ec; --mark:#ffe08a; }
@media (prefers-color-scheme: dark) { :root { --bg:#16171b; --fg:#e8e8ea; --muted:#9a9aa2;
  --line:#2c2d33; --card:#1e1f24; --you:#1f2a3a; --accent:#e08a68; --code:#26272d; --mark:#6b5410; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.55 system-ui, sans-serif; }
main { max-width: 920px; margin: 0 auto; padding: 20px 16px 60px; }
a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
header { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:18px; }
header .home { font-weight:700; font-size:18px; color:var(--fg); }
form.search { flex:1; display:flex; gap:8px; min-width:240px; }
input[type=search] { flex:1; padding:8px 12px; border:1px solid var(--line); border-radius:8px;
  background:var(--card); color:var(--fg); font:inherit; }
button { padding:8px 14px; border:0; border-radius:8px; background:var(--accent); color:#fff; font:inherit; }
h1 { font-size:22px; margin:6px 0 4px; } h2 { font-size:16px; margin:26px 0 8px; color:var(--muted); }
.meta { color:var(--muted); font-size:13px; }
table { width:100%; border-collapse:collapse; } td, th { padding:7px 8px; border-bottom:1px solid var(--line);
  text-align:left; vertical-align:top; } th { font-size:12px; color:var(--muted); font-weight:600; }
td.n { text-align:right; white-space:nowrap; color:var(--muted); }
.msg { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin:10px 0; }
.msg.user { background:var(--you); } .msg.summary { border-left:4px solid var(--accent); }
.msg .who { font-size:12px; color:var(--muted); margin-bottom:4px; display:flex; justify-content:space-between; }
.msg .body { white-space:pre-wrap; overflow-wrap:anywhere; }
details.tool { margin:4px 0; color:var(--muted); font-size:13px; }
details.tool .body { white-space:pre-wrap; overflow-wrap:anywhere; font-family:ui-monospace, monospace; font-size:12px; }
pre { background:var(--code); padding:10px; border-radius:8px; overflow-x:auto; white-space:pre; }
code { background:var(--code); padding:1px 4px; border-radius:4px; font-family:ui-monospace, monospace; font-size:13px; }
pre code { padding:0; background:none; }
mark { background:var(--mark); color:inherit; padding:0 1px; }
.hit { padding:10px 0; border-bottom:1px solid var(--line); }
.switch { display:flex; border:1px solid var(--line); border-radius:8px; overflow:hidden; font-size:13px; }
.switch a { padding:7px 12px; color:var(--muted); background:var(--card); }
.switch a.on { background:var(--accent); color:#fff; font-weight:600; }
.switch a:hover { text-decoration:none; }
.cmd { font-family:ui-monospace, monospace; font-size:13px; background:var(--code); padding:6px 10px;
  border-radius:6px; display:inline-block; user-select:all; }
:target { outline: 2px solid var(--accent); }
"""


class Source:
    """One database the pages read from: this computer's SQLite or the Neon mirror."""

    def __init__(self, name: str, conn, api, ph: str):
        self.name, self.conn, self.api, self.ph = name, conn, api, ph

    def rows(self, sql: str, params=()) -> list:
        return self.conn.execute(sql.replace("?", self.ph), params).fetchall()

    def row(self, sql: str, params=()):
        return self.conn.execute(sql.replace("?", self.ph), params).fetchone()


def e(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def local_time(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts[:16].replace("T", " ")


def render_text(text: str) -> str:
    """Escaped text with ``` fences as code blocks and `inline code`; everything else verbatim."""
    out = []
    for i, part in enumerate(re.split(r"```", text or "")):
        if i % 2:
            body = part.split("\n", 1)[1] if "\n" in part else part  # drop the language tag
            out.append(f"<pre><code>{e(body.rstrip())}</code></pre>")
        else:
            out.append(re.sub(r"`([^`\n]+)`", r"<code>\1</code>", e(part)))
    return "".join(out)


def link(path: str, src: str, **params) -> str:
    return f"{path}?{urlencode({**params, 'src': src})}"


def page(title: str, body: str, src: str, cloud: bool, q: str = "") -> str:
    def side(name: str, label: str) -> str:
        if name == "cloud" and not cloud:
            return f"<a title='Run `claude-brain cloud connect` and install uv' style='opacity:.45'>{label}</a>"
        return f"<a class='{'on' if src == name else ''}' href='{link('/', name)}'>{label}</a>"

    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>{e(title)} · ClaudeBrain</title><style>{CSS}</style></head><body><main>"
            f"<header><a class=home href='{link('/', src)}'>🧠 ClaudeBrain</a>"
            f"<form class=search action='/search'><input type=hidden name=src value='{e(src)}'>"
            f"<input type=search name=q value='{e(q)}' placeholder='Search every conversation…' "
            f"aria-label=Search><button>Search</button></form>"
            f"<nav class=switch>{side('cloud', '☁️ Cloud')}{side('local', '💻 Local')}</nav>"
            f"</header>{body}</main></body></html>")


def _session_rows(rows, src: Source) -> str:
    def host(r) -> str:
        return f" · @{e(r['host'] or '?')}" if "host" in r.keys() else ""

    cells = "".join(
        f"<tr><td><a href='{link('/session', src.name, id=r['session_id'])}'>{e(r['title'] or '(untitled)')}</a>"
        f"<div class=meta>{e(r['session_id'][:8])} · {e(r['entrypoint'] or '?')}"
        f"{' · ' + e(r['project']) if r['project'] else ''}{host(r)}</div></td>"
        f"<td class=n>{e(local_time(r['last_ts']))}</td><td class=n>{r['msg_count']:,} msgs</td></tr>"
        for r in rows)
    return f"<table>{cells}</table>" if cells else "<p class=meta>No sessions yet.</p>"


def index_page(src: Source) -> str:
    cols = "session_id, project, entrypoint, title, last_ts, msg_count" + (", host" if src.name == "cloud" else "")
    projects = src.rows("""SELECT project, COUNT(*) AS n, SUM(msg_count) AS msgs, MAX(last_ts) AS last_ts FROM sessions
                           WHERE msg_count > 0 AND project IS NOT NULL GROUP BY project
                           ORDER BY MAX(last_ts) DESC""")
    recent = src.rows(f"SELECT {cols} FROM sessions WHERE msg_count > 0 ORDER BY last_ts DESC LIMIT ?", (RECENT,))
    rows = "".join(
        f"<tr><td><a href='{link('/project', src.name, name=p['project'])}'>{e(p['project'])}</a></td>"
        f"<td class=n>{p['n']:,} sessions</td><td class=n>{p['msgs']:,} msgs</td>"
        f"<td class=n>{e(local_time(p['last_ts']))}</td></tr>" for p in projects)
    return f"<h2>Latest sessions</h2>{_session_rows(recent, src)}<h2>Projects</h2><table>{rows}</table>"


def project_page(src: Source, name: str) -> tuple[str, str]:
    cols = "session_id, project, entrypoint, title, last_ts, msg_count" + (", host" if src.name == "cloud" else "")
    rows = src.rows(f"SELECT {cols} FROM sessions WHERE project = ? AND msg_count > 0 ORDER BY last_ts DESC", (name,))
    if not rows:
        raise LookupError(f"no project {name!r}")
    total = sum(r["msg_count"] for r in rows)
    return name, (f"<h1>{e(name)}</h1><p class=meta>{len(rows):,} sessions · {total:,} messages</p>"
                  f"{_session_rows(rows, src)}")


def session_page(src: Source, prefix: str) -> tuple[str, str]:
    sid = src.api.resolve_session(src.conn, prefix)
    s = src.row("SELECT * FROM sessions WHERE session_id = ?", (sid,))
    msgs = src.rows("SELECT uuid, ts, role, text FROM messages WHERE session_id = ? AND is_sidechain = 0 "
                    "ORDER BY ts, uuid", (sid,))
    parts, tools = [], []

    def flush_tools():
        if tools:
            calls = sum(line.startswith("[tool:") for t in tools for line in t.splitlines())
            parts.append(f"<details class=tool><summary>🔧 {calls} tool call(s)</summary>"
                         f"<div class=body>{e(chr(10).join(tools))}</div></details>")
            tools.clear()

    for m in msgs:
        if m["role"] == "tool":
            tools.append(m["text"])
            continue
        flush_tools()
        parts.append(f"<div class='msg {e(m['role'])}' id='m{e(m['uuid'])}'><div class=who>"
                     f"<span>{ROLE_LABEL.get(m['role'], e(m['role']))}</span>"
                     f"<a href='#m{e(m['uuid'])}'>{e(local_time(m['ts']))}</a></div>"
                     f"<div class=body>{render_text(m['text'])}</div></div>")
    flush_tools()
    keys = s.keys()
    project = (f"<a href='{link('/project', src.name, name=s['project'])}'>{e(s['project'])}</a> · "
               if s["project"] else "")
    host = f" · @{e(s['host'] or '?')}" if "host" in keys else ""
    head = (f"<h1>{e(s['title'] or '(untitled)')}</h1><p class=meta>{project}{e(s['entrypoint'] or '?')}{host}"
            f" · {e(local_time(s['first_ts']))} → {e(local_time(s['last_ts']))} · {s['msg_count']:,} messages"
            f"{' · ' + e(s['git_branch']) if 'git_branch' in keys and s['git_branch'] else ''}</p>")
    if s["entrypoint"] != "claude.ai":
        where = f" (on {e(s['host'] or '?')})" if "host" in keys and s["host"] != socket.gethostname() else ""
        head += f"<p class=meta>Resume it{where}: <span class=cmd>claude --resume {e(sid)}</span></p>"
    return s["title"] or sid[:8], head + "".join(parts)


def search_page(src: Source, q: str) -> tuple[str, str]:
    rows = src.api.search(src.conn, q, limit=RESULTS, marks=(HIT_OPEN, HIT_CLOSE)) if q.strip() else []
    rows = [r for r in rows if r["role"] != "tool"]
    hits = "".join(
        f"<div class=hit><a href='{link('/session', src.name, id=r['session_id'])}#m{e(r['uuid'])}'>"
        f"{e(r['title'] or '(untitled)')}</a><div class=meta>{e(r['project'] or '')} · "
        f"{ROLE_LABEL.get(r['role'], e(r['role']))} · {e(local_time(r['ts']))}"
        f"{' · @' + e(r['host'] or '?') if 'host' in r else ''}</div>"
        f"<div>{e(r['snippet']).replace(HIT_OPEN, '<mark>').replace(HIT_CLOSE, '</mark>')}</div></div>"
        for r in rows)
    count = f"{len(rows)}{'+' if len(rows) == RESULTS else ''} result(s)"
    return f"Search: {q}", (f"<h1>“{e(q)}”</h1><p class=meta>{count}</p>"
                            f"{hits or '<p>Nothing found. Fewer or other words?</p>'}")


def allowed_host(host: str | None, port: int) -> bool:
    return host in {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}


def open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def open_cloud():
    """A read-only connection to Neon (the sync's direct endpoint); needs psycopg."""
    import psycopg
    from psycopg.rows import dict_row

    from brain import remote
    from brain.sync import direct_url, neon_url

    conn = psycopg.connect(direct_url(neon_url()), connect_timeout=8, row_factory=dict_row)
    conn.read_only = True
    return conn, remote


def cloud_available() -> bool:
    from brain.sync import neon_url

    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return bool(neon_url())


def make_handler(path: Path, cloud: bool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet: the terminal is for the address and Ctrl+C
            pass

        def _send(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _open(self, name: str) -> Source:
            if name == "cloud":
                conn, api = open_cloud()
                return Source("cloud", conn, api, "%s")
            return Source("local", open_readonly(path), query, "?")

        def do_GET(self):
            if not allowed_host(self.headers.get("Host"), self.server.server_address[1]):
                return self._send(403, "forbidden: open it as http://127.0.0.1")
            url = urlsplit(self.path)
            args = {k: v[0] for k, v in parse_qs(url.query).items()}
            name = args.get("src") if args.get("src") in ("cloud", "local") else ("cloud" if cloud else "local")
            if name == "cloud" and not cloud:
                name = "local"
            q = args.get("q", "") if url.path == "/search" else ""
            try:
                src = self._open(name)
            except Exception as exc:
                return self._send(502, page("Cloud unreachable", (
                    f"<h1>Can't reach the cloud</h1><p>{e(exc)}</p>"
                    f"<p><a href='{link('/', 'local')}'>Use the local archive instead</a></p>"), "cloud", cloud))
            try:
                if url.path == "/":
                    title, body = "Your history", index_page(src)
                elif url.path == "/project":
                    title, body = project_page(src, args.get("name", ""))
                elif url.path == "/session":
                    title, body = session_page(src, args.get("id", ""))
                elif url.path == "/search":
                    title, body = search_page(src, q) if q else ("Your history", index_page(src))
                else:
                    return self._send(404, page("Not found", "<h1>Not found</h1>", name, cloud))
                self._send(200, page(title, body, name, cloud, q))
            except LookupError as exc:
                self._send(404, page("Not found", f"<h1>Not found</h1><p>{e(exc)}</p>"
                                     f"<p class=meta>Is it on the other side of the switch?</p>", name, cloud))
            except Exception as exc:  # a cloud query failing mid-way is shown, not a dropped connection
                self._send(500, page("Error", f"<h1>Couldn't run that</h1><p>{e(exc)}</p>", name, cloud))
            finally:
                src.conn.close()

    return Handler


def bind(path: Path, port: int, cloud: bool = False) -> ThreadingHTTPServer:
    """A server on the first free port from `port` (0 = any)."""
    for candidate in [port] if port == 0 else range(port, port + PORTS_TRIED):
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), make_handler(path, cloud))
        except OSError:
            continue
    raise OSError(f"ports {port}–{port + PORTS_TRIED - 1} are all in use; try --port")


def main(argv: list[str]) -> None:
    utf8_output()
    path = db_path()
    if not sys.stdout.isatty():
        sys.exit("web starts a local web server and runs until Ctrl+C — run it in your own terminal:\n"
                 "  claude-brain web")
    if not cloud_available():
        from brain import sync

        uv = sync.find_uv() if sync.neon_url() else None
        if uv and "--no-cloud" not in argv:  # psycopg comes from uv: run this script again through it
            try:
                sys.exit(subprocess.call(sync.uv_script(uv, Path(__file__).resolve(), *argv)))
            except KeyboardInterrupt:
                return
    cloud = cloud_available() and "--no-cloud" not in argv
    if not path.is_file() and not cloud:
        sys.exit("nothing archived yet: run `claude-brain ingest` first")
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else DEFAULT_PORT
    server = bind(path, port, cloud)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    mode = "cloud (live) and local" if cloud else "local only"
    print(f"ClaudeBrain → {url}  ({mode}; this computer only, read-only). Ctrl+C to stop.")
    if "--no-open" not in argv:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
