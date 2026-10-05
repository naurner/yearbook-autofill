import json
from pathlib import Path

import fitz
import pytest
from PIL import Image

from vignette.preview import add_watermark, draw_text, load_page, render_page, student_preview

FONT_DIR = Path(__file__).resolve().parents[2] / "Split" / "fonts"
FONT = "DelaGothicOne_Regular.ttf"


def text_spec(text="А", origin=(150, 60), limit=1e9, justification="Justification.CENTER"):
    return {"text": text, "default": text, "kind": "point", "box": None, "matrix": [1, 0, 0, 1],
            "runs": [{"from": 0, "to": len(text) + 1, "font": FONT, "index": 0, "size": 20, "color": [0, 0, 0],
                      "tracking": 0, "leading": None, "caps": False}],
            "paras": [{"from": 0, "to": len(text) + 1, "align": "center"}], "origin": list(origin),
            "calib": {"scale": 1.0, "dx": 0.0, "dy": 0.0}, "limit": limit, "horizontal": True,
            "justification": justification, "textKind": "TextType.POINTTEXT"}


@pytest.fixture
def compiled(tmp_path):
    root = tmp_path / "T"
    page = root / "p1"
    page.mkdir(parents=True)
    (root / "fonts").mkdir()
    (root / "fonts" / FONT).write_bytes((FONT_DIR / FONT).read_bytes())
    Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(page / "run00.png")
    mask = Image.new("L", (25, 50), 255)                     # covers only the left half of the slot
    mask.save(page / "mask_1.png")
    stack = [{"run": "run00.png", "offset": [0, 0]},
             {"photo": "1", "bounds": [10, 10, 60, 60], "mask": "mask_1.png", "mask_offset": [10, 10]},
             {"text": "2", "spec": text_spec()}]
    (page / "page.json").write_text(json.dumps({"page": "p1", "size": [200, 100], "scale": 0.5, "stack": stack}),
                                    encoding="utf-8")
    photo = tmp_path / "blue.jpg"
    Image.new("RGB", (400, 400), (0, 0, 255)).save(photo)
    return root, photo


def fill(photo=None, texts=None, clones=()):
    return {"page": "p1", "copy": 0, "texts": texts or {}, "photos": {"1": str(photo)} if photo else {},
            "clones": list(clones)}


def test_photo_cover_fit_inside_mask(compiled):
    root, photo = compiled
    img = render_page(fill(photo), *load_page(root, "p1"))
    assert img.getpixel((20, 30))[2] > 200 and img.getpixel((20, 30))[0] < 60      # blue inside mask
    assert img.getpixel((50, 30))[0] > 200                                           # red outside mask
    assert img.getpixel((5, 5))[0] > 200


def test_text_drawn_and_changes(compiled):
    root, _ = compiled
    page = load_page(root, "p1")
    a = render_page(fill(), *page)
    b = render_page(fill(texts={"2": "ФАМИЛИЯ"}), *page)
    assert a.tobytes() != b.tobytes()
    assert b.getpixel((150, 55)) != (255, 0, 0)


def test_clone_drawn_with_offset(compiled):
    root, _ = compiled
    page = load_page(root, "p1")
    a = render_page(fill(), *page)
    b = render_page(fill(clones=[{"of": "2", "dx": 0, "dy": 50, "value": "Б"}]), *page)
    diff = [y for y in range(100) if a.crop((100, y, 200, y + 1)).tobytes() != b.crop((100, y, 200, y + 1)).tobytes()]
    assert diff and min(diff) > 62                           # clone at y≈60+50*0.5=85 (dy scaled by page scale)


def test_shrink_to_limit(tmp_path):
    canvas = Image.new("RGBA", (400, 100), (255, 255, 255, 255))
    k = draw_text(canvas, text_spec("А", origin=(200, 60), limit=80), "ОЧЕНЬ ДЛИННАЯ ФАМИЛИЯ", FONT_DIR)
    bb = Image.eval(canvas.convert("L"), lambda v: 255 - v).getbbox()
    assert k == pytest.approx(0.6) or bb[2] - bb[0] <= 84


def test_watermark_changes_pixels():
    img = Image.new("RGB", (300, 200), (255, 255, 255))
    marked = add_watermark(img)
    assert marked.size == img.size and marked.tobytes() != img.tobytes()


