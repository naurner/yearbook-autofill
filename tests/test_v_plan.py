import pytest

from vhelpers import config, manifest, student
from vignette.plan import PhotoIndex, build_plans, page_key


@pytest.fixture
def photos(tmp_path):
    for sub, names in {"": ["c1.jpg", "p1.jpg", "c2.jpg", "p2.jpg", "c3.jpg", "p3.jpg", "t1.jpg", "t2.JPG"],
                       "group": ["g1.jpg", "g2.jpg", "g3.jpg", "g4.jpg"]}.items():
        (tmp_path / sub).mkdir(exist_ok=True)
        for n in names:
            (tmp_path / sub / n).write_bytes(b"x")
    return tmp_path


def cls(students, fields=None, teachers=(), common=(), class_photos=None):
    return {"class_name": "11 А", "fields": fields or {"Год": "2025", "Класс": None},
            "class_photos": class_photos or {}, "students": list(students), "teachers": list(teachers),
            "common_photos": list(common), "errors": [], "warnings": []}


def three():
    return [student("Абишева Алия", "c1", "p1", group=["g1"]),
            student("Азимбеков Эльдар", "c2", "p2.jpg", pages=["02"]),
            student("Айнабеков Атай", "c3", "p3", quote="Вперёд")]


def plan(photos, data, cfg=None):
    plans, errors, warnings = build_plans(cfg or config(), manifest(), data, photos)
    return plans, errors, warnings


def test_photo_index_recursive_case_insensitive(photos):
    idx = PhotoIndex(photos)
    assert idx.find("G1").endswith("g1.jpg")
    assert idx.find("t2.jpg").endswith("t2.JPG")
    assert idx.find("nope") is None


def test_pages_required_plus_chosen(photos):
    plans, errors, _ = plan(photos, cls(three()))
    assert not errors
    assert [p["page"] for p in plans[0]["pages"]] == ["cover", "01", "02", "03"]
    assert [p["page"] for p in plans[1]["pages"]] == ["cover", "01", "02"]
    assert plans[0]["file"] == "Абишева Алия.pdf"


def test_cover_photo_personal_field_and_clone(photos):
    plans, _, _ = plan(photos, cls(three()))
    cover = plans[0]["pages"][0]
    assert cover["photos"] == {"1": str((photos / "c1.jpg").resolve())}
    assert cover["texts"]["0.0"] == "Абишева"                          # personal field
    assert cover["texts"]["0.1"] == "2025"                              # common field
    assert "0.2" not in cover["texts"]                                  # empty «Класс» keeps template
    assert cover["clones"] == [{"of": "0.2", "dx": 0, "dy": 40, "value": "Алия Абишева"}]


def test_students_grid_identical_and_overflow(photos):
    many = three() + [student(f"Ученик{i} Имя{i}", "c1", "p1") for i in range(3)]   # 6 students, 4 slots
    plans, errors, _ = plan(photos, cls(many))
    assert not errors
    grids = [p for p in plans[0]["pages"] if p["page"] == "01"]
    assert [g["copy"] for g in grids] == [0, 1]
    assert grids[0]["texts"]["1.0"] == "АЛИЯ\x03АБИШЕВА"               # caps template -> upper, \x03 break
    assert grids[0]["photos"]["0.0"].endswith("p1.jpg")
    assert set(grids[1]["photos"]) == {"0.0", "0.1"}                    # 2 leftovers stay template gray
    assert grids[0]["texts"]["2"] == "2025"
    other = [p for p in plans[3]["pages"] if p["page"] == "01"]
    assert [page_key(g) for g in grids] == [page_key(g) for g in other]


