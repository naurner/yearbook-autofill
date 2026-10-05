"""Per-student vignette PDFs from one class workbook.

  python vignette.py table   --template Flight --out 11А.xlsx
  python vignette.py check   --template Flight --excel 11А.xlsx --photos D:\\фото\\11А
  python vignette.py preview --template Flight --excel 11А.xlsx --photos D:\\фото\\11А --out D:\\вывод
  python vignette.py build   --template Flight --excel 11А.xlsx --photos D:\\фото\\11А --out D:\\вывод
  python vignette.py compile --template Flight
  python vignette.py grids   --template Flight --people 25-45      (сетки класса под это число учеников)
"""
import argparse
import sys

from autofill.fonts import missing_fonts
from autofill.templates import TEMPLATES
from vignette.cli_common import load_manifest
from vignette.config import load_template_config
from vignette.plan import build_plans
from vignette.table import read_table, write_table


def prepare(args, manifest, cfg):
    """Read the workbook and plan every student; prints problems. Returns (cls, plans) or None."""
    cls = read_table(cfg, manifest, args.excel)
    plans, errors, warnings = build_plans(cfg, manifest, cls, args.photos)
    for w in warnings:
        print("ВНИМАНИЕ:", w)
    if errors:
        for e in errors:
            print("ОШИБКА:", e)
        return None
    if args.only:
        wanted = {n.strip().casefold() for n in args.only.split(",")}
        plans = [p for p in plans if p["name"].casefold() in wanted]
    elif args.students:
        plans = plans[: args.students]
    pages = sum(len(p["pages"]) for p in plans)
    print(f"Класс «{cls['class_name']}»: учеников {len(cls['students'])}, в сборке {len(plans)}, страниц {pages}")
    return cls, plans


def cmd_table(args, manifest, cfg):
    write_table(cfg, manifest, args.out)
    print(f"Таблица: {args.out}")
    return 0


def cmd_check(args, manifest, cfg):
    for font, where in missing_fonts(manifest).items():
        print(f"ВНИМАНИЕ: шрифт {font} не найден в системе (стр. {', '.join(where)}) — Photoshop подставит замену")
    if prepare(args, manifest, cfg) is None:
        return 1
    print("Проверка пройдена.")
    return 0


def cmd_build(args, manifest, cfg):
    from vignette.final import build
    ready = prepare(args, manifest, cfg)
    if ready is None:
        return 1
    cls, plans = ready
    report = build(plans, cls["class_name"], manifest, TEMPLATES[args.template]["psd_dir"], args.out,
                   keep_psd=args.psd, photoshop=args.photoshop, titles={p["page"]: p["title"] for p in cfg["pages"]})
    for key, err in report["pages"].items():
        if err:
            print(f"ОШИБКА страницы {key}: {err}")
    failed = [(n, m) for n, p, m in report["students"] if p is None]
    for name, missing in failed:
        print(f"НЕ СОБРАН: {name} (нет страниц: {', '.join(missing)})")
    print(f"Готово (папки со страницами JPG): {len(report['students']) - len(failed)} из {len(report['students'])} → {report['class_dir']}")
    return 1 if failed else 0


def cmd_preview(args, manifest, cfg):
    from vignette.preview import build_previews
    ready = prepare(args, manifest, cfg)
    if ready is None:
        return 1
    cls, plans = ready
    out = build_previews(plans, cls["class_name"], args.template, args.out, watermark=not args.no_watermark)
    print(f"Превью: {out}")
    return 0


def cmd_compile(args, manifest, cfg):
    from vignette.compile import compile_template
    compile_template(args.template, manifest, pages=args.pages.split(",") if args.pages else None,
                     photoshop=args.photoshop)
    return 0


def cmd_grids(args, manifest, cfg):
    from vignette import gridvariants
    lo, _, hi = args.people.partition("-")
    wants = sorted({w for n in range(int(lo), int(hi or lo) + 1) for w in gridvariants.needed(cfg, manifest, n)})
    made = gridvariants.ensure(args.template, cfg, wants, photoshop=args.photoshop)
    print(f"Сетки {args.template}: сделано {len(made)}, уже были {len(wants) - len(made)}")
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["table", "check", "preview", "build", "compile", "grids"])
    ap.add_argument("--template", required=True, choices=list(TEMPLATES))
    ap.add_argument("--excel", help="таблица класса")
    ap.add_argument("--photos", help="папка с фото класса (ищется во всех подпапках)")
    ap.add_argument("--out", help="папка результата (для table — путь к новой таблице)")
    ap.add_argument("--students", type=int, help="собрать только первых N учеников")
    ap.add_argument("--only", help="собрать только этих учеников: «Фамилия Имя, Фамилия Имя»")
    ap.add_argument("--psd", action="store_true", help="build: сохранить и PSD страниц")
    ap.add_argument("--no-watermark", action="store_true", help="preview: без водяного знака")
    ap.add_argument("--pages", help="compile: только эти страницы")
    ap.add_argument("--photoshop", help="путь к Photoshop.exe")
    ap.add_argument("--people", help="grids: число учеников или диапазон, например 25-45")
    args = ap.parse_args(argv)
    need = {"table": ["out"], "check": ["excel", "photos"], "preview": ["excel", "photos", "out"],
            "build": ["excel", "photos", "out"], "compile": [], "grids": ["people"]}[args.command]
    missing = [f"--{n}" for n in need if not getattr(args, n)]
    if missing:
        ap.error(f"для {args.command} нужно: {' '.join(missing)}")
    manifest = load_manifest(args.template)
    cfg = load_template_config(args.template, manifest)
    return {"table": cmd_table, "check": cmd_check, "build": cmd_build, "preview": cmd_preview,
            "compile": cmd_compile, "grids": cmd_grids}[args.command](args, manifest, cfg)


if __name__ == "__main__":
    sys.exit(main())
