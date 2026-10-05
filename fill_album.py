"""Fill a photobook template with data from Excel via Photoshop.

Example:
  python fill_album.py --template Freedom_21x30 --excel 11A.xlsx --photos D:\\photos\\11A --out D:\\out\\11A
"""
import argparse
import json
import sys
from pathlib import Path

from autofill.excel_io import read_filled
from autofill.fonts import missing_fonts
from autofill.job import build_job
from autofill.photoshop import run_worker
from autofill.templates import TEMPLATES

HERE = Path(__file__).resolve().parent


def load_manifest(name):
    return json.loads((HERE / "manifests" / f"{name}.json").read_text(encoding="utf-8"))


def format_warning(w):
    if w["kind"] == "shrink":
        return f"«{w['layer']}»: текст не помещался — уменьшен до {w['value']:.0%}"
    if w["kind"] == "styles_lost":
        return f"«{w['layer']}»: стиль строк не сохранился, текст вставлен одним стилем ({w['value']})"
    return f"«{w.get('layer')}»: {w}"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True, choices=list(TEMPLATES))
    ap.add_argument("--excel", required=True, help="заполненный Excel (копия templates/<шаблон>.xlsx)")
    ap.add_argument("--photos", required=True, help="папка с фото")
    ap.add_argument("--out", required=True, help="папка для результата")
    ap.add_argument("--pages", help="только эти страницы, через запятую: cover,01")
    ap.add_argument("--check", action="store_true", help="только проверить данные и шрифты")
    ap.add_argument("--photoshop", help="путь к Photoshop.exe")
    args = ap.parse_args(argv)

    manifest = load_manifest(args.template)
    data = read_filled(manifest, args.excel)
    pages = [p.strip() for p in args.pages.split(",")] if args.pages else None
    out = Path(args.out)
    job, errors, warnings = build_job(manifest, data, TEMPLATES[args.template]["psd_dir"], args.photos, out, pages)

    for w in warnings:
        print("ВНИМАНИЕ:", w)
    for font, where in missing_fonts(manifest).items():
        print(f"ВНИМАНИЕ: шрифт {font} не найден в системе (стр. {', '.join(where)}) — Photoshop подставит замену")
    if errors:
        for e in errors:
            print("ОШИБКА:", e)
        return 1
    n_texts = sum(len(p["texts"]) for p in job["pages"])
    n_photos = sum(len(p["photos"]) for p in job["pages"])
    print(f"Страниц: {len(job['pages'])}, текстов к замене: {n_texts}, фото: {n_photos}")
    if args.check:
        print("Проверка пройдена.")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    result = run_worker("fill_worker.jsx", job, out / "_work", photoshop=args.photoshop,
                        on_progress=lambda line: print("  ", line))
    failed = 0
    for page in result["pages"]:
        status = "готово" if page["ok"] else "ОШИБКА: " + page.get("error", "")
        print(f"стр {page['page']}: {status} (текстов {page.get('texts', 0)}, фото {page.get('photos', 0)})")
        for w in page.get("warnings", []):
            print("    " + format_warning(w))
        failed += 0 if page["ok"] else 1
    print(f"Результат: {out.resolve()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
