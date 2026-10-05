import pytest

from vignette.autocrop import choose_crop, safe_focus


def window(crop, img_w, img_h, slot_w, slot_h):
    z, fx, fy, rot = crop
    if rot in (90, 270):
        img_w, img_h = img_h, img_w
    s = max(slot_w / img_w, slot_h / img_h) * z
    nw, nh = img_w * s, img_h * s
    x0, y0 = (nw - slot_w) * fx, (nh - slot_h) * fy
    return x0 / nw, y0 / nh, (x0 + slot_w) / nw, (y0 + slot_h) / nh          # visible part, image fractions


def test_group_faces_all_inside_wide_image_in_square_frame():
    faces = [[0.55, 0.30, 0.60, 0.38], [0.70, 0.32, 0.75, 0.40], [0.85, 0.31, 0.90, 0.39]]   # people on the right
    crop = choose_crop(3000, 2000, faces, 1000, 1000)
    x0, y0, x1, y1 = window(crop, 3000, 2000, 1000, 1000)
    assert x0 <= 0.55 and x1 >= 0.90                                   # nobody cut off
    assert crop[1] > 0.5                                               # moved right, not centered


def test_portrait_head_not_cut_in_wide_frame():
    faces = [[0.40, 0.10, 0.60, 0.22]]                                  # face near the top of a tall photo
    crop = choose_crop(2000, 3000, faces, 1500, 700)
    x0, y0, x1, y1 = window(crop, 2000, 3000, 1500, 700)
    assert y0 < 0.10 - 0.12 * 0.4 and y1 > 0.22                         # headroom above, chin inside


def test_focus_region_keeps_face_in_the_clear_part():
    faces = [[0.45, 0.15, 0.55, 0.25]]
    crop = choose_crop(3000, 3000, faces, 2000, 1000, focus=(0.0, 0.0, 0.4, 1.0), zoom_to_focus=True)
    x0, _, x1, _ = window(crop, 3000, 3000, 2000, 1000)
    face_cx = (0.5 - x0) / (x1 - x0)
    assert face_cx < 0.4


def test_no_faces_defaults_and_rotation():
    assert choose_crop(2000, 3000, [], 100, 100) == [1.0, 0.5, 0.3, 0]
    crop = choose_crop(3000, 2000, [[0.1, 0.4, 0.2, 0.5]], 1000, 1500, rot=90)
    assert crop[3] == 90


def test_safe_focus():
    slot = {"left": 0, "top": 0, "right": 1000, "bottom": 1000}
    f = safe_focus(slot, 5000, 3000, 200)
    assert f == pytest.approx((0.2, 0.2, 1.0, 1.0))
    assert safe_focus({"left": 2000, "top": 1000, "right": 2500, "bottom": 1500}, 5000, 3000, 200) == (0.0, 0.0, 1.0, 1.0)


def test_safe_margins_never_zoom():
    faces = [[0.45, 0.2, 0.55, 0.3]]
    assert choose_crop(3000, 2000, faces, 5000, 2500, focus=(0.05, 0.05, 0.95, 0.95))[0] == 1.0
    assert choose_crop(3000, 3000, faces, 2000, 1000, focus=(0.0, 0.0, 0.4, 1.0), zoom_to_focus=True)[0] > 1.0


def cut_faces(crop, faces, img_w, img_h, slot_w, slot_h):
    x0, y0, x1, y1 = window(crop, img_w, img_h, slot_w, slot_h)
    cut = 0
    for f in faces:
        inside_x = f[0] >= x0 and f[2] <= x1
        outside_x = f[2] <= x0 or f[0] >= x1
        inside_y = f[1] >= y0 and f[3] <= y1
        if not (inside_x or outside_x) or (inside_x and not inside_y):
            cut += 1
    return cut


