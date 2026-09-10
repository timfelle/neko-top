# Define the CTest for the steady/unsteady objective-convergence regression
# check.
#
# `steady_unsteady_converged` was moved here from tests/unit/objectives/ (see
# that directory's readme.md, "steady_unsteady_converged"): reaching a true
# steady state at representative Pe is dominated by the solid interior, not
# the flow, and that cost is not tunable away, so it no longer gates CI. The
# other three cases in tests/unit/objectives/ stay there.
#
# The driver (time_window_tester.f90) and the shared user module
# (objectives_user.f90) are still needed by those three cases too, so they
# are referenced by path from tests/unit/objectives/ rather than duplicated.
set(CMAKE_FOLDER "Tests/Regression/Objectives")

set(OBJECTIVES_UNIT_DIR ${CMAKE_SOURCE_DIR}/tests/unit/objectives)

# Keep module outputs isolated for this target.
get_target_property(NEKO_TOP_MOD_DIR neko-top Fortran_MODULE_DIRECTORY)
set(LOCAL_MOD_DIR ${CMAKE_CURRENT_BINARY_DIR}/modules)
set(CMAKE_Fortran_MODULE_DIRECTORY ${LOCAL_MOD_DIR} CACHE PATH
    "Fortran module directory" FORCE)

# Runtime environment for Neko tools (genmeshbox) and libraries.
set(neko_PATH "${neko_PREFIX}/bin:$ENV{PATH}")
string(REPLACE ";" ":"
    neko_LD_LIBRARY_PATH "${neko_LIBRARY_DIRS}:$ENV{LD_LIBRARY_PATH}")

# ============================================================================ #
# Build a dedicated executable for this regression test.
add_executable(reg_time_window_tester_bin
    ${OBJECTIVES_UNIT_DIR}/objectives_user.f90
    ${OBJECTIVES_UNIT_DIR}/time_window_tester.f90
)
target_link_libraries(reg_time_window_tester_bin PRIVATE Neko-TOP::neko-top)
target_include_directories(reg_time_window_tester_bin PRIVATE ${LOCAL_MOD_DIR})
set_target_properties(reg_time_window_tester_bin PROPERTIES
    FOLDER "Tests/Regression/Objectives"
    RUNTIME_OUTPUT_NAME "reg_time_window_tester_bin"
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

add_dependencies(Regression reg_time_window_tester_bin)

set(CMAKE_Fortran_MODULE_DIRECTORY ${NEKO_TOP_MOD_DIR} CACHE PATH
    "Fortran module directory" FORCE)

# ============================================================================ #
# Build the executable as its own (labelled, timed) CTest step, matching the
# pattern in tests/regression/valgrind and tests/regression/sensitivity.
add_test(NAME steady_unsteady_converged_build
    COMMAND ${CMAKE_COMMAND} --build ${CMAKE_BINARY_DIR}
        --target reg_time_window_tester_bin
)
set_tests_properties(steady_unsteady_converged_build PROPERTIES
    LABELS "regression;objectives"
    TIMEOUT 900
)

# ============================================================================ #
# Mesh generation: the same box mesh as tests/unit/objectives (N=6, i.e.
# 12x6x6), reusing that directory's prepare.sh rather than duplicating it.
add_custom_target(
    reg_objectives_prepare_script
    COMMENT "Copying and executing the objectives regression prepare script"
    SOURCES ${OBJECTIVES_UNIT_DIR}/prepare.sh
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/prepare.sh
    COMMAND
        ${CMAKE_COMMAND} -E copy_if_different
        ${OBJECTIVES_UNIT_DIR}/prepare.sh
        ${CMAKE_CURRENT_BINARY_DIR}/prepare.sh
    COMMAND ${CMAKE_COMMAND} -E env
        LD_LIBRARY_PATH="${neko_LD_LIBRARY_PATH}" PATH="${neko_PATH}"
        ./prepare.sh -N6 > ${CMAKE_CURRENT_BINARY_DIR}/prepare.log
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

add_custom_target(
    steady_unsteady_converged_case_file
    COMMENT "Copying case file steady_unsteady_converged.case"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/cases/steady_unsteady_converged.case
    BYPRODUCTS
        ${CMAKE_CURRENT_BINARY_DIR}/steady_unsteady_converged.case
    COMMAND
        ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_CURRENT_SOURCE_DIR}/cases/steady_unsteady_converged.case
        ${CMAKE_CURRENT_BINARY_DIR}/steady_unsteady_converged.case
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# ============================================================================ #
# Register the regression test.
add_test(NAME steady_unsteady_converged
    COMMAND $<TARGET_FILE:reg_time_window_tester_bin>
        steady_unsteady_converged.case
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# This case is inherently expensive at representative Pe (see this
# directory's top comment). `end_time` in
# cases/steady_unsteady_converged.case was extended from t = 50.0 to
# t = 100.0 (a neko-build pass, see git history) to settle the objective
# window's steady-vs-unsteady difference comfortably inside tolerance --
# the unmasked "mixing whole" objective's relative steady-vs-unsteady
# difference went from 2.014e-9 (failing against the 1e-9 tolerance) at
# [49,50] to 8.607e-15 at [99,100], the solver round-off floor.
#
# Measured: the full two-pass (steady + unsteady) test took 1382.56 s
# wall-clock on this box under light concurrent load. Extending end_time
# from 49.9975 to 99.9975 -- doubling the simulated duration -- cost only
# ~3% more wall time (1339 s -> 1382 s), because the fluid freezes at
# t ~= 12.69 (steady simcomp's tol = 1e-6 met) and every step after that
# point costs ~0.009 s against ~0.5 s during the transient. This is what
# makes the longer, converged window affordable: do not shorten end_time
# to save wall time without re-deriving the steady-vs-unsteady margin
# above, since that is what reintroduces the failure.
#
# TIMEOUT is set to ~2.6x the measured figure (3600 s) -- enough headroom
# to absorb ordinary machine-load variance without masking a genuine hang,
# while no longer relying on the previous, explicitly unmeasured 14400 s
# placeholder.
set(su_converged_depends
    "steady_unsteady_converged_build"
    "reg_objectives_prepare_script"
    "steady_unsteady_converged_case_file"
)
set_tests_properties(steady_unsteady_converged
    PROPERTIES
        DEPENDS "${su_converged_depends}"
        LABELS "regression;objectives"
        ENVIRONMENT "NEKO_LOG_FILE=steady_unsteady_converged.log"
        TIMEOUT 3600
)
