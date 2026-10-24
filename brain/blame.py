"""`claude-brain blame <file>`: the conversations that edited a file, and why.

Works over any read API (the local archive, or brain.remote for every device). A file is matched
by its path inside the repo, so every clone, every machine and both path styles count.
Edit/Write/MultiEdit/NotebookEdit calls are edits, shell commands naming the file count too
(Claude often edits through sed or scripts); any other appearance is a mention. The "why" is the
user's message right before a change. A commit that touched the file is attributed to the session
that changed it and was active when the commit was made.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from brain.db import connect, project_of_cwd
from brain.gitrepo import find_repo

EDIT_CALL = re.compile(
    r'^\[tool:(?:Edit|MultiEdit|Write|NotebookEdit)\] \{"(?:file_path|notebook_path)": ("(?:[^"\\]|\\.)*")')
SHELL_TOKEN = re.compile(r"""[^\s"'`;|&<>()\\]+""")
WHYS = 3
WHY_CHARS = 160
COMMITS_SHOWN = 5
COMMIT_SLACK = timedelta(minutes=30)  # commits made just after a session's last message


def repo_relative(target: str, cwd: str) -> str:
    """The file's path inside its repo (`brain/sync.py`); outside repos, relative to the current
    folder (usually the project folder) when it is below it; else absolute."""
    path = Path(os.path.realpath(Path(cwd, target)))
    _, root = find_repo(str(path.parent) if path.parent.is_dir() else cwd)
    for base in (root, cwd):
        if base:
            try:
                return path.relative_to(os.path.realpath(base)).as_posix()
            except ValueError:
                pass
    return path.as_posix()


def needles(rel: str) -> list[str]:
    """Substrings that preselect candidate messages: the path as written on POSIX, and as it
    appears JSON-escaped in a Windows tool call (`brain\\\\sync.py`)."""
    return [rel, rel.replace("/", "\\\\")]


def edited_path(line: str) -> str | None:
    match = EDIT_CALL.match(line)
    try:
        return json.loads(match[1]) if match else None
    except ValueError:
        return None  # clipped mid-string


def shell_names(line: str, rel: str, cwd: str | None) -> bool:
    """True if a recorded Bash call names the file: as `rel` itself (run from the repo root),
    `./rel`, or a full path inside the session's clone."""
    if not line.startswith("[tool:Bash]"):
        return False
    for token in SHELL_TOKEN.findall(line):
        token = token.removeprefix("./")
        if token == rel or (token.endswith("/" + rel) and is_same_file(token, rel, cwd)):
            return True
    return False


def _norm(path: str) -> str:
    path = path.replace("\\", "/").rstrip("/")
    return path.casefold() if re.match(r"^[A-Za-z]:/", path) else path  # Windows: case-insensitive


def is_same_file(path: str, rel: str, session_cwd: str | None) -> bool:
    """True if `path` (recorded on any machine) is `rel` inside that session's clone: the part
    before `rel` must be the session's folder or one of its parents — the repo root always is —
    so `brain/db.py` doesn't count as a root-level `db.py`."""
    path, rel = _norm(path), _norm(rel)
    if path == rel:
        return True
    if not path.endswith("/" + rel):
        return False
    prefix = path[: -len(rel) - 1]
    cwd = _norm(session_cwd or "")
    return bool(prefix) and (cwd == prefix or cwd.startswith(prefix + "/"))


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= WHY_CHARS else text[:WHY_CHARS] + "…"


