"""Telegram layer (aiogram 3, long polling): messages/buttons -> flows.handle -> delivered Outs.
Slow actions run in a worker thread. Settings: bot.env next to vignette.py (see bot.env.example).

  python -m bot.main
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (BotCommand, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
                           InputMediaPhoto, Message)

from . import crm
from .flows import App, Out, handle
from .runner import run_action
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("vignette-bot")


def load_settings(path=ROOT / "bot.env"):
    values = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    values.update({k: v for k, v in os.environ.items()
                   if k in ("BOT_TOKEN", "ADMIN_IDS", "DATA_DIR", "PHOTOSHOP", "CRM_SHEET_ID", "CRM_KEY_FILE")})
    admins = {int(x) for x in values.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
    photoshop = values.get("PHOTOSHOP", "auto").lower()
    if photoshop == "auto":
        try:
            from autofill.photoshop import find_photoshop
            photoshop = find_photoshop().exists()
        except FileNotFoundError:
            photoshop = False
    else:
        photoshop = photoshop in ("1", "yes", "true", "да")
    key = values.get("CRM_KEY_FILE") or "crm_key.json"            # the CRM's Google key, next to vignette.py
    if key and not Path(key).is_absolute():
        key = str(ROOT / key)
    return {"token": values.get("BOT_TOKEN", ""), "admins": admins,
            "data_dir": Path(values.get("DATA_DIR") or ROOT / "bot_data"), "photoshop": bool(photoshop),
            "crm_sheet": values.get("CRM_SHEET_ID", ""), "crm_key": key,
            "crm_worksheet": values.get("CRM_WORKSHEET", "")}


def keyboard(buttons):
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=data)
                                                  for label, data in row] for row in buttons])


class Delivery:
    def __init__(self, bot, app):
        self.bot, self.app = bot, app

    async def send(self, outs, uid, cb_message=None):
        for out in outs:
            try:
                await self._one(out, uid, cb_message)
            except (TelegramBadRequest, TelegramForbiddenError) as e:   # user blocked the bot / never started it
                log.warning("cannot deliver to %s: %s", out.chat or uid, e.message)
            except Exception:
                log.exception("delivery failed")
            if out.action:
                asyncio.create_task(self._action(out.action, uid))

    async def _one(self, out: Out, uid, cb_message):
        chat = out.chat or uid
        kb = keyboard(out.buttons)
        if out.album:
            items = [InputMediaPhoto(media=FSInputFile(p), caption=c) for p, c in out.album]
            for i in range(0, len(items), 10):
                await self.bot.send_media_group(chat, items[i:i + 10])
        if out.photo:
            if out.edit and cb_message is not None and out.chat is None and cb_message.photo:
                try:
                    await cb_message.edit_media(InputMediaPhoto(media=FSInputFile(out.photo), caption=out.text or None),
                                                reply_markup=kb)
                    return
                except TelegramBadRequest:
                    pass
            await self.bot.send_photo(chat, FSInputFile(out.photo), caption=out.text or None, reply_markup=kb)
        elif out.document:
            await self.bot.send_document(chat, FSInputFile(out.document), caption=out.text or None, reply_markup=kb)
        elif out.text:
            if out.edit and cb_message is not None and out.chat is None:
                try:
                    await cb_message.edit_text(out.text, reply_markup=kb)
                    return
                except TelegramBadRequest:
                    pass
            await self.bot.send_message(chat, out.text, reply_markup=kb)

    async def _action(self, action, uid):
        try:
            outs = await asyncio.to_thread(run_action, self.app, action, uid)
        except Exception as e:
            log.exception("action %s failed", action)
            outs = [Out(f"Ошибка при «{action[0]}»: {e}", chat=a) for a in self.app.admins]
            if uid not in self.app.admins:
                outs.append(Out("Что-то пошло не так, студия уже знает. Попробуйте позже.", chat=uid))
        await self.send(outs, uid)


def build_dispatcher(bot, app):
    dp = Dispatcher()
    delivery = Delivery(bot, app)

    @dp.message(F.text)
    async def on_text(message: Message):
        uid, text = message.from_user.id, message.text
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            outs = await asyncio.to_thread(handle, app, uid, start=parts[1].strip() if len(parts) > 1 else "")
        else:
            outs = await asyncio.to_thread(handle, app, uid, text=text)
        await delivery.send(outs, uid)

    @dp.message()
    async def on_other(message: Message):
        await message.answer("Пришлите номер кадра текстом (номер видно на сайте под фото).")

    @dp.callback_query()
    async def on_button(query: CallbackQuery):
        await query.answer()
        outs = await asyncio.to_thread(handle, app, query.from_user.id, data=query.data)
        await delivery.send(outs, query.from_user.id, cb_message=query.message)

    return dp


CRM_EVERY = 120


async def crm_loop(app, delivery):
    """Every couple of minutes: vignette progress and stages into the CRM, new ready orders to the admins."""
    while True:
        try:
            outs = await asyncio.to_thread(crm.sync, app)
            if outs:
                await delivery.send(outs, next(iter(app.admins)))
        except Exception:
            log.exception("CRM sync failed")
        await asyncio.sleep(CRM_EVERY)


async def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = load_settings()
    if not s["token"] or not s["admins"]:
        print("Заполните bot.env: BOT_TOKEN (от @BotFather) и ADMIN_IDS (ваш Telegram id). См. bot.env.example")
        return 1
    s["data_dir"].mkdir(parents=True, exist_ok=True)
    bot = Bot(s["token"])
    me = await bot.get_me()
    app = App(store=Store(s["data_dir"] / "bot.sqlite"), admins=s["admins"], data_dir=s["data_dir"],
              bot_username=me.username, photoshop=s["photoshop"], crm=crm.connect(s))
    await bot.set_my_commands([BotCommand(command="menu", description="Мои данные и превью"),
                               BotCommand(command="new", description="Новый класс (студия)"),
                               BotCommand(command="classes", description="Классы (студия)")])
    log.info("bot @%s started, admins %s, photoshop %s, CRM %s", me.username, s["admins"], s["photoshop"],
             "on" if app.crm else "off")
    dp = build_dispatcher(bot, app)
    if app.crm:
        asyncio.create_task(crm_loop(app, Delivery(bot, app)))
    await dp.start_polling(bot)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
