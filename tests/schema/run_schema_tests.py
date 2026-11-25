#!/usr/bin/env python3
"""Run one schema test module with pytest, for CTest.

Exit 77 (CTest's SKIP_RETURN_CODE) when a Python dependency is missing or the
Neko schemas that Neko-TOP's build on are missing or incompatible, unless
NEKO_TOP_REQUIRE_SCHEMA_TESTS=1, in which case that is a failure: a skip must
not read as a pass where the schemas are supposed to be checked.

Usage: run_schema_tests.py TEST_FILE [pytest args...]
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

SKIP = 77
HERE = Path(__file__).resolve().parent
MODULES = ("jsonschema", "referencing", "json5", "pytest")


def unavailable() -> str | None:
    """Return why the schema tests cannot run, or None if they can."""
    for name in MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            return f"Python module {name} is not installed"
    sys.path.insert(0, str(HERE.parents[1] / "scripts" / "python"))
    top = os.environ.get("NEKO_TOP_SOURCE_DIR")
    if top:
        sys.path.insert(0, str(Path(top) / "scripts" / "python"))
    import validate_case_schema as vcs

    try:
        vcs.load_all()
    except vcs.SchemaSetupError as exc:
        return str(exc)
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    reason = unavailable()
    if reason is not None:
        required = os.environ.get("NEKO_TOP_REQUIRE_SCHEMA_TESTS") == "1"
        verb = "FAILED" if required else "SKIPPED"
        print(f"Schema tests {verb}: {reason}", file=sys.stderr)
        return 1 if required else SKIP

    import pytest

    return int(pytest.main(["-p", "no:cacheprovider", *sys.argv[1:]]))


if __name__ == "__main__":
    raise SystemExit(main())
