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
    return install.commands("/usr/bin/python3", Path("/home/u/My Code/ClaudeBrain"), Path("/home/u/log"), uv)


def test_commands_quote_paths_with_spaces():
    cmds = _cmds()
    assert "'/home/u/My Code/ClaudeBrain/brain/ingest.py'" in cmds["stop"]
    assert "sync.py" in cmds["stop"] and "sync.py" not in cmds["session_end"]
    assert cmds["query"] == "/usr/bin/python3 '/home/u/My Code/ClaudeBrain/brain/query.py'"
    assert "sync.py" not in _cmds(uv=None)["stop"]


def test_merge_replaces_previous_install_and_keeps_everything_else():
    out = install.merge_settings(copy.deepcopy(OLD_MANUAL_INSTALL), _cmds())

    assert out["model"] == "opus"
    assert out["permissions"]["allow"] == [
        "Bash(git *)", "Bash(/usr/bin/python3 '/home/u/My Code/ClaudeBrain/brain/query.py':*)"]
    assert out["cleanupPeriodDays"] == install.RETENTION_DAYS
    assert out["hooks"]["PostToolUse"] == OLD_MANUAL_INSTALL["hooks"]["PostToolUse"]

    stop_cmds = [h["command"] for g in out["hooks"]["Stop"] for h in g["hooks"]]
    assert "notify-send done" in stop_cmds
    assert not any("/old/brain/ingest.py" in c for c in stop_cmds)
    assert sum("brain/ingest.py" in c for c in stop_cmds) == 1
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
    (skills / "claude-brain").symlink_to(install.REPO / "skill")

    target = install.install_skill(skills, "/py '/x y/query.py'")

    assert not target.is_symlink()
    text = (target / "SKILL.md").read_text()
    assert install.PLACEHOLDER not in text and "/py '/x y/query.py' <command>" in text
    assert install.PLACEHOLDER in (install.REPO / "skill" / "SKILL.md").read_text()  # template untouched
