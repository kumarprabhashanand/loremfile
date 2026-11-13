"""The Python adapter: one reader, one file, one JSON object on stdout (compat/README.md).

    python adapter.py <reader-id> <path> [--password P] [--delimiter D]

Standard library only, and no imports of this repository. Each reader opens the file the way
its own documentation shows, reads all of it, and reports only what the reader gives natively,
under the manifest's names. A module imported inside a function, so that a runtime without it
answers `no-reader` instead of dying.
"""

from __future__ import annotations

import json
import sys
from typing import Any

CHUNK = 1 << 16
ERROR_LIMIT = 200


def drain(stream: Any) -> int:  # noqa: ANN401 - any file-like object with read()
    """Read a stream to its end without keeping it; the number of bytes it held."""
    total = 0
    while chunk := stream.read(CHUNK):
        total += len(chunk)
    return total


def zip_reader(path: str, password: str | None, _delimiter: str | None) -> dict[str, Any]:
    import zipfile

    entries = directories = size = 0
    with zipfile.ZipFile(path) as archive:
        if password:
            archive.setpassword(password.encode())
        for info in archive.infolist():
            entries += 1
            directories += info.is_dir()
            with archive.open(info) as member:
                size += drain(member)
    return {"entries": entries, "directories": directories, "uncompressed_bytes": size}


def tar_reader(path: str, _password: str | None, _delimiter: str | None) -> dict[str, Any]:
    import tarfile

    entries = directories = size = 0
    with tarfile.open(path) as archive:
        for member in archive:
            entries += 1
            directories += member.isdir()
            data = archive.extractfile(member)
            if data is not None:
                size += drain(data)
    return {"entries": entries, "directories": directories, "uncompressed_bytes": size}


def gzip_reader(path: str, _password: str | None, _delimiter: str | None) -> dict[str, Any]:
    import gzip

    with gzip.open(path, "rb") as stream:
        return {"uncompressed_bytes": drain(stream)}


def wave_reader(path: str, _password: str | None, _delimiter: str | None) -> dict[str, Any]:
    import wave

    with wave.open(path, "rb") as audio:
        rate = audio.getframerate()
        frames = audio.getnframes()
        while audio.readframes(8192):
            pass
        return {
            "channels": audio.getnchannels(),
            "sample_rate": rate,
            "bit_depth": audio.getsampwidth() * 8,
            "duration_ms": round(frames * 1000 / rate) if rate else 0,
        }


def json_reader(path: str, _password: str | None, _delimiter: str | None) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    names = {dict: "object", list: "array", str: "string", bool: "boolean", type(None): "null"}
    top = names.get(type(value), "number")
    report: dict[str, Any] = {"top_type": top}
    if isinstance(value, dict | list):
        report["items"] = len(value)
    return report


def csv_reader(path: str, _password: str | None, delimiter: str | None) -> dict[str, Any]:
    import csv

    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream, delimiter=delimiter or ","))
    report: dict[str, Any] = {"rows": len(rows)}
    if rows:
        report["columns"] = len(rows[0])
    return report


def etree_reader(path: str, _password: str | None, _delimiter: str | None) -> dict[str, Any]:
    from xml.etree import ElementTree

    tag = ElementTree.parse(path).getroot().tag
    # A named exception (readers.yaml): a name in Clark notation, {namespace}local, is reduced to
    # its local name, and the namespace is reported as its own property.
    namespace, _, local = tag[1:].partition("}") if tag.startswith("{") else ("", "", tag)
    report: dict[str, Any] = {"root_element": local}
    if namespace:
        report["root_namespace"] = namespace
    return report


def minidom_reader(path: str, _password: str | None, _delimiter: str | None) -> dict[str, Any]:
    from xml.dom import minidom

    root = minidom.parse(path).documentElement
    report: dict[str, Any] = {"root_element": root.localName}
    if root.namespaceURI:
        report["root_namespace"] = root.namespaceURI
    return report


READERS = {
    "python/csv": csv_reader,
    "python/gzip": gzip_reader,
    "python/json": json_reader,
    "python/tarfile": tar_reader,
    "python/wave": wave_reader,
    "python/xml.dom.minidom": minidom_reader,
    "python/xml.etree.ElementTree": etree_reader,
    "python/zipfile": zip_reader,
}


def option(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def error_type(error: BaseException) -> str:
    kind = type(error)
    return (
        kind.__qualname__
        if kind.__module__ == "builtins"
        else f"{kind.__module__}.{kind.__qualname__}"
    )


def first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return (lines[0] if lines else "")[:ERROR_LIMIT]


def answer(
    reader_id: str, path: str, password: str | None, delimiter: str | None
) -> dict[str, Any]:
    reader = READERS.get(reader_id)
    if reader is None:
        raise SystemExit(f"unknown reader: {reader_id}")
    try:
        return {"outcome": "reads", "props": reader(path, password, delimiter)}
    except ImportError:
        return {"outcome": "no-reader"}
    except Exception as error:
        message = first_line(str(error)) or type(error).__name__
        return {"outcome": "refuses", "error_type": error_type(error), "error": message}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: adapter.py <reader-id> <path> [--password P] [--delimiter D]", file=sys.stderr
        )
        return 2
    result = answer(argv[0], argv[1], option(argv, "--password"), option(argv, "--delimiter"))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
