"""Showcase renders of the templates (every page once, all places filled) for the bot.

  python make_showcase.py --portraits <folder> --groups <folder> [--templates Flight Split]

Portraits: single-person photos (used on covers and in grids); groups: group photos. Files are taken in
name order. Output: compiled/<template>/showcase/<page>.jpg and <page>_nums.jpg (numbered group places)."""
import argparse
import sys
from pathlib import Path

from autofill.templates import TEMPLATES
from vignette.cli_common import load_manifest
from vignette.config import load_template_config
from vignette.showcase import build_showcase

EXTS = (".jpg", ".jpeg", ".png")


def photos(folder):
    return [str(p.resolve()) for p in sorted(Path(folder).iterdir()) if p.suffix.lower() in EXTS]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--portraits", required=True)
    ap.add_argument("--groups", required=True)
    ap.add_argument("--templates", nargs="*", default=list(TEMPLATES))
    args = ap.parse_args(argv)
    portraits, groups = photos(args.portraits), photos(args.groups)
    for t in args.templates:
        man = load_manifest(t)
        res = build_showcase(t, load_template_config(t, man), man, portraits, groups)
        print(t, ", ".join(sorted(res)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
