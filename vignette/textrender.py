"""Approximate Photoshop text rendering with Pillow, for previews.

A spec (built by compile.py from Photoshop's document JSON) describes one text layer in page pixels:
  kind "point" (origin = baseline start / alignment anchor) or "box" (box = [l, t, r, b] around origin),
  matrix [xx, xy, yx, yy] (layer transform), runs [{from, to, font, index, size, color, tracking,
  leading, caps}], paras [{from, to, align}].
render() lays text out in local coordinates, applies the matrix and returns the image plus the pixel
that corresponds to the layer origin."""
import math
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

BREAKS = "\r\x03\n"
AUTO_LEADING = 1.2


@lru_cache(maxsize=256)
def _font(path, index, size_px):
    try:
        return ImageFont.truetype(path, max(1, round(size_px)), index=index)
    except OSError:
        return ImageFont.load_default(max(1, round(size_px)))


def _line_starts(text):
    return [0] + [i + 1 for i, c in enumerate(text) if c in BREAKS]


def _word_starts(text, a, b):
    out, in_word = [], False
    for i in range(a, b):
        if text[i].isspace() or text[i] in BREAKS:
            in_word = False
        elif not in_word:
            out.append(i)
            in_word = True
    return out


def _covering(runs, pos):
    for r in runs:
        if r["from"] <= pos < r["to"]:
            return r
    return runs[-1]


def remap_runs(runs, old, new):
    """Mirror of fill_worker.jsx remapTextStyles: word k of line i gets the style of word k of old line i."""
    extra = max(0, runs[-1]["to"] - len(old)) if runs else 0
    old_lines, new_lines = _line_starts(old), _line_starts(new)
    segs = []
    for i, n_from in enumerate(new_lines):
        n_to = new_lines[i + 1] if i + 1 < len(new_lines) else len(new)
        oi = min(i, len(old_lines) - 1)
        o_from = old_lines[oi]
        o_to = old_lines[oi + 1] if oi + 1 < len(old_lines) else len(old)
        o_words = _word_starts(old, o_from, o_to) or [min(o_from, max(0, len(old) - 1))]
        n_words = _word_starts(new, n_from, n_to)
        segs.append((n_from, o_words[0]))
        segs += [(n_words[k], o_words[min(k, len(o_words) - 1)]) for k in range(1, len(n_words))]
    out = []
    for i, (start, anchor) in enumerate(segs):
        end = segs[i + 1][0] if i + 1 < len(segs) else len(new) + extra
        if end <= start:
            continue
        style = {k: v for k, v in _covering(runs, anchor).items() if k not in ("from", "to")}
        if out and all(out[-1].get(k) == v for k, v in style.items()):
            out[-1]["to"] = end
        else:
            out.append({"from": start, "to": end, **style})
    return out


def _para(paras, pos):
    for p in paras:
        if p["from"] <= pos < p["to"]:
            return p
    return paras[-1] if paras else {"align": "left"}


class _Line:
    def __init__(self, text, start, runs, s):
        self.text, self.start, self.s = text, start, s
        self.para_start = False    # first line after a paragraph break (carriage return)
        self.pieces = []           # (text, font, color, tracking_px)
        self.width, self.ascent, self.descent, self.leading = 0.0, 0.0, 0.0, 0.0
        i = 0
        while i < len(text):
            run = _covering(runs, start + i)
            j = i + 1
            while j < len(text) and _covering(runs, start + j) is run:
                j += 1
            self._add(text[i:j], run)
            i = j
        if not text:
            self._add("", _covering(runs, start))

    def _add(self, piece, run):
        size = run["size"] * self.s
        font = _font(run["font"], run.get("index", 0), size)
        if run.get("caps"):
            piece = piece.upper()
        track = run.get("tracking", 0) / 1000.0 * size
        width = font.getlength(piece) + track * len(piece)
        asc, desc = font.getmetrics()
        self.pieces.append((piece, font, tuple(run["color"]), track))
        self.width += width
        self.ascent, self.descent = max(self.ascent, asc), max(self.descent, desc)
        lead = run["leading"] * self.s if run.get("leading") else size * AUTO_LEADING
        self.leading = max(self.leading, lead)


def _wrap(text, start, runs, s, width):
    """Split one hard line into lines no wider than width (at spaces)."""
    words = re.split(r"(\s+)", text)
    lines, cur, cur_start, pos = [], "", start, start
    for w in words:
        trial = cur + w
        if cur.strip() and w.strip() and _Line(trial, cur_start, runs, s).width > width:
            lines.append(_Line(cur.rstrip(), cur_start, runs, s))
            cur, cur_start = w, pos
        else:
            cur = trial
        pos += len(w)
    lines.append(_Line(cur, cur_start, runs, s))
    return lines


