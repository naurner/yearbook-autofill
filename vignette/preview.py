"""Fast previews without Photoshop: compose compiled pages (compile.py) with photos and texts,
add a watermark, glue a PDF per student. This is what the bot runs on a server."""
import json
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from .compile import COMPILED, PREVIEW_DPI, with_font_paths
from .final import unique_fills
from .names import safe_file_name
from .pdfmerge import images_to_pdf
from .plan import page_key
from .textrender import render

ANCHOR_Y = 0.3
MIN_SHRINK = 0.6
WATERMARK = "ОБРАЗЕЦ"


def load_page(root, page):
    """-> (page_json, page_dir, font_dir) for render_page."""
    root = Path(root)
    page_dir = root / page
    if not (page_dir / "page.json").exists():
        raise FileNotFoundError(f"нет разобранной страницы {page_dir} — выполните: python vignette.py compile")
    return json.loads((page_dir / "page.json").read_text(encoding="utf-8")), page_dir, root / "fonts"


@lru_cache(maxsize=64)
def _png(path):
    return Image.open(path).convert("RGBA") if "mask_" not in Path(path).name else Image.open(path).convert("L")


def paste_rgba(canvas, img, x, y):
    """alpha_composite that tolerates images sticking out of the canvas."""
    x, y = round(x), round(y)
    l, t = max(0, x), max(0, y)
    r, b = min(canvas.width, x + img.width), min(canvas.height, y + img.height)
    if r <= l or b <= t:
        return
    canvas.alpha_composite(img.crop((l - x, t - y, r - x, b - y)), (l, t))


def place_photo(canvas, path, bounds, masks=None, crop=None):
    """Cover-fit the photo into bounds; masks = [(L image, (x, y))] in page pixels, None = whole rect.
    crop = [zoom, fx, fy]: zoom >= 1 on top of cover-fit, fx/fy = where the window sits in the scaled
    photo (0 = left/top edge, 1 = right/bottom). Default: centered horizontally, 30 % from the top."""
    L, T = round(bounds[0]), round(bounds[1])
    W, H = max(1, round(bounds[2]) - L), max(1, round(bounds[3]) - T)
    with Image.open(path) as src:
        src.draft("RGB", (W * 2, H * 2))
        im = ImageOps.exif_transpose(src).convert("RGB")
    zoom, fx, fy = (crop or (1.0, 0.5, ANCHOR_Y))[:3]
    rot = crop[3] if crop and len(crop) > 3 else 0
    if rot:
        im = im.rotate(-rot, expand=True)                  # clockwise, as Photoshop's rotateCanvas
    s = max(W / im.width, H / im.height) * max(1.0, zoom)
    nw, nh = max(W, math.ceil(im.width * s)), max(H, math.ceil(im.height * s))
    im = im.resize((nw, nh), Image.LANCZOS)
    ox, oy = round((nw - W) * fx), round((nh - H) * fy)
    im = im.crop((ox, oy, ox + W, oy + H)).convert("RGBA")
    if masks is not None:
        alpha = Image.new("L", (W, H), 0)
        for m, (x, y) in masks:
            layer = Image.new("L", (W, H), 0)
            layer.paste(m, (round(x) - L, round(y) - T))
            alpha = ImageChops.lighter(alpha, layer)
        im.putalpha(alpha)
    paste_rgba(canvas, im, L, T)


def text_image(spec, value, font_dir, dx=0.0, dy=0.0):
    """Text like fill_worker.jsx: same styles, point text over its limit shrinks (>= 60 %).
    Returns (RGBA image, x, y, shrink factor) in page pixels."""
    spec = with_font_paths(spec, font_dir)
    c = spec.get("calib", {"scale": 1.0, "dx": 0.0, "dy": 0.0})
    img, (ox, oy) = render(spec, value, c["scale"])
    x0, y0 = spec["origin"][0] + c["dx"] + dx - ox, spec["origin"][1] + c["dy"] + dy - oy
    k = 1.0
    bb = img.getchannel("A").getbbox()
    if bb and "PARAGRAPH" not in spec.get("textKind", "") and value != spec["text"]:
        run = (bb[2] - bb[0]) if spec.get("horizontal", True) else (bb[3] - bb[1])
        if run > spec["limit"]:
            k = max(MIN_SHRINK, spec["limit"] / run)
            before = (bb[0] + x0, bb[1] + y0, bb[2] + x0, bb[3] + y0)
            img, _ = render(spec, value, c["scale"] * k)
            nb = img.getchannel("A").getbbox()
            just = spec.get("justification", "")
            cy = (before[1] + before[3]) / 2 - (nb[1] + nb[3]) / 2
            if spec.get("horizontal", True) and "LEFT" in just:
                x0, y0 = before[0] - nb[0], cy
            elif spec.get("horizontal", True) and "RIGHT" in just:
                x0, y0 = before[2] - nb[2], cy
            else:
                x0, y0 = (before[0] + before[2]) / 2 - (nb[0] + nb[2]) / 2, cy
    return img, x0, y0, k


