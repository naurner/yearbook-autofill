"""Grid variants of the class pages, made in Photoshop on demand and kept: «<page>x<people>.psd» next to the
template (a normal page: open it, fix it by hand, it is used as it is), its layout, manifest page and
compiled preview data. Config: a students page with "fit": "one" (everyone on one spread) or "even"
(copies of the page filled evenly) uses the variant for its count of people (vignette.plan)."""
import json
import math
from pathlib import Path

from autofill.manifest import build_page
from autofill.photoshop import run_worker
from autofill.templates import TEMPLATES

from .cli_common import HERE, load_manifest
from .config import manifest_page, records, variant_id
from .gridfit import obstacles_from_layout, plan_grid, split_cells, _geometry

LAYOUTS = HERE / "layouts"


def fit_pages(cfg):
    return [p for p in cfg["pages"] if p.get("role") == "students" and p.get("fit")]


def _free(page_cfg, recs):
    explicit = {int(k) for k in page_cfg.get("photos", {})}
    return [i for i, r in enumerate(recs) if i not in explicit and r["photo"] is not None]


def needed(cfg, manifest, people):
    """(page, people on it) of every grid variant a class of that size uses (the template's own count of
    places needs none)."""
    out = []
    for p in fit_pages(cfg):
        cap = len(_free(p, records(manifest_page(manifest, p["page"]))))
        if p["fit"] == "one":
            sizes = [people]
        else:
            copies = max(1, math.ceil(people / cap))
            sizes = {people // copies + (1 if i < people % copies else 0) for i in range(copies)}
        out += [(p["page"], k) for k in sorted(sizes) if k and k != cap]
    return out


def is_ready(template, manifest, page, people):
    from .compile import COMPILED
    vid = variant_id(page, people)
    return (manifest_page(manifest, vid) is not None and (COMPILED / template / vid / "page.json").exists()
            and (TEMPLATES[template]["psd_dir"] / f"{vid}.psd").exists())


def plan_variant(manifest, page_cfg, people, layout):
    """The gridfit plan for that many people on the page, as the job for jsx/grid_variant.jsx."""
    mp = manifest_page(manifest, page_cfg["page"])
    recs = records(mp)
    explicit = {int(k) for k in page_cfg.get("photos", {})}
    cells, _ = split_cells([_geometry(r) for r in recs])
    cells = [i for i in cells if i not in explicit]
    fixed_people = len(_free(page_cfg, recs)) - len(cells)            # e.g. a big highlighted portrait
    small = people - fixed_people
    plan = plan_grid(mp["width"], recs, obstacles_from_layout(layout, recs), small) if small > 0 else None
    if plan is None:
        raise ValueError(f"на странице {page_cfg['page']} не помещается {people} человек")
    targets = []
    for t in plan["targets"]:
        src = recs[t["src"]]
        targets.append({"photo": src["photo"]["path"], "texts": [x["path"] for x in src["texts"]],
                        "box": [round(t["photo"]["left"]), round(t["photo"]["top"])],
                        "textBoxes": [[round(b["left"]), round(b["top"])] for b in t["texts"]]})
    unused = plan["cells"][small:]
    remove = [p for i in unused for p in [recs[i]["photo"]["path"]] + [x["path"] for x in recs[i]["texts"]]]
    return {"scale": plan["scale"], "targets": targets, "remove": remove}


def ensure(template, cfg, wants, photoshop=None, on_progress=print, force=False):
    """Make the grid variants in `wants` [(page, people)] that are not ready yet (all of them with force).
    Returns their page ids."""
    manifest = load_manifest(template)
    todo = sorted({w for w in wants if force or not is_ready(template, manifest, *w)})
    if not todo:
        return []
    psd_dir = TEMPLATES[template]["psd_dir"]
    pages = {p["page"]: p for p in cfg["pages"]}
    jobs, vids = [], []
    for page, people in todo:
        layout = json.loads((LAYOUTS / template / f"{page}.json").read_text(encoding="utf-8-sig"))
        job = plan_variant(manifest, pages[page], people, layout)
        vid = variant_id(page, people)
        jobs.append(dict(job, psd=(psd_dir / f"{page}.psd").as_posix(), out=(psd_dir / f"{vid}.psd").as_posix()))
        vids.append((vid, page, people))
    on_progress(f"Сетки {template}: делаю в Photoshop {', '.join(v for v, _, _ in vids)}")
    work = HERE / "work"
    res = run_worker("grid_variant.jsx", {"pages": jobs}, work / f"grid_{template}", photoshop=photoshop,
                     on_progress=on_progress)
    bad = [p for p in res["pages"] if not p["ok"]]
    if bad:
        raise RuntimeError(f"Photoshop: {bad}")
    out = LAYOUTS / template
    res = run_worker("extract_layout.jsx", {"psdDir": psd_dir.as_posix(), "pages": [v for v, _, _ in vids],
                                            "outDir": out.as_posix(), "previewWidth": 1400},
                     work / f"extract_{template}", photoshop=photoshop, on_progress=on_progress)
    bad = [p for p in res["pages"] if not p["ok"]]
    if bad:
        raise RuntimeError(f"Photoshop: {bad}")
    add_to_manifest(template, [(vid, page, people) for vid, page, people in vids])
    from .compile import compile_template
    compile_template(template, load_manifest(template), cfg, pages=[v for v, _, _ in vids], photoshop=photoshop,
                     on_progress=on_progress)
    return [v for v, _, _ in vids]


def add_to_manifest(template, variants):
    """Manifest pages of grid variants [(page id, base page, people)] from their extracted layouts."""
    path = HERE / "manifests" / f"{template}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    ids = {v for v, _, _ in variants}
    manifest["pages"] = [p for p in manifest["pages"] if p["page"] not in ids]
    taken = {g["sheet"] for p in manifest["pages"] for g in p["groups"]}
    for vid, base, people in variants:
        layout = json.loads((LAYOUTS / template / f"{vid}.json").read_text(encoding="utf-8-sig"))
        page = build_page(layout, vid, taken)
        page.update(variant_of=base, people=people)
        manifest["pages"].append(page)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
