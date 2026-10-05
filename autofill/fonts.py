"""Which template fonts (PostScript names) are missing from this machine."""
import os
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont


def font_dirs():
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return [d for d in dirs if d.is_dir()]


def installed_postscript_names(dirs=None):
    names = set()
    for d in dirs if dirs is not None else font_dirs():
        for f in d.iterdir():
            ext = f.suffix.lower()
            try:
                if ext in (".ttf", ".otf"):
                    fonts = [TTFont(f, lazy=True)]
                elif ext == ".ttc":
                    fonts = TTCollection(f, lazy=True).fonts
                else:
                    continue
                for font in fonts:
                    ps = font["name"].getDebugName(6)
                    if ps:
                        names.add(ps)
            except Exception:
                continue
    return names


def manifest_fonts(manifest):
    fonts = {}
    for page in manifest["pages"]:
        slots = list(page["fields"]) + [t for g in page["groups"] for r in g["records"] for t in r["texts"]]
        for s in slots:
            if s.get("font"):
                pages = fonts.setdefault(s["font"], [])
                if page["page"] not in pages:
                    pages.append(page["page"])
    return fonts


def missing_fonts(manifest, installed=None):
    installed = installed_postscript_names() if installed is None else installed
    return {font: pages for font, pages in manifest_fonts(manifest).items() if font not in installed}
