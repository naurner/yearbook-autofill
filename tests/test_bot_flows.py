import pytest
from PIL import Image

from bot.flows import App, handle
from bot.store import Store

ADMIN = 1


@pytest.fixture
def app(tmp_path):
    for sub, nums in {"портретки": range(1001, 1010), "общие": range(2001, 2013)}.items():
        (tmp_path / "photos" / sub).mkdir(parents=True)
        for n in nums:
            Image.new("RGB", (60, 80), "blue").save(tmp_path / "photos" / sub / f"IMG_{n}.jpg")
    return App(store=Store(tmp_path / "db.sqlite"), admins={ADMIN}, data_dir=tmp_path / "data", bot_username="vbot")


def texts(outs):
    return " | ".join(o.text for o in outs if o.text)


def buttons(outs):
    return [d for o in outs if o.buttons for row in o.buttons for _, d in row]


def create_class(app, tmp_path, expected=2, tariff=2):
    outs = handle(app, ADMIN, text="/new")
    assert "tpl:Flight" in buttons(outs) and "tplshow:Flight" in buttons(outs) and outs[0].album
    assert handle(app, ADMIN, data="tplshow:Split")[0].album                  # all pages of a template
    handle(app, ADMIN, data="tpl:Flight")
    handle(app, ADMIN, text="11 Б")
    outs = handle(app, ADMIN, text=str(expected))
    assert [f"tariff:{n}" for n in range(11)] == [d for d in buttons(outs) if d.startswith("tariff:")]
    handle(app, ADMIN, data=f"tariff:{tariff}")
    outs = handle(app, ADMIN, text=str(tmp_path / "photos"))
    assert "Год выпуска" in texts(outs) and any(d.startswith("year:") for d in buttons(outs))
    outs = handle(app, ADMIN, data="year:2026")                          # group photos: all of «общие» by itself
    assert "create" in buttons(outs) and "Общих фото: 12" in texts(outs) and "Класс: 11 “Б”" in texts(outs)
    outs = handle(app, ADMIN, data="create")
    return texts(outs).split("start=")[1].split()[0]


def to_cover(app, uid, code, name="Абишева Алия", pages=("pg+:03", "pg+:03")):
    outs = handle(app, uid, start=code)
    assert "фамилию и имя" in texts(outs) and "back" not in buttons(outs)
    outs = handle(app, uid, text=name)
    assert "pg+:03" in buttons(outs) and "pg+:01" not in buttons(outs)          # grids are never optional
    for p in pages:
        outs = handle(app, uid, data=p)
    return handle(app, uid, data="pg:done")


def fill_student(app, uid, code, name="Абишева Алия", cover="1001"):
    outs = to_cover(app, uid, code, name)
    assert "обложки" in texts(outs)
    assert "Кадра 9999 нет" in texts(handle(app, uid, text="9999"))
    outs = handle(app, uid, text=cover)
    assert outs[0].photo and "ok" in buttons(outs)
    outs = handle(app, uid, data="ok")
    assert outs[0].photo and "adj:zi" in buttons(outs)                          # framing the cover
    outs = handle(app, uid, data="adj:zi")
    assert outs[0].edit and outs[0].photo
    outs = handle(app, uid, data="adj:done")
    assert "same" in buttons(outs)
    handle(app, uid, data="same")
    outs = handle(app, uid, data="adj:done")
    assert "цитата" in texts(outs).lower()
    outs = handle(app, uid, text="Вперёд")
    while "мест для групповых" in texts(outs):
        outs = handle(app, uid, data="skip") if "копия 2" in texts(outs) else handle(app, uid, text="2001, 2002")
    assert "confirm" in buttons(outs)
    return handle(app, uid, data="confirm")


def test_pages_counters_repeat_and_tariff(app, tmp_path):
    code = create_class(app, tmp_path, tariff=2)
    handle(app, 100, start=code)
    handle(app, 100, text="Абишева Алия")
    handle(app, 100, data="pg+:03")
    outs = handle(app, 100, data="pg+:03")
    assert outs[0].edit and "Мои друзья: 2" in [label for row in outs[0].buttons for label, _ in row]
    assert "не больше 2" in texts(handle(app, 100, data="pg+:04"))
    handle(app, 100, data="pg-:03")
    handle(app, 100, data="pg+:04")
    assert app.store.student(code, 100)["pages"] == ["03", "04"]