def test_group_photos_choice_then_common_then_gray(photos):
    plans, _, _ = plan(photos, cls(three(), common=["g2", "g1", "g3"]))
    friends = next(p for p in plans[0]["pages"] if p["page"] == "02")
    assert [friends["photos"][k].rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for k in ("0.0", "0.1", "0.2")] == \
        ["g1.jpg", "g2.jpg", "g3.jpg"]                                  # own choice, then common skipping used
    plans, _, _ = plan(photos, cls(three(), common=[]))
    friends = next(p for p in plans[2]["pages"] if p["page"] == "02")
    assert friends["photos"] == {}


def test_teachers_page(photos):
    plans, errors, _ = plan(photos, cls(three(), teachers=[{"photo": "t1", "caption": "Иванова Анна\nматематика"}]))
    assert not errors
    t = next(p for p in plans[0]["pages"] if p["page"] == "03")
    assert t["photos"] == {"0.0": str((photos / "t1.jpg").resolve())}
    assert t["texts"] == {"1.0": "ИВАНОВА АННА\x03МАТЕМАТИКА"}


def test_class_photo_source(photos):
    cfg = config()
    cfg["pages"][3]["photos"] = {"1": "class:Фото руководителя"}
    plans, errors, warnings = plan(photos, cls(three(), class_photos={"Фото руководителя": "t2"}), cfg)
    t = next(p for p in plans[0]["pages"] if p["page"] == "03")
    assert t["photos"]["0.1"].endswith("t2.JPG")


def test_missing_files_are_errors(photos):
    bad = [student("Абишева Алия", "nope", "p1", group=["zzz"])]
    _, errors, _ = plan(photos, cls(bad, common=["missing"]))
    text = "\n".join(errors)
    assert "Абишева Алия" in text and "nope" in text and "zzz" in text and "missing" in text


def test_empty_quote_line_dropped(photos):
    cfg = config()
    cfg["pages"][1]["captions"] = {"Подпись: ИМЯ / ФАМИЛИЯ": "{Имя}\n“{Цитата}”"}
    plans, _, _ = plan(photos, cls(three()), cfg)
    grid = plans[0]["pages"][1]
    assert grid["texts"]["1.0"] == "АЛИЯ"
    assert grid["texts"]["1.2"] == "АТАЙ\x03“ВПЕРЁД”"


def test_page_key_changes_with_photo(photos):
    plans, _, _ = plan(photos, cls(three()))
    assert page_key(plans[0]["pages"][0]) != page_key(plans[1]["pages"][0])


def test_group_photos_repeat_when_not_enough(photos):
    plans, errors, warnings = plan(photos, cls([student("Абишева Алия", "c1", "p1", group=["g1"])], common=["g2"]))
    friends = next(p for p in plans[0]["pages"] if p["page"] == "02")
    names = [friends["photos"][k].replace("\\", "/").rsplit("/", 1)[-1] for k in ("0.0", "0.1", "0.2")]
    assert names == ["g1.jpg", "g2.jpg", "g2.jpg"]           # own choice keeps its place; commons repeat
    assert any("повтор" in w for w in warnings)


def test_fixed_and_hidden_fields(photos):
    cfg = config()
    cfg["fields"] += [{"label": "Заголовок", "layers": ["02:01"], "value": "НАШ КЛАСС"},
                      {"label": "Убрать", "layers": ["cover:03"], "value": "{скрыть}"}]
    cfg["fields"][1]["layers"] = []                                    # «Класс» no longer uses cover:03
    plans, errors, _ = plan(photos, cls(three()), cfg)
    assert not errors
    friends = next(p for p in plans[0]["pages"] if p["page"] == "02")
    assert friends["texts"]["1"] == "НАШ КЛАСС"
    cover = plans[0]["pages"][0]
    assert cover["hide"] == ["0.2"] and "0.2" not in cover["texts"]


