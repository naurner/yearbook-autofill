"""Slow bot actions (run in a worker thread by main.py): previews, workbook, print build, reminders.
Each returns [Out] to deliver."""
from pathlib import Path

from vignette.compile import COMPILED
from vignette.names import safe_file_name
from vignette.plan import build_plans
from vignette.preview import student_preview

from .classdata import READY, to_classdata, write_class_xlsx
from .core import Out
from .student import GRID_NOTE

APPROVE_BUTTONS = [[("✅ Одобрить", "approve"), ("✏️ Изменить", "edit")]]


def _photos_dir(app, cls):
    src = cls["source"]
    return src["path"] if src["kind"] == "folder" else app.class_dir(cls["code"]) / "cache"


def grid_size(cls, students, final=False):
    """People the class grids are laid out for: everyone who filled in once the class is complete (or for
    print), else the expected class size (empty places until the rest fill in)."""
    ready = len(students)
    return ready if final or ready >= cls["expected"] else max(ready, cls["expected"])


def ensure_grids(app, cls, people):
    """Grid variants for that many people, made in Photoshop when missing (minutes, once per size)."""
    from vignette import gridvariants
    cfg, man = app.template(cls["template"])
    wants = gridvariants.needed(cfg, man, people)
    if not app.photoshop or not wants:
        return []
    made = gridvariants.ensure(cls["template"], cfg, wants, on_progress=lambda s: None)
    if made:
        app._templates.pop(cls["template"], None)              # reload the manifest with the new pages
    return made


def _plans(app, cls, final=False):
    students = app.store.students(cls["code"], READY)
    size = grid_size(cls, students, final)
    ensure_grids(app, cls, size)
    cfg, man = app.template(cls["template"])
    data = to_classdata(cls, students, app.source(cls), size)
    plans, errors, warnings = build_plans(cfg, man, data, _photos_dir(app, cls))
    by_sid = {p_st["sid"]: plan for p_st, plan in zip(data["students"], plans)}
    return students, by_sid, errors, warnings


def previews(app, code, uid=None, only=None):
    """Preview PDFs for all ready students (or only sid `only`); the class grid includes everyone ready."""
    cls = app.store.get_class(code)
    students, plans, errors, warnings = _plans(app, cls)
    admins = [Out(f"«{cls['title']}»: {w}", chat=a) for w in warnings for a in app.admins]
    if errors:
        return admins + [Out(f"«{cls['title']}»: превью не собраны:\n" + "\n".join(errors[:15]), chat=a)
                         for a in app.admins]
    complete = len(students) >= cls["expected"]
    if only is None:
        app.store.update_class(code, status="preview")
    root = COMPILED / cls["template"]
    cache = app.class_dir(code) / "preview_cache"
    out_dir = app.class_dir(code) / "previews"
    outs = []
    for st in students:
        if only is not None and st["id"] != only:
            continue
        pdf = student_preview(plans[st["id"]], root, cache, out_dir, watermark=True)
        app.store.update_student(st["id"], status="previewed", preview=str(pdf))
        note = "Класс заполнен — сетка класса окончательная." if complete else GRID_NOTE
        outs.append(Out(text="Ваше превью виньетки (водяной знак не будет напечатан). Проверьте имя, фото и "
                             f"страницы, затем одобрите или измените.\n{note}",
                        document=str(pdf), chat=st["user_id"], buttons=APPROVE_BUTTONS))
    if only is None:
        outs += [Out(f"«{cls['title']}»: превью разосланы ({len(outs)}).", chat=a) for a in app.admins]
    return admins + outs


def xlsx(app, code, uid):
    cls = app.store.get_class(code)
    cfg, man = app.template(cls["template"])
    path = app.class_dir(code) / f"{safe_file_name(cls['title'])}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_class_xlsx(cfg, man, cls, app.store.students(code, READY), path)
    return [Out(text="Таблица класса: для печати — python vignette.py build --template "
                     f"{cls['template']} --excel <таблица> --photos <папка фото класса> --out <папка>",
                document=str(path), chat=uid)]


def build(app, code, uid, out_root=None):
    from vignette.final import build as final_build
    from autofill.templates import TEMPLATES
    cls = app.store.get_class(code)
    students, plans, errors, _ = _plans(app, cls, final=True)
    if errors:
        return [Out("Не собрано:\n" + "\n".join(errors[:15]), chat=uid)]
    out_root = Path(out_root or app.class_dir(code) / "print")
    cfg, man = app.template(cls["template"])
    report = final_build(list(plans.values()), cls["title"], man, TEMPLATES[cls["template"]]["psd_dir"], out_root,
                         on_progress=lambda s: None, titles={p["page"]: p["title"] for p in cfg["pages"]})
    failed = [n for n, p, _ in report["students"] if p is None]
    outs = []
    if not failed and (cls.get("crm") or {}).get("order"):
        from . import crm
        app.store.update_class(code, crm=dict(cls["crm"], built=True))
        try:
            outs = crm.sync(app, only=code)
        except Exception as e:                          # CRM offline: the loop retries later
            outs = [Out(f"CRM пока не обновлена: {e}", chat=uid)]
    text = f"Печать «{cls['title']}»: готово {len(report['students']) - len(failed)} из {len(report['students'])}.\n" \
           f"Папка: {report['class_dir']}\nУ каждого ученика своя папка: страницы JPG 300 dpi " \
           "«01 - обложка», «02 - …» по порядку альбома."
    if failed:
        text += "\nНе собраны: " + ", ".join(failed)
    return [Out(text, chat=uid)] + outs


def grids(app, code, uid):
    """Right after a class is made: its grids for the expected class size, so previews need not wait."""
    cls = app.store.get_class(code)
    made = ensure_grids(app, cls, cls["expected"])
    if not made:
        return []
    return [Out(f"Сетки «{cls['title']}» под {cls['expected']} учеников готовы.", chat=uid)]


def crm_sync(app, code, uid):
    from . import crm
    if app.crm is None:
        return [Out("Связь с CRM не настроена (bot.env: CRM_SHEET_ID, CRM_KEY_FILE).", chat=uid)]
    outs = crm.sync(app, only=code)
    return outs or [Out("CRM: всё уже актуально.", chat=uid)]


def remind(app, code, uid):
    cls = app.store.get_class(code)
    waiting = app.store.students(code, {"filling"})
    outs = [Out(f"Напоминание от фотостудии: заполните, пожалуйста, данные для виньетки класса «{cls['title']}». "
                "Нажмите /menu, чтобы продолжить.", chat=st["user_id"]) for st in waiting]
    return outs + [Out(f"Напоминание отправлено: {len(waiting)}.", chat=uid)]


def run_action(app, action, uid):
    kind, code = action[0], action[1]
    if kind == "previews":
        return previews(app, code, uid)
    if kind == "preview_one":
        return previews(app, code, uid, only=action[2])
    if kind == "xlsx":
        return xlsx(app, code, uid)
    if kind == "build":
        return build(app, code, uid)
    if kind == "remind":
        return remind(app, code, uid)
    if kind == "crmsync":
        return crm_sync(app, code, uid)
    if kind == "grids":
        return grids(app, code, uid)
    raise ValueError(kind)
