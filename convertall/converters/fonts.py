"""Fonts via fontTools: TTF/OTF <-> WOFF/WOFF2, TrueType <-> CFF outlines, and collections (.ttc)
split into their fonts."""

from pathlib import Path

from ..errors import ConversionError
from ..losses import loss
from ..registry import converter

FLAVOR = {"ttf": None, "otf": None, "woff": "woff", "woff2": "woff2"}
MAX_ERR = 1.0  # font units: how far a converted curve may stray from the original (1/1000 em)


def _to_cff(font) -> None:
    """Quadratic TrueType outlines -> cubic CFF (an .otf), in place."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.qu2cuPen import Qu2CuPen
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    if "fvar" in font:
        raise ConversionError("Variable fonts can't change outline type; convert to WOFF2 instead")
    glyphs = font.getGlyphSet()
    hmtx = font["hmtx"]
    charstrings = {}
    for name in font.getGlyphOrder():
        pen = T2CharStringPen(hmtx[name][0], glyphs)
        # TrueType draws outer contours clockwise, PostScript counter-clockwise
        glyphs[name].draw(Qu2CuPen(pen, MAX_ERR, all_cubic=True, reverse_direction=True))
        charstrings[name] = pen.getCharString()
    names = font["name"]
    ps_name = (names.getDebugName(6) or names.getDebugName(4) or "Font").replace(" ", "")
    info = {"FullName": names.getDebugName(4) or ps_name, "FamilyName": names.getDebugName(1) or ps_name,
            "Weight": names.getDebugName(2) or "Regular"}
    for tag in ("glyf", "loca", "fpgm", "prep", "cvt ", "gasp", "hdmx", "LTSH", "VDMX", "cvar", "gvar"):
        if tag in font:
            del font[tag]
    font.sfntVersion = "OTTO"
    fb = FontBuilder(font=font, isTTF=False)
    fb.setupCFF(ps_name, info, charstrings, {})
    fb.setupMaxp()
    font["post"].formatType = 3.0  # CFF carries the glyph names itself


def _to_glyf(font) -> None:
    """Cubic CFF outlines -> quadratic TrueType (a .ttf), in place (fontTools' otf2ttf recipe)."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import newTable
    if "CFF2" in font:
        raise ConversionError("Variable fonts can't change outline type; convert to WOFF2 instead")
    order = font.getGlyphOrder()
    glyphs = font.getGlyphSet()
    quadratic = {}
    for name in order:
        pen = TTGlyphPen(glyphs)
        glyphs[name].draw(Cu2QuPen(pen, MAX_ERR, reverse_direction=True))
        quadratic[name] = pen.glyph()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = quadratic
    for tag in ("CFF ", "VORG"):
        if tag in font:
            del font[tag]
    glyf.compile(font)
    for name, g in quadratic.items():  # left side bearing = where the outline starts
        width, _ = font["hmtx"][name]
        font["hmtx"][name] = (width, getattr(g, "xMin", 0))
    font["maxp"] = maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.maxZones = 1
    for attr in ("maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                 "maxStackElements", "maxSizeOfInstructions", "maxComponentElements"):
        setattr(maxp, attr, 0)
    maxp.compile(font)
    post = font["post"]
    post.formatType, post.extraNames, post.mapping = 2.0, [], {}
    post.glyphOrder = order
    try:
        post.compile(font)
    except OverflowError:
        post.formatType = 3.0
    font.sfntVersion = "\x00\x01\x00\x00"


def _outline_notes(src: str, dst: str, opts: dict) -> list:
    # .ttf is TrueType and .otf usually CFF; a .woff or .woff2 may hold either, so it isn't said up front
    if dst == "otf" and src == "ttf":
        return [loss("Outlines become CFF curves (within 1/1000 of the letter size) and TrueType hinting is "
                     "left out", weight=0)]
    if dst == "ttf" and src == "otf":
        return [loss("Outlines become TrueType curves (within 1/1000 of the letter size) and CFF hinting is "
                     "left out", weight=0)]
    return []


@converter(inputs={"ttf", "otf", "woff", "woff2"}, outputs={"woff", "woff2"})
@converter(inputs={"ttf", "otf", "woff", "woff2"}, outputs={"ttf", "otf"}, first_only=True, notes=_outline_notes)
def font_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    from fontTools.ttLib import TTFont
    font = TTFont(src)
    if dst_fmt in ("ttf", "otf"):
        is_cff = font.sfntVersion == "OTTO"
        if dst_fmt == "otf" and not is_cff:
            _to_cff(font)
        elif dst_fmt == "ttf" and is_cff:
            _to_glyf(font)
    font.flavor = FLAVOR[dst_fmt]
    font.save(dst)


@converter(inputs={"ttc"}, outputs={"ttf"}, terminal=True)
def split_collection(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    """Every font in the collection, each saved in its own outline type (.ttf or .otf)."""
    from fontTools.ttLib import TTCollection
    folder = dst.parent / dst.stem
    folder.mkdir()
    with TTCollection(src) as ttc:
        if not ttc.fonts:
            raise ConversionError("This collection holds no fonts")
        used: set[str] = set()
        for i, font in enumerate(ttc.fonts):
            name = (font["name"].getDebugName(4) or f"{src.stem} {i + 1}") if "name" in font else f"{src.stem} {i + 1}"
            name = "".join(c for c in name if c not in '<>:"/\\|?*').strip() or f"font {i + 1}"
            while name.lower() in used:
                name += f" {i + 1}"
            used.add(name.lower())
            font.save(folder / f"{name}.{'otf' if font.sfntVersion == 'OTTO' else 'ttf'}")
    return folder
