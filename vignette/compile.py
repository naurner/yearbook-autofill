"""One-time Photoshop "compile" of a template for fast Python previews.

Per page: Photoshop's document JSON gives the layer tree (z-order, visibility, clipping, text styles).
Leaves are walked bottom-up; static leaves are grouped into runs exported as transparent PNGs, and
variable items (photo slots, texts the config can change) are inserted between runs. A variable item
is deferred past later static leaves that do not overlap it, which keeps the number of runs small.
Output: compiled/<tpl>/<page>/page.json + PNGs, compiled/<tpl>/fonts/."""
import json
import os
import shutil
from pathlib import Path

from PIL import Image

from autofill.photoshop import run_worker
from autofill.templates import TEMPLATES

from .config import field_slots, manifest_page, records, resolve_layer, sid_map
from .fontindex import FontIndex
from .plan import slot_id
from .textrender import render

HERE = Path(__file__).resolve().parents[1]
COMPILED = HERE / "compiled"
PREVIEW_DPI = 110
ALIGN = {"left": "left", "center": "center", "right": "right", "justifyLeft": "left",
         "justifyCenter": "center", "justifyRight": "right", "justifyAll": "left"}


# ---------- layer tree ----------

def walk_leaves(doc):
    """Leaves top-down: {path, id, type, name, visible (effective), own_visible, clipped, bounds, base}."""
    out = []

    def rec(layers, prefix, parent_visible):
        for i, layer in enumerate(layers):
            path = prefix + (i,)
            vis = parent_visible and layer.get("visible", True)
            if layer["type"] == "layerSection":
                rec(layer.get("layers", []), path, vis)
                continue
            out.append({"path": path, "id": layer["id"], "type": layer["type"], "name": layer["name"],
                        "visible": vis, "own_visible": layer.get("visible", True), "parent_visible": parent_visible,
                        "clipped": layer.get("clipped", False), "bounds": layer.get("bounds"),
                        "base": _clip_base(layers, i, prefix) if layer.get("clipped") else None, "layer": layer})
    rec(doc["layers"], (), True)
    return out


def _clip_base(siblings, i, prefix):
    """Path of the clipping base: first non-clipped sibling below (siblings are listed top-down)."""
    for j in range(i + 1, len(siblings)):
        if not siblings[j].get("clipped"):
            return prefix + (j,)
    return None


def leaf_ids_under(leaves, path, visible_only=True):
    return [lf["id"] for lf in leaves if lf["path"][:len(path)] == path and (lf["visible"] or not visible_only)]


def _box(b):
    return (b["left"], b["top"], b["right"], b["bottom"]) if b else None


def _overlap(a, b):
    return a and b and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _pad(box, frac=0.25, minimum=30):
    w, h = box[2] - box[0], box[3] - box[1]
    dx, dy = max(minimum, w * frac), max(minimum, h * frac)
    return (box[0] - dx, box[1] - dy, box[2] + dx, box[3] + dy)


def variable_texts(cfg, manifest):
    """{page: set(slot ids)} of texts the config can change (fields, clone sources, people captions)."""
    out = {}
    for f in field_slots(cfg, manifest):
        for page, slot, _ in f["layers"]:
            out.setdefault(page, set()).add(slot_id(slot))
    for c in cfg.get("clones", []):
        page, slot = resolve_layer(manifest, c["of"])
        out.setdefault(page, set()).add(slot_id(slot))
    for p in cfg["pages"]:
        if p.get("role") in ("students", "teachers"):
            for rec in records(manifest_page(manifest, p["page"])):
                for t in rec["texts"]:
                    out.setdefault(p["page"], set()).add(slot_id(t))
    pages = {p["page"]: p for p in cfg["pages"]}
    for mp in manifest["pages"]:                     # grid variants: their captions + the base page's fields
        base = mp.get("variant_of")
        if base in pages:
            explicit = [int(k) for k in pages[base].get("photos", {})]
            m, _ = sid_map(manifest_page(manifest, base), mp, explicit)
            out[mp["page"]] = {m.get(s, s) for s in out.get(base, set())}
            out[mp["page"]] |= {slot_id(t) for rec in records(mp) for t in rec["texts"]}
    return out


