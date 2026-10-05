from autofill.layout import is_photo_leaf, pair_captions, photo_slots, reading_order
from helpers import box, leaf


def test_unnamed_overlay_next_to_named_slots_is_decor():
    leaves = [
        leaf("фото1", "solidfill", (0, 0, 10, 10), parents=["фото "], path=[3, 0]),
        leaf("фото2", "solidfill", (20, 0, 30, 10), parents=["фото "], path=[3, 1]),
        leaf("затемнее ", "normal", (0, 0, 900, 900), parents=["фото "], path=[3, 2]),
        leaf("Rectangle 1", "shape", (0, 0, 10, 10), parents=["фото"], path=[4, 0]),
        leaf("Rectangle 2", "shape", (20, 0, 30, 10), parents=["фото"], path=[4, 1]),
    ]
    assert [x["name"] for x in photo_slots(leaves)] == ["фото1", "фото2", "Rectangle 1", "Rectangle 2"]


def test_photo_by_own_name():
    assert is_photo_leaf(leaf("фото3", "shape", (0, 0, 10, 10)))


def test_photo_by_group_even_with_odd_name():
    assert is_photo_leaf(leaf("йото11", "shape", (0, 0, 10, 10)))
    assert is_photo_leaf(leaf("Rectangle 5", "pixel", (0, 0, 10, 10), parents=["фото "]))
    assert is_photo_leaf(leaf("Фото1", "pixel", (0, 0, 10, 10), parents=["Фото"]))


def test_decor_on_photo_is_not_photo():
    assert not is_photo_leaf(leaf("элемент1", "pixel", (0, 0, 10, 10), parents=["декор на фото "]))


def test_text_is_never_photo():
    assert not is_photo_leaf(leaf("фото подпись", "text", (0, 0, 10, 10), parents=["фото"]))


def test_plain_decor_is_not_photo():
    assert not is_photo_leaf(leaf("bg", "pixel", (0, 0, 10, 10), parents=["фон"]))


def test_reading_order_left_half_then_right_rows_then_columns():
    boxes = [
        box(600, 0, 700, 100),    # 0: right half
        box(200, 205, 300, 300),  # 1: left, row 2, col 2
        box(0, 0, 100, 100),      # 2: left, row 1, col 1
        box(0, 200, 100, 300),    # 3: left, row 2, col 1
        box(200, 5, 300, 105),    # 4: left, row 1, col 2 (slightly lower)
    ]
    assert reading_order(boxes, 1000) == [2, 4, 3, 1, 0]


def test_reading_order_tall_box_starts_in_the_row_of_its_top_edge():
    boxes = [
        box(200, 0, 300, 100),    # 0: row 1, col 2
        box(0, 0, 150, 300),      # 1: tall photo spanning two rows, col 1
        box(200, 200, 300, 300),  # 2: row 2, col 2
    ]
    assert reading_order(boxes, 1000) == [1, 0, 2]


def test_reading_order_empty():
    assert reading_order([], 1000) == []


def test_pair_captions_under_photos():
    photos = [box(0, 0, 100, 120), box(150, 0, 250, 120), box(0, 200, 100, 320)]
    caps = [box(160, 125, 240, 140), box(10, 125, 90, 140), box(10, 325, 90, 340)]
    assert pair_captions(photos, caps) == {0: 1, 1: 0, 2: 2}


def test_pair_captions_skips_above_and_far_below():
    photos = [box(0, 200, 100, 300)]
    caps = [box(10, 150, 90, 170), box(10, 900, 90, 920)]
    assert pair_captions(photos, caps) == {}


def test_each_photo_gets_one_caption():
    photos = [box(0, 0, 100, 100)]
    caps = [box(10, 105, 90, 115), box(10, 130, 90, 140)]
    assert pair_captions(photos, caps) == {0: 0}
