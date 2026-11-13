"""`python -m harness fetch | run | merge | check`, run from compat/."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import check, fetch, merge, runner, scope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download and hash-check the corpus")
    f.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run", help="run one runtime version's readers over the fetched files")
    r.add_argument("--runtime", required=True)
    r.add_argument("--version", required=True)
    r.add_argument("--work", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    m = sub.add_parser("merge", help="combine the parts into results/")
    m.add_argument("--parts", type=Path, required=True)
    m.add_argument("--work", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check", help="hold committed results to the manifest and readers")
    c.add_argument("--results", type=Path, default=scope.COMPAT_DIR / "results")
    args = parser.parse_args(argv)
    config, manifest = scope.load_config(), scope.load_manifest()

    if args.command == "fetch":
        files, _ = scope.corpus(manifest, config)
        report = fetch.fetch_all(files, args.out)
        bad = {p: v["reason"] for p, v in report["files"].items() if not v["ok"]}
        print(f"fetched {len(files) - len(bad)} of {len(files)} files; failed: {bad or 'none'}")
        return 0
    if args.command == "run":
        files, _ = scope.corpus(manifest, config)
        report = json.loads((args.work / "fetch.json").read_text(encoding="utf-8"))
        ok = [x for x in files if report["files"].get(x["path"], {}).get("ok")]
        part = runner.run_runtime(config, ok, args.work, args.runtime, args.version)
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"{args.runtime}-{args.version}.json"
        target.write_text(merge.render(part), encoding="utf-8")
        print(f"{target}: {len(part['cells'])} cells, resolved {part.get('resolved')}")
        return 0
    if args.command == "merge":
        report = json.loads((args.work / "fetch.json").read_text(encoding="utf-8"))
        parts = [
            json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.parts.glob("*.json"))
        ]
        today = dt.datetime.now(dt.UTC).date().isoformat()
        try:
            documents = merge.merge(
                config,
                manifest,
                report,
                parts,
                date=today,
                run_id=os.environ.get("GITHUB_RUN_ID", ""),
            )
        except merge.RunFailed as error:
            print(f"not written: {error}", file=sys.stderr)
            return 1
        merge.write(documents, args.out)
        print(f"wrote {len(documents)} files to {args.out}")
        return 0
    found = check.problems(args.results, config, manifest)
    for line in found[:40]:
        print(line)
    print(f"{len(found)} problems")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