def build_stack(doc, mpage, text_sids):
    """-> (items bottom-up, exports, warnings). items: {"run": name} | {"photo": sid} | {"text": sid}."""
    leaves = walk_leaves(doc)
    photo_sids = {slot_id(r["photo"]) for r in records(mpage) if r["photo"] is not None}
    items, exports, warnings = [], [], []
    run, deferred = [], []

    def flush():
        nonlocal run, deferred
        if run:
            name = f"run{sum(e['name'].startswith('run') for e in exports):02d}"
            exports.append({"name": name, "ids": list(dict.fromkeys(run))})
            items.append({"run": name})
        items.extend(it for it, _ in deferred)
        run, deferred = [], []

    for lf in reversed(leaves):
        sid = ".".join(str(i) for i in lf["path"])
        box = _box(lf["bounds"])
        if sid in text_sids:
            if lf["visible"]:
                deferred.append(({"text": sid}, _pad(box) if box else None))
            continue
        if sid in photo_sids:
            if not lf["parent_visible"]:
                continue
            item = {"photo": sid, "mask": f"mask_{sid}"}
            if lf["base"]:
                # Texts the config changes inside the clipping base shape the mask at render time.
                under = [b for b in leaves if b["path"][:len(lf["base"])] == lf["base"] and b["visible"]]
                dyn = [".".join(str(i) for i in b["path"]) for b in under]
                dyn = [x for x in dyn if x in text_sids]
                ids = [b["id"] for b in under if ".".join(str(i) for i in b["path"]) not in dyn]
                if dyn:
                    item["mask_texts"] = dyn
            else:
                ids = [lf["id"]]
            if ids:
                exports.append({"name": f"mask_{sid}", "ids": ids})
            else:
                item["mask"] = None
            if lf["visible"] and not lf["clipped"]:
                if any(_overlap(box, b) for _, b in deferred):
                    flush()
                run.append(lf["id"])
            deferred.append((item, box))
            continue
        if not lf["visible"] or box is None:
            continue
        ids = [lf["id"]]
        if lf["clipped"] and lf["base"]:
            base_sid = ".".join(str(i) for i in lf["base"])
            if base_sid in photo_sids:
                warnings.append(f"слой «{lf['name']}» обтравлен по слоту фото — в превью не показан")
                continue
            ids += leaf_ids_under(leaves, lf["base"])
        if any(_overlap(box, b) for _, b in deferred):
            flush()
        run.extend(ids)
    flush()
    runs = [e for e in exports if e["name"].startswith("run")]
    masks = [e for e in exports if e["name"].startswith("mask_")]
    return items, runs + masks, warnings


# ---------- text specs ----------

def _color(c):
    if not c:
        return [0, 0, 0]
    if "red" in c:
        return [round(c["red"]), round(c["green"]), round(c["blue"])]
    if "gray" in c:
        v = round(255 * (1 - c["gray"] / 100.0))
        return [v, v, v]
    if "cyan" in c:
        k = c.get("black", 0) / 100.0
        return [round(255 * (1 - min(1, c[x] / 100.0)) * (1 - k)) for x in ("cyan", "magenta", "yellowColor")]
    return [0, 0, 0]


