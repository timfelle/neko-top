"""Exit codes and behaviour of scripts/python/validate_case_schema.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import validate_case_schema as vcs

SCRIPT = Path(vcs.__file__).resolve()
TOP_ROOT = SCRIPT.parents[2]
GOOD_CASE = TOP_ROOT / "tests/schema/fixtures/topopt_steady.case"


def run(*args, env=None, cwd=None):
    """Run the validator; returns the CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, text=True, env=env, cwd=cwd,
    )


@pytest.fixture(scope="module")
def neko_dir(loaded):
    return loaded.neko_dir


@pytest.fixture()
def clean_env():
    """The environment without any variable the discovery looks at."""
    env = dict(os.environ)
    for name in ("NEKO_SCHEMA_DIR", "NEKO_DIR", "NEKO_TOP_SCHEMA_DIR"):
        env.pop(name, None)
    return env


def fake_neko_dir(path: Path) -> Path:
    """A directory that passes the discovery check (the id is all it needs)."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "case-file.schema.json").write_text(
        json.dumps({"$id": vcs.ROOT_IDS["neko"]})
    )
    return path


def write_case(tmp_path, text, name="x.case"):
    path = tmp_path / name
    path.write_text(text)
    return path


# ---------------------------------------------------------------- exit codes #


def test_exit_0_valid_case(neko_dir):
    result = run("--neko-schema-dir", neko_dir, GOOD_CASE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"OK   {GOOD_CASE}" in result.stdout
    assert "Validated 1 file(s)." in result.stdout


def test_exit_1_invalid_case(neko_dir, tmp_path):
    case = write_case(tmp_path, '{"case": 1}')
    result = run("--neko-schema-dir", neko_dir, case)
    assert result.returncode == 1
    assert f"FAIL {case}" in result.stdout
    assert "at $.case" in result.stdout
    assert "1 of 1 file(s) failed validation." in result.stderr


def test_directories_are_searched_for_case_files(neko_dir, tmp_path):
    (tmp_path / "sub").mkdir()
    write_case(tmp_path / "sub", '{"case": 1}', "a.case")
    write_case(tmp_path, '{"case": 1}', "ignored.json")
    result = run("--neko-schema-dir", neko_dir, tmp_path)
    assert result.returncode == 1
    assert "a.case" in result.stdout
    assert "ignored.json" not in result.stdout


def test_exit_2_usage(neko_dir, tmp_path):
    assert run("--neko-schema-dir", neko_dir).returncode == 2
    assert run("--bogus", GOOD_CASE).returncode == 2
    missing = run("--neko-schema-dir", neko_dir, tmp_path / "nope.case")
    assert missing.returncode == 2
    empty = run("--neko-schema-dir", neko_dir, tmp_path)
    assert empty.returncode == 2
    assert "No case files found" in empty.stderr


def test_exit_3_no_neko_schemas(tmp_path, clean_env):
    result = run("--neko-schema-dir", tmp_path, GOOD_CASE, env=clean_env)
    assert result.returncode == 3
    assert "holds no Neko case-file.schema.json" in result.stderr


def test_exit_3_when_nothing_is_found(clean_env):
    # An empty PATH keeps pkg-config from finding some other Neko.
    clean_env["PATH"] = ""
    result = run(GOOD_CASE, env=clean_env)
    assert result.returncode == 3
    assert "not found" in result.stderr


def test_exit_3_without_the_simcomp_fallback(neko_dir, tmp_path):
    """Neko schemas lacking the registered-type fallback are too old."""
    old = without_fallback(neko_dir, tmp_path / "neko")
    result = run("--neko-schema-dir", old, GOOD_CASE)
    assert result.returncode == 3
    assert "registered-type fallback" in result.stderr


def dangling_top_dir(tmp_path: Path) -> Path:
    """A Neko-TOP schema directory whose root refers to a Neko definition
    that does not exist."""
    top = tmp_path / "top"
    top.mkdir()
    (top / "case-file.schema.json").write_text(json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": vcs.ROOT_IDS["neko-top"],
        "allOf": [
            {"$ref": vcs.NEKO_PREFIX + "common#/$defs/noSuchDefinition"}
        ],
    }))
    return top


def without_fallback(neko_dir: Path, destination: Path) -> Path:
    """A copy of Neko's schemas without the registered-type fallback."""
    shutil.copytree(neko_dir, destination)
    path = destination / "simulation-components.schema.json"
    schema = json.loads(path.read_text())
    union = schema["$defs"]["simulationComponent"]["oneOf"]
    kept = [
        branch for branch in union
        if "registered through the extension mechanism"
        not in branch.get("description", "")
    ]
    assert len(kept) == len(union) - 1, "fallback branch not found"
    schema["$defs"]["simulationComponent"]["oneOf"] = kept
    path.write_text(json.dumps(schema))
    return destination


