"""Automatic framing: find faces and choose crop = [zoom, fx, fy, rot] (see preview.place_photo) so every
face is inside the frame, heads keep some room above, and faces stay inside the focus region
(the part of the frame away from the trim edges, or a region set in the config)."""
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps

HEADROOM = 0.55          # of a face height, above the face box (hair, caps)
TOP_GAP = 0.06           # of the frame height between the region top and the highest head
MAX_ZOOM = 2.5
SHOULDERS = 0.8         # of a face width added on both sides of the group
BODY = 0.9              # of a face width: a person's shoulders on each side of the face
FOLD_ZOOMS = (1.0, 1.1, 1.2, 1.3)   # zooms tried to get faces off the spread's fold
CACHE_FILE = Path(os.environ.get("VIGNETTE_FACE_CACHE", Path(tempfile.gettempdir()) / "vignette_faces.json"))
_lock = threading.Lock()
_cache = None
_cascade = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _key(path, version="v6"):
    st = os.stat(path)
    return hashlib.sha1(f"{version}|{Path(path).resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()


FRAMING = ("haarcascade_frontalface_alt2.xml",)
# for keeping faces off the spread's fold: more detectors, as a missed face there is lost in the binding
THOROUGH = ("haarcascade_frontalface_alt2.xml", "haarcascade_frontalface_alt.xml", "haarcascade_profileface.xml")


def detect_faces(path, cascades=FRAMING):
    """Face boxes [x0, y0, x1, y1] as fractions of the (EXIF-upright) image. Cached on disk."""
    key = _key(path, "v6" if cascades == FRAMING else "all1")
    with _lock:
        cache = _load_cache()
        if key in cache:
            return cache[key]
    import cv2
    import numpy as np
    with Image.open(path) as im:
        im.draft("L", (1600, 1600))
        im = ImageOps.exif_transpose(im).convert("L")
        im.thumbnail((1600, 1600))
    gray = np.asarray(im)
    global _cascade
    if _cascade is None:
        _cascade = {}
    for name in cascades:
        if name not in _cascade:
            _cascade[name] = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, name))
    h, w = gray.shape
    size = (max(12, min(w, h) // 50),) * 2
    boxes = []
    for name in cascades:
        cascade = _cascade[name]
        for flip in ((False, True) if "profile" in name else (False,)):   # profile cascade sees one side
            img = cv2.flip(gray, 1) if flip else gray
            for x, y, fw, fh in cascade.detectMultiScale(img, scaleFactor=1.05, minNeighbors=4, minSize=size):
                if flip:
                    x = w - x - fw
                box = [float(x / w), float(y / h), float((x + fw) / w), float((y + fh) / h)]
                if not any(_overlap(box, b) > 0.3 for b in boxes):
                    boxes.append(box)
    boxes = clean_faces(boxes)
    with _lock:
        cache = _load_cache()
        cache[key] = boxes
        try:
            CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    return boxes


def clean_faces(boxes):
    """Drop false detections: much smaller than the real faces (posters, fabric), or far below/above
    the band the people's faces are in (car wheels, hands)."""
    if not boxes:
        return boxes
    hs = sorted(b[3] - b[1] for b in boxes)
    if len(boxes) >= 3:                          # a group: drop outliers in size (fabric, posters, screens)
        med = hs[len(hs) // 2]
        boxes = [b for b in boxes if 0.45 * med <= b[3] - b[1] <= 2.5 * med]
    else:                                        # one or two people: small extra "faces" are fabric, hands;
        boxes = [b for b in boxes if b[3] - b[1] >= max(0.6 * hs[-1], 0.05)]   # a lone tiny one is noise
    if not boxes:
        return boxes
    hs = sorted(b[3] - b[1] for b in boxes)
    cys = sorted((b[1] + b[3]) / 2 for b in boxes)
    h, cy = hs[len(hs) // 2], cys[len(cys) // 2]
    return [b for b in boxes if abs((b[1] + b[3]) / 2 - cy) <= 3 * h]


def _overlap(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))


def _rotate_boxes(boxes, rot):
    """Boxes of the image rotated clockwise by rot degrees (0/90/180/270)."""
    out = []
    for x0, y0, x1, y1 in boxes:
        if rot == 90:
            out.append([1 - y1, x0, 1 - y0, x1])
        elif rot == 180:
            out.append([1 - x1, 1 - y1, 1 - x0, 1 - y0])
        elif rot == 270:
            out.append([y0, 1 - x1, y1, 1 - x0])
        else:
            out.append([x0, y0, x1, y1])
    return out


def choose_crop(img_w, img_h, faces, slot_w, slot_h, focus=(0, 0, 1, 1), rot=0, zoom_to_focus=False,
                gutter=None, fold_faces=None):
    """Pure framing math. faces: fractions of the upright image; focus: fractions of the frame;
    gutter: (g0, g1) fractions of the frame width over the spread's fold, where a face would disappear
    in the binding: the photo is moved, or zoomed in a little, to keep faces off it (fold_faces: a more
    thorough detection used for that, default faces)."""
    best = None
    for z in (FOLD_ZOOMS if gutter else (1.0,)):
        crop, cut, folded = _frame(img_w, img_h, faces, slot_w, slot_h, focus, rot, zoom_to_focus, gutter, z,
                                   faces if fold_faces is None else fold_faces)
        key = (cut + folded, z)
        if best is None or key < best[0]:
            best = (key, crop)
        if not cut and not folded:
            break
    return best[1]


def _frame(img_w, img_h, faces, slot_w, slot_h, focus, rot, zoom_to_focus, gutter, min_zoom, fold_faces):
    """-> (crop, faces cut by the frame edge, faces on the fold)."""
    if rot in (90, 270):
        img_w, img_h = img_h, img_w
    faces = _rotate_boxes(faces, rot)
    fold_faces = _rotate_boxes(fold_faces or [], rot)
    s = max(slot_w / img_w, slot_h / img_h)
    if not faces:
        return [1.0, 0.5, 0.3 if img_h >= img_w else 0.35, rot], 0, 0
    a0, b0, a1, b1 = focus
    zoom = 1.0
    if zoom_to_focus and a1 - a0 < 0.95:
        # a narrow clear region: zoom in just enough to bring the faces' center to the region's center
        cx = (min(f[0] for f in faces) + max(f[2] for f in faces)) / 2 * img_w * s
        c = (a0 + a1) / 2
        need = [slot_w * c / cx if cx > 0 else 1, slot_w * (1 - c) / (img_w * s - cx) if img_w * s > cx else 1]
        zoom = min(MAX_ZOOM, max(1.0, *need))
    zoom = max(zoom, min_zoom)
    nw, nh = img_w * s * zoom, img_h * s * zoom
    ex, ey = nw - slot_w, nh - slot_h
    fw = sorted((f[2] - f[0]) * nw for f in faces)[len(faces) // 2]
    ux0 = min(f[0] for f in faces) * nw - SHOULDERS * fw                # people are wider than their faces
    ux1 = max(f[2] for f in faces) * nw + SHOULDERS * fw
    uy0 = min(f[1] for f in faces) * nh
    uy1 = max(f[3] for f in faces) * nh
    fh = sorted((f[3] - f[1]) * nh for f in faces)[len(faces) // 2]
    # people centered in the frame (the search below keeps them out of the margins); in a configured
    # focus region (next to lettering) centered in that region
    x0 = (ux0 + ux1) / 2 - slot_w * ((a0 + a1) / 2 if zoom_to_focus else 0.5)
    head_top = uy0 - HEADROOM * fh
    y0 = head_top - slot_h * (b0 + TOP_GAP * (b1 - b0))                # heads just under the region top
    y0 = max(y0, uy1 + 0.25 * fh - slot_h * b1)                         # ...but chins stay inside the region
    # Never cut a face with the frame edge: try window positions, prefer more whole faces, no halves,
    # then the closest to the ideal position computed above.
    # People as (face span, body span) per axis. Try window positions: a person with the whole body inside
    # the region is best, a whole face with a cut shoulder is acceptable, a face cut by an edge or shown
    # outside the region (behind lettering, in the trim margin) is bad; people fully outside are neutral.
    people = []
    for f in faces:
        w_, h_ = (f[2] - f[0]) * nw, (f[3] - f[1]) * nh
        people.append(((f[0] * nw, f[2] * nw), (f[0] * nw - BODY * w_, f[2] * nw + BODY * w_),
                       (f[1] * nh - 0.35 * h_, f[3] * nh + 0.15 * h_), (f[1] * nh - 0.6 * h_, f[3] * nh + 0.4 * h_)))
    rx0, rx1, ry0, ry1 = a0 * slot_w, a1 * slot_w, b0 * slot_h, b1 * slot_h
    fold = (gutter[0] * slot_w, gutter[1] * slot_w) if gutter else None
    fold_x = [(f[0] * nw, f[2] * nw) for f in fold_faces]

    def score(pos, want, lo, hi, spans, size, fold=None):
        total = 0.0
        if fold:
            total -= 3 * sum(1 for a, b in fold_x if b > pos + fold[0] and a < pos + fold[1])   # lost in the binding
        for face, body in spans:
            if body[0] >= pos + lo and body[1] <= pos + hi:
                total += 1
            elif face[0] >= pos + lo and face[1] <= pos + hi:
                total += 0.3
            elif face[1] > pos and face[0] < pos + size:
                total -= 4
        return total - 0.5 * abs(pos - want) / size

    def best(extent, want, lo, hi, spans, size, fold=None):
        if extent <= 0.5 or not spans:
            return min(max(want, 0), max(extent, 0))
        cands = [extent * i / 240 for i in range(241)] + [min(max(want, 0), extent)]
        return max(cands, key=lambda p: score(p, want, lo, hi, spans, size, fold))

    x0 = best(ex, x0, rx0, rx1, [(p[0], p[1]) for p in people], slot_w, fold)
    shown = [p for p in people if p[0][0] >= x0 + rx0 and p[0][1] <= x0 + rx1] or people
    y0 = best(ey, y0, ry0, ry1, [(p[2], p[3]) for p in shown], slot_h)
    fx = min(1.0, max(0.0, x0 / ex)) if ex > 0.5 else 0.5
    fy = min(1.0, max(0.0, y0 / ey)) if ey > 0.5 else 0.5
    x0 = fx * ex if ex > 0.5 else ex / 2
    faces_x = [p[0] for p in people]
    cut = sum(1 for a, b in faces_x if b > x0 and a < x0 + slot_w and not (a >= x0 and b <= x0 + slot_w))
    folded = sum(1 for a, b in fold_x if fold and b > x0 + fold[0] and a < x0 + fold[1])
    return [round(zoom, 3), round(fx, 3), round(fy, 3), rot], cut, folded


def fits(img_w, img_h, faces, frame_aspect):
    """Do all people (faces plus shoulders and some headroom) fit into a frame of this shape?"""
    if not faces:
        return True
    a = img_w / img_h
    vis_w, vis_h = (frame_aspect / a, 1.0) if a > frame_aspect else (1.0, a / frame_aspect)
    fw = sorted(f[2] - f[0] for f in faces)[len(faces) // 2]
    fh = sorted(f[3] - f[1] for f in faces)[len(faces) // 2]
    span_w = max(f[2] for f in faces) - min(f[0] for f in faces) + 2 * (BODY + 0.3) * fw
    span_h = max(f[3] for f in faces) - min(f[1] for f in faces) + 1.6 * fh
    return span_w <= vis_w and span_h <= vis_h


def has_faces(path):
    try:
        return bool(detect_faces(path))
    except Exception:
        return False


def photo_fits(path, frame_aspect):
    try:
        with Image.open(path) as im:
            w, h = ImageOps.exif_transpose(im).size if im.getexif().get(274, 1) != 1 else im.size
        return fits(w, h, detect_faces(path), frame_aspect)
    except Exception:
        return True


def auto_crop(path, slot_w, slot_h, focus=(0, 0, 1, 1), rot=0, zoom_to_focus=False, gutter=None):
    try:
        with Image.open(path) as im:
            w, h = ImageOps.exif_transpose(im).size if im.getexif().get(274, 1) != 1 else im.size
        faces = detect_faces(path)
        fold_faces = clean_faces(detect_faces(path, THOROUGH)) if gutter else None
    except Exception:
        return [1.0, 0.5, 0.3, rot]
    return choose_crop(w, h, faces, slot_w, slot_h, focus, rot, zoom_to_focus, gutter, fold_faces)


def fold_gutter(slot, page_w, clear):
    """Part of the slot's width (fractions) within `clear` px of the spread's middle fold, or None
    when the slot does not cross the fold."""
    l, r = slot["left"], slot["right"]
    fold = page_w / 2
    if not (l < fold - 1 and r > fold + 1):
        return None
    w = max(1, r - l)
    return ((fold - clear - l) / w, (fold + clear - l) / w)


def safe_focus(slot, page_w, page_h, margin):
    """Part of the slot (fractions) at least `margin` px away from the page edges."""
    l, t, r, b = slot["left"], slot["top"], slot["right"], slot["bottom"]
    w, h = max(1, r - l), max(1, b - t)
    sl, st, sr, sb = max(l, margin), max(t, margin), min(r, page_w - margin), min(b, page_h - margin)
    if sr - sl < 0.3 * w or sb - st < 0.3 * h:
        return (0, 0, 1, 1)
    return ((sl - l) / w, (st - t) / h, (sr - l) / w, (sb - t) / h)
