"""`loremfile get | list | verify` (the CLI spec), and `loremfile mcp` (mcp.py).

argparse rather than a framework, because the package has no dependencies and this is
four subcommands. Exit codes are the contract: 0 fine, 1 a file failed verification or
is missing, 2 the request was wrong, 3 loremfile.dev could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from loremfile_client import __version__, api, mcp

OK, FAILED, REFUSED, UNREACHABLE = 0, 1, 2, 3
DEFAULT_DEST = "loremfile-fixtures"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loremfile",
        description="Download CC0 sample files from loremfile.dev and check every byte.",
        epilog="Files come from loremfile.dev and nowhere else; there is no mirror option.",
    )
    parser.add_argument("--version", action="version", version=f"loremfile {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    def shared(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--json", action="store_true", help="Print one JSON object.")
        sub.add_argument("--quiet", action="store_true", help="Print nothing but failures.")
        sub.add_argument(
            "--catalog-version",
            metavar="X.Y.Z",
            help="Refuse to run unless loremfile.dev publishes this catalog version.",
        )

    get = subcommands.add_parser("get", help="Download fixtures and verify them.")
    get.add_argument("paths", nargs="*", metavar="PATH", help="e.g. pdf/minimal.pdf")
    get.add_argument(
        "--format",
        action="append",
        default=[],
        metavar="FMT",
        help="Every published file of this format. Repeatable.",
    )
    get.add_argument("--dest", default=DEFAULT_DEST, type=Path, help=f"Default: {DEFAULT_DEST}")
    get.add_argument("--force", action="store_true", help="Overwrite files already there.")
    get.add_argument("--dry-run", action="store_true", help="List what would be fetched.")
    shared(get)

    listing = subcommands.add_parser("list", help="What is published, without downloading.")
    listing.add_argument("--format", action="append", default=[], metavar="FMT")
    listing.add_argument("--tag", action="append", default=[], metavar="TAG")
    listing.add_argument("--max-bytes", type=int, metavar="N")
    shared(listing)

    check = subcommands.add_parser("verify", help="Check files on disk against the manifest.")
    check.add_argument("paths", nargs="*", metavar="PATH")
    check.add_argument("--format", action="append", default=[], metavar="FMT")
    check.add_argument("--dest", default=DEFAULT_DEST, type=Path, help=f"Default: {DEFAULT_DEST}")
    shared(check)

    subcommands.add_parser(
        "mcp", help="Serve list, describe and verify to an agent over MCP on stdio."
    )
    return parser


def emit(args: argparse.Namespace, summary: dict[str, Any], results: list[api.Result]) -> None:
    if args.json:
        print(json.dumps({"summary": summary, "items": [vars(r) for r in results]}, indent=2))
        return
    for result in results:
        if not result.ok or not args.quiet:
            print(
                f"  {result.status:8} {result.path}{'  ' + result.detail if result.detail else ''}"
            )
    if not args.quiet:
        print(", ".join(f"{key}={value}" for key, value in summary.items()))


def run_get(args: argparse.Namespace) -> int:
    entries = api.select(
        api.active(api.manifest(catalog_version=args.catalog_version)),
        paths=args.paths,
        formats=args.format,
    )
    if args.dry_run:
        total = sum(e["bytes"] for e in entries)
        emit(
            args,
            {"files": len(entries), "bytes": total, "dest": str(args.dest), "dry-run": True},
            [api.Result(e["path"], "would fetch", f"{e['bytes']:,} bytes") for e in entries],
        )
        return OK
    results = []
    for index, entry in enumerate(entries):
        results.append(api.download(entry, args.dest, force=args.force))
        if index + 1 < len(entries):
            api.pace()
    emit(args, {"files": len(results), "dest": str(args.dest)}, results)
    return OK


def run_list(args: argparse.Namespace) -> int:
    entries = api.active(api.manifest(catalog_version=args.catalog_version))
    if args.format:
        entries = [e for e in entries if e["format"] in set(args.format)]
    if args.tag:
        entries = [e for e in entries if set(args.tag) & set(e.get("tags", []))]
    if args.max_bytes is not None:
        entries = [e for e in entries if e["bytes"] <= args.max_bytes]
    results = [
        api.Result(e["path"], "listed", f"{e['bytes']:,} bytes  {e['mime']}") for e in entries
    ]
    emit(args, {"files": len(results)}, results)
    return OK


def run_verify(args: argparse.Namespace) -> int:
    entries = api.active(api.manifest(catalog_version=args.catalog_version))
    if args.paths or args.format:
        entries = api.select(entries, paths=args.paths, formats=args.format)
    else:
        # Everything the destination actually holds, so `verify` alone checks a directory.
        entries = [e for e in entries if (args.dest / Path(e["path"])).is_file()]
    results = [api.verify(entry, args.dest) for entry in entries]
    failing = [r for r in results if not r.ok]
    emit(args, {"checked": len(results), "failing": len(failing)}, results)
    return FAILED if failing else OK


def run_mcp(_args: argparse.Namespace) -> int:
    # stdout carries protocol messages only, so this prints nothing of its own there.
    mcp.serve()
    return OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = {"get": run_get, "list": run_list, "verify": run_verify, "mcp": run_mcp}[args.command]
    try:
        return runner(args)
    except api.Refused as exc:
        print(f"loremfile: {exc}", file=sys.stderr)
        return REFUSED
    except api.Mismatch as exc:
        print(f"loremfile: {exc}", file=sys.stderr)
        return FAILED
    except api.Unreachable as exc:
        print(f"loremfile: {exc}", file=sys.stderr)
        return UNREACHABLE


if __name__ == "__main__":
    raise SystemExit(main())
