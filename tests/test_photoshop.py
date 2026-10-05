from autofill.photoshop import js_literal, write_run_script


def test_js_literal_is_ascii():
    s = js_literal({"a": "Имя \x03"})
    assert s.isascii() and "\\u0418" in s and "\\u2028" in s and "\\u0003" in s


def test_run_script(tmp_path):
    (tmp_path / "done").write_text("old")
    run = write_run_script("fill_worker.jsx", {"pages": []}, tmp_path)
    text = run.read_text(encoding="ascii")
    assert not (tmp_path / "done").exists()
    assert "var JOB = {" in text and '"workDir": "' in text
    assert text.index("common.jsx") < text.index("fill_worker.jsx")
