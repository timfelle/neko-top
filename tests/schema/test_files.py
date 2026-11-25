"""Self-checks of the Neko-TOP schema files.

These hold for every schema under documentation/schemas, whatever it
describes: well-formed draft 2020-12, `$id` matching the path, references that
resolve, and only keywords that Neko's own checker (`checkneko`) supports.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

import jsonschema
import pytest
from referencing.exceptions import Unresolvable

import validate_case_schema as vcs

# Keywords checkneko supports, plus annotations.
VALIDATION_KEYWORDS = {
    "properties", "$defs", "allOf", "anyOf", "oneOf", "not", "if", "then",
    "else", "items", "additionalProperties", "$ref", "pattern", "type",
    "enum", "const", "required", "dependentRequired", "minItems", "maxItems",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "x-neko-real",
}
ANNOTATIONS = {
    "$schema", "$id", "$comment", "title", "description", "default",
    "examples", "format", "deprecated",
}
ALLOWED_KEYWORDS = VALIDATION_KEYWORDS | ANNOTATIONS

SUBSCHEMA_MAPS = {"properties", "$defs"}
SUBSCHEMA_LISTS = {"allOf", "anyOf", "oneOf"}
SUBSCHEMA_SINGLE = {"not", "if", "then", "else", "items",
                    "additionalProperties"}

NEKO_REF = re.compile(r"^urn:neko:schema:[a-z_:-]+#/\$defs/\w+$")
NEKO_ROOT = vcs.ROOT_IDS["neko"]


def walk(schema: Any, path: str = "#") -> Iterator[tuple[str, dict]]:
    """Yield (path, subschema) for every subschema, boolean ones skipped."""
    if not isinstance(schema, dict):
        return
    yield path, schema
    for key, value in schema.items():
        if key in SUBSCHEMA_MAPS and isinstance(value, dict):
            for name, sub in value.items():
                yield from walk(sub, f"{path}/{key}/{name}")
        elif key in SUBSCHEMA_LISTS and isinstance(value, list):
            for i, sub in enumerate(value):
                yield from walk(sub, f"{path}/{key}/{i}")
        elif key in SUBSCHEMA_SINGLE:
            yield from walk(value, f"{path}/{key}")


def test_schemas_exist(top_schemas):
    assert vcs.ROOT_IDS["neko-top"] in top_schemas


def test_check_schema(top_schemas):
    for schema_id, schema in top_schemas.items():
        cls = jsonschema.validators.validator_for(
            schema, default=jsonschema.Draft202012Validator
        )
        assert cls is jsonschema.Draft202012Validator, schema_id
        cls.check_schema(schema)


def test_id_matches_path(top_dir, top_schemas):
    for path in top_dir.rglob("*.schema.json"):
        relative = path.relative_to(top_dir).as_posix()
        stem = relative[: -len(".schema.json")]
        expected = vcs.TOP_PREFIX + stem.replace("/", ":")
        found = [
            sid for sid, s in top_schemas.items()
            if s.get("$id") == expected
        ]
        assert found, f"{relative}: $id must be {expected}"


def test_only_top_level_id(top_schemas):
    for schema_id, schema in top_schemas.items():
        for path, sub in walk(schema):
            if path != "#":
                assert "$id" not in sub, f"{schema_id}: $id at {path}"
                assert "$schema" not in sub, f"{schema_id}: $schema at {path}"


def test_every_ref_resolves(registry, top_schemas):
    for schema_id, schema in top_schemas.items():
        resolver = registry.resolver(base_uri=schema_id)
        for ref in vcs.iter_refs(schema):
            try:
                resolver.lookup(ref)
            except Unresolvable as exc:
                pytest.fail(f"{schema_id}: {ref} does not resolve: {exc}")


def test_refs_are_absolute_urns_or_local(top_schemas):
    for schema_id, schema in top_schemas.items():
        for ref in vcs.iter_refs(schema):
            assert (
                ref.startswith("#/$defs/")
                or ref.startswith(vcs.TOP_PREFIX)
                or ref.startswith(vcs.NEKO_PREFIX)
            ), f"{schema_id}: unexpected $ref {ref}"


def test_refs_into_neko_are_defs_or_root(top_schemas):
    for schema_id, schema in top_schemas.items():
        for ref in vcs.iter_refs(schema):
            if ref.startswith(vcs.NEKO_PREFIX):
                assert ref == NEKO_ROOT or NEKO_REF.match(ref), (
                    f"{schema_id}: {ref} is neither a Neko $defs entry "
                    "nor Neko's root"
                )


def test_keyword_whitelist(top_schemas):
    for schema_id, schema in top_schemas.items():
        for path, sub in walk(schema):
            unknown = set(sub) - ALLOWED_KEYWORDS
            assert not unknown, (
                f"{schema_id} {path}: unsupported keyword(s) "
                f"{sorted(unknown)}"
            )


def test_boolean_subschemas_are_allowed():
    """The whitelist walk must tolerate boolean schemas (`false`/`true`)."""
    assert list(walk({"properties": {"a": False, "b": True}})) == [
        ("#", {"properties": {"a": False, "b": True}})
    ]


def test_whitelist_walk_flags_unknown_keyword():
    """The whitelist check can fail: an unevaluatedProperties is found."""
    schema = {"allOf": [{"unevaluatedProperties": False}]}
    unknown = [
        set(sub) - ALLOWED_KEYWORDS for _, sub in walk(schema)
    ]
    assert {"unevaluatedProperties"} in unknown


def test_fallback_canary(registry):
    """Neko's simulation-component union admits a registered type.

    Neko-TOP's `steady` is registered through Neko's extension mechanism; if
    this fails the Neko schemas lack the registered-type fallback.
    """
    union = vcs.strict_validator_class()(
        {"$ref": vcs.SIMCOMP_UNION}, registry=registry
    )
    assert union.is_valid({"type": "steady"})


def test_root_delegates_to_neko(validator):
    """The collected root accepts and rejects what Neko's root does."""
    assert not validator.is_valid({})
    assert not validator.is_valid({"case": 1})
