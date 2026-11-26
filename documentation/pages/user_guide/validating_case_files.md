# Validating a case file {#validating_case_files}

\tableofcontents

Neko-TOP ships JSON Schemas for its case files, and a small command-line tool
that checks a case file against them before a run is started. A mistyped key, a
value of the wrong type, a missing required key or a combination of settings on
which the code stops are reported at once, with the path of the offending
entry, rather than part way through a set-up or a long optimization.

The schemas extend Neko's own case-file schemas: a Neko-TOP case file is first
a Neko case file, with the keys of the optimization drivers added. The
validator therefore needs both sets of schemas, and finds Neko's at run time
(see \ref validating_case_files_neko).

## Running the validator {#validating_case_files_run}

The validator is the Python script `scripts/python/validate_case_schema.py` of
the Neko-TOP source tree (it is also installed as
`share/neko-top/validate_case_schema.py`, next to the schemas in
`share/neko-top/schemas`). It needs Python 3 and three packages:

```bash
pip install jsonschema referencing json5
```

Pass it case files, or directories, which are searched recursively for
`*.case` files:

```bash
python3 scripts/python/validate_case_schema.py examples/passive_scalar/passive_scalar.case
python3 scripts/python/validate_case_schema.py examples/ tests/
```

Each file prints one line, `OK` or `FAIL`, followed for a failing file by the
message and the JSON path it applies to. A file that is valid prints:

```
OK   tests/schema/fixtures/topopt_steady.case
Validated 1 file(s).
```

and a failing one, for example an objective with the key `phi_ref` that nothing
reads (see \ref objectives_and_constraints):

```
FAIL examples/passive_scalar/passive_scalar.case
     {'type': 'scalar_mixing', 'mask_name': 'objective_domain', 'phi_ref': 0.5, 'weight': 1.0} is not valid under any of the given schemas
     at $.optimization.objectives[0]
1 of 1 file(s) failed validation.
```

### Options {#validating_case_files_options}

| Option | Effect |
|---|---|
| `PATH...` | Case files, or directories searched recursively for `*.case`. At least one is required, except with `--print-dirs`. |
| `--all-errors` | List every leaf error instead of only the best match. For a key that can be one of several types, the default reports the closest match only; `--all-errors` shows why each alternative failed. |
| `--strict-syntax` | Also require that the file is accepted by a parser that follows json-fortran. The file is always read as JSON5, which allows more than json-fortran does. A comment started with `!` or `#`, for example, is accepted by json-fortran but is not JSON5 and is reported with a hint to use this option; `--strict-syntax` shows what json-fortran would reject that JSON5 accepts. |
| `--neko-schema-dir DIR` | Neko's schema directory, see below. |
| `--schema-dir DIR` | Neko-TOP's schema directory. By default the schemas next to the script are used (`documentation/schemas` of the source tree, or `schemas` beside the installed script), or `$NEKO_TOP_SCHEMA_DIR` if set. |
| `--root {neko-top,neko}` | The root schema to validate against; `neko-top` (the default) is the collected Neko-TOP schema, `neko` is Neko's alone. |
| `--print-dirs` | Print the two schema directories in use, and where each was found, then exit. |

### Exit codes {#validating_case_files_exit}

| Code | Meaning |
|---|---|
| `0` | Every file is valid (or `--print-dirs` succeeded). |
| `1` | At least one file failed validation, or Neko-TOP's own schemas are broken. |
| `2` | Usage error: no such file or directory, no case files found, or bad arguments. |
| `3` | Neko's schemas are missing, not valid, or too old for Neko-TOP's, see below. |

Real numbers must be written as reals: the validator, like Neko's JSON reader,
distinguishes `1` from `1.0`, and a key that the code reads as a real is
rejected when it is written as an integer.

## Where Neko's schemas are found {#validating_case_files_neko}

The validator looks for a directory that holds Neko's `case-file.schema.json`.
The first of these that does is used:

1. the `--neko-schema-dir` option;
2. the `NEKO_SCHEMA_DIR` environment variable;
3. `$NEKO_DIR/share/neko/schemas`, the install location of a Neko build;
4. `$NEKO_DIR/doc/schemas`, a Neko source tree;
5. `share/neko/schemas` under the prefix reported by `pkg-config` for `neko`.

The first two are exact: if one is given and does not hold Neko's schema, the
validator stops with exit code 3 instead of falling through to another Neko.
`--print-dirs` shows what was found, for example

```
neko-top schemas: <source tree>/documentation/schemas (source tree)
neko schemas:     <neko install>/share/neko/schemas ($NEKO_DIR/share/neko/schemas)
```

