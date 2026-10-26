# Changelog

Newest first. Each entry is dated by when it landed.

## 2026-10-26: Safer 3D files, old Windows text files, and the app moves to Releases (part of 1.1.0)

- **Fixed (security):** a 3D model's texture paths could name any file on the computer, and converting the model to FBX, 3DS or OBJ copied that file into the output. ConvertAll now uses [meshport 0.2.0](https://github.com/puretechteam/meshport/blob/main/CHANGELOG.md), which only takes files that are really images and never opens network paths.
- **Fixed:** subtitles, web pages, HTML → PDF, CSV, JSON, YAML, TOML, XML and INI files saved in older Windows encodings (Windows-1252) or as "Unicode" (UTF-16) keep their accented letters. Before, accents turned into "�" in some conversions and CSV files from Excel failed outright. One shared reader (`convertall/textfile.py`) replaces three copies of the same fallback.
- **Fixed:** an unexpected error during a conversion or engine install could leave the window's progress bar spinning forever. It now shows the error.
- **Changed:** when Explorer hands files to an already open window, the sending process now waits until the whole list is written, and the window waits until the sender is done, instead of both assuming the list goes across in one piece. A test sends 5,000 file names (665 KB) between two processes.
- **Changed:** CPIO archives are extracted by [packport 0.2.0](https://github.com/puretechteam/packport/blob/main/CHANGELOG.md), which streams them to disk instead of loading them into memory.
- **Changed:** the ready-to-run app is no longer kept in the repository's `app` folder (369 MB per build, in every clone). Download it as a zip from [Releases](https://github.com/puretechteam/ConvertAll/releases/latest); `packaging/release.py` builds the zip.
- **Changed:** meshport and packport are pinned to their `v0.2.0` tags, and the libraries ConvertAll imports directly (Beautiful Soup, NumPy, backports.zstd before Python 3.14) are listed as dependencies instead of arriving by chance through other packages.
- **Changed:** the window starts a little faster: the download code for Ghostscript loads only when Ghostscript is being installed. Ghostscript downloads are also only accepted from Artifex's own GitHub releases.
- **Added:** GitHub Actions run the tests and `ruff check` on every push and pull request, plus `CONTRIBUTING.md` and `SECURITY.md`. The code passes ruff 0.16's default rules.

## 2026-10-26: Extract from the right-click menu, every archive type, and 62 more formats (1.1.0)

ConvertAll now reads 245 formats (was 183) and writes 150 (was 116).

- **Added: "Extract with ConvertAll"** in Explorer's right-click menu on archives. It unpacks straight away, with progress, then "Saved …" and *Show in folder*. Select several archives and they're extracted as one batch. Other files and folders still get "Convert with ConvertAll". An existing right-click menu updates itself the first time the new version opens.
- **Added: RAR and CBR output**, written by [packport](https://github.com/puretechteam/packport), a new pure-Python library (the way meshport replaced Blender for FBX). They're RAR 4 *stored* archives, which every reader opens, including old comic apps. If WinRAR is installed, ConvertAll uses it instead for real compression. packport also writes Unix `.Z` and CPIO.
- **Added: every common archive and compression type.**
  - New outputs: rar, tar.lz4, lz4, br (Brotli), lzma, z, cpio, iso (with Joliet and Rock Ridge, so long and non-English names survive) and wim.
  - New inputs: disk images (vmdk, vdi, qcow2, img, squashfs, udf, apfs, hfs), macOS installers (xar, pkg), Windows patches (msp), Unix ar, zipx, and split archives (.001, .r00).
  - Zip-based packages each show under their own name and extract like a zip: jar, war, ear, apk, aab, ipa, xpi, crx, vsix, nupkg, whl, appx and msix.
- **Added: new formats.**
  - **Images:** any picture → **SVG**, traced into real vector shapes; PSD, CUR, XPM and EPS outputs; EPS and PostScript inputs; gzipped SVG (.svgz).
  - **Audio and video:** M4R iPhone ringtones; DSD audio (dsf, dff) and 3G2 inputs.
  - **Subtitles:** YouTube SBV, MicroDVD SUB, TTML/DFXP and SAMI. ASS/SSA no longer need FFmpeg.
  - **Documents:**
    - LaTeX, reStructuredText, Org, AsciiDoc and MediaWiki ↔ Markdown, HTML, Word, OpenDocument and EPUB, through Pandoc;
    - DjVu → PDF and text, through DjVuLibre;
    - Hangul (HWP) and dBASE (DBF) inputs;
    - Jupyter notebooks → Markdown/HTML, including saved outputs and plots;
    - saved web pages (MHT/MHTML) → HTML/PDF with their pictures inlined;
    - CHM help files → EPUB/PDF/MOBI.
  - **New kind, Email:** EML and Outlook MSG → PDF, HTML or text, with headers, inline pictures and the list of attachments.
  - **New kind, Maps:** GPX, KML, KMZ and GeoJSON to each other, and → CSV.
  - **Contacts and calendars:** vCard and iCalendar ↔ CSV/JSON (and on to Excel). Google and Outlook CSV exports are understood.
  - **Fonts:** TTF ↔ OTF (TrueType and CFF outlines converted), and TTC collections split into their fonts.
  - **3D:** 3DS read and write, through meshport 0.2.
  - **CAD:** SVG and PDF vector drawings → DXF, for laser cutters.
  - **Data:** SQLite as an output.
- **Added: three engines, each installed from the window like the others:**
  - **Pandoc** and **DjVuLibre**, both through winget;
  - **Ghostscript**, which winget doesn't carry. ConvertAll downloads Artifex's official release, checks its published SHA-256 and unpacks it into its own folder. There's no installer to run and no admin prompt.
- **Changed:** files with no extension are also recognised by their content for EPS/PS, DjVu, vCard, iCalendar, GPX, KML, TTML and the new archive types.

## 2026-10-26: A new way to choose the format

- **Changed:** the long dropdown list of formats is replaced by a panel:
  - a **search box** that filters as you type (by extension or full name, so "bitmap" finds BMP), where Enter picks the first match;
  - a **Suggested** row with the most common choice, or what you picked last time;
  - each **kind of file** as a heading over a **grid of format tags**, with the current choice highlighted;
  - formats that need a one-time engine install shown **dashed**, with a short explanation underneath; hover a tag for the details;
  - **keyboard support**: arrow keys move through the grid, Enter picks, Esc closes, and typing anywhere goes to the search box.
- **Changed:** the button shows the chosen format in bold with its full name beside it (for example **OBJ** Wavefront OBJ).
- **Added:** screenshots of the window and the format panel at the top of the README.

## 2026-10-25: Faster startup, sturdier 3D parsing

- **Faster:** every conversion starts about a third quicker. Heavy libraries (the PDF engine, 7z, HEIC, fonts, YAML/TOML) now load only when a conversion needs them, not on every run.

  | Conversion (app) | Before | After |
  |---|---|---|
  | JSON → YAML, tiny file | 0.40 s | 0.25 s |
  | PNG → JPG | 0.37 s | 0.25 s |
  | FBX → GLB, car model | 0.44 s | 0.31 s |

  In a pip install, where newer PyMuPDF versions also load a layout model, loading the converters went from about 1.9 s to 0.1 s.
- **Fixed:** damaged or deliberately malformed FBX and glTF files now always give a "this file is damaged" message instead of an internal error. A tiny file can no longer claim gigabytes of memory by inflating a compressed array. This is checked by fuzz tests in meshport.
- **Checked:** no secrets or personal paths anywhere in the source, the git history or the shipped app.

## 2026-10-25: STL and 3MF stand upright

- **Changed:** STL and 3MF are written Z-up, as 3D-printing slicers expect, and read as Z-up. Before, they came out Y-up like the other 3D formats, so a model could lie on its side in a slicer.
  - STL ↔ 3MF isn't rotated.
  - STL → GLB comes out upright.
  - FBX → STL now matches what the Blender-based version produced.

## 2026-10-25: FBX without Blender

- **Added:** [meshport](https://github.com/puretechteam/meshport), a new pure-Python library for FBX and glTF, published as its own repo. ConvertAll converts FBX with it, so FBX no longer needs Blender. Blender is still used for `.blend`, USD and Alembic.
- **Smaller:** FBX support adds 74 KB to the app. Before, it needed Blender, a 963 MB install.
- **Faster:** every conversion measured got faster, by 1.6× to 4.9× (full app runs, best of 3):

  | FBX file | → GLB | → STL | → OBJ | → 3MF |
  |---|---|---|---|---|
  | Car, 90 KB | 2.28 → 0.46 s | 2.04 → 0.74 s | 2.07 → 0.44 s | 2.64 → 0.76 s |
  | Material ball, 1.5 MB | 2.35 → 0.49 s | 2.08 → 0.79 s | 2.12 → 0.63 s | 2.83 → 0.92 s |
  | Nature scene, 7.8 MB | 4.04 → 1.22 s | 2.59 → 1.64 s | 2.68 → 1.52 s | 6.68 → 2.73 s |

- **Added:** ASCII FBX and FBX 6 files convert. Blender couldn't open them.
- **Fixed:** models that use FBX geometric rotation came out wrong (for example, a ball on a stand ended up sideways with the stand upside down). They now match what Unity and Autodesk's FBX SDK show.
- **Added:** FBX textures are found even when the file points at the original artist's PC. ConvertAll looks next to the model and in `Textures` folders up to two levels above it. In testing this raised the share of textures found from 24% to 74%; the rest don't exist on disk.
- **Faster:** FBX → OBJ is written directly. STL skips merging textures it can't store, which took seconds on scenes with hundreds of parts.
- **Changed:** rigged or animated FBX files convert as static models in their rest pose. Blender carried the skeleton and animation into GLB. FBX files with no model in them (animation clips) now give a clear error.

## 2026-10-25: Ready-to-run app in the repo

- **Added:** the built app is in `app/`. Download the repo and run `app\ConvertAll.exe`; nothing to install. The README explains that `app` is all you need.

## 2026-10-25: ConvertAll 1.0, first public release

- **Converts** images, audio, video, subtitles, documents, spreadsheets, presentations, drawings, PDFs, comics, ebooks, 3D models, CAD, DICOM, data files and fonts to each other. It also compresses or extracts archives. It chains steps when there's no direct route (docx → pdf → png). See the formats table in the README.
- **Added:** when you drop a file in, the most common conversion for it is already picked (JPG → PNG, MP4 → MP3, DOCX → PDF, ...). After that, ConvertAll remembers your choice per file type. `convertall FILE --list` shows the most common choice too.
- **Fixed:** comics wouldn't convert to PDF.
  - CBZ, CBR, CB7 and CBT → PDF works, with pages in reading order and JPEG/PNG pages kept as they are, not re-compressed.
  - A comic with the wrong extension (a "cbr" that's really a zip) is detected by its content.
  - PDF → CBZ extracts page images without loss.
  - A folder of images → PDF or CBZ.
- **Added formats:**
  - **Subtitles:** SRT, VTT, ASS, SSA, and pulling the subtitle track out of a video.
  - **Drawings:** Visio, Publisher, CorelDRAW, ODG.
  - **Office:** macro-enabled and template files.
  - **Images:** EMF/WMF, AI, SGI, XBM, CUR, XPM, and PDF → SVG.
  - **Audio:** M4B, WavPack, CAF, MP2, AU, APE.
  - **Video:** VOB, ASF, F4V, MXF, RealMedia.
  - **Data:** JSONL, plist, SQLite.
  - **Archives:** tar.zst and zst.
  - **Video → animated WebP.**
- **Fixed**, found by converting every format to every format it can reach (4,262 conversions):
  - **ICO:** images smaller than 16 px.
  - **INI:** tables now become numbered sections. Key case is kept, and files without a section header can be read.
  - **WavPack:** MP3 input.
  - **MP2:** low-sample-rate input.
  - **GIF:** no longer offers nonsense routes like GIF → video → audio.
  - **CSV → XLSX:** numbers become real numbers, and leading zeros (zip codes, IDs) are kept as text.
  - **Temporary folders:** cleaned up even when Windows still has a file open.
- **Licensed** under MIT.
