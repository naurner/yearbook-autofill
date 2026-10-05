"""Grid of a class page for any number of people: the same cells (portrait frame + captions under it),
re-laid in the free part of the page — bigger or smaller, more or fewer — keeping clear of everything else
(headings, plates, a big highlighted portrait) and of the spread's middle fold.

plan_grid() is pure geometry on boxes {left, top, right, bottom} in template pixels; jsx/grid_variant.jsx
applies a plan to the PSD and saves it as a new page (e.g. «03x30» = page 03 for 30 people)."""
import statistics

SIZE_TOL = 0.15          # cells are the records whose portrait is within 15 % of the typical size
S_MAX, S_MIN, S_STEP = 1.3, 0.4, 0.01
MARGIN = 0.03            # of a cell's width kept between a cell and anything else on the page
MAX_GAP = 3.0            # cells spread edge to edge unless the gaps grow beyond 3 x the template's
NEAR = 0.97              # layouts with portraits at least 97 % of the largest possible compete on looks
BALANCE = 0.6            # a half of the spread filled under 60 % of the overall share -> share people out


def box(left, top, right, bottom):
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def union(boxes):
    return box(min(b["left"] for b in boxes), min(b["top"] for b in boxes),
               max(b["right"] for b in boxes), max(b["bottom"] for b in boxes))


def overlaps(a, b, margin=0.0):
    return (a["left"] < b["right"] + margin and b["left"] < a["right"] + margin and
            a["top"] < b["bottom"] + margin and b["top"] < a["bottom"] + margin)


def _w(b):
    return b["right"] - b["left"]


def _h(b):
    return b["bottom"] - b["top"]


def _geometry(record):
    """A manifest record ({"photo": slot, "texts": [slot]}, slots with "bounds") as plain boxes."""
    def b(slot):
        return slot["bounds"] if "bounds" in slot else slot
    return {"photo": b(record["photo"]) if record["photo"] else None, "texts": [b(t) for t in record["texts"]]}


def split_cells(records):
    """Records -> (indices of the uniform grid cells, indices of the others: a big portrait…)."""
    with_photo = [i for i, r in enumerate(records) if r["photo"] is not None]
    if not with_photo:
        return [], list(range(len(records)))
    w = statistics.median(_w(records[i]["photo"]) for i in with_photo)
    h = statistics.median(_h(records[i]["photo"]) for i in with_photo)
    cells = [i for i in with_photo
             if abs(_w(records[i]["photo"]) / w - 1) <= SIZE_TOL and abs(_h(records[i]["photo"]) / h - 1) <= SIZE_TOL]
    return cells, [i for i in range(len(records)) if i not in cells]


def _pitch(photos, along):
    """Typical distance between neighbouring cells across (along='x') or down (along='y') the grid."""
    a0, a1, b0, b1 = ("left", "right", "top", "bottom") if along == "x" else ("top", "bottom", "left", "right")
    steps = []
    for p in photos:
        size_b = p[b1] - p[b0]
        nxt = [q[a0] - p[a0] for q in photos if q[a0] > p[a0] and abs(q[b0] - p[b0]) < size_b / 2]
        if nxt:
            steps.append(min(nxt))
    return statistics.median(steps) if steps else None


def cell_shape(records, cells):
    """The cell model: portrait size, caption boxes relative to the portrait, pitch across and down."""
    p0 = records[cells[0]]["photo"]
    photos = [records[i]["photo"] for i in cells]
    whole = union([p0] + records[cells[0]]["texts"])
    w, h = _w(p0), _h(p0)
    px = _pitch(photos, "x") or _w(whole) * 1.12
    py = _pitch(photos, "y") or _h(whole) * 1.12
    return {"w": w, "h": h, "box": (whole["left"] - p0["left"], whole["top"] - p0["top"],
                                    whole["right"] - p0["left"], whole["bottom"] - p0["top"]),
            "px": max(px, _w(whole)), "py": max(py, _h(whole))}


def fold_band(page_w, boxes):
    """The free band around the spread's fold between the cells left and right of it, or None."""
    mid = page_w / 2
    left = [b["right"] for b in boxes if (b["left"] + b["right"]) / 2 < mid]
    right = [b["left"] for b in boxes if (b["left"] + b["right"]) / 2 >= mid]
    if not left or not right:
        return None
    return (min(max(left), mid - 1), max(min(right), mid + 1))


