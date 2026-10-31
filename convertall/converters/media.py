"""Audio and video via FFmpeg."""

from pathlib import Path

from .. import engines
from ..errors import ConversionError
from ..losses import loss
from ..registry import converter, option

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

AUDIO = set(AUDIO_ARGS)
VIDEO = set(VIDEO_ARGS)
# FFmpeg reads these fine but can't (usefully) write them
AUDIO_IN = AUDIO | {"ape", "dsf", "dff"}
VIDEO_IN = VIDEO | {"mxf", "rm", "rmvb", "3g2"}


def ffmpeg(src: Path, dst: Path, args: list[str]) -> None:
    exe = engines.require("ffmpeg")
    try:
        # local files only: a playlist or concat file can't make FFmpeg fetch URLs
        engines.run([exe, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file",
                     "-i", str(src), *args, str(dst)])
    except ConversionError as exc:
        msg = str(exc)
        if "does not contain any stream" in msg or "matches no streams" in msg:
            kind = "subtitle" if "0:s:0" in args else "audio" if "-vn" in args else "video"
            raise ConversionError(f"{src.name} has no {kind} track to convert") from None
        if "only possible from text to text or bitmap to bitmap" in msg:
            raise ConversionError(f"{src.name}'s subtitles are pictures (DVD/Blu-ray style), not text") from None
        raise


# ---- settings (options.py): each replaces what the args above say when it's chosen

LOSSY_AUDIO = {"mp3", "ogg", "opus", "m4a", "aac", "wma", "ac3", "mka", "m4b", "mp2", "m4r"}
# video_quality "smaller", "balanced" (what VIDEO_ARGS use) or "best": per encoder, the value of
# the flag that sets its quality
VIDEO_QUALITY = {"libx264": ("-crf", ("28", "23", "18")), "libvpx-vp9": ("-crf", ("38", "32", "24")),
                 "mpeg4": ("-q:v", ("6", "3", "2")), "mpeg2video": ("-q:v", ("6", "3", "2")),
                 "libtheora": ("-q:v", ("5", "7", "9")), "wmv2": ("-b:v", ("2M", "4M", "8M"))}
QUALITY_LEVELS = ("smaller", "balanced", "best")
GIF_FPS, GIF_WIDTH, WEBP_FPS, WEBP_WIDTH = 12, 640, 15, 800


def _short_side(n: int) -> str:
    """A scale filter fitting the shorter side to n pixels (720 for "720p", portrait or not), never enlarging."""
    return f"scale='if(gte(iw,ih),-2,min({n},iw))':'if(gte(iw,ih),min({n},ih),-2)'"


def _with_filters(args: list[str], filters: list[str]) -> list[str]:
    """args with filters run first (before the -vf the args already have, if any)."""
    if not filters:
        return args
    args = list(args)
    if "-vf" in args:
        i = args.index("-vf") + 1
        args[i] = ",".join([*filters, args[i]])
        return args
    return ["-vf", ",".join(filters), *args]


def _picture_filters() -> list[str]:
    fps, size = option("fps"), option("video_size")
    return ([f"fps={int(fps)}"] if fps else []) + ([_short_side(int(str(size).rstrip("p")))] if size else [])


def video_args(fmt: str) -> list[str]:
    args = list(VIDEO_ARGS[fmt])
    level = option("video_quality")
    codec = args[args.index("-c:v") + 1]
    if level in QUALITY_LEVELS and codec in VIDEO_QUALITY:
        flag, values = VIDEO_QUALITY[codec]
        args[args.index(flag) + 1] = values[QUALITY_LEVELS.index(level)]
    return _with_filters(args, _picture_filters())


def audio_args(fmt: str) -> list[str]:
    args = list(AUDIO_ARGS[fmt])
    rate = option("bitrate")
    if rate and fmt in LOSSY_AUDIO:
        for flag in ("-q:a", "-b:a"):  # a fixed rate in place of the format's own quality
            if flag in args:
                i = args.index(flag)
                del args[i:i + 2]
        args[2:2] = ["-b:a", f"{int(rate)}k"]
    return args


def animation_args(fps: int, width: int, tail: list[str]) -> list[str]:
    size = option("video_size")
    scale = _short_side(int(str(size).rstrip("p"))) if size else f"scale='min({width},iw)':-1"
    return ["-vf", f"fps={int(option('fps', fps))},{scale}:flags=lanczos{tail[0]}", *tail[1:]]


def _gif_args() -> list[str]:
    return animation_args(GIF_FPS, GIF_WIDTH, [",split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0"])


def _webp_args() -> list[str]:
    return animation_args(WEBP_FPS, WEBP_WIDTH, ["", "-c:v", "libwebp_anim", "-quality", "75", "-loop", "0", "-an"])


def _size_words(opts: dict, width: int) -> str:
    return f"at most {opts['video_size']}" if opts.get("video_size") else f"at most {width} pixels wide"


TRACKS = loss("Only one sound track is kept", "tracks", affects=("audio_tracks",))


def _audio_notes(src: str, dst: str, opts: dict) -> list:
    out = [TRACKS]
    if dst == "m4r":
        out.append(loss("iPhone ringtones stop at 40 seconds", weight=0, affects=("duration",)))
    if dst == "amr":
        out.append(loss("AMR is phone-call sound: 8 kHz, one channel", weight=0))
    return out


@converter(inputs=AUDIO_IN | VIDEO_IN, outputs=AUDIO, engine="ffmpeg", notes=_audio_notes,
           options=lambda s, d: ("bitrate",) if d in LOSSY_AUDIO else ())
def to_audio(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, ["-vn", *audio_args(dst_fmt)])


def _video_notes(src: str, dst: str, opts: dict) -> list:
    out = [loss("The video is re-encoded: a little quality is lost", weight=0), TRACKS]
    if opts.get("video_size"):
        out.append(loss(f"Scaled down to at most {opts['video_size']}", weight=0, affects=("width", "height")))
    return out


VIDEO_SETTINGS = ("video_quality", "video_size", "fps")


@converter(inputs=VIDEO_IN, outputs=VIDEO, engine="ffmpeg", notes=_video_notes, options=VIDEO_SETTINGS)
@converter(inputs={"gif"}, outputs=VIDEO, engine="ffmpeg", terminal=True,  # no gif -> video -> "audio"
           notes=_video_notes, options=VIDEO_SETTINGS)
def to_video(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, video_args(dst_fmt))


@converter(inputs=VIDEO_IN, outputs={"gif"}, engine="ffmpeg", options=("fps", "video_size"),
           notes=lambda s, d, o: [loss(f"GIF animations run at {o.get('fps') or GIF_FPS} frames a second, "
                                       f"{_size_words(o, GIF_WIDTH)}, with 256 colors and no sound", "colors",
                                       weight=0, affects=("width", "height", "frames"))])
def to_gif(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, _gif_args())


@converter(inputs=VIDEO_IN, outputs={"webp"}, engine="ffmpeg", terminal=True,  # animated: don't chain on
           options=("fps", "video_size"),
           notes=lambda s, d, o: [loss(f"Animated WebP runs at {o.get('fps') or WEBP_FPS} frames a second, "
                                       f"{_size_words(o, WEBP_WIDTH)}, with no sound", weight=0,
                                       affects=("width", "height", "frames"))])
def to_animated_webp(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ffmpeg(src, dst, _webp_args())
