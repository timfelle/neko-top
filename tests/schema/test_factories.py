"""The type names of the schemas equal the case labels of the Fortran factories.

For every family that Neko-TOP builds from a `type` key, the names a schema
accepts are compared with the labels of the `select case` in the factory
subroutine that builds it (multi-label cases such as `case ("a", "b")` count
for both, comments are ignored, and only the named subroutine is read). The
families with a registration instead of a factory compare with the
`register_*` calls.

The Fortran sources are read from `NEKO_TOP_FACTORY_SOURCE_ROOT` when it is
set (a copy of the tree, to show the test going red), otherwise from the
source tree of this checkout.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

import validate_case_schema as vcs
from schema_helpers import TOP_ROOT

SOURCE_ROOT = Path(os.environ.get("NEKO_TOP_FACTORY_SOURCE_ROOT") or TOP_ROOT)

CASE_LABEL = re.compile(r"^\s*case\s*\(([^)]*)\)", re.IGNORECASE)
SUBROUTINE = re.compile(
    r"^\s*(?:(?:module|recursive|pure|elemental)\s+)*subroutine\s+(\w+)",
    re.IGNORECASE)
END_SUBROUTINE = re.compile(r"^\s*end\s+subroutine", re.IGNORECASE)
STRING = re.compile(r"""["']([^"']*)["']""")
REGISTER = re.compile(
    r"^\s*call\s+(register_\w+)\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)


def read_lines(relative: str) -> list[str]:
    """Source lines, with comments and continuation noise removed."""
    text = (SOURCE_ROOT / relative).read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        stripped = line.split("!", 1)[0] if "!" in line else line
        lines.append(stripped)
    return lines


def case_labels(relative: str, subroutine: str) -> set[str]:
    """The labels of every `case (...)` in the subroutine `subroutine`."""
    return labels_in(read_lines(relative), subroutine)


def labels_in(lines: list[str], subroutine: str) -> set[str]:
    labels: set[str] = set()
    inside = False
    found = False
    for line in lines:
        match = SUBROUTINE.match(line)
        if match and match.group(1).lower() == subroutine.lower():
            inside = found = True
            continue
        if inside and END_SUBROUTINE.match(line):
            inside = False
            continue
        if inside:
            case = CASE_LABEL.match(line)
            if case:
                labels.update(STRING.findall(case.group(1)))
    assert found, f"subroutine {subroutine} not found"
    return labels


def registered(relative: str, routine: str) -> set[str]:
    """The names registered by `call <routine>('name', ...)`."""
    names = set()
    for line in read_lines(relative):
        match = REGISTER.match(line)
        if match and match.group(1).lower() == routine:
            names.add(match.group(2))
    return names


def known_list(relative: str, variable: str) -> set[str]:
    """The strings of a `character(...) :: VARIABLE(n) = [...]` array."""
    lines = read_lines(relative)
    out: set[str] = set()
    collecting = False
    for line in lines:
        if variable.lower() in line.lower() and "=" in line:
            collecting = True
        if collecting:
            out.update(STRING.findall(line.split("::", 1)[-1]))
            if "]" in line:
                break
    return out


# ----------------------------------------------------------- schema side --- #
def top_def(schemas, schema: str, name: str):
    return schemas[vcs.TOP_PREFIX + schema.replace("/", ":")]["$defs"][name]


def collect(schemas, schema: str, node) -> set[str]:
    names: set[str] = set()
    if not isinstance(node, dict):
        return names
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        base = schemas[vcs.TOP_PREFIX + schema.replace("/", ":")]
        names |= collect(schemas, schema, base["$defs"][ref.split("/")[-1]])
    prop = node.get("properties", {}).get("type")
    if isinstance(prop, dict):
        if "const" in prop:
            names.add(prop["const"])
        names.update(prop.get("enum", []))
    for key in ("oneOf", "anyOf", "allOf"):
        for member in node.get(key, []):
            names |= collect(schemas, schema, member)
    return names


# --------------------------------------------------------------- families --- #
# (id, schema file, def, factory file, factory subroutine, labels that abort
# in the shipped drivers and so are not accepted)
FACTORY_FAMILIES = [
    ("mapping", "mapping", "mapping",
     "sources/mapping_functions/mapping_fctry.f90", "mapping_factory", set()),
    ("objective", "objectives", "objective",
     "sources/problem/objectives/objective_factory.f90",
     "objective_factory", set()),
    ("constraint", "constraints", "constraint",
     "sources/problem/constraints/constraint_factory.f90",
     "constraint_factory", set()),
    # design.f90:262: simple_design_t lacks init_from_json_sim.
    ("design", "design", "design",
     "sources/design/design_factory.f90", "design_factory", {"simple"}),
    ("optimizer", "optimizer", "solver",
     "sources/optimizer/optimizer_factory.f90", "optimizer_factory", set()),
    ("state_recovery", "state-recovery", "stateRecovery",
     "sources/state_recovery/state_recover_fctry.f90",
     "state_recover_allocator", set()),
]


@pytest.mark.parametrize(
    "family, schema, name, source, routine, aborting", FACTORY_FAMILIES,
    ids=[row[0] for row in FACTORY_FAMILIES])
def test_schema_types_equal_factory_labels(schemas, family, schema, name,
                                           source, routine, aborting):
    labels = case_labels(source, routine)
    assert labels, f"no case labels found in {routine}"
    accepted = collect(schemas, schema, top_def(schemas, schema, name))
    assert aborting <= labels, (
        f"{family}: aborting labels {aborting - labels} are not factory "
        "cases any more")
    assert accepted == labels - aborting, (
        f"{family}: schema {sorted(accepted)} != factory "
        f"{sorted(labels - aborting)}")


def test_state_recovery_type_is_a_property_not_a_oneof(schemas):
    """`state_recovery.type` is an enum inside one closed object, and the
    default factory case is the `checkpoint` label."""
    node = top_def(schemas, "state-recovery", "stateRecovery")
    assert set(node["properties"]["type"]["enum"]) == case_labels(
        "sources/state_recovery/state_recover_fctry.f90",
        "state_recover_allocator")


# adjoint fluid boundary conditions: the velocity and pressure factories each
# have a `select case`; types in the known list without a case in either are
# accepted and do nothing.
ADJOINT_BC_SOURCE = "sources/adjoint/adjoint_fluid_pnpn_bc_fctry.f90"
ADJOINT_BC_ABORTING = {"symmetry", "shear_stress", "wall_model"}
ADJOINT_BC_NO_OP = {"user_velocity_pointwise"}


def test_adjoint_fluid_bc_enum_equals_factory_labels(schemas):
    labels = (case_labels(ADJOINT_BC_SOURCE, "velocity_bc_factory")
              | case_labels(ADJOINT_BC_SOURCE, "pressure_bc_factory"))
    known = known_list(ADJOINT_BC_SOURCE, "ADJOINT_FLUID_PNPN_KNOWN_BCS")
    assert known - labels == ADJOINT_BC_NO_OP, (
        f"known types without a factory case: {sorted(known - labels)}")
    expected = (labels | known) - ADJOINT_BC_ABORTING
    accepted = collect(schemas, "adjoint-fluid",
                       top_def(schemas, "adjoint-fluid", "boundaryCondition"))
    accepted_in_oneof = set()
    for branch in top_def(schemas, "adjoint-fluid",
                          "boundaryCondition")["oneOf"]:
        accepted_in_oneof |= collect(schemas, "adjoint-fluid", branch)
    # The first branch reuses Neko's union and narrows its type: the enum
    # sits in an allOf member.
    assert accepted | accepted_in_oneof == expected, (
        f"schema {sorted(accepted | accepted_in_oneof)} != factories "
        f"{sorted(expected)}")


def test_adjoint_scalar_bc_enum_equals_factory_labels(schemas):
    labels = case_labels("sources/adjoint/adjoint_scalar_pnpn_bc_fctry.f90",
                         "adjoint_bc_factory")
    accepted = set()
    for branch in top_def(schemas, "adjoint-scalar",
                          "boundaryCondition")["oneOf"]:
        accepted |= collect(schemas, "adjoint-scalar", branch)
    assert accepted == labels


# registrations
def test_registered_simcomps_equal_register_calls(schemas):
    calls = registered("sources/simulation_components/neko_top_simcomps.f90",
                       "register_simulation_component")
    assert calls
    overlay = top_def(schemas, "simulation-components",
                      "simulationComponentAdditions")
    assert {overlay["if"]["properties"]["type"]["const"]} == calls
    steady = schemas[vcs.TOP_PREFIX + "simcomps:steady"]["$defs"]["keys"]
    assert {steady["properties"]["type"]["const"]} == calls


def test_registered_source_terms_equal_register_calls(schemas):
    calls = registered("sources/source_terms/neko_top_source_terms.f90",
                       "register_source_term")
    assert len(calls) == 5
    overlay = top_def(schemas, "source-terms", "registeredSourceTerm")
    assert set(overlay["if"]["properties"]["type"]["enum"]) == calls
    assert set(overlay["then"]["properties"]["type"]["enum"]) == calls


# ------------------------------------------------- the check can go red --- #
def test_multi_label_cases_count_for_each_label():
    lines = ["subroutine f()", '  select case (x)', '  case ("a", "b")',
             "  case ('c')", "  case default", "end subroutine f"]
    assert labels_in(lines, "f") == {"a", "b", "c"}


def test_other_subroutines_and_comments_are_ignored():
    lines = ["subroutine g()", '  case ("other")', "end subroutine g",
             "subroutine f()", '  ! case ("commented")',
             '  case ("kept")', "end subroutine f"]
    cleaned = [line.split("!", 1)[0] for line in lines]
    assert labels_in(cleaned, "f") == {"kept"}


def test_a_fake_factory_label_is_reported(schemas):
    """A label that the schema does not know makes the comparison fail."""
    # Always the checkout's own source, whatever SOURCE_ROOT says.
    text = (TOP_ROOT / "sources/mapping_functions/mapping_fctry.f90"
            ).read_text(encoding="utf-8")
    lines = [line.split("!", 1)[0] for line in text.splitlines()]
    fake = [line.replace('case ("linear")',
                         'case ("linear", "fake_mapping")')
            for line in lines]
    assert fake != lines
    labels = labels_in(fake, "mapping_factory")
    accepted = collect(schemas, "mapping", top_def(schemas, "mapping",
                                                   "mapping"))
    assert "fake_mapping" in labels and "fake_mapping" not in accepted
    assert accepted != labels


def test_unknown_subroutine_is_an_error():
    with pytest.raises(AssertionError):
        labels_in(["subroutine f()", "end subroutine f"], "g")