def test_photo_index_by_frame_number(tmp_path):
    (tmp_path / "портретки").mkdir()
    (tmp_path / "портретки" / "IMG_1811.JPG").write_bytes(b"x")
    (tmp_path / "портретки" / "2528-Абдыкадырова Жасмин.jpg").write_bytes(b"x")
    idx = PhotoIndex(tmp_path)
    assert idx.find("1811").endswith("IMG_1811.JPG")
    assert idx.find("2528").endswith("Жасмин.jpg")
    assert idx.find(str(tmp_path / "портретки" / "IMG_1811.JPG")).endswith("IMG_1811.JPG")
    assert idx.find("181") is None


def test_sample_fill_uses_fixed_texts_and_hides():
    from vignette.plan import sample_fill
    cfg = config()
    cfg["fields"] += [{"label": "Заголовок", "layers": ["02:01"], "value": "НАШ КЛАСС"},
                      {"label": "Убрать", "layers": ["01:01"], "value": "{скрыть}"}]
    f = sample_fill(cfg, manifest(), "02")
    assert f["texts"] == {"1": "НАШ КЛАСС"} and f["photos"] == {} and f["page"] == "02"
    assert sample_fill(cfg, manifest(), "01")["hide"] == ["2"]
    assert sample_fill(cfg, manifest(), "cover")["texts"]["0.0"] == "Иванова"


def test_group_choice_aligned_to_slots_and_crops(photos):
    st = student("Абишева Алия", "c1", "p1", group=["-", "g3"])
    st["crops"] = {"cover": [1.5, 0.2, 0.4], "portrait": [1.2, 0.5, 0.5], "g1": [2.0, 0.9, 0.1]}
    plans, errors, _ = plan(photos, cls([st], common=["g1", "g2"]))
    assert not errors
    friends = next(p for p in plans[0]["pages"] if p["page"] == "02")
    names = [friends["photos"][k].replace("\\", "/").rsplit("/", 1)[-1] for k in ("0.0", "0.1", "0.2")]
    assert names == ["g1.jpg", "g3.jpg", "g2.jpg"]                   # slot 0 left to the studio
    assert friends["crops"]["0.1"] == [2.0, 0.9, 0.1]                  # the student's own framing wins
    assert friends["crops"]["0.0"][0] >= 1                             # others: automatic framing
    assert plans[0]["pages"][0]["crops"]["1"] == [1.5, 0.2, 0.4]
    grid = plans[0]["pages"][1]
    assert grid["crops"]["0.0"] == [1.2, 0.5, 0.5]


def test_hand_swapped_photo_and_hand_crop_win(photos):
    from vignette.plan import crop_key, photo_key
    st = student("Абишева Алия", "c1", "p1", group=[], pages=["02", "02"])
    data = cls([st], common=["g1", "g2", "g3", "g4"])
    g4 = str((photos / "group" / "g4.jpg").resolve())
    data["photo_overrides"] = {photo_key("02", 1, "0.2"): g4}           # 2nd copy of page 02, 3rd frame
    data["crop_overrides"] = {crop_key("02", "0.2", g4): [1.5, 0.1, 0.9, 0]}
    plans, errors, _ = plan(photos, data)
    assert not errors
    first, second = [p for p in plans[0]["pages"] if p["page"] == "02"]
    assert second["photos"]["0.2"] == g4 and first["photos"]["0.2"] != g4
    assert second["crops"]["0.2"] == [1.5, 0.1, 0.9, 0]


def test_optional_page_repeated(photos):
    st = student("Абишева Алия", "c1", "p1", group=["g1", "g2", "g3", "g4"], pages=["02", "02"])
    plans, errors, _ = plan(photos, cls([st], common=[]))
    friends = [p for p in plans[0]["pages"] if p["page"] == "02"]
    assert len(friends) == 2
    from pathlib import Path
    first = sorted(Path(v).name for v in friends[0]["photos"].values())
    assert len(friends[1]["photos"]) == 1 and first == ["g1.jpg", "g2.jpg", "g3.jpg"]


def test_group_slot_order():
    from vignette.plan import group_slot_order
    assert group_slot_order(config(), manifest(), "02") == ["0.0", "0.1", "0.2"]
    assert group_slot_order(config(), manifest(), "01") == []


