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
from loremfile.util.ffmpeg import FfmpegError, packet_bytes, probe
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
        if first.get("profile"):
            props["profile"] = first["profile"]
        if first["codec_name"] == "h264" and int(first.get("level", -99)) > 0:
            # level_idc is ten times the level: 30 is level 3.0, 31 is level 3.1.
            props["level"] = f"{int(first['level']) / 10:.1f}"
    if audio:
        first = audio[0]
        props["acodec"] = first["codec_name"]
        props["sample_rate"] = int(first["sample_rate"])
        props["channels"] = int(first["channels"])
    return props


def _audio_rates(data: bytes, suffix: str, report: dict[str, Any]) -> dict[str, Any]:
    """`bitrate_kbps` from the audio packets themselves, and `bit_depth` for PCM.

    The rate is the audio packets' bytes over the stream's duration: what the codec
    actually spent, without container pages, tags or cover art. Neither ffprobe's stream
    rate nor an encoder setting will do: for Vorbis the stream rate is the nominal figure
    the encoder wrote into its header (128 kbps on a file whose packets average 23.6), and
    asked for 96k, libopus averaged 114.
    """
    audio = _streams(report, "audio")[0]
    seconds = float(audio.get("duration") or report.get("format", {}).get("duration") or 0)
    if seconds <= 0:
        raise ValidationError("the audio stream reports no duration to divide by")
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / f"fixture{suffix}"
        path.write_bytes(data)
        try:
            payload = packet_bytes(path)
        except FfmpegError as exc:
            raise ValidationError(f"ffprobe could not list the audio packets: {exc}") from exc
    props: dict[str, Any] = {"bitrate_kbps": round(payload * 8 / seconds / 1000, 1)}
    if str(audio.get("codec_name", "")).startswith("pcm_"):
        props["bit_depth"] = int(audio["bits_per_sample"])
    return props


#: WAVE `fmt ` chunk format tags a fixture may carry.
WAV_FORMAT_TAGS = {1: "pcm", 3: "float", 0xFFFE: "extensible"}
RIFF_CHUNK_HEADER_BYTES = 8


def _wav_header(data: bytes) -> dict[str, Any]:
    """The `fmt ` chunk's format tag and where the samples start, read from the chunks.

    A canonical PCM header is 44 bytes; a 24-bit writer uses the extensible tag and 68.
    Readers that seek to byte 44 instead of walking the chunks read 24 bytes of header
    as audio, which is why both numbers are measured rather than assumed.
    """
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValidationError("not a RIFF/WAVE file")
    offset, tag = 12, None
    while offset + RIFF_CHUNK_HEADER_BYTES <= len(data):
        chunk = data[offset : offset + 4]
        (size,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        if chunk == b"fmt ":
            (tag,) = struct.unpack("<H", data[offset + 8 : offset + 10])
        elif chunk == b"data":
            if tag is None:
                raise ValidationError("the data chunk comes before any fmt chunk")
            if tag not in WAV_FORMAT_TAGS:
                raise ValidationError(f"unknown WAVE format tag 0x{tag:04x}")
            return {"header_format": WAV_FORMAT_TAGS[tag], "header_bytes": offset + 8}
        offset += RIFF_CHUNK_HEADER_BYTES + size + (size & 1)
    raise ValidationError("no data chunk")


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
        report = _probe(data, suffix)
        props = _common_props(report)

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
        if fmt in AUDIO_FORMATS:
            props.update(_audio_rates(data, suffix, report))
        if fmt == "wav":
            props.update(_wav_header(data))

        if fmt in {"mp4", "mov"}:
            # +faststart moves `moov` ahead of `mdat`. Without it the file plays fine
            # from disk and stalls when streamed, which no parser will report.
            order = _atoms(data)
            if "moov" not in order:
                raise ValidationError(f"no moov atom among {order}")
            if "mdat" not in order:
                raise ValidationError(f"no mdat atom among {order}")
            faststart = order.index("moov") < order.index("mdat")
            if fixture.params.get("faststart", True) and not faststart:
                raise ValidationError(
                    f"moov comes after mdat ({order}); -movflags +faststart was not applied"
                )
            if "faststart" in fixture.params:
                props["faststart"] = faststart
                props["moov_at_end"] = order[-1] == "moov"
        return props


for _format in VIDEO_FORMATS:
    make_media_validator(_format, f".{_format}")
for _format in AUDIO_FORMATS:
    make_media_validator(_format, f".{_format}")


#: An HLS media playlist has to open with this and, being VOD, has to close with ENDLIST.
PLAYLIST_HEADER = "#EXTM3U"
SEGMENT_URI_RE = re.compile(r"^seg-\d{3}\.ts$")
#: A rendition named by a master playlist: a sibling variant directory's media playlist.
RENDITION_URI_RE = re.compile(r"^\.\./[a-z0-9]+(?:-[a-z0-9]+)*/index\.m3u8$")
STREAM_INF_ATTRIBUTE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
RESOLUTION_RE = re.compile(r"^[1-9][0-9]*x[1-9][0-9]*$")
MIN_RENDITIONS = 2


def _master_props(lines: list[str]) -> dict[str, Any]:
    """Every rendition with the three attributes a player chooses by, and a relative URI."""
    renditions = []
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attributes = dict(STREAM_INF_ATTRIBUTE.findall(line.split(":", 1)[1]))
        missing = [n for n in ("BANDWIDTH", "RESOLUTION", "CODECS") if n not in attributes]
        if missing:
            raise ValidationError(f"a rendition without {', '.join(missing)}: {line}")
        if not attributes["BANDWIDTH"].isdigit():
            raise ValidationError(f"BANDWIDTH is not a whole number: {line}")
        if not RESOLUTION_RE.match(attributes["RESOLUTION"]):
            raise ValidationError(f"RESOLUTION is not WIDTHxHEIGHT: {line}")
        uri = lines[index + 1] if index + 1 < len(lines) else ""
        if not RENDITION_URI_RE.match(uri):
            raise ValidationError(f"a rendition URI must be ../<variant>/index.m3u8; got {uri!r}")
        renditions.append(
            (
                int(attributes["BANDWIDTH"]),
                attributes["RESOLUTION"],
                attributes["CODECS"].strip('"'),
            )
        )
    if len(renditions) < MIN_RENDITIONS:
        raise ValidationError(f"{len(renditions)} rendition(s): a master needs at least two")
    if "#EXT-X-ENDLIST" in lines:
        raise ValidationError("a master playlist carries #EXT-X-ENDLIST, a media-playlist tag")
    return {
        "variants": len(renditions),
        "bandwidths": [bandwidth for bandwidth, _, _ in renditions],
        "resolutions": [resolution for _, resolution, _ in renditions],
        "codecs": [codecs for _, _, codecs in renditions],
    }


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
    if fixture.path.endswith("/master.m3u8"):
        return _master_props(lines)
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
