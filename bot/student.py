"""Student side: name -> extra pages (repeatable) -> cover photo (+ framing) -> grid photo (+ framing)
-> quote -> group photos page by page (numbered places) -> summary -> preview right away -> approve."""
from collections import Counter

from vignette.config import manifest_page, records

from .classdata import READY
from .core import (BACK, Out, group_instances, group_slot_bounds, known_pages, optional_pages, page_preview,
                   pick_frames, with_back)
from .cropview import ADJUST_BUTTONS, DEFAULT, adjust, crop_picture
from .photos import NumbersError, parse_numbers, thumbnail

MAX_QUOTE = 300
STEPS = ("name", "pages", "cover", "grid", "quote", "group")
EDIT_LABELS = {"name": "Имя", "pages": "Страницы", "cover": "Фото обложки", "grid": "Фото сетки",
               "quote": "Цитата", "group": "Групповые фото", "croplist": "✂️ Кадрирование фото"}
GRID_NOTE = "Страница с сеткой класса будет меняться, пока одноклассники заполняют данные."


# ---------- helpers ----------

def _cls(app, st):
    return app.store.get_class(st["class_code"])


def pages_skipped(app, c):
    cfg, _ = app.template(c["template"])
    return c["tariff"] == 0 or not optional_pages(cfg)


def chosen_count(pages):
    return Counter(pages or [])


def pages_text(cfg, pages):
    titles = {p["page"]: p["title"] for p in cfg["pages"]}
    cnt = chosen_count(known_pages(cfg, pages))
    return ", ".join(titles[p] + (f" ×{n}" if n > 1 else "") for p, n in cnt.items()) or "только обязательные"


def pages_buttons(cfg, pages):
    cnt = chosen_count(pages)
    rows = [[("➖", f"pg-:{p['page']}"), (f"{p['title']}: {cnt.get(p['page'], 0)}", "noop"),
             ("➕", f"pg+:{p['page']}")] for p in optional_pages(cfg)]
    return rows + [[("Готово", "pg:done")]]


def total_places(app, c, pages):
    inst = group_instances(app, c["template"], pages)
    return sum(i["places"] for i in inst)


def aligned_group(grp, total):
    grp = list(grp or [])[:total]
    return grp + [None] * (total - len(grp))


def crop_slot(app, c, st, target):
    """Manifest bounds of the slot a photo goes to (cover / portrait / g<i>)."""
    cfg, man = app.template(c["template"])
    if target in ("cover", "portrait"):
        for p in cfg["pages"]:
            recs = records(manifest_page(man, p["page"]))
            for idx, src in p.get("photos", {}).items():
                if src == target:
                    return recs[int(idx)]["photo"]["bounds"]
            if target == "portrait" and p.get("role") == "students":
                explicit = {int(k) for k in p.get("photos", {})}
                for i, r in enumerate(recs):
                    if i not in explicit and r["photo"] is not None:
                        return r["photo"]["bounds"]
        return {"left": 0, "top": 0, "right": 1000, "bottom": 1400}
    k = int(target[1:])
    for inst in group_instances(app, c["template"], st["pages"]):
        if inst["start"] <= k < inst["start"] + inst["places"]:
            return group_slot_bounds(app, c["template"], inst["page"])[k - inst["start"]]
    return {"left": 0, "top": 0, "right": 1400, "bottom": 1000}


def crop_photo(app, c, st, target):
    src = app.source(c)
    if target == "cover":
        return src.find(st["cover"], "portrait")
    if target == "portrait":
        return src.find(st["portrait"], "portrait")
    num = (st["grp"] or [])[int(target[1:])]
    return src.find(num, "common") if num else None


# ---------- navigation ----------

