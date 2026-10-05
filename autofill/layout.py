"""Classification and geometry over layer dumps produced by jsx/extract_layout.jsx."""
import statistics

PHOTO_WORDS = ("фото", "йото", "photo")
DECOR_WORDS = ("декор",)


def _has(name, words):
    low = (name or "").lower()
    return any(w in low for w in words)


def is_photo_leaf(leaf):
    """A non-text layer is a photo slot if its own name says "фото" (and not "декор"), or the
    nearest ancestor group mentioning "фото" is not a decor group ("декор на фото" holds decor)."""
    if leaf["kind"] == "text":
        return False
    if _has(leaf["name"], PHOTO_WORDS) and not _has(leaf["name"], DECOR_WORDS):
        return True
    for group in reversed(leaf["parents"]):
        if _has(group, PHOTO_WORDS):
            return not _has(group, DECOR_WORDS)
    return False


def photo_slots(leaves):
    """Photo leaves, minus unnamed extras (e.g. a darkening overlay "затемнее") in groups where
    the real slots are named "фото…": there the name, not the group, decides."""
    candidates = [x for x in leaves if is_photo_leaf(x)]
    named_groups = {tuple(x["path"][:-1]) for x in candidates
                    if _has(x["name"], PHOTO_WORDS) and not _has(x["name"], DECOR_WORDS)}
    return [x for x in candidates
            if tuple(x["path"][:-1]) not in named_groups or _has(x["name"], PHOTO_WORDS)]


def center(b):
    return ((b["left"] + b["right"]) / 2, (b["top"] + b["bottom"]) / 2)


def reading_order(boxes, page_width):
    """Indices in reading order: left half of the spread, then right; rows by top edge, top to
    bottom (row tolerance = half the median box height), so a tall box belongs to the row it
    starts in; left to right inside a row."""
    if not boxes:
        return []
    tol = max(1.0, statistics.median(b["bottom"] - b["top"] for b in boxes) / 2)
    order = []
    for right_side in (False, True):
        idx = [i for i, b in enumerate(boxes) if (center(b)[0] >= page_width / 2) == right_side]
        idx.sort(key=lambda i: boxes[i]["top"])
        rows, row_y = [], None
        for i in idx:
            y = boxes[i]["top"]
            if rows and abs(y - row_y) <= tol:
                rows[-1].append(i)
            else:
                rows.append([i])
                row_y = y
        for row in rows:
            order.extend(sorted(row, key=lambda i: center(boxes[i])[0]))
    return order


def pair_captions(photo_boxes, caption_boxes):
    """Map caption index -> photo index. A caption pairs with a photo above it that overlaps it
    horizontally, at most one photo-height away; nearest pairs win, one caption per photo."""
    candidates = []
    for ci, c in enumerate(caption_boxes):
        cx, cy = center(c)
        for pi, p in enumerate(photo_boxes):
            if cy <= center(p)[1]:
                continue
            overlap = min(c["right"], p["right"]) - max(c["left"], p["left"])
            if overlap <= 0 and not (p["left"] <= cx <= p["right"]):
                continue
            gap = c["top"] - p["bottom"]
            if gap > p["bottom"] - p["top"]:
                continue
            candidates.append((abs(gap), abs(cx - center(p)[0]), ci, pi))
    candidates.sort()
    result, used_c, used_p = {}, set(), set()
    for _, _, ci, pi in candidates:
        if ci not in used_c and pi not in used_p:
            result[ci] = pi
            used_c.add(ci)
            used_p.add(pi)
    return result
