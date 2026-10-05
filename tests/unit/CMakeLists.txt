# ============================================================================ #
# Neko-TOP tests
# ============================================================================ #
# This CMakeLists.txt file is used to define the tests for the Neko-TOP
# library. The tests are defined using the pFUnit testing framework, which
# is a Fortran testing framework that is also used by Neko.
#
# ============================================================================ #
# Setup the Neko-TOP tests
# ============================================================================ #
# The unit tests should be self contained and not depend on any external
# libraries or files outside of the Neko-TOP library. Each test is defined in a
# ".pf" file, which contains the test code and any necessary setup. The tests
# are compiled and linked against the Neko-TOP library and the MPI library.
#
# New tests should be added to the `PFUNIT_TEST_SOURCES` list below. Each
# test is then added to the CMake project using the `add_pfunit_ctest`
# command, which creates a CTest target for the test. The tests are organized
# into a "Tests/Unit" folder in the CMake project for better organization.
#
# In addition to the simple unit tests using PFUnit, this file also includes
# the subdirectory for sensitivity tests and other more complex tests.

# Ensure that the BUILD_TESTING option is enabled.
if (BUILD_TESTING)
    message(STATUS "Building Neko-TOP unit tests.")
else()
    return()
endif()

# Find the pFUnit package. This is required to build the unit tests.
find_package(PFUNIT REQUIRED HINTS ${PFUNIT_DIR})

add_custom_target(Unit COMMENT "Build all unit tests.")
set_target_properties(Unit PROPERTIES
    FOLDER "Tests/Unit"
    EXCLUDE_FROM_ALL $<IF:$<BOOL:BUILD_TESTING>,FALSE,TRUE>
)
add_dependencies(Tests Unit)

# Add the more complex tests that require additional setup or dependencies.
add_subdirectory(sensitivity)
add_subdirectory(objectives)
add_subdirectory(checkpointing)
add_subdirectory(optimizer)
add_subdirectory(mapping)

# ============================================================================ #
# Add the listed tests to the CMake project.

# Create a file list of the pFUnit test sources. These should be relative paths.
set(PFUNIT_TEST_SOURCES "" CACHE INTERNAL "List of pFUnit test source files.")

list(APPEND PFUNIT_TEST_SOURCES problem/time_window.pf)

if (HAVE_HDF5)
    list(APPEND PFUNIT_TEST_SOURCES mma/io_hdf5.pf)
endif()

foreach(pf_file ${PFUNIT_TEST_SOURCES})
    # Ensure the path is relative to the tests/unit directory.
    get_filename_component(pf_file_abs "${pf_file}"
        ABSOLUTE BASE_DIR ${CMAKE_SOURCE_DIR}/tests/unit)

    # Check if the file exists before proceeding.
    if(NOT EXISTS ${pf_file_abs})
        message(FATAL_ERROR "Test file ${pf_file} does not exist.")
    endif()

    # Get the name and relative path of the test file.
    get_filename_component(pf_file_path ${pf_file} DIRECTORY)
    get_filename_component(pf_file_name_we ${pf_file} NAME_WE)

    # Create the test name by combining the path and name. if the path is not empty,
    # it will be included in the test name.
    if (pf_file_path)
        string(REPLACE "/" "-" pf_file_path "${pf_file_path}")
        set(test_name "${pf_file_path}-${pf_file_name_we}")
    else()
        set(test_name "${pf_file_name_we}")
    endif()

    # Add the test to the CMake project.
    add_pfunit_ctest(${test_name}
        TEST_SOURCES ${pf_file}
        LINK_LIBRARIES Neko-TOP::neko-top
        MAX_PES $<IF:$<STREQUAL:${DEVICE_TYPE},CPU>,2,1>
    )

    # Disable treating unused-variable as error for pfunit tests
    if (CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
        target_compile_options(${test_name} PRIVATE
            $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
        )
    endif()

    set_target_properties(${test_name} PROPERTIES
        FOLDER "Tests/Unit"
    )
    set_tests_properties(${test_name} PROPERTIES
        LABELS "unit"
        ENVIRONMENT "NEKO_LOG_FILE=${CMAKE_BINARY_DIR}/tests/unit/${test_name}.log"
        TIMEOUT 120
    )
    add_dependencies(Unit ${test_name})
endforeach()

# ============================================================================ #
# mma-backend_consistency: registered separately from the generic loop above
# because it must NOT use the generic MAX_PES expression
# ($<IF:$<STREQUAL:${DEVICE_TYPE},CPU>,2,1>) -- that expression launches only
# 1 rank on device builds, which fails every npes=2 pFUnit variant in this
# file (known bug #61; 2 ranks may share one GPU, device_init only needs
# device_count() >= 1 per rank). MAX_PES 2 unconditionally, as
# tests/unit/optimizer/ and tests/unit/checkpointing/ already do.

add_pfunit_ctest(mma-backend_consistency
    TEST_SOURCES mma/backend_consistency.pf
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 2
)

set(mma_backend_consistency_log
    "${CMAKE_BINARY_DIR}/tests/unit/mma-backend_consistency.log")

if (CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    target_compile_options(mma-backend_consistency PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
endif()

set_target_properties(mma-backend_consistency PROPERTIES
    FOLDER "Tests/Unit"
)
set_tests_properties(mma-backend_consistency PROPERTIES
    LABELS "unit;mma"
    ENVIRONMENT "NEKO_LOG_FILE=${mma_backend_consistency_log}"
    TIMEOUT 600
)
add_dependencies(Unit mma-backend_consistency)