def goto(app, uid, st, step, edit, **extra):
    c = _cls(app, st)
    if step == "pages" and pages_skipped(app, c):
        app.store.update_student(st["id"], pages=[])
        step = "summary" if edit else "cover"
    if step == "group":
        st = app.store.student_by_id(st["id"])
        if not group_instances(app, c["template"], st["pages"]):
            app.store.update_student(st["id"], grp=[])
            step = "summary"
    if step == "summary":
        app.store.set_state(uid, "s:summary", {"sid": st["id"]})
        return [summary_out(app, app.store.student_by_id(st["id"]))]
    state = dict({"sid": st["id"], "edit": edit}, **extra)
    app.store.set_state(uid, "s:" + step, state)
    return prompt(app, uid, app.store.student_by_id(st["id"]), step, state)


def next_after(step, edit):
    if edit:
        return "summary"
    i = STEPS.index(step)
    return STEPS[i + 1] if i + 1 < len(STEPS) else "summary"


def go_back(app, uid, st, step, state):
    c = _cls(app, st)
    if step in ("cover_ok", "grid_ok"):
        return goto(app, uid, st, step[:-3], state.get("edit"))
    if step == "adj":
        return goto(app, uid, st, state.get("back_to", "summary"), state.get("edit"))
    if step == "group" and state.get("inst", 0) > 0:
        return goto(app, uid, st, "group", state.get("edit"), inst=state["inst"] - 1)
    if state.get("edit") or step == "croplist":
        return goto(app, uid, st, "summary", True)
    if step == "summary":
        inst = group_instances(app, c["template"], st["pages"])
        if inst:
            return goto(app, uid, st, "group", False, inst=len(inst) - 1)
        return goto(app, uid, st, "quote", False)
    i = STEPS.index(step)
    if i == 0:
        return prompt(app, uid, st, step, state)
    prev = STEPS[i - 1]
    if prev == "pages" and pages_skipped(app, c):
        prev = "name"
    return goto(app, uid, st, prev, False)


# ---------- prompts ----------

def prompt(app, uid, st, step, state):
    outs = _prompt(app, uid, st, step, state)
    return outs if step in ("name", "cover_ok", "grid_ok") else with_back(outs)


def _prompt(app, uid, st, step, state):
    c = _cls(app, st)
    cfg, _ = app.template(c["template"])
    skip = [[("Пропустить", "skip")]]
    if step == "name":
        return [Out("Напишите фамилию и имя, как они будут в альбоме (например: Абишева Алия):")]
    if step == "pages":
        opt = optional_pages(cfg)
        album = [(page_preview(c["template"], p["page"]), p["title"]) for p in opt][:10]
        req = ", ".join(p["title"] for p in cfg["pages"] if p.get("required"))
        return [Out(album=[a for a in album if a[0]]),
                Out(f"В альбом всегда входят: {req}.\nДобавьте страницы — всего до {c['tariff']}. "
                    "Одну страницу можно взять несколько раз: на каждой копии будут свои фото.",
                    buttons=pages_buttons(cfg, st["pages"] or []))]
    if step == "cover":
        return [Out("Номер кадра для обложки (из папки «портретки» на сайте):")]
    if step == "grid":
        return [Out("Номер кадра для сетки класса:", buttons=[[("Такой же, как на обложке", "same")]])]
    if step in ("cover_ok", "grid_ok"):
        path = app.source(c).find(state["num"], "portrait")
        return [Out(photo=thumbnail(path, app.class_dir(c["code"]) / "cache"),
                    text=f"Кадр {state['num']}. Этот?", buttons=[[("Да", "ok"), ("Другой номер", "again")]])]
    if step == "adj":
        photo = crop_photo(app, c, st, state["target"])
        pic = crop_picture(photo, crop_slot(app, c, st, state["target"]), state["crop"], app.class_dir(c["code"]) / "cache")
        return [Out(photo=pic, text="Так фото встанет в рамку. Подвиньте или приблизите кнопками, затем «Готово».",
                    buttons=ADJUST_BUTTONS)]
    if step == "quote":
        return [Out(f"Ваша цитата или пожелание (до {MAX_QUOTE} символов) — или «Пропустить»:", buttons=skip)]
    if step == "group":
        inst = group_instances(app, c["template"], st["pages"])[state.get("inst", 0)]
        copy = f" (копия {inst['copy'] + 1} из {inst['copies']})" if inst["copies"] > 1 else ""
        cur = aligned_group(st["grp"], total_places(app, c, st["pages"]))[inst["start"]:inst["start"] + inst["places"]]
        now = ", ".join(n or "—" for n in cur) if any(cur) else "не выбраны"
        return [Out(photo=page_preview(c["template"], inst["page"], numbered=True),
                    text=f"«{inst['title']}»{copy}: мест для групповых фото — {inst['places']} (номера на картинке).\n"
                         f"Пришлите номера кадров из «общих» по порядку мест: 1-е место, 2-е… "
                         f"(через запятую, можно диапазон). Сейчас: {now}.\n"
                         "«Пропустить» — фото подберёт студия.", buttons=skip)]
    if step == "croplist":
        rows = [[("Обложка", "crop:cover")], [("Сетка класса", "crop:portrait")]]
        for inst in group_instances(app, c["template"], st["pages"]):
            for place in range(inst["places"]):
                k = inst["start"] + place
                grp = st["grp"] or []
                if k < len(grp) and grp[k]:
                    rows.append([(f"«{inst['title']}» место {place + 1} (кадр {grp[k]})", f"crop:g{k}")])
        return [Out("Какое фото подвинуть или приблизить?", buttons=rows[:40])]
    raise ValueError(step)


