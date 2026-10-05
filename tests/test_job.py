from autofill.job import build_job, convert_value, is_caps
from autofill.manifest import PHOTO_COL, build_manifest
from helpers import grid_layout

SHEET = "Стр 01 (4 фото)"
CAPTION = "Подпись: Имя Фамилия"


def data_for(rows, fields=None):
    return {"fields": fields or {}, "groups": {SHEET: rows}, "errors": [], "warnings": []}


def test_convert_value_caps_and_breaks():
    assert convert_value("Мария\nИванова", "ИМЯ\x03ФАМИЛИЯ") == "МАРИЯ\x03ИВАНОВА"
    assert convert_value("Мария\nИванова", "Имя Фамилия") == "Мария\rИванова"
    assert convert_value("Мария\r\nИванова", "Имя Фамилия") == "Мария\rИванова"
    assert not is_caps("2022") and is_caps("11 “А”")


def test_build_job_collects_filled_slots(tmp_path):
    (tmp_path / "ivanova.jpg").write_bytes(b"x")
    (tmp_path / "petrov.png").write_bytes(b"x")
    m = build_manifest("T", [("01", grid_layout())])
    rows = [{CAPTION: "Мария Иванова", PHOTO_COL: "ivanova.jpg"},
            {CAPTION: None, PHOTO_COL: "petrov"},
            {CAPTION: None, PHOTO_COL: None}]
    job, errors, warnings = build_job(m, data_for(rows, {"p01_01": "11 «Б»"}),
                                      tmp_path / "psd", tmp_path, tmp_path / "out")
    assert errors == [] and warnings == []
    [page] = job["pages"]
    assert page["psd"].endswith("psd/01.psd") and page["out"].endswith("out/01")
    assert [t["value"] for t in page["texts"]] == ["11 «Б»", "Мария Иванова"]
    assert page["texts"][1]["limit"] == 150 and page["texts"][1]["horizontal"] is True
    assert [p["name"] for p in page["photos"]] == ["фото1", "фото2"]
    assert page["photos"][1]["file"].endswith("petrov.png")
    assert page["photos"][0]["hidden"] is False
    assert job["anchorY"] == 0.3


def test_missing_photo_is_error(tmp_path):
    m = build_manifest("T", [("01", grid_layout())])
    _, errors, _ = build_job(m, data_for([{PHOTO_COL: "nope.jpg"}]), tmp_path, tmp_path, tmp_path)
    assert len(errors) == 1 and "nope.jpg" in errors[0]


def test_value_in_gray_cell_is_warning(tmp_path):
    m = build_manifest("T", [("01", grid_layout())])
    m["pages"][0]["groups"][0]["records"][0]["texts"] = []
    _, errors, warnings = build_job(m, data_for([{CAPTION: "Кто-то"}]), tmp_path, tmp_path, tmp_path)
    assert errors == [] and len(warnings) == 1


def test_pages_filter_and_unknown_page(tmp_path):
    m = build_manifest("T", [("01", grid_layout()), ("02", grid_layout())])
    job, errors, _ = build_job(m, {"fields": {}, "groups": {}}, tmp_path, tmp_path, tmp_path, pages=["02", "99"])
    assert [p["page"] for p in job["pages"]] == ["02"]
    assert errors and "99" in errors[0]
