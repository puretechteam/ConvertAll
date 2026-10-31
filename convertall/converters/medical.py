"""DICOM medical images -> regular images (windowed for viewing) and readable metadata JSON."""

import json
from pathlib import Path

from PIL import Image

from ..errors import ConversionError
from ..losses import loss
from ..registry import converter
from .images import WRITE as IMAGE_OUT
from .images import prepare, save_image

# Series become one file only where viewers expect several frames (animation / pages);
# anything else (e.g. PNG) gets a folder of frames.
SERIES_IN_ONE_FILE = {"gif", "webp", "tiff", "pdf"}


def _read(src: Path):
    import pydicom
    try:
        return pydicom.dcmread(str(src), force=True)
    except Exception as exc:
        raise ConversionError(f"Couldn't read this DICOM file: {exc}") from exc


def _frames(ds) -> list[Image.Image]:
    import numpy as np
    from pydicom.pixels import apply_modality_lut, apply_voi_lut
    if "PixelData" not in ds:
        raise ConversionError("This DICOM file has no image (it may be a report or structure set)")
    try:
        arr = ds.pixel_array
    except Exception as exc:
        syntax = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
        name = getattr(syntax, "name", "")
        if "missing dependencies" in str(exc) or "Unable to decompress" in str(exc):
            raise ConversionError(f"This DICOM uses {name or 'a compression'} that ConvertAll can't decode") from exc
        raise ConversionError(f"Couldn't read the image in this DICOM file: {exc}") from exc
    frames = int(ds.get("NumberOfFrames", 1) or 1)
    if frames == 1:
        arr = arr[None]
    if int(ds.get("SamplesPerPixel", 1)) == 1:
        # stored values -> real units (e.g. Hounsfield) -> the window the scanner chose for viewing
        arr = apply_modality_lut(arr, ds)
        if "WindowCenter" in ds or "VOILUTSequence" in ds:
            arr = apply_voi_lut(arr, ds)
        arr = arr.astype(np.float64)
        lo, hi = float(arr.min()), float(arr.max())  # one scale for all frames: consistent brightness
        arr = (arr - lo) / ((hi - lo) or 1.0) * 255.0
        if ds.get("PhotometricInterpretation") == "MONOCHROME1":  # 0 means white here
            arr = 255.0 - arr
        return [Image.fromarray(f.astype(np.uint8), "L") for f in arr]
    return [Image.fromarray(np.ascontiguousarray(f).astype(np.uint8), "RGB") for f in arr]


def _image_notes(src: str, dst: str, opts: dict) -> list:
    out = [loss("Scanner values are scaled to 8 bits for viewing (the window the scan chose): measurements such "
                "as Hounsfield units and patient details are left out", weight=0)]
    if dst not in SERIES_IN_ONE_FILE:
        out.append(loss("A series becomes a folder of frames", "frames", weight=0, affects=("frames",)))
    return out


@converter(inputs={"dcm"}, outputs=IMAGE_OUT, terminal=True, notes=_image_notes)
def dicom_to_image(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    """One frame -> one image. A multi-frame series -> animated file if the format allows, else a folder."""
    frames = [prepare(f, dst_fmt) for f in _frames(_read(src))]
    if len(frames) == 1 or dst_fmt in SERIES_IN_ONE_FILE:
        save_image(frames[0], dst, dst_fmt, frames, duration=100)
        return dst
    folder = dst.parent / f"{dst.stem} ({dst_fmt} frames)"
    folder.mkdir()
    width = len(str(len(frames)))
    for i, frame in enumerate(frames, 1):
        save_image(frame, folder / f"frame-{i:0{width}}.{dst_fmt}", dst_fmt)
    return folder


def _to_dict(ds) -> dict:
    from pydicom.multival import MultiValue
    out: dict = {}
    for el in ds:
        if el.tag == 0x7FE00010:  # pixel data
            continue
        key = el.keyword or str(el.tag)
        if el.VR == "SQ":
            out[key] = [_to_dict(item) for item in el.value]
        elif el.VR in ("OB", "OW", "OF", "OD", "OL", "OV", "UN"):
            out[key] = f"<{len(el.value or b'')} bytes>"
        elif isinstance(el.value, MultiValue):
            out[key] = [v if isinstance(v, (int, float)) else str(v) for v in el.value]
        elif isinstance(el.value, (int, float)) or el.value is None:
            out[key] = el.value
        else:
            out[key] = str(el.value)
    return out


@converter(inputs={"dcm"}, outputs={"json"}, terminal=True,
           notes=lambda s, d, o: [loss("Only the details are kept: the image itself is left out", weight=0)])
def dicom_to_json(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ds = _read(src)
    data = _to_dict(ds)
    if getattr(ds, "file_meta", None):
        data = {"FileMeta": _to_dict(ds.file_meta), **data}
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
