"""Manifest + operator data -> job for jsx/fill_worker.jsx, with validation."""
from pathlib import Path

from .manifest import PHOTO_COL

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".psd")


def is_caps(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c == c.upper() for c in letters)


def convert_value(value, default):
    """Excel line breaks -> the break char the template text uses (\\x03 soft or \\r paragraph);
    upper-case if the template text is all caps."""
    v = value.replace("\r\n", "\n").replace("\r", "\n")
    if is_caps(default):
        v = v.upper()
    brk = "\x03" if ("\x03" in default and "\r" not in default) else "\r"
    return v.replace("\n", brk)


def resolve_photo(photos_dir, name):
    p = Path(photos_dir) / name
    if p.is_file():
        return p
    if not p.suffix:
        for ext in PHOTO_EXTS:
            if p.with_suffix(ext).is_file():
                return p.with_suffix(ext)
    return None


def _text_entry(slot, value):
    entry = {k: slot[k] for k in ("path", "name", "styleRuns", "textKind", "justification", "horizontal", "limit")}
    entry["value"] = convert_value(value, slot["default"])
    return entry


def build_job(manifest, data, psd_dir, photos_dir, out_dir, pages=None, anchor_y=0.3):
    errors, warnings = list(data.get("errors", [])), list(data.get("warnings", []))
    job_pages = []
    for page in manifest["pages"]:
        if pages and page["page"] not in pages:
            continue
        texts, photos = [], []
        for f in page["fields"]:
            val = data["fields"].get(f["key"])
            if val is not None:
                texts.append(_text_entry(f, val))
        for g in page["groups"]:
            for n, (rec, row) in enumerate(zip(g["records"], data["groups"].get(g["sheet"], [])), start=1):
                present = {t["column"] for t in rec["texts"]}
                for t in rec["texts"]:
                    if row.get(t["column"]) is not None:
                        texts.append(_text_entry(t, row[t["column"]]))
                for col, val in row.items():
                    if val is not None and col != PHOTO_COL and col not in present:
                        warnings.append(f"Лист «{g['sheet']}», ячейка {n}: у неё нет поля «{col}» — пропущено")
                fname = row.get(PHOTO_COL)
                if fname is None:
                    continue
                if rec["photo"] is None:
                    warnings.append(f"Лист «{g['sheet']}», ячейка {n}: у неё нет фото — «{fname}» пропущено")
                    continue
                path = resolve_photo(photos_dir, fname.strip())
                if path is None:
                    errors.append(f"Лист «{g['sheet']}», ячейка {n}: файл «{fname}» не найден в {photos_dir}")
                    continue
                photos.append({"path": rec["photo"]["path"], "name": rec["photo"]["name"],
                               "hidden": rec["photo"].get("hidden", False),
                               "file": path.resolve().as_posix()})
        job_pages.append({
            "page": page["page"],
            "psd": (Path(psd_dir) / f"{page['page']}.psd").resolve().as_posix(),
            "out": (Path(out_dir) / page["page"]).resolve().as_posix(),
            "texts": texts,
            "photos": photos,
        })
    unknown = sorted(set(pages or []) - {p["page"] for p in manifest["pages"]})
    if unknown:
        errors.append(f"Нет таких страниц в шаблоне: {unknown}")
    return {"pages": job_pages, "anchorY": anchor_y}, errors, warnings