def summary_out(app, st):
    c = _cls(app, st)
    cfg, _ = app.template(c["template"])
    status = {"filling": "", "filled": "\n\nДанные приняты.",
              "previewed": "\n\nПревью отправлено — одобрите или измените.",
              "approved": "\n\nВы одобрили превью. Спасибо!"}[st["status"]]
    grp = [n for n in st["grp"] or [] if n]
    text = (f"Проверьте:\nИмя: {st['name']}\nДоп. страницы: {pages_text(cfg, st['pages'])}\n"
            f"Обложка: кадр {st['cover']}\nСетка: кадр {st['portrait']}\nЦитата: {st['quote'] or '—'}\n"
            f"Групповые: {', '.join(grp) or 'подберёт студия'}{status}")
    buttons = [[("Изменить", "edit")]]
    if st["status"] == "filling":
        buttons.insert(0, [("Всё верно", "confirm")])
        buttons.append(BACK)
    return Out(text, buttons=buttons)


# ---------- entry points ----------

def student_join(app, uid, code):
    c = app.store.get_class(code)
    if c is None:
        return [Out("Ссылка устарела или неверна. Попросите новую у фотостудии.")]
    if c["status"] == "closed":
        return [Out("Приём данных для этого класса закрыт. Напишите в фотостудию.")]
    st = app.store.join(code, uid)
    if st["name"]:
        return student_resume(app, uid, st)
    return [Out(f"Здравствуйте! Это бот виньеток класса «{c['title']}».\n"
                "Соберём ваши данные: имя, страницы, фото и цитату. Займёт пару минут.")] + \
        goto(app, uid, st, "name", False)


def student_resume(app, uid, st):
    if st["status"] == "filling":
        step, state = app.store.get_state(uid)
        if step and step.startswith("s:"):
            return [Out("Продолжим.")] + prompt(app, uid, app.store.student_by_id(st["id"]), step[2:], state)
        return goto(app, uid, st, "name", False)
    return [summary_out(app, st)]


