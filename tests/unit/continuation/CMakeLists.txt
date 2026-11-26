# CMakeLists.txt for the continuation scheduler unit tests.
#
# continuation_scheduler: a continuation parameter given as the name of a
# constant takes the form of that constant, real or vector, and an integer or
# missing constant raises an error.

set(CMAKE_FOLDER "Tests/Unit/Continuation")

add_pfunit_ctest(continuation_scheduler
    TEST_SOURCES test_continuation_scheduler.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)

add_dependencies(Unit continuation_scheduler)

set_tests_properties(continuation_scheduler PROPERTIES
    LABELS "unit;continuation"
    ENVIRONMENT "NEKO_LOG_FILE=continuation_scheduler.log"
    TIMEOUT 120
)

# Disable treating unused-variable as error for pfunit tests
if (CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    target_compile_options(continuation_scheduler PRIVATE
        $<$<COMPILE_LANGUAGE:Fortran>:-Wno-unused-variable>
    )
endif()
