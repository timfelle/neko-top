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


# --------------------------------------------------------------------------- #
# Reuse of Neko's definitions
# --------------------------------------------------------------------------- #
ANNOTATION_STRINGS = {"description", "$comment", "title"}
ANNOTATIONS_DROPPED = {"default", "examples", "deprecated", "format"}

#: Subschemas of Neko-TOP's schemas that equal a Neko definition without
#: copying it: (schema id, path) -> why. Empty unless a coincidence is real.
ALLOWED_COINCIDENCES: dict[tuple[str, str], str] = {}


def normalised(node: Any, base: str) -> Any:
    """`node` without annotations and with local refs made absolute."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in ANNOTATIONS_DROPPED:
                continue
            if key in ANNOTATION_STRINGS and isinstance(value, str):
                continue
            if key == "$ref" and isinstance(value, str) \
                    and value.startswith("#"):
                value = base + value
            if key in ("const", "enum", "required"):
                out[key] = value
            else:
                out[key] = normalised(value, base)
        return out
    if isinstance(node, list):
        return [normalised(item, base) for item in node]
    return node


def neko_definitions(schemas):
    out = {}
    for schema_id, schema in schemas.items():
        if schema_id.startswith(vcs.NEKO_PREFIX):
            for name, definition in schema.get("$defs", {}).items():
                out[f"{schema_id}#/$defs/{name}"] = normalised(
                    definition, schema_id)
    return out


def test_no_copied_neko_definitions(schemas, top_schemas):
    """A subschema that equals one of Neko's definitions is a `$ref` to it,
    not a copy (a bare `$ref` is the reuse and is skipped)."""
    neko = neko_definitions(schemas)
    copies = []
    for schema_id, schema in top_schemas.items():
        for path, sub in walk(schema):
            if "$ref" in sub or len(sub) == 0:
                continue
            flat = normalised(sub, schema_id)
            if not flat:
                continue
            for ref, definition in neko.items():
                if flat == definition and \
                        (schema_id, path) not in ALLOWED_COINCIDENCES:
                    copies.append(f"{schema_id} {path} equals {ref}")
    assert not copies, "\n".join(copies)


def test_the_copy_check_can_fail(schemas):
    """A schema holding a copy of a Neko definition is reported."""
    neko = neko_definitions(schemas)
    copy_of = dict(schemas[vcs.NEKO_PREFIX + "common"]["$defs"][
        "positiveInteger"])
    flat = normalised({"description": "mine", **copy_of}, "urn:x")
    assert any(flat == definition for definition in neko.values())


# The Neko objects that Neko-TOP adds keys under. They are open in Neko
# (`additionalProperties` true), as they have to be for the additions to be
# accepted by Neko's own root as well: (schema, definition or None for the
# root, what Neko-TOP adds there).
EXTENSION_POINTS = [
    ("case-file", None, "optimization, unsteady, state_recovery, ..."),
    ("case-file", "case", "adjoint_fluid, adjoint_scalar, ..."),
    ("fluid", "fluid", "freeze_flow, source_terms overlay"),
    ("scalar", "scalarField", "source_terms overlay"),
    ("simulation-components", "simcompBase", "steady's keys"),
]


@pytest.mark.parametrize("schema, name, what", EXTENSION_POINTS,
                         ids=[f"{s}:{n or 'root'}" for s, n, _ in
                              EXTENSION_POINTS])
def test_extension_points_are_open_in_neko(schemas, schema, name, what):
    node = schemas[vcs.NEKO_PREFIX + schema]
    if name is not None:
        node = node["$defs"][name]
    assert node.get("additionalProperties") is True, (
        f"Neko's {schema} {name or 'root'} is closed: Neko-TOP cannot add "
        f"{what} below it without widening it")


def test_neko_top_does_not_add_keys_under_closed_neko_objects(
        schemas, top_schemas):
    """The only Neko objects Neko-TOP's `properties` land on are the open
    ones listed above: `case.numerics` is closed in Neko and gets no key."""
    numerics = schemas[vcs.NEKO_PREFIX + "numerics"]["$defs"]["numerics"]
    assert numerics["additionalProperties"] is False
    root = top_schemas[vcs.TOP_PREFIX + "case-file"]
    case = root["$defs"]["case"]["properties"]
    assert "numerics" not in case and "time" not in case