def student_step(app, uid, step, state, text, data):
    st = app.store.student_by_id(state["sid"])
    c = _cls(app, st)
    step = step[2:]
    value = (text or "").strip()
    if data == "noop":
        return []
    if data == "edit":
        return [Out("Что изменить?", buttons=[[(v, "e:" + k)] for k, v in EDIT_LABELS.items()] + [BACK])]
    if data and data.startswith("e:"):
        target = data[2:]
        if st["status"] != "filling":           # changed after confirming: confirm again -> new preview
            app.store.update_student(st["id"], status="filling")
            st = app.store.student_by_id(st["id"])
        return goto(app, uid, st, target, True, inst=0) if target == "group" else goto(app, uid, st, target, True)
    if data and data.startswith("crop:"):
        target = data[5:]
        crop = (st["crops"] or {}).get(target) or list(DEFAULT)
        return goto(app, uid, st, "adj", True, target=target, crop=crop, then="croplist", back_to="croplist")
    if data == "approve":
        return approve(app, uid, st)
    if data == "back":
        return go_back(app, uid, st, step, state)
    edit = state.get("edit", False)

    if step == "summary":
        if data == "confirm":
            return confirm(app, uid, st)
        return [summary_out(app, st)]
    if step == "name":
        words = value.split()
        if len(words) < 2 or not all(any(ch.isalpha() for ch in w) for w in words) or len(value) > 60:
            return [Out("Нужны фамилия и имя через пробел, например: Абишева Алия.")]
        app.store.update_student(st["id"], name=" ".join(words))
        return goto(app, uid, st, next_after("name", edit), edit)
    if step == "pages":
        cfg, _ = app.template(c["template"])
        pages = known_pages(cfg, st["pages"])
        if data == "pg:done":
            total = total_places(app, c, pages)
            app.store.update_student(st["id"], pages=pages, grp=aligned_group(st["grp"], total))
            if edit and total:
                return goto(app, uid, st, "group", True, inst=0)
            return goto(app, uid, st, next_after("pages", edit), edit)
        if data and data[:4] in ("pg+:", "pg-:"):
            page = data[4:]
            if data.startswith("pg+:"):
                if len(pages) >= c["tariff"]:
                    return [Out(f"Можно добавить не больше {c['tariff']} страниц. Уберите другую (➖).")]
                pages.append(page)
            elif page in pages:
                pages.remove(page)
            order = [p["page"] for p in cfg["pages"]]
            pages.sort(key=order.index)
            app.store.update_student(st["id"], pages=pages)
            return [Out(f"Добавьте страницы — всего до {c['tariff']} (сейчас {len(pages)}):",
                        buttons=pages_buttons(cfg, pages) + [BACK], edit=True)]
        return prompt(app, uid, st, step, state)
    if step in ("cover", "grid"):
        if step == "grid" and data == "same":
            app.store.update_student(st["id"], portrait=st["cover"])
            return _to_adjust(app, uid, st, "portrait", "grid", edit)
        try:
            nums = parse_numbers(value)
        except NumbersError as e:
            return [Out(f"{e}. Нужен один номер кадра.")]
        if len(nums) != 1:
            return [Out("Нужен один номер кадра.")]
        if not app.source(c).has(nums[0], "portrait"):
            return [Out(f"Кадра {nums[0]} нет в «портретках». Проверьте номер на сайте.")]
        state = dict(state, num=nums[0])
        app.store.set_state(uid, f"s:{step}_ok", state)
        return prompt(app, uid, st, f"{step}_ok", state)
    if step in ("cover_ok", "grid_ok"):
        base = step[:-3]
        if data == "again":
            app.store.set_state(uid, "s:" + base, state)
            return prompt(app, uid, st, base, state)
        if data != "ok":
            return prompt(app, uid, st, step, state)
        field = "cover" if base == "cover" else "portrait"
        app.store.update_student(st["id"], **{field: state["num"]})
        crops = dict(st["crops"] or {})
        crops.pop(field, None)                    # a new frame starts with default framing
        app.store.update_student(st["id"], crops=crops)
        return _to_adjust(app, uid, app.store.student_by_id(st["id"]), field, base, edit)
    if step == "adj":
        if data == "adj:done":
            crops = dict(st["crops"] or {})
            crops[state["target"]] = state["crop"]
            app.store.update_student(st["id"], crops=crops)
            then = state.get("then", "summary")
            if then == "croplist":
                return goto(app, uid, st, "croplist", True)
            return goto(app, uid, st, then, state.get("edit"))
        if data and data.startswith("adj:"):
            state = dict(state, crop=adjust(state["crop"], data[4:]))
            app.store.set_state(uid, "s:adj", state)
            outs = prompt(app, uid, st, "adj", state)
            for o in outs:
                o.edit = True
            return outs
        return prompt(app, uid, st, step, state)
    if step == "quote":
        if data != "skip":
            if not value:
                return prompt(app, uid, st, step, state)
            if len(value) > MAX_QUOTE:
                return [Out(f"Слишком длинно: {len(value)} символов, можно до {MAX_QUOTE}.")]
        app.store.update_student(st["id"], quote=None if data == "skip" else value)
        return goto(app, uid, st, next_after("quote", edit), edit, **({"inst": 0} if not edit else {}))
    if step == "group":
        instances = group_instances(app, c["template"], st["pages"])
        k = state.get("inst", 0)
        inst = instances[k]
        grp = aligned_group(st["grp"], total_places(app, c, st["pages"]))
        out = []
        if data == "skip":
            nums = []
        else:
            nums, err = pick_frames(app.source(c), value, "common")
            if err:
                return [Out(err)]
            if len(nums) > inst["places"]:
                out.append(Out(f"Мест {inst['places']}, номеров {len(nums)} — лишние не войдут."))
                nums = nums[:inst["places"]]
        grp[inst["start"]:inst["start"] + inst["places"]] = nums + [None] * (inst["places"] - len(nums))
        crops = {key: v for key, v in (st["crops"] or {}).items()
                 if not (key.startswith("g") and inst["start"] <= int(key[1:]) < inst["start"] + inst["places"])}
        app.store.update_student(st["id"], grp=grp, crops=crops)
        if k + 1 < len(instances):
            return out + goto(app, uid, st, "group", edit, inst=k + 1)
        return out + goto(app, uid, st, "summary", edit)
    return prompt(app, uid, st, step, state)


