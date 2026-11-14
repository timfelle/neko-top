# CMakeLists.txt for the mapping-function unit tests.
#
# mapping_finite_difference: every pointwise mapping (linear, heaviside,
# RAMP, Borrvall & Petersson, SIMP) is verified against a hardcoded,
# independently-derived closed-form derivative -- both via central-difference
# of the forward mapping and directly against the backward (chain-rule)
# mapping.
#
# mapping_pde_filter: the Helmholtz-PDE based filter mapping is verified
# against its own linearity and against the mass-weighted adjoint identity
# the rest of Neko-TOP's sensitivity code relies on.
#
# mapping_pde_filter_convergence: a filter solve that does not converge logs a
# warning, or raises an error with strict convergence.
#
# mapping_pde_filter_lifecycle: a filter re-initialised on other coefficients
# uses them, a preconditioner the filter cannot initialise is rejected, and a
# continuation step after the filter is re-initialised reaches the new filter
# only. Every mapping deregisters its continued parameters when it is freed.

set(CMAKE_FOLDER "Tests/Unit/Mapping")

# ============================================================================ #
# Define the tests themselves

add_pfunit_ctest(mapping_finite_difference
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/mapping_finite_difference.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)

add_pfunit_ctest(mapping_pde_filter
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/mapping_pde_filter.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)

add_pfunit_ctest(mapping_pde_filter_convergence
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/mapping_pde_filter_convergence.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)

add_pfunit_ctest(mapping_pde_filter_lifecycle
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/mapping_pde_filter_lifecycle.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)

add_dependencies(Unit
    mapping_finite_difference
    mapping_pde_filter
    mapping_pde_filter_convergence
    mapping_pde_filter_lifecycle
)

# Set test properties
set_tests_properties(mapping_finite_difference PROPERTIES
    LABELS "unit;mapping"
    ENVIRONMENT "NEKO_LOG_FILE=mapping_finite_difference.log"
    TIMEOUT 120
)

set_tests_properties(mapping_pde_filter PROPERTIES
    LABELS "unit;mapping"
    ENVIRONMENT "NEKO_LOG_FILE=mapping_pde_filter.log"
    TIMEOUT 120
)

# The suite counts the warnings in its log, so it needs NEKO_LOG_FILE.
set_tests_properties(mapping_pde_filter_convergence PROPERTIES
    LABELS "unit;mapping"
    ENVIRONMENT "NEKO_LOG_FILE=mapping_pde_filter_convergence.log"
    TIMEOUT 120
)

set_tests_properties(mapping_pde_filter_lifecycle PROPERTIES
    LABELS "unit;mapping"
    ENVIRONMENT "NEKO_LOG_FILE=mapping_pde_filter_lifecycle.log"
    TIMEOUT 120
)

# Disable treating unused-variable as error for pfunit tests
if (CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    target_compile_options(mapping_finite_difference PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
    target_compile_options(mapping_pde_filter PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
    target_compile_options(mapping_pde_filter_convergence PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
    target_compile_options(mapping_pde_filter_lifecycle PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
endif()
