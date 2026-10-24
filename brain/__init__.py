"""claude_brain: archive Claude Code transcripts into SQLite and query them."""
import sys


def utf8_output() -> None:
    """Print UTF-8 whatever the console: Windows pipes (Claude Code's Bash tool) default to the
    ANSI code page, which has no →, · or ▁ and would crash the command mid-output."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
