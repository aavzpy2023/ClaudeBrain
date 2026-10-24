"""Claude Code hook entry point: archive new messages, then optionally push to Neon.

Usage (exec-form hook, no shell — same on Linux, macOS and Windows):
  python brain/hook.py [--sync [--uv /path/to/uv]]
--sync pushes to Neon only when NEON_URL is configured; uv is found on its own if not given.
Never fails the hook: errors go to the log next to the database, exit code is always 0.
"""
import argparse
import subprocess
import sys
import traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import mcp_setup
from brain.db import connect, db_path
from brain.ingest import DEFAULT_ROOT, ingest
from brain.sync import find_uv, neon_url, uv_command

SYNC_TIMEOUT = 100  # below the hook's own 120 s timeout


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sync", action="store_true", help="push to Neon after ingesting, if configured")
    parser.add_argument("--uv", help="uv executable used to run the sync with its dependencies")
    args = parser.parse_args(argv)

    log = db_path().parent / "ingest.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", errors="replace") as err:
        try:
            conn = connect()
            ingest(conn, DEFAULT_ROOT)
            conn.close()
        except Exception:
            traceback.print_exc(file=err)
        try:
            mcp_setup.record_root()  # keeps the MCP launcher pointing at this (possibly new) version
        except Exception:
            traceback.print_exc(file=err)
        if not (args.sync and neon_url()):
            return  # local-only install: nothing else to do
        uv = args.uv or find_uv()
        if not uv:
            print("sync skipped: NEON_URL is set but uv was not found", file=err)
            return
        try:
            subprocess.run(uv_command(uv, "--quiet"), stdout=subprocess.DEVNULL, stderr=err,
                           timeout=SYNC_TIMEOUT)
        except Exception:
            traceback.print_exc(file=err)


if __name__ == "__main__":
    main()
