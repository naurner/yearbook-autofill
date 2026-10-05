"""Per-template vignette config (configs/<tpl>.json): page roles, merged fields, extra text clones.

Layer keys are "<page>:<nn>" and point at manifest field p<page>_<nn>. Photo sources are keyed by
record index of the page's group: cover | portrait | group | class:<label>."""
import json
from pathlib import Path

from autofill.manifest import one_line

ROLES = ("cover", "students", "teachers", "photos")
SOURCES = ("cover", "portrait", "group")
STUDENT_GRID_MIN = 20
HIDE = "{скрыть}"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


class ConfigError(ValueError):
    pass


def layer_key(field_key):
    """'pcover_02' -> 'cover:02'."""
    page, nn = field_key[1:].rsplit("_", 1)
    return f"{page}:{nn}"


def manifest_page(manifest, page):
    for p in manifest["pages"]:
        if p["page"] == page:
            return p
    return None


def records(mpage):
    return mpage["groups"][0]["records"] if mpage and mpage["groups"] else []


def split_layer(spec):
    """'cover:02|{last2}' -> ('cover:02', '{last2}'); no format -> '{v}'."""
    key, _, fmt = spec.partition("|")
    return key, fmt or "{v}"


def apply_format(fmt, value):
    return fmt.replace("{first2}", value[:2]).replace("{last2}", value[-2:]).replace("{v}", value)


def resolve_layer(manifest, key):
    key = split_layer(key)[0]
    page, nn = key.rsplit(":", 1)
    mpage = manifest_page(manifest, page)
    if mpage:
        for f in mpage["fields"]:
            if f["key"] == f"p{page}_{nn}":
                return page, f
    raise KeyError(key)


def split_source(src):
    """'group@90' -> ('group', 90): a photo source with an optional clockwise rotation."""
    base, _, rot = src.partition("@")
    return base, int(rot) if rot.isdigit() else 0


def _valid_source(src):
    src, rot = split_source(src)
    return rot in (0, 90, 180, 270) and (src in SOURCES or (src.startswith("class:") and len(src) > 6))


def load_config(cfg, manifest):
    """Validate a config dict (or path) against the manifest; returns the dict. Collects all problems."""
    if not isinstance(cfg, dict):
        cfg = json.loads(Path(cfg).read_text(encoding="utf-8"))
    errs = []
    for p in cfg["pages"]:
        mpage = manifest_page(manifest, p["page"])
        if mpage is None:
            errs.append(f"страницы {p['page']} нет в шаблоне")
            continue
        if any(ch in p.get("title", "") for ch in ",;"):
            errs.append(f"стр {p['page']}: в названии «{p['title']}» не должно быть запятых (это разделитель в таблице)")
        if p.get("role", "photos") not in ROLES:
            errs.append(f"стр {p['page']}: неизвестная роль «{p['role']}»")
        n = len(records(mpage))
        for idx, src in p.get("photos", {}).items():
            if not idx.isdigit() or int(idx) >= n:
                errs.append(f"стр {p['page']}: нет слота фото №{idx}")
            if not _valid_source(src):
                errs.append(f"стр {p['page']}: неизвестный источник фото «{src}»")
        columns = set(mpage["groups"][0]["columns"]) if mpage["groups"] else set()
        for col in p.get("captions", {}):
            if col not in columns:
                errs.append(f"стр {p['page']}: нет колонки подписи «{col}»")
    logo = cfg.get("logo")
    if logo:
        if manifest_page(manifest, logo.get("page")) is None:
            errs.append(f"логотип: страницы {logo.get('page')} нет в шаблоне")
        if not (ASSETS_DIR / logo.get("file", "")).is_file():
            errs.append(f"логотип: нет файла assets/{logo.get('file')}")
        if len(logo.get("center", [])) != 2 or not logo.get("width"):
            errs.append("логотип: нужны center [x, y] и width в пикселях шаблона")
    for f in cfg.get("fields", []):
        for key in f["layers"]:
            try:
                resolve_layer(manifest, key)
            except KeyError:
                errs.append(f"поле «{f['label']}»: нет слоя {key}")
    for c in cfg.get("clones", []):
        try:
            resolve_layer(manifest, c["of"])
        except KeyError:
            errs.append(f"копия надписи: нет слоя {c['of']}")
    labels = [f["label"] for f in cfg.get("fields", [])]
    for dup in sorted({x for x in labels if labels.count(x) > 1}):
        errs.append(f"поле «{dup}» описано дважды")
    if errs:
        raise ConfigError("; ".join(errs))
    return cfg


