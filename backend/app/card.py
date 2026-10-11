"""Server-side roast card (1200x630 PNG) for link previews (Open Graph / Twitter).

Uses Pillow's bundled FreeType font (portable to the server, no font licensing issues);
heavier weights come from stroke width. All text is repo-derived and only drawn, never
interpreted.
"""
import io
import textwrap

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = (17, 16, 24)
INK = (255, 248, 235)
FLAME = (255, 77, 46)
GOLD = (255, 210, 63)
MUTED = (170, 164, 190)
GOOD = (46, 204, 113)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def score_color(score: int | None) -> tuple:
    if score is None:
        return MUTED
    return GOOD if score >= 70 else GOLD if score >= 40 else FLAME


def _fit_roast(draw: ImageDraw.ImageDraw, text: str, box_w: int, box_h: int) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """Largest font size at which the roast fits the box (ellipsis as a last resort)."""
    for size in (44, 40, 36, 32, 29, 26, 23):
        f = _font(size)
        avg = max(1, draw.textlength("abcdefghijklmnopqrstuvwxyz", font=f) / 26)
        lines = textwrap.wrap(text, width=max(10, int(box_w / avg)))
        if len(lines) * int(size * 1.3) <= box_h:
            return lines, f
    f = _font(23)
    avg = max(1, draw.textlength("abcdefghijklmnopqrstuvwxyz", font=f) / 26)
    lines = textwrap.wrap(text, width=int(box_w / avg))
    max_lines = box_h // int(23 * 1.3)
    return lines[:max_lines - 1] + [lines[max_lines - 1].rstrip(".,; ") + "…"], f


def render_card(*, repo: str, score: int | None, roast: str, site: str, source: str = "llm",
                delta: int | None = None) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # flame stripe + header
    d.rectangle([0, 0, W, 14], fill=FLAME)
    d.text((56, 44), "PREJUDGE", font=_font(34), fill=INK, stroke_width=1, stroke_fill=INK)
    d.text((56 + d.textlength("PREJUDGE", font=_font(34)) + 18, 50), "roasted before the judges",
           font=_font(26), fill=MUTED)
    tag = "#neatHack"
    d.text((W - 56 - d.textlength(tag, font=_font(30)), 46), tag, font=_font(30), fill=GOLD,
           stroke_width=1, stroke_fill=GOLD)

    # score block
    col = score_color(score)
    d.rounded_rectangle([56, 130, 376, 450], radius=36, fill=(30, 28, 42), outline=col, width=6)
    s = "?" if score is None else str(score)
    big = _font(150)
    sw = d.textlength(s, font=big)
    d.text((216 - sw / 2, 170), s, font=big, fill=col, stroke_width=3, stroke_fill=col)
    d.text((216 - d.textlength("/ 100", font=_font(36)) / 2, 360), "/ 100", font=_font(36), fill=MUTED)
    if delta and delta > 0:  # progress since the last check, only when it went up
        up = f"+{delta} since last check"
        d.text((216 - d.textlength(up, font=_font(26)) / 2, 466), up, font=_font(26), fill=GOOD,
               stroke_width=1, stroke_fill=GOOD)

    # roast
    lines, f = _fit_roast(d, f"“{roast.strip()}”", W - 420 - 56, 330)
    y = 135
    for line in lines:
        d.text((420, y), line, font=f, fill=INK)
        y += int(f.size * 1.3)
    if source != "llm":
        d.text((420, 462), "quick facts mode: full roast coming later", font=_font(22), fill=MUTED)

    # footer
    d.line([56, 520, W - 56, 520], fill=(48, 45, 64), width=2)
    repo_txt = repo if len(repo) <= 48 else repo[:47] + "…"
    d.text((56, 545), repo_txt, font=_font(38), fill=INK, stroke_width=1, stroke_fill=INK)
    d.text((W - 56 - d.textlength(site, font=_font(30)), 551), site, font=_font(30), fill=FLAME)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
