import http.server
import threading
from functools import partial

import pytest
from PIL import Image

from bot.photos import FolderSource, NumbersError, UrlSource, parse_numbers, parse_source, thumbnail


def test_parse_numbers():
    assert parse_numbers("1811, 1812-1814 ;2001\n0015 1811") == ["1811", "1812", "1813", "1814", "2001", "15"]
    with pytest.raises(NumbersError):
        parse_numbers("12, фото")
    with pytest.raises(NumbersError):
        parse_numbers("10-5")


def jpg(path, size=(300, 400)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "red").save(path)
    return path


def test_folder_source_subfolders(tmp_path):
    jpg(tmp_path / "Портретки" / "IMG_1811.jpg")
    jpg(tmp_path / "Общие" / "IMG_1811.jpg")
    jpg(tmp_path / "Общие" / "IMG_2001.jpg")
    src = FolderSource(tmp_path)
    assert "Портретки" in src.find("1811", "portrait") and "Общие" in src.find("1811", "common")
    assert src.find("2001", "portrait") is None
    assert src.numbers("common") == ["1811", "2001"]


def test_url_source_downloads_and_caches(tmp_path):
    site = tmp_path / "site"
    jpg(site / "p" / "IMG_1811.jpg")
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        src = UrlSource(base + "/p/IMG_{num}.jpg", None, tmp_path / "cache")
        path = src.find("1811", "portrait")
        assert path and Image.open(path).size == (300, 400)
        assert src.find("9999", "portrait") is None
    finally:
        server.shutdown()
    assert src.find("1811", "portrait") == path                   # served from cache after the site is gone


def test_parse_source(tmp_path):
    assert parse_source(str(tmp_path))["kind"] == "folder"
    spec = parse_source("https://s/p/{num}.jpg\nhttps://s/c/{num}.jpg")
    assert spec == {"kind": "url", "portraits": "https://s/p/{num}.jpg", "common": "https://s/c/{num}.jpg"}
    with pytest.raises(ValueError):
        parse_source("https://s/p/1811.jpg")
    with pytest.raises(ValueError):
        parse_source(str(tmp_path / "nope"))


def test_thumbnail(tmp_path):
    big = jpg(tmp_path / "big.jpg", (4000, 3000))
    t = thumbnail(big, tmp_path / "cache")
    assert max(Image.open(t).size) == 1280


def test_parse_numbers_with_origin():
    from bot.photos import parse_numbers_origin
    assert parse_numbers_origin("1811, 1812-1813 1811") == [("1811", False), ("1812", True), ("1813", True)]
