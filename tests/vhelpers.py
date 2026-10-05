"""Synthetic manifest + config for vignette tests."""


def text_slot(path, default, column=None, key=None):
    s = {"path": list(path), "name": default[:20], "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 20},
         "default": default, "font": "Font-Regular", "styleRuns": 1, "textKind": "TextType.POINTTEXT",
         "justification": "Justification.CENTER", "horizontal": True, "limit": 115.0}
    if column:
        s["column"] = column
    if key:
        s["key"] = key
    return s


def photo_slot(path, name="фото"):
    return {"path": list(path), "name": name, "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 150}}


def group(page, records, columns=()):
    return {"sheet": f"Стр {page}", "columns": list(columns), "records": records}


def manifest():
    grid_col = "Подпись: ИМЯ / ФАМИЛИЯ"
    teach_col = "Подпись: ФИО / ПРЕДМЕТ"
    return {"template": "T", "pages": [
        {"page": "cover", "width": 1000, "height": 700,
         "groups": [group("cover", [{"photo": photo_slot([1], "ваше фото"), "texts": []}])],
         "fields": [text_slot([0, 0], "Коновалова", key="pcover_01"),
                    text_slot([0, 1], "2022", key="pcover_02"),
                    text_slot([0, 2], "11 “А” класс", key="pcover_03")]},
        {"page": "01", "width": 1000, "height": 700,
         "groups": [group("01", [{"photo": photo_slot([0, i], f"фото{i + 1}"),
                                  "texts": [text_slot([1, i], "ИМЯ\x03ФАМИЛИЯ", column=grid_col)]}
                                 for i in range(4)], [grid_col])],
         "fields": [text_slot([2], "2022", key="p01_01")]},
        {"page": "02", "width": 1000, "height": 700,
         "groups": [group("02", [{"photo": photo_slot([0, i]), "texts": []} for i in range(3)])],
         "fields": [text_slot([1], "МОИ ДРУЗЬЯ", key="p02_01")]},
        {"page": "03", "width": 1000, "height": 700,
         "groups": [group("03", [{"photo": photo_slot([0, i]),
                                  "texts": [text_slot([1, i], "ИМЯ ФАМИЛИЯ\x03ПРЕДМЕТ", column=teach_col)]}
                                 for i in range(2)], [teach_col])],
         "fields": []},
    ]}


def config():
    return {"template": "T",
            "pages": [
                {"page": "cover", "title": "Обложка", "role": "cover", "required": True, "photos": {"0": "cover"}},
                {"page": "01", "title": "Сетка класса", "role": "students", "required": True,
                 "captions": {"Подпись: ИМЯ / ФАМИЛИЯ": "{Имя}\n{Фамилия}"}},
                {"page": "02", "title": "Мои друзья", "role": "photos", "required": False},
                {"page": "03", "title": "Учителя", "role": "teachers", "required": False},
            ],
            "fields": [
                {"label": "Год", "layers": ["cover:02", "01:01"]},
                {"label": "Класс", "layers": ["cover:03"]},
                {"label": "Фамилия ученика", "layers": ["cover:01"], "value": "{Фамилия}"},
            ],
            "clones": [{"page": "cover", "of": "cover:03", "dx": 0, "dy": 40, "value": "{Имя} {Фамилия}"}]}


def student(name, cover="c", portrait="p", quote=None, group=(), pages=None, row=2):
    surname, first = name.split(" ", 1)
    return {"name": name, "surname": surname, "first": first, "cover": cover, "portrait": portrait,
            "quote": quote, "group": list(group), "pages": pages, "row": row}
