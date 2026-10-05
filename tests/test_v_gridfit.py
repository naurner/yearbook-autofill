import pytest

from vignette.gridfit import box, overlaps, plan_grid


def grid_records(cols_left=2, cols_right=4, rows=4):
    """A spread 5200 wide: portraits 400x560 with a caption under each, a teacher photo on the left."""
    recs = [{"photo": box(300, 300, 1300, 1900), "texts": []}]                      # big, not a grid cell
    for side, x0, cols in (("l", 1500, cols_left), ("r", 2700, cols_right)):
        for r in range(rows):
            for c in range(cols):
                x, y = x0 + c * 550, 260 + r * 800
                recs.append({"photo": box(x, y, x + 400, y + 560), "texts": [box(x, y + 600, x + 400, y + 680)]})
    return recs


@pytest.mark.parametrize("n", [10, 22, 30, 45])
def test_everyone_placed_clear_of_headings_and_the_fold(n):
    recs = grid_records()
    heading = box(4100, 2700, 4900, 3400)                                           # «ВЫПУСК 2026»
    plan = plan_grid(5200, recs, [heading], n)
    assert plan and len(plan["targets"]) == n
    boxes = [box(t["photo"]["left"], t["photo"]["top"], t["photo"]["right"], t["texts"][0]["bottom"])
             for t in plan["targets"]]
    for b in boxes:
        assert not overlaps(b, heading) and not overlaps(b, recs[0]["photo"])
        assert b["right"] <= 2600 or b["left"] >= 2600                              # nobody on the fold
    for i, a in enumerate(boxes):
        assert not any(overlaps(a, b) for b in boxes[i + 1:])
    if n > 22:
        assert plan["scale"] < 1                                                      # more people: smaller
    if n < 22:
        assert plan["scale"] >= 1


def test_both_halves_used_for_a_few_people():
    plan = plan_grid(5200, grid_records(cols_left=2, cols_right=2, rows=2), [], 3)
    lefts = [t["photo"]["left"] for t in plan["targets"]]
    assert any(x < 2600 for x in lefts) and any(x > 2600 for x in lefts)


def test_too_many_people_is_none():
    assert plan_grid(5200, grid_records(), [], 400) is None
