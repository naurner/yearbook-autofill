def leaf(name, kind, box, parents=(), text=None, path=None, **extra):
    left, top, right, bottom = box
    d = {"name": name, "kind": kind,
         "bounds": {"left": left, "top": top, "right": right, "bottom": bottom},
         "parents": list(parents), "path": list(path or [0]), "effectiveVisible": True}
    if kind == "text":
        d.update({"text": name if text is None else text, "font": "Font-Regular", "styleRuns": 1,
                  "textKind": "TextType.POINTTEXT", "justification": "Justification.CENTER"})
    d.update(extra)
    return d


def box(left, top, right, bottom):
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def grid_layout():
    """2x2 photo grid on the left half with 'Имя Фамилия' captions, one field on the right."""
    leaves = []
    for i, (x, y) in enumerate([(0, 0), (200, 0), (0, 300), (200, 300)]):
        leaves.append(leaf(f"фото{i + 1}", "shape", (x, y, x + 150, y + 200), parents=["фото"], path=[0, i]))
        leaves.append(leaf(f"имя {i + 1}", "text", (x + 20, y + 210, x + 130, y + 230), parents=["имена"],
                           text="Имя Фамилия", path=[1, i]))
    leaves.append(leaf("класс", "text", (600, 500, 800, 540), text="11 “А”", path=[2]))
    leaves.append(leaf("bg", "pixel", (0, 0, 1000, 700), path=[3]))
    return {"width": 1000, "height": 700, "leaves": leaves}
