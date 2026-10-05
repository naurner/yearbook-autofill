import pytest
from PIL import Image

from bot.classdata import to_classdata, write_class_xlsx
from bot.photos import FolderSource
from bot.store import Store
from vignette.cli_common import load_manifest
from vignette.config import load_template_config
from vignette.plan import build_plans
from vignette.table import read_table


@pytest.fixture
def world(tmp_path):
    for sub, nums in {"портретки": range(1001, 1007), "общие": range(2001, 2013)}.items():
        (tmp_path / "photos" / sub).mkdir(parents=True)
        for n in nums:
            Image.new("RGB", (60, 80), "blue").save(tmp_path / "photos" / sub / f"IMG_{n}.jpg")
    store = Store(tmp_path / "db.sqlite")
    code = store.create_class(template="Flight", title="11 Б", expected=3, tariff=2,
                              source={"kind": "folder", "path": str(tmp_path / "photos")},
                              fields={"Год выпуска": "2025", "Класс": "11 “Б”"}, class_photos={},
                              common=["2001", "2002", "2003"], admin_id=1)
    for uid, name, pages in [(1, "Абишева Алия", ["03"]), (2, "Азимбеков Эльдар", []), (3, "Айнабеков Атай", None)]:
        st = store.join(code, uid)
        store.update_student(st["id"], name=name, cover=str(1000 + uid), portrait=str(1003 + uid), quote="Вперёд",
                             grp=["2005", "2006"], pages=pages or [], status="filled")
    return tmp_path, store, code


def test_to_classdata_plans_without_errors(world):
    tmp, store, code = world
    cls, students = store.get_class(code), store.students(code)
    data = to_classdata(cls, students, FolderSource(tmp / "photos"))
    assert data["students"][0]["cover"].endswith("IMG_1001.jpg")
    assert data["students"][0]["group"][0].endswith("IMG_2005.jpg")
    man = load_manifest("Flight")
    plans, errors, _ = build_plans(load_template_config("Flight", man), man, data, tmp / "photos")
    assert not errors
    assert [p["page"] for p in plans[1]["pages"]] == ["cover", "01", "02", "05"]      # only required pages
    assert "03" in [p["page"] for p in plans[0]["pages"]]


def test_class_xlsx_roundtrip(world):
    tmp, store, code = world
    man = load_manifest("Flight")
    cfg = load_template_config("Flight", man)
    path = write_class_xlsx(cfg, man, store.get_class(code), store.students(code), tmp / "c.xlsx")
    cls = read_table(cfg, man, path)
    assert not cls["errors"] and cls["class_name"] == "11 Б" and cls["fields"]["Год выпуска"] == "2025"
    assert [s["pages"] for s in cls["students"]] == [["03"], [], []]
    plans, errors, _ = build_plans(cfg, man, cls, tmp / "photos")          # numbers resolve on the PC side too
    assert not errors