def test_full_student_flow_and_immediate_preview(app, tmp_path):
    code = create_class(app, tmp_path)
    outs = fill_student(app, 100, code)
    st = app.store.student(code, 100)
    assert st["pages"] == ["03", "03"] and st["cover"] == "1001" and st["portrait"] == "1001"
    assert st["crops"]["cover"][0] > 1 and "portrait" in st["crops"]
    grp = st["grp"]
    assert len(grp) == 1 + 3 + 8 + 8 and grp[:6] == ["2001", "2001", "2002", None, "2001", "2002"]  # back cover first
    assert grp[12:] == [None] * 8
    assert outs[-1].action == ("preview_one", code, st["id"]) and "сеткой класса будет меняться" in texts(outs)
    outs = fill_student(app, 200, code, "Азимбеков Эльдар", cover="1002")
    assert ("previews", code) in [o.action for o in outs]                        # class complete: everyone
    assert any(o.chat == ADMIN and "заполнен" in o.text for o in outs)


def test_group_step_shows_numbered_pages_and_skips_gaps(app, tmp_path):
    code = create_class(app, tmp_path)
    outs = to_cover(app, 100, code, pages=())
    handle(app, 100, text="1001"); handle(app, 100, data="ok"); handle(app, 100, data="adj:done")
    handle(app, 100, data="same"); handle(app, 100, data="adj:done")
    outs = handle(app, 100, data="skip")
    assert "мест для групповых фото — 1" in texts(outs) and outs[0].photo     # the back cover
    outs = handle(app, 100, text="2009")
    assert "мест для групповых фото — 3" in texts(outs) and outs[0].photo
    outs = handle(app, 100, text="2010-2020")                                   # only 2010..2012 exist
    assert "confirm" in buttons(outs)
    assert app.store.student(code, 100)["grp"] == ["2009", "2010", "2011", "2012"]
    handle(app, 100, data="edit")
    handle(app, 100, data="e:group")
    assert "Нет кадров" in texts(handle(app, 100, text="2001, 2099"))
    assert "нет ни одного" in texts(handle(app, 100, text="3000-3005"))


def test_back_buttons(app, tmp_path):
    code = create_class(app, tmp_path, expected=5)
    handle(app, 100, start=code)
    outs = handle(app, 100, text="Абишева Алия")
    assert "back" in buttons(outs)
    assert "фамилию и имя" in texts(handle(app, 100, data="back"))
    handle(app, 100, text="Абишева Алия")
    handle(app, 100, data="pg:done")
    handle(app, 100, text="1001")
    handle(app, 100, data="ok")
    outs = handle(app, 100, data="back")                                         # from framing to the number
    assert "обложки" in texts(outs)
    handle(app, 100, text="1001"); handle(app, 100, data="ok"); handle(app, 100, data="adj:done")
    handle(app, 100, data="same"); handle(app, 100, data="adj:done")
    handle(app, 100, data="skip")
    outs = handle(app, 100, text="2001")
    outs = handle(app, 100, data="back")                                         # summary -> last group page
    assert "мест для групповых" in texts(outs)
    handle(app, ADMIN, text="/new"); handle(app, ADMIN, data="tpl:Flight")
    outs = handle(app, ADMIN, text="11 Б")
    assert "Название класса" in texts(handle(app, ADMIN, data="back"))


def test_crop_menu_and_edit_after_approve(app, tmp_path):
    code = create_class(app, tmp_path, expected=1)
    fill_student(app, 100, code)
    st = app.store.student(code, 100)
    app.store.update_student(st["id"], status="previewed")
    outs = handle(app, 100, data="approve")
    assert "одобрено" in texts(outs) and any(o.chat == ADMIN and "одобрили" in o.text for o in outs)
    outs = handle(app, 100, data="edit")
    assert "e:croplist" in buttons(outs)
    outs = handle(app, 100, data="e:croplist")
    assert "crop:cover" in buttons(outs) and "crop:g0" in buttons(outs)
    outs = handle(app, 100, data="crop:g0")
    handle(app, 100, data="adj:r")
    outs = handle(app, 100, data="adj:done")
    assert "crop:g0" in buttons(outs)
    assert app.store.student(code, 100)["crops"]["g0"][1] > 0.5
    assert app.store.student(code, 100)["status"] == "filling"
    outs = handle(app, 100, data="back")
    assert "confirm" in buttons(outs)
    app.store.update_class(code, status="preview")
    assert handle(app, 100, data="confirm")[0].action == ("preview_one", code, st["id"])


