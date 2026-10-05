"""Class data + template config -> what goes on every page of every student's PDF.

PageFill keys are manifest slot paths joined with dots ("1.29"); values are converted texts and
absolute photo paths. Slots left out keep the template (gray placeholder / sample text)."""
import hashlib
import json
import math
import os
import re
from pathlib import Path

from PIL import Image

from autofill.job import PHOTO_EXTS, convert_value

from .autocrop import auto_crop, fold_gutter, has_faces, photo_fits, safe_focus
from .config import (HIDE, apply_format, field_slots, logo_for, manifest_page, records, resolve_layer,
                     sid_map, split_source, variant_id)
from .names import fill_tokens, safe_file_name

MEANINGFUL = re.compile(r"[\w\d]")
SAFE_MARGIN = round(20 / 25.4 * 300)     # px at 300 dpi from the file edge: 10 mm bleed + 10 mm safety
FOLD_CLEAR = round(8 / 25.4 * 300)       # px on each side of the spread's middle fold kept free of faces


def slot_id(slot):
    return ".".join(str(i) for i in slot["path"])


class PhotoIndex:
    """Case-insensitive lookup of photo files anywhere under a folder: by file name (extension
    optional), by frame number (a digit group in the name: IMG_1811, 2528-Фамилия) or absolute path."""

    def __init__(self, root):
        self.by_name, self.by_stem, self.by_number = {}, {}, {}
        for p in sorted(Path(root).rglob("*")):
            if p.is_file() and p.suffix.lower() in PHOTO_EXTS:
                self.by_name.setdefault(p.name.casefold(), p)
                self.by_stem.setdefault(p.stem.casefold(), p)
                for num in re.findall(r"\d+", p.stem):
                    self.by_number.setdefault(num.lstrip("0") or "0", p)

    def find(self, name):
        name = name.strip()
        if Path(name).is_absolute() and Path(name).is_file():
            return str(Path(name).resolve())
        key = Path(name).name.casefold()
        p = self.by_name.get(key) or self.by_stem.get(key)
        if p is None and key.isdigit():
            p = self.by_number.get(key.lstrip("0") or "0")
        return str(p.resolve()) if p else None


def crop_key(page, sid, path):
    """A hand-set framing applies to this photo in this frame of this page, wherever the page appears."""
    return f"{page}|{sid}|{path}"


def photo_key(page, n, sid):
    """A group photo swapped by hand: frame sid on the n-th copy (from 0) of the page in the album."""
    return f"{page}#{n}|{sid}"


def _aspect(slot):
    b = slot["bounds"]
    return (b["right"] - b["left"]) / max(1, b["bottom"] - b["top"])


def caption_text(template, person, default):
    lines = [ln for ln in fill_tokens(template, person).split("\n") if MEANINGFUL.search(ln)]
    return convert_value("\n".join(lines), default)


NO_CHOICE = ("", "-", None)


_ASPECTS = {}


def photo_aspect(path):
    """Width / height of a photo as shown (EXIF rotation applied); cached."""
    if path not in _ASPECTS:
        try:
            with Image.open(path) as im:
                w, h = im.size
                if im.getexif().get(274, 1) in (5, 6, 7, 8):
                    w, h = h, w
            _ASPECTS[path] = w / h if h else 1.0
        except OSError:
            _ASPECTS[path] = 1.0
    return _ASPECTS[path]


def _shape(aspect):
    return None if aspect is None else "tall" if aspect < 0.85 else "wide" if aspect > 1.18 else None


def _frame_number(path):
    groups = re.findall(r"\d+", Path(path).stem)
    return int(max(groups, key=len)) if groups else None


def _similar(a, b):
    """Frames shot one after another (numbers within 3, same folder and shape) are nearly the same picture."""
    na, nb = _frame_number(a), _frame_number(b)
    return (na is not None and nb is not None and abs(na - nb) <= 3 and Path(a).parent == Path(b).parent
            and _shape(photo_aspect(a)) == _shape(photo_aspect(b)))


