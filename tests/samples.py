"""Real sample files for end-to-end tests: make(fmt, folder) builds one, or returns None when nothing
on this machine can create that format (camera RAW, Apple iWork, Visio...)."""

from __future__ import annotations

import io
import shutil
import sqlite3
import struct
import tarfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from convertall import engines
from convertall.converters import archives, documents, images, media

TEXT = "ConvertAll sample text"


def picture(size=(160, 120), shade=0) -> Image.Image:
    img = Image.new("RGBA", size, (240, 240, 240, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, size[0] // 2, size[1] // 2], fill=(220, 40 + shade, 40, 255))
    d.ellipse([size[0] // 2, size[1] // 3, size[0] - 10, size[1] - 10], fill=(30, 90, 200, 255))
    d.rectangle([0, 0, 20, 20], fill=(0, 0, 0, 0))  # transparent corner
    return img


def _jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG")
    return out.getvalue()


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _webp(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "WEBP")
    return out.getvalue()


# ---------------------------------------------------------------- hand-written binary formats

def write_rar(path: Path, files: dict[str, bytes]) -> None:
    """RAR 4 archive with stored entries (packport grew out of this sample writer)."""
    import packport
    packport.write_rar(path, files)


def write_ar(path: Path, members: dict[str, bytes]) -> None:
    out = b"!<arch>\n"
    for name, data in members.items():
        out += f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n".encode() + data
        if len(data) % 2:
            out += b"\n"
    path.write_bytes(out)


def _tar_gz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------- text formats

SRT = "1\n00:00:00,000 --> 00:00:01,000\nHello <i>there</i>\n\n2\n00:00:01,000 --> 00:00:02,000\nSecond line\n"
VTT = "WEBVTT\n\nNOTE made by tests\n\n00:00.000 --> 00:01.000 align:start\n<v Bob>Hello</v>\n\nintro\n00:01.000 --> 00:02.500\nSecond line\n"
HTML = f"<html><head><title>Sample</title></head><body><h1>Heading</h1><p>{TEXT}.</p>" \
       "<ul><li>one</li><li>two</li></ul></body></html>"
MD = f"# Heading\n\n{TEXT}, *emphasis*.\n\n- one\n- two\n"
RECORDS = [{"name": "Ada", "age": 36, "city": "London"}, {"name": "Linus", "age": 28, "city": "Helsinki"}]
FODP = """<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
 xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
 office:version="1.2" office:mimetype="application/vnd.oasis.opendocument.presentation">
<office:body><office:presentation>
<draw:page draw:name="One"><draw:frame svg:x="2cm" svg:y="2cm" svg:width="20cm" svg:height="3cm">
<draw:text-box><text:p>Slide one: ConvertAll sample text</text:p></draw:text-box></draw:frame></draw:page>
<draw:page draw:name="Two"><draw:frame svg:x="2cm" svg:y="2cm" svg:width="20cm" svg:height="3cm">
<draw:text-box><text:p>Slide two</text:p></draw:text-box></draw:frame></draw:page>
</office:presentation></office:body></office:document>
"""
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" fill="#eee"/>'
       '<circle cx="60" cy="40" r="30" fill="#c33"/><text x="10" y="75" font-size="10">ConvertAll</text></svg>')
XPM = """/* XPM */
static char *sample[] = {
"4 4 2 1",
"  c #FFFFFF",
"X c #FF0000",
"XX  ",
"XX  ",
"  XX",
"  XX"};
"""
FB2 = f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Sample</book-title><lang>en</lang></title-info></description>
<body><section><title><p>Chapter</p></title><p>{TEXT}.</p></section></body></FictionBook>
"""


SUBTITLE_TEXT = {
    "sbv": "0:00:00.000,0:00:01.000\nHello there\n\n0:00:01.000,0:00:02.000\nSecond line\n",
    "sub": "{1}{1}25.000\n{0}{25}Hello there\n{25}{50}Second line\n",
    "ttml": '<?xml version="1.0" encoding="utf-8"?>\n<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="00:00:00.000" end="00:00:01.000">Hello there</p>'
            '<p begin="00:00:01.000" end="00:00:02.000">Second line</p></div></body></tt>\n',
    "smi": "<SAMI><HEAD><TITLE>Sample</TITLE></HEAD><BODY>\n<SYNC Start=0><P Class=ENCC>Hello there\n"
           "<SYNC Start=1000><P Class=ENCC>Second line\n<SYNC Start=2000><P Class=ENCC>&nbsp;\n</BODY></SAMI>\n",
}
MARKUP_TEXT = {
    "tex": "\\documentclass{article}\n\\begin{document}\n\\section{Heading}\n" + TEXT
           + ", \\emph{emphasis}.\n\\begin{itemize}\n\\item one\n\\item two\n\\end{itemize}\n\\end{document}\n",
    "rst": "Heading\n=======\n\n" + TEXT + ", *emphasis*.\n\n- one\n- two\n",
    "org": "* Heading\n\n" + TEXT + ", /emphasis/.\n\n- one\n- two\n",
    "adoc": "= Sample\n\n== Heading\n\n" + TEXT + ", _emphasis_.\n\n* one\n* two\n",
    "wiki": "== Heading ==\n\n" + TEXT + ", ''emphasis''.\n\n* one\n* two\n",
}
PS = f"%!PS-Adobe-3.0\n/Helvetica findfont 24 scalefont setfont 72 700 moveto ({TEXT}) show\n" \
     "newpath 72 600 moveto 300 450 lineto 72 450 lineto closepath stroke\nshowpage\n"
EPS = "%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 60 440 400 730\n" + PS.split("\n", 1)[1].replace("showpage\n", "")
GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="tests" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="51.5007" lon="-0.1246"><ele>12</ele><name>Big Ben</name></wpt>
<trk><name>Walk</name><trkseg>
<trkpt lat="51.5007" lon="-0.1246"><ele>12</ele><time>2026-05-01T10:00:00Z</time></trkpt>
<trkpt lat="51.5014" lon="-0.1419"><ele>15</ele><time>2026-05-01T10:20:00Z</time></trkpt>
<trkpt lat="51.5033" lon="-0.1195"><ele>9</ele><time>2026-05-01T10:45:00Z</time></trkpt>
</trkseg></trk></gpx>
"""
KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2"><Document>
<name>Sample</name><Folder>
<Placemark><name>Eiffel Tower</name><Point><coordinates>2.2945,48.8584,35</coordinates></Point></Placemark>
<Placemark><name>Seine walk</name><LineString><coordinates>2.2945,48.8584 2.3010,48.8610 2.3200,48.8630</coordinates>
</LineString></Placemark>
<Placemark><name>Park</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
2.29,48.85 2.30,48.85 2.30,48.86 2.29,48.85</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Folder></Document></kml>
"""
GEOJSON = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Statue"}, "geometry": {"type": "Point", "coordinates": [-74.0445, 40.6892]}},
    {"type": "Feature", "properties": {"name": "Ferry"},
     "geometry": {"type": "LineString", "coordinates": [[-74.0445, 40.6892], [-74.0134, 40.7013]]}}]}
VCF = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ada Lovelace\r\nN:Lovelace;Ada;;;\r\nORG:Analytical Engines\r\n"
       "EMAIL;TYPE=INTERNET:ada@example.com\r\nTEL;TYPE=CELL:+44 20 7946 0000\r\nNOTE:Line one\\nline two\\, "
       "with a comma that is long enough to need folding onto\r\n  the next line\r\nEND:VCARD\r\n"
       "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Torvalds;Linus\r\nTEL;WORK:+358 9 000\r\n"
       "ADR;HOME;ENCODING=QUOTED-PRINTABLE:;;Helsinginkatu 1=0D=0A;Helsinki;;00100;Finland\r\nEND:VCARD\r\n")
ICS = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//tests//EN\r\nBEGIN:VEVENT\r\nUID:one@tests\r\n"
       "DTSTART:20261025T140000Z\r\nDTEND:20261025T150000Z\r\nSUMMARY:Team meeting\\, weekly\r\n"
       "LOCATION:Room 4\r\nRRULE:FREQ=WEEKLY;BYDAY=SU\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Soon\r\n"
       "TRIGGER:-PT10M\r\nEND:VALARM\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:two@tests\r\n"
       "DTSTART;VALUE=DATE:20261101\r\nDTEND;VALUE=DATE:20261103\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\n"
       "END:VCALENDAR\r\n")


def write_ipynb(path: Path) -> None:
    import base64
    import json
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"language": "python"}}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Heading\n", f"{TEXT}."]},
        {"cell_type": "code", "metadata": {}, "execution_count": 1, "source": ["print('hello')"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["hello\n"]},
                     {"output_type": "display_data", "metadata": {},
                      "data": {"image/png": base64.b64encode(_png(picture())).decode(), "text/plain": ["<Figure>"]}}]}]}
    path.write_text(json.dumps(nb), encoding="utf-8")


def write_eml(path: Path) -> None:
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "Ada <ada@example.com>", "Linus <linus@example.com>", "Sample mail"
    msg["Date"] = "Sun, 25 Oct 2026 14:00:00 +0000"
    msg.set_content(f"{TEXT}.\nSecond line.\n")
    msg.add_alternative(f"<html><body><p>{TEXT}.</p><img src='cid:pic1'></body></html>", subtype="html")
    msg.get_payload()[1].add_related(_png(picture()), "image", "png", cid="<pic1>")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="report.pdf")
    path.write_bytes(msg.as_bytes())


def write_mht(path: Path) -> None:
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = "Saved page"
    msg.set_content(f"<html><head><meta charset='windows-1252'></head><body><h1>Heading</h1><p>{TEXT}.</p>"
                    "<img src='https://example.com/pic.png'></body></html>", subtype="html")
    msg.add_related(_png(picture()), "image", "png")
    msg.get_payload()[1]["Content-Location"] = "https://example.com/pic.png"
    path.write_bytes(msg.as_bytes())


def write_cfb(path: Path, streams: dict[str, bytes]) -> None:
    """Minimal OLE compound file, the container of Outlook .msg files: version 3, 512-byte sectors,
    streams under 4 KB in the mini stream as the format requires. Storages are path parts ('a/b')."""
    endchain, fatsect, free = 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
    nodes = [{"name": "Root Entry", "type": 5, "kids": [], "data": b""}]
    index = {"": 0}
    for full in sorted(streams):
        parts = full.split("/")
        for i in range(1, len(parts)):
            key = "/".join(parts[:i])
            if key not in index:
                index[key] = len(nodes)
                nodes.append({"name": parts[i - 1], "type": 1, "kids": [], "data": b""})
                nodes[index["/".join(parts[:i - 1])]]["kids"].append(index[key])
        index[full] = len(nodes)
        nodes.append({"name": parts[-1], "type": 2, "kids": [], "data": streams[full]})
        nodes[index["/".join(parts[:-1])]]["kids"].append(index[full])

    mini, minifat = b"", []
    for n in nodes:
        if n["type"] == 2 and len(n["data"]) < 4096:
            count = max(1, -(-len(n["data"]) // 64))
            n["start"] = len(mini) // 64
            minifat += [len(minifat) + i + 1 for i in range(count - 1)] + [endchain]
            mini += n["data"].ljust(count * 64, b"\0")
    sectors: list[bytes] = []
    fat: list[int] = []

    def add(data: bytes, pad: bytes = b"\0") -> int:
        start, count = len(sectors), max(1, -(-len(data) // 512))
        for i in range(count):
            sectors.append(data[i * 512:(i + 1) * 512].ljust(512, pad))
        fat.extend([start + i + 1 for i in range(count - 1)] + [endchain])
        return start

    for n in nodes:
        if n["type"] == 2 and len(n["data"]) >= 4096:
            n["start"] = add(n["data"])
    nodes[0]["start"], nodes[0]["data"] = (add(mini), mini) if mini else (endchain, b"")
    minifat_start = add(struct.pack(f"<{len(minifat)}I", *minifat), b"\xff") if minifat else endchain
    minifat_count = len(sectors) - minifat_start if minifat else 0

    for n in nodes:  # each storage's children: first one is its child, the rest a right-sibling chain
        kids = sorted(n["kids"], key=lambda k: (len(nodes[k]["name"]), nodes[k]["name"].upper()))
        n["child"] = kids[0] if kids else free
        for a, b in zip(kids, kids[1:] + [free]):
            nodes[a]["right"] = b
    entries = b""
    for n in nodes:
        name = n["name"].encode("utf-16-le") + b"\0\0"
        entries += struct.pack("<64sHBBIII16sIQQIII", name, len(name), n["type"], 1, free, n.get("right", free),
                               n["child"], b"\0" * 16, 0, 0, 0, n.get("start", 0) if n["type"] != 1 else 0,
                               len(n["data"]), 0)
    while len(entries) % 512:
        entries += struct.pack("<64sHBBIII16sIQQIII", b"", 0, 0, 0, free, free, free, b"\0" * 16, 0, 0, 0, 0, 0, 0)
    dir_start = add(entries)

    nfat = 1
    while (len(sectors) + nfat) > nfat * 128:
        nfat += 1
    fat_start = len(sectors)
    fat += [fatsect] * nfat
    fat += [free] * (nfat * 128 - len(fat))
    for i in range(nfat):
        sectors.append(struct.pack("<128I", *fat[i * 128:(i + 1) * 128]))
    difat = [fat_start + i for i in range(nfat)] + [free] * (109 - nfat)
    header = struct.pack("<8s16sHHHHH6sIIIIIIIII", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"\0" * 16, 0x3E, 3,
                         0xFFFE, 9, 6, b"\0" * 6, 0, nfat, dir_start, 0, 4096, minifat_start, minifat_count,
                         endchain, 0) + struct.pack("<109I", *difat)
    path.write_bytes(header + b"".join(sectors))


def write_msg(path: Path) -> None:
    """An Outlook message: MAPI properties as streams (001F = UTF-16 text, 0102 = bytes)."""
    def text(s: str) -> bytes:
        return s.encode("utf-16-le")
    sent = (1_792_000_000 * 10_000_000) + 116_444_736_000_000_000  # 2026-10-15 as a FILETIME
    props = b"\0" * 32 + struct.pack("<IIQ", 0x00390040, 6, sent)
    pre = "__attach_version1.0_#0000000"
    write_cfb(path, {
        "__substg1.0_0037001F": text("Sample mail"), "__substg1.0_0C1A001F": text("Ada"),
        "__substg1.0_5D01001F": text("ada@example.com"), "__substg1.0_0E04001F": text("Linus"),
        "__substg1.0_1000001F": text(f"{TEXT}.\r\nSecond line."),
        "__substg1.0_10130102": f"<html><body><p>{TEXT}.</p><img src='cid:pic1'></body></html>".encode(),
        "__properties_version1.0": props,
        f"{pre}0/__substg1.0_3707001F": text("pic.png"), f"{pre}0/__substg1.0_37010102": _png(picture()),
        f"{pre}0/__substg1.0_3712001F": text("pic1"), f"{pre}0/__substg1.0_370E001F": text("image/png"),
        f"{pre}1/__substg1.0_3707001F": text("report.pdf"), f"{pre}1/__substg1.0_37010102": b"%PDF-1.4 x" * 500,
    })


def write_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">sample</dc:identifier>'
                   '<dc:title>Sample</dc:title><dc:language>en</dc:language></metadata>'
                   '<manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>'
                   '<spine><itemref idref="c1"/></spine></package>')
        z.writestr("OEBPS/nav.xhtml",
                   '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
                   '<body><nav epub:type="toc"><ol><li><a href="ch1.xhtml">Chapter</a></li></ol></nav></body></html>')
        z.writestr("OEBPS/ch1.xhtml",
                   f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title></head>'
                   f'<body><h1>Chapter</h1><p>{TEXT}.</p></body></html>')


def _font(path: Path, cff: bool) -> None:
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    fb = FontBuilder(1000, isTTF=not cff)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    pen = T2CharStringPen(1000, None) if cff else TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((500, 700))
    pen.lineTo((900, 0))
    pen.closePath()
    if cff:
        empty = T2CharStringPen(500, None)
        fb.setupCFF("Sample", {"FullName": "Sample"}, {".notdef": empty.getCharString(), "A": pen.getCharString()}, {})
    else:
        fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "A": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (1000, 100)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Sample", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    fb.save(str(path))


# ---------------------------------------------------------------- engine-made samples

def _ffmpeg(args: list, path: Path) -> Path | None:
    exe = engines.find("ffmpeg")
    if not exe:
        return None
    engines.run([exe, "-hide_banner", "-nostdin", "-y", *args, str(path)], timeout=120)
    return path


AV_IN = ["-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2", "-f", "lavfi", "-i", "sine=duration=2"]
# containers that can carry a text subtitle track, and the codec they want it in
SUB_CODEC = {"mkv": "srt", "mp4": "mov_text", "m4v": "mov_text", "mov": "mov_text", "webm": "webvtt"}


def _video(fmt: str, path: Path) -> Path | None:
    args = {"mxf": ["-c:v", "mpeg2video", "-c:a", "pcm_s16le", "-ar", "48000"],
            "rm": ["-c:v", "rv20", "-c:a", "ac3"], "rmvb": ["-f", "rm", "-c:v", "rv20", "-c:a", "ac3"],
            "3g2": [*media.H264, *media.AAC, "-ar", "44100", "-f", "3g2"]}.get(fmt)
    args = args or media.VIDEO_ARGS[fmt]
    if fmt in SUB_CODEC:
        srt = path.with_name("track.srt")
        srt.write_text(SRT, encoding="utf-8")
        return _ffmpeg([*AV_IN, "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:s", *args,
                        "-c:s", SUB_CODEC[fmt], "-shortest"], path)
    return _ffmpeg([*AV_IN, *args, "-shortest"], path)


def _soffice(src: Path, path: Path, filt: str) -> Path | None:
    """Ask LibreOffice to save src as path, using export filter filt ('docx', 'dotx:MS Word 2007 XML Template'...)."""
    if not engines.available("libreoffice"):
        return None
    out = path.parent / f"_lo_{path.suffix[1:]}"
    out.mkdir(exist_ok=True)
    engines.run([documents._soffice(), "--headless", "--norestore", "--nolockcheck", "--nodefault",
                 f"-env:UserInstallation={documents._profile_uri()}", "--convert-to", filt,
                 "--outdir", str(out), str(src)], timeout=300)
    made = next(out.iterdir(), None)
    if made is None:
        return None
    shutil.move(str(made), str(path))
    return path


def _blender(glb: Path, path: Path) -> Path | None:
    exe = engines.find("blender")
    if not exe:
        return None
    save = {"blend": f"bpy.ops.wm.save_as_mainfile(filepath=r'{path}')",
            "fbx": f"bpy.ops.export_scene.fbx(filepath=r'{path}')",
            "usd": f"bpy.ops.wm.usd_export(filepath=r'{path}')",
            "usdz": f"bpy.ops.wm.usd_export(filepath=r'{path}')",
            "abc": f"bpy.ops.wm.alembic_export(filepath=r'{path}')"}[path.suffix[1:]]
    script = path.with_name(f"_make_{path.suffix[1:]}.py")
    script.write_text("import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
                      f"bpy.ops.import_scene.gltf(filepath=r'{glb}')\n{save}\n", encoding="utf-8")
    engines.run([exe, "-b", "--factory-startup", "-noaudio", "--python-exit-code", "1", "--python", str(script)],
                timeout=600)
    return path


# ---------------------------------------------------------------- the factory

class Samples:
    """Builds each sample once per folder; later samples may be made from earlier ones."""

    def __init__(self, folder: Path):
        self.dir = folder
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, Path | None] = {}

    def __call__(self, fmt: str) -> Path | None:
        if fmt not in self.cache:
            target = self.dir / ("sample_folder" if fmt == "folder" else f"sample.{fmt}")
            self.cache[fmt] = self._make(fmt, target)
        return self.cache[fmt]

    def _make(self, fmt: str, p: Path) -> Path | None:  # noqa: C901 - one branch per family
        img = picture()
        # images (cursor and pixmap made by hand, so ConvertAll's own writers don't test themselves)
        if fmt == "cur":
            buf = io.BytesIO()
            img.resize((32, 32)).save(buf, "ICO", sizes=[(32, 32)], bitmap_format="bmp")
            data = bytearray(buf.getvalue())
            data[2] = 2  # ICO type 1 -> CUR type 2
            p.write_bytes(bytes(data))
            return p
        if fmt == "xpm":
            p.write_text(XPM)
            return p
        if fmt in ("ps", "eps"):  # vector PostScript with real text (Pillow's EPS would be a bitmap)
            p.write_text(EPS if fmt == "eps" else PS, encoding="ascii")
            return p
        if fmt in images.WRITE - {"pdf"}:
            images.save_image(images.prepare(img, fmt), p, fmt)
            return p
        if fmt == "djvu":
            c44 = engines.find("djvulibre") and Path(engines.find("djvulibre")).with_name("c44.exe")
            if not c44 or not c44.exists():
                return None
            img.convert("RGB").save(self.dir / "_djvu.ppm")
            engines.run([c44, "_djvu.ppm", p.name], cwd=str(self.dir))
            return p
        if fmt == "svg":
            p.write_text(SVG, encoding="utf-8")
            return p
        if fmt == "ai":  # PDF-compatible Illustrator file = a PDF
            shutil.copyfile(self("pdf"), p)
            return p
        if fmt in ("emf", "wmf"):
            return _soffice(self("svg"), p, fmt)
        # audio / video / subtitles
        if fmt in media.AUDIO_ARGS:
            return _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=2", *media.AUDIO_ARGS[fmt]], p)
        if fmt in media.VIDEO_ARGS or fmt in ("mxf", "rm", "rmvb", "3g2"):
            return _video(fmt, p)
        if fmt == "srt":
            p.write_text(SRT, encoding="utf-8")
            return p
        if fmt == "vtt":
            p.write_text(VTT, encoding="utf-8")
            return p
        if fmt in ("ass", "ssa"):
            return _ffmpeg(["-i", str(self("srt"))], p)
        if fmt in SUBTITLE_TEXT:
            p.write_text(SUBTITLE_TEXT[fmt], encoding="utf-8")
            return p
        if fmt in MARKUP_TEXT:
            p.write_text(MARKUP_TEXT[fmt], encoding="utf-8")
            return p
        if fmt == "ipynb":
            write_ipynb(p)
            return p
        if fmt == "eml":
            write_eml(p)
            return p
        if fmt == "msg":
            write_msg(p)
            return p
        if fmt == "mht":
            write_mht(p)
            return p
        # maps, contacts, calendars
        if fmt == "gpx":
            p.write_text(GPX, encoding="utf-8")
            return p
        if fmt == "kml":
            p.write_text(KML, encoding="utf-8")
            return p
        if fmt == "kmz":
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("doc.kml", KML)
            return p
        if fmt == "geojson":
            import json
            p.write_text(json.dumps(GEOJSON), encoding="utf-8")
            return p
        if fmt == "vcf":
            p.write_bytes(VCF.encode())
            return p
        if fmt == "ics":
            p.write_bytes(ICS.encode())
            return p
        # documents
        if fmt == "pdf":
            import pymupdf
            doc = pymupdf.open()
            for i in range(2):
                page = doc.new_page()
                page.insert_text((72, 72), f"{TEXT}, page {i + 1}")
                page.insert_image(pymupdf.Rect(72, 100, 232, 220), stream=_png(img))
            doc.save(p)
            return p
        if fmt == "txt":
            p.write_text(f"{TEXT}\nsecond line\n", encoding="utf-8")
            return p
        if fmt == "html":
            p.write_text(HTML, encoding="utf-8")
            return p
        if fmt == "md":
            p.write_text(MD, encoding="utf-8")
            return p
        writer = {"odt": "odt", "docx": "docx", "doc": "doc:MS Word 97", "rtf": "rtf",
                  "docm": "docm:MS Word 2007 XML VBA", "dotx": "dotx:MS Word 2007 XML Template",
                  "dot": "dot:MS Word 97 Vorlage"}
        if fmt in writer:
            html = self.dir / "_writer.html"
            html.write_text(HTML, encoding="utf-8")
            return _soffice_writer(html, p, writer[fmt])
        if fmt == "xlsx":
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.append(list(RECORDS[0]))
            for r in RECORDS:
                ws.append(list(r.values()))
            wb.save(p)
            return p
        calc = {"xls": "xls:MS Excel 97", "ods": "ods", "xlsm": "xlsm:Calc MS Excel 2007 VBA XML", "dbf": "dbf:dBase",
                "xltx": "xltx:Calc MS Excel 2007 XML Template", "xlsb": "xlsb:Calc MS Excel 2007 Binary"}
        if fmt in calc:
            return _soffice(self("xlsx"), p, calc[fmt])
        if fmt in ("csv", "tsv"):
            sep = "," if fmt == "csv" else "\t"
            p.write_text(sep.join(RECORDS[0]) + "\n" + "\n".join(sep.join(str(v) for v in r.values()) for r in RECORDS)
                         + "\n", encoding="utf-8")
            return p
        impress = {"odp": "odp", "pptx": "pptx", "ppt": "ppt:MS PowerPoint 97",
                   "pptm": "pptm:Impress MS PowerPoint 2007 XML VBA",
                   "ppsx": "ppsx:Impress MS PowerPoint 2007 XML AutoPlay", "pps": "pps:MS PowerPoint 97 AutoPlay",
                   "potx": "potx:Impress MS PowerPoint 2007 XML Template"}
        if fmt in impress:
            fodp = self.dir / "_slides.fodp"
            fodp.write_text(FODP, encoding="utf-8")
            return _soffice(fodp, p, impress[fmt])
        if fmt == "odg":
            return _soffice(self("svg"), p, "odg")
        # ebooks & comics
        if fmt == "epub":
            write_epub(p)
            return p
        if fmt == "fb2":
            p.write_text(FB2, encoding="utf-8")
            return p
        if fmt in ("cbz", "cbr", "cb7", "cbt"):
            pages = self.dir / f"_pages_{fmt}"
            (pages / "Issue 1").mkdir(parents=True, exist_ok=True)
            # mixed page types, a subfolder, natural order (2 before 10), metadata and macOS junk
            for name, data in {"Issue 1/page2.jpg": _jpeg(picture(shade=20)),
                               "Issue 1/page10.png": _png(picture(shade=60)),
                               "Issue 1/page3.webp": _webp(picture(shade=40)),
                               "Issue 1/page1.jpg": _jpeg(picture((120, 160)))}.items():
                (pages / name).write_bytes(data)
            (pages / "ComicInfo.xml").write_text("<ComicInfo><Title>Sample</Title></ComicInfo>")
            if fmt == "cbr":
                files = {f.relative_to(pages).as_posix(): f.read_bytes() for f in pages.rglob("*") if f.is_file()}
                write_rar(p, files)
            else:
                archives.compress(pages, p, fmt)
                if fmt == "cbz":  # a Mac-made comic carries resource-fork junk
                    with zipfile.ZipFile(p, "a") as z:
                        z.writestr("__MACOSX/Issue 1/._page1.jpg", b"\x00\x05\x16\x07junk")
            return p
        # data
        if fmt in ("json", "jsonl", "yaml", "toml", "xml", "plist"):
            from convertall.converters import data
            data.dump({"people": RECORDS} if fmt != "jsonl" else RECORDS, p, fmt)
            return p
        if fmt == "ini":
            p.write_text("[server]\nHost = example.com\nport = 8080\n\n[client]\nretries = 3\n", encoding="utf-8")
            return p
        if fmt == "sqlite":
            con = sqlite3.connect(p)
            con.execute("CREATE TABLE people (name TEXT, age INTEGER, photo BLOB)")
            con.executemany("INSERT INTO people VALUES (?, ?, ?)", [(r["name"], r["age"], b"\x00\x01") for r in RECORDS])
            con.execute("CREATE TABLE cities (name TEXT)")
            con.execute("INSERT INTO cities VALUES ('London')")
            con.commit()
            con.close()
            return p
        # fonts
        if fmt == "ttf":
            _font(p, cff=False)
            return p
        if fmt == "otf":
            _font(p, cff=True)
            return p
        if fmt in ("woff", "woff2"):
            from fontTools.ttLib import TTFont
            font = TTFont(self("ttf"))
            font.flavor = fmt
            font.save(p)
            return p
        if fmt == "ttc":
            from fontTools.ttLib import TTCollection, TTFont
            ttc = TTCollection()
            ttc.fonts = [TTFont(self("ttf")), TTFont(self("otf"))]
            ttc.save(p)
            return p
        # 3D & CAD & medical
        if fmt in ("glb", "gltf", "stl", "obj", "ply", "off", "3mf", "dae"):
            import trimesh
            box = trimesh.creation.box((2, 2, 2))
            ball = trimesh.creation.icosphere(1)
            ball.apply_translation((4, 0, 0))
            scene = trimesh.Scene({"box": box, "ball": ball})
            if fmt == "gltf":
                files = trimesh.exchange.gltf.export_gltf(scene, embed_buffers=True)
                p.write_bytes(next(v for k, v in files.items() if k.endswith(".gltf")))
            else:
                out = (scene if fmt in ("glb", "3mf", "obj", "ply", "stl") else scene.to_mesh()).export(file_type=fmt)
                p.write_bytes(out.encode() if isinstance(out, str) else out)
            return p
        if fmt == "fbx" and not engines.find("blender"):  # Blender's FBX is the more independent sample
            import meshport
            meshport.save(meshport.load(self("glb")), p)
            return p
        if fmt in ("fbx", "blend", "usd", "usdz", "abc"):
            return _blender(self("glb"), p)
        if fmt in ("step", "iges", "brep"):
            import gmsh
            gmsh.initialize(interruptible=False)
            try:
                gmsh.option.setNumber("General.Terminal", 0)
                gmsh.model.occ.addBox(0, 0, 0, 40, 30, 5)
                gmsh.model.occ.synchronize()
                gmsh.write(str(p))
            finally:
                gmsh.finalize()
            return p
        if fmt == "3ds":
            import meshport
            meshport.save(meshport.load(self("glb")), p)
            return p
        if fmt == "dxf":
            import ezdxf
            doc = ezdxf.new()
            doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True)
            doc.modelspace().add_circle((50, 30), 20, dxfattribs={"color": 1})
            doc.saveas(p)
            return p
        if fmt == "dcm":
            from pydicom.data import get_testdata_file
            shutil.copyfile(get_testdata_file("CT_small.dcm"), p)
            return p
        # archives & folders
        if fmt == "folder":
            p.mkdir()
            (p / "notes.txt").write_text(TEXT)
            (p / "scan 2.png").write_bytes(_png(picture(shade=30)))
            (p / "scan 1.jpg").write_bytes(_jpeg(picture()))
            return p
        if fmt in archives.COMPRESS_OUT:
            archives.compress(self("folder") if fmt in archives.FOLDER_OUT else self("txt"), p, fmt)
            return p
        if fmt == "lzma":
            import lzma
            with lzma.open(p, "wb", format=lzma.FORMAT_ALONE) as f:
                f.write(TEXT.encode())
            return p
        if fmt == "deb":
            write_ar(p, {"debian-binary": b"2.0\n",
                         "control.tar.gz": _tar_gz({"./control": b"Package: sample\nVersion: 1.0\n"}),
                         "data.tar.gz": _tar_gz({"./usr/share/doc/sample/readme": TEXT.encode()})})
            return p
        if fmt == "wim" and engines.available("7zip"):
            engines.run([engines.find("7zip"), "a", "-twim", str(p), str(self("folder"))])
            return p
        if fmt in archives.ZIP_BASED:  # apps and packages are zip files under another name
            shutil.copyfile(self("zip"), p)
            return p
        if fmt == "ar":
            write_ar(p, {"notes.txt": TEXT.encode(), "readme": b"second member\n"})
            return p
        if fmt == "img":  # a raw disc image: 7-Zip finds the ISO 9660 file system inside
            shutil.copyfile(self("iso"), p)
            return p
        if fmt == "001" and engines.available("7zip"):  # a 7z split into 1 KB volumes
            vol = self.dir / "_split" / "sample.7z"
            vol.parent.mkdir(exist_ok=True)
            engines.run([engines.find("7zip"), "a", "-v1k", "-mx0", str(vol), str(self("folder"))])
            for part in vol.parent.iterdir():  # sample.7z.001, .002... -> sample.001, .002...
                shutil.move(str(part), str(self.dir / f"sample.{part.suffix[1:]}"))
            return p
        return None


def _soffice_writer(html: Path, p: Path, filt: str) -> Path | None:
    """HTML has to be opened by Writer (not Writer/Web) to be saved as a Word document."""
    if not engines.available("libreoffice"):
        return None
    out = p.parent / f"_lo_{p.suffix[1:]}"
    out.mkdir(exist_ok=True)
    engines.run([documents._soffice(), "--headless", "--norestore", "--nolockcheck", "--nodefault",
                 f"-env:UserInstallation={documents._profile_uri()}", "--infilter=HTML (StarWriter)",
                 "--convert-to", filt, "--outdir", str(out), str(html)], timeout=300)
    made = next(out.iterdir(), None)
    if made is None:
        return None
    shutil.move(str(made), str(p))
    return p
