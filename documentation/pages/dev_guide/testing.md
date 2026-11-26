# Testing {#testing}

\note This section is under construction.


\warning The use of pFUnit requires an up to date version as there are issues in
the pFUnit CTest macros that are fixed in the latest version. In particular the
fix was included in version 4.7.1 of pFUnit.


## Unit Testing

## Build types {#testing-build-types}

`./setup.sh -t` builds tests and, unless a build type is already chosen
(the `CMAKE_BUILD_TYPE` environment variable), defaults `CMAKE_BUILD_TYPE` to
`Testing`. `Testing` is an optimised configuration (`-g -O2` for GNU, debug
symbols kept) with the same warning set as `Debug`, so the test suite runs at
a realistic speed while still surfacing compiler warnings. See the
[setup script variables](@ref installation-setup) for the other build types
and `CMAKE_BUILD_TYPE`.

## Runtime checks {#testing-runtime-checks}

GNU builds can additionally enable bounds/do/pointer/recursion checking,
floating-point exception traps and poisoned values for uninitialised variables
via `-DNEKO_TOP_RUNTIME_CHECKS=ON` (default `AUTO`). Setting `AUTO` enables
runtime known passing checks for `Debug` builds and disables them otherwise.
Setting `ON` enables all runtime checks regardless of the build type, and
setting `OFF` disables all runtime checks.

### Known failing tests with runtime checks enabled

- Several tests currently fail with it enabled, due to collapsed-index loops in
the sources (for example `x(i,1,1,1)` with `i` running over the whole array,
which `-fcheck=bounds` rejects).

## Regression testing {#testing-regression}

`tests/regression/mma/run.sh` and `tests/regression/sensitivity/run.sh` are
developer scripts that run their regression cases directly against an
already-built `reg_mma_bin` / `sensitivity_regression_driver`, independently
of `ctest`. Both locate the binary in the build tree (its
`RUNTIME_OUTPUT_DIRECTORY`) via `NEKO_TOP_BUILD_DIR`, which defaults to
`<repo root>/build` -- the directory `./setup.sh -t` creates -- and can be
set to a differently-named build directory.

## Validation tests {#testing-validation}

Validation tests reproduce published results and run for hours, so they are
not registered by default. Configure with `-DNEKO_TOP_VALIDATION_TESTS=ON` to
register them, and select them with `ctest -L validation`. They do not carry
the `regression` label, so `ctest -L regression` never runs them.

- `borrvall_rugby_ball_validation_0p8` runs the Borrvall & Petersson (2003)
  rugby ball with a fluid volume fraction of 0.8 (about 80 minutes on eight
  MPI ranks; set `NEKO_TOP_RUGBY_BALL_RANKS` to use another count). It checks
  that the final objective is within 2% of the paper's 31.75, that the final
  design is feasible, and that the paper's stopping rule is met before the
  last iteration.

The fast `borrvall_rugby_ball_regression` test runs the same physics on a
small mesh for a few iterations and compares the whole optimization history
with a stored reference. It is part of the default suite.

## Case-file schema tests {#testing-schema}

The JSON Schemas under `documentation/schemas` and the validator
`scripts/python/validate_case_schema.py` (see \ref validating_case_files) are
tested by pytest tests in `tests/schema`. They need neither pFUnit nor MPI, and
no Neko-TOP build: only Python with the packages in
`tests/schema/requirements.txt` (`jsonschema>=4.18`, `referencing`, `json5` and
`pytest`) and a Neko whose installed schemas Neko-TOP's build on.

```bash
pip install -r tests/schema/requirements.txt
ctest --test-dir build -L schema
```

### How they run under CTest {#testing-schema-ctest}

`tests/schema/CMakeLists.txt` registers every `tests/schema/test_*.py` as one
CTest test named `schema_<module>` (for example `schema_test_tables`), with the
labels `schema` and `unit`. Each is run through `tests/schema/run_schema_tests.py`,
which first checks that the Python packages import and that
`validate_case_schema.load_all()` finds a Neko whose schemas are compatible
(they contain the registered-type fallback, see
\ref validating_case_files_neko), and then calls pytest.

- **Neko's schemas.** CMake looks for Neko's `case-file.schema.json` in
  `${neko_PREFIX}/share/neko/schemas`, `${NEKO_DIR}/share/neko/schemas` and
  `${NEKO_DIR}/doc/schemas`, and stores the directory in the cache variable
  `NEKO_SCHEMA_DIR`. Configure with `-DNEKO_SCHEMA_DIR=<dir>` to override the
  search. The value is passed to the tests as the `NEKO_SCHEMA_DIR` environment
  variable. If CMake finds nothing the tests are still registered, and the
  validator searches again at run time.
- **Skipping.** When a Python package is missing, or the Neko schemas are
  missing or too old, `run_schema_tests.py` exits with `77`, which CTest reports
  as *skipped*. A skip must not read as a pass where the schemas are supposed to
  be checked, so in CI export `NEKO_TOP_REQUIRE_SCHEMA_TESTS=1` in the
  environment of `ctest`: the same condition is then a failure. A mistake in
  Neko-TOP's own schemas is a failure either way.

### What each module tests {#testing-schema-modules}

