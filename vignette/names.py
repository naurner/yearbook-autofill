"""Student names and personal tokens ({Имя}, {Фамилия}, {ФИО}, {Цитата})."""
import re

TOKENS = ("Имя", "Фамилия", "ФИО", "Цитата")


def split_name(full):
    """«Фамилия Имя [Отчество]» -> (surname, rest)."""
    parts = full.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


TOKEN_RE = re.compile(r"\{(\^?)(" + "|".join(TOKENS) + r")\}")


def has_tokens(text):
    return bool(TOKEN_RE.search(text or ""))


def fill_tokens(template, student):
    """{Имя} {Фамилия} {ФИО} {Цитата}; {^Имя} etc. give upper case."""
    values = {"ФИО": student["name"], "Фамилия": student["surname"], "Имя": student["first"],
              "Цитата": student.get("quote") or ""}
    return TOKEN_RE.sub(lambda m: values[m.group(2)].upper() if m.group(1) else values[m.group(2)], template)


def safe_file_name(name):
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    return re.sub(r"\s+", " ", name).strip(" .")
