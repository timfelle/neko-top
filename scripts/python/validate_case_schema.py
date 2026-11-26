#!/usr/bin/env python3
"""Validate Neko-TOP case files against the Neko-TOP JSON Schemas.

Adapted from Neko's contrib/validate_case_schema.py. Keep the `x-neko-real`
keyword and the strict `integer` type in sync with it: they mirror how Neko's
JSON reader tells reals and integers apart.

The Neko-TOP schemas extend Neko's, so the registry holds the schemas of both
projects, each keyed by its declared `$id`. Neko's schemas are not copied: they
are read from a Neko install (or source tree) found at run time.

Exit codes: 0 all files valid, 1 a file failed (or Neko-TOP's own schemas
are broken, see TopSchemaError), 2 usage error, 3 Neko's schemas are missing
or too old for Neko-TOP's.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

try:
    import json5
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        f"Missing dependency: {exc.name}. "
        "Install it with: pip install jsonschema referencing json5"
    ) from exc

NEKO_PREFIX = "urn:neko:schema:"
TOP_PREFIX = "urn:neko-top:schema:"
ROOT_IDS = {
    "neko-top": TOP_PREFIX + "case-file",
    "neko": NEKO_PREFIX + "case-file",
}
SIMCOMP_UNION = NEKO_PREFIX + "simulation-components#/$defs/simulationComponent"
SCRIPT = Path(__file__).resolve()

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_SCHEMAS = 0, 1, 2, 3


class SchemaSetupError(Exception):
    """The schemas are missing, malformed or too old (exit code 3).

    Raised when Neko's schemas cannot be used: not found, not valid, or
    lacking the registered-type fallback that Neko-TOP's schemas rely on, so
    that the fault is in the Neko found rather than in Neko-TOP's schemas.
    """


class TopSchemaError(Exception):
    """Neko-TOP's own schemas are broken (exit code 1).

    Raised when Neko's schemas do have the registered-type fallback, so they
    are new enough, yet a Neko-TOP schema refers to a Neko schema or
    definition that does not exist: a mistake in Neko-TOP's schemas.
    """


# --------------------------------------------------------------------------- #
# Validator classes (kept in sync with Neko's contrib/validate_case_schema.py)
# --------------------------------------------------------------------------- #


def validate_neko_real(validator, expected, instance, schema):
    """Require a JSON real, rather than an integer-valued JSON number."""
    if (
        expected
        and isinstance(instance, (int, float))
        and not isinstance(instance, (bool, float))
    ):
        yield jsonschema.ValidationError(
            f"{instance!r} is not encoded as a JSON real"
        )


def strict_validator_class():
    """Draft 2020-12 with `x-neko-real` and Neko's strict integer type."""
    base = jsonschema.Draft202012Validator
    # JSON Schema treats integral-valued reals such as 10.0 as integers. Neko's
    # JSON reader distinguishes the stored JSON types, however, and rejects
    # 10.0 where an integer is requested. Match Neko's stricter behavior.
    strict_type_checker = base.TYPE_CHECKER.redefine(
        "integer",
        lambda checker, instance: (
            isinstance(instance, int) and not isinstance(instance, bool)
        ),
    )
    return jsonschema.validators.extend(
        base,
        validators={"x-neko-real": validate_neko_real},
        type_checker=strict_type_checker,
    )


# --------------------------------------------------------------------------- #
# Schema directory discovery
# --------------------------------------------------------------------------- #


def _read_id(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle).get("$id")
    except (OSError, ValueError, AttributeError):
        return None


def _is_neko_dir(path: Path) -> bool:
    return _read_id(path / "case-file.schema.json") == ROOT_IDS["neko"]


def _is_top_dir(path: Path) -> bool:
    return _read_id(path / "case-file.schema.json") == ROOT_IDS["neko-top"]


