from bot.store import Store


def test_class_roundtrip(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    code = s.create_class(template="Flight", title="11 Б", expected=25, tariff=2, source={"kind": "folder"},
                          fields={"Год выпуска": "2025"}, class_photos={}, common=["1811"], admin_id=1)
    c = s.get_class(code)
    assert c["status"] == "collecting" and c["fields"] == {"Год выпуска": "2025"} and c["common"] == ["1811"]
    s.update_class(code, status="preview", tariff=3)
    assert s.get_class(code)["tariff"] == 3 and [x["code"] for x in s.list_classes()] == [code]


def test_students_and_state_survive_reopen(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    code = s.create_class(template="Flight", title="11 Б", expected=2, tariff=1)
    st = s.join(code, 42)
    assert s.join(code, 42)["id"] == st["id"]                     # joining twice keeps one row
    s.update_student(st["id"], name="Абишева Алия", pages=["03"], grp=["1811", "1812"], status="filled")
    s.set_state(42, "st:quote", {"class": code})
    s2 = Store(tmp_path / "db.sqlite")
    row = s2.student(code, 42)
    assert row["name"] == "Абишева Алия" and row["pages"] == ["03"] and row["grp"] == ["1811", "1812"]
    assert s2.get_state(42) == ("st:quote", {"class": code})
    assert [r["user_id"] for r in s2.students(code, {"filled"})] == [42]
    assert s2.latest_student(42)["class_code"] == code
    assert s2.get_state(7) == (None, {})