def _axis(start, length, n, size, gap):
    """n cells of `size` spread over [start, start + length]: edge to edge when the gaps stay within
    MAX_GAP x the template's gap, else a centred block with those gaps."""
    if n == 1:
        return [start + (length - size) / 2]
    step = (length - size) / (n - 1)
    if step - size > MAX_GAP * gap:
        step = size + MAX_GAP * gap
        start += (length - (step * (n - 1) + size)) / 2
    return [start + i * step for i in range(n)]


def _fit_scale(length, n, size, gap):
    """The largest scale at which n cells (size and gap at scale 1) fit in length."""
    return length / (n * size + (n - 1) * gap)


def _grid(part, region, shape, s, cols, rows, obstacles):
    """Free cells of a cols x rows grid at scale s spread over the part: [{"row", "whole", "photo"}]."""
    bx0, by0, bx1, by1 = (v * s for v in shape["box"])
    cw, ch = bx1 - bx0, by1 - by0
    gx, gy = (shape["px"] - (shape["box"][2] - shape["box"][0])) * s, (shape["py"] - (shape["box"][3] - shape["box"][1])) * s
    xs = _axis(part[0], part[1] - part[0], cols, cw, gx)
    ys = _axis(region["top"], region["bottom"] - region["top"], rows, ch, gy)
    margin = MARGIN * shape["w"] * s
    out = []
    for r, y in enumerate(ys):
        for x in xs:
            whole = box(x, y, x + cw, y + ch)
            if not any(overlaps(whole, o, margin) for o in obstacles):
                photo = box(x - bx0, y - by0, x - bx0 + shape["w"] * s, y - by0 + shape["h"] * s)
                out.append({"row": r, "whole": whole, "photo": photo})
    return out


def plan_grid(page_w, records, obstacles, n):
    """Where the n people of a class go. records: the page's photo+caption records (manifest order);
    obstacles: boxes of everything else to keep clear of. Tries every number of rows (shared by both
    halves of the spread) and of columns per half; takes the largest portraits that give room for n,
    then the fewest empty places. Returns {"scale": s, "cells": [record index of each grid cell],
    "targets": [{"src": cell record index, "photo": box, "texts": [box per caption]} × n] in reading
    order}, or None if n does not fit."""
    records = [_geometry(r) for r in records]
    cells, others = split_cells(records)
    if not cells or n < 1:
        return None
    shape = cell_shape(records, cells)
    wholes = [union([records[i]["photo"]] + records[i]["texts"]) for i in cells]
    region = union(wholes)
    fixed = list(obstacles) + [union([records[i]["photo"]] + records[i]["texts"]) if records[i]["photo"]
                               else union(records[i]["texts"]) for i in others]
    band = fold_band(page_w, wholes)
    parts = [(region["left"], band[0]), (band[1], region["right"])] if band else [(region["left"], region["right"])]
    bw, bh = shape["box"][2] - shape["box"][0], shape["box"][3] - shape["box"][1]
    gx0, gy0 = shape["px"] - bw, shape["py"] - bh
    rh = region["bottom"] - region["top"]
    found = []
    for rows in range(1, 13):
        s_rows = _fit_scale(rh, rows, bh, gy0)
        for cols in _col_choices(len(parts)):
            s = min([S_MAX, s_rows] + [_fit_scale(p[1] - p[0], c, bw, gx0) for p, c in zip(parts, cols)])
            if s < S_MIN:
                continue
            grids = [_grid(p, region, shape, s, c, rows, fixed) for p, c in zip(parts, cols)]
            free = sum(len(g) for g in grids)
            if free >= n:
                found.append((s, free - n, _unevenness(parts, cols, bw * s), grids))
    if not found:
        return None
    # nearly the largest portraits (within NEAR), then columns spaced alike on both halves, then the fewest
    # empty places
    top = max(f[0] for f in found)
    s, _, _, grids = min((f for f in found if f[0] >= top * NEAR), key=lambda f: (round(f[2], 1), f[1], -f[0]))
    chosen = [(part, pos[:k], pos) for part, pos, k in zip(parts, grids, _allocate(n, [len(g) for g in grids]))]
    _center_last_row(chosen, fixed, shape, s)
    targets = []
    for _, take, _ in chosen:
        for cell in take:
            src = cells[len(targets) % len(cells)]
            p0 = records[src]["photo"]
            texts = [box(cell["photo"]["left"] + (t["left"] - p0["left"]) * s,
                         cell["photo"]["top"] + (t["top"] - p0["top"]) * s,
                         cell["photo"]["left"] + (t["right"] - p0["left"]) * s,
                         cell["photo"]["top"] + (t["bottom"] - p0["top"]) * s) for t in records[src]["texts"]]
            targets.append({"src": src, "photo": cell["photo"], "texts": texts})
    return {"scale": s, "cells": cells, "targets": targets}


