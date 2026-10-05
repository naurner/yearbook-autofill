from pathlib import Path

import pytest

from vignette.textrender import remap_runs, render

FONT = str(Path(__file__).resolve().parents[2] / "Split" / "fonts" / "DelaGothicOne_Regular.ttf")


def spec(text="ИМЯ", align="center", kind="point", box=None, matrix=(1, 0, 0, 1), runs=None, leading=None):
    runs = runs or [{"from": 0, "to": len(text) + 1, "font": FONT, "index": 0, "size": 40, "color": [255, 0, 0],
                     "tracking": 0, "leading": leading, "caps": False}]
    return {"text": text, "kind": kind, "box": box, "matrix": list(matrix), "runs": runs,
            "paras": [{"from": 0, "to": len(text) + 1, "align": align}]}


def alpha_box(img):
    return img.getchannel("A").getbbox()


def test_width_grows_with_text():
    a, _ = render(spec(), "ИМЯ")
    b, _ = render(spec(), "ИМЯ ФАМИЛИЯ")
    assert alpha_box(b)[2] - alpha_box(b)[0] > 2 * (alpha_box(a)[2] - alpha_box(a)[0])


@pytest.mark.parametrize("align, rel", [("center", 0.5), ("left", 0.0), ("right", 1.0)])
def test_alignment_relative_to_origin(align, rel):
    img, (ox, oy) = render(spec(align=align), "ТЕКСТ")
    l, t, r, b = alpha_box(img)
    assert abs((l + (r - l) * rel) - ox) <= 4
    assert t < oy <= b + 2                                   # origin is on the baseline


def test_line_breaks_and_leading():
    one, _ = render(spec(), "АБВ")
    two, _ = render(spec(leading=80), "АБВ\x03ГЕЖ")        # no descenders: height grows by leading only
    three, _ = render(spec(leading=80), "АБВ\rГЕЖ\rЖЗИ")
    h = lambda im: alpha_box(im)[3] - alpha_box(im)[1]
    assert h(two) - h(one) == pytest.approx(80, abs=4)
    assert h(three) - h(two) == pytest.approx(80, abs=4)


def test_box_text_wraps_inside_box():
    img, (ox, oy) = render(spec(kind="box", box=[0, 0, 260, 600], align="left"), "ОДИН ДВА ТРИ ПЯТЬ ШЕСТЬ СЕМЬ")
    l, t, r, b = alpha_box(img)
    assert r - l <= 264 and b - t > 100


def test_rotation_swaps_dimensions():
    flat, _ = render(spec(), "ФАМИЛИЯ")
    rot, _ = render(spec(matrix=(0, -1, 1, 0)), "ФАМИЛИЯ")
    fw, fh = alpha_box(flat)[2] - alpha_box(flat)[0], alpha_box(flat)[3] - alpha_box(flat)[1]
    rw, rh = alpha_box(rot)[2] - alpha_box(rot)[0], alpha_box(rot)[3] - alpha_box(rot)[1]
    assert rw == pytest.approx(fh, abs=4) and rh == pytest.approx(fw, abs=4)


def test_tracking_widens():
    s = spec()
    s["runs"][0]["tracking"] = 200
    wide, _ = render(s, "ТЕКСТ")
    narrow, _ = render(spec(), "ТЕКСТ")
    assert alpha_box(wide)[2] - alpha_box(wide)[0] > alpha_box(narrow)[2] - alpha_box(narrow)[0] + 20


def test_scale_argument():
    a, _ = render(spec(), "ТЕКСТ")
    b, _ = render(spec(), "ТЕКСТ", scale=0.5)
    assert alpha_box(b)[2] - alpha_box(b)[0] == pytest.approx((alpha_box(a)[2] - alpha_box(a)[0]) / 2, abs=4)


def test_remap_runs_word_and_line_styles():
    runs = [{"from": 0, "to": 3, "size": 10}, {"from": 3, "to": 8, "size": 20}]     # "ИМЯ\x03ФАМ" + trailing
    new = remap_runs(runs, "ИМЯ\x03ФАМ", "АННА\x03ПЕТРОВА")
    assert [(r["from"], r["to"], r["size"]) for r in new] == [(0, 5, 10), (5, 13, 20)]


def test_stroke_and_hidden_fill():
    plain, _ = render(spec(), "ИВАНОВА")
    s = spec()
    s["stroke"] = {"width": 3, "color": [255, 255, 255]}
    stroked, _ = render(s, "ИВАНОВА")
    assert alpha_box(stroked)[2] - alpha_box(stroked)[0] >= alpha_box(plain)[2] - alpha_box(plain)[0] + 4
    s["hide_fill"] = True
    outline, _ = render(s, "ИВАНОВА")
    opaque = lambda im: sum(1 for a in im.getchannel("A").getdata() if a > 128)
    assert opaque(outline) < opaque(stroked) * 0.8


def test_paragraph_space_after_only_between_paragraphs():
    s = spec(leading=10)
    s["paras"] = [{"from": 0, "to": 8, "align": "center", "space_after": 30, "space_before": 0}]
    soft, _ = render(s, "АБВ\x03ГЕЖ")
    hard, _ = render(s, "АБВ\rГЕЖ")
    h = lambda im: alpha_box(im)[3] - alpha_box(im)[1]
    assert h(hard) - h(soft) == pytest.approx(30, abs=3)
