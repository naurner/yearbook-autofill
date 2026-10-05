import pytest

from autofill.manifest import build_manifest, build_page, one_line, run_limit, unique_sheet_name
from helpers import grid_layout, leaf


def test_build_page_groups_photos_with_captions_in_reading_order():
    page = build_page(grid_layout(), "01", set())
    [group] = page["groups"]
    assert group["sheet"] == "Стр 01 (4 фото)"
    assert group["columns"] == ["Подпись: Имя Фамилия"]
    assert [r["photo"]["name"] for r in group["records"]] == ["фото1", "фото2", "фото3", "фото4"]
    assert [r["texts"][0]["name"] for r in group["records"]] == ["имя 1", "имя 2", "имя 3", "имя 4"]
    assert group["records"][0]["texts"][0]["limit"] == 150


def test_build_page_one_off_texts_become_fields():
    page = build_page(grid_layout(), "01", set())
    [field] = page["fields"]
    assert (field["key"], field["number"], field["default"]) == ("p01_01", 1, "11 “А”")
    assert field["where"] == "правая половина, низ"


def test_photos_without_captions_are_records_too():
    layout = {"width": 1000, "height": 700, "leaves": [
        leaf("фото1", "shape", (0, 0, 100, 100), parents=["фото"], path=[0, 0]),
        leaf("фото2", "shape", (600, 0, 700, 100), parents=["фото"], path=[0, 1]),
    ]}
    [group] = build_page(layout, "03", set())["groups"]
    assert group["columns"] == [] and group["hasPhotos"]
    assert [r["texts"] for r in group["records"]] == [[], []]


def test_hidden_layers_are_ignored_and_orphan_captions_kept():
    layout = grid_layout()
    for item in layout["leaves"]:
        if item["name"] == "фото4":
            item["effectiveVisible"] = False
    records = build_page(layout, "01", set())["groups"][0]["records"]
    assert len(records) == 4
    assert records[-1]["photo"] is None and records[-1]["texts"][0]["name"] == "имя 4"


def test_photo_slot_hidden_by_designer_is_kept_and_marked():
    layout = {"width": 1000, "height": 700, "leaves": [
        leaf("ваше фото", "solidfill", (0, 0, 100, 100), path=[1], visible=False, effectiveVisible=False,
             parentVisible=True),
        leaf("фото2", "shape", (600, 0, 700, 100), parents=["скрытая группа фото"], path=[0, 0],
             visible=False, effectiveVisible=False, parentVisible=False),
    ]}
    [group] = build_page(layout, "cover", set())["groups"]
    [record] = group["records"]
    assert record["photo"]["name"] == "ваше фото" and record["photo"]["hidden"] is True


def test_page_without_slots_has_no_group():
    layout = {"width": 100, "height": 100, "leaves": [leaf("t", "text", (0, 0, 50, 10), text="Заголовок")]}
    page = build_page(layout, "cover", set())
    assert page["groups"] == [] and len(page["fields"]) == 1


def test_one_line_and_sheet_names():
    assert one_line("ИМЯ\x03ФАМИЛИЯ\rКЛАСС") == "ИМЯ / ФАМИЛИЯ / КЛАСС"
    assert len(one_line("a" * 70)) == 60 and one_line("a" * 70).endswith("…")
    taken = set()
    assert unique_sheet_name("Стр 01 (4 фото)", taken) == "Стр 01 (4 фото)"
    assert unique_sheet_name("Стр 01 (4 фото)", taken) == "Стр 01 (4 фото) 2"
    assert unique_sheet_name("bad:/name?", set()) == "badname"


def test_text_direction_comes_from_rotation_not_box_shape():
    layout = {"width": 1000, "height": 700, "leaves": [
        leaf("20", "text", (0, 0, 80, 95), path=[0], rotation=0),        # tall box, horizontal text
        leaf("ИВАНОВА", "text", (900, 0, 950, 600), path=[1], rotation=-90),
        leaf("old", "text", (0, 300, 20, 500), path=[2]),                # no rotation info: box shape
    ]}
    fields = {f["name"]: f for f in build_page(layout, "01", set())["fields"]}
    assert fields["20"]["horizontal"] is True and fields["20"]["limit"] == pytest.approx(92)
    assert fields["ИВАНОВА"]["horizontal"] is False and fields["ИВАНОВА"]["limit"] == pytest.approx(690)
    assert fields["old"]["horizontal"] is False


def test_run_limit():
    text = {"left": 0, "top": 0, "right": 100, "bottom": 20}
    assert run_limit(text) == pytest.approx(115)
    assert run_limit(text, {"left": 0, "top": 0, "right": 300, "bottom": 400}) == 300
    assert run_limit({"left": 0, "top": 0, "right": 20, "bottom": 200}) == pytest.approx(230)


def test_build_manifest_applies_overrides():
    m = build_manifest("T", [("01", grid_layout()), ("02", grid_layout())],
                       {"fixed_fields": ["p02_01"], "sheet_names": {"Стр 01 (4 фото)": "Класс"}})
    assert m["template"] == "T"
    assert m["pages"][0]["groups"][0]["sheet"] == "Класс"
    assert m["pages"][1]["fields"] == []
    assert m["pages"][1]["groups"][0]["sheet"] == "Стр 02 (4 фото)"
