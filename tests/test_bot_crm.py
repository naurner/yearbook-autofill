import pytest
from PIL import Image

from bot import crm
from bot.flows import App, handle
from bot.store import Store

ADMIN = 1


class FakeSheet:
    """The CRM Lumi worksheet «Заказы» in memory."""

    def __init__(self, rows):
        self.rows = rows
        self.header = list(rows[0])
        self.writes = []

    def fetch_rows(self):
        return [{h: r.get(h, "") for h in self.header} for r in self.rows]

    def update_order(self, order_id, updates):
        row = next(r for r in self.rows if r["ID"] == order_id)
        assert all(k in self.header for k in updates), updates
        row.update(updates)
        self.writes.append((order_id, dict(updates)))

    def ensure_columns(self, names):
        missing = [n for n in names if n not in self.header]
        self.header += missing
        return missing


def order(oid, school, status, count="2", link="https://baijanov.gallery.photo/gallery/kgma-x1"):
    return {"ID": oid, "Школа/класс": school, "Контактное лицо": "Айгуль", "Телефон": "+996 555 000",
            "Кол-во человек": count, "Статус": status, "Ссылка на исходники": "", "Ссылка на обработанные": link,
            "Ссылка на макет": "", "Примечания": ""}


def texts(outs):
    return " | ".join(o.text for o in outs if o.text)


def buttons(outs):
    return [d for o in outs if o.buttons for row in o.buttons for _, d in row]


@pytest.fixture
def app(tmp_path):
    for sub, nums in {"портретки": range(1001, 1010), "общие": range(2001, 2013)}.items():
        (tmp_path / "photos" / sub).mkdir(parents=True)
        for n in nums:
            Image.new("RGB", (60, 80), "blue").save(tmp_path / "photos" / sub / f"IMG_{n}.jpg")
    sheet = FakeSheet([order("O-1", "Школа 13, 11 Б", "Обработка фото"),
                       order("O-2", "Лицей 5 11А", "Лид"),
                       order("O-3", "Гимназия 7, 9 В", "Вёрстка", link="")])
    a = App(store=Store(tmp_path / "db.sqlite"), admins={ADMIN}, data_dir=tmp_path / "data", bot_username="vbot",
            crm=crm.Crm(sheet))
    a.data_dir.mkdir(parents=True)
    a.sheet = sheet
    return a


def test_prefill_from_an_order():
    o = crm._order(order("O-1", "Школа 13, 11 Б", "Обработка фото", count="24 чел"))
    assert crm.prefill(o) == {"title": "Школа 13, 11 Б", "expected": "24", "field:Класс": "11 “Б”",
                              "source": "https://baijanov.gallery.photo/gallery/kgma-x1"}
    assert crm.class_label("Лицей 5 11А") == "11 “А”" and crm.class_label("11-в") == "11 “В”"
    assert crm.class_label("Школа 13") is None


def test_stage_only_moves_forward():
    assert crm.advance("Обработка фото", "Вёрстка") == "Вёрстка"
    assert crm.advance("Печать", "Вёрстка") is None                       # never back
    assert crm.advance("Выдано", "Печать") is None and crm.advance("странный", "Печать") is None
    c = {"ready": 3, "approved": 1}
    assert crm.target_status(c, 5, False) == "Вёрстка" and crm.target_status(c, 3, False) == "Согласование с клиентом"
    assert crm.target_status({"ready": 3, "approved": 3}, 3, True) == "Печать"


