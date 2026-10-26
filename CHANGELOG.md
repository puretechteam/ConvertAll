# Changelog

Newest first. Each entry is dated by when it landed.

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
