from fill_album import format_warning


def test_format_warning():
    assert format_warning({"kind": "shrink", "layer": "имя 1", "value": 0.8}) == \
        "«имя 1»: текст не помещался — уменьшен до 80%"
    assert format_warning({"kind": "styles_lost", "layer": "t", "value": "err"}).startswith("«t»: стиль строк")
