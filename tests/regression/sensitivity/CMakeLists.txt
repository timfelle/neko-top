# Define the CTest for sensitivity (regression suite)
set(CMAKE_FOLDER "Tests/Regression/Sensitivity")

# --------------------------------------------------------------------------- #
# Ensure the neko library module dir is found (from the main target)
get_target_property(NEKO_TOP_MOD_DIR neko-top Fortran_MODULE_DIRECTORY)

# --------------------------------------------------------------------------- #
# Preparation target: copies helper scripts into the binary dir
add_custom_target(reg_sensitivity_test_prepare ALL
    COMMENT "Preparing regression sensitivity test files"
)

# --------------------------------------------------------------------------- #
# Use a private .mod folder to avoid clashes with unit targets
set(LOCAL_MOD_DIR ${CMAKE_CURRENT_BINARY_DIR}/modules)
set(CMAKE_Fortran_MODULE_DIRECTORY ${LOCAL_MOD_DIR} CACHE PATH
    "Fortran module directory" FORCE)

# --------------------------------------------------------------------------- #
# Build the single driver executable for regression
add_executable(reg_problem_tester_sensitivity_bin
    ${CMAKE_CURRENT_SOURCE_DIR}/user.f90
    ${CMAKE_CURRENT_SOURCE_DIR}/problem_tester.f90

    # Shared sensitivity module.
    ${SHARED_TEST_SOURCES}/sensitivity.f90
)
target_link_libraries(reg_problem_tester_sensitivity_bin
    PRIVATE Neko-TOP::neko-top
)

# The driver must also see the regression .mod directory
target_include_directories(reg_problem_tester_sensitivity_bin
    PRIVATE ${LOCAL_MOD_DIR})

set_target_properties(reg_problem_tester_sensitivity_bin
    PROPERTIES
        FOLDER "Tests/Regression/Sensitivity"
        RUNTIME_OUTPUT_NAME "sensitivity_regression_driver"
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    )

# Let the umbrella target trigger both build+prepare steps (if present)
add_dependencies(Regression reg_problem_tester_sensitivity_bin)

set(CMAKE_Fortran_MODULE_DIRECTORY ${NEKO_TOP_MOD_DIR} CACHE PATH
    "Fortran module directory" FORCE)

# --------------------------------------------------------------------------- #
# Register the regression sensitivity checks, split into two tiers.
#
# All of these run realistic forward+adjoint solves and compare an analytic
# gradient against a finite-difference sweep (the FD-vs-analytic assertion
# happens inside the driver itself, see run_sensitivity_regression_check.sh).
# The *fast* tier (measured 15-20 s/case) runs unconditionally, every time,
# with no opt-in required. The *slow* tier (~1000-timestep solves, up to
# 3600-10800 s/case) is not part of the default/PR-blocking test budget —
# with all 6 sharing one RESOURCE_LOCK, their TIMEOUTs alone sum to 8 h
# serial worst case, so they only run when
# NEKO_TOP_RUN_SENSITIVITY_REGRESSION is set (see
# run_sensitivity_regression_check.sh, which exits 77 — CTest's "skipped"
# code — otherwise). This mirrors the opt-in pattern already used for
# tests/regression/valgrind (there gated on `valgrind` being installed;
# here gated on an explicit opt-in since the tool is always installed).
#
# Fast and slow tiers share one RESOURCE_LOCK (both write into the same
# WORKING_DIRECTORY and reuse one generated mesh across cases — see
# run_sensitivity_regression_check.sh) so ctest never runs a fast and a slow
# case concurrently against it, regardless of -j.

# Runtime environment for Neko tools (genmeshbox) and libraries.
set(neko_PATH "${neko_PREFIX}/bin:$ENV{PATH}")
string(REPLACE ";" ":" neko_LD_LIBRARY_PATH
    "${neko_LIBRARY_DIRS}:$ENV{LD_LIBRARY_PATH}")

add_test(NAME sensitivity_regression_build
    COMMAND ${CMAKE_COMMAND} --build ${CMAKE_BINARY_DIR}
        --target reg_problem_tester_sensitivity_bin
)
set_tests_properties(sensitivity_regression_build PROPERTIES
    LABELS "regression;sensitivity"
    TIMEOUT 900
)

# Fast tier: cheap enough to always run (measured: unsteady_viscous_dissipation
# 14.5 s, unsteady_brinkman_dissipation 14.4 s). passive_scalar_smallP was
# *proposed* for this tier (estimated ~1 min from a different harness) but
# a direct measurement here (bypassing ctest's TIMEOUT so it could run to
# completion) showed that estimate does not hold at all: it needs ~1399 s
# (~23.3 min) end to end — it runs 6 solves (1 forward + 1 adjoint baseline
# + 4 FD perturbations, see tests/shared/sensitivity.f90's `perturbations`
# array), each taking several minutes on this hardware. It is in the slow
# tier instead. Forced opted-in via the ENVIRONMENT override below,
# regardless of the ambient NEKO_TOP_RUN_SENSITIVITY_REGRESSION setting, so
# these never skip.
set(sensitivity_regression_fast_cases
    "unsteady_viscous_dissipation"
    "unsteady_brinkman_dissipation"
)

