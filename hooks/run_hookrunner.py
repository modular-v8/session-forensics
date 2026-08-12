"""Plugin hook entry point -- what hooks/hooks.json actually invokes.

`hookrunner.py` lives inside the `session_forensics` package and uses relative
imports (`from . import threshold`), which only resolve when the package is
importable -- normally via `python -m session_forensics.hookrunner` with
`src/` on `PYTHONPATH`. A plugin hook command has no straightforward way to
set an environment variable for the process it launches, so this tiny,
import-free bootstrap script does the equivalent by hand: find `src/` next to
this file, put it on `sys.path`, then call in.

Deliberately outside the `session_forensics` package itself (it cannot import
anything from it before `sys.path` is fixed) and deliberately tiny -- anything
this script gets wrong runs on the same critical path hookrunner.py itself
must stay off of.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from session_forensics.hookrunner import main  # noqa: E402

raise SystemExit(main())
