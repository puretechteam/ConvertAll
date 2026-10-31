# Security

ConvertAll opens files people download from anywhere, so a file that makes it read, write or run something it shouldn't is a security bug. Examples: a file that writes outside the output folder when extracted, pulls other files from the computer into its output, or makes ConvertAll contact a server.

## What ConvertAll does about it

- Archives extract only inside their folder: no escaping names, links or device files, nothing overwritten, and a disk-space budget against archive bombs.
- A file may pull in pictures only from its own folder or one level up. Pandoc runs sandboxed, FFmpeg reads local files only, and ImageMagick reads only the format ConvertAll planned, with its script and URL readers off.
- Engines are found on PATH or by full path, never in the current folder.
- Compressed pictures and maps (`.svgz`, `.kmz`) are refused past 512 MB unpacked.
- The open window takes files only from the same Windows account.

`tests/test_hardening.py` and `tests/test_archive_safety.py` build hostile files in code and check each of these.

## Reporting

Please don't open a public issue. Use **Security → Report a vulnerability** on this repository's GitHub page, which only the maintainers can see. Include the file that triggers it, if you can, and what it makes ConvertAll do.

You'll get a reply within a week. Fixes ship in a new release, and the changelog credits you unless you'd rather it didn't.

## Supported versions

Only the latest release gets fixes.

The engines ConvertAll can call (FFmpeg, LibreOffice, ImageMagick, 7-Zip, Pandoc, DjVuLibre, Ghostscript) are separate programs. Report problems in them to their own projects.
