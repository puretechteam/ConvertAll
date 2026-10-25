# ConvertAll

Convert, compress or extract any file. Drop it in, pick a format, done.

## Just want the app?

Download the repo (**Code → Download ZIP**), unzip it, and run **`app\ConvertAll.exe`**. Nothing to install.

The `app` folder is all you need. You can delete everything else (the source code, tests and packaging files are only for developers) and move `app` wherever you like. Keep `ConvertAll.exe` and its `_internal` folder together: the exe won't start without it.

## Using it

- **Window:** `ConvertAll.exe`. Drop files or folders on it, choose a format (the most common conversion for that file is already picked, and next time it remembers yours), click **Convert**. Archives also get **Extract here**. Output lands next to the original and never overwrites (`photo (1).png`).
- **Terminal:** `convertall-cli.exe` (or `convertall` when installed with pip).
- **Right-click:** in the window, go to ⋯ → *Add to right-click menu* to get "Convert with ConvertAll" in Explorer (Windows 11: under *Show more options*).

## What it handles

| Kind | Formats | Engine |
|---|---|---|
| Images | png jpg webp gif bmp tiff ico heic avif jp2 tga qoi dds icns pcx ppm sgi xbm, plus psd cur xpm in; svg and pdf-compatible ai → images/pdf; pdf → svg | built in |
| Windows metafiles | emf wmf → png/svg/pdf | LibreOffice |
| Camera RAW, GIMP, HDR, JPEG XL | dng cr2 cr3 nef arw orf rw2 raf xcf exr hdr jxl | ImageMagick |
| Audio | mp3 wav flac ogg opus m4a m4b aac wma aiff ac3 amr mka wv caf mp2 au, plus ape in | FFmpeg |
| Video | mp4 mkv webm mov avi wmv flv f4v asf vob m4v mpg ts 3gp ogv, plus mxf rm rmvb in; video → gif, animated webp or audio | FFmpeg |
| Subtitles | srt ↔ vtt; ass ssa; pull the subtitle track out of a video | built in (FFmpeg for ass/ssa and videos) |
| Office | docx doc odt rtf pages wps (+ docm dotx dot), xlsx xls ods numbers csv (+ xlsm xlsb xltx), pptx ppt odp key (+ pptm ppsx pps potx) → pdf and each other; pdf → docx; html → docx/odt/rtf | LibreOffice |
| Drawings | vsdx vsd (Visio), pub (Publisher), odg, cdr (CorelDRAW) → pdf/png/svg | LibreOffice |
| PDF | pdf → images (one folder per multi-page doc), pdf → txt, images/txt/html/md → pdf, xps → pdf | built in |
| Markdown & HTML | md → html, html → md, docx → html/md (md ↔ docx chains through html) | built in (+ LibreOffice for → docx) |
| Comics | cbz cbr cb7 cbt → pdf (pages kept as they are, in reading order), between each other, and pdf → cbz/cb7/cbt; a folder of images → pdf or cbz. Renamed comics (a "cbr" that's really a zip) are detected by content | built in (7-Zip for real RAR comics) |
| Ebooks | epub mobi azw3 azw fb2 lit pdb lrf, and html/docx/odt/rtf/txt → epub/mobi/azw3; comics → epub/mobi/azw3 | Calibre (epub/mobi/fb2 → pdf is built in) |
| 3D models | stl obj ply off glb gltf 3mf dae fbx, all to each other (parts, colors and textures kept where the format can hold them). FBX: binary and ASCII, 2006 onward; textures are found even when the file points at another PC | built in ([meshport](https://github.com/puretechteam/meshport) for FBX) |
| 3D (DCC) | blend usd usdz abc ↔ the formats above | Blender |
| CAD | step/stp, iges/igs, brep → watertight stl (and from there any mesh format); dxf → svg/pdf/png | built in |
| Medical | DICOM (.dcm or no extension) → png/jpg/tiff/… with the scanner's display window applied; multi-frame → folder, gif or multi-page tiff/pdf; header → json | built in |
| Data | json jsonl yaml toml xml ini plist csv tsv xlsx, all to each other; sqlite databases → any of them | built in |
| Fonts | ttf otf ↔ woff woff2 | built in |
| Archives | create zip 7z tar tar.gz tar.bz2 tar.xz tar.zst gz bz2 xz zst from **any file or folder**; extract all of those plus rar iso cab arj lzh dmg wim cpio rpm deb msi vhd; repack any archive into another | built in, 7-Zip for rar etc. |

When there's no direct conversion, ConvertAll chains steps automatically, for example docx → pdf → png, fbx → glb → 3mf, or step → stl → glb. If a step needs an engine that's missing, ConvertAll offers a one-time install with `winget`. Check engine status with ⋯ → *Engines…* or `convertall engines`.

Some outputs come back as a **folder**: multi-page PDFs and multi-frame DICOMs saved as single-image formats, plus OBJ and USD models that have textures or materials (stored as side files).

ConvertAll can read but not create RAR/CBR (no free RAR encoder exists); CBR → CBZ is the usual fix.

**Not supported:** DWG (closed format), and DICOMs compressed with *JPEG Lossless* (Process 14). Decoding that would need a 45–140 MB codec library.

## Command line

```
convertall photo.heic --to png          # writes photo.png next to it
convertall *.wav --to mp3 -o out        # batch into a folder
convertall report.docx --list           # what can this become? (and the most common choice)
convertall issue1.cbr --to pdf          # comic -> PDF
convertall project --to 7z              # compress a folder
convertall archive.rar --extract        # unpack
convertall bracket.step --to stl        # CAD -> printable mesh
convertall engines [--install blender]
```

`-y` installs missing engines without asking.

## Development

```
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m convertall              # window
.venv\Scripts\python -m pytest                  # tests (engine tests skip if the engine is missing)
.venv\Scripts\python -m pytest tests\test_e2e.py --e2e   # every format -> every target it can reach (slow)
.venv\Scripts\pyinstaller --noconfirm ConvertAll.spec   # -> dist\ConvertAll\ (copy it over app\ to update the shipped app)
python packaging\make_icon.py                   # regenerate the icon
```

Adding a format means writing one function in `convertall/converters/` with
`@converter(inputs={...}, outputs={...}, engine=...)`. Routing, the CLI and the window pick it up automatically.

## License

MIT, see [LICENSE](LICENSE). ConvertAll calls FFmpeg, LibreOffice, Calibre, ImageMagick, Blender and 7-Zip as separate programs when they are installed; each keeps its own license.
