"""Regenerate assets/demo.gif: real `claude-brain` commands run against a synthetic archive.

Usage: uv run --with pillow python assets/make_demo.py
Nothing personal goes in: the transcripts below are made up, and HOME points at a temp folder so
no real database, settings or cloud credentials are read.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "demo.gif"
FONT = "/usr/share/fonts/noto/NotoSansMono-Regular.ttf"
COLS, ROWS, SIZE, PAD = 96, 13, 15, 14
BG, FG, PROMPT = (24, 26, 33), (220, 223, 228), (120, 200, 140)

SESSIONS = [
    ("web-shop", "Checkout database choice", "2026-09-02T10:00:00Z", [
        ("user", "Should the checkout service use MongoDB or PostgreSQL?"),
        ("assistant", "PostgreSQL: orders need transactions across stock and payments, and the reports "
                      "are relational. We keep MongoDB out of the critical path."),
    ]),
    ("web-shop", "Slow product search", "2026-09-15T16:20:00Z", [
        ("user", "Product search is very slow since the catalog import."),
        ("assistant", "The query scans the whole table. Added a trigram index on products.name: "
                      "p95 latency dropped from 1.8 s to 40 ms."),
    ]),
    ("web-shop", "Payments retry policy", "2026-10-03T09:10:00Z", [
        ("user", "Payment webhooks sometimes arrive twice."),
        ("assistant", "Made the handler idempotent with the provider's event id as a unique key, "
                      "and retries back off exponentially up to 5 attempts."),
    ]),
    ("thesis", "Chapter 2 structure", "2026-09-20T18:00:00Z", [
        ("user", "How should I structure the related-work chapter?"),
        ("assistant", "Three sections: classical models, graph neural networks, and the gap your "
                      "method fills. The PostgreSQL-backed corpus goes to the appendix."),
    ]),
    ("data-pipeline", "Nightly job performance", "2026-10-10T07:45:00Z", [
        ("user", "The nightly ETL performance got worse: it takes four hours now."),
        ("assistant", "Switched the loader to COPY into PostgreSQL in batches of 50k rows; the job "
                      "now finishes in 25 minutes."),
    ]),
]

STEPS = [
    "claude-brain projects",
    'claude-brain search "slow OR latency OR performance"',
    "claude-brain session 00000001",
]


def build_archive(home: Path) -> None:
    root = home / ".claude" / "projects"
    for i, (project, title, ts, messages) in enumerate(SESSIONS):
        sid = f"{i:08x}-demo-0000-0000-000000000000"
        cwd = f"/code/{project}"
        lines = [{"type": "ai-title", "aiTitle": title, "sessionId": sid}]
        for j, (role, text) in enumerate(messages):
            minute = f"{ts[:17]}{j:02d}{ts[19:]}"  # one second apart
            lines.append({"type": role, "uuid": f"{sid}-{j}", "sessionId": sid, "timestamp": minute,
                          "cwd": cwd, "entrypoint": "cli", "isSidechain": False,
                          "message": {"role": role, "content": [{"type": "text", "text": text}]}})
        folder = root / cwd.replace("/", "-")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{sid}.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")


def run(cmd: str, env: dict) -> list[str]:
    argv = [sys.executable, str(REPO / "bin" / "claude-brain"), *shlex.split(cmd)[1:]]
    out = subprocess.run(argv, capture_output=True, text=True, env=env).stdout
    rows = []
    for line in out.rstrip().splitlines():
        rows += textwrap.wrap(line, COLS, subsequent_indent="    ") or [""]
    return rows


def frame(lines: list[tuple[str, tuple]], font) -> Image.Image:
    w = PAD * 2 + int(font.getlength("M") * COLS)
    h = PAD * 2 + ROWS * (SIZE + 5)
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    for row, (text, color) in enumerate(lines[-ROWS:]):
        draw.text((PAD, PAD + row * (SIZE + 5)), text, font=font, fill=color)
    return img


def main() -> None:
    font = ImageFont.truetype(FONT, SIZE)
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        build_archive(home)
        env = {**os.environ, "HOME": str(home), "CLAUDE_BRAIN_DB": str(home / "brain.db"),
               "CLAUDE_CONFIG_DIR": str(home / ".claude")}
        env.pop("NEON_URL", None)
        subprocess.run([sys.executable, str(REPO / "bin" / "claude-brain"), "ingest", "--full"],
                       env=env, capture_output=True, check=True)
        frames, durations, screen = [], [], []
        for step in STEPS:
            screen = []  # one command per screen keeps the text large and readable
            for k in range(0, len(step) + 1, 2):
                frames.append(frame(screen + [("$ " + step[:k] + "▌", PROMPT)], font))
                durations.append(45)
            screen.append(("$ " + step, PROMPT))
            screen += [(row, FG) for row in run(step, env)]
            frames.append(frame(screen, font))
            durations.append(4200)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   optimize=True, disposal=2)
    print(f"{OUT} — {len(frames)} frames, {OUT.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