def draw_text(canvas, spec, value, font_dir, dx=0.0, dy=0.0):
    img, x0, y0, k = text_image(spec, value, font_dir, dx, dy)
    paste_rgba(canvas, img, x0, y0)
    return k


def render_page(fill, page, page_dir, font_dir):
    canvas = Image.new("RGBA", tuple(page["size"]), (255, 255, 255, 255))
    scale = page["scale"]
    specs = {it["text"]: it["spec"] for it in page["stack"] if "text" in it}
    for item in page["stack"]:
        if "run" in item:
            paste_rgba(canvas, _png(str(page_dir / item["run"])), *item["offset"])
        elif "photo" in item:
            path = fill["photos"].get(item["photo"])
            if path:
                masks = []
                if item.get("mask"):
                    masks.append((_png(str(page_dir / item["mask"])), item["mask_offset"]))
                for sid in item.get("mask_texts", []):
                    img, x0, y0, _ = text_image(specs[sid], fill["texts"].get(sid, specs[sid]["text"]), font_dir)
                    masks.append((img.getchannel("A"), (x0, y0)))
                clip = masks or item.get("clip_only")
                place_photo(canvas, path, item["bounds"], masks if clip else None,
                            (fill.get("crops") or {}).get(item["photo"]))
        elif item["text"] not in fill.get("hide", ()):
            spec = item["spec"]
            draw_text(canvas, spec, fill["texts"].get(item["text"], spec["text"]), font_dir)
            for c in fill.get("clones", []):
                if c["of"] == item["text"]:
                    draw_text(canvas, spec, c["value"], font_dir, c["dx"] * scale, c["dy"] * scale)
    if fill.get("logo"):
        place_logo(canvas, fill["logo"], scale)
    return canvas.convert("RGB")


def place_logo(canvas, logo, scale):
    """The studio logo on top of everything, centered on logo["center"] (template pixels)."""
    img = _png(logo["file"])
    w = max(1, round(logo["width"] * scale))
    h = max(1, round(img.height * w / img.width))
    im = img.resize((w, h), Image.LANCZOS)
    paste_rgba(canvas, im, logo["center"][0] * scale - w / 2, logo["center"][1] * scale - h / 2)


@lru_cache(maxsize=8)
def _watermark_tile(size):
    try:
        font = ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        font = ImageFont.load_default(size)
    w = int(font.getlength(WATERMARK)) + size
    tile = Image.new("RGBA", (w, size * 2), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((size // 2, size), WATERMARK, font=font, fill=(255, 255, 255, 110), anchor="lm",
                              stroke_width=max(1, size // 30), stroke_fill=(0, 0, 0, 60))
    return tile.rotate(30, expand=True, resample=Image.BICUBIC)


def add_watermark(img):
    base = img.convert("RGBA")
    tile = _watermark_tile(max(12, img.height // 9))
    for y in range(-tile.height // 2, img.height, int(tile.height * 0.9)):
        shift = (y // max(1, tile.height)) % 2 * tile.width // 2
        for x in range(-tile.width + shift, img.width, tile.width):
            paste_rgba(base, tile, x, y)
    return base.convert("RGB")


def render_cached(fill, root, cache, watermark):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    page = load_page(root, fill["page"])
    stamp = int((page[1] / "page.json").stat().st_mtime)          # recompiled template -> new renders
    jpg = cache / f"{page_key(fill)}-{stamp}{'' if watermark else '-clean'}.jpg"
    if not jpg.exists():
        img = render_page(fill, *page)
        if watermark:
            img = add_watermark(img)
        tmp = jpg.with_suffix(".tmp.jpg")
        img.save(tmp, quality=85, optimize=True)
        tmp.replace(jpg)
    return jpg


def page_thumbnail(template, cfg, manifest, page, root=None, width=900):
    """Template page as students will get it (fixed texts, hidden layers, sample name), no photos."""
    from .plan import sample_fill
    root = Path(root or COMPILED / template)
    out = root / "thumbs" / f"{page}.jpg"
    page_json = root / page / "page.json"
    if not out.exists() or out.stat().st_mtime < page_json.stat().st_mtime:
        img = render_page(sample_fill(cfg, manifest, page), *load_page(root, page))
        img.thumbnail((width, width))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, quality=85)
    return out


def student_preview(plan, root, cache, out_dir, watermark=True):
    """One student's preview PDF (pages rendered once and cached by content)."""
    images = [render_cached(f, root, cache, watermark) for f in plan["pages"]]
    return images_to_pdf(images, Path(out_dir) / plan["file"], PREVIEW_DPI)


def build_previews(plans, class_name, template, out_dir, watermark=True, root=None, on_progress=print):
    root = Path(root or COMPILED / template)
    class_dir = Path(out_dir) / f"{safe_file_name(class_name)} (превью)"
    cache = class_dir / "_страницы"
    total = len(unique_fills(plans))
    on_progress(f"Уникальных страниц: {total}")
    for i, plan in enumerate(plans, 1):
        student_preview(plan, root, cache, class_dir, watermark)
        on_progress(f"  {i}/{len(plans)} {plan['file']}")
    return class_dir