class GroupQueue:
    """Group photo slots in album order. Slot i takes the student's choice i (with its crop key "g<i>");
    a slot without a choice takes a common photo: least used first, and of the frame's shape when
    there is one (tall frames get vertical photos, wide frames horizontal ones)."""

    def __init__(self, chosen, common):
        self.chosen = chosen                     # [path | None] aligned with the slot order
        taken = {p for p in chosen if p}
        self.common = [p for p in common if p not in taken]
        self.uses = {p: 0 for p in self.common}
        self.used, self.common_used = 0, 0
        self.on_page = set()

    def start_page(self):
        self.on_page = set()

    def pop(self, aspect=None):
        i = self.used
        self.used += 1
        if i < len(self.chosen) and self.chosen[i]:
            self.on_page.add(self.chosen[i])
            return self.chosen[i], f"g{i}"
        if not self.common:
            return None, None
        if aspect is None:
            path = min(self.common, key=lambda p: (p in self.on_page, self.uses[p], self.common.index(p)))
        else:
            # never twice on one spread if avoidable; least used first; a photo whose group does not fit
            # this frame counts as used twice more; then the shape closest to the frame
            want = _shape(aspect)
            path = min(self.common, key=lambda p: (p in self.on_page,
                                                   self.uses[p] + (0 if photo_fits(p, aspect) else 2)
                                                   + (2 if any(_similar(p, q) for q in self.on_page) else 0)
                                                   + (1 if want and _shape(photo_aspect(p)) != want else 0)
                                                   + (0 if has_faces(p) else 1),
                                                   abs(math.log(photo_aspect(p) / aspect)),
                                                   self.common.index(p)))
        self.on_page.add(path)
        self.uses[path] += 1
        self.common_used += 1
        return path, None

    @property
    def pool(self):
        return [p for p in self.chosen if p] + self.common

    @property
    def repeated(self):
        return any(n > 1 for n in self.uses.values())