def test_resume_after_restart(app, tmp_path):
    code = create_class(app, tmp_path)
    handle(app, 300, start=code)
    handle(app, 300, text="Айнабеков Атай")
    app2 = App(store=type(app.store)(tmp_path / "db.sqlite"), admins={ADMIN}, data_dir=app.data_dir)
    outs = handle(app2, 300, text="/menu")
    assert "Продолжим" in texts(outs) and "pg+:03" in buttons(outs)


def test_admin_card_and_actions(app, tmp_path):
    code = create_class(app, tmp_path)
    outs = handle(app, ADMIN, text="/classes")
    assert f"cls:{code}" in buttons(outs)
    outs = handle(app, ADMIN, data=f"cls:{code}")
    assert f"act:xlsx:{code}" in buttons(outs) and f"act:build:{code}" not in buttons(outs)
    assert handle(app, ADMIN, data=f"act:xlsx:{code}")[0].action == ("xlsx", code)
    handle(app, ADMIN, data=f"act:toggle:{code}")
    assert "закрыт" in texts(handle(app, 555, start=code))
    assert "устарела" in texts(handle(app, 555, start="nope"))
    assert handle(app, 555, data=f"act:xlsx:{code}")[0].action is None


def test_source_errors_are_friendly(app, tmp_path, monkeypatch):
    code = create_class(app, tmp_path, expected=5)
    to_cover(app, 100, code, pages=())
    src = app.source(app.store.get_class(code))

    def boom(*a, **k):
        raise OSError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(src, "find", boom)
    monkeypatch.setattr(src, "has", boom)
    assert "недоступн" in texts(handle(app, 100, text="1001"))


def test_page_removed_from_the_template_is_ignored(app, tmp_path):
    code = create_class(app, tmp_path)
    fill_student(app, 100, code)
    st = app.store.student(code, 100)
    app.store.update_student(st["id"], pages=["03", "99"])                  # «99» is no longer in the template
    outs = handle(app, 100, text="/menu")
    assert "Мои друзья" in texts(outs)
    handle(app, 100, data="edit")
    handle(app, 100, data="e:pages")
    outs = handle(app, 100, data="pg+:03")
    assert "сейчас 2" in texts(outs)
    handle(app, 100, data="pg:done")
    assert app.store.student(code, 100)["pages"] == ["03", "03"]


def test_short_wizard_for_split_and_captions_in_the_card(app, tmp_path):
    from bot.admin import school_text
    assert school_text("11 Б школа 13") == "ШКОЛА 13" and school_text("Гимназия 5, 11-А") == "ГИМНАЗИЯ 5"
    assert school_text("11 Б") == ""
    handle(app, ADMIN, text="/new")
    handle(app, ADMIN, data="tpl:Split")
    handle(app, ADMIN, text="11 Б школа 13")
    handle(app, ADMIN, text="3")
    handle(app, ADMIN, data="tariff:2")
    outs = handle(app, ADMIN, text=str(tmp_path / "photos"))
    assert "Классный руководитель" in texts(outs)                       # Split's grid has the teacher
    assert "Нужны имя и фамилия" in texts(handle(app, ADMIN, text="Анна"))
    outs = handle(app, ADMIN, text="Анна Иванова")
    assert "номер кадра" in texts(outs)
    outs = handle(app, ADMIN, text="1001")
    assert "create" in buttons(outs) and "Друзья" not in texts(outs)    # no questions about friends' captions
    outs = handle(app, ADMIN, data="create")
    code = texts(outs).split("start=")[1].split()[0]
    cls = app.store.get_class(code)
    assert cls["fields"]["Классный руководитель: имя"] == "Анна" and cls["class_photos"]
    card = handle(app, ADMIN, data=f"cls:{code}")
    assert f"act:fields:{code}" in buttons(card)
    menu = handle(app, ADMIN, data=f"act:fields:{code}")
    assert "Город: Г.БИШКЕК" in texts(menu)                              # config default
    n = next(i for i, d in enumerate(d for d in buttons(menu) if d.startswith("fld:")) if True)
    outs = handle(app, ADMIN, data=f"fld:{code}:{n}")
    assert "fld:hide" in buttons(outs)
    handle(app, ADMIN, text="Г.ОШ")
    assert app.store.get_class(code)["fields"]["Город"] == "Г.ОШ"
