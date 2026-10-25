"""Catalog of every format ConvertAll knows: extension -> (category, label)."""

CATEGORIES = [
    "Image", "Video", "Audio", "Subtitle", "Document", "Spreadsheet", "Presentation", "Drawing",
    "Ebook", "Comic", "3D model", "CAD", "Medical", "Data", "Markup", "Font", "Archive", "Folder",
    "Other",
]

_CATALOG = {
    "3D model": {
        "stl": "STL", "obj": "Wavefront OBJ", "ply": "PLY", "off": "OFF", "glb": "glTF binary",
        "gltf": "glTF", "3mf": "3D Manufacturing", "dae": "Collada", "fbx": "FBX", "blend": "Blender",
        "usd": "USD", "usdz": "USDZ", "abc": "Alembic",
    },
    "CAD": {
        "step": "STEP", "iges": "IGES", "brep": "OpenCASCADE BREP", "dxf": "AutoCAD DXF",
    },
    "Medical": {
        "dcm": "DICOM",
    },
    "Image": {
        "png": "PNG", "jpg": "JPEG", "webp": "WebP", "gif": "GIF", "bmp": "Bitmap",
        "tiff": "TIFF", "ico": "Icon", "tga": "Targa", "heic": "HEIC", "avif": "AVIF",
        "ppm": "PPM", "jp2": "JPEG 2000", "psd": "Photoshop", "pcx": "PCX", "dds": "DirectDraw",
        "qoi": "QOI", "icns": "Apple icon", "xbm": "X bitmap", "sgi": "SGI image",
        "cur": "Cursor", "xpm": "X pixmap", "emf": "Windows metafile", "wmf": "Windows metafile",
        "ai": "Illustrator", "svg": "SVG vector", "jxl": "JPEG XL", "exr": "OpenEXR", "hdr": "Radiance HDR",
        "xcf": "GIMP", "dng": "RAW (DNG)", "cr2": "RAW (Canon)",
        "cr3": "RAW (Canon)", "nef": "RAW (Nikon)", "arw": "RAW (Sony)", "orf": "RAW (Olympus)",
        "rw2": "RAW (Panasonic)", "raf": "RAW (Fujifilm)",
    },
    "Video": {
        "mp4": "MP4", "mkv": "Matroska", "webm": "WebM", "mov": "QuickTime", "avi": "AVI",
        "wmv": "Windows Media", "flv": "Flash video", "m4v": "M4V", "mpg": "MPEG",
        "ts": "MPEG-TS", "3gp": "3GP", "ogv": "Ogg video", "vob": "DVD video", "asf": "ASF",
        "f4v": "Flash MP4", "mxf": "MXF", "rm": "RealMedia", "rmvb": "RealMedia",
    },
    "Audio": {
        "mp3": "MP3", "wav": "WAV", "flac": "FLAC", "ogg": "Ogg Vorbis", "opus": "Opus",
        "m4a": "M4A (AAC)", "aac": "AAC", "wma": "Windows Media Audio", "aiff": "AIFF",
        "ac3": "AC-3", "amr": "AMR", "mka": "Matroska audio", "m4b": "Audiobook", "wv": "WavPack",
        "caf": "Core Audio", "mp2": "MPEG layer 2", "au": "Sun audio", "ape": "Monkey's Audio",
    },
    "Subtitle": {
        "srt": "SubRip", "vtt": "WebVTT", "ass": "Advanced SubStation", "ssa": "SubStation Alpha",
    },
    "Document": {
        "pdf": "PDF", "docx": "Word", "doc": "Word 97-2003", "odt": "OpenDocument text",
        "rtf": "Rich Text", "txt": "Plain text", "wpd": "WordPerfect", "pages": "Apple Pages",
        "xps": "XPS", "oxps": "OpenXPS", "docm": "Word (macros)", "dotx": "Word template",
        "dot": "Word 97-2003 template", "wps": "Microsoft Works",
    },
    "Spreadsheet": {
        "xlsx": "Excel", "xls": "Excel 97-2003", "ods": "OpenDocument sheet",
        "numbers": "Apple Numbers", "csv": "CSV", "tsv": "TSV", "xlsm": "Excel (macros)",
        "xlsb": "Excel binary", "xltx": "Excel template",
    },
    "Presentation": {
        "pptx": "PowerPoint", "ppt": "PowerPoint 97-2003", "odp": "OpenDocument slides",
        "key": "Apple Keynote", "pptm": "PowerPoint (macros)", "ppsx": "PowerPoint show",
        "pps": "PowerPoint 97-2003 show", "potx": "PowerPoint template",
    },
    "Drawing": {
        "vsdx": "Visio", "vsd": "Visio 2003-2010", "pub": "Publisher", "odg": "OpenDocument drawing",
        "cdr": "CorelDRAW",
    },
    "Ebook": {
        "epub": "EPUB", "mobi": "Kindle MOBI", "azw3": "Kindle AZW3", "azw": "Kindle AZW",
        "fb2": "FictionBook", "lit": "MS Reader", "pdb": "Palm eBook", "lrf": "Sony LRF",
    },
    "Comic": {
        "cbz": "Comic (zip)", "cbr": "Comic (rar)", "cb7": "Comic (7z)", "cbt": "Comic (tar)",
    },
    "Data": {
        "json": "JSON", "yaml": "YAML", "toml": "TOML", "xml": "XML", "ini": "INI",
        "jsonl": "JSON Lines", "plist": "Property list", "sqlite": "SQLite database",
    },
    "Markup": {
        "md": "Markdown", "html": "HTML",
    },
    "Font": {
        "ttf": "TrueType", "otf": "OpenType", "woff": "WOFF", "woff2": "WOFF2",
    },
    "Archive": {
        "zip": "ZIP", "7z": "7-Zip", "tar": "TAR", "tar.gz": "TAR.GZ", "tar.bz2": "TAR.BZ2",
        "tar.xz": "TAR.XZ", "tar.zst": "TAR.ZST", "gz": "GZip", "bz2": "BZip2", "xz": "XZ",
        "zst": "Zstandard", "rar": "RAR",
        "iso": "Disk image", "cab": "Cabinet", "arj": "ARJ", "lzh": "LZH", "dmg": "Apple disk image",
        "wim": "Windows image", "cpio": "CPIO", "rpm": "RPM package", "deb": "Debian package",
        "z": "Unix compress", "lzma": "LZMA", "msi": "Windows installer", "vhd": "Virtual disk",
        "vhdx": "Virtual disk",
    },
    "Folder": {"folder": "Folder"},
}

