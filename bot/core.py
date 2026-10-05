"""Shared bot pieces: Out (a message to deliver), App (store, templates, photo sources) and helpers."""
from dataclasses import dataclass, field
from pathlib import Path

from vignette.cli_common import HERE, load_manifest
from vignette.config import load_template_config, manifest_page
from vignette.plan import group_slot_order, page_count
from vignette.table import group_slot_count

from .photos import NumbersError, make_source, parse_numbers_origin

TEMPLATES = ("Freedom_21x30", "Flight", "Split")
BACK = [("⬅️ Назад", "back")]


@dataclass
class Out:
    text: str = ""
    buttons: list = None           # [[(label, callback_data)], ...]
    photo: str = None
    album: list = None             # [(path, caption)]
    document: str = None
    chat: int = None               # None = the user being answered
    edit: bool = False             # replace the message the button was pressed on (text or photo)
    action: tuple = None           # ("previews", code) | ("preview_one", code, sid) | ("xlsx", code) | ...


@dataclass
class App:
    store: object
    admins: set
    data_dir: Path
    bot_username: str = "bot"
    photoshop: bool = False
    crm: object = None             # bot.crm.Crm when bot.env links the CRM Lumi sheet
    _templates: dict = field(default_factory=dict)
    _sources: dict = field(default_factory=dict)

    def template(self, name):
        if name not in self._templates:
            man = load_manifest(name)
            self._templates[name] = (load_template_config(name, man), man)
        return self._templates[name]

    def class_dir(self, code):
        return Path(self.data_dir) / "classes" / code

    def source(self, cls):
        if cls["code"] not in self._sources:
            self._sources[cls["code"]] = make_source(cls["source"], self.class_dir(cls["code"]) / "cache")
        return self._sources[cls["code"]]


def with_back(outs):
    """Add the back button under the question (the last message with text)."""
    for out in reversed(outs):
        if out.text:
            out.buttons = (out.buttons or []) + [BACK]
            break
    return outs


def page_preview(template, page, numbered=False):
    """Picture of a template page: the showcase render (real photos; numbered places on request),
    else a thumbnail from the preview engine, else the raw template preview."""
    from vignette.showcase import showcase_dir
    show = showcase_dir(template) / (f"{page}_nums.jpg" if numbered else f"{page}.jpg")
    if show.exists():
        return str(show)
    if numbered:
        return page_preview(template, page)
    try:
        from vignette.preview import page_thumbnail
        man = load_manifest(template)
        return str(page_thumbnail(template, load_template_config(template, man), man, page))
    except FileNotFoundError:
        p = HERE / "layouts" / template / f"{page}_preview.jpg"
        return str(p) if p.exists() else None


def known_pages(cfg, pages):
    """A student's chosen pages that the template still has (a page removed from a template since the
    student chose it is dropped)."""
    have = {p["page"] for p in cfg["pages"]}
    return [p for p in (pages or []) if p in have]


def optional_pages(cfg):
    return [p for p in cfg["pages"] if not p.get("required")]


def group_instances(app, template, pages):
    """Pages of a student's album that take group photos, in album order:
    [{page, title, copy, places, start}] where start is the first index in the student's group list."""
    cfg, man = app.template(template)
    out, start = [], 0
    for p in cfg["pages"]:
        n = page_count(p, pages)
        places = group_slot_count(p, manifest_page(man, p["page"]))
        for copy in range(n):
            if places:
                out.append({"page": p["page"], "title": p["title"], "copy": copy, "copies": n,
                            "places": places, "start": start})
                start += places
    return out


def group_slot_bounds(app, template, page):
    """Manifest bounds of a page's group places in fill order."""
    cfg, man = app.template(template)
    mpage = manifest_page(man, page)
    photos = {}
    for g in mpage["groups"]:
        for rec in g["records"]:
            if rec["photo"] is not None:
                photos[".".join(str(i) for i in rec["photo"]["path"])] = rec["photo"]["bounds"]
    return [photos[s] for s in group_slot_order(cfg, man, page)]


def pick_frames(src, text, kind):
    """Numbers from text that exist in the source. Gaps inside ranges are skipped silently;
    a single number that is missing is an error. -> (numbers, error)"""
    try:
        items = parse_numbers_origin(text)
    except NumbersError as e:
        return [], str(e)
    found, missing = [], []
    for num, from_range in items:
        if src.has(num, kind):
            found.append(num)
        elif not from_range:
            missing.append(num)
    if missing:
        return [], f"Нет кадров: {', '.join(missing[:20])}. Пришлите номера ещё раз."
    if not found:
        return [], "В этих номерах нет ни одного кадра. Проверьте номера на сайте."
    return found, None


def is_admin(app, uid):
    return uid in app.admins