def _to_adjust(app, uid, st, target, base, edit):
    """After choosing a frame: let the student frame it, then continue with the next step."""
    crop = (st["crops"] or {}).get(target) or list(DEFAULT)
    return goto(app, uid, st, "adj", edit, target=target, crop=crop, then=next_after(base, edit), back_to=base)


def _missing_data(st):
    need = {"name": "имя", "cover": "фото обложки", "portrait": "фото сетки"}
    return [v for k, v in need.items() if not st[k]]


def confirm(app, uid, st):
    missing = _missing_data(st)
    if missing:
        return [Out("Не хватает: " + ", ".join(missing) + ".", buttons=[[("Изменить", "edit")]])]
    c = _cls(app, st)
    app.store.update_student(st["id"], status="filled")
    app.store.set_state(uid, "s:summary", {"sid": st["id"]})
    ready = len(app.store.students(c["code"], READY))
    if c["status"] == "collecting" and ready >= c["expected"]:
        return [Out("Спасибо! Класс заполнен — собираю превью…", action=("previews", c["code"]))] + \
            [Out(f"Класс «{c['title']}» заполнен ({ready}). Рассылаю превью всем.", chat=a) for a in app.admins]
    return [Out(f"Спасибо! Собираю ваше превью…\n{GRID_NOTE}", action=("preview_one", c["code"], st["id"]))]


def approve(app, uid, st):
    if st["status"] != "previewed":
        return [summary_out(app, st)]
    app.store.update_student(st["id"], status="approved")
    c = _cls(app, st)
    out = [Out("Спасибо! Превью одобрено. Если что-то нужно поменять — /menu.")]
    sts = app.store.students(c["code"], READY)
    if len(sts) >= c["expected"] and all(s["status"] == "approved" for s in sts):
        buttons = [[("Таблица xlsx", f"act:xlsx:{c['code']}")]]
        if app.photoshop:
            buttons.append([("Собрать для печати", f"act:build:{c['code']}")])
        out += [Out(f"Все ученики «{c['title']}» одобрили превью.", buttons=buttons, chat=a) for a in app.admins]
    return out