def _allocate(n, caps):
    """People per half of the spread: in reading order (the left half filled first), unless that leaves a
    half much emptier than the whole — then shared in proportion to the places."""
    seq, left = [], n
    for c in caps:
        seq.append(min(c, left))
        left -= seq[-1]
    ratio = n / sum(caps)
    if all(k >= BALANCE * ratio * c for k, c in zip(seq, caps) if c):
        return seq
    share = [n * c / sum(caps) for c in caps]
    alloc = [int(x) for x in share]
    for i in sorted(range(len(caps)), key=lambda i: share[i] - alloc[i], reverse=True)[:n - sum(alloc)]:
        alloc[i] += 1
    return alloc


def _unevenness(parts, cols, cell_w):
    """How differently the halves are spaced: column step / cell width, max minus min over the halves."""
    steps = [((p[1] - p[0] - cell_w) / (c - 1) if c > 1 else p[1] - p[0]) / cell_w for p, c in zip(parts, cols)]
    return max(steps) - min(steps)


def _col_choices(parts):
    if parts == 1:
        return [(c,) for c in range(1, 16)]
    return [(a, b) for a in range(1, 13) for b in range(1, 13)]


def _center_last_row(chosen, fixed, shape, s):
    """A part whose last row is not full gets that row centred, when nothing is in the way."""
    margin = MARGIN * shape["w"] * s
    for part, take, pos in chosen:
        if not take:
            continue
        last = take[-1]["row"]
        row = [c for c in take if c["row"] == last]
        full = [c for c in pos if c["row"] == last]
        if len(row) == len(full):
            continue
        span = full[-1]["whole"]["right"] - full[0]["whole"]["left"]
        used = row[-1]["whole"]["right"] - row[0]["whole"]["left"]
        dx = full[0]["whole"]["left"] + (span - used) / 2 - row[0]["whole"]["left"]
        moved = [{"whole": _shift(c["whole"], dx), "photo": _shift(c["photo"], dx), "row": last} for c in row]
        if not any(overlaps(m["whole"], o, margin) for m in moved for o in fixed):
            for c, m in zip(row, moved):
                c.update(m)


def _shift(b, dx):
    return box(b["left"] + dx, b["top"], b["right"] + dx, b["bottom"])


def obstacles_from_layout(layout, records):
    """Boxes to keep clear of: every visible layer that is not part of a record, except pixel layers
    (decor drawn over the photos), backgrounds (a large part of the page) and plates the template's own
    cells already lie on (stripes and corners behind the grid)."""
    taken = {tuple(r["photo"]["path"]) for r in records if r["photo"]}
    taken |= {tuple(t["path"]) for r in records for t in r["texts"]}
    cell_boxes = [_geometry(r)["photo"] for r in records if r["photo"]]
    area = layout["width"] * layout["height"]
    out = []
    for leaf in layout["leaves"]:
        b = leaf["bounds"]
        if (tuple(leaf["path"]) in taken or not leaf.get("effectiveVisible", True) or leaf["kind"] == "normal"
                or _w(b) * _h(b) > 0.25 * area or _w(b) <= 0 or _h(b) <= 0):
            continue
        ob = box(b["left"], b["top"], b["right"], b["bottom"])
        if leaf["kind"] != "text" and any(overlaps(ob, c) for c in cell_boxes):
            continue
        out.append(ob)
    return out