In this workspace `NEKO_DIR` is normally set by `prepare.env` (see
\ref installation), so no option is needed.

\attention Neko-TOP's schemas rely on a feature of Neko's: the
registered-type fallback of its schemas, by which a user-registered type (here
the `steady` simulation component of Neko-TOP) is admitted by Neko's union of
simulation components. Neko's schemas contain it from the Neko change that adds
it (the Neko branch `worktree-docs-schema-code-key-audit`, until its pull
request is merged and released). With an older Neko the validator finds the
directory but then detects, by checking that a `steady` component is accepted,
that the schemas are too old; it reports so and exits with code `3`, and the
schema tests of the test suite are skipped (see \ref testing-schema). Build and
install a Neko that contains the change, or point `--neko-schema-dir` at its
`doc/schemas` directory, to validate.

## What the schemas check {#validating_case_files_scope}

The schemas encode **structure and aborts**. For every key they check:

- that the key exists (a key that nothing reads is rejected, so a misspelling
  such as `phi_ref` for `target_concentration` does not pass silently), and
  where it sits: nesting is part of the check, so a `domain` under
  `optimization` instead of under `optimization.design` is reported;
- its JSON type, including real versus integer, and whether a constants name
  may stand in for a literal (see \ref validating_case_files_constants);
- which keys are required, and which are required only together with others;
- allowed values (enumerations) and simple ranges;
- the combinations of settings on which the code stops at set-up or crashes,
  for instance an unsteady case without `state_recovery`, a mapping without its
  required parameter, a steepest-descent optimizer given constraints, or a
  `strict_convergence` PDE filter with a solver that is never reported as
  converged.

Each rule carries a `$comment` in the schema file that cites the source line
that justifies it, so a rule can be traced to the code (the schema files are in
`documentation/schemas`: one per component, `case-file.schema.json` being the
root that collects them).

### Constants names {#validating_case_files_constants}

A numeric key of the case file accepts either a literal or the name of an entry
of `case.constants`, which is looked up when the case is read. The schema
accepts a non-empty string wherever a name is allowed, and keeps the type of
the literal: a key that the code reads as a real needs a real constant and a
real literal (`1.0`, not `1`), a key that it reads as an integer needs an
integer constant or literal. The continuation parameters (`f_max`, `p`, `q`,
`beta`, `r`, `weight` of an objective) accept a real, an array of reals, or the
name of a real or vector constant; their `_iterations` keys and
`continuation_iterations` accept an integer or the name of an integer constant.
`zone_indices` of the adjoint boundary conditions accept an array of integers
or the name of an integer array constant.

### What they deliberately do not check {#validating_case_files_limits}

A schema that accepts a case file is not a guarantee that the run works:

- **Cases that run to completion with a degenerate or wrong result** are not
  rejected. Examples are a SIMP exponent below 1, a RAMP `q` of `-1`, an MMA
  `asyinit` of `0`, a negative MMA `c`, or a negative initial design value. The
  code accepts these, so the schema does too.
- **Mesh-dependent checks** cannot be expressed: that every labelled zone of the
  mesh has a boundary condition, that a named point zone or zone index exists,
  that the mesh is three-dimensional, or that a field named in `extra_fields`
  exists.
- **Runtime checks** cannot be expressed either: a solve that does not converge,
  a file that must exist, or the availability of an optional back end (HDF5,
  ADIOS2, a device).
- **Constants** that do not exist or are of the wrong kind: the schema accepts
  any non-empty string where a constants name is allowed, and cannot see
  `case.constants` (see \ref validating_case_files_constants).
- **Things only a user routine can decide**, which the schema cannot see.

The rules that were considered and left out for that reason are listed with
their code behaviour in the schema tests (`ACCEPTED_AFTER_THE_TRIM` in
`tests/schema/test_tables.py`).

## Case files of the repository that fail today {#validating_case_files_known}

Not every case file shipped in `examples/` and `tests/` passes. Several use a
key that no code reads (for instance `phi_ref` for the scalar-mixing objective,
`optimization.domain` in place of `optimization.design.domain`, or
`state_recovery.enabled`), combine a `steady` component with `"unsteady": true`,
or belong to a driver of its own that has no `optimization.design`. They run
today because the code ignores the surplus keys, and the schema rejects them on
purpose. They are listed, each with the paths at which it fails and the reason,
in `KNOWN_FAILURES` in `tests/schema/test_case_files.py`, and are to be corrected
in the case files themselves. See \ref testing-schema for how that list is
enforced.
