"""PostScript font name -> font file, over system, template and extra font folders."""
import os
import re
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

from autofill.fonts import font_dirs
from autofill.templates import ROOT

FONT_EXTS = (".ttf", ".otf", ".ttc")
EXTRA_DIRS_ENV = "VIGNETTE_FONT_DIRS"
DEFAULT_EXTRA = [Path.home() / "Desktop" / "Виньетки Эльмурат" / "шрифты"]
WEIGHTS = ("thin", "extralight", "light", "regular", "book", "medium", "semibold", "demibold", "bold",
           "extrabold", "heavy", "black")


def search_dirs():
    dirs = [Path(d) for d in font_dirs()]
    dirs += sorted(p for p in ROOT.glob("*/font*") if p.is_dir())
    extra = os.environ.get(EXTRA_DIRS_ENV)
    dirs += [Path(p) for p in extra.split(os.pathsep)] if extra else DEFAULT_EXTRA
    return [d for d in dirs if d.is_dir()]


def _ps_names(path):
    try:
        if path.suffix.lower() == ".ttc":
            fonts = TTCollection(str(path), lazy=True).fonts
        else:
            fonts = [TTFont(str(path), lazy=True, fontNumber=0)]
        return [(i, f["name"].getDebugName(6)) for i, f in enumerate(fonts)]
    except Exception:
        return []


class FontIndex:
    def __init__(self, dirs=None):
        self.files = {}
        for d in dirs or search_dirs():
            for p in sorted(d.rglob("*")):
                if p.suffix.lower() in FONT_EXTS:
                    for idx, ps in _ps_names(p):
                        if ps:
                            self.files.setdefault(ps, (str(p), idx))
        self.lower = {k.casefold(): k for k in self.files}

    def find(self, ps_name):
        """-> (path, index, substituted)."""
        if ps_name in self.files:
            return (*self.files[ps_name], False)
        key = self.lower.get(ps_name.casefold())
        if key:
            return (*self.files[key], False)
        family = re.split(r"[-_]", ps_name)[0].casefold()
        weight = _weight(ps_name)
        cands = [k for k in self.files if k.casefold().startswith(family[:max(4, len(family) - 3)])]
        if cands:
            best = min(cands, key=lambda k: abs(_weight(k) - weight))
            return (*self.files[best], True)
        fallback = "Arial-BoldMT" if weight >= WEIGHTS.index("semibold") else "ArialMT"
        if fallback in self.files:
            return (*self.files[fallback], True)
        return (None, 0, True)


def _weight(ps_name):
    style = ps_name.split("-", 1)[1].casefold() if "-" in ps_name else "regular"
    for i in range(len(WEIGHTS) - 1, -1, -1):
        if WEIGHTS[i] in style:
            return i
    return WEIGHTS.index("regular")
