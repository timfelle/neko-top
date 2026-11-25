"""Helpers shared by the schema tests: fixtures, edits, validation."""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

import validate_case_schema as vcs

HERE = Path(__file__).resolve().parent
TOP_ROOT = Path(os.environ.get("NEKO_TOP_SOURCE_DIR") or HERE.parents[1])
FIXTURES = HERE / "fixtures"

#: Marks a key to delete in an edit.
DEL = object()

BASES = {
    "steady": FIXTURES / "topopt_steady.case",
    "unsteady": FIXTURES / "topopt_unsteady.case",
    "neko": FIXTURES / "neko_driver.case",
}

_STEP = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def steps(path: str) -> list[str | int]:
    """`optimization.design.mapping[0].f_max` -> list of keys and indices."""
    out: list[str | int] = []
    for key, index in _STEP.findall(path):
        out.append(int(index) if index != "" and not key else key)
    return out


def load_base(name: str) -> Any:
    return vcs.parse_case(BASES[name])


def edit(instance: Any, path: str, value: Any) -> None:
    """Set (or with DEL delete) the value at `path`, in place."""
    parts = steps(path)
    node = instance
    for part in parts[:-1]:
        if value is not DEL and isinstance(part, str) and part not in node:
            node[part] = {}  # a new block, e.g. `solver.checkpoint`
        node = node[part]
    last = parts[-1]
    if value is DEL:
        if isinstance(node, list):
            del node[last]
        else:
            node.pop(last, None)
    else:
        if isinstance(node, list) and last == len(node):
            node.append(value)
        else:
            node[last] = value


def build(base: str, edits: dict[str, Any]) -> Any:
    """The fixture `base` with the `edits` ({path: value or DEL}) applied."""
    instance = copy.deepcopy(load_base(base))
    for path, value in edits.items():
        edit(instance, path, value)
    return instance


def ensure_object(instance: Any, path: str) -> Any:
    """The object at `path`, created (empty) where it is missing."""
    node = instance
    for part in steps(path):
        if isinstance(part, str) and part not in node:
            node[part] = {}
        node = node[part]
    return node


def errors(validator, instance: Any) -> list[tuple[str, str]]:
    return vcs.validate_instance(validator, instance, all_errors=True)


def error_paths(validator, instance: Any) -> set[str]:
    return {path for path, _ in errors(validator, instance)}


def short(instance_errors: list[tuple[str, str]]) -> str:
    return "; ".join(f"{p}: {m[:100]}" for p, m in instance_errors[:4])


def dumps(instance: Any) -> str:
    return json.dumps(instance)
