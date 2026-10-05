"""Studio side: class creation wizard, class list/card, class actions."""
import datetime
import re

from vignette.config import HIDE, class_photo_labels, field_slots

from . import crm as crmlink
from .core import TEMPLATES, Out, is_admin, optional_pages, page_preview, pick_frames, with_back
from .photos import NumbersError, make_source, parse_numbers, parse_source

MAX_TARIFF = 10
YEAR, CLASS, SCHOOL = "Год выпуска", "Класс", "Школа"
TEACHER_FIRST, TEACHER_LAST = "Классный руководитель: имя", "Классный руководитель: фамилия"


def admin_fields(cfg, man):
    return [f for f in field_slots(cfg, man) if not f["personal"]]


def school_text(title):
    """'11 Б школа 13' -> 'ШКОЛА 13': the class name without the class number and letter."""
    rest = crmlink.CLASS_RE.sub(" ", title or "")
    rest = re.sub(r"^[\s,.;:–-]+|[\s,.;:–-]+$", "", re.sub(r"\s+", " ", rest))
    return rest.upper()


def auto_fields(cfg, man, title, year=None):
    """Class fields the bot fills by itself: class number and school from the class name, the year."""
    labels = {f["label"] for f in admin_fields(cfg, man)}
    out = {}
    label = crmlink.class_label(title)
    if CLASS in labels and label:
        out[CLASS] = label
    if SCHOOL in labels:
        out[SCHOOL] = school_text(title) or HIDE
    if YEAR in labels and year:
        out[YEAR] = str(year)
    return out


def _years():
    y = datetime.date.today().year
    return [y, y + 1]


def admin_help():
    return Out("Команды:\n/new — новый класс\n/classes — классы: заполнение, превью, таблица, печать")


def admin_new(app, uid, order_id=None):
    """The class wizard; with the CRM linked it starts from the order (or from `order_id` straight away)."""
    draft = {}
    if order_id and app.crm:
        _take_order(app, draft, order_id)
    steps = ["crm", "template"] if app.crm and not order_id else ["template"]
    app.store.set_state(uid, "a:new", {"i": 0, "steps": steps, "draft": draft})
    return admin_prompt(app, uid, steps[0], draft)


def _take_order(app, draft, order_id):
    order = app.crm.order(order_id)
    if order:
        draft["crm"] = order_id
        draft["pre"] = crmlink.prefill(order)


def _open_orders(app):
    linked = {(c.get("crm") or {}).get("order") for c in app.store.list_classes()}
    return [o for o in app.crm.orders() if o["status"] in crmlink.OPEN and o["id"] not in linked]


def _wizard_steps(app, template, crm_step=False):
    """Only what the bot cannot work out: the rest comes from the class name, the config or the template
    and can be changed later in the class card («✏️ Подписи»)."""
    cfg, man = app.template(template)
    labels = {f["label"] for f in admin_fields(cfg, man)}
    steps = (["crm"] if crm_step else []) + ["template", "title", "expected", "tariff", "source"]
    if YEAR in labels:
        steps.append("year")
    if TEACHER_FIRST in labels:
        steps.append("teacher")
    steps += ["cphoto:" + label for label in class_photo_labels(cfg)]
    return steps + ["common", "confirm"]


def _skipped(step, draft):
    """Steps answered by themselves: group photos are all of the gallery's «общие» when it can list them."""
    return step == "common" and bool(draft.get("common"))


def _mockup(template):
    """The album mockup of a template (work/make_mockups.py), if made."""
    from vignette.showcase import showcase_dir
    p = showcase_dir(template) / "mockup.jpg"
    return str(p) if p.exists() else None


def template_album(template):
    cfg = None
    from vignette.cli_common import load_manifest
    from vignette.config import load_template_config
    cfg = load_template_config(template, load_manifest(template))
    pics = [(_mockup(template), f"{template}: так выглядит альбом")]
    pics += [(page_preview(template, p["page"]), p["title"]) for p in cfg["pages"]]
    return [(p, c) for p, c in pics if p][:10]


def admin_prompt(app, uid, step, draft):
    outs = _admin_prompt(app, uid, step, draft)
    kept = (draft.get("pre") or {}).get(step)
    if kept and outs and outs[-1].text and step != "confirm":
        short = kept if len(kept) <= 40 else kept[:37] + "…"
        outs[-1].buttons = [[(f"✅ Из CRM: {short}", "keep")]] + (outs[-1].buttons or [])
    steps = app.store.get_state(uid)[1].get("steps") or [step]
    return outs if step == steps[0] else with_back(outs)