def layout(spec, text, runs, s):
    lines = []
    starts = _line_starts(text)
    for i, a in enumerate(starts):
        b = starts[i + 1] - 1 if i + 1 < len(starts) else len(text)
        if spec["kind"] == "box" and spec.get("box"):
            box_w = (spec["box"][2] - spec["box"][0]) * s
            new = _wrap(text[a:b], a, runs, s, box_w)
        else:
            new = [_Line(text[a:b], a, runs, s)]
        new[0].para_start = i > 0 and text[a - 1] == "\r"
        lines += new
    return lines


def render(spec, value, scale=1.0):
    """-> (RGBA image, (ox, oy)) with (ox, oy) the pixel of the layer origin."""
    xx, xy, yx, yy = spec["matrix"]
    det = abs(xx * yy - xy * yx) or 1.0
    s = scale * math.sqrt(det)
    a, b, c, d = xx / math.sqrt(det), xy / math.sqrt(det), yx / math.sqrt(det), yy / math.sqrt(det)
    runs = remap_runs(spec["runs"], spec["text"], value) if value != spec["text"] else spec["runs"]
    lines = layout(spec, value, runs, s)

    box = [v * s for v in spec["box"]] if spec["kind"] == "box" and spec.get("box") else None
    y = (box[1] + lines[0].ascent) if box else 0.0
    placed = []
    for i, ln in enumerate(lines):
        if i:
            y += ln.leading
            if ln.para_start:
                y += (_para(spec["paras"], lines[i - 1].start).get("space_after", 0)
                      + _para(spec["paras"], ln.start).get("space_before", 0)) * s
        align = _para(spec["paras"], ln.start)["align"]
        if box:
            left, right = box[0], box[2]
            x = {"center": (left + right - ln.width) / 2, "right": right - ln.width}.get(align, left)
        else:
            x = {"center": -ln.width / 2, "right": -ln.width}.get(align, 0.0)
        placed.append((x, y, ln))

    stroke = spec.get("stroke")
    sw = max(1, round(stroke["width"] * s)) if stroke else 0
    sfill = tuple(stroke["color"]) + (255,) if stroke else None
    pad = 4 + sw
    minx = min(x for x, _, _ in placed) - pad
    maxx = max(x + ln.width for x, _, ln in placed) + pad
    miny = min(yb - ln.ascent for _, yb, ln in placed) - pad
    maxy = max(yb + ln.descent for _, yb, ln in placed) + pad
    w, h = max(1, math.ceil(maxx - minx)), max(1, math.ceil(maxy - miny))
    local = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(local)
    for x, yb, ln in placed:
        cx = x - minx
        for piece, font, color, track in ln.pieces:
            # Hidden fill (outline-only text) writes transparent ink over the stroke's inside.
            ink = (0, 0, 0, 0) if spec.get("hide_fill") else color + (255,)
            for part in (piece if track else [piece]):
                draw.text((cx, yb - miny), part, font=font, fill=ink, anchor="ls", stroke_width=sw, stroke_fill=sfill)
                cx += font.getlength(part) + (track if track else 0)
    origin = (-minx, -miny)
    if (a, b, c, d) == (1.0, 0.0, 0.0, 1.0):
        return local, origin
    return _transform(local, origin, a, b, c, d)


def _transform(img, origin, a, b, c, d):
    """Apply page = M * local (M = [[a, c], [b, d]]) around the origin; returns image and new origin."""
    ox, oy = origin
    w, h = img.size
    corners = [(px - ox, py - oy) for px, py in ((0, 0), (w, 0), (0, h), (w, h))]
    mapped = [(a * x + c * y, b * x + d * y) for x, y in corners]
    minx, miny = min(p[0] for p in mapped), min(p[1] for p in mapped)
    maxx, maxy = max(p[0] for p in mapped), max(p[1] for p in mapped)
    out_w, out_h = max(1, math.ceil(maxx - minx)), max(1, math.ceil(maxy - miny))
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det       # inverse of [[a, c], [b, d]]
    # output pixel (u, v) -> page offset (u + minx, v + miny) -> local = inv * offset + origin
    coeffs = (ia, ic, ia * minx + ic * miny + ox, ib, id_, ib * minx + id_ * miny + oy)
    out = img.transform((out_w, out_h), Image.AFFINE, coeffs, resample=Image.BICUBIC)
    return out, (-minx, -miny)
