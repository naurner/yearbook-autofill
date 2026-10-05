import http.server
import json
import threading
from functools import partial

from PIL import Image

from bot.gallery import GallerySource, gallery_page_url, number_of, parse_listing
from bot.photos import parse_source


def page(scenes):
    """A page shaped like gallery.photo: Next.js flight chunks carrying the scenes JSON."""
    data = json.dumps({"gallery": {"scenes": scenes}}, ensure_ascii=False)
    half = len(data) // 2
    chunks = "".join(f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>" for part in (data[:half], data[half:]))
    return f"<html><body>{chunks}</body></html>"


def media(name, key):
    return {"photos": [key], "name": name, "type": "photo", "fileKey": key}


SCENES = [{"name": "Портретки", "mediaFiles": [media("IMG_1844.jpg", "k/plain.jpg"),
                                               media("IMG_1844-retouched.jpg", "k/ret.jpg")]},
          {"name": "Общие фото", "mediaFiles": [media("IMG_2001-retouched.jpg", "k/g.jpg"),
                                                {"name": "clip.mp4", "type": "clip", "fileKey": "k/c.mp4"}]}]


def test_parse_listing_and_numbers():
    items = parse_listing(page(SCENES))
    assert [(i["scene"], i["name"]) for i in items] == [("Портретки", "IMG_1844.jpg"),
                                                         ("Портретки", "IMG_1844-retouched.jpg"),
                                                         ("Общие фото", "IMG_2001-retouched.jpg")]
    assert number_of("IMG_1844-retouched.jpg") == "1844" and number_of("0015.jpg") == "15"


def test_gallery_source_scenes_retouched_and_download(tmp_path):
    store = tmp_path / "storage" / "k"
    store.mkdir(parents=True)
    Image.new("RGB", (30, 40), "red").save(store / "ret.jpg")
    Image.new("RGB", (30, 40), "blue").save(store / "plain.jpg")
    Image.new("RGB", (50, 20), "green").save(store / "g.jpg")
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "storage"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        src = GallerySource("https://x.gallery.photo/gallery/a", None, tmp_path / "cache",
                            fetch=lambda url: page(SCENES), storage=f"http://127.0.0.1:{server.server_port}/")
        assert src.numbers("portrait") == ["1844"] and src.numbers("common") == ["2001"]
        path = src.find("1844", "portrait")
        assert Image.open(path).getpixel((1, 1)) == (254, 0, 0) or Image.open(path).getpixel((1, 1))[0] > 200
        assert src.find("2001", "portrait") is None and src.find("2001", "common")
    finally:
        server.shutdown()


def test_unnamed_scene_serves_both_kinds(tmp_path):
    scenes = [{"name": "", "mediaFiles": [media("IMG_1800-retouched.jpg", "k/a.jpg")]}]
    src = GallerySource("u", None, tmp_path, fetch=lambda url: page(scenes))
    assert src.numbers("portrait") == ["1800"] == src.numbers("common")


def test_parse_source_gallery_links():
    spec = parse_source("https://b.gallery.photo/photo/xyz/\nhttps://b.gallery.photo/gallery/common-g",
                        resolve_gallery=lambda u: u if "/gallery/" in u else "https://b.gallery.photo/gallery/port")
    assert spec == {"kind": "gallery", "portraits": "https://b.gallery.photo/gallery/port",
                    "common": "https://b.gallery.photo/gallery/common-g"}
    assert gallery_page_url("https://b.gallery.photo/gallery/abc") == "https://b.gallery.photo/gallery/abc"


def test_missing_numbers_do_not_hammer_the_gallery(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return page(SCENES)

    src = GallerySource("u", None, tmp_path, fetch=fetch)
    for n in ("5000", "5001", "5002", "5003"):
        assert not src.has(n, "common")
    assert len(calls) <= 4                                    # first listing (2 kinds) + one forced refresh
    assert src.has("2001", "common") and not list((tmp_path).rglob("*.jpg"))   # has() never downloads