def text_spec(layer, doc, f, fonts):
    """Spec for textrender in preview pixels; fonts(ps_name) -> (file name, substituted)."""
    t = layer["text"]
    k = doc["resolution"] / 72.0 * f
    runs, seen = [], set()
    for r in t.get("textStyleRange", []):
        if (r["from"], r["to"]) in seen:
            continue
        seen.add((r["from"], r["to"]))
        ts = r.get("textStyle", {})
        font_file, _ = fonts(ts.get("fontPostScriptName", "ArialMT"))
        leading = None
        if ts.get("autoLeading", True) is False and "leading" in ts:
            leading = ts["leading"]["value"] * k
        runs.append({"from": r["from"], "to": r["to"], "font": font_file, "index": 0,
                     "size": ts.get("size", {"value": 12})["value"] * k, "color": _color(ts.get("color")),
                     "tracking": ts.get("tracking", 0), "leading": leading, "caps": ts.get("fontCaps") == "allCaps"})
    runs.sort(key=lambda r: r["from"])
    paras = []
    for p in t.get("paragraphStyleRange", []):
        ps = p.get("paragraphStyle", {})
        paras.append({"from": p["from"], "to": p["to"], "align": ALIGN.get(ps.get("align", "left"), "left"),
                      "space_before": ps.get("spaceBefore", {}).get("value", 0) * k,
                      "space_after": ps.get("spaceAfter", {}).get("value", 0) * k})
    paras = paras or [{"from": 0, "to": len(t["textKey"]) + 1, "align": "left"}]
    tr = t.get("transform", {"xx": 1, "xy": 0, "yx": 0, "yy": 1})
    shape = (t.get("textShape") or [{}])[0]
    box = None
    if shape.get("char") == "box" and "bounds" in shape:
        b = shape["bounds"]
        box = [b["left"] * k, b["top"] * k, b["right"] * k, b["bottom"] * k]
    W, H = doc["bounds"]["right"], doc["bounds"]["bottom"]
    cp = t.get("textClickPoint", {})
    origin = [cp.get("horizontal", {}).get("value", 0) / 100.0 * W * f, cp.get("vertical", {}).get("value", 0) / 100.0 * H * f]
    lb = layer.get("bounds")
    fx = (layer.get("layerEffects") or {}).get("frameFX") or {}
    stroke = {"width": fx.get("size", 3) * f, "color": _color(fx.get("color"))} if fx.get("enabled") else None
    blend = layer.get("blendOptions") or {}
    dark = runs and sum(runs[0]["color"]) < 150
    hide_fill = (blend.get("fillOpacity", {}).get("value", 100) == 0
                 or (blend.get("mode") in ("lighterColor", "lighten", "screen") and dark))
    return {"stroke": stroke, "hide_fill": bool(hide_fill), "text": t["textKey"], "kind": "box" if box else "point", "box": box,
            "matrix": [tr["xx"], tr["xy"], tr["yx"], tr["yy"]], "runs": runs, "paras": paras, "origin": origin,
            "bounds": [lb["left"] * f, lb["top"] * f, lb["right"] * f, lb["bottom"] * f] if lb else None}


def with_font_paths(spec, font_dir):
    runs = [dict(r, font=str(Path(font_dir) / r["font"])) for r in spec["runs"]]
    return dict(spec, runs=runs)


def rendered_box(spec, value, scale=1.0, shift=(0.0, 0.0)):
    img, (ox, oy) = render(spec, value, scale)
    bb = img.getchannel("A").getbbox()
    if not bb:
        return img, None, (0, 0)
    x0 = spec["origin"][0] + shift[0] - ox
    y0 = spec["origin"][1] + shift[1] - oy
    return img, (bb[0] + x0, bb[1] + y0, bb[2] + x0, bb[3] + y0), (x0, y0)


def calibrate(spec):
    """Scale + shift that make our rendering of the template text land on Photoshop's bounds."""
    target = spec.get("bounds")
    _, got, _ = rendered_box(spec, spec["text"])
    if not target or not got:
        return {"scale": 1.0, "dx": 0.0, "dy": 0.0}
    tw, th = target[2] - target[0], target[3] - target[1]
    gw, gh = got[2] - got[0], got[3] - got[1]
    s = ((tw / gw) * (th / gh)) ** 0.5 if gw > 2 and gh > 2 else 1.0
    s = min(1.4, max(0.7, s))
    _, got, _ = rendered_box(spec, spec["text"], s)
    dx = (target[0] + target[2]) / 2 - (got[0] + got[2]) / 2
    dy = (target[1] + target[3]) / 2 - (got[1] + got[3]) / 2
    return {"scale": s, "dx": dx, "dy": dy}


# ---------- orchestration ----------

def _crop_png(src, dst):
    im = Image.open(src).convert("RGBA")
    bb = im.getchannel("A").getbbox()
    if not bb:
        return None
    im.crop(bb).save(dst, optimize=True)
    return [bb[0], bb[1]]


def _crop_mask(src, dst):
    a = Image.open(src).convert("RGBA").getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bb = a.getbbox()
    if not bb:
        return None
    a.crop(bb).save(dst, optimize=True)
    return [bb[0], bb[1]]


