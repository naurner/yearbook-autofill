from autofill.fonts import manifest_fonts, missing_fonts
from autofill.manifest import build_manifest
from helpers import grid_layout


def test_missing_fonts_reports_pages():
    m = build_manifest("T", [("01", grid_layout()), ("02", grid_layout())])
    assert manifest_fonts(m) == {"Font-Regular": ["01", "02"]}
    assert missing_fonts(m, installed={"Other"}) == {"Font-Regular": ["01", "02"]}
    assert missing_fonts(m, installed={"Font-Regular"}) == {}
