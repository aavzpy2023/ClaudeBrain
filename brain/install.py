"""Manual install (instead of the plugin): skill, hooks, permission, retention, backfill.

Usage: python3 brain/install.py [--no-backfill | --uninstall]
For Windows, or anyone not using Claude Code plugins. Don't combine with the plugin: both would
run the hooks. Idempotent: re-running replaces its own hooks/rule, leaves other settings alone.
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

from brain.sync import find_uv, neon_url, uv_command

REPO = Path(__file__).resolve().parent.parent
SKILL_TEMPLATE = REPO / "skills" / "recall" / "SKILL.md"
PLUGIN_COMMAND = "claude-brain"  # what the skill calls; on PATH only when installed as a plugin
# Substrings that identify hooks/rules written by any previous install (shell or exec form).
OUR_HOOK_MARKS = ("brain/ingest.py", "brain/hook.py")
OUR_RULE_MARKS = ("brain/query.py", "bin/claude-brain")
RETENTION_DAYS = 3650


def _posix(path) -> str:
    # Forward slashes work in Git Bash (Claude Code's shell on Windows) and need no escaping.
    return Path(path).as_posix()


def commands(python: str, repo: Path, uv: str | None) -> dict:
    """Hooks use exec form (command + args, no shell) so the same entry works on every OS."""
    hook = _posix(repo / "brain" / "hook.py")
    # --sync is a no-op until NEON_URL is configured, so cloud can be switched on later.
    stop_args = [hook, "--sync"] + (["--uv", _posix(uv)] if uv else [])
    return {
        "stop": {"type": "command", "command": _posix(python), "args": stop_args,
                 "timeout": 120, "async": True},
        "session_end": {"type": "command", "command": _posix(python), "args": [hook], "timeout": 120},
        "query": f"{shlex.quote(_posix(python))} {shlex.quote(_posix(repo / 'bin' / 'claude-brain'))}",
    }


def _is_ours(hook: dict) -> bool:
    text = " ".join([hook.get("command", ""), *hook.get("args", [])])
    return any(mark in text for mark in OUR_HOOK_MARKS)


def merge_settings(settings: dict, cmds: dict) -> dict:
    """Return settings with ClaudeBrain's hooks, permission and retention set; others untouched."""
    hooks = settings.setdefault("hooks", {})
    for event, hook in (("Stop", cmds["stop"]), ("SessionEnd", cmds["session_end"])):
        groups = [g for g in hooks.get(event, []) if not any(_is_ours(h) for h in g.get("hooks", []))]
        groups.append({"hooks": [hook]})
        hooks[event] = groups

    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    allow[:] = [r for r in allow if not any(mark in r for mark in OUR_RULE_MARKS)]
    allow.append(f"Bash({cmds['query']}:*)")

    settings["cleanupPeriodDays"] = max(settings.get("cleanupPeriodDays", 0), RETENTION_DAYS)
    return settings


def remove_ours(settings: dict) -> dict:
    """Inverse of merge_settings for hooks and the permission rule; retention and data stay."""
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        hooks[event] = [g for g in hooks[event] if not any(_is_ours(h) for h in g.get("hooks", []))]
        if not hooks[event]:
            del hooks[event]
    allow = settings.get("permissions", {}).get("allow")
    if allow is not None:
        allow[:] = [r for r in allow if not any(mark in r for mark in OUR_RULE_MARKS)]
    return settings


def render_skill(query_cmd: str) -> str:
    """The plugin's skill with its bare `claude-brain` command replaced by this machine's path."""
    # Lines about ${CLAUDE_PLUGIN_ROOT} only make sense inside the plugin: drop them.
    text = "".join(l for l in SKILL_TEMPLATE.read_text().splitlines(keepends=True)
                   if "${CLAUDE_PLUGIN_ROOT}" not in l)
    for old, new in ((f"Bash({PLUGIN_COMMAND} *)", f"Bash({query_cmd} *)"),
                     (f"{PLUGIN_COMMAND} <command>", f"{query_cmd} <command>"),
                     (f"`{PLUGIN_COMMAND} status`", f"`{query_cmd} status`")):
        if old not in text:
            raise RuntimeError(f"skill template changed: {old!r} not found")
        text = text.replace(old, new)
    return text


def install_skill(skills_dir: Path, query_cmd: str) -> Path:
    target = skills_dir / "claude-brain"  # the folder name is the skill name: /claude-brain
    if target.is_symlink():
        target.unlink()  # older installs symlinked the repo's template; replace with a rendered copy
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(render_skill(query_cmd))
    return target


def check_fts5() -> None:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError:
        sys.exit(f"error: {sys.executable} has no SQLite FTS5 support; run with another python3")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-backfill", action="store_true", help="skip the initial full ingest")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove this manual install's hooks, permission and skill (e.g. before "
                             "switching to the plugin); the database is kept")
    args = parser.parse_args(argv)

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    settings_file = claude_dir / "settings.json"
    if args.uninstall:
        uninstall(claude_dir, settings_file)
        return

    check_fts5()
    has_neon = neon_url() is not None
    uv = find_uv()
    if has_neon and not uv:
        print("warning: NEON_URL is set but uv is not installed; cloud sync disabled")
    cmds = commands(sys.executable, REPO, uv)

    skill = install_skill(claude_dir / "skills", cmds["query"])
    print(f"skill      → {skill}")

    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    if settings_file.exists():
        shutil.copy2(settings_file, settings_file.with_name("settings.json.bak-claudebrain"))
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(merge_settings(settings, cmds), indent=2, ensure_ascii=False) + "\n")
    print(f"settings   → {settings_file} (Stop/SessionEnd hooks, permission, cleanupPeriodDays)")

    if not args.no_backfill:
        subprocess.run([sys.executable, str(REPO / "brain" / "ingest.py"), "--full"], check=True)
    if has_neon and uv:
        subprocess.run(uv_command(uv, "--init"), check=True)
    else:
        print("cloud sync → off for now (optional: NEON_URL in ~/.config/claude-brain/.env, then re-run)")
    print("done. Open /hooks once (or restart Claude Code) so running sessions pick up the hooks.")


def uninstall(claude_dir: Path, settings_file: Path) -> None:
    if settings_file.exists():
        shutil.copy2(settings_file, settings_file.with_name("settings.json.bak-claudebrain"))
        settings = remove_ours(json.loads(settings_file.read_text()))
        settings_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        print(f"settings   → removed ClaudeBrain hooks and permission from {settings_file}")
    skill = claude_dir / "skills" / "claude-brain"
    if skill.is_symlink():
        skill.unlink()
    elif (skill / "SKILL.md").is_file() and "ClaudeBrain" in (skill / "SKILL.md").read_text():
        shutil.rmtree(skill)
    print("skill      → removed. Your database and cleanupPeriodDays are untouched.")


if __name__ == "__main__":
    main()
