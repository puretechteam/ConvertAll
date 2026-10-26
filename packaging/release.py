"""Build the app and zip it for a GitHub release: dist/ConvertAll-<version>-windows.zip.

    .venv\\Scripts\\python packaging\\release.py
    gh release create v<version> dist\\ConvertAll-<version>-windows.zip --notes-file <notes>
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from convertall import __version__


def main() -> int:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "ConvertAll.spec"], cwd=ROOT, check=True)
    base = ROOT / "dist" / f"ConvertAll-{__version__}-windows"
    # the zip holds one ConvertAll folder with ConvertAll.exe, convertall-cli.exe and _internal
    zip_path = shutil.make_archive(str(base), "zip", root_dir=ROOT / "dist", base_dir="ConvertAll")
    print(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
