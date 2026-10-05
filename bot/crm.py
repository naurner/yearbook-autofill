"""Link with CRM Lumi. The studio's orders live in a Google Sheet (worksheet «Заказы»); the CRM Lumi bot polls
it and reacts to a changed «Статус» with notifications and To Do tasks. This bot:
- reads orders to prefill a new class (name, number of students, gallery link, class letter);
- suggests a class when an order's photos are processed and no class is made for it yet;
- writes the vignette progress and a link for students into the order, and moves the order forward:
  class made -> «Вёрстка», everyone filled in -> «Согласование с клиентом», print files built -> «Печать».
Settings in bot.env: CRM_SHEET_ID, CRM_KEY_FILE (the CRM's Google service account key), CRM_WORKSHEET."""
import json
import logging
import re
import threading
import time
from pathlib import Path

from .core import Out

log = logging.getLogger("vignette-bot")

FUNNEL = ("Лид", "Договорились", "Дата и локация назначены", "Ищем фотографа", "Съёмка назначена",
          "Обработка фото", "Вёрстка", "Согласование с клиентом", "Печать", "Выдано")
LAYOUT, APPROVAL, PRINTING, DELIVERED = "Вёрстка", "Согласование с клиентом", "Печать", "Выдано"
# orders offered for a new class: shot already, not handed out
OPEN = FUNNEL[FUNNEL.index("Съёмка назначена"):FUNNEL.index(DELIVERED)]
COL = {"id": "ID", "school": "Школа/класс", "contact": "Контактное лицо", "phone": "Телефон",
       "count": "Кол-во человек", "status": "Статус", "raw": "Ссылка на исходники",
       "processed": "Ссылка на обработанные", "layout": "Ссылка на макет"}
PROGRESS_COL, LINK_COL = "Виньетки", "Виньетки: ссылка для учеников"
CACHE_S = 60


def _order(row):
    return {k: str(row.get(col, "")).strip() for k, col in COL.items()}


class GspreadClient:
    """The worksheet as rows of {header: value}; a row is found by its ID in the first column."""

    def __init__(self, sheet_id, key_file, worksheet="Заказы"):
        import gspread
        book = gspread.service_account(filename=str(key_file)).open_by_key(sheet_id)
        match = [ws for ws in book.worksheets() if ws.title.strip().casefold() == worksheet.strip().casefold()]
        if not match:
            raise ValueError(f"в таблице «{book.title}» нет листа «{worksheet}»")
        self._ws = match[0]                              # «заказы» / «Заказы»: case does not matter

    def fetch_rows(self):
        return self._ws.get_all_records(numericise_ignore=["all"])

    def update_order(self, order_id, updates):
        from gspread.utils import rowcol_to_a1
        cell = self._ws.find(order_id, in_column=1)
        if cell is None:
            raise ValueError(f"заказ {order_id} не найден в таблице")
        header = self._ws.row_values(1)
        data = [{"range": rowcol_to_a1(cell.row, header.index(k) + 1), "values": [[v]]} for k, v in updates.items()]
        if data:
            self._ws.batch_update(data, raw=True)

    def ensure_columns(self, names):
        from gspread.utils import rowcol_to_a1
        header = self._ws.row_values(1)
        missing = [n for n in names if n not in header]
        if missing:
            if self._ws.col_count < len(header) + len(missing):
                self._ws.add_cols(len(header) + len(missing) - self._ws.col_count)
            self._ws.batch_update([{"range": rowcol_to_a1(1, len(header) + 1 + i), "values": [[n]]}
                                   for i, n in enumerate(missing)], raw=True)
        return missing


class Crm:
    def __init__(self, client):
        self.client = client
        self._rows, self._at = None, 0.0
        self._lock = threading.Lock()
        self._columns_ok = False

    def orders(self, fresh=False):
        with self._lock:
            if fresh or self._rows is None or time.time() - self._at > CACHE_S:
                self._rows = [_order(r) for r in self.client.fetch_rows()]
                self._rows = [o for o in self._rows if o["id"]]
                self._at = time.time()
            return list(self._rows)

    def order(self, order_id):
        return next((o for o in self.orders() if o["id"] == order_id), None)

    def update(self, order_id, updates):
        if not updates:
            return
        with self._lock:
            if not self._columns_ok:
                self.client.ensure_columns([PROGRESS_COL, LINK_COL])
                self._columns_ok = True
            self.client.update_order(order_id, updates)
            self._at = 0.0                              # re-read next time


def connect(settings):
    """Crm from bot.env settings, or None when the link is not set up."""
    sheet, key = settings.get("crm_sheet"), settings.get("crm_key")
    if not sheet or not key:
        return None
    if not Path(key).exists():
        log.warning("CRM: нет файла ключа %s — связь с CRM выключена", key)
        return None
    try:
        return Crm(GspreadClient(sheet, key, settings.get("crm_worksheet") or "Заказы"))
    except Exception as e:                              # wrong id, no access, offline
        log.warning("CRM: не удалось открыть таблицу: %s", e)
        return None


# ---- pure pieces ----

CLASS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–]?\s*[«\"“']?\s*([А-ЯЁA-Z])(?![а-яёa-z])[»\"”']?", re.IGNORECASE)