FORMATS: dict[str, tuple[str, str]] = {
    ext: (cat, label) for cat, items in _CATALOG.items() for ext, label in items.items()
}

ALIASES = {
    "jpeg": "jpg", "jpe": "jpg", "jfif": "jpg", "tif": "tiff", "heif": "heic", "pbm": "ppm",
    "pgm": "ppm", "j2k": "jp2", "htm": "html", "xhtml": "html", "yml": "yaml",
    "markdown": "md", "tgz": "tar.gz", "tbz2": "tar.bz2", "tbz": "tar.bz2", "txz": "tar.xz",
    "aif": "aiff", "mpeg": "mpg", "mts": "ts", "m2ts": "ts", "qt": "mov", "oga": "ogg",
    "text": "txt", "log": "txt", "cfg": "ini", "lha": "lzh",
    "stp": "step", "igs": "iges", "brp": "brep", "usda": "usd", "usdc": "usd", "dicom": "dcm",
    "apng": "png", "dib": "bmp", "rgb": "sgi", "bw": "sgi", "divx": "avi", "m2v": "mpg",
    "webvtt": "vtt", "ndjson": "jsonl", "sqlite3": "sqlite", "db3": "sqlite", "tzst": "tar.zst",
    "zstd": "zst", "xlt": "xls", "pot": "ppt", "ott": "odt", "ots": "ods", "otp": "odp",
}

