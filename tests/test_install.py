import copy
from pathlib import Path

from brain import install

OLD_MANUAL_INSTALL = {
    "model": "opus",
    "permissions": {"allow": ["Bash(git *)", "Bash(/usr/bin/python3 /old/claude_brain/brain/query.py:*)"]},
    "cleanupPeriodDays": 30,
    "hooks": {
        "Stop": [
            {"hooks": [{"type": "command", "command": "/usr/bin/python3 /old/brain/ingest.py --quiet || true"}]},
            {"matcher": "", "hooks": [{"type": "command", "command": "notify-send done"}]},
        ],
        "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "prettier"}]}],
    },
}


def _cmds(uv="/usr/bin/uv"):
    return install.commands("/usr/bin/python3", Path("/home/u/My Code/ClaudeBrain"), uv)


def test_hooks_use_exec_form_without_shell():
    cmds = _cmds()
    assert cmds["stop"]["command"] == "/usr/bin/python3"
    assert cmds["stop"]["args"] == ["/home/u/My Code/ClaudeBrain/brain/hook.py", "--sync", "--uv", "/usr/bin/uv"]
    assert cmds["stop"]["async"] is True
    assert cmds["session_end"]["args"] == ["/home/u/My Code/ClaudeBrain/brain/hook.py"]
    assert _cmds(uv=None)["stop"]["args"] == ["/home/u/My Code/ClaudeBrain/brain/hook.py", "--sync"]
    assert cmds["query"] == "/usr/bin/python3 '/home/u/My Code/ClaudeBrain/bin/claude-brain'"


def test_windows_paths_become_forward_slashes():
    from pathlib import PureWindowsPath
    cmds = install.commands(PureWindowsPath(r"C:\Python312\python.exe"),
                            PureWindowsPath(r"C:\Users\A\ClaudeBrain"), None)
    assert cmds["stop"]["command"] == "C:/Python312/python.exe"
    assert cmds["stop"]["args"] == ["C:/Users/A/ClaudeBrain/brain/hook.py", "--sync"]
    assert cmds["query"] == "C:/Python312/python.exe C:/Users/A/ClaudeBrain/bin/claude-brain"


def test_merge_replaces_previous_install_and_keeps_everything_else():
    out = install.merge_settings(copy.deepcopy(OLD_MANUAL_INSTALL), _cmds())

    assert out["model"] == "opus"
    assert out["permissions"]["allow"] == [
        "Bash(git *)", "Bash(/usr/bin/python3 '/home/u/My Code/ClaudeBrain/bin/claude-brain':*)"]
    assert out["cleanupPeriodDays"] == install.RETENTION_DAYS
    assert out["hooks"]["PostToolUse"] == OLD_MANUAL_INSTALL["hooks"]["PostToolUse"]

    stop_hooks = [h for g in out["hooks"]["Stop"] for h in g["hooks"]]
    assert {"type": "command", "command": "notify-send done"} in stop_hooks
    assert not any("/old/brain/ingest.py" in h["command"] for h in stop_hooks)
    assert sum(install._is_ours(h) for h in stop_hooks) == 1
    assert out["hooks"]["Stop"][-1]["hooks"][0]["async"] is True
    assert len(out["hooks"]["SessionEnd"]) == 1


def test_merge_is_idempotent_and_keeps_longer_retention():
    once = install.merge_settings({"cleanupPeriodDays": 9999}, _cmds())
    twice = install.merge_settings(copy.deepcopy(once), _cmds())
    assert once == twice
    assert twice["cleanupPeriodDays"] == 9999


def test_install_skill_renders_template_and_replaces_symlink(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "claude-brain").symlink_to(install.REPO / "skills" / "recall")

    target = install.install_skill(skills, "/py '/x y/bin/claude-brain'")

    assert not target.is_symlink()
    text = (target / "SKILL.md").read_text()
    assert "allowed-tools: Bash(/py '/x y/bin/claude-brain' *)" in text
    assert "/py '/x y/bin/claude-brain' <command> [options]" in text
    assert "\nclaude-brain <command>" not in text
    assert "~/.local/share/claude-brain/brain.db" in text  # paths that merely contain the name stay
    assert "CLAUDE_PLUGIN_ROOT" not in text  # plugin-only fallback dropped
    template = install.SKILL_TEMPLATE.read_text()
    assert "allowed-tools: Bash(claude-brain *)" in template  # the plugin's copy stays bare


def test_uninstall_removes_only_ours():
    installed = install.merge_settings(copy.deepcopy(OLD_MANUAL_INSTALL), _cmds())
    out = install.remove_ours(installed)
    assert out["permissions"]["allow"] == ["Bash(git *)"]
    assert out["hooks"]["Stop"] == [{"matcher": "", "hooks": [{"type": "command", "command": "notify-send done"}]}]
    assert "SessionEnd" not in out["hooks"]
    assert out["hooks"]["PostToolUse"] == OLD_MANUAL_INSTALL["hooks"]["PostToolUse"]
    assert out["cleanupPeriodDays"] == install.RETENTION_DAYS and out["model"] == "opus"