def test_wizard_starts_from_a_crm_order(app, tmp_path):
    outs = handle(app, ADMIN, text="/new")
    assert "crm:O-1" in buttons(outs) and "crm:O-3" in buttons(outs) and "crm:O-2" not in buttons(outs)  # no lead
    handle(app, ADMIN, data="crm:O-1")
    handle(app, ADMIN, data="tpl:Flight")
    step, state = app.store.get_state(ADMIN)
    assert state["steps"][state["i"]] == "title"
    for _ in range(2):                                                    # title, number of students from CRM
        outs = handle(app, ADMIN, data="keep")
    assert "tariff:2" in buttons(outs)
    outs = handle(app, ADMIN, data="tariff:2")
    assert "keep" in buttons(outs)                                        # gallery link offered from CRM
    outs = handle(app, ADMIN, text=str(tmp_path / "photos"))             # but a folder can be given instead
    outs = handle(app, ADMIN, data="year:2026")
    assert "Заказ CRM: Школа 13, 11 Б" in texts(outs) and "Класс: 11 “Б”" in texts(outs)
    outs = handle(app, ADMIN, data="create")
    assert outs[-1].action and outs[-1].action[0] == "crmsync"
    cls = app.store.list_classes()[0]
    assert cls["crm"] == {"order": "O-1"} and cls["expected"] == 2 and cls["title"] == "Школа 13, 11 Б"

    outs = crm.sync(app, only=cls["code"])
    row = app.sheet.rows[0]
    assert row["Статус"] == "Вёрстка" and row["Виньетки"] == "0/2 заполнили, 0 одобрили"
    assert row["Виньетки: ссылка для учеников"] == f"https://t.me/vbot?start={cls['code']}"
    assert "«Вёрстка»" in texts(outs)
    n = len(app.sheet.writes)
    crm.sync(app, only=cls["code"])
    assert len(app.sheet.writes) == n                                     # nothing new: nothing written

    for uid in (100, 200):
        app.store.join(cls["code"], uid)
    for st in app.store.students(cls["code"]):
        app.store.update_student(st["id"], status="approved")
    crm.sync(app, only=cls["code"])
    assert row["Статус"] == "Согласование с клиентом" and row["Виньетки"] == "2/2 заполнили, 2 одобрили"
    app.store.update_class(cls["code"], crm=dict(app.store.get_class(cls["code"])["crm"], built=True))
    crm.sync(app, only=cls["code"])
    assert row["Статус"] == "Печать" and "собраны" in row["Виньетки"]


def test_ready_orders_are_offered_once(app):
    outs = crm.sync(app)
    assert buttons(outs) == ["crmnew:O-1"]                                # O-3 has no gallery, O-2 is a lead
    assert crm.sync(app) == []
    outs = handle(app, ADMIN, data="crmnew:O-1")
    assert "tpl:Flight" in buttons(outs)                                  # straight to the template, order taken
    assert app.store.get_state(ADMIN)[1]["draft"]["crm"] == "O-1"


def test_no_crm_keeps_the_old_wizard(tmp_path):
    a = App(store=Store(tmp_path / "db.sqlite"), admins={ADMIN}, data_dir=tmp_path, bot_username="vbot")
    outs = handle(a, ADMIN, text="/new")
    assert "tpl:Flight" in buttons(outs) and not any(d.startswith("crm:") for d in buttons(outs))
    assert crm.sync(a) == []


def test_a_stage_set_by_hand_in_the_crm_is_kept(app):
    code = app.store.create_class(template="Flight", title="11 Б", expected=2, tariff=2,
                                  source={"kind": "folder", "path": "x"}, fields={}, class_photos={}, common=[],
                                  admin_id=ADMIN, crm={"order": "O-1"})
    row = app.sheet.rows[0]
    crm.sync(app, only=code)
    assert row["Статус"] == "Вёрстка"
    row["Статус"] = "Обработка фото"                                     # the owner moved it back in CRM Lumi
    crm.sync(app, only=code)
    assert row["Статус"] == "Обработка фото"                             # not pushed forward again
    for uid in (100, 200):
        app.store.join(code, uid)
    for st in app.store.students(code):
        app.store.update_student(st["id"], status="filled")
    crm.sync(app, only=code)
    assert row["Статус"] == "Согласование с клиентом"                    # a new milestone moves it on


def test_same_sheet_contract_as_crm_lumi():
    """Columns and stages the vignette bot uses are the ones CRM Lumi has (when its repo is next door)."""
    import sys
    from pathlib import Path
    src = Path(__file__).resolve().parents[3] / "CRM_Lumi" / "src"
    if not (src / "crmlumi" / "models.py").exists():
        pytest.skip("CRM_Lumi is not next to Vinyetka")
    sys.path.insert(0, str(src))
    try:
        from crmlumi.models import FIELD_COLUMNS
        from crmlumi.statuses import FUNNEL_ORDER
    finally:
        sys.path.remove(str(src))
    assert tuple(crm.FUNNEL) == tuple(FUNNEL_ORDER)
    columns = set(FIELD_COLUMNS.values())
    assert set(crm.COL.values()) <= columns and {crm.PROGRESS_COL, crm.LINK_COL} <= columns