MULTI_EXT = ("tar.gz", "tar.bz2", "tar.xz", "tar.zst")

# What a file most likely wants to become: the conversion people ask for most often.
# suggest() falls back to CATEGORY_TARGETS for anything not listed here.
COMMON_TARGETS = {
    "jpg": "png", "png": "jpg", "heic": "jpg", "webp": "png", "avif": "png", "gif": "mp4",
    "tiff": "pdf", "bmp": "png", "ico": "png", "svg": "png", "psd": "png", "ai": "pdf", "jxl": "jpg",
    "exr": "png", "hdr": "jpg", "xcf": "png", "emf": "png", "wmf": "png", "jp2": "jpg",
    "dng": "jpg", "cr2": "jpg", "cr3": "jpg", "nef": "jpg", "arw": "jpg", "orf": "jpg", "rw2": "jpg",
    "raf": "jpg",
    "mp4": "mp3", "mov": "mp4", "mkv": "mp4", "webm": "mp4", "avi": "mp4",
    "mp3": "wav", "wav": "mp3", "flac": "mp3", "m4a": "mp3", "ape": "flac", "wv": "flac",
    "srt": "vtt", "vtt": "srt", "ass": "srt", "ssa": "srt",
    "pdf": "docx", "docx": "pdf", "odt": "docx", "txt": "pdf",
    "xlsx": "pdf", "csv": "xlsx", "tsv": "xlsx", "xls": "xlsx", "ods": "xlsx", "numbers": "xlsx",
    "pptx": "pdf", "odp": "pptx", "key": "pptx",
    "epub": "pdf", "mobi": "epub", "azw3": "epub", "azw": "epub",
    "json": "csv", "yaml": "json", "toml": "json", "xml": "json", "ini": "json", "plist": "json",
    "jsonl": "json", "sqlite": "xlsx",
    "md": "pdf", "html": "pdf",
    "ttf": "woff2", "otf": "woff2", "woff": "ttf", "woff2": "ttf",
    "stl": "obj", "obj": "stl", "fbx": "obj", "blend": "fbx", "glb": "obj", "gltf": "obj", "3mf": "stl",
    "ply": "stl", "off": "stl", "dae": "obj", "usd": "obj", "usdz": "obj", "abc": "obj",
    "step": "stl", "iges": "stl", "brep": "stl", "dxf": "pdf",
    "dcm": "jpg",
    "zip": "7z",
}

CATEGORY_TARGETS = {
    "Image": "png", "Video": "mp4", "Audio": "mp3", "Subtitle": "srt", "Document": "pdf",
    "Spreadsheet": "xlsx", "Presentation": "pdf", "Drawing": "pdf", "Ebook": "epub", "Comic": "pdf",
    "Data": "json", "Markup": "pdf", "Font": "woff2", "3D model": "glb", "CAD": "stl",
    "Medical": "png", "Archive": "zip", "Folder": "zip", "Other": "zip",
}


def category(fmt: str) -> str:
    return FORMATS.get(fmt, ("Other", ""))[0]


def label(fmt: str) -> str:
    return FORMATS.get(fmt, ("Other", fmt.upper()))[1] or fmt.upper()


def suggest(src: str, options) -> str | None:
    """The most likely target for a src file among options (formats it can reach)."""
    for want in (COMMON_TARGETS.get(src), CATEGORY_TARGETS.get(category(src))):
        if want and want != src and want in options:
            return want
    return None


def describe(fmt: str) -> str:
    """'heic' -> 'HEIC image'-ish human text for the UI."""
    if fmt == "folder":
        return "Folder"
    cat, lab = FORMATS.get(fmt, ("Other", fmt.upper()))
    return f"{lab} ({cat.lower()})" if cat != "Other" else f"{fmt.upper()} file"