def _admin_prompt(app, uid, step, draft):
    skip = [[("Пропустить", "skip")]]
    if step == "crm":
        try:
            orders = _open_orders(app)
        except Exception as e:                          # sheet unreachable: the wizard goes on without it
            orders = None
            note = f"CRM сейчас недоступна ({e})."
        if orders is None:
            return [Out(f"{note} Выберите «Без заказа CRM».", buttons=[[("Без заказа CRM", "crm:-")]])]
        rows = [[(f"{o['school'][:40]} · {o['status']}", f"crm:{o['id']}")] for o in orders[:20]]
        text = ("Новый класс. Для какого заказа из CRM? Название, число учеников и ссылку на галерею подставлю "
                "из заказа." if rows else "В CRM нет заказов после съёмки без класса.")
        return [Out(text, buttons=rows + [[("Без заказа CRM", "crm:-")]])]
    if step == "template":
        covers = [(_mockup(t) or page_preview(t, "cover" if t != "Split" else "cover1"), t) for t in TEMPLATES]
        return [Out(album=[a for a in covers if a[0]]),
                Out("Новый класс. Выберите шаблон (👁 — посмотреть все страницы шаблона):",
                    buttons=[[(t, f"tpl:{t}"), ("👁", f"tplshow:{t}")] for t in TEMPLATES])]
    if step == "title":
        return [Out("Название класса, например «11 Б школа 13». Номер класса и школу поставлю в макет сам.")]
    if step == "expected":
        return [Out("Сколько учеников в классе? (число)")]
    if step == "tariff":
        cfg, _ = app.template(draft["template"])
        opt = optional_pages(cfg)
        names = "\n".join(f"• {p['title']}" for p in opt)
        req = ", ".join(p["title"] for p in cfg["pages"] if p.get("required"))
        return [Out(f"Тариф класса: сколько дополнительных страниц может выбрать ученик (до {MAX_TARIFF}; "
                    f"одну страницу можно взять несколько раз с разными фото)?\n"
                    f"Обязательные (всегда): {req}.\nДополнительные на выбор:\n{names}",
                    buttons=[[(str(n), f"tariff:{n}") for n in range(0, 6)],
                             [(str(n), f"tariff:{n}") for n in range(6, MAX_TARIFF + 1)]])]
    if step == "source":
        return [Out("Где фото класса? Пришлите ссылку на галерею gallery.photo (или на любое фото из неё). "
                    "Если портреты и общие фото в разных галереях — две ссылки, каждая с новой строки: "
                    "сначала портреты, потом общие. Разделы галереи «портретки»/«общие» бот различает сам.\n"
                    "Можно и путь к папке на этом компьютере (с подпапками «портретки» и «общие»).")]
    if step == "year":
        return [Out("Год выпуска:", buttons=[[(str(y), f"year:{y}") for y in _years()]])]
    if step == "teacher":
        return [Out("Классный руководитель — имя и фамилия, например «Анна Иванова»:")]
    if step.startswith("cphoto:"):
        return [Out(f"«{step[7:]}»: номер кадра с этим фото.", buttons=skip)]
    if step == "common":
        src_can_list = draft.get("source", {}).get("kind") in ("folder", "gallery")
        extra = " или «все» — все кадры из «общих»" if src_can_list else ""
        return [Out("Групповые фото по умолчанию (ими заполняются места, которые ученик не выбрал): "
                    f"номера через запятую, можно диапазоны 2001-2040{extra}.", buttons=skip)]
    if step == "confirm":
        return [Out(admin_summary(draft), buttons=[[("Создать класс", "create"), ("Отмена", "cancel")]])]
    raise ValueError(step)


def admin_summary(d):
    lines = [f"Заказ CRM: {d['pre'].get('title', d['crm'])}"] if d.get("crm") else []
    lines += [f"Шаблон: {d['template']}", f"Класс: {d['title']}", f"Учеников: {d['expected']}",
              f"Доп. страниц: {d['tariff']}", f"Фото: {d['source'].get('path') or d['source'].get('portraits')}"]
    lines += [f"{k}: {'не печатается' if v == HIDE else v}" for k, v in d.get("fields", {}).items()]
    lines += [f"{k}: кадр {v}" for k, v in d.get("class_photos", {}).items()]
    lines.append(f"Общих фото: {len(d.get('common', []))}")
    return "Проверьте:\n" + "\n".join(lines) + "\n\nПодписи можно поправить потом: карточка класса → «✏️ Подписи»."