| Module | Tests |
|---|---|
| `test_files.py` | Every schema is well-formed draft 2020-12, its `$id` matches its path, its references resolve and it uses only keywords that Neko's own checker supports. |
| `test_factories.py` | The type names a schema accepts equal the labels of the `select case` in the Fortran factory that builds that family. |
| `test_tables.py` | Table-driven rows, each a fixture with a few edits: values the code accepts, values on which it aborts, and the other families of rule. |
| `test_case_files.py` | Every `examples/**/*.case` and `tests/**/*.case` of the repository against the schemas. |
| `test_validator_cli.py` | The exit codes and the schema-directory discovery of the validator. |

The fixtures `tests/schema/fixtures/topopt_steady.case`,
`topopt_unsteady.case` and `neko_driver.case` are the valid bases that the table
rows edit.

### Adding or changing a type {#testing-schema-factories}

`test_factories.py` compares the schema with the Fortran. The families are in
`FACTORY_FAMILIES` (mapping, objective, constraint, design, optimizer and state
recovery), each naming the schema file, the definition, the factory source file
and the factory subroutine. The registrations of simulation components and
source terms are compared with the `register_*` calls, and the adjoint boundary
conditions with the factories of `sources/adjoint`.

When a type is added to, or removed from, one of these factories, the test goes
red until the schema agrees: add the type to the schema file (its `type`
enumeration or `oneOf` branch, with its keys), and add the table rows described
below. A label of a factory that aborts in the shipped drivers (the `simple`
design today) is listed in the sixth column of `FACTORY_FAMILIES` and is not
accepted by the schema. To compare against a modified copy of the sources, for
example to show the test going red, set `NEKO_TOP_FACTORY_SOURCE_ROOT` to the
root of that copy.

### Adding a key {#testing-schema-keys}

A new case-file key is added in three places: the code that reads it, the schema
(the key, its type, its default and required-ness, with a `$comment` citing the
source line), and the user documentation of the key (see
\ref configuration and the pages it links). Then extend the tables of
`tests/schema/test_tables.py`; a rule that is removed from a schema turns its
rows red, so the rows are what keeps a rule from silently disappearing:

- `ACCEPTED_BY_THE_CODE`: `(id, base, edits)` rows for valid values, including
  odd ones that the code reads without complaint.
- `REJECTED_AS_THE_CODE_ABORTS`: `(id, base, edits, where)` rows for values on
  which the code aborts, with a comment naming the source line. `where` is a
  fragment of the path at which the error must be reported.
- `LITERAL_ONLY_KEYS` and `LOOKUP_KEYS`: for a key read as a literal real or
  integer only, and for one that goes through Neko's constants lookup.
- `OPTIMIZING_RESTRICTIONS`: for a restriction that applies only with an
  `optimization` object. Each row is checked twice: rejected with
  `optimization`, accepted without it (and accepted by Neko's own root).
- `REGISTERED_BY_NEKO_TOP`: for the types that Neko-TOP registers in Neko's
  unions.

`base` is `steady`, `unsteady` or `neko` and selects one of the three fixtures;
`edits` is a dictionary from a dotted path such as
`optimization.design.mapping[0].f_max` to the new value, with `DEL` deleting the
key. The schemas encode structure and aborts only: a rule for input that the
code accepts and runs to completion does not belong in the schema, and a row
for such an input goes in `ACCEPTED_AFTER_THE_TRIM`, where it must be accepted.

When a new check is added, show it going red once: remove or loosen the rule
and confirm that its rows fail.

### Case files of the repository {#testing-schema-known}

`test_case_files.py` puts every case file in exactly one of three places: it
is valid; it is in `EXPECTED_REJECTED`, a fixture built to make the code abort,
which the schema must reject at the path of that abort; or it is in
`KNOWN_FAILURES`, which names the set of paths at which the schema rejects it and
the reason (the code reads something other than the file says, or the file uses
a key nothing reads). The `KNOWN_FAILURES` entries are *strict* expected
failures: a file that becomes valid, or that fails at other paths, turns its
test red. Fixing such a case file therefore means removing its entry in the
same change, and adding a new case file that does not pass means either fixing
the file or adding a documented entry. The list of the files that fail today is
described, for users, in \ref validating_case_files_known.

## Keeping test executables in sync {#testing-build-fixtures}

CTest only runs tests; it does not build anything. After editing the sources,
build before testing, or `ctest` runs the executables from the previous build:

```bash
cmake --build build
ctest --test-dir build
```

Some regression tests register their build step as a test of its own, so that
running `ctest` alone keeps their executable in sync with the sources. The CI
job for the valgrind regression tests relies on this, as it runs `ctest`
without a separate build step. In `tests/regression/valgrind/CMakeLists.txt`:

- `regression_valgrind_build` runs `cmake --build` for `reg_valgrind_bin` and
  is the setup test (`FIXTURES_SETUP`) of the `regression_valgrind_bin`
  fixture.
- `regression_valgrind_steady_mixer` and `regression_valgrind_unsteady_mixer`
  require that fixture (`FIXTURES_REQUIRED`).

Concurrent `cmake --build` calls on one build tree race on shared outputs, so
every test that builds in the tree should take the `neko_top_build_tree`
resource lock (`RESOURCE_LOCK`). CTest then never runs two of them at once
under `ctest -j`.
