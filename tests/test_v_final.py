import fitz

from vhelpers import manifest
from vignette.final import fill_to_job_page, unique_fills
from vignette.pdfmerge import images_to_pdf, merge_pdfs


def fill(**kw):
    base = {"page": "cover", "copy": 0, "texts": {"0.1": "2025"}, "photos": {"1": "D:/c1.jpg"},
            "clones": [{"of": "0.2", "dx": 0, "dy": 40, "value": "Алия Абишева"}]}
    base.update(kw)
    return base


def test_fill_to_job_page(tmp_path):
    jp = fill_to_job_page(fill(), manifest(), tmp_path / "psd", tmp_path / "out" / "k1")
    assert jp["page"] == "cover" and jp["psd"].endswith("psd/cover.psd") and jp["out"].endswith("out/k1")
    assert jp["texts"] == [{"path": [0, 1], "name": "2022", "styleRuns": 1, "textKind": "TextType.POINTTEXT",
                            "justification": "Justification.CENTER", "horizontal": True, "limit": 115.0,
                            "value": "2025"}]
    assert jp["photos"] == [{"path": [1], "name": "ваше фото", "hidden": False, "file": "D:/c1.jpg", "crop": None}]
    clone = jp["clones"][0]
    assert clone["path"] == [0, 2] and clone["dx"] == 0 and clone["dy"] == 40 and clone["value"] == "Алия Абишева"


def test_unique_fills_dedupes():
    plans = [{"name": "a", "pages": [fill(), fill(page="01", clones=[])]},
             {"name": "b", "pages": [fill(), fill(page="01", clones=[], texts={"2": "x"})]}]
    keys = unique_fills(plans)
    assert len(keys) == 3


def one_page_pdf(path, text):
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), text)
    doc.save(path)
    return path


def test_merge_pdfs(tmp_path):
    out = merge_pdfs([one_page_pdf(tmp_path / "a.pdf", "a"), one_page_pdf(tmp_path / "b.pdf", "b")],
                     tmp_path / "x" / "Ученик.pdf")
    with fitz.open(out) as d:
        assert d.page_count == 2


def test_images_to_pdf(tmp_path):
    from PIL import Image
    Image.new("RGB", (300, 150), "red").save(tmp_path / "p.jpg")
    out = images_to_pdf([tmp_path / "p.jpg"], tmp_path / "o.pdf", dpi=150)
    with fitz.open(out) as d:
        assert round(d[0].rect.width) == 144 and round(d[0].rect.height) == 72


def test_cached_ignores_empty_files(tmp_path):
    from vignette.final import cached
    (tmp_path / "a.pdf").write_bytes(b"")
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    assert not cached(tmp_path, "a") and cached(tmp_path, "b") and not cached(tmp_path, "c")


def test_hidden_layers_in_job(tmp_path):
    jp = fill_to_job_page(fill(hide=["0.1"]), manifest(), tmp_path, tmp_path / "k")
    assert jp["hide"] == [{"path": [0, 1], "name": "2022"}]


def test_crop_in_job(tmp_path):
    jp = fill_to_job_page(fill(crops={"1": [1.5, 0.2, 0.8]}), manifest(), tmp_path, tmp_path / "k")
    assert jp["photos"][0]["crop"] == [1.5, 0.2, 0.8]
    jp = fill_to_job_page(fill(), manifest(), tmp_path, tmp_path / "k")
    assert jp["photos"][0]["crop"] is None


def test_pages_exported_as_numbered_jpegs(tmp_path):
    from PIL import Image
    from vignette.final import page_names
    from vignette.pdfmerge import export_jpgs
    photo = tmp_path / "spread.jpg"
    Image.new("RGB", (880, 634), (200, 30, 30)).save(photo, quality=90)
    image_pdf = images_to_pdf([photo], tmp_path / "p1.pdf", 300)          # like Photoshop's page PDFs
    text_pdf = one_page_pdf(tmp_path / "p2.pdf", "b")
    plan = {"file": "Абишева Алия.pdf", "pages": [{"page": "cover"}, {"page": "01"}, {"page": "zz"}]}
    names = page_names(plan, {"cover": "Обложка", "01": "Сетка класса"})
    assert names == ["01 - обложка", "02 - сетка класса", "03 - zz"]
    folder = tmp_path / "out"
    (folder).mkdir()
    (folder / "9 - старая.jpg").write_bytes(b"x")                          # an earlier build's page goes
    (folder / "заметки.jpg").write_bytes(b"x")                              # other files stay
    export_jpgs([image_pdf, text_pdf], folder, names[:2])
    assert sorted(p.name for p in folder.iterdir()) == ["01 - обложка.jpg", "02 - сетка класса.jpg", "заметки.jpg"]
    with Image.open(folder / "01 - обложка.jpg") as im:
        assert im.size == (880, 634) and round(im.info["dpi"][0]) == 300
    assert (folder / "01 - обложка.jpg").read_bytes()[-2000:] == photo.read_bytes()[-2000:]   # not re-compressed
    with Image.open(folder / "02 - сетка класса.jpg") as im:
        assert round(im.info["dpi"][0]) == 300
