"""Claude Code hook entry point: archive new messages, then optionally push to Neon.

Usage (from settings.json, exec form, no shell — same on Linux, macOS and Windows):
  python brain/hook.py [--sync --uv /path/to/uv]
Never fails the hook: errors go to the log next to the database, exit code is always 0.
"""
import argparse
import subprocess
import sys
import traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.db import connect, db_path
from brain.ingest import DEFAULT_ROOT, ingest

REPO = Path(__file__).resolve().parent.parent
SYNC_TIMEOUT = 100  # below the hook's own 120 s timeout


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sync", action="store_true", help="push to Neon after ingesting")
    parser.add_argument("--uv", help="uv executable used to run the sync with its dependencies")
    args = parser.parse_args(argv)

    log = db_path().parent / "ingest.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as err:
        try:
            conn = connect()
            ingest(conn, DEFAULT_ROOT)
            conn.close()
        except Exception:
            traceback.print_exc(file=err)
        if args.sync and args.uv:
            try:
                subprocess.run(
                    [args.uv, "run", "--quiet", "--project", str(REPO),
                     str(REPO / "brain" / "sync.py"), "--quiet"],
                    stdout=subprocess.DEVNULL, stderr=err, timeout=SYNC_TIMEOUT,
                )
            except Exception:
                traceback.print_exc(file=err)


if __name__ == "__main__":
    main()
