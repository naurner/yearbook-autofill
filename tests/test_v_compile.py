import json
from pathlib import Path

import pytest

from vignette.compile import build_stack, calibrate, text_spec, variable_texts, walk_leaves, with_font_paths
from vignette.config import load_config, manifest_page

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "tests" / "data" / "flight_cover_doc.json").read_text(encoding="utf-8"))
MAN = json.loads((ROOT / "manifests" / "Flight.json").read_text(encoding="utf-8"))
CFG = load_config(ROOT / "configs" / "Flight.json", MAN)
FONT = str(ROOT.parent / "Split" / "fonts" / "DelaGothicOne_Regular.ttf")


def test_walk_order_matches_manifest_layout():
    layout = json.loads((ROOT / "layouts" / "Flight" / "cover.json").read_text(encoding="utf-8"))
    assert [lf["path"] for lf in walk_leaves(DOC)] == [tuple(l["path"]) for l in layout["leaves"]]


def test_clip_base_of_clipped_photo_slot():
    photo = next(lf for lf in walk_leaves(DOC) if lf["name"] == "фото")
    assert photo["clipped"] and photo["base"] == (3,)


def test_variable_texts_from_config():
    v = variable_texts(CFG, MAN)
    assert v["cover"] == {"0", "1", "3.0"}                 # Марина, Коновалова, “22 (year)


def test_build_stack_order_and_masks():
    items, exports, warnings = build_stack(DOC, manifest_page(MAN, "cover"), {"0", "1", "3.0"})
    assert items == [{"run": "run00"}, {"photo": "4", "mask": "mask_4"}, {"text": "3.0"},
                     {"photo": "2", "mask": "mask_2", "mask_texts": ["3.0"]}, {"text": "1"}, {"text": "0"}]
    names = {lf["id"]: lf["name"] for lf in walk_leaves(DOC)}
    run = next(e for e in exports if e["name"] == "run00")
    assert [names[i] for i in run["ids"]] == ["Layer 0", "фото задняя обложка", "Rectangle 1", "ВЫ ПУ СК"]
    mask = next(e for e in exports if e["name"] == "mask_2")
    assert sorted(names[i] for i in mask["ids"]) == ["Rectangle 1", "ВЫ ПУ СК"]     # variable “22 joins at render time
    assert not warnings


def test_text_spec_point_rotated():
    layer = next(lf for lf in walk_leaves(DOC) if lf["name"].startswith("Коновалова"))["layer"]
    spec = text_spec(layer, DOC, 0.5, lambda ps: ("x.ttf", False))
    assert spec["kind"] == "point" and spec["text"] == "Коновалова "
    assert spec["runs"][0]["size"] == pytest.approx(70.8661 * 300 / 72 * 0.5)
    assert spec["runs"][0]["color"] == [255, 255, 255]
    assert spec["matrix"][1] == pytest.approx(-0.0692589)                  # same angle, scaled to A4
    assert spec["origin"][0] == pytest.approx(0.613037 * 5197 * 0.5, rel=1e-3)
    assert spec["paras"][0]["align"] == "center"


def test_text_spec_box_with_leading():
    layer = next(lf for lf in walk_leaves(DOC) if lf["name"] == "ВЫ ПУ СК")["layer"]
    spec = text_spec(layer, DOC, 1.0, lambda ps: ("x.ttf", False))
    assert spec["kind"] == "box" and spec["box"][2] == pytest.approx(344.635 * 300 / 72)
    assert len(spec["runs"]) == 1 and spec["runs"][0]["leading"] == pytest.approx(220 * 300 / 72)


def test_calibrate_recovers_shift_and_scale(tmp_path):
    layer = next(lf for lf in walk_leaves(DOC) if lf["name"].startswith("Коновалова"))["layer"]
    spec = text_spec(layer, DOC, 0.3, lambda ps: (Path(FONT).name, False))
    spec = with_font_paths(spec, Path(FONT).parent)
    from vignette.compile import rendered_box
    _, got, _ = rendered_box(spec, spec["text"], 1.1, (7, -5))
    spec["bounds"] = list(got)
    c = calibrate(spec)
    assert c["scale"] == pytest.approx(1.1, abs=0.03)
    assert c["dx"] == pytest.approx(7, abs=3) and c["dy"] == pytest.approx(-5, abs=3)


def test_text_spec_stroke_and_hidden_fill():
    layer = {"name": "ИВАНОВА", "bounds": {"left": 0, "top": 0, "right": 10, "bottom": 10},
             "blendOptions": {"mode": "lighterColor"},
             "layerEffects": {"frameFX": {"enabled": True, "size": 8, "color": {"red": 255, "green": 255, "blue": 255}}},
             "text": {"textKey": "ИВАНОВА", "textStyleRange": [{"from": 0, "to": 8, "textStyle": {
                 "fontPostScriptName": "X", "size": {"value": 10}, "color": {"red": 18, "green": 13, "blue": 24}}}]}}
    spec = text_spec(layer, DOC, 0.5, lambda ps: ("x.ttf", False))
    assert spec["stroke"] == {"width": 4.0, "color": [255, 255, 255]} and spec["hide_fill"]


def test_text_spec_paragraph_spacing():
    layer = {"name": "x", "bounds": None, "text": {"textKey": "А\rБ",
             "textStyleRange": [{"from": 0, "to": 4, "textStyle": {"size": {"value": 10}}}],
             "paragraphStyleRange": [{"from": 0, "to": 2, "paragraphStyle": {"align": "center",
                                      "spaceAfter": {"value": 13.5888}, "spaceBefore": {"value": 2}}}]}}
    spec = text_spec(layer, DOC, 1.0, lambda ps: ("x.ttf", False))
    assert spec["paras"][0]["space_after"] == pytest.approx(13.5888 * 300 / 72)
    assert spec["paras"][0]["space_before"] == pytest.approx(2 * 300 / 72)