def test_exit_1_dangling_neko_def_in_a_new_enough_neko(neko_dir, tmp_path):
    """A Neko-TOP reference to a Neko definition that is missing, in a Neko
    that has the registered-type fallback, is a mistake in Neko-TOP's own
    schemas: exit 1, not the exit 3 (skip) of a Neko that is too old."""
    top = dangling_top_dir(tmp_path)
    result = run("--neko-schema-dir", neko_dir, "--schema-dir", top, GOOD_CASE)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "no such Neko definition" in result.stderr
    assert "although it has the registered-type fallback" in result.stderr


def test_exit_3_dangling_neko_def_in_an_old_neko(neko_dir, tmp_path):
    """The same reference, in a Neko without the fallback, means the Neko is
    too old: exit 3, with both problems listed."""
    old = without_fallback(neko_dir, tmp_path / "neko")
    top = dangling_top_dir(tmp_path)
    result = run("--neko-schema-dir", old, "--schema-dir", top, GOOD_CASE)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "too old" in result.stderr
    assert "registered-type fallback" in result.stderr
    assert "no such Neko definition" in result.stderr


def test_probe_returns_old_neko_and_typo_problems_apart(registry, schemas):
    """probe() returns `(too_old, typos)`; both are empty for a compatible
    Neko."""
    assert vcs.probe(registry, schemas) == ([], [])


def test_load_all_raises_the_matching_error(neko_dir, tmp_path):
    """load_all() raises SchemaSetupError for a Neko that is too old and
    TopSchemaError for a Neko-TOP typo."""
    top = dangling_top_dir(tmp_path)
    with pytest.raises(vcs.TopSchemaError):
        vcs.load_all(str(top), str(neko_dir))
    old = without_fallback(neko_dir, tmp_path / "neko")
    with pytest.raises(vcs.SchemaSetupError):
        vcs.load_all(str(top), str(old))


def test_duplicate_schema_ids_are_rejected(neko_dir, tmp_path):
    top = tmp_path / "top"
    top.mkdir()
    for name in ("case-file", "other"):
        (top / f"{name}.schema.json").write_text(json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": vcs.ROOT_IDS["neko-top"],
        }))
    result = run("--neko-schema-dir", neko_dir, "--schema-dir", top, GOOD_CASE)
    assert result.returncode == 3
    assert "duplicate schema $id" in result.stderr


def test_wrong_id_namespace_is_rejected(neko_dir, tmp_path):
    top = tmp_path / "top"
    top.mkdir()
    (top / "case-file.schema.json").write_text(json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": vcs.ROOT_IDS["neko-top"],
    }))
    (top / "stray.schema.json").write_text(json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:neko:schema:stray",
    }))
    result = run("--neko-schema-dir", neko_dir, "--schema-dir", top, GOOD_CASE)
    assert result.returncode == 3
    assert "$id must start with urn:neko-top:schema:" in result.stderr


def test_invalid_schema_file_is_rejected(neko_dir, tmp_path):
    top = tmp_path / "top"
    top.mkdir()
    (top / "case-file.schema.json").write_text(json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": vcs.ROOT_IDS["neko-top"],
        "type": "no-such-type",
    }))
    result = run("--neko-schema-dir", neko_dir, "--schema-dir", top, GOOD_CASE)
    assert result.returncode == 3
    assert "not a valid schema" in result.stderr


# ----------------------------------------------------------------- discovery #


def printed_neko(result) -> str:
    assert result.returncode == 0, result.stdout + result.stderr
    line = [x for x in result.stdout.splitlines()
            if x.startswith("neko schemas:")]
    return line[0].split(":", 1)[1].strip()


def test_discovery_order(tmp_path, clean_env):
    flag = fake_neko_dir(tmp_path / "flag")
    env_dir = fake_neko_dir(tmp_path / "env")
    prefix = tmp_path / "prefix"
    share = fake_neko_dir(prefix / "share/neko/schemas")
    doc = fake_neko_dir(prefix / "doc/schemas")

    both = dict(clean_env, NEKO_SCHEMA_DIR=str(env_dir), NEKO_DIR=str(prefix))
    result = run("--print-dirs", "--neko-schema-dir", flag, env=both)
    assert printed_neko(result) == f"{flag.resolve()} (--neko-schema-dir)"

    result = run("--print-dirs", env=both)
    assert printed_neko(result) == f"{env_dir.resolve()} ($NEKO_SCHEMA_DIR)"

    only_prefix = dict(clean_env, NEKO_DIR=str(prefix))
    result = run("--print-dirs", env=only_prefix)
    assert printed_neko(result) == (
        f"{share.resolve()} ($NEKO_DIR/share/neko/schemas)"
    )

    shutil.rmtree(prefix / "share")
    result = run("--print-dirs", env=only_prefix)
    assert printed_neko(result) == f"{doc.resolve()} ($NEKO_DIR/doc/schemas)"


