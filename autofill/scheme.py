"""Page preview with numbered slots, so the operator knows which Excel row is which cell."""
from PIL import Image, ImageDraw, ImageFont

GROUP_COLOR = (220, 30, 30)
FIELD_COLOR = (30, 90, 220)


def _font(size):
    for name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _scaled(bounds, k):
    return [bounds["left"] * k, bounds["top"] * k, bounds["right"] * k, bounds["bottom"] * k]


def _label(draw, x, y, text, font, color):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    w, h, pad = right - left, bottom - top, 4
    draw.rectangle([x - w / 2 - pad, y - h / 2 - pad, x + w / 2 + pad, y + h / 2 + pad], fill=color + (235,))
    draw.text((x - w / 2 - left, y - h / 2 - top), text, font=font, fill=(255, 255, 255, 255))


def draw_scheme(page_manifest, preview_path, out_path):
    im = Image.open(preview_path).convert("RGB")
    k = im.width / page_manifest["width"]
    draw = ImageDraw.Draw(im, "RGBA")
    font = _font(max(14, im.width // 70))
    for group in page_manifest["groups"]:
        for n, rec in enumerate(group["records"], 1):
            anchor = rec["photo"] or rec["texts"][0]
            b = _scaled(anchor["bounds"], k)
            draw.rectangle(b, outline=GROUP_COLOR + (255,), width=3, fill=GROUP_COLOR + (40,))
            _label(draw, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, str(n), font, GROUP_COLOR)
    for f in page_manifest["fields"]:
        b = _scaled(f["bounds"], k)
        draw.rectangle(b, outline=FIELD_COLOR + (255,), width=2)
        _label(draw, b[0], b[1], f"П{f['number']}", font, FIELD_COLOR)
    im.save(out_path)
