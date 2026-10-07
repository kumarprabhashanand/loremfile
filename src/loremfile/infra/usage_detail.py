"""`python -m loremfile.infra.usage_detail usage.json`: every row of a usage report.

health.yml runs it when R2 reads cross the cost threshold (docs/19 §3).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from loremfile.infra.usage import render_detail


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print(render_detail(json.loads(Path(args[0]).read_text(encoding="utf-8"))))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