def load_template_config(template, manifest):
    return load_config(CONFIG_DIR / f"{template}.json", manifest)


def logo_for(cfg, page):
    """The studio logo put on top of this page, or None: {file (absolute), center [x, y], width} in
    template pixels (300 dpi)."""
    logo = cfg.get("logo")
    if not logo or logo["page"] != page:
        return None
    return {"file": str((ASSETS_DIR / logo["file"]).resolve()), "center": list(logo["center"]),
            "width": logo["width"]}


def variant_id(page, people):
    """The grid variant of a class page for that many people: «03x30»."""
    return f"{page}x{people}"


def _sid(slot):
    return ".".join(str(i) for i in slot["path"])


def sid_map(base, variant, explicit=()):
    """Slot ids of a page -> the same slots in its grid variant: fields by their number and layer name,
    the explicit (not grid) photo records — and their captions — by identical place and name.
    Returns ({base sid: variant sid}, {base record index: variant record index})."""
    out, rec_map = {}, {}
    by_number = {f["number"]: f for f in variant["fields"]}
    for f in base["fields"]:
        v = by_number.get(f["number"])
        if v is not None and v["name"] == f["name"]:
            out[_sid(f)] = _sid(v)
    brecs, vrecs = records(base), records(variant)
    for i in explicit:
        bp = brecs[i]["photo"]
        for j, r in enumerate(vrecs):
            if r["photo"] and r["photo"]["name"] == bp["name"] and r["photo"]["bounds"] == bp["bounds"]:
                rec_map[i] = j
                out[_sid(bp)] = _sid(r["photo"])
                for a, b in zip(brecs[i]["texts"], r["texts"]):
                    out[_sid(a)] = _sid(b)
                break
    return out, rec_map


def field_slots(cfg, manifest):
    """Fields with resolved layers: [{label, layers: [(page, slot, fmt)], value, personal, hint}].
    A field with "value" is set by the config, not the table: personal tokens ({Имя}…), fixed text,
    or HIDE to switch the layers off."""
    out = []
    for f in cfg.get("fields", []):
        layers = [resolve_layer(manifest, k) + (split_layer(k)[1],) for k in f["layers"]]
        out.append({"label": f["label"], "value": f.get("value"), "personal": f.get("value") is not None,
                    "hint": f.get("hint"), "default": f.get("default"), "layers": layers})
    return out


def class_photo_labels(cfg):
    labels = []
    for p in cfg["pages"]:
        for src in p.get("photos", {}).values():
            src = split_source(src)[0]
            if src.startswith("class:") and src[6:] not in labels:
                labels.append(src[6:])
    return labels


def draft_config(manifest):
    """Starting point for a hand-written config: roles by heuristics, identical texts merged."""
    pages = []
    for mp in manifest["pages"]:
        recs = records(mp)
        page = {"page": mp["page"], "title": f"Страница {mp['page']}", "role": "photos", "required": False}
        if mp["page"].startswith("cover") and recs:
            page.update(title="Обложка", role="cover", required=True, photos={"0": "cover"})
        elif len(recs) >= STUDENT_GRID_MIN:
            page.update(title="Сетка класса", role="students", required=True,
                        captions={c: "{Имя} {Фамилия}" for c in mp["groups"][0]["columns"]})
        pages.append(page)
    by_text, order = {}, []
    for mp in manifest["pages"]:
        for f in mp["fields"]:
            norm = one_line(f["default"], 1000)
            if norm not in by_text:
                by_text[norm] = []
                order.append(norm)
            by_text[norm].append(layer_key(f["key"]))
    fields, used = [], set()
    for norm in order:
        label = one_line(norm, 40)
        n = 2
        while label in used:
            label = f"{one_line(norm, 36)} ({n})"
            n += 1
        used.add(label)
        fields.append({"label": label, "layers": by_text[norm]})
    return {"template": manifest["template"], "pages": pages, "fields": fields, "clones": []}
