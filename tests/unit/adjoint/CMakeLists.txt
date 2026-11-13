# CMakeLists.txt for the adjoint unit tests.
#
# adv_adjoint_no_dealias_transpose: the non-dealiased adjoint advection terms
# (adv_lin_no_dealias_t) are verified to be the exact discrete transposes of
# the forward (linearised) advection terms, for the fluid and for a passive
# scalar, via a Euclidean dot-product identity on a two-element hex mesh.
#
# adjoint_source_term_json: the adjoint source terms registered with Neko's
# source-term factory stop with an error when built from a case file.
#
# adjoint_case_init: initialising an adjoint case releases what an earlier
# initialisation left behind.
#
# adjoint_case_output_layout: the adjoint field output takes the data layout
# of the case.

set(CMAKE_FOLDER "Tests/Unit/Adjoint")

# ============================================================================ #
# Neko environment
set(neko_PATH "${neko_PREFIX}/bin:$ENV{PATH}")
string(REPLACE ";" ":"
    neko_LD_LIBRARY_PATH "${neko_LIBRARY_DIRS}:$ENV{LD_LIBRARY_PATH}"
)

# The mesh and the case file the adjoint case tests set up
add_custom_target(
    adjoint_test_prepare
    COMMENT "Preparing the adjoint case test files"
    SOURCES
        ${CMAKE_CURRENT_SOURCE_DIR}/prepare.sh
        ${CMAKE_CURRENT_SOURCE_DIR}/adjoint_case.case
    BYPRODUCTS
        ${CMAKE_CURRENT_BINARY_DIR}/prepare.sh
        ${CMAKE_CURRENT_BINARY_DIR}/adjoint_case.case
    COMMAND
        ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_CURRENT_SOURCE_DIR}/prepare.sh
        ${CMAKE_CURRENT_BINARY_DIR}/prepare.sh
    COMMAND
        ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_CURRENT_SOURCE_DIR}/adjoint_case.case
        ${CMAKE_CURRENT_BINARY_DIR}/adjoint_case.case
    COMMAND ${CMAKE_COMMAND} -E env
        LD_LIBRARY_PATH="${neko_LD_LIBRARY_PATH}" PATH="${neko_PATH}"
        ./prepare.sh > ${CMAKE_CURRENT_BINARY_DIR}/prepare.log
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# ============================================================================ #
# Define the tests themselves

add_pfunit_ctest(adv_adjoint_no_dealias_transpose
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/adv_adjoint_no_dealias_transpose.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)

add_pfunit_ctest(adjoint_source_term_json
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/adjoint_source_term_json.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)

add_pfunit_ctest(adjoint_case_init
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/adjoint_case_init.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)
add_dependencies(adjoint_case_init adjoint_test_prepare)

add_pfunit_ctest(adjoint_case_output_layout
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/adjoint_case_output_layout.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)
add_dependencies(adjoint_case_output_layout adjoint_test_prepare)

add_dependencies(Unit
    adv_adjoint_no_dealias_transpose
    adjoint_source_term_json
    adjoint_case_init
    adjoint_case_output_layout
)

# Set test properties
set_tests_properties(adv_adjoint_no_dealias_transpose PROPERTIES
    LABELS "unit;adjoint"
    ENVIRONMENT "NEKO_LOG_FILE=adv_adjoint_no_dealias_transpose.log"
    TIMEOUT 120
)

set_tests_properties(adjoint_source_term_json PROPERTIES
    LABELS "unit;adjoint"
    ENVIRONMENT "NEKO_LOG_FILE=adjoint_source_term_json.log"
    TIMEOUT 120
)

set_tests_properties(adjoint_case_init PROPERTIES
    LABELS "unit;adjoint"
    ENVIRONMENT "NEKO_LOG_FILE=adjoint_case_init.log"
    TIMEOUT 120
)

set_tests_properties(adjoint_case_output_layout PROPERTIES
    LABELS "unit;adjoint"
    ENVIRONMENT "NEKO_LOG_FILE=adjoint_case_output_layout.log"
    TIMEOUT 120
)

# Disable treating unused-variable as error for pfunit tests
if (CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    target_compile_options(adv_adjoint_no_dealias_transpose PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
    target_compile_options(adjoint_source_term_json PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
    target_compile_options(adjoint_case_init PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
    target_compile_options(adjoint_case_output_layout PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
endif()