class _Planner:
    def __init__(self, cfg, manifest, cls, photos_dir):
        self.cfg, self.manifest, self.cls = cfg, manifest, cls
        self.index = PhotoIndex(photos_dir) if photos_dir else None
        self.errors, self.warnings = [], []
        self.fields = field_slots(cfg, manifest)
        self.common = [p for p in (self._file(n, "Лист «Общие фото»") for n in cls["common_photos"]) if p]
        self.repeats = []
        self.page_seen = {}
        self.missing_grids = set()                # (page, people) grid variants a plan wanted but lacks

    def _file(self, name, where):
        if not name:
            return None
        path = self.index.find(name)
        if path is None:
            self._error(f"{where}: файл «{name}» не найден")
        return path

    def _error(self, msg):
        if msg not in self.errors:
            self.errors.append(msg)

    def common_texts(self, page):
        """Class fields -> texts (the class's value, else the config default, else the template's own text);
        HIDE -> hidden layers."""
        texts, hide = {}, []
        for f in self.fields:
            value = self.cls["fields"].get(f["label"]) or f.get("default")
            if f["personal"] or value is None:
                continue
            for pg, slot, fmt in f["layers"]:
                if pg == page:
                    if value == HIDE:
                        hide.append(slot_id(slot))
                    else:
                        texts[slot_id(slot)] = convert_value(apply_format(fmt, value), slot["default"])
        return texts, hide

    def personal_texts(self, page, st):
        """Config-set fields: personal tokens or fixed text -> texts; HIDE -> hidden layers."""
        texts, hide = {}, []
        for f in self.fields:
            if not f["personal"]:
                continue
            value = fill_tokens(f["value"], st)
            for pg, slot, fmt in f["layers"]:
                if pg != page:
                    continue
                if f["value"] == HIDE:
                    hide.append(slot_id(slot))
                else:
                    texts[slot_id(slot)] = convert_value(apply_format(fmt, value), slot["default"])
        return texts, sorted(hide)

    def framing(self, path, slot, mpage, focus=None, own=None, rot=0):
        """A crop set by hand in the studio (crop_key -> crop in cls["crop_overrides"]), else the student's
        own crop for this photo, else automatic framing on faces."""
        fixed = (self.cls.get("crop_overrides") or {}).get(crop_key(mpage["page"], slot_id(slot), path))
        if fixed:
            return list(fixed)
        if own:
            return list(own) + [rot] if len(own) == 3 and rot else list(own)
        f = safe_focus(slot["bounds"], mpage.get("width", 10 ** 6), mpage.get("height", 10 ** 6), SAFE_MARGIN)
        if focus:
            f = (max(f[0], focus[0]), max(f[1], focus[1]), min(f[2], focus[2]), min(f[3], focus[3]))
        b = slot["bounds"]
        gutter = fold_gutter(b, mpage["width"], FOLD_CLEAR) if mpage.get("width") else None
        return auto_crop(path, b["right"] - b["left"], b["bottom"] - b["top"], f, rot, zoom_to_focus=bool(focus),
                         gutter=gutter)

    def fills_for(self, page_cfg, st, group_queue):
        fills = self._fills_for(page_cfg, st, group_queue)
        logo = logo_for(self.cfg, page_cfg["page"])
        if logo:
            for f in fills:
                f["logo"] = logo
        return fills

    def _fills_for(self, page_cfg, st, group_queue):
        page = page_cfg["page"]
        mpage = manifest_page(self.manifest, page)
        self._mpage = mpage
        group_queue.start_page()
        n = self.page_seen.get(page, 0)
        self.page_seen[page] = n + 1
        swaps = self.cls.get("photo_overrides") or {}
        recs = records(mpage)
        role = page_cfg.get("role", "photos")
        explicit = {int(k): v for k, v in page_cfg.get("photos", {}).items()}
        free = [i for i in range(len(recs)) if i not in explicit]
        personal, hide = self.personal_texts(page, st)
        common, common_hide = self.common_texts(page)
        base_texts = {**common, **personal}
        hide = sorted(set(hide) | set(common_hide))
        base_photos, base_crops = {}, {}
        focus = {int(k): v for k, v in page_cfg.get("focus", {}).items()}
        for i, src in sorted(explicit.items()):
            src, rot = split_source(src)
            aspect = _aspect(recs[i]["photo"])
            if rot in (90, 270):
                aspect = 1 / aspect                  # the photo is turned: a tall frame wants a wide photo
            path, crop = self.source_photo(src, st, group_queue, aspect)
            swap =swaps.get(photo_key(page, n, slot_id(recs[i]["photo"]))) if src == "group" else None
            if swap:
                path, crop = swap, None
            if path:
                base_photos[slot_id(recs[i]["photo"])] = path
                base_crops[slot_id(recs[i]["photo"])] = self.framing(path, recs[i]["photo"], mpage, focus.get(i), crop, rot)
        clones = []
        for c in self.cfg.get("clones", []):
            if c["page"] == page:
                _, slot = resolve_layer(self.manifest, c["of"])
                clones.append({"of": slot_id(slot), "dx": c["dx"], "dy": c["dy"],
                               "value": convert_value(fill_tokens(c["value"], st), slot["default"])})

        if role in ("students", "teachers"):
            people = self.cls["students"] if role == "students" else self.cls["teachers"]
            cap = max(1, len(free))
            fit = page_cfg.get("fit") if role == "students" else None
            fills = []
            if self.cls.get("template_grids"):          # examples and samples show the template's own pages
                fit = None
            for copy, (chunk, size) in enumerate(self._chunks(page, people, cap, fit)):
                vpage, vrecs, vfree, remap = self._variant(page, mpage, size, cap, explicit)
                texts, photos, crops = remap(base_texts), remap(base_photos), remap(base_crops)
                vclones = [dict(c, of=remap({c["of"]: 0}).popitem()[0]) for c in clones]
                for person, i in zip(chunk, vfree):
                    self.fill_person(role, page_cfg, vrecs[i], person, texts, photos, crops)
                fills.append({"page": vpage, "copy": copy, "texts": texts, "photos": photos, "crops": crops,
                              "clones": vclones, "hide": sorted(remap(dict.fromkeys(hide)))})
            return fills
        photos, crops = dict(base_photos), dict(base_crops)
        if role == "photos":
            for i in free:
                if recs[i]["photo"] is not None:
                    path, crop = self.source_photo("group", st, group_queue, _aspect(recs[i]["photo"]))
                    swap = swaps.get(photo_key(page, n, slot_id(recs[i]["photo"])))
                    if swap:
                        path, crop = swap, None
                    if path:
                        photos[slot_id(recs[i]["photo"])] = path
                        crops[slot_id(recs[i]["photo"])] = self.framing(path, recs[i]["photo"], mpage, focus.get(i), crop)
        return [{"page": page, "copy": 0, "texts": base_texts, "photos": photos, "crops": crops, "clones": clones,
                 "hide": hide}]

    def _chunks(self, page, people, cap, fit):
        """[(people, places)] per copy of a class page. fit «one»: everyone on one spread, «even»: copies of
        the page filled evenly — both need the grid variants for those counts (vignette.gridvariants), else
        (and without fit) copies of the template's own grid."""
        n = len(people)
        target = max(n, int(self.cls.get("grid_size") or 0))   # the class size while it is still filling in
        if fit == "one":
            sizes = [target]
        elif fit == "even":
            copies = max(1, math.ceil(target / cap))
            sizes = [target // copies + (1 if i < target % copies else 0) for i in range(copies)]
        else:
            sizes = []
        if sizes and all(k == cap or manifest_page(self.manifest, variant_id(page, k)) for k in sizes if k):
            out, start = [], 0
            for k in sizes:
                out.append((people[start:start + k], k))
                start += k
            return out
        self.missing_grids.update((page, k) for k in sizes if k and k != cap)
        return [(people[i:i + cap], cap) for i in range(0, max(n, 1), cap)] or [([], cap)]

    def _variant(self, page, mpage, people, cap, explicit):
        """-> (page id, records, free record indices, remap(dict of base slot ids -> same for the page))."""
        vm = manifest_page(self.manifest, variant_id(page, people)) if people != cap else None
        recs = records(mpage)
        if vm is None:
            return page, recs, [i for i in range(len(recs)) if i not in explicit], dict
        m, rec_map = sid_map(mpage, vm, list(explicit))
        vrecs = records(vm)
        mapped = set(rec_map.values())
        return (vm["page"], vrecs, [j for j in range(len(vrecs)) if j not in mapped],
                lambda d: {m.get(k, k): v for k, v in d.items()})

    def fill_person(self, role, page_cfg, rec, person, texts, photos, crops):
        if role == "students":
            path = self._file(person["portrait"], f"Ученик «{person['name']}», фото сетки")
            for t in rec["texts"]:
                tmpl = page_cfg.get("captions", {}).get(t["column"])
                if tmpl is not None:
                    texts[slot_id(t)] = caption_text(tmpl, person, t["default"])
        else:
            path = self._file(person["photo"], "Лист «Учителя»")
            if rec["texts"] and person["caption"]:
                t = rec["texts"][0]
                texts[slot_id(t)] = convert_value(person["caption"], t["default"])
        if path and rec["photo"] is not None:
            photos[slot_id(rec["photo"])] = path
            own = (person.get("crops") or {}).get("portrait") if role == "students" else None
            crops[slot_id(rec["photo"])] = self.framing(path, rec["photo"], self._mpage, None, own)

    def source_photo(self, src, st, group_queue, aspect=None):
        """-> (path | None, crop | None)."""
        crops = st.get("crops") or {}
        if src == "cover":
            return (self._file(st["cover"], f"Ученик «{st['name']}», фото обложки") or
                    self._missing(st, "фото обложки", st["cover"])), crops.get("cover")
        if src == "portrait":
            return (self._file(st["portrait"], f"Ученик «{st['name']}», фото сетки") or
                    self._missing(st, "фото сетки", st["portrait"])), crops.get("portrait")
        if src.startswith("class:"):
            label = src[6:]
            name = self.cls["class_photos"].get(label)
            if not name:
                msg = f"Лист «Класс»: не указано «{label}» — останется как в шаблоне"
                if msg not in self.warnings:
                    self.warnings.append(msg)
                return None, None
            return self._file(name, f"Лист «Класс», «{label}»"), None
        path, key = group_queue.pop(aspect)
        return path, (crops.get(key) if key else None)

    def _missing(self, st, what, name):
        if not name:
            self._error(f"Ученик «{st['name']}» (строка {st['row']}): не указано {what}")
        return None

    def student_plan(self, st):
        chosen = [None if n in NO_CHOICE else self._file(n, f"Ученик «{st['name']}», групповые фото")
                  for n in st["group"]]
        queue = GroupQueue(chosen, self.common)
        self.page_seen = {}
        pages = []
        for page_cfg in self.cfg["pages"]:
            for _ in range(page_count(page_cfg, st["pages"])):
                pages.extend(self.fills_for(page_cfg, st, queue))
        if queue.repeated:
            self.repeats.append((st["name"], queue.used, len(queue.pool)))
        return {"name": st["name"], "file": safe_file_name(st["name"]) + ".pdf", "pages": pages}


def page_count(page_cfg, chosen):
    """How many times a page goes into a student's album: required pages once; optional ones as often
    as the student chose them (a page may be chosen twice, with other photos); None = all, once each."""
    if page_cfg.get("required") or chosen is None:
        return 1
    return list(chosen).count(page_cfg["page"])


def group_slot_order(cfg, manifest, page):
    """Photo slot ids of a page in the order group photos fill them."""
    page_cfg = next(p for p in cfg["pages"] if p["page"] == page)
    recs = records(manifest_page(manifest, page))
    explicit = {int(k): v for k, v in page_cfg.get("photos", {}).items()}
    order = [slot_id(recs[i]["photo"]) for i, src in sorted(explicit.items()) if split_source(src)[0] == "group"]
    if page_cfg.get("role", "photos") == "photos":
        order += [slot_id(recs[i]["photo"]) for i in range(len(recs))
                  if i not in explicit and recs[i]["photo"] is not None]
    return order


SAMPLE_STUDENT = {"name": "Иванова Мария", "surname": "Иванова", "first": "Мария", "quote": "Цитата ученика",
                  "cover": None, "portrait": None, "group": [], "pages": None, "row": 0}


def sample_fill(cfg, manifest, page):
    """A page as the config shapes it (fixed texts, hidden layers, sample name), without photos:
    for page thumbnails shown to students."""
    planner = _Planner(cfg, manifest, {"fields": {}, "class_photos": {}, "students": [], "teachers": [],
                                       "common_photos": []}, None)
    texts, hide = planner.personal_texts(page, SAMPLE_STUDENT)
    fill = {"page": page, "copy": 0, "texts": texts, "photos": {}, "crops": {}, "clones": [], "hide": hide}
    if logo_for(cfg, page):
        fill["logo"] = logo_for(cfg, page)
    return fill


def build_plans(cfg, manifest, cls, photos_dir):
    planner = _Planner(cfg, manifest, cls, photos_dir)
    plans = [planner.student_plan(st) for st in cls["students"]]
    if planner.repeats:
        name, slots, n = planner.repeats[0]
        planner.warnings.append(f"Групповых фото меньше, чем мест в альбоме — фото повторяются у {len(planner.repeats)} "
                                f"учеников (например, «{name}»: мест {slots}, фото {n}). Добавьте фото в «Общие фото».")
    return plans, list(cls.get("errors", [])) + planner.errors, list(cls.get("warnings", [])) + planner.warnings


def page_key(fill):
    """Stable id of a page render: same fill + same photo files -> same key."""
    stats = {}
    for path in fill["photos"].values():
        try:
            st = os.stat(path)
            stats[path] = [st.st_size, int(st.st_mtime)]
        except OSError:
            stats[path] = None
    blob = json.dumps([fill, stats], sort_keys=True, ensure_ascii=False)
    return f"{fill['page']}-{hashlib.sha1(blob.encode('utf-8')).hexdigest()[:12]}"
