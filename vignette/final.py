"""Print build: render every unique page once in Photoshop (fill_worker.jsx), then per student a folder of
numbered page JPEGs («01 - обложка.jpg», «02 - сетка класса.jpg», …) at 300 dpi."""
from pathlib import Path

from autofill.photoshop import run_worker

from .config import manifest_page
from .names import safe_file_name
from .pdfmerge import export_jpgs
from .plan import page_key, slot_id

TEXT_KEYS = ("path", "name", "styleRuns", "textKind", "justification", "horizontal", "limit")
CACHE_DIR = "_страницы"


def page_slots(mpage):
    texts, photos = {}, {}
    for f in mpage["fields"]:
        texts[slot_id(f)] = f
    for g in mpage["groups"]:
        for rec in g["records"]:
            for t in rec["texts"]:
                texts[slot_id(t)] = t
            if rec["photo"] is not None:
                photos[slot_id(rec["photo"])] = rec["photo"]
    return texts, photos


def fill_to_job_page(fill, manifest, psd_dir, out_base):
    texts, photos = page_slots(manifest_page(manifest, fill["page"]))
    return {
        "page": fill["page"],
        "psd": (Path(psd_dir) / f"{fill['page']}.psd").resolve().as_posix(),
        "out": Path(out_base).resolve().as_posix(),
        "texts": [dict({k: texts[sid][k] for k in TEXT_KEYS}, value=v) for sid, v in fill["texts"].items()],
        "photos": [{"path": photos[sid]["path"], "name": photos[sid]["name"],
                    "hidden": photos[sid].get("hidden", False), "file": f,
                    "crop": (fill.get("crops") or {}).get(sid)} for sid, f in fill["photos"].items()],
        "clones": [dict({k: texts[c["of"]][k] for k in TEXT_KEYS}, dx=c["dx"], dy=c["dy"], value=c["value"])
                   for c in fill["clones"]],
        "hide": [{"path": texts[sid]["path"], "name": texts[sid]["name"]} for sid in fill.get("hide", [])],
        "logo": fill.get("logo"),
    }


def cached(cache, key):
    pdf = cache / f"{key}.pdf"
    return pdf.exists() and pdf.stat().st_size > 0


def unique_fills(plans):
    out = {}
    for plan in plans:
        for fill in plan["pages"]:
            out.setdefault(page_key(fill), fill)
    return out


def page_names(plan, titles=None):
    """File names of a plan's pages: «01 - обложка», «02 - сетка класса», … (page id without a title)."""
    names = []
    for i, fill in enumerate(plan["pages"], 1):
        title = (titles or {}).get(fill["page"]) or fill["page"]
        names.append(safe_file_name(f"{i:02d} - {title[:1].lower()}{title[1:]}"))   # 01…: sorts right anywhere
    return names


def student_folder(plan):
    return Path(plan["file"]).stem


def build(plans, class_name, manifest, psd_dir, out_dir, keep_psd=False, photoshop=None, on_progress=print,
          titles=None):
    """Returns {"students": [(name, folder|None, missing_keys)], "pages": {key: error|None}, "class_dir"}.
    titles: {page: title} from the template config, for the file names."""
    class_dir = Path(out_dir) / safe_file_name(class_name)
    cache = class_dir / CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    fills = unique_fills(plans)
    todo = {k: f for k, f in fills.items() if not cached(cache, k)}
    page_errors = {k: None for k in fills}
    if todo:
        on_progress(f"Страниц к рендеру в Photoshop: {len(todo)} (всего уникальных {len(fills)})")
        job = {"pages": [fill_to_job_page(f, manifest, psd_dir, cache / k) for k, f in todo.items()],
               "anchorY": 0.3, "formats": ["psd", "pdf"] if keep_psd else ["pdf"]}
        result = run_worker("fill_worker.jsx", job, cache / "_work", photoshop=photoshop,
                            on_progress=lambda line: on_progress("  " + line))
        for key, rep in zip(todo, result["pages"]):
            if not rep["ok"]:
                page_errors[key] = rep.get("error", "ошибка")
                (cache / f"{key}.pdf").unlink(missing_ok=True)
    students = []
    for plan in plans:
        keys = [page_key(f) for f in plan["pages"]]
        missing = [k for k in keys if not cached(cache, k)]
        path = None if missing else export_jpgs([cache / f"{k}.pdf" for k in keys],
                                                class_dir / student_folder(plan), page_names(plan, titles))
        students.append((plan["name"], path, missing))
    return {"students": students, "pages": page_errors, "class_dir": class_dir}
