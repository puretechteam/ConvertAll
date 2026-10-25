# PyInstaller build: pyinstaller ConvertAll.spec
# Produces dist/ConvertAll/ with ConvertAll.exe (window) and convertall-cli.exe (terminal),
# sharing one set of libraries.
import glob
import os
import re
import sysconfig

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ICON = "convertall/assets/icon.ico"
SOURCES = ["**/*.c", "**/*.h", "**/*.pyx", "**/*.pxd", "**/*.pyi"]  # build leftovers, never loaded
DATAS = [("convertall/assets", "convertall/assets")]
for pkg in ("trimesh", "ezdxf"):  # json schemas, templates, fonts loaded at runtime
    DATAS += collect_data_files(pkg, excludes=SOURCES)
DATAS += collect_data_files("pydicom", excludes=["**/test_files/**", "**/charset_files/**"])

# gmsh's pip wheel puts its DLL outside site-packages (<venv>/Lib); gmsh.py looks next to itself
GMSH_DLL = glob.glob(os.path.join(os.path.dirname(sysconfig.get_paths()["purelib"]), "gmsh-*.dll"))
BINARIES = [(dll, ".") for dll in GMSH_DLL]

MODULES = collect_submodules("convertall") + collect_submodules("meshport") + ["pydicom.pixels.decoders", "jpeg_ls"]
# PyMuPDF 2 bundles an optional AI layout analyzer (onnxruntime + model files); ConvertAll doesn't
# use it and PyMuPDF imports it inside try/except ImportError.
EXCLUDES = ["tkinter", "unittest", "pydoc_data", "test", "pymupdf.layout", "pymupdf4llm",
            "pymupdf_layout", "onnxruntime", "matplotlib", "IPython", "pytest"]
# scipy parts outside the import closure of everything trimesh can reach (measured, not guessed:
# trimesh uses spatial/sparse/ndimage/interpolate/special/optimize/cluster, which pull in
# linalg/fft/constants — those all stay).
EXCLUDES += [f"scipy.{m}" for m in ("stats", "signal", "io", "integrate", "odr", "fftpack",
                                    "misc", "datasets", "differentiate")]

# The window only needs QtCore/QtGui/QtWidgets/QtNetwork and the qwindows platform plugin.
# PySide6's hook also ships plugins that drag in Quick/QML (virtual keyboard), PDF & SVG
# readers, TLS backends with their own OpenSSL, and a software OpenGL renderer.
QT_DROP = re.compile(r"""(?ix)
    PySide6[\\/](
        opengl32sw\.dll
      | Qt6(Qml\w*|Quick\w*|Pdf|Svg|VirtualKeyboard|OpenGL)\.dll
      | translations[\\/]
      | plugins[\\/](tls|networkinformation|platforminputcontexts|generic|iconengines|styles)[\\/]
      | plugins[\\/]platforms[\\/]q(direct2d|minimal|offscreen)\.dll
      | plugins[\\/]imageformats[\\/]q(pdf|svg)\.dll
    )
    | ^lib(ssl|crypto)-3-x64\.dll$        # OpenSSL copy used only by Qt's TLS plugin
""")


def slim(toc):
    return [entry for entry in toc if not QT_DROP.search(entry[0])]


gui = Analysis(["packaging/gui_entry.py"], pathex=["."], hiddenimports=MODULES, datas=DATAS,
               binaries=BINARIES, excludes=EXCLUDES)
gui.binaries, gui.datas = slim(gui.binaries), slim(gui.datas)
cli = Analysis(["packaging/cli_entry.py"], pathex=["."],
               hiddenimports=[m for m in MODULES if m != "convertall.gui"], datas=DATAS,
               binaries=BINARIES, excludes=EXCLUDES + ["PySide6", "convertall.gui"])

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="ConvertAll",
              console=False, icon=ICON, upx=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="convertall-cli",
              console=True, icon=ICON, upx=False)

COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas,
        name="ConvertAll", upx=False)