def test_narrow_frame_never_cuts_faces_in_half():
    # a row of 8 people in a wide photo, a tall narrow frame: only ~2 fit, nobody may be cut
    faces = [[0.08 + i * 0.11, 0.30, 0.13 + i * 0.11, 0.38] for i in range(8)]
    crop = choose_crop(3000, 2000, faces, 800, 1300)
    assert cut_faces(crop, faces, 3000, 2000, 800, 1300) == 0
    x0, _, x1, _ = window(crop, 3000, 2000, 800, 1300)
    assert sum(1 for f in faces if f[0] >= x0 and f[2] <= x1) >= 2


def test_crowd_in_square_frame_minimal_cuts():
    faces = [[0.05 + i * 0.075, 0.40 + (i % 2) * 0.03, 0.10 + i * 0.075, 0.47 + (i % 2) * 0.03] for i in range(12)]
    crop = choose_crop(3000, 2000, faces, 1000, 1000)
    assert cut_faces(crop, faces, 3000, 2000, 1000, 1000) == 0


def test_face_stays_in_configured_region_not_pushed_behind_it():
    faces = [[0.35, 0.12, 0.65, 0.35]]                                  # one big face (cover portrait)
    crop = choose_crop(2000, 3000, faces, 2665, 4031, focus=(0.02, 0.0, 0.48, 0.68), zoom_to_focus=True)
    x0, y0, x1, y1 = window(crop, 2000, 3000, 2665, 4031)
    cx = ((0.35 + 0.65) / 2 - x0) / (x1 - x0)
    assert 0.02 <= cx <= 0.48                                            # face center inside the clear part


def test_fits():
    from vignette.autocrop import fits
    row = [[0.1 + i * 0.1, 0.4, 0.15 + i * 0.1, 0.47] for i in range(8)]      # 8 people across a wide photo
    assert not fits(3000, 2000, row, 0.8)                                      # tall frame: no
    assert fits(3000, 2000, row[3:5], 0.8)                                     # two people: yes
    assert fits(3000, 2000, [], 0.5)


def test_clean_faces_drops_screens_and_fabric():
    from vignette.autocrop import clean_faces
    people = [[0.1 * i, 0.5, 0.1 * i + 0.03, 0.54] for i in range(1, 7)]
    screen = [0.4, 0.1, 0.55, 0.3]
    assert clean_faces(people + [screen]) == people
    portrait = [0.4, 0.15, 0.6, 0.3]
    assert clean_faces([portrait, [0.45, 0.7, 0.48, 0.73]]) == [portrait]


def test_lone_tiny_face_is_noise():
    from vignette.autocrop import clean_faces
    assert clean_faces([[0.3, 0.02, 0.32, 0.05]]) == []


def _face_x_in_frame(crop, img_w, img_h, face, slot_w, slot_h):
    s = max(slot_w / img_w, slot_h / img_h) * crop[0]
    nw = img_w * s
    x0 = (nw - slot_w) * crop[1]
    return (face[0] * nw - x0) / slot_w, (face[2] * nw - x0) / slot_w


def test_faces_kept_off_the_spread_fold():
    from vignette.autocrop import choose_crop, fold_gutter
    faces = [[x - 0.02, 0.3, x + 0.02, 0.36] for x in (0.3, 0.5, 0.7)]
    plain = choose_crop(3000, 1000, faces, 1500, 1000)
    a, b = _face_x_in_frame(plain, 3000, 1000, faces[1], 1500, 1000)
    assert a < 0.5 < b                                          # centered group: the middle face on the fold
    gutter = fold_gutter({"left": 1850, "right": 3350}, 5200, 60)   # frame across the middle of the spread
    assert gutter == pytest.approx(((2600 - 60 - 1850) / 1500, (2600 + 60 - 1850) / 1500))
    crop = choose_crop(3000, 1000, faces, 1500, 1000, gutter=gutter)
    for f in faces:
        a, b = _face_x_in_frame(crop, 3000, 1000, f, 1500, 1000)
        assert b <= gutter[0] or a >= gutter[1] or b <= 0 or a >= 1     # no face over the fold
    assert fold_gutter({"left": 0, "right": 2600}, 5200, 60) is None     # a frame on one page only
