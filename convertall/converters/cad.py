"""CAD: STEP/IGES/BREP solids -> STL mesh via gmsh (OpenCASCADE); DXF drawings -> SVG/PDF/PNG via ezdxf."""

import shutil
from pathlib import Path

from ..errors import ConversionError
from ..registry import converter


@converter(inputs={"step", "iges", "brep"}, outputs={"stl"})
def cad_to_stl(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import gmsh
    # gmsh's file reader can trip over non-ASCII paths on Windows, so work on a plain-named copy
    local = dst.parent / f"input.{src_fmt}"
    shutil.copyfile(src, local)
    gmsh.initialize(interruptible=False)  # no signal handlers: we may be on a worker thread
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        # IGES (and some STEP exports) store loose faces: sew them into closed solids
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
        gmsh.option.setNumber("Geometry.OCCMakeSolids", 1)
        gmsh.model.add("part")
        gmsh.model.occ.importShapes(str(local))
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            # surfaces only (typical IGES): make neighbouring faces share edges -> watertight mesh.
            # Not done for solids, where it would weld touching parts of an assembly together.
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(2):
            raise ConversionError("No surfaces found in this CAD file")
        x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(-1, -1)
        diag = ((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2) ** 0.5 or 1.0
        # fine enough for 3D printing: follow curvature, cap triangle size relative to the part
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
        gmsh.option.setNumber("Mesh.MeshSizeMax", diag / 50)
        gmsh.option.setNumber("Mesh.MeshSizeMin", diag / 5000)
        gmsh.option.setNumber("Mesh.Binary", 1)
        gmsh.option.setNumber("Mesh.StlOneSolidPerSurface", 0)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(dst))
    except Exception as exc:
        if isinstance(exc, ConversionError):
            raise
        raise ConversionError(f"Couldn't mesh this CAD file: {exc}") from exc
    finally:
        gmsh.finalize()


@converter(inputs={"dxf"}, outputs={"svg", "png"})
@converter(inputs={"dxf"}, outputs={"pdf"}, terminal=True)  # a drawing PDF has no text worth extracting
def dxf_render(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    from ezdxf import recover
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
    try:
        doc, _auditor = recover.readfile(str(src))
    except Exception as exc:
        raise ConversionError(f"Couldn't read this DXF: {exc}") from exc
    cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE,
                               color_policy=config.ColorPolicy.COLOR)
    # auto-size to the drawing, but cap at A2 so huge-unit drawings still make sane pages/images
    page = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(10), max_width=594, max_height=594)
    if dst_fmt == "svg":
        from ezdxf.addons.drawing.svg import SVGBackend
        backend = SVGBackend()
        Frontend(RenderContext(doc), backend, config=cfg).draw_layout(doc.modelspace())
        dst.write_text(backend.get_string(page), encoding="utf-8")
    else:
        from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
        backend = PyMuPdfBackend()
        Frontend(RenderContext(doc), backend, config=cfg).draw_layout(doc.modelspace())
        if dst_fmt == "pdf":
            dst.write_bytes(backend.get_pdf_bytes(page))
        else:
            dst.write_bytes(backend.get_pixmap_bytes(page, fmt="png", dpi=200))
