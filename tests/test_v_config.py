import json
from pathlib import Path

import pytest

from vhelpers import config, manifest
from vignette.config import (ConfigError, class_photo_labels, draft_config, field_slots, load_config,
                             resolve_layer)

ROOT = Path(__file__).resolve().parents[1]


def test_resolve_layer_field_key():
    page, slot = resolve_layer(manifest(), "cover:02")
    assert page == "cover" and slot["default"] == "2022"


def test_load_config_ok():
    cfg = load_config(config(), manifest())
    assert [p["page"] for p in cfg["pages"]] == ["cover", "01", "02", "03"]


@pytest.mark.parametrize("mutate, msg", [
    (lambda c: c["pages"][2].update(role="bogus"), "роль"),
    (lambda c: c["pages"].append({"page": "99", "title": "x", "role": "photos"}), "99"),
    (lambda c: c["fields"][0]["layers"].append("01:77"), "01:77"),
    (lambda c: c["clones"][0].update({"of": "cover:55"}), "cover:55"),
    (lambda c: c["pages"][0]["photos"].update({"0": "selfie"}), "selfie"),
    (lambda c: c["pages"][2].update(title="Ура, мы"), "запят"),
])
def test_load_config_errors(mutate, msg):
    c = config()
    mutate(c)
    with pytest.raises(ConfigError, match=msg):
        load_config(c, manifest())


def test_field_slots_and_personal():
    fs = field_slots(load_config(config(), manifest()), manifest())
    year = next(f for f in fs if f["label"] == "Год")
    assert [(p, s["default"]) for p, s, _ in year["layers"]] == [("cover", "2022"), ("01", "2022")]
    assert next(f for f in fs if f["label"] == "Фамилия ученика")["personal"]
    assert not year["personal"]


def test_class_photo_labels():
    c = config()
    c["pages"][0]["photos"]["0"] = "class:Фото классного руководителя"
    assert class_photo_labels(load_config(c, manifest())) == ["Фото классного руководителя"]


def test_draft_config_merges_identical_texts():
    d = draft_config(manifest())
    year = [f for f in d["fields"] if f["label"] == "2022"]
    assert len(year) == 1 and year[0]["layers"] == ["cover:02", "01:01"]
    assert d["pages"][0]["role"] == "cover"
    load_config(d, manifest())


@pytest.mark.parametrize("tpl", ["Freedom_21x30", "Flight", "Split"])
def test_real_configs_load(tpl):
    path = ROOT / "configs" / f"{tpl}.json"
    if not path.exists():
        pytest.skip("config not authored yet")
    man = json.loads((ROOT / "manifests" / f"{tpl}.json").read_text(encoding="utf-8"))
    load_config(json.loads(path.read_text(encoding="utf-8")), man)


def test_layer_format():
    from vignette.config import apply_format, split_layer
    assert split_layer("cover:02|“{last2}") == ("cover:02", "“{last2}")
    assert split_layer("cover:02") == ("cover:02", "{v}")
    assert apply_format("{first2}\n", "2025") == "20\n"
    assert apply_format("ВЫПУСК {v} года", "2025") == "ВЫПУСК 2025 года"
    c = config()
    c["fields"][0]["layers"] = ["cover:02|{last2}", "01:01"]
    fs = field_slots(load_config(c, manifest()), manifest())
    assert [fmt for _, _, fmt in fs[0]["layers"]] == ["{last2}", "{v}"]
