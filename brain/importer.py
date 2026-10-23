"""Import a claude.ai data export (Settings → Privacy → Export data) into the brain.

Usage: python3 brain/importer.py <export.zip | export folder | conversations.json> [--inspect]
Re-importing a newer export only adds what is new. The export format is undocumented, so
parsing is defensive; run --inspect first on a new export to see what it contains.
"""
import argparse
import json
import sqlite3
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import connect, load_aliases, project_for
from brain.ingest import TOOL_INPUT_CHARS, TOOL_RESULT_CHARS, _clip, refresh_session_stats

ENTRYPOINT = "claude-ai"
ATTACHMENT_CHARS = 300
_ROLES = {"human": "user", "user": "user", "assistant": "assistant"}


def load_export(path: Path) -> tuple[list, list]:
    """(conversations, projects) from a zip, an extracted folder, or a bare conversations.json."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = {Path(n).name: n for n in zf.namelist()}
            read = lambda name: json.loads(zf.read(names[name])) if name in names else []
            return read("conversations.json"), read("projects.json")
    if path.is_dir():
        read = lambda name: json.loads((path / name).read_text()) if (path / name).exists() else []
        return read("conversations.json"), read("projects.json")
    projects = path.with_name("projects.json")
    return json.loads(path.read_text()), json.loads(projects.read_text()) if projects.exists() else []


def iso(ts: str | None) -> str | None:
    """Any ISO-8601 timestamp → '2026-10-01T10:00:00.123Z', the transcripts' sortable format."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def message_text(msg: dict) -> str:
    parts: list[str] = []
    blocks = msg.get("content")
    if isinstance(blocks, list) and blocks:
        for block in blocks:
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                parts.append(block["text"].strip())
            elif kind == "tool_use":
                args = json.dumps(block.get("input", {}), ensure_ascii=False)
                parts.append(f"[tool:{block.get('name')}] {_clip(args, TOOL_INPUT_CHARS)}")
            elif kind == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                parts.append(f"[result] {_clip(str(body or ''), TOOL_RESULT_CHARS)}")
    elif msg.get("text"):
        parts.append(str(msg["text"]).strip())
    for att in msg.get("attachments") or []:
        name = att.get("file_name") or "attachment"
        body = _clip(att.get("extracted_content") or "", ATTACHMENT_CHARS)
        parts.append(f"[attachment:{name}] {body}".rstrip())
    for f in msg.get("files") or []:
        parts.append(f"[file:{f.get('file_name') or 'file'}]")
    return "\n".join(p for p in parts if p)


def _project_uuid(conv: dict) -> str | None:
    project = conv.get("project")
    return conv.get("project_uuid") or (project.get("uuid") if isinstance(project, dict) else None)


def import_export(conn: sqlite3.Connection, conversations: list, projects: list) -> dict:
    aliases = load_aliases(conn)
    names = {p.get("uuid"): p.get("name") for p in projects if p.get("uuid")}
    stats = Counter()
    for conv in conversations:
        sid = conv.get("uuid")
        if not sid:
            continue
        project_name = names.get(_project_uuid(conv))
        # Pseudo cwd: project_for treats it like a folder path, so aliases on the claude.ai
        # project name apply; repo_root '' keeps the repo resolver off it.
        cwd = f"claude.ai/{project_name}" if project_name else "claude.ai"
        messages = [m for m in conv.get("chat_messages") or [] if _ROLES.get(m.get("sender"))]
        first_user = next((message_text(m) for m in messages if _ROLES[m["sender"]] == "user"), "")
        title = (conv.get("name") or "").strip() or _clip(first_user, 60) or None

        conn.execute(
            """INSERT INTO sessions (session_id, project, project_cwd, entrypoint, title, repo_root)
               VALUES (?, ?, ?, ?, ?, '')
               ON CONFLICT(session_id) DO UPDATE SET title = excluded.title,
                 project = excluded.project, project_cwd = excluded.project_cwd""",
            (sid, project_for(cwd, aliases, None, ""), cwd, ENTRYPOINT, title),
        )
        for i, msg in enumerate(messages):
            text = message_text(msg)
            if not text:
                continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO messages (uuid, session_id, ts, role, entrypoint, cwd, text)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (msg.get("uuid") or f"{sid}:{i}", sid, iso(msg.get("created_at")),
                 _ROLES[msg["sender"]], ENTRYPOINT, cwd, text),
            )
            stats["messages"] += cur.rowcount  # not total_changes: FTS triggers count too
        stats["conversations"] += 1
        stats["in_projects"] += bool(project_name)
    refresh_session_stats(conn, [c["uuid"] for c in conversations if c.get("uuid")])
    conn.commit()
    return dict(stats)


def inspect(conversations: list, projects: list) -> None:
    conv_keys = Counter(k for c in conversations for k in c)
    msgs = [m for c in conversations for m in c.get("chat_messages") or []]
    print(f"{len(conversations)} conversations, {len(msgs)} messages, {len(projects)} projects")
    print("conversation keys:", dict(conv_keys.most_common()))
    print("message keys:", dict(Counter(k for m in msgs for k in m).most_common()))
    print("senders:", dict(Counter(m.get("sender") for m in msgs)))
    print("content block types:", dict(Counter(
        b.get("type") for m in msgs if isinstance(m.get("content"), list) for b in m["content"])))
    linked = sum(1 for c in conversations if _project_uuid(c))
    print(f"conversations linked to a project: {linked} (project names: "
          f"{sorted(p.get('name') for p in projects if p.get('name'))})")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="export .zip, its extracted folder, or conversations.json")
    parser.add_argument("--inspect", action="store_true", help="describe the export, import nothing")
    args = parser.parse_args(argv)

    conversations, projects = load_export(args.export.expanduser())
    if args.inspect:
        inspect(conversations, projects)
        return
    conn = connect()
    stats = import_export(conn, conversations, projects)
    conn.close()
    print(f"imported {stats.get('conversations', 0)} conversation(s) "
          f"({stats.get('in_projects', 0)} in claude.ai projects), "
          f"{stats.get('messages', 0)} new message(s). They reach Neon with the next sync.")


if __name__ == "__main__":
    main()