def test_student_preview_pdf(compiled, tmp_path):
    root, photo = compiled
    plan = {"name": "Абишева Алия", "file": "Абишева Алия.pdf", "pages": [fill(photo), fill()]}
    out = student_preview(plan, root, tmp_path / "cache", tmp_path / "out", watermark=True)
    with fitz.open(out) as d:
        assert d.page_count == 2


def test_variable_text_extends_photo_mask(compiled):
    root, photo = compiled
    page_json, page_dir, font_dir = load_page(root, "p1")
    page_json["stack"] = [page_json["stack"][0], page_json["stack"][2],
                          {"photo": "1", "bounds": [100, 20, 200, 80], "mask": None, "mask_offset": None,
                           "mask_texts": ["2"], "clip_only": True}]
    img = render_page(fill(photo, texts={"2": "ШШШ"}), page_json, page_dir, font_dir)
    assert img.getpixel((150, 52))[2] > 200 and img.getpixel((150, 52))[0] < 80     # photo inside the letters
    assert img.getpixel((105, 25))[0] > 200                                          # red outside the letters


def test_hidden_text_not_drawn(compiled):
    root, _ = compiled
    page = load_page(root, "p1")
    shown = render_page(fill(), *page)
    f = fill()
    f["hide"] = ["2"]
    hidden = render_page(f, *page)
    assert shown.tobytes() != hidden.tobytes() and hidden.getpixel((150, 55)) == (255, 0, 0)


def test_page_thumbnail_real_template(tmp_path):
    from vignette.cli_common import load_manifest
    from vignette.config import load_template_config
    from vignette.compile import COMPILED
    from vignette.preview import page_thumbnail
    import shutil
    root = tmp_path / "Flight"
    shutil.copytree(COMPILED / "Flight", root, ignore=shutil.ignore_patterns("thumbs"))
    man = load_manifest("Flight")
    out = page_thumbnail("Flight", load_template_config("Flight", man), man, "02", root=root, width=400)
    assert Image.open(out).width == 400


def test_photo_crop_zoom_and_focus(tmp_path):
    from vignette.preview import place_photo
    photo = tmp_path / "lr.jpg"
    im = Image.new("RGB", (400, 400), (255, 0, 0))
    im.paste((0, 0, 255), (200, 0, 400, 400))                  # left red, right blue
    im.save(photo)
    canvas = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    place_photo(canvas, photo, [0, 0, 100, 100])
    assert canvas.getpixel((10, 50))[0] > 200 and canvas.getpixel((90, 50))[2] > 200     # default: both halves
    place_photo(canvas, photo, [0, 0, 100, 100], crop=[2.0, 0.0, 0.5])
    assert canvas.getpixel((90, 50))[0] > 200                                              # zoomed on the left
    place_photo(canvas, photo, [0, 0, 100, 100], crop=[2.0, 1.0, 0.5])
    assert canvas.getpixel((10, 50))[2] > 200                                              # zoomed on the right


def test_showcase_real_template(tmp_path):
    import shutil
    from vignette.cli_common import load_manifest
    from vignette.compile import COMPILED
    from vignette.config import load_template_config
    from vignette.showcase import build_showcase
    shutil.copytree(COMPILED / "Flight", tmp_path / "Flight", ignore=shutil.ignore_patterns("thumbs", "showcase"))
    photos = tmp_path / "ph"
    photos.mkdir()
    portraits = [str(photos / f"p{i}.jpg") for i in range(3)]
    groups = [str(photos / f"g{i}.jpg") for i in range(3)]
    for i, p in enumerate(portraits):
        Image.new("RGB", (300, 450), (200, 40 * i, 40)).save(p)
    for i, g in enumerate(groups):
        Image.new("RGB", (450, 300), (40, 40 * i, 200)).save(g)
    man = load_manifest("Flight")
    res = build_showcase("Flight", load_template_config("Flight", man), man, portraits, groups, root=tmp_path, width=500)
    assert set(res) == {"cover", "01", "02", "03", "04", "05", "06"}
    assert res["cover"][1] is not None and res["03"][1] is not None      # Flight's back cover takes a group photo
    assert res["01"][1] is None
    assert Image.open(res["03"][0]).width == 500
    assert Image.open(res["03"][1]).tobytes() != Image.open(res["03"][0]).tobytes()