def admin_wizard(app, uid, step, state, text, data):
    if step == "a:fld":
        return field_edit(app, uid, state, text, data)
    draft, steps, i = state["draft"], state["steps"], state["i"]
    cur = steps[i]
    if data == "keep" and (draft.get("pre") or {}).get(cur):
        text, data = draft["pre"][cur], None
    if data == "cancel":
        app.store.set_state(uid, None)
        return [Out("Создание класса отменено.", edit=True)]
    if data and data.startswith("tplshow:"):
        t = data[8:]
        return [Out(album=template_album(t)), Out(f"Это страницы шаблона {t}. Выберите шаблон:",
                                                  buttons=[[(x, f"tpl:{x}"), ("👁", f"tplshow:{x}")] for x in TEMPLATES])]
    if data == "back":
        i = max(0, i - 1)
        while i > 0 and _skipped(steps[i], draft):
            i -= 1
        app.store.set_state(uid, "a:new", {"i": i, "steps": steps, "draft": draft})
        return admin_prompt(app, uid, steps[i], draft)
    value = (text or "").strip()
    err = None
    if cur == "crm":
        if not (data or "").startswith("crm:"):
            return admin_prompt(app, uid, cur, draft)
        draft.pop("crm", None)
        draft.pop("pre", None)
        if data != "crm:-":
            _take_order(app, draft, data[4:])
    elif cur == "template":
        if not (data or "").startswith("tpl:"):
            return admin_prompt(app, uid, cur, draft)
        draft["template"] = data[4:]
        steps = _wizard_steps(app, draft["template"], crm_step=steps[0] == "crm")
        i = steps.index("template")
    elif cur == "title":
        err = None if 0 < len(value) <= 60 else "Нужно название до 60 символов."
        draft["title"] = value
        cfg, man = app.template(draft["template"])
        draft["fields"] = {**draft.get("fields", {}), **auto_fields(cfg, man, value)}
    elif cur == "expected":
        err = None if value.isdigit() and 0 < int(value) <= 80 else "Нужно число от 1 до 80."
        draft["expected"] = int(value) if not err else None
    elif cur == "tariff":
        if not (data or "").startswith("tariff:"):
            return admin_prompt(app, uid, cur, draft)
        draft["tariff"] = int(data[7:])
    elif cur == "source":
        try:
            draft["source"] = parse_source(value)
            src = make_source(draft["source"], app.data_dir / "tmp_cache")
            draft["common"] = src.numbers("common") if src.can_list else []
        except (ValueError, OSError) as e:
            err = f"Не подходит: {e}."
    elif cur == "year":
        if not (data or "").startswith("year:"):
            return admin_prompt(app, uid, cur, draft)
        draft.setdefault("fields", {})[YEAR] = data[5:]
    elif cur == "teacher":
        words = value.split()
        if len(words) < 2:
            return [Out("Нужны имя и фамилия через пробел, например «Анна Иванова».")]
        draft.setdefault("fields", {}).update({TEACHER_FIRST: words[0], TEACHER_LAST: " ".join(words[1:])})
    elif cur.startswith("cphoto:"):
        if data != "skip":
            src = make_source(draft["source"], app.data_dir / "tmp_cache")
            try:
                nums = parse_numbers(value)
            except NumbersError as e:
                nums, err = [], str(e)
            if not err and len(nums) != 1:
                err = "Нужен один номер кадра."
            if not err and not (src.has(nums[0], "portrait") or src.has(nums[0], "common")):
                err = f"Кадр {nums[0]} не найден."
            if not err:
                draft.setdefault("class_photos", {})[cur[7:]] = nums[0]
    elif cur == "common":
        if data != "skip":
            src = make_source(draft["source"], app.data_dir / "tmp_cache")
            if value.casefold() == "все" and src.can_list:
                draft["common"] = src.numbers("common")
            else:
                nums, err = pick_frames(src, value, "common")
                draft["common"] = nums
    elif cur == "confirm":
        if data != "create":
            return admin_prompt(app, uid, cur, draft)
        code = app.store.create_class(template=draft["template"], title=draft["title"], expected=draft["expected"],
                                      tariff=draft["tariff"], source=draft["source"], fields=draft.get("fields", {}),
                                      class_photos=draft.get("class_photos", {}), common=draft.get("common", []),
                                      admin_id=uid, crm={"order": draft["crm"]} if draft.get("crm") else None)
        app.store.set_state(uid, None)
        link = f"https://t.me/{app.bot_username}?start={code}"
        outs = [Out(f"Класс «{draft['title']}» создан. Ссылка для учеников:\n{link}", edit=True)]
        if app.photoshop:
            outs.append(Out(f"Готовлю сетку класса под {draft['expected']} учеников (несколько минут)…",
                            action=("grids", code)))
        if draft.get("crm"):
            outs.append(Out("Записываю в CRM ссылку для учеников и этап «Вёрстка»…", action=("crmsync", code)))
        return outs
    if err:
        return [Out(err)] + admin_prompt(app, uid, cur, draft)
    i += 1
    while _skipped(steps[i], draft):
        i += 1
    app.store.set_state(uid, "a:new", {"i": i, "steps": steps, "draft": draft})
    return admin_prompt(app, uid, steps[i], draft)


# ---- class card: «✏️ Подписи» ----

