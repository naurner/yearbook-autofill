"""Bot dialogs without Telegram: handle(app, user, text/data/start) -> [Out].

Dialog position lives in the store (state step + data), so a restart continues where the user was.
Admin wizard "a:new" (bot/admin.py), student steps "s:<step>" (bot/student.py). Slow side effects
(previews, print build, workbook export, reminders) are requested with Out.action and run by runner.py."""
from .admin import admin_callback, admin_classes, admin_help, admin_new, admin_wizard, field_pick
from .core import App, Out, is_admin
from .student import student_join, student_resume, student_step

__all__ = ["App", "Out", "handle"]


def handle(app, uid, text=None, data=None, start=None):
    try:
        return _handle(app, uid, text, data, start)
    except OSError as e:                     # photo source (gallery/site/folder) unreachable or rate-limited
        admins = [Out(f"Источник фото недоступен: {e}", chat=a) for a in app.admins if a != uid]
        return [Out("Фото сейчас недоступны (галерея не отвечает). Попробуйте ещё раз через минуту.")] + admins


def _handle(app, uid, text, data, start):
    store = app.store
    if start is not None:
        if start:
            return student_join(app, uid, start)
        if is_admin(app, uid):
            return [admin_help()]
        st = store.latest_student(uid)
        if st:
            return student_resume(app, uid, st)
        return [Out("Здравствуйте! Откройте ссылку-приглашение вашего класса от фотостудии.")]
    if text and text.startswith("/"):
        cmd = text.split()[0].lower()
        if is_admin(app, uid):
            if cmd == "/new":
                return admin_new(app, uid)
            if cmd == "/classes":
                return admin_classes(app)
            if cmd in ("/help", "/start"):
                return [admin_help()]
        st = store.latest_student(uid)
        if st and cmd in ("/menu", "/start", "/edit"):
            return student_resume(app, uid, st)
        return [Out("Команда не найдена. Откройте ссылку-приглашение класса.")]
    if data and data.startswith(("cls:", "act:")) and is_admin(app, uid):
        return admin_callback(app, uid, data)
    if data and data.startswith("fld:") and data.count(":") == 2 and is_admin(app, uid):
        return field_pick(app, uid, data)
    if data and data.startswith("crmnew:") and is_admin(app, uid):
        return admin_new(app, uid, order_id=data[7:])
    step, state = store.get_state(uid)
    if step and step.startswith("a:"):
        return admin_wizard(app, uid, step, state, text, data)
    if step and step.startswith("s:"):
        return student_step(app, uid, step, state, text, data)
    if is_admin(app, uid):
        return [admin_help()]
    return [Out("Откройте ссылку-приглашение вашего класса от фотостудии.")]
