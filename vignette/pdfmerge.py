"""Glue page files into one PDF per student, or export them as numbered JPEGs (PyMuPDF)."""
import re
import struct
from pathlib import Path

import fitz
from PIL import Image


def merge_pdfs(paths, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for p in paths:
        with fitz.open(p) as src:
            doc.insert_pdf(src)
    tmp = out.with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(out)
    return out


def images_to_pdf(images, out, dpi):
    """JPEG files -> PDF, each page sized from pixels at dpi."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for img in images:
        with Image.open(img) as im:
            w, h = im.size
        page = doc.new_page(width=w * 72 / dpi, height=h * 72 / dpi)
        page.insert_image(page.rect, filename=str(img))
    tmp = out.with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(out)
    return out


PAGE_JPG = re.compile(r"^\d+ - .+\.jpg$")


def with_dpi(jpeg, dpi):
    """JPEG bytes with the resolution set (JFIF density), the image itself untouched."""
    app0 = b"JFIF\x00\x01\x01\x01" + struct.pack(">HH", dpi, dpi) + b"\x00\x00"
    if jpeg[2:4] == b"\xff\xe0" and jpeg[6:11] == b"JFIF\x00":
        return jpeg[:13] + b"\x01" + struct.pack(">HH", dpi, dpi) + jpeg[18:]
    return jpeg[:2] + b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0 + jpeg[2:]


def export_jpgs(pdfs, folder, names, dpi=300):
    """One JPEG per page file, named names[i] + '.jpg': the image Photoshop embedded in the page PDF, not
    re-compressed (rendered at dpi if a page is anything else). Old numbered pages in the folder go."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.jpg"):
        if PAGE_JPG.match(old.name):
            old.unlink()
    for pdf, name in zip(pdfs, names):
        with fitz.open(pdf) as doc:
            page = doc[0]
            images = page.get_images(full=True)
            data = None
            if len(images) == 1:
                x = doc.extract_image(images[0][0])
                same_shape = abs(x["width"] / x["height"] - page.rect.width / page.rect.height) < 0.01
                if x["ext"] in ("jpeg", "jpg") and same_shape:
                    data = x["image"]
            if data is None:
                data = page.get_pixmap(dpi=dpi).tobytes("jpeg", jpg_quality=95)
        tmp = folder / f"{name}.tmp"
        tmp.write_bytes(with_dpi(data, dpi))
        tmp.replace(folder / f"{name}.jpg")
    return folder
