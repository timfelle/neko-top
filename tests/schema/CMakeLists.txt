# ============================================================================ #
# Neko-TOP case-file schema tests
# ============================================================================ #
# pytest tests of the JSON Schemas under documentation/schemas and of the
# validator in scripts/python/validate_case_schema.py. They need neither
# pFUnit nor MPI, only Python with the packages in requirements.txt and a Neko
# whose installed schemas Neko-TOP's build on (share/neko/schemas).
#
# Each test_*.py is one CTest test, run through run_schema_tests.py, which
# exits 77 (a CTest skip) if a Python package or a compatible Neko schema
# directory is missing. Set NEKO_TOP_REQUIRE_SCHEMA_TESTS=1 in the environment
# of ctest to make that a failure instead.

find_package(Python3 COMPONENTS Interpreter)
if (NOT Python3_Interpreter_FOUND)
    message(STATUS "Python3 not found: the schema tests are not registered.")
    return()
endif()

# Neko's schemas: -DNEKO_SCHEMA_DIR=... overrides the search.
find_path(NEKO_SCHEMA_DIR
    NAMES case-file.schema.json
    PATHS
        ${neko_PREFIX}/share/neko/schemas
        ${NEKO_DIR}/share/neko/schemas
        ${NEKO_DIR}/doc/schemas
    NO_DEFAULT_PATH
    DOC "Directory holding Neko's JSON Schemas"
)
if (NOT NEKO_SCHEMA_DIR)
    message(STATUS "Neko's schemas not found: the schema tests will skip "
        "unless the validator finds them at run time.")
    set(_neko_schema_dir "")
else()
    set(_neko_schema_dir "${NEKO_SCHEMA_DIR}")
endif()

file(GLOB _schema_test_files
    LIST_DIRECTORIES FALSE
    CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/test_*.py
)

foreach (_test_file IN LISTS _schema_test_files)
    get_filename_component(_name ${_test_file} NAME_WE)
    add_test(NAME schema_${_name}
        COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/run_schema_tests.py ${_test_file}
    )
    set_tests_properties(schema_${_name} PROPERTIES
        LABELS "schema;unit"
        TIMEOUT 300
        SKIP_RETURN_CODE 77
        ENVIRONMENT
            "NEKO_SCHEMA_DIR=${_neko_schema_dir};NEKO_TOP_SOURCE_DIR=${CMAKE_SOURCE_DIR}"
    )
endforeach()

unset(_schema_test_files)
