from vignette.names import fill_tokens, has_tokens, safe_file_name, split_name


def test_split_name_surname_first():
    assert split_name("Абишева Алия") == ("Абишева", "Алия")
    assert split_name("  Муканбетова   Талантгул Төлөновна ") == ("Муканбетова", "Талантгул Төлөновна")
    assert split_name("Ева") == ("Ева", "")


def test_fill_tokens():
    st = {"name": "Абишева Алия", "surname": "Абишева", "first": "Алия", "quote": "Вперёд"}
    assert fill_tokens("{Имя}\x03{Фамилия}", st) == "Алия\x03Абишева"
    assert fill_tokens("{ФИО} — {Цитата}", st) == "Абишева Алия — Вперёд"
    assert fill_tokens("{Цитата}", {"name": "А Б", "surname": "А", "first": "Б", "quote": None}) == ""


def test_has_tokens():
    assert has_tokens("{Имя}")
    assert not has_tokens("11 “А” класс")


def test_safe_file_name():
    assert safe_file_name('А/Б:В*?"<>|  Г.') == "АБВ Г"


def test_upper_tokens():
    st = {"name": "Абишева Алия", "surname": "Абишева", "first": "Алия", "quote": None}
    assert fill_tokens("{^Имя} {Фамилия}", st) == "АЛИЯ Абишева"
    assert has_tokens("{^ФИО}")
