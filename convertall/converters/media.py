"""Audio and video via FFmpeg."""

from pathlib import Path

from .. import engines
from ..errors import ConversionError
from ..registry import converter

EVEN = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]  # H.264/yuv420p needs even dimensions
H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", *EVEN]
AAC = ["-c:a", "aac", "-b:a", "160k"]

AUDIO_ARGS = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "wma": ["-c:a", "wmav2", "-b:a", "192k"],
    "aiff": ["-c:a", "pcm_s16be"],
    "ac3": ["-c:a", "ac3", "-b:a", "448k"],
    "amr": ["-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k"],
    "mka": ["-c:a", "libopus", "-b:a", "160k"],
    "m4b": ["-c:a", "aac", "-b:a", "96k"],  # audiobooks: speech needs little
    "wv": ["-c:a", "wavpack", "-frame_size", "4096"],  # MP3's short first frame upsets it otherwise
    "caf": ["-c:a", "alac"],
    "mp2": ["-c:a", "mp2", "-b:a", "256k", "-ar", "44100"],  # MP2 has no 8 kHz mode (phone audio)
    "au": ["-c:a", "pcm_s16be"],
    "m4r": ["-c:a", "aac", "-b:a", "192k", "-t", "40", "-f", "ipod"],  # iPhone ringtones stop at 40 s
}

VIDEO_ARGS = {
    "mp4": [*H264, *AAC, "-movflags", "+faststart"],
    "m4v": [*H264, *AAC, "-movflags", "+faststart"],
    "mov": [*H264, *AAC],
    "mkv": [*H264, *AAC],
    "ts": [*H264, *AAC],
    "flv": [*H264, *AAC, "-ar", "44100"],
    "3gp": [*H264, *AAC, "-ar", "44100"],
    "webm": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-pix_fmt", "yuv420p",
             "-c:a", "libopus", "-b:a", "128k"],
    "avi": ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3"],
    "wmv": ["-c:v", "wmv2", "-b:v", "4M", *EVEN, "-c:a", "wmav2", "-b:a", "192k"],
    "mpg": ["-c:v", "mpeg2video", "-q:v", "3", "-c:a", "mp2", "-b:a", "192k"],
    "ogv": ["-c:v", "libtheora", "-q:v", "7", "-pix_fmt", "yuv420p", *EVEN, "-c:a", "libvorbis", "-q:a", "5"],
    "f4v": [*H264, *AAC],
    "asf": ["-c:v", "wmv2", "-b:v", "4M", *EVEN, "-c:a", "wmav2", "-b:a", "192k"],
    "vob": ["-c:v", "mpeg2video", "-q:v", "3", *EVEN, "-c:a", "ac3", "-b:a", "192k"],
}

GIF_ARGS = ["-vf", "fps=12,scale='min(640,iw)':-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
            "-loop", "0"]
WEBP_ARGS = ["-vf", "fps=15,scale='min(800,iw)':-1:flags=lanczos", "-c:v", "libwebp_anim", "-quality", "75",
             "-loop", "0", "-an"]

AUDIO = set(AUDIO_ARGS)
VIDEO = set(VIDEO_ARGS)
# FFmpeg reads these fine but can't (usefully) write them
AUDIO_IN = AUDIO | {"ape", "dsf", "dff"}
VIDEO_IN = VIDEO | {"mxf", "rm", "rmvb", "3g2"}


def ffmpeg(src: Path, dst: Path, args: list[str]) -> None:
    exe = engines.require("ffmpeg")
    try:
        engines.run([exe, "-hide_banner", "-nostdin", "-y", "-i", str(src), *args, str(dst)])
    except ConversionError as exc:
        msg = str(exc)
        if "does not contain any stream" in msg or "matches no streams" in msg:
            kind = "subtitle" if "0:s:0" in args else "audio" if "-vn" in args else "video"
            raise ConversionError(f"{src.name} has no {kind} track to convert") from None
        if "only possible from text to text or bitmap to bitmap" in msg:
            raise ConversionError(f"{src.name}'s subtitles are pictures (DVD/Blu-ray style), not text") from None
        raise


@converter(inputs=AUDIO_IN | VIDEO_IN, outputs=AUDIO, engine="ffmpeg")
def to_audio(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, ["-vn", *AUDIO_ARGS[dst_fmt]])


@converter(inputs=VIDEO_IN, outputs=VIDEO, engine="ffmpeg")
@converter(inputs={"gif"}, outputs=VIDEO, engine="ffmpeg", terminal=True)  # no gif -> video -> "audio"
def to_video(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, VIDEO_ARGS[dst_fmt])


@converter(inputs=VIDEO_IN, outputs={"gif"}, engine="ffmpeg")
def to_gif(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, GIF_ARGS)


@converter(inputs=VIDEO_IN, outputs={"webp"}, engine="ffmpeg", terminal=True)  # animated: don't chain on
def to_animated_webp(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, WEBP_ARGS)
