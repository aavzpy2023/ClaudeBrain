"""Export projects as Markdown: one note per session plus a project index — Obsidian-friendly.

Works over any read API (the local archive, or brain.remote for every device). Files are only
rewritten when their content changed, and nothing else in the target folder is touched.
"""
import json
import re
import unicodedata
from pathlib import Path

from brain.query import DEFAULT_ROLES
from brain.sync import redact

ROLE_HEADINGS = {"user": "🧑 User", "assistant": "🤖 Claude"}
EVERYTHING = 10**12  # max_chars for a full transcript


def slug(text: str, limit: int = 60) -> str:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", "-", plain).strip("-_")[:limit].rstrip("-") or "untitled"


def note_name(s: dict) -> str:
    return f"{(s['first_ts'] or '0000-00-00')[:10]}_{slug(s['title'] or 'untitled')}_{s['session_id'][:8]}.md"


def _yaml(value) -> str:
    return json.dumps(value, ensure_ascii=False)  # JSON scalars are valid YAML


def _day(ts: str | None) -> str:
    return (ts or "")[:16].replace("T", " ")


def render_session(meta: dict, messages: list[dict], clean) -> str:
    props = {
        "session_id": meta["session_id"], "project": meta["project"], "title": meta["title"],
        "started": meta["first_ts"], "ended": meta["last_ts"], "source": meta["entrypoint"],
        "host": meta.get("host"), "repo": meta.get("repo"), "folder": meta.get("project_cwd"),
        "messages": meta["msg_count"],
    }
    lines = ["---", *(f"{k}: {_yaml(v)}" for k, v in props.items() if v is not None), "---", "",
             f"# {meta['title'] or '(untitled)'}", ""]
    for m in messages:
        text = clean(m["text"]).strip()
        if m["role"] == "summary":
            body = "\n".join(f"> {line}" for line in text.splitlines())
            lines += [f"> [!summary] Summary · {_day(m['ts'])}", body, ""]
        elif m["role"] == "tool":
            lines += [f"> 🔧 {_day(m['ts'])}", *(f"> {line}" for line in text.splitlines()), ""]
        else:
            lines += [f"### {ROLE_HEADINGS.get(m['role'], m['role'])} · {_day(m['ts'])}", "", text, ""]
    return "\n".join(lines).rstrip() + "\n"


def render_index(project: str, digest: dict | None, sessions: list[dict], clean) -> str:
    lines = ["---", f"project: {_yaml(project)}", f"sessions: {len(sessions)}", "---", "",
             f"# {project}", ""]
    if digest:
        lines += [f"## Latest digest", "", f"*Covers until {digest['covers_until_ts']}.*", "",
                  clean(digest["content"]).strip(), ""]
    lines += ["## Sessions", "", "| Date | Session | Source | Messages |", "|---|---|---|---|"]
    for s in sessions:
        where = f"{s['entrypoint'] or '?'}" + (f" @{s['host']}" if s.get("host") else "")
        title = (s["title"] or "(untitled)").replace("|", "\\|")
        lines.append(f"| {_day(s['first_ts'])} | [{title}]({note_name(s)}) | {where} | {s['msg_count']} |")
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> bool:
    """Write only when the content changed (keeps synced vaults quiet). True if written."""
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def export_project(conn, api, name: str, out: Path, since=None, tools=False, redact_secrets=True) -> dict:
    data = api.project(conn, name, since)
    project, sessions = data["project"], data["sessions"]
    folder = out / project
    folder.mkdir(parents=True, exist_ok=True)
    clean = redact if redact_secrets else (lambda text: text)
    roles = DEFAULT_ROLES + (("tool",) if tools else ())
    written = 0
    for s in sessions:
        full = api.session(conn, s["session_id"], None, roles, False, EVERYTHING)
        written += _write(folder / note_name(s), render_session({**s, **full["session"]}, full["messages"], clean))
    written += _write(folder / f"{project}.md", render_index(project, data["digest"], sessions, clean))
    return {"project": project, "folder": folder, "sessions": len(sessions), "written": written}


def run(conn, api, args, say=print) -> None:
    out = Path(args.out).expanduser()
    names = [p["project"] for p in api.projects(conn)] if args.all else [args.project]
    if not names or names == [None]:
        raise LookupError("name a project, or pass --all")
    for name in names:
        r = export_project(conn, api, name, out, args.since, args.tools, not args.no_redact)
        say(f"{r['project']:<24} {r['sessions']:>4} sessions → {r['folder']}  ({r['written']} file(s) written)")
