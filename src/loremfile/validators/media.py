"""Validators for video, audio and HLS (docs/06 §6 and §13).

ffprobe is the independent reader: nothing here trusts the generator's own idea of what
it produced. What ffprobe cannot answer is asked separately — an MP4 whose `moov` atom
comes last still probes perfectly and still stalls a progressive player, and a playlist
whose segment URIs point at a build directory parses as valid HLS.

These validators assert structure, not parseability (docs/06 §13).
"""

from __future__ import annotations

import re
import struct
import tempfile
from pathlib import Path
from typing import Any

from loremfile.catalog import Fixture
from loremfile.util.ffmpeg import FfmpegError, probe
from loremfile.validators import ValidationError, register

#: Formats whose props come from ffprobe. HLS playlists are text and handled separately.
VIDEO_FORMATS = ("mp4", "webm", "mkv", "mov", "avi", "ogv", "ts")
AUDIO_FORMATS = ("mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "aiff")

#: Duration is measured, so it is compared with a tolerance rather than for equality.
DURATION_TOLERANCE_MS = 150

#: An MP4 box header is a 4-byte size plus a 4-byte name; a size below that is a
#: malformed box and the walk stops rather than looping.
MP4_BOX_HEADER_BYTES = 8

#: Top-level box names worth walking past to find where `moov` sits.
MP4_TOPLEVEL_ATOMS = (b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide")


def _probe(data: bytes, suffix: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / f"fixture{suffix}"
        path.write_bytes(data)
        try:
            return probe(path)
        except FfmpegError as exc:
            raise ValidationError(f"ffprobe could not read it: {exc}") from exc


def _streams(report: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [s for s in report.get("streams", []) if s.get("codec_type") == kind]


def _duration_ms(report: dict[str, Any]) -> int:
    for source in (report.get("format", {}), *report.get("streams", [])):
        raw = source.get("duration")
        if raw:
            return round(float(raw) * 1000)
    raise ValidationError("neither the container nor any stream reports a duration")


def _common_props(report: dict[str, Any]) -> dict[str, Any]:
    video = _streams(report, "video")
    audio = _streams(report, "audio")
    props: dict[str, Any] = {
        "duration_ms": _duration_ms(report),
        "video_streams": len(video),
        "audio_streams": len(audio),
        "subtitle_streams": len(_streams(report, "subtitle")),
    }
    if video:
        first = video[0]
        props["width"] = int(first["width"])
        props["height"] = int(first["height"])
        props["vcodec"] = first["codec_name"]
        rate = first.get("avg_frame_rate", "0/1")
        numerator, _, denominator = rate.partition("/")
        props["fps"] = round(int(numerator) / int(denominator or 1), 2) if int(numerator) else 0
    if audio:
        first = audio[0]
        props["acodec"] = first["codec_name"]
        props["sample_rate"] = int(first["sample_rate"])
        props["channels"] = int(first["channels"])
    return props


def _atoms(data: bytes) -> list[str]:
    """Top-level MP4/MOV atoms in order. Enough to tell where `moov` sits."""
    names: list[str] = []
    offset = 0
    while offset + MP4_BOX_HEADER_BYTES <= len(data):
        (size,) = struct.unpack(">I", data[offset : offset + 4])
        name = data[offset + 4 : offset + 8]
        if name not in MP4_TOPLEVEL_ATOMS and not name.isalpha():
            break
        names.append(name.decode("ascii", "replace"))
        if size == 1:  # 64-bit extended size follows the name
            (size,) = struct.unpack(">Q", data[offset + 8 : offset + 16])
        if size < MP4_BOX_HEADER_BYTES:
            break
        offset += size
    return names


def make_media_validator(fmt: str, suffix: str) -> None:
    @register(fmt)
    def _validate(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
        props = _common_props(_probe(data, suffix))

        declared = fixture.params.get("duration")
        if declared is not None:
            expected = round(float(declared) * 1000)
            drift = abs(props["duration_ms"] - expected)
            if drift > DURATION_TOLERANCE_MS:
                raise ValidationError(
                    f"is {props['duration_ms']} ms but the catalog asks for {expected} ms "
                    f"({drift} ms out, tolerance {DURATION_TOLERANCE_MS} ms)"
                )
        if fmt in VIDEO_FORMATS and not props["video_streams"]:
            raise ValidationError("has no video stream")
        if fmt in AUDIO_FORMATS and not props["audio_streams"]:
            raise ValidationError("has no audio stream")

        if fmt in {"mp4", "mov"}:
            # +faststart moves `moov` ahead of `mdat`. Without it the file plays fine
            # from disk and stalls when streamed, which no parser will report.
            order = _atoms(data)
            if "moov" not in order:
                raise ValidationError(f"no moov atom among {order}")
            if "mdat" in order and order.index("moov") > order.index("mdat"):
                raise ValidationError(
                    f"moov comes after mdat ({order}); -movflags +faststart was not applied"
                )
        return props


for _format in VIDEO_FORMATS:
    make_media_validator(_format, f".{_format}")
for _format in AUDIO_FORMATS:
    make_media_validator(_format, f".{_format}")


#: An HLS media playlist has to open with this and, being VOD, has to close with ENDLIST.
PLAYLIST_HEADER = "#EXTM3U"
SEGMENT_URI_RE = re.compile(r"^seg-\d{3}\.ts$")


@register("hls")
def validate_hls(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    """A playlist is checked as text; a segment is checked as MPEG-TS."""
    if not fixture.path.endswith(".m3u8"):
        props = _common_props(_probe(data, ".ts"))
        if not props["video_streams"]:
            raise ValidationError("a segment with no video stream")
        return props

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"the playlist is not valid UTF-8: {exc}") from exc
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != PLAYLIST_HEADER:
        raise ValidationError(f"does not start with {PLAYLIST_HEADER}")
    if "#EXT-X-ENDLIST" not in lines:
        raise ValidationError("no #EXT-X-ENDLIST, so a player treats it as a live stream")

    uris = [line for line in lines if not line.startswith("#")]
    if not uris:
        raise ValidationError("names no segments")
    absolute = [uri for uri in uris if not SEGMENT_URI_RE.match(uri)]
    if absolute:
        raise ValidationError(
            f"segment URIs must be relative names beside the playlist; found {absolute[:3]}"
        )
    target = [line for line in lines if line.startswith("#EXT-X-TARGETDURATION")]
    if not target:
        raise ValidationError("no #EXT-X-TARGETDURATION")
    return {
        "segments": len(uris),
        "target_duration_s": int(target[0].split(":", 1)[1]),
        "playlist_type": "VOD" if "#EXT-X-PLAYLIST-TYPE:VOD" in lines else "",
    }