def test_bad_flag_does_not_fall_through(tmp_path, clean_env):
    good = fake_neko_dir(tmp_path / "good")
    env = dict(clean_env, NEKO_SCHEMA_DIR=str(good))
    result = run("--print-dirs", "--neko-schema-dir", tmp_path / "nowhere",
                 env=env)
    assert result.returncode == 3


def test_top_schema_dir_discovery(tmp_path, clean_env, neko_dir):
    result = run("--print-dirs", "--neko-schema-dir", neko_dir, env=clean_env)
    assert result.returncode == 0
    assert "documentation/schemas (source tree)" in result.stdout
    top = tmp_path / "top"
    top.mkdir()
    (top / "case-file.schema.json").write_text(
        json.dumps({"$id": vcs.ROOT_IDS["neko-top"]})
    )
    env = dict(clean_env, NEKO_TOP_SCHEMA_DIR=str(top))
    result = run("--print-dirs", "--neko-schema-dir", neko_dir, env=env)
    assert f"{top.resolve()} ($NEKO_TOP_SCHEMA_DIR)" in result.stdout


# -------------------------------------------------------------------- syntax #


def test_duplicate_keys_are_rejected(neko_dir, tmp_path):
    case = write_case(tmp_path, '{"case": {"a": 1, "a": 2}}')
    result = run("--neko-schema-dir", neko_dir, case)
    assert result.returncode == 1
    assert 'Duplicate key "a"' in result.stdout


def test_strict_syntax_catches_json5_only_construct(neko_dir, tmp_path):
    text = GOOD_CASE.read_text()
    assert '"case"' in text
    unquoted = write_case(tmp_path, text.replace('"case"', "case", 1))
    relaxed = run("--neko-schema-dir", neko_dir, unquoted)
    assert relaxed.returncode == 0, relaxed.stdout + relaxed.stderr
    strict = run("--neko-schema-dir", neko_dir, "--strict-syntax", unquoted)
    assert strict.returncode == 1
    assert "accepted by json5 but not by json-fortran" in strict.stdout


def test_strict_syntax_accepts_what_json_fortran_reads(neko_dir, tmp_path):
    """Comments and trailing commas, which json-fortran reads, are fine."""
    text = GOOD_CASE.read_text()
    case = write_case(
        tmp_path,
        text.replace("{", '{ // a comment\n', 1) + "\n",
    )
    result = run("--neko-schema-dir", neko_dir, "--strict-syntax", case)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("comment", ["#", "!"])
def test_line_comment_message(neko_dir, tmp_path, comment):
    """json5 rejects `#` and `!` comments; the message says json-fortran
    would read the file and what to pass to check it that way."""
    text = GOOD_CASE.read_text()
    case = write_case(tmp_path, f"{comment} a comment\n{text}")
    result = run("--neko-schema-dir", neko_dir, case)
    assert result.returncode == 1
    assert "json-fortran accepts this file" in result.stdout
    assert "--strict-syntax" in result.stdout


def test_strip_keeps_comment_characters_inside_strings():
    text = '{"a": "x // y ! z # w", // c\n "b": [1, 2,],}'
    assert vcs.parse_fortran_json(text) == {"a": "x // y ! z # w", "b": [1, 2]}


def test_fortran_loader_rejects_nan_and_duplicates():
    with pytest.raises(ValueError):
        vcs.parse_fortran_json('{"a": NaN}')
    with pytest.raises(ValueError):
        vcs.parse_fortran_json('{"a": 1, "a": 2}')


# -------------------------------------------------------------- error output #


def test_all_errors_lists_more_than_the_best_match(neko_dir, tmp_path):
    case = write_case(tmp_path, '{"case": 1, "version": "x"}')
    best = run("--neko-schema-dir", neko_dir, case)
    every = run("--neko-schema-dir", neko_dir, "--all-errors", case)
    assert best.returncode == every.returncode == 1
    assert every.stdout.count("     at ") > best.stdout.count("     at ")


def test_strict_integer_and_real_keywords(registry, schemas):
    """x-neko-real and the strict integer type are in force."""
    cls = vcs.strict_validator_class()
    real = cls({"x-neko-real": True})
    assert not real.is_valid(1)
    assert real.is_valid(1.0)
    assert not cls({"type": "integer"}).is_valid(1.0)
    assert cls({"type": "integer"}).is_valid(1)
