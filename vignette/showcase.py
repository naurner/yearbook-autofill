"""Showcase renders of a template: every page once, every slot filled with real photos, plus a version
with numbered group-photo places. Used by the bot to show templates and where chosen photos go.
Output: compiled/<tpl>/showcase/<page>.jpg and <page>_nums.jpg."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .compile import COMPILED
from .config import class_photo_labels, field_slots
from .plan import build_plans, group_slot_order
from .preview import load_page, render_page

NAMES = ["Асанова Айпери", "Бекова Алина", "Жумабаев Нурлан", "Касымова Айгерим", "Мамытова Зарина",
         "Осмонов Тимур", "Садыкова Мээрим", "Токтосунова Асель", "Усенов Бектур", "Абдыкадырова Жасмин",
         "Алиев Эмир", "Байматова Адель", "Жээнбеков Алинур", "Исмаилова Сезим", "Кадыров Азамат",
         "Муратова Айжан", "Нурланова Дана", "Omurbekov Arsen", "Рахимова Амина", "Сатыбалдиев Ислам"]
SAMPLE_FIELDS = {"Год выпуска": "2026", "Класс": "11 “А”", "Город": "Г.БИШКЕК",
                 "Школа": "ШКОЛА-ГИМНАЗИЯ №13\nГОРОДА БИШКЕК",
                 "Классный руководитель: имя": "СВЕТЛАНА", "Классный руководитель: фамилия": "ТИХОНОВА"}
WIDTH = 1400


def showcase_dir(template, root=COMPILED):
    return Path(root) / template / "showcase"


def _class(cfg, manifest, portraits, groups):
    capacity = 1
    for p in cfg["pages"]:
        if p.get("role") == "students":
            from .config import manifest_page, records
            explicit = {int(k) for k in p.get("photos", {})}
            capacity = max(capacity, sum(1 for i, r in enumerate(records(manifest_page(manifest, p["page"])))
                                         if i not in explicit and r["photo"] is not None))
    names = (NAMES * (capacity // len(NAMES) + 1))[:capacity]
    students = []
    for i, name in enumerate(names):
        surname, first = name.split(" ", 1)
        students.append({"name": name, "surname": surname, "first": first, "quote": "Лучшие годы — впереди",
                         "cover": portraits[i % len(portraits)], "portrait": portraits[i % len(portraits)],
                         "group": [], "pages": None, "row": i + 2})
    labels = {f["label"] for f in field_slots(cfg, manifest) if not f["personal"]}
    return {"class_name": "Образец", "fields": {k: v for k, v in SAMPLE_FIELDS.items() if k in labels},
            "class_photos": {label: portraits[0] for label in class_photo_labels(cfg)},
            "students": students, "teachers": [], "common_photos": list(groups), "errors": [], "warnings": [],
            "template_grids": True}


def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def number_places(img, bounds_list, scale=1.0):
    """Big numbered badges in the middle of each place (1-based, in fill order)."""
    img = img.convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for n, b in enumerate(bounds_list, 1):
        l, t, r, bt = (v * scale for v in b)
        l, t, r, bt = max(0, l), max(0, t), min(img.width, r), min(img.height, bt)
        cx, cy = (l + r) / 2, (t + bt) / 2
        rad = max(16, min(70, min(r - l, bt - t) * 0.22))
        d.rectangle([l + 2, t + 2, r - 2, bt - 2], outline=(255, 214, 0, 255), width=max(2, int(rad / 8)))
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(255, 214, 0, 235), outline=(0, 0, 0, 255),
                  width=max(2, int(rad / 10)))
        d.text((cx, cy), str(n), font=_font(int(rad * 1.15)), fill=(0, 0, 0, 255), anchor="mm")
    return Image.alpha_composite(img, over).convert("RGB")


def build_showcase(template, cfg, manifest, portraits, groups, root=COMPILED, width=WIDTH):
    """Render every page of the template once; returns {page: (jpg, nums_jpg | None)}."""
    data = _class(cfg, manifest, portraits, groups)
    plans, errors, _ = build_plans(cfg, manifest, data, Path(portraits[0]).parent)
    if errors:
        raise ValueError("; ".join(errors[:5]))
    return save_showcase(template, cfg, manifest, plans[0]["pages"], root, width)


def save_showcase(template, cfg, manifest, fills, root=COMPILED, width=WIDTH):
    """Render the first fill of every page (e.g. the studio's print samples); returns
    {page: (jpg, nums_jpg | None)}."""
    out = showcase_dir(template, root)
    out.mkdir(parents=True, exist_ok=True)
    done, result = set(), {}
    for fill in fills:
        if fill["page"] in done:
            continue                                   # grid copies and repeats: once is enough
        done.add(fill["page"])
        page_json, page_dir, font_dir = load_page(Path(root) / template, fill["page"])
        img = render_page(fill, page_json, page_dir, font_dir)
        k = width / img.width
        small = img.resize((width, round(img.height * k)), Image.LANCZOS)
        jpg = out / f"{fill['page']}.jpg"
        small.save(jpg, quality=86, optimize=True)
        order = group_slot_order(cfg, manifest, fill["page"])
        nums = None
        if order:
            bounds = {it["photo"]: it["bounds"] for it in page_json["stack"] if "photo" in it}
            nums = out / f"{fill['page']}_nums.jpg"
            number_places(small, [bounds[s] for s in order if s in bounds], k).save(nums, quality=86, optimize=True)
        result[fill["page"]] = (jpg, nums)
    return result
