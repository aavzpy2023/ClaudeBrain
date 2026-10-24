"""Regenerate assets/social-preview.png, the image shown when the repo link is shared.

Usage: uv run --with pillow python assets/make_social.py
Upload it in GitHub → Settings → General → Social preview.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "social-preview.png"
FONTS = Path("/usr/share/fonts/noto")
W, H = 1280, 640
BG, FG, MUTED, ACCENT, CHIP = (20, 22, 28), (236, 238, 242), (150, 156, 168), (217, 119, 87), (38, 41, 50)

TITLE = "ClaudeBrain"
TAGLINE = "Your entire Claude history —\nevery device, every word, one place."
CHIPS = ["word for word", "local-first", "every computer", "claude.ai & phone", "blame: the why",
         "free: no AI at save time"]
INSTALL = "/plugin marketplace add aavzpy2023/ClaudeBrain"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    emoji = Image.new("RGBA", (160, 160))
    ImageDraw.Draw(emoji).text((0, 0), "🧠", font=font("NotoColorEmoji.ttf", 109), embedded_color=True)
    img.paste(emoji.resize((120, 120)), (80, 92), emoji.resize((120, 120)))
    draw.text((224, 70), TITLE, font=font("NotoSans-Bold.ttf", 96), fill=FG)
    draw.multiline_text((84, 230), TAGLINE, font=font("NotoSans-SemiBold.ttf", 52), fill=FG, spacing=14)

    x, y = 84, 420
    chip_font = font("NotoSans-Regular.ttf", 26)
    for chip in CHIPS:
        w = int(draw.textlength(chip, font=chip_font)) + 36
        if x + w > W - 80:
            x, y = 84, y + 58
        draw.rounded_rectangle((x, y, x + w, y + 44), radius=22, fill=CHIP)
        draw.text((x + 18, y + 6), chip, font=chip_font, fill=MUTED)
        x += w + 14
    draw.text((84, H - 74), INSTALL, font=font("NotoSansMono-Regular.ttf", 28), fill=ACCENT)
    img.save(OUT, optimize=True)
    print(f"{OUT} — {OUT.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
