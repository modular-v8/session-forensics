"""CLI bootstrap for plugin/skill contexts -- what SKILL.md tells the agent to
invoke, and a plain alternative to setting PYTHONPATH by hand for anyone using
the plugin install rather than a checked-out copy of the repository.

Same reasoning as hooks/run_hookrunner.py: `cli.py` lives inside the
`session_forensics` package and needs `src/` on `sys.path` before it is
importable. This script does that by hand from its own known location, then
forwards every argument straight to the real CLI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from session_forensics.cli import main  # noqa: E402

raise SystemExit(main(sys.argv[1:]))