def _field_value(cfg, man, cls, f):
    v = (cls["fields"] or {}).get(f["label"]) or f.get("default")
    if v == HIDE:
        return "не печатается"
    if v:
        return v
    return f["layers"][0][1]["default"].replace("\r", " ").replace("\x03", " ") + " (как в шаблоне)"


def fields_menu(app, code):
    cls = app.store.get_class(code)
    cfg, man = app.template(cls["template"])
    fields = admin_fields(cfg, man)
    lines = [f"• {f['label']}: {_field_value(cfg, man, cls, f)[:60]}" for f in fields]
    rows = [[(f["label"][:40], f"fld:{code}:{n}")] for n, f in enumerate(fields)]
    return Out(f"Подписи класса «{cls['title']}» (общие для всех учеников):\n" + "\n".join(lines) +
               "\n\nНажмите подпись, чтобы изменить.", buttons=rows + [[("⬅️ К классу", f"cls:{code}")]])


def field_pick(app, uid, data):
    _, code, n = data.split(":")
    cls = app.store.get_class(code)
    cfg, man = app.template(cls["template"])
    f = admin_fields(cfg, man)[int(n)]
    app.store.set_state(uid, "a:fld", {"code": code, "label": f["label"]})
    return [Out(f"«{f['label']}» — сейчас: {_field_value(cfg, man, cls, f)}.\nНапишите новый текст.",
                buttons=[[("Как в шаблоне", "fld:reset"), ("Не печатать", "fld:hide")],
                         [("⬅️ Назад", f"act:fields:{code}")]])]


def field_edit(app, uid, state, text, data):
    code, label = state["code"], state["label"]
    cls = app.store.get_class(code)
    fields = dict(cls["fields"] or {})
    if data == "fld:reset":
        fields.pop(label, None)
    elif data == "fld:hide":
        fields[label] = HIDE
    elif text and text.strip():
        fields[label] = text.strip()
    else:
        return [Out("Напишите текст подписи или выберите кнопку.")]
    app.store.update_class(code, fields=fields)
    app.store.set_state(uid, None)
    return [Out("Сохранено. Превью учеников обновятся при следующей рассылке."), fields_menu(app, code)]


def class_counts(app, code):
    sts = app.store.students(code)
    by = {s: sum(1 for x in sts if x["status"] == s) for s in ("filling", "filled", "previewed", "approved")}
    return by, sts


def admin_classes(app):
    classes = app.store.list_classes()
    if not classes:
        return [Out("Классов пока нет. /new — создать.")]
    rows = []
    for c in classes:
        by, _ = class_counts(app, c["code"])
        ready = by["filled"] + by["previewed"] + by["approved"]
        rows.append([(f"{c['title']} — {ready}/{c['expected']}, одобрили {by['approved']}", f"cls:{c['code']}")])
    return [Out("Классы:", buttons=rows)]


def class_card(app, code):
    c = app.store.get_class(code)
    by, _ = class_counts(app, code)
    text = (f"«{c['title']}» ({c['template']}), статус: {c['status']}\n"
            f"Заполняют: {by['filling']}, заполнили: {by['filled']}, получили превью: {by['previewed']}, "
            f"одобрили: {by['approved']} (ожидается учеников: {c['expected']})\n"
            f"Ссылка: https://t.me/{app.bot_username}?start={code}")
    oid = (c.get("crm") or {}).get("order")
    order = None
    if oid and app.crm:
        try:
            order = app.crm.order(oid)
        except Exception:                               # CRM offline: the card still shows
            order = None
    if order:
        text += "\n" + crmlink.order_line(order)
    buttons = [[("Напомнить незаполнившим", f"act:remind:{code}")],
               [("Разослать превью всем заполнившим", f"act:previews:{code}")],
               [("Таблица xlsx", f"act:xlsx:{code}")]]
    buttons.append([("✏️ Подписи", f"act:fields:{code}")])
    if app.photoshop:
        buttons.append([("Собрать для печати (Photoshop)", f"act:build:{code}")])
    if oid and app.crm:
        buttons.append([("🔄 Обновить CRM", f"act:crmsync:{code}")])
    buttons.append([("Закрыть класс" if c["status"] != "closed" else "Открыть класс", f"act:toggle:{code}")])
    return Out(text, buttons=buttons)


def admin_callback(app, uid, data):
    if data.startswith("cls:"):
        return [class_card(app, data[4:])]
    _, action, code = data.split(":", 2)
    c = app.store.get_class(code)
    if c is None:
        return [Out("Класс не найден.")]
    if action == "toggle":
        app.store.update_class(code, status="collecting" if c["status"] == "closed" else "closed")
        return [class_card(app, code)]
    if action == "fields":
        app.store.set_state(uid, None)
        return [fields_menu(app, code)]
    return [Out("Выполняю…", action=(action, code))]


def is_admin_cmd(app, uid):
    return is_admin(app, uid)