def compile_template(template, manifest, cfg=None, pages=None, photoshop=None, out_root=COMPILED,
                     on_progress=print):
    from .config import load_template_config
    cfg = cfg or load_template_config(template, manifest)
    psd_dir = TEMPLATES[template]["psd_dir"]
    pages = pages or [p["page"] for p in manifest["pages"]]
    root = Path(out_root) / template
    work = root / "_work"
    work.mkdir(parents=True, exist_ok=True)
    f = PREVIEW_DPI / 300.0

    job = {"pages": [{"page": p, "psd": (psd_dir / f"{p}.psd").as_posix()} for p in pages], "outDir": work.as_posix()}
    res = run_worker("docjson.jsx", job, work / "json", photoshop=photoshop, on_progress=on_progress)
    bad = [r for r in res["pages"] if not r["ok"]]
    if bad:
        raise RuntimeError(f"Photoshop: {bad}")

    variable = variable_texts(cfg, manifest)
    index = FontIndex()
    font_dir = root / "fonts"
    font_dir.mkdir(exist_ok=True)
    font_notes = {}

    def fonts(ps):
        path, idx, substituted = index.find(ps)
        if path is None:
            path, substituted = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"), True
        name = Path(path).name
        if not (font_dir / name).exists():
            shutil.copy2(path, font_dir / name)
        if substituted:
            font_notes[ps] = name
        return name, substituted

    export_pages, page_data = [], {}
    for p in pages:
        doc = json.loads((work / f"{p}.doc.json").read_text(encoding="utf-8"))
        mpage = manifest_page(manifest, p)
        items, exports, warnings = build_stack(doc, mpage, variable.get(p, set()))
        for w in warnings:
            on_progress(f"  стр {p}: {w}")
        W, H = doc["bounds"]["right"], doc["bounds"]["bottom"]
        size = (max(1, round(W * f)), max(1, round(H * f)))
        page_dir = root / p
        shutil.rmtree(page_dir, ignore_errors=True)
        (work / p).mkdir(parents=True, exist_ok=True)
        page_dir.mkdir(parents=True)
        export_pages.append({"page": p, "psd": (psd_dir / f"{p}.psd").as_posix(), "width": size[0],
                             "height": size[1], "outDir": (work / p).as_posix(), "exports": exports})
        page_data[p] = (doc, mpage, items, size)

    res = run_worker("export_runs.jsx", {"pages": export_pages}, work / "png", photoshop=photoshop,
                     on_progress=on_progress)
    bad = [r for r in res["pages"] if not r["ok"]]
    if bad:
        raise RuntimeError(f"Photoshop: {bad}")

    for p, (doc, mpage, items, size) in page_data.items():
        page_dir = root / p
        leaves = {".".join(str(i) for i in lf["path"]): lf for lf in walk_leaves(doc)}
        slots = {slot_id(r["photo"]): r["photo"] for r in records(mpage) if r["photo"] is not None}
        texts_meta = {slot_id(t): t for t in mpage["fields"]}
        for r in records(mpage):
            texts_meta.update({slot_id(t): t for t in r["texts"]})
        stack = []
        for it in items:
            if "run" in it:
                off = _crop_png(work / p / f"{it['run']}.png", page_dir / f"{it['run']}.png")
                if off:
                    stack.append({"run": f"{it['run']}.png", "offset": off})
            elif "photo" in it:
                off = _crop_mask(work / p / f"{it['mask']}.png", page_dir / f"{it['mask']}.png") if it["mask"] else None
                b = slots[it["photo"]]["bounds"]
                stack.append({"photo": it["photo"], "bounds": [b["left"] * f, b["top"] * f, b["right"] * f, b["bottom"] * f],
                              "mask": f"{it['mask']}.png" if off else None, "mask_offset": off,
                              "mask_texts": it.get("mask_texts", []), "clip_only": bool(it.get("mask_texts"))})
            else:
                spec = text_spec(leaves[it["text"]]["layer"], doc, f, fonts)
                meta = texts_meta.get(it["text"], {})
                spec.update({"limit": (meta.get("limit") or 1e9) * f, "horizontal": meta.get("horizontal", True),
                             "justification": meta.get("justification", ""), "textKind": meta.get("textKind", ""),
                             "default": meta.get("default", spec["text"])})
                spec["calib"] = calibrate(with_font_paths(spec, font_dir))
                stack.append({"text": it["text"], "spec": spec})
        (page_dir / "page.json").write_text(json.dumps({"page": p, "size": list(size), "scale": f, "stack": stack},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
        on_progress(f"  стр {p}: слоёв-картинок {sum('run' in s for s in stack)}, "
                    f"фото {sum('photo' in s for s in stack)}, текстов {sum('text' in s for s in stack)}")
    for ps, name in sorted(font_notes.items()):
        on_progress(f"  шрифт {ps} не найден — в превью замена {name}")
    shutil.rmtree(work, ignore_errors=True)
    return root
