"""Where class photos come from: a local folder or the studio site (URL template with {num}).

Frames are addressed by the number students see on the site (IMG_1811 -> 1811). Portraits and common
(group) photos may live in separate places."""
import re
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

from vignette.plan import PhotoIndex

from .gallery import GallerySource, gallery_page_url, is_gallery_url

MAX_RANGE = 500
THUMB = 1280


class NumbersError(ValueError):
    pass


def parse_numbers(text):
    """'1811, 1812-1815 2001' -> ['1811', '1812', ..., '2001'] (order kept, no duplicates)."""
    return [n for n, _ in parse_numbers_origin(text)]


def parse_numbers_origin(text):
    """Like parse_numbers, with a flag: True when the number came from a range (a gap there is fine)."""
    out, seen = [], set()
    for num, from_range in _tokens(text):
        if num not in seen:
            seen.add(num)
            out.append((num, from_range))
    return out


def _tokens(text):
    out = []
    for token in re.split(r"[\s,;]+", text.strip()):
        if not token:
            continue
        m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", token)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if b < a or b - a > MAX_RANGE:
                raise NumbersError(f"диапазон «{token}» не подходит")
            out += [(str(n), True) for n in range(a, b + 1)]
        elif token.isdigit():
            out.append((str(int(token)), False))
        else:
            raise NumbersError(f"«{token}» — не номер кадра")
    return out


def _sub(root, word):
    for p in sorted(Path(root).iterdir()) if Path(root).is_dir() else []:
        if p.is_dir() and word in p.name.casefold():
            return p
    return Path(root)


class FolderSource:
    """Photos in a local folder; subfolders named like «портретки»/«общие» are used when present."""
    can_list = True

    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"нет папки {self.root}")
        self.index = {"portrait": PhotoIndex(_sub(self.root, "портрет")), "common": PhotoIndex(_sub(self.root, "общ"))}

    def find(self, num, kind):
        return self.index[kind].find(str(num))

    def has(self, num, kind):
        return self.find(num, kind) is not None

    def numbers(self, kind):
        idx = self.index[kind]
        return sorted(idx.by_number, key=int)


class UrlSource:
    """Photos downloaded by URL template, e.g. https://site/classes/11a/portraits/IMG_{num}.jpg."""
    can_list = False

    def __init__(self, portraits, common, cache_dir, timeout=30):
        self.templates = {"portrait": portraits, "common": common or portraits}
        self.cache = Path(cache_dir)
        self.timeout = timeout

    def find(self, num, kind):
        target = self.cache / kind / f"{int(num)}.jpg"
        if target.exists():
            return str(target.resolve())
        url = self.templates[kind].replace("{num}", str(int(num)))
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        return str(target.resolve())

    def has(self, num, kind):
        return self.find(num, kind) is not None

    def numbers(self, kind):
        raise NotImplementedError("сайт не отдаёт список кадров — перечислите номера")


def make_source(spec, cache_dir):
    if spec["kind"] == "folder":
        return FolderSource(spec["path"])
    if spec["kind"] == "gallery":
        return GallerySource(spec["portraits"], spec.get("common"), cache_dir)
    return UrlSource(spec["portraits"], spec.get("common"), cache_dir)


def parse_source(text, resolve_gallery=gallery_page_url):
    """Admin answer -> source spec: a folder path, a gallery.photo link (or two: portraits, common),
    or one/two URL templates with {num}."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines and is_gallery_url(lines[0]):
        urls = [resolve_gallery(u) for u in lines[:2]]
        return {"kind": "gallery", "portraits": urls[0], "common": urls[-1]}
    if lines and lines[0].lower().startswith(("http://", "https://")):
        if any("{num}" not in ln for ln in lines[:2]):
            raise ValueError("в ссылке нужен {num} на месте номера кадра")
        return {"kind": "url", "portraits": lines[0], "common": lines[1] if len(lines) > 1 else lines[0]}
    if not lines or not Path(lines[0]).is_dir():
        raise ValueError("папка не найдена")
    return {"kind": "folder", "path": str(Path(lines[0]).resolve())}


def thumbnail(path, cache_dir):
    """Small JPEG for Telegram (photo messages are limited to 10 MB)."""
    src = Path(path)
    out = Path(cache_dir) / "thumbs" / f"{src.stem}-{abs(hash(str(src))) % 10**8}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.draft("RGB", (THUMB, THUMB))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((THUMB, THUMB))
            im.save(out, quality=85)
    return str(out)
