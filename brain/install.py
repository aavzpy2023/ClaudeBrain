"""Install ClaudeBrain for the current user: skill, hooks, permission, backfill, first sync.

Usage: python3 brain/install.py [--no-backfill]
Idempotent: re-running replaces its own hooks/rule and leaves the rest of settings.json alone.
"""
import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import db_path
from brain.sync import neon_url

REPO = Path(__file__).resolve().parent.parent
PLACEHOLDER = "{{BRAIN_QUERY}}"
# Substrings that identify hooks/rules written by any previous install of ClaudeBrain.
OUR_HOOK_MARK = "brain/ingest.py"
OUR_RULE_MARK = "brain/query.py"
RETENTION_DAYS = 3650


def commands(python: str, repo: Path, log: Path, uv: str | None) -> dict:
    q = shlex.quote
    ingest = f"{q(python)} {q(str(repo / 'brain' / 'ingest.py'))} --quiet 2>>{q(str(log))}"
    stop = ingest
    if uv:
        stop += (f"; {q(uv)} run --quiet --project {q(str(repo))} "
                 f"{q(str(repo / 'brain' / 'sync.py'))} --quiet 2>>{q(str(log))}")
    query = f"{q(python)} {q(str(repo / 'brain' / 'query.py'))}"
    return {"stop": stop + " || true", "session_end": ingest + " || true", "query": query}


def merge_settings(settings: dict, cmds: dict) -> dict:
    """Return settings with ClaudeBrain's hooks, permission and retention set; others untouched."""
    hooks = settings.setdefault("hooks", {})
    wanted = {
        "Stop": {"type": "command", "command": cmds["stop"], "timeout": 120, "async": True},
        "SessionEnd": {"type": "command", "command": cmds["session_end"], "timeout": 120},
    }
    for event, hook in wanted.items():
        groups = [
            g for g in hooks.get(event, [])
            if not any(OUR_HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))
        ]
        groups.append({"hooks": [hook]})
        hooks[event] = groups

    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    allow[:] = [r for r in allow if OUR_RULE_MARK not in r]
    allow.append(f"Bash({cmds['query']}:*)")

    settings["cleanupPeriodDays"] = max(settings.get("cleanupPeriodDays", 0), RETENTION_DAYS)
    return settings


def install_skill(skills_dir: Path, query_cmd: str) -> Path:
    target = skills_dir / "claude-brain"
    if target.is_symlink():
        target.unlink()  # older installs symlinked the repo's template; replace with a rendered copy
    target.mkdir(parents=True, exist_ok=True)
    text = (REPO / "skill" / "SKILL.md").read_text().replace(PLACEHOLDER, query_cmd)
    (target / "SKILL.md").write_text(text)
    return target


def check_fts5() -> None:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError:
        sys.exit(f"error: {sys.executable} has no SQLite FTS5 support; run with another python3")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-backfill", action="store_true", help="skip the initial full ingest")
    args = parser.parse_args(argv)

    check_fts5()
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    log = db_path().parent / "ingest.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    has_neon = neon_url() is not None
    uv = shutil.which("uv") if has_neon else None
    if has_neon and not uv:
        print("warning: NEON_URL is set but uv is not installed; cloud sync disabled")
    cmds = commands(sys.executable, REPO, log, uv)

    skill = install_skill(claude_dir / "skills", cmds["query"])
    print(f"skill      → {skill}")

    settings_file = claude_dir / "settings.json"
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    if settings_file.exists():
        shutil.copy2(settings_file, settings_file.with_name("settings.json.bak-claudebrain"))
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(merge_settings(settings, cmds), indent=2, ensure_ascii=False) + "\n")
    print(f"settings   → {settings_file} (Stop/SessionEnd hooks, permission, cleanupPeriodDays)")

    if not args.no_backfill:
        subprocess.run([sys.executable, str(REPO / "brain" / "ingest.py"), "--full"], check=True)
    if uv:
        subprocess.run([uv, "run", "--quiet", "--project", str(REPO),
                        str(REPO / "brain" / "sync.py"), "--init"], check=True)
    else:
        print("cloud sync → off (no NEON_URL in env or ~/.config/claude-brain/.env)")
    print("done. Open /hooks once (or restart Claude Code) so running sessions pick up the hooks.")


if __name__ == "__main__":
    main()
