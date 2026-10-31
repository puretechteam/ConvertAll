"""Bake the 3D viewer's shaders: convertall/assets/shaders/*.vert|frag -> *.qsb.

Run after editing a shader:  python packaging/bake_shaders.py
The .qsb files are committed, so building the app doesn't need this step. Each one holds the
shader for every backend Qt may pick: Direct3D 11 (HLSL), OpenGL (GLSL), Vulkan (SPIR-V), Metal.
"""

import subprocess
import sys
from pathlib import Path

import PySide6

QSB = Path(PySide6.__file__).parent / ("qsb.exe" if sys.platform == "win32" else "qsb")
SHADERS = Path(__file__).resolve().parent.parent / "convertall" / "assets" / "shaders"


def main() -> int:
    for src in sorted([*SHADERS.glob("*.vert"), *SHADERS.glob("*.frag")]):
        out = src.with_name(src.name + ".qsb")
        subprocess.run([str(QSB), "--glsl", "100 es,120,150", "--hlsl", "50", "--msl", "12",
                        "-o", str(out), str(src)], check=True)
        print(f"{src.name} -> {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
