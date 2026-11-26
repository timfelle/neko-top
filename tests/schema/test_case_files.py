"""Every case file of the repository against the Neko-TOP schemas.

The files are `examples/**/*.case` and `tests/**/*.case`, which includes the
fixtures of this directory. A file is in exactly one of three places:

* it is valid;
* it is in `EXPECTED_REJECTED`: a fixture built to make the code abort, which
  the schema must reject at the path of that abort;
* it is in `KNOWN_FAILURES`: the code reads something else than the file says
  (or the file uses a key nothing reads), the file is to be fixed in a later
  stage, and the schema must keep rejecting it at exactly these paths. The
  entries are strict expected failures: a file that becomes valid, or fails
  at other paths, turns its test red.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import validate_case_schema as vcs
from schema_helpers import FIXTURES, TOP_ROOT, error_paths

CASE_FILES = sorted(
    p.relative_to(TOP_ROOT).as_posix()
    for top in ("examples", "tests")
    for p in (TOP_ROOT / top).rglob("*.case")
)

# --------------------------------------------------------------------------- #
# Fixtures built to make the code abort: file -> (fragment of the path of the
# error that must be reported, what the code does).
# --------------------------------------------------------------------------- #
EXPECTED_REJECTED = {
    "tests/unit/sensitivity/unsteady_variable_timestep.case": (
        "variable_timestep",
        "an unsteady run with case.time.variable_timestep aborts "
        "(simulation.f90:283); the case also has the other problems of its "
        "group"),
    "tests/unit/sensitivity/unsteady_variable_timestep_without_timestep.case":
    ("variable_timestep",
     "the same abort, without the `timestep` that caps the first step"),
    "tests/unit/sensitivity/unsteady_exact_output_time.case": (
        "exact_output_time",
        "an unsteady run with case.time.exact_output_time aborts "
        "(simulation.f90:289-297) before Neko asks for a variable timestep; "
        "the case also has the other problems of its group"),
    "tests/unit/sensitivity/brinkman_dissipation_dealias_mismatch.case": (
        "dealias_sensitivity",
        "dealias_sensitivity and dealias_forcing differ "
        "(brinkman_dissipation_objective.f90:162); the case also has the "
        "other problems of its group"),
}

# --------------------------------------------------------------------------- #
# Files the schema rejects and that are to be fixed in a later stage.
# file -> (the set of paths of the errors, why).
# --------------------------------------------------------------------------- #
DOMAIN = (
    "`optimization.domain` is read by nothing: the Brinkman design reads "
    "`domain` below `optimization.design` (design_brinkman.f90:274), so the "
    "case optimises the full domain")
PHI_REF = (
    "the scalar_mixing objective carries `phi_ref`, which nothing reads "
    "(the key read is `target_concentration`, "
    "scalar_mixing_objective_function.f90:129)")
ENABLED = (
    "`state_recovery.enabled` is not read (checkpoint.f90:152-157)")
SUBSOLVE = (
    "`optimization.solver.subsolve` is not read (the key read is "
    "`optimization.solver.mma.subsolver`, mma.f90:291)")
STEADY_UNSTEADY = (
    "a `steady` simulation component in an `unsteady: true` case, which the "
    "owner ruled invalid on 2026-11-16 (the rejection is in the code only on "
    "an unmerged branch)")
FREEZE = (
    "`optimization.time_window_test.require_steady_state` is set without "
    "`case.fluid.freeze_flow: true`, so the fluid is never frozen and the "
    "tester aborts after its first run (time_window_tester.f90:199-202)")
PHMG = (
    "the phmg preconditioner has `coarse_grid.solver` and "
    "`pcoarsening_schedule`, which Neko's own schema rejects as well "
    "(neko audit branch: a Neko schema or case file issue)")
OWN_DRIVER = (
    "a case of a driver of its own (examples/mma, examples/1d_beam, "
    "examples/heat_compliance): `optimization` has no `design` "
    "(heat_compliance reads its design keys at the document root) and there "
    "is no `case.adjoint_fluid`")
ZERO = (
    "`optimization.zero` is not read (examples/wiggles/user.f90:58 reads "
    "`zero_fields`), and `state_recovery` is given without `unsteady`, "
    "where nothing reads it (simulation.f90:271-287)")


def known(files, paths, *reasons):
    return {f: (frozenset(paths), "; ".join(reasons)) for f in files}


KNOWN_FAILURES: dict[str, tuple[frozenset, str]] = {}
KNOWN_FAILURES.update(known(
    ["examples/wiggles/uniform_1.case", "examples/wiggles/uniform_1_mask.case"],
    ["$", "$.optimization", "$.optimization.objectives[0]",
     "$.optimization.objectives[0].type", "$.state_recovery"],
    ZERO, PHI_REF, ENABLED))
KNOWN_FAILURES.update(known(
    ["examples/1d_beam/1d_beam.case", "examples/heat_compliance/"
     "heat_compliance.case", "examples/mma/mma.case",
     "tests/regression/mma/cases/1d_beam_dip.case",
     "tests/regression/mma/cases/1d_beam_pdip.case"],
    ["$.case", "$.optimization"], OWN_DRIVER))
KNOWN_FAILURES.update(known(
    ["examples/unsteady_mixer/steady_200.case",
     "examples/unsteady_mixer/steady_200_short.case",
     "examples/unsteady_mixer/steady_200_short_small.case"],
    ["$.case.fluid.pressure_solver.preconditioner",
     "$.case.fluid.pressure_solver.preconditioner.coarse_grid",
     "$.case.fluid.pressure_solver.preconditioner.type",
     "$.optimization.objectives[0]", "$.optimization.objectives[0].type"],
    PHMG, PHI_REF))
KNOWN_FAILURES.update(known(
    ["examples/unsteady_mixer/unsteady_200.case",
     "examples/unsteady_mixer/unsteady_200_short.case",
     "examples/unsteady_mixer/unsteady_200_short_small.case"],
    ["$.case.fluid.pressure_solver.preconditioner",
     "$.case.fluid.pressure_solver.preconditioner.coarse_grid",
     "$.case.fluid.pressure_solver.preconditioner.type",
     "$.optimization.objectives[0]", "$.optimization.objectives[0].type",
     "$.state_recovery"],
    PHMG, PHI_REF, ENABLED))
KNOWN_FAILURES.update(known(
    ["tests/unit/objectives/steady_scalar_unconverged.case",
     "tests/unit/objectives/steady_scalar_unconverged_simtime.case",
     "tests/unit/objectives/steady_unsteady_converged.case",
     "tests/unit/objectives/steady_unsteady_final_step.case"],
    ["$.case.simulation_components[0]", "$.state_recovery"],
    STEADY_UNSTEADY, ENABLED))
for _name in ("steady_scalar_unconverged", "steady_scalar_unconverged_simtime",
              "steady_unsteady_converged"):
    _file = f"tests/unit/objectives/{_name}.case"
    KNOWN_FAILURES[_file] = (KNOWN_FAILURES[_file][0] | {"$.case.fluid"},
                             KNOWN_FAILURES[_file][1] + "; " + FREEZE)
KNOWN_FAILURES.update(known(
    ["tests/regression/sensitivity/cases/passive_scalar.case",
     "tests/regression/sensitivity/cases/passive_scalar_smallP.case",
     "tests/regression/sensitivity/cases/passive_scalar_smallP_dt2.case",
     "tests/regression/sensitivity/cases/passive_scalar_smallP_nodealias.case"],
    ["$.optimization", "$.optimization.objectives[0]",
     "$.optimization.objectives[0].type", "$.optimization.solver",
     "$.optimization.solver.type"],
    DOMAIN, PHI_REF, SUBSOLVE))
KNOWN_FAILURES.update(known(
    ["examples/passive_scalar/passive_scalar.case",
     "tests/regression/valgrind/cases/steady_mixer_valgrind_cpu.case"],
    ["$.optimization.objectives[0]", "$.optimization.objectives[0].type"],
    PHI_REF))
KNOWN_FAILURES.update(known(
    ["tests/regression/valgrind/cases/unsteady_mixer_valgrind_cpu.case"],
    ["$.optimization.objectives[0]", "$.optimization.objectives[0].type",
     "$.state_recovery"],
    PHI_REF, ENABLED))
KNOWN_FAILURES.update(known(
    ["examples/unsteady_rugby_ball/unsteady_rugby_ball.case",
     "tests/regression/sensitivity/cases/unsteady_brinkman_dissipation.case",
     "tests/regression/sensitivity/cases/"
     "unsteady_brinkman_dissipation_nodealias.case",
     "tests/regression/sensitivity/cases/unsteady_viscous_dissipation.case",
     "tests/regression/sensitivity/cases/"
     "unsteady_viscous_dissipation_nodealias.case",
     "tests/unit/objectives/time_window_equivalence.case",
     "tests/unit/objectives/time_window_run_length.case",
     "tests/unit/sensitivity/unsteady_brinkman_dissipation.case",
     "tests/unit/sensitivity/unsteady_brinkman_dissipation_masked.case",
     "tests/unit/sensitivity/unsteady_brinkman_dissipation_window.case",
     "tests/unit/sensitivity/unsteady_brinkman_dissipation_window_end.case",
     "tests/unit/sensitivity/unsteady_viscous_dissipation_masked.case"],
    ["$.state_recovery"], ENABLED))
KNOWN_FAILURES.update(known(
    ["tests/regression/sensitivity/cases/brinkman_dissipation.case",
     "tests/regression/sensitivity/cases/dissipation.case",
     "tests/regression/sensitivity/cases/dissipation_weights.case",
     "tests/regression/sensitivity/cases/viscous_dissipation.case",
     "tests/unit/sensitivity/adjoint_joblimit_variable_dt.case",
     "tests/unit/sensitivity/brinkman_dissipation.case",
     "tests/unit/sensitivity/brinkman_dissipation_continuation.case",
     "tests/unit/sensitivity/brinkman_dissipation_window.case",
     "tests/unit/sensitivity/variable_timestep_without_timestep.case",
     "tests/unit/sensitivity/viscous_dissipation.case",
     "tests/unit/sensitivity/viscous_dissipation_continuation.case",
     "tests/unit/sensitivity/viscous_dissipation_masked.case",
     "tests/unit/sensitivity/viscous_dissipation_variable_dt.case",
     "tests/unit/sensitivity/viscous_dissipation_variable_dt_weighted.case",
     "tests/unit/sensitivity/volume.case",
     "tests/unit/sensitivity/volume_filtered.case"],
    ["$.optimization"], DOMAIN))
KNOWN_FAILURES.update(known(
    ["tests/unit/constraints/volume_constraint_free.case"],
    ["$.optimization"],
    "the constraint unit test builds only the constraint: `optimization` "
    "has no `solver`, which the optimiser factory requires "
    "(optimizer_factory.f90:79)"))


class KnownFailure(Exception):
    """The file is rejected at the paths its KNOWN_FAILURES entry lists."""


def _param(name):
    if name in KNOWN_FAILURES:
        return pytest.param(name, marks=pytest.mark.xfail(
            strict=True, raises=KnownFailure,
            reason=KNOWN_FAILURES[name][1]))
    return name


@pytest.mark.parametrize("name", [_param(n) for n in CASE_FILES],
                         ids=CASE_FILES)
def test_case_file(validator, name):
    instance = vcs.parse_case(TOP_ROOT / name, strict_syntax=False)
    paths = error_paths(validator, instance)
    if name in EXPECTED_REJECTED:
        fragment, _ = EXPECTED_REJECTED[name]
        assert any(fragment in p for p in paths), (
            f"{name} is not rejected at {fragment}: {sorted(paths)}")
        return
    if name in KNOWN_FAILURES:
        if not paths:
            return  # strict xfail: the entry is stale, remove it
        expected = KNOWN_FAILURES[name][0]
        assert paths == expected, (
            f"{name} fails at other paths than its KNOWN_FAILURES entry: "
            f"{sorted(paths ^ expected)}")
        raise KnownFailure(name)
    assert not paths, f"{name}: {sorted(paths)}"


def test_tables_name_existing_files():
    files = set(CASE_FILES)
    for table in (EXPECTED_REJECTED, KNOWN_FAILURES):
        assert set(table) <= files, sorted(set(table) - files)
    assert not set(EXPECTED_REJECTED) & set(KNOWN_FAILURES)


def test_every_known_failure_has_a_reason_and_paths():
    for name, (paths, reason) in KNOWN_FAILURES.items():
        assert paths and len(reason) > 20, name


def test_the_fixtures_are_valid():
    names = {p.relative_to(TOP_ROOT).as_posix()
             for p in FIXTURES.glob("*.case")}
    assert {"tests/schema/fixtures/topopt_steady.case",
            "tests/schema/fixtures/topopt_unsteady.case",
            "tests/schema/fixtures/neko_driver.case"} <= names
    assert not names & (set(KNOWN_FAILURES) | set(EXPECTED_REJECTED))


def test_known_failures_equal_the_sweeps_failing_set(validator):
    """The files that fail, less the expected rejections, are exactly the
    KNOWN_FAILURES keys."""
    failing = set()
    for name in CASE_FILES:
        instance = vcs.parse_case(TOP_ROOT / name)
        if error_paths(validator, instance):
            failing.add(name)
    assert failing - set(EXPECTED_REJECTED) == set(KNOWN_FAILURES)
    assert set(EXPECTED_REJECTED) <= failing


# --------------------------------------------------------------------------- #
# What Neko-TOP's root accepts, Neko's accepts too; Neko's own examples pass.
# --------------------------------------------------------------------------- #
def test_whatever_neko_top_accepts_neko_accepts(validator, neko_validator):
    for name in CASE_FILES:
        instance = vcs.parse_case(TOP_ROOT / name)
        if not error_paths(validator, instance):
            assert not error_paths(neko_validator, instance), (
                f"{name}: accepted by Neko-TOP's root, rejected by Neko's")


def neko_examples(neko_dir: Path) -> list[Path]:
    """Case files of the Neko tree the schemas come from, if there is one."""
    env = os.environ.get("NEKO_SOURCE_DIR")
    candidates = [Path(env)] if env else []
    candidates += [neko_dir.parents[i] for i in (1, 2, 3) if
                   len(neko_dir.parents) > i]
    for root in candidates:
        found = sorted((root / "examples").rglob("*.case"))
        if found:
            return found
    return []


def test_nekos_own_examples_still_pass(validator, neko_validator, loaded):
    """A case that Neko's root accepts and that has no Neko-TOP key is
    accepted by the Neko-TOP root."""
    files = neko_examples(Path(loaded.neko_dir))
    if not files:
        pytest.skip("no Neko examples next to the Neko schemas "
                    "(set NEKO_SOURCE_DIR)")
    checked = 0
    for path in files:
        try:
            instance = vcs.parse_case(path)
        except ValueError:
            continue
        if error_paths(neko_validator, instance):
            continue
        checked += 1
        assert not error_paths(validator, instance), str(path)
    assert checked > 10


def test_neko_only_cases_of_this_repository_pass(validator):
    """Cases that Neko-TOP ships without an `optimization` object."""
    for name in ("examples/easy-E/easy-E_1.case",
                 "examples/thermal_mix_channel/laminar.case",
                 "examples/thermal_mix_channel/turbulent.case",
                 "tests/schema/fixtures/neko_driver.case"):
        instance = vcs.parse_case(TOP_ROOT / name)
        assert not error_paths(validator, instance), name
