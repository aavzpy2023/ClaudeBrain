"""Stable entry point for ClaudeBrain's MCP server; MCP clients' configs point here.

`claude-brain mcp enable` copies this file next to the database, so client configs never hold a
plugin path that changes on every update. It reads the current ClaudeBrain folder from `root`
(kept up to date by the hooks) and starts the server through uv. Deliberately self-contained:
it runs before anything of ClaudeBrain can be imported.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REQUIREMENTS = ("mcp>=2.3,<3", "psycopg[binary]>=3.2")


def state_dir() -> Path:
    db = os.environ.get("CLAUDE_BRAIN_DB")
    return Path(db).expanduser().parent if db else Path.home() / ".local" / "share" / "claude-brain"


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "uv", Path.home() / ".cargo" / "bin" / "uv"):
        if candidate.is_file():
            return str(candidate)
    return None


def command(root: Path, uv: str, extra: list[str]) -> list[str]:
    deps = [arg for req in REQUIREMENTS for arg in ("--with", req)]
    return [uv, "run", "--quiet", "--no-project", *deps, str(root / "brain" / "mcp_server.py"), *extra]


def main() -> None:
    marker = state_dir() / "root"
    root = Path(marker.read_text().strip()) if marker.is_file() else Path(__file__).resolve().parent.parent
    if not (root / "brain" / "mcp_server.py").is_file():
        sys.exit(f"claude-brain MCP: no ClaudeBrain at {root}; open Claude Code once (its hook records "
                 f"the path) or run `claude-brain mcp enable` again")
    uv = find_uv()
    if not uv:
        sys.exit("claude-brain MCP: uv not found — https://docs.astral.sh/uv/")
    sys.exit(subprocess.call(command(root, uv, sys.argv[1:])))


if __name__ == "__main__":
    main()
