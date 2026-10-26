# Security

ConvertAll opens files people download from anywhere, so a file that makes it read, write or run something it shouldn't is a security bug. Examples: a file that writes outside the output folder when extracted, pulls other files from the computer into its output, or makes ConvertAll contact a server.

## Reporting

Please don't open a public issue. Use **Security → Report a vulnerability** on this repository's GitHub page, which only the maintainers can see. Include the file that triggers it, if you can, and what it makes ConvertAll do.

You'll get a reply within a week. Fixes ship in a new release, and the changelog credits you unless you'd rather it didn't.

## Supported versions

Only the latest release gets fixes.

The engines ConvertAll can call (FFmpeg, LibreOffice, Calibre, ImageMagick, Blender, 7-Zip, Pandoc, DjVuLibre, Ghostscript) are separate programs. Report problems in them to their own projects.
