"""The ``loremfile`` command line interface.

The full command table lives in ``docs/06-generation-pipeline.md`` §10. Commands
are added by the milestone that implements them (M1.6 ``catalog``/``manifest``,
M3 ``build``/``validate``, M4 ``site``/``upload``/``verify-live``), so this module
is deliberately a stub until then: M1.1 only has to give the console script an
entry point to bind to.
"""

from __future__ import annotations

import sys

from loremfile import __version__


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``loremfile`` console script.

    Returns a process exit code; every command exits non-zero on any failure.
    """
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in {"--version", "-V"}:
        print(f"loremfile {__version__}")
        return 0
    print(
        "loremfile: no commands are implemented yet (M1.1 skeleton).\n"
        "See docs/06-generation-pipeline.md §10 for the command table and\n"
        "docs/15-implementation-plan.md for which milestone adds each one.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