def commits(rel: str, cwd: str, limit: int = 200) -> list[tuple[str, datetime, str]]:
    """(short sha, commit time, subject) of commits touching the file, newest first; [] without
    git or outside a repo."""
    _, root = find_repo(cwd)
    if not root or rel.startswith("/"):
        return []
    try:
        out = subprocess.run(
            ["git", "-C", root, "log", "--follow", f"-n{limit}", "--format=%h%x09%cI%x09%s", "--", rel],
            capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        sha, when, subject = (line.split("\t", 2) + ["", ""])[:3]
        try:
            rows.append((sha, _ts(when), subject))
        except ValueError:
            pass
    return rows


def blame(conn, api, rel: str, project: str, file_commits=(), limit: int = 10) -> dict:
    rows = api.file_mentions(conn, project, needles(rel))
    meta = {s["session_id"]: s for s in api.sessions_meta(conn, sorted({r["session_id"] for r in rows}))}
    changes: dict[str, dict[str, list[str]]] = {}  # session -> {"edit": [ts], "shell": [ts]}
    for r in rows:
        cwd = meta.get(r["session_id"], {}).get("project_cwd")
        for line in r["text"].splitlines():
            path = edited_path(line)
            kind = ("edit" if path and is_same_file(path, rel, cwd)
                    else "shell" if shell_names(line, rel, cwd) else None)
            if kind:
                changes.setdefault(r["session_id"], {"edit": [], "shell": []})[kind].append(r["ts"])
    times = {sid: sorted(c["edit"] + c["shell"]) for sid, c in changes.items()}
    changed = sorted(changes, key=lambda sid: times[sid][-1], reverse=True)[:limit]
    prompts: dict[str, list[dict]] = {}
    for p in api.user_prompts(conn, changed):
        prompts.setdefault(p["session_id"], []).append(p)

    owner: dict[str, list] = {}
    for sha, when, subject in file_commits:
        active = [sid for sid in changes if meta[sid]["first_ts"] and meta[sid]["last_ts"]
                  and _ts(meta[sid]["first_ts"]) <= when <= _ts(meta[sid]["last_ts"]) + COMMIT_SLACK]
        if active:
            sid = max(active, key=lambda a: max((t for t in times[a] if _ts(t) <= when), default=""))
            owner.setdefault(sid, []).append((sha, when, subject))

    sessions = []
    for sid in changed:
        whys = []
        for t in times[sid]:
            before = [p for p in prompts.get(sid, []) if p["ts"] < t]
            if before and before[-1] not in whys:
                whys.append(before[-1])
        sessions.append({**meta[sid], "edits": len(changes[sid]["edit"]), "shell": len(changes[sid]["shell"]),
                         "first_change": times[sid][0], "last_change": times[sid][-1],
                         "whys": whys[-WHYS:], "commits": owner.get(sid, [])})
    mentioned = [meta[sid] for sid in {r["session_id"] for r in rows} - set(changes) if sid in meta]
    mentioned.sort(key=lambda s: s["last_ts"] or "", reverse=True)
    return {"file": rel, "project": project, "sessions": sessions, "changed": len(changes),
            "mentioned": mentioned}


def run(conn, api, args, say=print) -> None:
    from brain.query import _day, _host

    cwd = os.getcwd()
    rel = repo_relative(args.file, cwd)
    if args.project:
        project = api.resolve_project(conn, args.project)
    else:
        local = connect()  # project naming rules live in the local archive, aliases included
        try:
            project = project_of_cwd(local, cwd)
        finally:
            local.close()
    out = blame(conn, api, rel, project, commits(rel, cwd), args.limit)
    shown = f", newest {len(out['sessions'])} shown" if out["changed"] > len(out["sessions"]) else ""
    say(f"# {rel} · project {project}")
    say(f"changed in {out['changed']} session(s){shown}; mentioned in {len(out['mentioned'])} more\n")
    for s in out["sessions"]:
        say(f"{s['session_id'][:8]}  {s['entrypoint'] or '?'}  {s['title'] or '(untitled)'}{_host(s)}")
        span = _day(s["first_change"]) + (f" → {_day(s['last_change'])}" if s["last_change"] != s["first_change"] else "")
        kinds = ", ".join(f"{n} {label}" for n, label in ((s["edits"], "edit(s)"), (s["shell"], "shell command(s)")) if n)
        say(f"  {kinds}  {span}")
        for w in s["whys"]:
            say(f"  why  {_day(w['ts'])}  \"{_clip(w['text'])}\"")
        for sha, when, subject in s["commits"][:COMMITS_SHOWN]:
            say(f"  commit  {sha}  {when.date()}  {subject}")
        if len(s["commits"]) > COMMITS_SHOWN:
            say(f"  … and {len(s['commits']) - COMMITS_SHOWN} older commit(s)")
        if s["whys"]:
            say(f"  read: claude-brain session {s['session_id'][:8]} --after {s['whys'][0]['ts'][:19]}")
        say("")
    if out["mentioned"]:
        names = ", ".join(f"{s['session_id'][:8]} {s['title'] or '(untitled)'}" for s in out["mentioned"][:8])
        more = f" (+{len(out['mentioned']) - 8})" if len(out["mentioned"]) > 8 else ""
        say(f"also mentioned in: {names}{more}")
    if not out["changed"] and not out["mentioned"]:
        say("no archived session edited or mentioned this file (in this project; --project to pick another)")
