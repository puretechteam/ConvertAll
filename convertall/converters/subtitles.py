"""Subtitles: SRT <-> WebVTT built in; ASS/SSA and pulling subtitle tracks out of videos via FFmpeg."""

import re
from pathlib import Path

from ..errors import ConversionError
from ..registry import converter
from .media import VIDEO_IN, ffmpeg

TEXT_SUBS = {"srt", "vtt"}
STYLED_SUBS = {"ass", "ssa"}

_TIMING = re.compile(r"(?P<a>[\d:.,]+)\s*-->\s*(?P<b>[\d:.,]+)")
_VTT_TAG = re.compile(r"</?(?:c|v|lang|ruby|rt)(?:[.\s][^>]*)?>|<\d[\d:.]*>")  # keeps <i> <b> <u>


def _blocks(text: str) -> list[list[str]]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return [b.split("\n") for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]


def _stamp(t: str, sep: str) -> str:
    """'1:02.5' / '00:01:02,500' -> '00:01:02<sep>500'."""
    parts = t.replace(",", ".").split(":")
    secs = float(parts[-1])
    mins = int(parts[-2]) if len(parts) > 1 else 0
    hours = int(parts[-3]) if len(parts) > 2 else 0
    ms = round(secs * 1000)
    return f"{hours:02}:{mins:02}:{ms // 1000:02}{sep}{ms % 1000:03}"


def _cues(src: Path) -> list[tuple[str, str, list[str]]]:
    cues = []
    for block in _blocks(src.read_text(encoding="utf-8-sig", errors="replace")):
        idx = next((i for i, line in enumerate(block) if "-->" in line), None)
        if idx is None:  # WEBVTT header, NOTE, STYLE, REGION, or junk
            continue
        m = _TIMING.search(block[idx])
        if m:
            cues.append((m["a"], m["b"], block[idx + 1:]))
    if not cues:
        raise ConversionError("No subtitles found in this file")
    return cues


@converter(inputs=TEXT_SUBS, outputs=TEXT_SUBS)
def srt_vtt(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    out = []
    for n, (a, b, lines) in enumerate(_cues(src), 1):
        if dst_fmt == "vtt":
            out.append(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n" + "\n".join(lines))
        else:
            lines = [_VTT_TAG.sub("", line) for line in lines]
            out.append(f"{n}\n{_stamp(a, ',')} --> {_stamp(b, ',')}\n" + "\n".join(lines))
    head = "WEBVTT\n\n" if dst_fmt == "vtt" else ""
    dst.write_text(head + "\n\n".join(out) + "\n", encoding="utf-8")


@converter(inputs=TEXT_SUBS | STYLED_SUBS, outputs=STYLED_SUBS, engine="ffmpeg")
@converter(inputs=STYLED_SUBS, outputs=TEXT_SUBS, engine="ffmpeg")
def ffmpeg_subs(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, [])


@converter(inputs=VIDEO_IN | {"mka"}, outputs=TEXT_SUBS | STYLED_SUBS, engine="ffmpeg")
def video_subs(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    """The video's first subtitle track."""
    ffmpeg(src, dst, ["-map", "0:s:0"])
