"""CAD: STEP/IGES/BREP solids -> STL mesh via gmsh (OpenCASCADE); DXF drawings -> SVG/PDF/PNG via ezdxf,
and SVG/PDF vector drawings -> DXF."""

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


# ---- SVG / PDF vectors -> DXF (laser cutters, CNC, CAD): every stroked or filled path becomes a
# polyline in millimetres, curves flattened finely; text becomes TEXT entities. Each page sits
# below the previous one on its own layer.

PT_TO_MM = 25.4 / 72
CURVE_STEPS = 16


def _bezier(p0, p1, p2, p3, steps: int = CURVE_STEPS):
    for i in range(1, steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        yield (a * p0.x + b * p1.x + c * p2.x + d * p3.x, a * p0.y + b * p1.y + c * p2.y + d * p3.y)


def _paths(drawing) -> list[tuple[list[tuple[float, float]], bool]]:
    """A PyMuPDF drawing's items as runs of connected points: [(points, closed)]."""
    runs: list[list[tuple[float, float]]] = []
    for item in drawing["items"]:
        kind = item[0]
        if kind == "re":
            r = item[1]
            runs.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
            continue
        if kind == "qu":
            q = item[1]
            runs.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])
            continue
        start = (item[1].x, item[1].y)
        pts = [(item[2].x, item[2].y)] if kind == "l" else list(_bezier(*item[1:5])) if kind == "c" else []
        if not pts:
            continue
        if runs and runs[-1] and abs(runs[-1][-1][0] - start[0]) < 1e-6 and abs(runs[-1][-1][1] - start[1]) < 1e-6:
            runs[-1] += pts
        else:
            runs.append([start, *pts])
    closed = bool(drawing.get("closePath"))
    return [(run, closed or (len(run) > 2 and run[0] == run[-1])) for run in runs if len(run) > 1]


@converter(inputs={"svg", "pdf"}, outputs={"dxf"}, terminal=True)
def vectors_to_dxf(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import ezdxf
    from ezdxf import colors

    from .pdf import open_doc
    doc = ezdxf.new(units=4)  # millimetres
    msp = doc.modelspace()
    count, offset = 0, 0.0
    with open_doc(src) as pdf:
        for page_no, page in enumerate(pdf, 1):
            layer = f"Page {page_no}" if len(pdf) > 1 else "0"
            if layer != "0":
                doc.layers.add(layer)
            height = page.rect.height

            def xy(p, h=height, off=offset):  # PDF y grows down, DXF y up; pages stack downwards
                return (p[0] * PT_TO_MM, (h - p[1]) * PT_TO_MM - off)

            for drawing in page.get_drawings():
                color = drawing.get("color") or drawing.get("fill")
                attribs = {"layer": layer}
                if color:
                    attribs["true_color"] = colors.rgb2int(tuple(round(c * 255) for c in color[:3]))
                for pts, closed in _paths(drawing):
                    msp.add_lwpolyline([xy(p) for p in pts], close=closed, dxfattribs=attribs)
                    count += 1
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if span["text"].strip():
                            msp.add_text(span["text"], height=span["size"] * PT_TO_MM * 0.7,
                                         dxfattribs={"layer": layer, "insert": xy(span["origin"])})
                            count += 1
            offset += height * PT_TO_MM + 20
    if not count:
        raise ConversionError("No vector shapes or text found (a scanned page or photo has none to trace)")
    doc.saveas(dst)
