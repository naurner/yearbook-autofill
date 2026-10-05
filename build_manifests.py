"""One-time setup: dump template layouts via Photoshop, then build manifests, operator Excel
templates and numbered slot schemes. Re-run with --skip-extract after editing overrides."""
import argparse
import json
import sys
from pathlib import Path

from autofill.excel_io import write_template
from autofill.manifest import build_manifest
from autofill.photoshop import run_worker
from autofill.scheme import draw_scheme
from autofill.templates import TEMPLATES

HERE = Path(__file__).resolve().parent


def extract(name, photoshop=None):
    tpl = TEMPLATES[name]
    out = HERE / "layouts" / name
    out.mkdir(parents=True, exist_ok=True)
    job = {"psdDir": tpl["psd_dir"].as_posix(), "pages": tpl["pages"], "outDir": out.as_posix(),
           "previewWidth": 1400}
    result = run_worker("extract_layout.jsx", job, HERE / "work" / f"extract_{name}", photoshop=photoshop,
                        on_progress=lambda line: print(f"  {line}"))
    bad = [p for p in result["pages"] if not p["ok"]]
    if bad:
        raise RuntimeError(f"{name}: ошибки извлечения: {bad}")


def build(name):
    tpl = TEMPLATES[name]
    layout_dir = HERE / "layouts" / name
    layouts = [(p, json.loads((layout_dir / f"{p}.json").read_text(encoding="utf-8-sig"))) for p in tpl["pages"]]
    overrides_path = HERE / "manifests" / f"{name}.overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else None
    manifest = build_manifest(name, layouts, overrides)
    keep_grid_variants(name, manifest)
    (HERE / "manifests").mkdir(exist_ok=True)
    (HERE / "manifests" / f"{name}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
    (HERE / "templates").mkdir(exist_ok=True)
    try:
        write_template(manifest, HERE / "templates" / f"{name}.xlsx")
    except PermissionError:
        print(f"ВНИМАНИЕ: templates/{name}.xlsx открыт в Excel — таблица не обновлена")
    scheme_dir = HERE / "templates" / f"{name}_схема"
    scheme_dir.mkdir(exist_ok=True)
    for page in manifest["pages"]:
        draw_scheme(page, layout_dir / f"{page['page']}_preview.jpg", scheme_dir / f"{page['page']}.png")
    return manifest


def keep_grid_variants(name, manifest):
    """Grid variant pages (vignette/gridvariants.py) survive a rebuild: their layouts are read again."""
    from autofill.manifest import build_page
    old_path = HERE / "manifests" / f"{name}.json"
    if not old_path.exists():
        return
    taken = {g["sheet"] for p in manifest["pages"] for g in p["groups"]}
    for old in json.loads(old_path.read_text(encoding="utf-8"))["pages"]:
        layout = HERE / "layouts" / name / f"{old['page']}.json"
        if old.get("variant_of") and layout.exists():
            page = build_page(json.loads(layout.read_text(encoding="utf-8-sig")), old["page"], taken)
            page.update(variant_of=old["variant_of"], people=old["people"])
            manifest["pages"].append(page)


def summary(manifest):
    for page in manifest["pages"]:
        g = page["groups"][0] if page["groups"] else None
        cells = len(g["records"]) if g else 0
        photos = sum(1 for r in g["records"] if r["photo"]) if g else 0
        print(f"  стр {page['page']}: ячеек {cells} (с фото {photos}), "
              f"колонки {g['columns'] if g else []}, полей {len(page['fields'])}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--templates", nargs="*", default=list(TEMPLATES))
    ap.add_argument("--skip-extract", action="store_true", help="использовать уже извлечённые layouts/")
    ap.add_argument("--photoshop", help="путь к Photoshop.exe")
    args = ap.parse_args()
    for name in args.templates:
        print(f"== {name}")
        if not args.skip_extract:
            extract(name, args.photoshop)
        summary(build(name))


if __name__ == "__main__":
    main()
