from bot.main import keyboard, load_settings


def test_keyboard():
    kb = keyboard([[("Да", "ok"), ("Нет", "again")], [("Готово", "pg:done")]])
    assert [[b.callback_data for b in row] for row in kb.inline_keyboard] == [["ok", "again"], ["pg:done"]]
    assert keyboard(None) is None


def test_load_settings(tmp_path, monkeypatch):
    for k in ("BOT_TOKEN", "ADMIN_IDS", "DATA_DIR", "PHOTOSHOP"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / "bot.env"
    env.write_text("# c\nBOT_TOKEN=123:abc\nADMIN_IDS=1, 2\nDATA_DIR=\nPHOTOSHOP=no\n", encoding="utf-8")
    s = load_settings(env)
    assert s["token"] == "123:abc" and s["admins"] == {1, 2} and s["photoshop"] is False
    assert s["data_dir"].name == "bot_data"


def test_delivery_sends_and_runs_actions(tmp_path, monkeypatch):
    import asyncio
    from PIL import Image
    import bot.main as main
    from bot.flows import Out

    img = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(img)
    calls = []

    class FakeBot:
        async def send_message(self, chat, text, reply_markup=None):
            calls.append(("text", chat, text))

        async def send_photo(self, chat, photo, caption=None, reply_markup=None):
            calls.append(("photo", chat, caption))

        async def send_document(self, chat, doc, caption=None, reply_markup=None):
            calls.append(("doc", chat, caption))

        async def send_media_group(self, chat, items):
            calls.append(("album", chat, len(items)))

    monkeypatch.setattr(main, "run_action", lambda app, action, uid: [Out("готово", chat=uid)])

    async def go():
        d = main.Delivery(FakeBot(), app=type("A", (), {"admins": {1}})())
        await d.send([Out(album=[(str(img), "c")] * 12), Out("hi", photo=str(img)), Out("f", document=str(img)),
                      Out("run", action=("xlsx", "c"))], 7)
        await asyncio.sleep(0.2)

    asyncio.run(go())
    assert calls == [("album", 7, 10), ("album", 7, 2), ("photo", 7, "hi"), ("doc", 7, "f"), ("text", 7, "run"),
                     ("text", 7, "готово")]
