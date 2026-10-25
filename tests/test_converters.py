import json
import zipfile

import pymupdf
import pytest
import yaml
from PIL import Image

from convertall.errors import ConversionError
from convertall.pipeline import convert, extract

from .conftest import needs

# ---- images


@pytest.mark.parametrize("fmt", ["jpg", "webp", "gif", "bmp", "tiff", "ico", "tga", "heic", "avif",
                                 "ppm", "jp2", "qoi", "dds", "icns", "pcx"])
def test_image_formats(png, fmt):
    out = convert(png, fmt)
    assert out.suffix == f".{fmt}"
    with Image.open(out) as img:
        img.load()
        assert img.width > 0


def test_jpg_flattens_alpha_on_white(png):
    with Image.open(convert(png, "jpg")) as img:
        assert img.mode == "RGB"
        r, g, b = img.getpixel((5, 5))
        assert min(r, g, b) > 240


def test_animated_gif_to_webp_keeps_frames(tmp_path):
    frames = [Image.new("RGB", (40, 40), c) for c in ("red", "green", "blue")]
    gif = tmp_path / "anim.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=80, loop=0)
    with Image.open(convert(gif, "webp")) as img:
        assert img.n_frames == 3


def test_image_to_pdf_and_back(png):
    pdf = convert(png, "pdf")
    with pymupdf.open(pdf) as doc:
        assert doc.page_count == 1
    back = convert(pdf, "png")
    assert back.suffix == ".png" and back.is_file()


def test_multipage_pdf_to_images_folder(tmp_path):
    pdf = tmp_path / "doc.pdf"
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"page {i}")
    doc.save(pdf)
    out = convert(pdf, "jpg")
    assert out.is_dir()
    assert sorted(p.name for p in out.iterdir()) == ["page-1.jpg", "page-2.jpg", "page-3.jpg"]


def test_svg_to_png(tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="32">'
                   '<rect width="64" height="32" fill="#f00"/></svg>')
    with Image.open(convert(svg, "png")) as img:
        assert img.size == (1024, 512)  # small vectors are rendered crisp


# ---- text & pdf

def test_markdown_to_pdf_has_text(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("# Hello\n\nConvertAll *works*.\n", encoding="utf-8")
    with pymupdf.open(convert(md, "pdf")) as doc:
        assert "ConvertAll works" in doc[0].get_text()


def test_txt_to_pdf_and_pdf_to_txt(tmp_path):
    txt = tmp_path / "plain.txt"
    txt.write_text("line one\nline two <not a tag>\n", encoding="utf-8")
    pdf = convert(txt, "pdf")
    assert "<not a tag>" in convert(pdf, "txt").read_text(encoding="utf-8")


# ---- data

RECORDS = [{"name": "Ada", "age": 36, "langs": {"main": "math"}}, {"name": "Linus", "age": 28}]


def test_json_yaml_toml_roundtrip(tmp_path):
    src = tmp_path / "people.json"
    src.write_text(json.dumps({"people": RECORDS}), encoding="utf-8")
    y = convert(src, "yaml")
    assert yaml.safe_load(y.read_text(encoding="utf-8"))["people"][0]["name"] == "Ada"
    t = convert(y, "toml")
    back = convert(t, "json", out_dir=tmp_path / "back")
    assert json.loads(back.read_text(encoding="utf-8")) == {"people": RECORDS}


def test_json_to_csv_flattens(tmp_path):
    src = tmp_path / "people.json"
    src.write_text(json.dumps(RECORDS), encoding="utf-8")
    lines = convert(src, "csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "name,age,langs.main"
    assert lines[2] == "Linus,28,"


def test_csv_xlsx_roundtrip(tmp_path):
    src = tmp_path / "t.csv"
    src.write_text("a;b\n1;x\n2;y\n", encoding="utf-8")  # semicolon delimiter is sniffed
    xlsx = convert(src, "xlsx")
    data = json.loads(convert(xlsx, "json").read_text(encoding="utf-8"))
    assert data == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}] or data == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]


def test_xml_and_ini(tmp_path):
    src = tmp_path / "cfg.xml"
    src.write_text('<config version="2"><server host="a" /><server host="b" /><name>x</name></config>')
    data = json.loads(convert(src, "json").read_text(encoding="utf-8"))
    assert data == {"config": {"@version": "2", "server": [{"@host": "a"}, {"@host": "b"}], "name": "x"}}
    ini = tmp_path / "app.ini"
    ini.write_text("[db]\nhost = localhost\nport = 5432\n")
    assert yaml.safe_load(convert(ini, "yaml").read_text())["db"]["port"] == "5432"


# ---- fonts

def _make_ttf(path):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((500, 700))
    pen.lineTo((900, 0))
    pen.closePath()
    fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "A": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (1000, 100)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    fb.save(str(path))


