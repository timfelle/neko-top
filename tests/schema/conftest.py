"""Shared fixtures for the Neko-TOP case-file schema tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

for _module in ("jsonschema", "referencing", "json5"):
    pytest.importorskip(_module)

TOP_ROOT = Path(
    os.environ.get("NEKO_TOP_SOURCE_DIR") or Path(__file__).resolve().parents[2]
)
sys.path.insert(0, str(TOP_ROOT / "scripts" / "python"))

import validate_case_schema as vcs  # noqa: E402


@pytest.fixture(scope="session")
def loaded():
    """Both projects' schemas, loaded and probed; skips if Neko's are not
    usable (the same condition run_schema_tests.py turns into exit 77)."""
    try:
        return vcs.load_all()
    except vcs.SchemaSetupError as exc:
        if os.environ.get("NEKO_TOP_REQUIRE_SCHEMA_TESTS") == "1":
            pytest.fail(str(exc), pytrace=False)
        pytest.skip(str(exc))


@pytest.fixture(scope="session")
def registry(loaded):
    return loaded.registry


@pytest.fixture(scope="session")
def schemas(loaded):
    """`$id -> schema` for every Neko and Neko-TOP schema."""
    return loaded.schemas


@pytest.fixture(scope="session")
def validator(loaded):
    """Validator for the Neko-TOP collected root."""
    return loaded.validator


@pytest.fixture(scope="session")
def top_dir(loaded):
    return loaded.top_dir


@pytest.fixture(scope="session")
def top_schemas(schemas):
    return {k: v for k, v in schemas.items() if k.startswith(vcs.TOP_PREFIX)}
