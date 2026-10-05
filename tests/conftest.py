"""Тесты, которым нужны дизайн-материалы студии.

Шаблоны альбомов, их шрифты, разобранные из PSD данные (configs/, layouts/,
manifests/, compiled/, templates/) и брендинг (assets/) в публичный репозиторий
не входят — здесь только код. Без этих папок зависящие от них тесты пропускаются.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HAS_DESIGN = all((ROOT / d).is_dir() for d in ("compiled", "configs", "layouts", "manifests", "assets"))

# модуль читает шаблон прямо при импорте — без данных его нельзя даже собрать
collect_ignore = [] if HAS_DESIGN else ["test_v_compile.py"]

NEEDS_DESIGN_FILES = {"test_bot_flows.py", "test_bot_runner.py", "test_v_preview.py"}
NEEDS_DESIGN_TESTS = {
    "test_to_classdata_plans_without_errors",
    "test_class_xlsx_roundtrip",
    "test_wizard_starts_from_a_crm_order",
    "test_logo_drawn_centered",
}


def pytest_collection_modifyitems(config, items):
    if HAS_DESIGN:
        return
    skip = pytest.mark.skip(reason="нужны дизайн-материалы студии (в публичный репозиторий не входят)")
    for item in items:
        if Path(str(item.fspath)).name in NEEDS_DESIGN_FILES or item.originalname in NEEDS_DESIGN_TESTS:
            item.add_marker(skip)
