# Changelog

Newest first. Each entry is dated by when it landed.

## Unreleased

- **Added: Cancel.** While a conversion runs, the *Convert* button becomes *Cancel*. It stops the engine at once (FFmpeg, LibreOffice and the rest, with anything they started; measured within 1 s), writes nothing half-made, and keeps the files already done (*Stopped*, with *1 saved, 2 not converted* under it).
- **Fixed: closing the window during a conversion.** ConvertAll used to quit with an error (exit code 127 in 10 of 10 tries) and leave the engine running in the background. Now it asks *Stop converting and close?*, stops the engine and closes cleanly: exit code 0 in 10 of 10, no engine left running, no temporary folder left behind.
- **Changed: converting with the check is faster.** The original is read once, for the check and the conversion, instead of twice. A 24-megapixel TIFF to PNG takes 3.91 s instead of 4.35 s (10% faster), MOBI to EPUB 0.30 s instead of 0.41 s (26%), FB2 to EPUB and a rigged GLB to STL about 8% faster. The results are the same.
- **Fixed: text files saved as "Unicode" in Notepad (UTF-16).** Subtitles (SRT, VTT, ASS and the rest) came out garbled; GeoJSON maps and Jupyter notebooks failed to open, also when saved in the old Windows encoding. All of them are read correctly now.
- **Fixed: animations made into AVIF or WebP** (a video or GIF turned into an animated picture) got a false warning, *Length: 2.1 s → 0*. The check now reads how long those animations really run.
- **Fixed: PDF to Markdown, LaTeX, reStructuredText, Org, AsciiDoc and MediaWiki came out empty.** LibreOffice opens a PDF as positioned text boxes, which Pandoc skipped on that route. These now go through Word (DOCX), where Pandoc reads them, and keep the text of every page.
- **Fixed: very small pictures (under 18 pixels a side) made into OGV** gave a video no player could open. They are now enlarged to 18 pixels, keeping their shape, and the report says so.
- **Changed: a conversion waiting for LibreOffice** (while another ConvertAll window uses it) can be cancelled, and gives up after 15 minutes with a message instead of waiting forever.

## 2026-10-30: ConvertAll 1.2.0

