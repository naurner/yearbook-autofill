"""Page layout -> manifest of fillable slots: one group of repeated records (photo + captions)
per page and one-off text fields. See the design spec for the rules."""
import math
import re
from collections import Counter

from .layout import center, pair_captions, photo_slots, reading_order

REPEAT_MIN = 3
FIELD_SLACK = 1.15
PHOTO_COL = "Фото (файл)"


def one_line(text, limit=60):
    s = re.sub(r"[\r\n\x03]+", " / ", text or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def unique_sheet_name(base, taken):
    base = re.sub(r"[\[\]:*?/\\]", "", base)[:31]
    name, k = base, 2
    while name in taken:
        suffix = f" {k}"
        name = base[: 31 - len(suffix)] + suffix
        k += 1
    taken.add(name)
    return name


def position_hint(b, width, height):
    cx, cy = center(b)
    side = "левая" if cx < width / 2 else "правая"
    third = "верх" if cy < height / 3 else ("низ" if cy > 2 * height / 3 else "середина")
    return f"{side} половина, {third}"


def is_horizontal(item):
    """Text direction from the layer's rotation (read from its transform); box shape is only a
    fallback — a two-digit "20" in huge type has a tall box but is still horizontal text."""
    rot = item.get("rotation")
    if rot is not None:
        r = math.radians(rot)
        return abs(math.cos(r)) >= abs(math.sin(r))
    b = item["bounds"]
    return (b["right"] - b["left"]) >= (b["bottom"] - b["top"])


def run_limit(text_bounds, photo_bounds=None, horizontal=None):
    """How long (px, along the text direction) the text may grow before it is shrunk.
    Horizontal captions under a photo may use the photo width; anything else gets 15% slack."""
    w = text_bounds["right"] - text_bounds["left"]
    h = text_bounds["bottom"] - text_bounds["top"]
    if horizontal is None:
        horizontal = w >= h
    if horizontal and photo_bounds:
        return max(w, photo_bounds["right"] - photo_bounds["left"])
    return (w if horizontal else h) * FIELD_SLACK


def _slot(item):
    slot = {"path": item["path"], "name": item["name"], "bounds": item["bounds"]}
    if not item.get("effectiveVisible", True):
        slot["hidden"] = True  # designer-hidden photo placeholder: the worker shows it when filled
    return slot


def _hidden_by_designer(item):
    """The layer itself is switched off while all its groups are visible."""
    return not item.get("visible", True) and item.get("parentVisible", False)


def _text_slot(item, column=None, photo=None):
    b = item["bounds"]
    horizontal = is_horizontal(item)
    slot = _slot(item)
    slot.update({
        "default": item["text"],
        "font": item.get("font"),
        "styleRuns": item.get("styleRuns", 1),
        "textKind": item.get("textKind", ""),
        "justification": item.get("justification", ""),
        "horizontal": horizontal,
        "limit": run_limit(b, photo["bounds"] if photo else None, horizontal),
    })
    if column:
        slot["column"] = column
    return slot


def build_page(layout, page, taken_sheets):
    visible = [x for x in layout["leaves"] if x.get("effectiveVisible", True)]
    photos = [x for x in photo_slots(layout["leaves"])
              if x.get("effectiveVisible", True) or _hidden_by_designer(x)]
    texts = [x for x in visible if x["kind"] == "text"]

    counts = Counter(t["text"].strip() for t in texts)
    caption_types = [txt for txt, n in counts.items() if n >= REPEAT_MIN]
    columns = []
    for ctype in caption_types:
        col = "Подпись: " + one_line(ctype, 40)
        while col in columns:
            col += "'"
        columns.append(col)

    records = [{"photo": p, "texts": []} for p in photos]
    orphans, captions = [], set()
    for ctype, col in zip(caption_types, columns):
        caps = [t for t in texts if t["text"].strip() == ctype]
        pairs = pair_captions([p["bounds"] for p in photos], [c["bounds"] for c in caps])
        for ci, cap in enumerate(caps):
            captions.add(id(cap))
            if ci in pairs:
                records[pairs[ci]]["texts"].append((col, cap))
            else:
                orphans.append({"photo": None, "texts": [(col, cap)]})
    records += orphans

    groups = []
    if records:
        anchors = [r["photo"]["bounds"] if r["photo"] else r["texts"][0][1]["bounds"] for r in records]
        ordered = [records[i] for i in reading_order(anchors, layout["width"])]
        n_photos = sum(1 for r in ordered if r["photo"])
        base = f"Стр {page} ({n_photos} фото)" if n_photos else f"Стр {page}"
        groups.append({
            "sheet": unique_sheet_name(base, taken_sheets),
            "columns": columns,
            "hasPhotos": n_photos > 0,
            "records": [{
                "photo": _slot(r["photo"]) if r["photo"] else None,
                "texts": [_text_slot(item, col, r["photo"]) for col, item in r["texts"]],
            } for r in ordered],
        })

    field_items = [t for t in texts if id(t) not in captions]
    fields = []
    for n, i in enumerate(reading_order([t["bounds"] for t in field_items], layout["width"]), 1):
        item = field_items[i]
        slot = _text_slot(item)
        slot.update({"key": f"p{page}_{n:02d}", "number": n, "label": one_line(item["text"]),
                     "where": position_hint(item["bounds"], layout["width"], layout["height"])})
        fields.append(slot)
    return {"page": page, "width": layout["width"], "height": layout["height"],
            "groups": groups, "fields": fields}


def apply_overrides(manifest, overrides):
    fixed = set(overrides.get("fixed_fields", []))
    names = overrides.get("sheet_names", {})
    for page in manifest["pages"]:
        page["fields"] = [f for f in page["fields"] if f["key"] not in fixed]
        for g in page["groups"]:
            g["sheet"] = names.get(g["sheet"], g["sheet"])
    return manifest


def build_manifest(template, layouts, overrides=None):
    """layouts: [(page, layout_dict)] in album order."""
    taken = set()
    manifest = {"template": template, "pages": [build_page(lay, page, taken) for page, lay in layouts]}
    return apply_overrides(manifest, overrides) if overrides else manifest
