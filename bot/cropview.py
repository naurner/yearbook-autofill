"""Framing a photo inside its slot: crop = [zoom, fx, fy] (see vignette.preview.place_photo) and a
picture of the result for the student to check."""
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

from vignette.preview import ANCHOR_Y, place_photo

DEFAULT = [1.0, 0.5, ANCHOR_Y]
STEP, ZOOM, MAX_ZOOM = 0.1, 1.2, 3.0
SIZE = 720


def adjust(crop, move):
    z, fx, fy = crop or DEFAULT
    if move == "l":
        fx -= STEP
    elif move == "r":
        fx += STEP
    elif move == "u":
        fy -= STEP
    elif move == "d":
        fy += STEP
    elif move == "zi":
        z *= ZOOM
    elif move == "zo":
        z /= ZOOM
    elif move == "reset":
        z, fx, fy = DEFAULT
    return [round(min(MAX_ZOOM, max(1.0, z)), 3), round(min(1.0, max(0.0, fx)), 3), round(min(1.0, max(0.0, fy)), 3)]


def crop_picture(photo, slot_bounds, crop, cache_dir):
    """The photo as it will sit in a slot of this shape."""
    w = slot_bounds["right"] - slot_bounds["left"]
    h = slot_bounds["bottom"] - slot_bounds["top"]
    k = SIZE / max(w, h)
    W, H = max(1, round(w * k)), max(1, round(h * k))
    key = hashlib.sha1(f"{photo}|{W}x{H}|{crop}".encode()).hexdigest()[:16]
    out = Path(cache_dir) / "adj" / f"{key}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        canvas = Image.new("RGBA", (W, H), (255, 255, 255, 255))
        place_photo(canvas, photo, [0, 0, W, H], crop=crop or DEFAULT)
        img = canvas.convert("RGB")
        ImageDraw.Draw(img).rectangle([0, 0, W - 1, H - 1], outline=(255, 214, 0), width=4)
        img.save(out, quality=88)
    return str(out)


ADJUST_BUTTONS = [[("⬅️", "adj:l"), ("⬆️", "adj:u"), ("⬇️", "adj:d"), ("➡️", "adj:r")],
                  [("➖ Отдалить", "adj:zo"), ("➕ Приблизить", "adj:zi"), ("↺ Сброс", "adj:reset")],
                  [("✅ Готово", "adj:done")]]