- **Changed: Calibre is no longer needed.** Every ebook conversion is now done by [bookport](https://github.com/puretechteam/bookport), a pure-Python ebook library made for ConvertAll (3.0 MB, against Calibre's 666.5 MB install). Measured against Calibre 9.17 on the same 13 books (median per conversion):
  - **Faster and lighter:** EPUB → PDF in 1.40 s and 40 MB of memory instead of 8.91 s and 1,138 MB. EPUB → MOBI in 0.96 s instead of 1.60 s. Python's documentation CHM → EPUB in 20.5 s instead of 381.8 s.
  - **Cleaner books:** Kindle books turned into EPUB have 0 epubcheck errors, against Calibre's 7,212.
  - **Nothing lost:** words, chapter titles, pictures, metadata and covers are kept as well as or better than Calibre does it, for every output format.
  - The Calibre engine is gone from ☰ → *Engines…* and `convertall engines`. An installed Calibre is simply no longer used.
- **Added: more ebook formats.** HTMLZ, TXTZ, FictionBook in a zip (fbz), PML and PMLZ (eReader), Rocket eBook (rb), Psion TCR and Shanda Bambook (snb), read and written. LIT, LRF and Palm (pdb) can now be written too, not only read. Ebooks also go to Word, RTF, HTML and Markdown, and every ebook format reaches every other. ConvertAll now offers 12,463 conversions (11,419 before).
- **Added: page size and text size for ebooks as PDF.** Two settings in *Options*, shown when an ebook becomes a PDF: page size (phone, 6-inch e-reader, A5, A4, Letter) and text size (small, normal, large). The command line takes `--page-size` and `--text-size`.
- **Changed: ebooks to PDF and text keep more of the book.** These used to go through PyMuPDF. On 10 books with a reference text, bookport kept a median 99.99% of the words in PDF (PyMuPDF: 98.62%), with 22% smaller files. As text, the worst book kept 99.48% of its words instead of 81.73%.
- **Added: comics become fixed-layout ebooks.** CBZ, CBR, CB7 and CBT become fixed-layout EPUB, MOBI, AZW3 and the other picture-holding formats, one page per picture, with their ComicInfo title. Pages in formats readers don't take (HEIC, TIFF, AVIF) are converted to JPG or PNG.
- **Added: ebooks are checked after converting.** ConvertAll counts the words in the original and in the result, also when the book becomes a PDF, Word, RTF, HTML, Markdown or text file; a difference of more than 3% (and more than 20 words) is reported. On 3 novels, at every page and text size and in every document format (60 conversions), the counts agreed within 4 words. Counting adds about 0.8 s to a 78,500-word novel made into a PDF.
- **Copy-protected ebooks** (DRM) are refused with a clear message. ConvertAll never removes DRM.

- **Added: ConvertAll says what a conversion can't keep.** Point at a format in the list and its tooltip gives the route (*via PDF*) and, in plain words, what that route leaves out: *"JPG has no transparency: see-through areas become white"*, *"STL holds one mesh: all parts are merged into one"*, *"CSV holds one table: only the first sheet is kept"*, *"Formulas become their last saved values"*, *"GIF animations run at 12 frames a second, at most 640 pixels wide, with 256 colors and no sound"*: 41 kinds in all, written from what each step really does. 5,926 of the 11,419 routes ConvertAll offers carry at least one. After converting, the notes are about *that* file: a PNG without transparency doesn't get the transparency note, a one-page PDF doesn't get "a folder of pages". The status line shows the first; hover it for all.
- **Added: every result is checked.** After each conversion ConvertAll opens the result the way the next program would and compares what it can measure with the original: pages, frames, picture size, transparency, length, sound tracks, parts, triangles, model size, animation, skeletons, sheets, records, subtitles, glyphs, files, places. Only measured facts are reported, never a score. A difference the route said it would make (*Parts: 4 → 1* for STL) is expected; any other, or a result that doesn't open, turns the status line amber and says what didn't match. The file is always kept. On the standard test set (192 conversions, the most common one for each format) it made 263 checks with **0 false alarms**, and on every built-in conversion of pictures, 3D models, data, tables, subtitles, fonts and maps (975) 2,100 checks, also 0 once the three real problems that sweep found were fixed (below), and the test suite now fails if a check ever disagrees unexplained. It adds 26 ms a conversion on average (35.5 → 40.5 s for all 192, same machine; files over 200 MB aren't read again).
- **Added: Details after converting.** A *Details* link next to *Show in folder* opens the report: the route and the tool that did each step (with its version), the settings used, what was left out, and a table of what was checked, before and after. *Copy report* puts it on the clipboard as JSON.
- **Changed: routes keep the most.** When there's more than one way to get there, a route now costs what it loses as well as its steps, so the one that keeps more wins even when it is a step longer. 49 of the 11,419 routes changed, every one keeping more than before: old Excel .xls/.xlsb/.xlsm and OpenDocument .ods workbooks go to JSON, YAML, XML, SQLite and the rest through XLSX (every sheet) instead of CSV (the first sheet only), SQLite databases to ODS, XLS and PDF the same way, and Visio, CorelDRAW and OpenDocument drawings to EPS through PDF (still vectors) instead of PNG. GLB ↔ glTF now goes through meshport instead of trimesh, which kept the mesh but dropped animation, skeletons and blend shapes (an animated glTF → GLB had 1 animation before and 0 after; now 1).
- **Added: files named for the wrong format are converted as what they are.** A JPEG saved as `.png` (common with downloads), a PNG named `.jpg`, a PDF, WebP, HEIC, AVIF, GIF, TIFF, BMP or Photoshop file under another of those names: ConvertAll reads the start of the file and, when it clearly says another format, uses that, and the report says *"This .png file is really a JPG"*. Converting such a file to its own real format says so instead of failing with "Can't convert JPG to JPG".
- **Added: options and presets.** A collapsed **Options** card under the format shows only the settings the chosen conversion takes: quality (JPG, WebP, AVIF, HEIC), maximum size (pictures), resolution (PDF pages to pictures or comics), video quality (smaller, balanced, best), video size (360p to 2160p, never enlarging), frame rate (video, GIF, animated WebP), sound bitrate (MP3, AAC, Ogg, Opus and the other lossy formats), and mesh detail (STEP, IGES, BREP to STL). Quality is a slider. Size, resolution, frame rate and bitrate list the usual values (1920 px, 300 dpi, 30 fps, 192 kbps...) and take any other you type. Presets are one click: *Default*, *Smaller for email and web*, *Best quality*, *For phones and social*, *Ready for 3D printing*, each shown only where it changes something. Change a setting yourself and *+ Save as preset* keeps it (in `%APPDATA%\ConvertAll\presets.json`, shared with the command line). The card's header says what's on (*Default*, the preset's name, or *Max size 1920 px*). Nothing set keeps ConvertAll's usual defaults, and each setting says what that default is, with hints only where they apply (frame rate says *Original (12 for GIF)* when making a GIF, *Original* otherwise). Measured on the test files: JPG quality 40 makes a photo under 70% of the default's size, resolution 300 draws a 4 × 2 inch page at 1200 × 600 pixels, mesh detail *fine* makes over twice the triangles of *coarse*, and sound at 256 kbps is over 2.5 times the size of 64 kbps.
- **Changed: a cleaner window.** Every screen was gone over (23 of them, in light and dark mode):
  - **Nothing overlaps.** The window's height now follows what it shows. With *Options* open, it could be made 430 px tall while its contents needed 475, so the format list slid over the drop area. Opening *Options* grows the window to fit, and closing it gives the height back.
  - **The drop area shows the file:** a small picture of a photo or of a PDF's first page, anything else as a page with its extension, several files as a stack. The file's size is shown under its name.
  - **The line under the buttons** says what happened (*Saved photo.jpg*, *Couldn't convert photo.heic*), with what the route couldn't keep, or why it failed, in grey under it. It takes no room while there's nothing to say.
  - **Dropdowns, lists, sliders and tooltips match the theme**, and every control in a row has the same height. The *Details* dialog shows each file as a card, with *Same*, *Changed*, *As noted* or *Didn't match* beside each check (and numbers like 6.633, not 6.63325). *Engines* has a *Close* button and shows which tools are installed in green. The Discord link in *About* is readable in dark mode.
- **Added: command line.** `--plan` shows each file's route, what it can't keep and the settings it takes, and converts nothing. `--json` prints one JSON object per file, and nothing else, on stdout, always as UTF-8: a report after converting (route, steps, notes, checks, warnings), the plan with `--plan` (route, steps, notes, settings, what the route takes, engines it needs), and every target with `--list` (format, kind, route, engines it needs). `--preset NAME` and the settings (`--quality`, `--max-size`, `--dpi`, `--video-quality`, `--video-size`, `--fps`, `--bitrate`, `--detail`) work as in the window; `convertall presets` lists them (*Default* included, which sets nothing). Text output prints the notes and checks under each file.
- **Added: Start menu shortcut.** ☰ → *Add to Start menu* puts ConvertAll in Start, so typing "ConvertAll" there opens it; the same item removes it.
- **Changed: the right-click menu follows the app.** Before, only a newer version repointed it, so after moving or reinstalling ConvertAll the menu kept opening the old copy. Now the installed app takes the menu over whenever the menu points at another copy of the same version, and an older copy never takes it back.
- **Changed: faster.** Measured on the same PC, before and after:
  - Right-clicking more files while ConvertAll is open hands them over in 177 ms instead of 420 ms (250 ms in the installed app, counting its own start). The handing-over process no longer loads the window or the converters.
  - The window code loads in 290 ms instead of 383 ms. The converters load just after the window shows.
  - Dropping another file takes 2.5 ms instead of 51 ms, because ConvertAll looks for newly installed engines at most every 10 seconds. Before, it searched every folder on PATH for each missing engine on every drop.
  - `convertall --plan` on 100 files takes 0.35 s instead of 1.21 s. Batches reuse the route found for the first file of each kind.
- **Fixed: piped `--json` wasn't valid UTF-8.** Output sent to a file or another program used the Windows code page, so an accented file name (`café.png`) made the JSON unreadable as UTF-8, and the route arrow came out as `?`.
- **Fixed: CSV made from JSON, YAML, XML, spreadsheets and other data showed accents wrong in Excel.** It now starts with the byte-order mark Excel looks for, as contacts already did. Both now use the same writer. TSV stays without one.
- **Fixed:** `convertall engines --install` crashed with a traceback when winget was missing or an install failed; it now says why. It also no longer accepts WinRAR, which ConvertAll never offers.
- **Fixed:** when FFmpeg was installed while ConvertAll was open, sound and video results stayed unchecked until a restart.
- **Changed:** meshport, packport and bookport are pinned to their `v0.3.0`, `v0.2.1` and `v0.1.0` tags.
- **Added: a Python API.** `from convertall import convert, plan, extract, Report`; `convert(path, "jpg", report=Report(), options={...})`.
- **Fixed: photo details and color profiles were dropped.** Converting a photo threw away its EXIF (camera, date, place) and its color profile, so wide-gamut photos (an iPhone's, for one) could shift in color and photo libraries lost their dates. They're now kept for JPG, PNG, WebP, TIFF, HEIC and AVIF (the picture is turned upright first, and its rotation flag reset).
- **Fixed: a Photoshop file with layers became an animation.** Converting a layered PSD to PNG, GIF, WebP, AVIF or TIFF made an animation of the flattened picture and some of its layers (a 2-layer test file came out as 2 frames, the second one a single layer). It's now the flattened picture alone.
- **Fixed: an OBJ's objects became one part.** Converting a multi-object OBJ to GLB, glTF, 3MF, FBX, USD, Alembic or 3DS merged its objects into one mesh (trimesh reads them as one); each object is a part of its own again (the 2-object test file: 1 part before, 2 now).
- **Fixed: a database with several tables came out as one line in JSON Lines,** holding every table; it now gets the first table, one record a line, and says so. Plist output keeps tables and keys in their order instead of sorting them.
- **Fixed: a workbook with several sheets came out as one row of JSON text in CSV/TSV.** CSV and TSV hold one table, so they now get the first sheet (or a database's first table), and the conversion says so.

- **Fixed (security): extracting archives is safer.** An audit of every way ConvertAll unpacks archives (ZIP, 7z, TAR in all its compressions, CPIO, single-file compressors, and 7-Zip for RAR, ISO, RPM and the rest) found gaps, now closed. Extracting a comic or repacking an archive goes through the same checks. New rules, the same for every extractor (`convertall/safety.py`):
  - **Nothing lands outside the folder.** Names with `..` are left out. Leading slashes and drive letters are dropped, as unzip and tar do.
  - **No links.** Symbolic links, hard links that point out, junctions and device files are left out. A sweep after every extraction removes any link that slipped through, without following it. A hard link inside a TAR becomes a copy of its file.
  - **Names Windows can't take are renamed the way 7-Zip does:** `a:b` (which would have written a hidden alternate data stream) becomes `a_b`, `CON.txt` becomes `_CON.txt`, and a trailing dot or space becomes `_`. Before, these failed or wrote somewhere unexpected.
  - **Nothing is overwritten.** Two entries with the same name, or names that differ only in case (one file on Windows), used to overwrite each other silently. The second is now saved as `name (1).ext`.
  - **Archive bombs stop.** Before anything is written, the archive's declared size is checked against the free disk space (ZIP, 7z, external 7-Zip). Single-file compressors (`.gz`, `.xz`, `.zst`…), TAR streams and CPIO are counted as they unpack. An archive that holds more data than it declares is stopped.
  - **7-Zip gets the same rules.** Before extracting, ConvertAll reads 7-Zip's listing and excludes links and escaping names. 7-Zip is also told to rename clashing names instead of overwriting them. 7-Zip releases older than 25.00 can be tricked into writing through a link (CVE-2025-11001 and 11002), so ConvertAll suggests updating. Links are excluded either way. Password prompts can no longer hang a conversion.
  - **Clear messages.** Password-protected archives say so. Damaged ones say *"looks damaged"* with the reason, instead of an "unexpected error". Disk-space refusals give the sizes. No half-extracted folder is left behind.
  - Anything left out or renamed is reported: on the status line in the window (hover for every note), and after the result in `convertall --extract`.
  - `tests/test_archive_safety.py` has 30 tests that build hostile and damaged archives in code. They cover escaping names, Windows names, duplicates, case clashes, symbolic and hard links, device files, encrypted, truncated and corrupted files, and bombs, plus the CVE pattern through 7-Zip. Every test checks that nothing outside the folder changed and no link was left.
  - One limit: 7z archives read by the built-in reader (py7zr) can't extract names containing `:`. Those entries are left out and counted.
- **Fixed (security): a downloaded file can't reach other files, the network or a planted program.** A review of every engine call and built-in reader found these, now closed. `tests/test_hardening.py` builds each hostile file in code; 16 of its tests failed before these fixes and pass now.
  - **Pandoc runs sandboxed.** An include line in a reStructuredText, LaTeX, Org or AsciiDoc file (`.. include:: C:/Users/you/notes.txt`) used to copy that file into the result. Pandoc now reads only the file it's given. Pictures still come along: ConvertAll embeds the ones in the file's own folder or one level up (never absolute, network or further-out paths), so Word, OpenDocument, EPUB and HTML results keep them as before.
  - **No programs from the current folder.** Windows looks for a program in the current folder before PATH, so a Downloads folder holding a file named `ffmpeg.exe` could have been run. Engines, winget and Explorer are now found on PATH or by full path only.
  - **FFmpeg reads local files only.** A playlist or concat file can no longer make FFmpeg (or the check after converting) fetch a URL.
  - **ImageMagick reads only the format ConvertAll planned.** The input is handed over under a plain name with its format named outright (`XCF:in.xcf`), and a policy turns off ImageMagick's script, text and URL readers. A file named for the wrong format (a PNG saved as `.jpg`) still converts.
  - **Size limits on compressed pictures and maps.** An `.svgz` or `.kmz` that unpacks to more than 512 MB is refused with a message instead of filling memory.
  - **Only you can hand files to the open window.** The local connection the right-click menu uses is now limited to your Windows account.
- **Fixed:** checking a sound or video result flashed a console window, and could misread file names with accents. FFprobe now runs hidden and in UTF-8.
- **Fixed:** right-clicking files while ConvertAll was starting or closing could open a second window. A launch now waits up to 15 seconds for the open window, then says it isn't answering instead of opening another.
- **Fixed: saved presets.** Saving or deleting a preset deleted any hand-edited preset with a value this version doesn't take; those are now kept as they are, and a `presets.json` that isn't valid JSON is set aside as `presets.unreadable.json` instead of written over. Preset names ignore case, so saving "web" replaces "Web" instead of making a second one, and "default" can't hide the built-in *Default*. The preset lit in *Options* is judged only by the settings the conversion takes, so a JPG at quality 75 and 1920 px lights *Smaller for email and web*.
- **Fixed:** a comic with both `07.jpg` and `07.webp` lost a page when it became an ebook (the converted WebP was written over the JPG). Pages left out of a comic (unsafe names) are now reported, as they are for PDF.
- **Fixed:** an ebook named for the wrong format is read as what it really is, the way the route was planned.
- **Fixed:** `--max-size 1920px` (no space) was refused; any spacing and case of the unit now works.
- **Fixed:** installing an engine from ☰ → *Engines…* now refreshes the format list at once, instead of after the next drop.
- **Fixed:** two document conversions at once in separate ConvertAll processes (the window and the command line, or a script running several) failed every other time, because both started LibreOffice on the same profile. The second now waits for the first: 0 of 28 failed with two and four at once, against 8 of 16 before.
- **Changed:** big counts in *Details* and the command line's report read 30,682 instead of 30682 (picture sizes like 1920 stay as they are).
- **Fixed: messages instead of tracebacks** for a GeoJSON file laid out in an unexpected way, a damaged archive in `--extract`, a locked file in `--plan`, `convertall view` with no ConvertAll.exe beside it, and a Start menu shortcut PowerShell couldn't write without saying why. The install question goes to stderr, so `--json` output stays JSON.
- **Changed: faster settings.** Dragging the quality slider took 3.6 ms of ConvertAll's own work a step and now takes 1.1 ms (13.8 → 11.3 ms with drawing): presets are read again only when `presets.json` changes, and the format list's notes follow once the slider rests. Checking a 12-megapixel picture for transparency takes 53 ms instead of 63 ms (38 instead of 51 for grey with transparency) and 94 MB of memory at most instead of 143 MB.
- **Changed: Blender is no longer needed.** `.blend`, USD (usd, usda, usdc, usdz) and Alembic files are now read and written by [meshport](https://github.com/puretechteam/meshport) (`.blend` is read only, as before), the same pure-Python library that took over FBX and 3DS. Blender was a 1 GB install, and the last engine any 3D format needed.
  - **Smaller:** the three formats add 266 KB to the app (388.83 → 389.10 MB unpacked, viewer included before and after). Blender was a 1 GB install.
  - **Faster:** every conversion measured got faster, by 1.8 to 5.5 times (full app runs on one PC, best of 3): a 3-object .blend → GLB 2.13 → 0.43 s, a 660,000-triangle .blend → GLB 2.41 → 0.93 s, USDZ → 3MF 3.33 → 1.31 s, Alembic → STL 2.01 → 1.13 s, GLB → USDZ 2.31 → 0.44 s, GLB → Alembic 2.23 → 0.40 s.
  - **Same results:** meshport reads Blender's own USD, Alembic and .blend files to the same geometry as Blender's conversion did (19 of 19 files), reads 13 tricky USD files the same way Pixar's own USD library does, and the USD files it writes pass all of Pixar's validators. The files it writes are no bigger than Blender's: USDZ 672 KB vs 759 KB, Alembic 909 KB vs 1.03 MB.
  - **.blend files now come out as Blender shows them:** the modifiers that are on in Blender's viewport are applied (Triangulate, Weld, Mirror, Array, Solidify and Subdivision Surface; others are skipped), and curve, text and metaball objects become meshes. The old conversion through Blender didn't apply modifiers. Text in Blender's built-in font uses a similar installed font, so its letters come out a few percent wider or narrower.
  - **Older .blend files checked:** files saved by Blender 2.83, 2.93, 3.3 and 3.5 come out the same as each of those versions converts them. This check found that every mesh with a UV map from Blender 2.8 to 3.4 was refused as damaged; that is fixed.
  - **Still to come:** other modifiers (Bevel, Boolean, Geometry Nodes, ...), bevel and taper objects on curves, and NURBS surfaces.
  - The Blender engine is gone from ☰ → *Engines…* and `convertall engines`. An installed Blender is simply no longer used.
- **Added: animation survives conversion.** Converting between FBX, GLB/glTF, USD (usd, usda, usdc, usdz) and Alembic now keeps the objects' movement (position, rotation and scale), and animated 3DS and Blender files bring theirs along too (to any of those). Before, the result was a still model. FBX and glTF keep every animation take; USD and Alembic have one timeline, so they keep the first. Formats without animation (OBJ, STL, 3MF, ...) keep the first frame.
- **Added: animated models play in the viewer.** Open an animated model in the big viewer (FBX, glTF, USD, Alembic, 3DS or Blender) and it plays: moving parts, rigged characters bending, blend shapes changing. Play or pause it (the button or the space bar), drag along the timeline to any moment, and pick which take to play when the file has several (takes that move different things, as Blender exports each object's action, play together by default). The view frames the model and sets its ground grid for the whole animation, not just its first frame. The preview in the drop area plays it too (and says it's animated under it), pausing while the big viewer has it open. A model too heavy to pose 60 times a second plays fewer frames a second instead of slowing ConvertAll down, and a preview nobody can see costs nothing. Shading follows blend shapes as they change.
- **Added: rigged characters and face shapes survive conversion.** A character's skeleton and how its mesh bends with it (skinning), and its blend shapes (shape keys, morph targets) with their animated weights, now come across between FBX, GLB/glTF and USD, and from Blender files. Before, a rigged character came out stiff in its rest pose. Checked against Blender and Pixar's own USD library: they bend ConvertAll's files exactly as ConvertAll bends theirs. Formats without skeletons (3DS, OBJ, STL, 3MF, PLY, ...) get the mesh where its skeleton holds it, its shapes applied, and Alembic gets its motion as a point cache. Checked with Khronos' rigged sample characters too (CesiumMan, BrainStem, Fox and others): Blender, Pixar's USD library and Autodesk's FBX library all bend ConvertAll's FBX and USD of them as ConvertAll does. Blend shapes with in-between shapes (FBX, USD) and Blender's bone options (inherit rotation, inherit scale) come across as well.
- **Fixed: some FBX models came out turned wrongly.** An FBX model's pre- and post-rotation only count when the file turns them on (most exporters that use them do). ConvertAll used to apply them always; now it follows Autodesk's own FBX library, as Blender does.
- **Added: a 3D viewer.** Drop one 3D model or CAD part on the window and it shows in the drop area, live: drag to turn it, right-drag to move it, scroll to zoom toward the cursor, arrow keys and +/- work too. The expand button in its corner, or a double-click, opens a big viewer window with a wireframe view and a summary (parts, triangles, materials, and the size in meters, or in the file's own units for STL, OBJ, 3MF and CAD files).
  - It opens everything ConvertAll can turn into a 3D model: glb gltf fbx 3ds usd usdz abc blend stl obj ply off 3mf dae, and CAD parts (step iges brep). Textures, vertex colors, see-through materials and mirrored parts show as they should. Models without normals get smooth shading on curved surfaces and crisp edges where faces meet at over 40°.
  - **View with ConvertAll** in Explorer's right-click menu (on 3D models and CAD parts) opens just the viewer, and `convertall view model.fbx` does the same from a terminal.
  - It draws with Qt's own GPU layer (Direct3D 11 on Windows), so it needs no extra libraries: the built app grew by 74 KB (388.76 → 388.83 MB unpacked).
- **Added: a Discord for help and chat** ([invite](https://discord.gg/dRMRGCG9Fk)), in the window's menu (☰ → *Help and chat on Discord*), the About box and the README.
- **Changed:** the menu button is now a clear ☰ that lights up on hover and while its menu is open, instead of three faint dots; the viewer's expand button is drawn the same way. Both follow light and dark mode and look the same on every PC (the old ones were font characters, which Windows showed as a small colored emoji).
- **Fixed:** previewing a CAD part while converting another one could run gmsh on two threads at once; they now take turns.
- **Changed:** ConvertAll needs PySide6 6.7 or newer (for `QRhiWidget`).

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
- **Changed:** the README's two old screenshots are replaced by one of 1.1.0: a phone video dropped on the window, with 87 formats to pick from.

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
