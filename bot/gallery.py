"""Photos from a gallery.photo (Vigbo) client gallery: the gallery page embeds every scene (folder) and
its media files (original file name + storage key). Frames are found by the number in the file name
(IMG_1844-retouched.jpg -> 1844) and downloaded from public storage on demand."""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

STORAGE = "https://storage.googleapis.com/vigbo/"
PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
LISTING_TTL = 3600
FORCE_COOLDOWN = 60          # re-read the gallery for an unknown frame at most once a minute
UA = {"User-Agent": "Mozilla/5.0 (vignette bot)"}


def is_gallery_url(text):
    return "gallery.photo/" in text


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _flight_text(html):
    """Concatenated Next.js flight data (the JSON the page is rendered from)."""
    return "".join(json.loads('"' + m + '"') for m in PUSH.findall(html))


def _json_array_after(text, key):
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*\[', text)
    if not m:
        return None
    j = m.end() - 1
    depth, in_str, esc = 0, False, False
    for k in range(j, len(text)):
        c = text[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[j:k + 1])
    return None


def gallery_page_url(url):
    """A gallery link, or a single photo link (its page names the gallery) -> gallery page URL."""
    parts = urllib.parse.urlsplit(url.strip())
    if "/gallery/" in parts.path:
        return url.strip()
    text = _flight_text(_fetch(url))
    m = re.search(r'"gallery":\{"id":"[^"]+","name":"[^"]*","url":"([^"]+)"', text)
    if not m:
        raise ValueError("не удалось найти галерею по этой ссылке")
    return f"{parts.scheme}://{parts.netloc}/gallery/{m.group(1)}"


def parse_listing(html):
    """-> [{"scene": name, "name": file name, "key": storage key}] for every photo in the gallery."""
    scenes = _json_array_after(_flight_text(html), "scenes") or []
    out = []
    for sc in scenes:
        for m in sc.get("mediaFiles", []):
            if m.get("type") == "photo" and m.get("fileKey"):
                out.append({"scene": sc.get("name") or "", "name": m["name"], "key": m["fileKey"]})
    return out


def number_of(name):
    """IMG_1844-retouched.jpg -> '1844' (the longest digit group)."""
    groups = re.findall(r"\d+", Path(name).stem)
    return (max(groups, key=len).lstrip("0") or "0") if groups else None


def kind_of(scene):
    s = scene.casefold()
    return "portrait" if "портрет" in s else "common" if "общ" in s else None


class GallerySource:
    """Frames of one or two gallery.photo galleries (portraits, common). Scenes named like
    «портретки»/«общие» split a single gallery; unnamed scenes serve both kinds."""
    can_list = True

    def __init__(self, portraits, common, cache_dir, fetch=_fetch, storage=STORAGE):
        self.urls = {"portrait": portraits, "common": common or portraits}
        self.storage = storage
        self.cache = Path(cache_dir)
        self.fetch = fetch
        self._index, self._loaded, self._forced = {}, 0.0, 0.0

    def _load(self, force=False):
        if self._index and not force and time.time() - self._loaded < LISTING_TTL:
            return
        index = {"portrait": {}, "common": {}}
        for kind in ("portrait", "common"):
            for item in parse_listing(self.fetch(self.urls[kind])):
                k = kind_of(item["scene"])
                if k not in (None, kind):
                    continue
                num = number_of(item["name"])
                if num is None:
                    continue
                prev = index[kind].get(num)
                # prefer the retouched file when both versions of a frame are in the gallery
                if prev is None or ("retouch" in item["name"].lower() and "retouch" not in prev["name"].lower()):
                    index[kind][num] = item
        self._index, self._loaded = index, time.time()

    def numbers(self, kind):
        self._load()
        return sorted(self._index[kind], key=int)

    def _lookup(self, num, kind):
        self._load()
        item = self._index[kind].get(num)
        if item is None and time.time() - self._forced > FORCE_COOLDOWN:
            self._forced = time.time()             # photos may have been added since the last listing
            self._load(force=True)
            item = self._index[kind].get(num)
        return item

    def has(self, num, kind):
        """Is the frame in the gallery (no download)."""
        num = str(int(num))
        return (self.cache / kind / f"{num}.jpg").exists() or self._lookup(num, kind) is not None

    def find(self, num, kind):
        num = str(int(num))
        target = self.cache / kind / f"{num}.jpg"
        if target.exists():
            return str(target.resolve())
        item = self._lookup(num, kind)
        if item is None:
            return None
        req = urllib.request.Request(self.storage + item["key"], headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        return str(target.resolve())