def class_label(school):
    """'Школа 13, 11 Б' -> '11 “Б”' (the «Класс» field of the templates), or None."""
    m = CLASS_RE.search(school or "")
    if not m or not 1 <= int(m.group(1)) <= 11:
        return None
    return f"{m.group(1)} “{m.group(2).upper()}”"


def prefill(order):
    """Wizard answers taken from an order: {step: text}."""
    pre = {}
    if order["school"]:
        pre["title"] = order["school"][:60]
    count = re.sub(r"\D", "", order["count"])
    if count and 0 < int(count) <= 80:
        pre["expected"] = count
    link = order["processed"] or order["raw"]
    if "gallery.photo" in link:
        pre["source"] = link
    label = class_label(order["school"])
    if label:
        pre["field:Класс"] = label
    return pre


def advance(current, target):
    """The status to write so the order moves forward to `target`, or None (never backwards, never out of
    «Выдано», unknown statuses left alone)."""
    if current not in FUNNEL or target not in FUNNEL or current == DELIVERED:
        return None
    return target if FUNNEL.index(target) > FUNNEL.index(current) else None


def target_status(counts, expected, built):
    if built and counts["approved"] >= expected:
        return PRINTING
    if counts["ready"] >= expected:
        return APPROVAL
    return LAYOUT


def progress_text(counts, expected):
    text = f"{counts['ready']}/{expected} заполнили, {counts['approved']} одобрили"
    return text + ", файлы для печати собраны" if counts.get("built") else text


def class_updates(order, counts, expected, built, link):
    """Cells to write into the order for a class, only those that change. The stage moves only when the
    vignette side reaches a new milestone (order["_target"] = the last one pushed), so a stage the studio
    sets by hand in the CRM (e.g. «⬅️ Этап назад») is not overwritten on the next sync."""
    want = {PROGRESS_COL: progress_text(dict(counts, built=built), expected), LINK_COL: link}
    target = target_status(counts, expected, built)
    status = advance(order["status"], target) if target != order.get("_target") else None
    if status:
        want[COL["status"]] = status
    if order.get("_progress") == want[PROGRESS_COL]:
        want.pop(PROGRESS_COL)
    if order.get("_link") == link:
        want.pop(LINK_COL)
    return want


def suggestions(orders, linked, seen):
    """Orders whose photos are processed (a gallery link, stage «Обработка фото» or «Вёрстка»), with no class
    and not offered before."""
    return [o for o in orders if o["status"] in ("Обработка фото", LAYOUT) and o["id"] not in linked
            and o["id"] not in seen and "gallery.photo" in (o["processed"] or o["raw"])]


# ---- bot side ----

def counts_of(app, code):
    sts = app.store.students(code)
    return {"ready": sum(1 for s in sts if s["status"] in ("filled", "previewed", "approved")),
            "approved": sum(1 for s in sts if s["status"] == "approved")}


def _seen_file(app):
    return Path(app.data_dir) / "crm_offered.json"


def sync(app, only=None):
    """Push every linked class's progress and stage into the CRM; offer classes for new ready orders.
    Returns [Out] for the admins."""
    crm = app.crm
    if crm is None:
        return []
    outs = []
    orders = {o["id"]: o for o in crm.orders(fresh=True)}
    linked = set()
    for cls in app.store.list_classes():
        link = cls.get("crm") or {}
        oid = link.get("order")
        if not oid:
            continue
        linked.add(oid)
        if only and cls["code"] != only:
            continue
        order = orders.get(oid)
        if order is None:
            continue
        order = dict(order, _progress=link.get("progress"), _link=link.get("link"), _target=link.get("target"))
        student_link = f"https://t.me/{app.bot_username}?start={cls['code']}"
        counts, built = counts_of(app, cls["code"]), bool(link.get("built"))
        updates = class_updates(order, counts, cls["expected"], built, student_link)
        target = target_status(counts, cls["expected"], built)
        if not updates and target == link.get("target"):
            continue
        crm.update(oid, updates)
        app.store.update_class(cls["code"], crm=dict(link, progress=updates.get(PROGRESS_COL, link.get("progress")),
                                                      link=student_link, target=target))
        if COL["status"] in updates:
            outs += [Out(f"CRM: заказ «{order['school']}» → «{updates[COL['status']]}».", chat=a) for a in app.admins]
    if only:
        return outs
    try:
        seen = set(json.loads(_seen_file(app).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    for o in suggestions(orders.values(), linked, seen):
        seen.add(o["id"])
        people = f", {o['count']} чел." if o["count"] else ""
        outs += [Out(f"📥 CRM: у заказа «{o['school']}»{people} готовы фото ({o['status']}). Создать класс виньеток?",
                     buttons=[[("Создать класс", f"crmnew:{o['id']}")]], chat=a) for a in app.admins]
    _seen_file(app).write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")
    return outs


def order_line(order):
    parts = [f"CRM: «{order['school']}», этап «{order['status']}»"]
    if order["contact"] or order["phone"]:
        parts.append(f"контакт: {order['contact']} {order['phone']}".strip())
    return "\n".join(parts)