# Slow tier: realistic ~1000-timestep forward+adjoint solves per
# perturbation. passive_scalar's case runs 10x longer than the others
# (end_time 10.0 vs 1.0 at the same timestep) — give it a much larger
# TIMEOUT rather than a shared one sized for the cheaper cases.
# passive_scalar_smallP (lower polynomial_order, same end_time as
# passive_scalar) measured ~1399 s end to end (see above) — comfortably
# inside the same 3600 s budget as the other non-passive_scalar slow cases,
# so it does not need passive_scalar's own larger one.
set(sensitivity_regression_slow_cases
    "viscous_dissipation"
    "brinkman_dissipation"
    "dissipation"
    "dissipation_weights"
    "passive_scalar"
    "passive_scalar_smallP"
)

foreach(case_name ${sensitivity_regression_fast_cases})
    add_test(NAME ${case_name}_sensitivity_regression
        COMMAND ${CMAKE_COMMAND} -E env
            PATH=${neko_PATH}
            LD_LIBRARY_PATH=${neko_LD_LIBRARY_PATH}
            NEKO_DIR=${neko_PREFIX}
            NEKO_TOP_RUN_SENSITIVITY_REGRESSION=1
            bash ${CMAKE_CURRENT_SOURCE_DIR}/run_sensitivity_regression_check.sh
            $<TARGET_FILE:reg_problem_tester_sensitivity_bin>
            ${CMAKE_CURRENT_SOURCE_DIR}/cases/${case_name}.case
        WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    )
    set_tests_properties(${case_name}_sensitivity_regression PROPERTIES
        DEPENDS "sensitivity_regression_build"
        LABELS "regression;sensitivity"
        RESOURCE_LOCK "sensitivity_regression_workspace"
        TIMEOUT 600
    )
endforeach()

foreach(case_name ${sensitivity_regression_slow_cases})
    add_test(NAME ${case_name}_sensitivity_regression
        COMMAND ${CMAKE_COMMAND} -E env
            PATH=${neko_PATH}
            LD_LIBRARY_PATH=${neko_LD_LIBRARY_PATH}
            NEKO_DIR=${neko_PREFIX}
            bash ${CMAKE_CURRENT_SOURCE_DIR}/run_sensitivity_regression_check.sh
            $<TARGET_FILE:reg_problem_tester_sensitivity_bin>
            ${CMAKE_CURRENT_SOURCE_DIR}/cases/${case_name}.case
        WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    )
    if(case_name STREQUAL "passive_scalar")
        set(case_timeout 10800)
    else()
        set(case_timeout 3600)
    endif()
    set_tests_properties(${case_name}_sensitivity_regression PROPERTIES
        DEPENDS "sensitivity_regression_build"
        LABELS "regression;sensitivity;sensitivity_slow"
        RESOURCE_LOCK "sensitivity_regression_workspace"
        SKIP_RETURN_CODE 77
        TIMEOUT ${case_timeout}
    )
endforeach()

# --------------------------------------------------------------------------- #
# Make the slow tier's opt-in gate impossible to miss.
#
# ctest's own top-line summary ("X% tests passed, Y tests failed out of Z")
# does not count SKIP_RETURN_CODE tests as failures at all — a run with the
# slow tier gated off reads as unqualified success unless a reader also
# scrolls to the separate "did not run" section. This sentinel test instead
# surfaces the gate state in the primary pass/fail accounting: it PASSES
# when NEKO_TOP_RUN_SENSITIVITY_REGRESSION is set (all 6 slow cases ran) and
# FAILS, under a self-describing name, when it is not (all 6 were skipped).
# That makes "N tests failed out of M" and the final "The following tests
# FAILED:" list themselves show the skip, with no need to read the
# per-case Passed/Skipped lines above to notice it. It carries the
# "sensitivity"/"sensitivity_slow" labels only (deliberately not
# "regression"), so it cannot affect any `ctest -L regression` invocation.
add_test(NAME sensitivity_slow_tier_opted_in__6_cases_else_all_skipped
    COMMAND bash -c "test -n \"$NEKO_TOP_RUN_SENSITIVITY_REGRESSION\""
)
set_tests_properties(sensitivity_slow_tier_opted_in__6_cases_else_all_skipped
    PROPERTIES
        LABELS "sensitivity;sensitivity_slow"
        TIMEOUT 10
)

# --------------------------------------------------------------------------- #