def test_font_roundtrip(tmp_path):
    from fontTools.ttLib import TTFont
    ttf = tmp_path / "t.ttf"
    _make_ttf(ttf)
    woff2 = convert(ttf, "woff2")
    assert TTFont(woff2).flavor == "woff2"
    back = convert(woff2, "ttf", out_dir=tmp_path / "back")
    assert "A" in TTFont(back).getGlyphOrder()


# ---- archives

@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "project"
    (root / "sub").mkdir(parents=True)
    (root / "readme.txt").write_text("hi")
    (root / "sub" / "data.bin").write_bytes(bytes(range(256)) * 50)
    return root


def _same_tree(a, b):
    files = lambda r: {p.relative_to(r).as_posix(): p.read_bytes() for p in r.rglob("*") if p.is_file()}  # noqa: E731
    return files(a) == files(b)


@pytest.mark.parametrize("fmt", ["zip", "7z", "tar", "tar.gz", "tar.bz2", "tar.xz"])
def test_folder_compress_extract_roundtrip(tree, tmp_path, fmt):
    archive = convert(tree, fmt)
    assert archive.name == f"project.{fmt}"
    out = extract(archive, tmp_path / f"out-{fmt}")
    assert out.name == "project"  # single top folder isn't double-nested
    assert _same_tree(tree, out)


@pytest.mark.parametrize("fmt", ["gz", "bz2", "xz", "zip"])
def test_single_file_compress(png, tmp_path, fmt):
    archive = convert(png, fmt)
    if fmt != "zip":
        assert archive.name == f"pic.png.{fmt}"
    out = extract(archive, tmp_path / "x")
    assert out.read_bytes() == png.read_bytes()


def test_repack_zip_to_7z(tree, tmp_path):
    seven = convert(convert(tree, "zip"), "7z")
    assert _same_tree(tree, extract(seven, tmp_path / "x"))


def test_zip_slip_blocked(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escaped.txt", "nope")
        zf.writestr("ok.txt", "fine")
    out = extract(evil, tmp_path / "dest")
    assert not (tmp_path / "escaped.txt").exists()
    assert (out / "ok.txt").exists() or out.name == "ok.txt"


# ---- engines (skipped when not installed)

@needs("ffmpeg")
def test_audio_and_video(tmp_path):
    from convertall import engines
    ff = engines.find("ffmpeg")
    wav, mp4 = tmp_path / "tone.wav", tmp_path / "clip.mp4"
    engines.run([ff, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(wav)])
    engines.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=size=161x91:rate=10:duration=1",
                 "-f", "lavfi", "-i", "sine=duration=1", "-shortest", "-pix_fmt", "yuv444p", str(mp4)])
    assert convert(wav, "mp3").stat().st_size > 1000
    assert convert(wav, "flac").stat().st_size > 1000
    assert convert(mp4, "mov").stat().st_size > 1000    # odd 161x91 gets evened out for yuv420p
    assert convert(mp4, "webm").stat().st_size > 1000
    assert convert(mp4, "mp3").stat().st_size > 1000    # audio track extraction
    gif = convert(mp4, "gif")
    with Image.open(gif) as img:
        assert img.n_frames > 1
    assert convert(gif, "mp4", out_dir=tmp_path / "back").stat().st_size > 1000
    silent = tmp_path / "silent.mp4"
    engines.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:duration=1", "-pix_fmt", "yuv420p", str(silent)])
    with pytest.raises(ConversionError, match="has no audio track"):
        convert(silent, "mp3")


@needs("libreoffice")
def test_office_documents(tmp_path):
    txt = tmp_path / "letter.txt"
    txt.write_text("Dear reader,\nthis came from LibreOffice.\n", encoding="utf-8")
    docx = convert(txt, "odt")
    with pymupdf.open(convert(docx, "pdf")) as doc:
        assert "LibreOffice" in doc[0].get_text()


@needs("libreoffice")
def test_markdown_word_roundtrip(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Report\n\nBody *text*.\n\n- one\n- two\n", encoding="utf-8")
    docx = convert(md, "docx")
    with zipfile.ZipFile(docx) as zf:
        assert "Body " in zf.read("word/document.xml").decode()
    back = convert(docx, "md", out_dir=tmp_path / "back").read_text(encoding="utf-8")
    assert "# Report" in back and "*text*" in back and "- one" in back


def test_html_to_markdown(tmp_path):
    page = tmp_path / "p.html"
    page.write_text("<html><head><style>x{}</style></head><body><h2>Hi</h2>"
                    "<p>A <a href='https://example.com'>link</a></p></body></html>", encoding="utf-8")
    md = convert(page, "md").read_text(encoding="utf-8")
    assert md.startswith("## Hi") and "[link](https://example.com)" in md and "x{}" not in md