def _pkg_config_prefix() -> str | None:
    try:
        out = subprocess.run(
            ["pkg-config", "--variable=prefix", "neko"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def find_neko_schema_dir(explicit: str | None = None) -> tuple[Path, str]:
    """Locate Neko's schema directory; return (directory, where from).

    The first candidate that holds Neko's `case-file.schema.json` wins. An
    explicit flag or `$NEKO_SCHEMA_DIR` that is not such a directory is an
    error rather than a reason to fall through to a different Neko.
    """
    strict = [("--neko-schema-dir", explicit),
              ("$NEKO_SCHEMA_DIR", os.environ.get("NEKO_SCHEMA_DIR"))]
    for source, value in strict:
        if value:
            if not _is_neko_dir(Path(value)):
                raise SchemaSetupError(
                    f"{source}={value} holds no Neko case-file.schema.json "
                    f"(expected $id {ROOT_IDS['neko']})."
                )
            return Path(value).resolve(), source

    candidates: list[tuple[str, Path]] = []
    neko_dir = os.environ.get("NEKO_DIR")
    if neko_dir:
        candidates.append(("$NEKO_DIR/share/neko/schemas",
                           Path(neko_dir) / "share/neko/schemas"))
        candidates.append(("$NEKO_DIR/doc/schemas",
                           Path(neko_dir) / "doc/schemas"))
    prefix = _pkg_config_prefix()
    if prefix:
        candidates.append(("pkg-config neko",
                           Path(prefix) / "share/neko/schemas"))
    for source, path in candidates:
        if _is_neko_dir(path):
            return path.resolve(), source
    tried = ", ".join(str(p) for _, p in candidates) or "nothing to try"
    raise SchemaSetupError(
        "Neko's schemas were not found (tried: "
        f"{tried}). Pass --neko-schema-dir, or set NEKO_SCHEMA_DIR or "
        "NEKO_DIR."
    )


def find_top_schema_dir(explicit: str | None = None) -> tuple[Path, str]:
    """Locate Neko-TOP's schema directory; return (directory, where from)."""
    strict = [("--schema-dir", explicit),
              ("$NEKO_TOP_SCHEMA_DIR", os.environ.get("NEKO_TOP_SCHEMA_DIR"))]
    for source, value in strict:
        if value:
            if not _is_top_dir(Path(value)):
                raise SchemaSetupError(
                    f"{source}={value} holds no Neko-TOP case-file.schema.json"
                    f" (expected $id {ROOT_IDS['neko-top']})."
                )
            return Path(value).resolve(), source
    for source, path in (
        ("source tree", SCRIPT.parents[2] / "documentation" / "schemas"),
        ("installed layout", SCRIPT.parent / "schemas"),
    ):
        if _is_top_dir(path):
            return path.resolve(), source
    raise SchemaSetupError(
        "Neko-TOP's schemas were not found next to this script. "
        "Pass --schema-dir or set NEKO_TOP_SCHEMA_DIR."
    )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def _load_dir(directory: Path, prefix: str, schemas: dict[str, Any]) -> None:
    for path in sorted(directory.rglob("*.schema.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                schema = json.load(handle)
        except ValueError as exc:
            raise SchemaSetupError(f"{path}: not valid JSON: {exc}") from exc
        schema_id = schema.get("$id") if isinstance(schema, dict) else None
        if not isinstance(schema_id, str) or not schema_id.startswith(prefix):
            raise SchemaSetupError(
                f"{path}: $id must start with {prefix}, got {schema_id!r}."
            )
        if schema_id in schemas:
            raise SchemaSetupError(f"{path}: duplicate schema $id {schema_id}.")
        try:
            jsonschema.validators.validator_for(
                schema, default=jsonschema.Draft202012Validator
            ).check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise SchemaSetupError(
                f"{path}: not a valid schema: {exc.message}"
            ) from exc
        schemas[schema_id] = schema


def load_registry(
    neko_dir: Path, top_dir: Path
) -> tuple[Registry, dict[str, Any]]:
    """Register every schema of both projects under its declared `$id`.

    Returns the registry and a dict `$id -> schema`.
    """
    schemas: dict[str, Any] = {}
    _load_dir(Path(neko_dir), NEKO_PREFIX, schemas)
    _load_dir(Path(top_dir), TOP_PREFIX, schemas)
    registry = Registry()
    for schema_id, schema in schemas.items():
        # `Validator.evolve()` re-picks the validator class with
        # `validator_for(schema, default=cls)` whenever a `$ref` descends into
        # a whole resource, and an explicit `$schema` 2020-12 (Neko's schemas
        # declare it) would swap in the stock `Draft202012Validator`,
        # silently dropping `x-neko-real` and the strict integer type below
        # that point. The registered copy therefore omits `$schema`, so the
        # class chosen by the caller is kept for every resource. The dialect
        # stays 2020-12 through `default_specification`; `schemas` itself
        # keeps the files as read.
        contents = {k: v for k, v in schema.items() if k != "$schema"}
        registry = registry.with_resource(
            schema_id,
            Resource.from_contents(
                contents, default_specification=DRAFT202012
            ),
        )
    return registry, schemas


def iter_refs(node: Any) -> Iterator[str]:
    """Yield every `$ref` string below a schema (keyword positions only)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            elif key in ("const", "enum", "default", "examples", "required"):
                continue
            else:
                yield from iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_refs(item)


def make_validator(registry: Registry, schemas: dict[str, Any], root: str):
    """Validator for the root schema `root` ('neko-top' or 'neko')."""
    return strict_validator_class()(
        schemas[ROOT_IDS[root]], registry=registry
    )


def probe(
    registry: Registry, schemas: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Check Neko's schemas are compatible with Neko-TOP's.

    Returns `(too_old, typos)`, both empty when compatible.

    `too_old` holds the problems that mean the Neko found is not new enough:
    its simulation-component union lacks the registered-type fallback that
    admits `steady`. When that is the case a Neko definition that Neko-TOP
    refers to is expected to be missing too, so such references are listed
    there as well.

    `typos` holds, only for a Neko that has the fallback, the references from
    a Neko-TOP schema to a Neko schema or definition that does not exist.
    That is a mistake in Neko-TOP's schemas, not a Neko that is too old.
    """
    missing: list[str] = []
    for schema_id, schema in schemas.items():
        if not schema_id.startswith(TOP_PREFIX):
            continue
        for ref in iter_refs(schema):
            if not ref.startswith(NEKO_PREFIX):
                continue
            target, _, fragment = ref.partition("#")
            if target not in schemas:
                missing.append(f"{schema_id}: {ref}: no such Neko schema")
                continue
            if not fragment:
                continue
            try:
                registry.resolver(base_uri=target).lookup("#" + fragment)
            except Exception:  # noqa: BLE001 - any lookup failure counts
                missing.append(f"{schema_id}: {ref}: no such Neko definition")
    too_old: list[str] = []
    cls = strict_validator_class()
    union = cls({"$ref": SIMCOMP_UNION}, registry=registry)
    try:
        accepted = union.is_valid({"type": "steady"})
    except Exception as exc:  # noqa: BLE001
        too_old.append(f"{SIMCOMP_UNION}: cannot be evaluated: {exc}")
    else:
        if not accepted:
            too_old.append(
                f"{SIMCOMP_UNION} rejects {{'type': 'steady'}}: Neko's "
                "schemas lack the registered-type fallback for simulation "
                "components."
            )
    if too_old:
        return too_old + missing, []
    return [], missing


def load_all(
    schema_dir: str | None = None,
    neko_schema_dir: str | None = None,
    root: str = "neko-top",
):
    """Discover, load and probe. Returns a namespace with everything."""
    neko_dir, neko_src = find_neko_schema_dir(neko_schema_dir)
    top_dir, top_src = find_top_schema_dir(schema_dir)
    registry, schemas = load_registry(neko_dir, top_dir)
    too_old, typos = probe(registry, schemas)
    if too_old:
        raise SchemaSetupError(
            f"Neko's schemas in {neko_dir} are too old for Neko-TOP's:\n"
            + "\n".join("  " + p for p in too_old)
        )
    if typos:
        raise TopSchemaError(
            f"Neko-TOP's schemas in {top_dir} refer to Neko schemas that "
            f"{neko_dir} does not have, although it has the registered-type "
            "fallback:\n" + "\n".join("  " + p for p in typos)
        )
    return argparse.Namespace(
        registry=registry, schemas=schemas,
        validator=make_validator(registry, schemas, root),
        neko_dir=neko_dir, neko_source=neko_src,
        top_dir=top_dir, top_source=top_src,
    )


# --------------------------------------------------------------------------- #
# Case-file parsing
# --------------------------------------------------------------------------- #


def strip_fortran_json(text: str) -> str:
    """Reduce text to what json-fortran reads: strip `//`, `!` and `#` line
    comments outside strings, and trailing commas."""
    out: list[str] = []
    in_string = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif ch in "!#" or text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif ch in "}]":
            # Drop a trailing comma, keeping the whitespace after it.
            j = len(out) - 1
            while j >= 0 and out[j].isspace():
                j -= 1
            if j >= 0 and out[j] == ",":
                del out[j]
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate key "{key}" found in object')
        result[key] = value
    return result


def _reject_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def parse_fortran_json(text: str) -> Any:
    """Parse the way json-fortran does (no NaN, no duplicate keys)."""
    return json.loads(
        strip_fortran_json(text),
        object_pairs_hook=_no_duplicates,
        parse_constant=_reject_constant,
    )


def parse_case(path: Path, strict_syntax: bool = False) -> Any:
    """Parse a case file with json5, rejecting duplicate keys.

    With `strict_syntax` the file must also parse with the json-fortran
    compatible loader, so anything only json5 accepts is an error.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json5.load(io.StringIO(text), allow_duplicate_keys=False)
    except ValueError as exc:
        hint = ""
        try:
            parse_fortran_json(text)
        except ValueError:
            pass
        else:
            hint = (
                " (json-fortran accepts this file: a '!' or '#' comment is "
                "not json5 syntax; pass --strict-syntax to check the file "
                "the way json-fortran reads it)"
            )
        raise ValueError(f"{exc}{hint}") from exc
    if strict_syntax:
        try:
            parse_fortran_json(text)
        except ValueError as exc:
            raise ValueError(
                f"accepted by json5 but not by json-fortran: {exc}"
            ) from exc
    return data


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def leaf_errors(error: jsonschema.ValidationError):
    """Yield the leaf errors below `error` (itself if it has no context)."""
    if error.context:
        for child in error.context:
            yield from leaf_errors(child)
    else:
        yield error


def validate_instance(
    validator, instance: Any, all_errors: bool = False
) -> list[tuple[str, str]]:
    """Return [(json path, message)] for the instance; empty when valid."""
    if all_errors:
        errors = [e for top in validator.iter_errors(instance)
                  for e in leaf_errors(top)]
    else:
        best = jsonschema.exceptions.best_match(validator.iter_errors(instance))
        errors = [best] if best is not None else []
    return [(e.json_path, e.message) for e in errors]


def iter_case_files(paths: list[str]) -> list[Path]:
    files: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.update(path.rglob("*.case"))
        elif path.is_file():
            files.add(path)
        else:
            raise FileNotFoundError(raw)
    return sorted(files)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Neko-TOP case files with a JSON5-compatible frontend "
            "and the Neko-TOP schemas (which extend Neko's)."
        )
    )
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="Case files, or directories searched "
                        "recursively for *.case.")
    parser.add_argument("--schema-dir", help="Neko-TOP's schema directory.")
    parser.add_argument("--neko-schema-dir",
                        help="Neko's schema directory (default: "
                        "$NEKO_SCHEMA_DIR, then $NEKO_DIR, then pkg-config).")
    parser.add_argument("--root", choices=sorted(ROOT_IDS), default="neko-top",
                        help="Root schema to validate against.")
    parser.add_argument("--all-errors", action="store_true",
                        help="List every leaf error, not only the best match.")
    parser.add_argument("--strict-syntax", action="store_true",
                        help="Also require json-fortran-compatible syntax.")
    parser.add_argument("--print-dirs", action="store_true",
                        help="Print the schema directories in use and exit.")
    args = parser.parse_args(argv)
    if not args.paths and not args.print_dirs:
        parser.error("at least one PATH is required")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.print_dirs:
            neko_dir, neko_src = find_neko_schema_dir(args.neko_schema_dir)
            top_dir, top_src = find_top_schema_dir(args.schema_dir)
            print(f"neko-top schemas: {top_dir} ({top_src})")
            print(f"neko schemas:     {neko_dir} ({neko_src})")
            return EXIT_OK
        loaded = load_all(args.schema_dir, args.neko_schema_dir, args.root)
    except SchemaSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SCHEMAS
    except TopSchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED
    try:
        case_files = iter_case_files(args.paths)
    except FileNotFoundError as exc:
        print(f"error: no such file or directory: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not case_files:
        print("No case files found.", file=sys.stderr)
        return EXIT_USAGE

    failures = 0
    for case_file in case_files:
        try:
            data = parse_case(case_file, args.strict_syntax)
        except (ValueError, OSError) as exc:
            failures += 1
            print(f"FAIL {case_file}")
            print(f"     {exc}")
            continue
        errors = validate_instance(loaded.validator, data, args.all_errors)
        if not errors:
            print(f"OK   {case_file}")
            continue
        failures += 1
        print(f"FAIL {case_file}")
        for json_path, message in errors:
            print(f"     {message}")
            print(f"     at {json_path}")

    if failures:
        print(f"{failures} of {len(case_files)} file(s) failed validation.",
              file=sys.stderr)
        return EXIT_FAILED
    print(f"Validated {len(case_files)} file(s).")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
