"""The /compat harness: fetch the corpus, run each reader, compare, write results.

Standard library only, and no imports of `src/loremfile`: it runs on a bare runner, under each
Python it tests, and it never touches the toolchain image or the lock (docs/20). Run it from
`compat/` as `python -m harness {fetch,run,merge,check}`.
"""

from __future__ import annotations

#: The harness's own version, in the agent every fetch sends. `config.COMPAT_USER_AGENT` in
#: `src/loremfile` must equal AGENT; `tests/unit/test_compat_harness.py` holds the two together.
VERSION = "1"
BASE_URL = "https://loremfile.dev/"
AGENT = f"loremfile-compat/{VERSION} (+{BASE_URL}status)"

#: The words a cell's outcome can be (docs/20 section 3). Nothing else is ever written.
OUTCOMES = ("reads", "differs", "refuses", "crashes", "no-reader", "not-run")
#: More failed files than this and the run is not committed at all.
MAX_FAILED_FILES = 3