def test_rotated_group_source_counts_as_group_place():
    from vignette.plan import group_slot_order
    from vignette.table import group_slot_count
    from vignette.config import manifest_page
    cfg = config()
    cfg["pages"][0]["photos"] = {"0": "group@90"}
    assert group_slot_order(cfg, manifest(), "cover") == ["1"]
    assert group_slot_count(cfg["pages"][0], manifest_page(manifest(), "cover")) == 1


def test_common_photos_matched_to_frame_orientation(tmp_path):
    from PIL import Image
    from vignette.plan import GroupQueue
    wide = [str(tmp_path / f"w{i}.jpg") for i in range(3)]
    tall = [str(tmp_path / f"t{i}.jpg") for i in range(2)]
    for p in wide:
        Image.new("RGB", (300, 200)).save(p)
    for p in tall:
        Image.new("RGB", (200, 300)).save(p)
    q = GroupQueue([], wide + tall)
    assert q.pop(aspect=0.6)[0] in tall                 # tall frame -> tall photo
    assert q.pop(aspect=1.8)[0] in wide
    assert q.pop(aspect=0.6)[0] in tall
    q.start_page()
    assert q.pop(aspect=0.6)[0] in tall                  # tall ones used up: reuse a tall one before a wide one
    assert q.pop()[0] in wide + tall


def test_common_photo_not_repeated_on_one_spread(tmp_path):
    from PIL import Image
    from vignette.plan import GroupQueue
    wide, tall = str(tmp_path / "w.jpg"), str(tmp_path / "t.jpg")
    Image.new("RGB", (300, 200)).save(wide)
    Image.new("RGB", (200, 300)).save(tall)
    q = GroupQueue([], [wide, tall])
    assert q.pop(aspect=0.6)[0] == tall
    assert q.pop(aspect=0.6)[0] == wide                  # same spread: another photo, even of the wrong shape
    q.start_page()
    assert q.pop(aspect=0.6)[0] == tall


def test_near_identical_frames_kept_apart_on_a_spread(tmp_path):
    from PIL import Image
    from vignette.plan import GroupQueue
    paths = [str(tmp_path / f"IMG_{n}.jpg") for n in (2136, 2137, 1900)]
    for p in paths:
        Image.new("RGB", (200, 300)).save(p)
    q = GroupQueue([], paths)
    assert q.pop(aspect=0.6)[0] == paths[0]
    assert q.pop(aspect=0.6)[0] == paths[2]              # 2137 is the next frame of the same scene


def test_logo_on_its_page_only(photos):
    from vignette.config import ConfigError, load_config
    cfg = config()
    cfg["logo"] = {"page": "cover", "file": "lumi_light_bg.png", "center": [100, 50], "width": 80}
    plans, errors, _ = plan(photos, cls(three()), cfg)
    assert not errors
    cover, rest = plans[0]["pages"][0], plans[0]["pages"][1:]
    assert cover["logo"]["file"].endswith("lumi_light_bg.png") and cover["logo"]["center"] == [100, 50]
    assert all("logo" not in p for p in rest)
    cfg["logo"]["file"] = "nope.png"
    with pytest.raises(ConfigError, match="логотип"):
        load_config(cfg, manifest())


def test_logo_drawn_centered():
    from PIL import Image
    from vignette.config import ASSETS_DIR
    from vignette.preview import place_logo
    canvas = Image.new("RGBA", (400, 300), (255, 255, 255, 255))
    place_logo(canvas, {"file": str(ASSETS_DIR / "lumi_light_bg.png"), "center": [400, 300], "width": 200}, 0.5)
    box = Image.eval(canvas.convert("L"), lambda v: 255 - v).getbbox()
    assert box and abs((box[0] + box[2]) / 2 - 200) < 6 and abs((box[1] + box[3]) / 2 - 150) < 6
