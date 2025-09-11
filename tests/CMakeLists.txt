# CMakeLists.txt for the tests directory.
# This file is used to define the tests for the Neko-TOP library.

add_custom_target(Tests
    COMMENT "Build all tests."
    DEPENDS neko-top
)
set_target_properties(Tests PROPERTIES FOLDER "Tests")

if (BUILD_TESTING)
    set_target_properties(Tests PROPERTIES EXCLUDE_FROM_ALL FALSE)
else()
    set_target_properties(Tests PROPERTIES EXCLUDE_FROM_ALL TRUE)
endif()

# ============================================================================ #
# Define the top target for unit tests.

add_subdirectory(unit)

# ============================================================================ #
# Define the top target for regression tests.

add_custom_target(Regression
    COMMENT "Build all regression tests."
    DEPENDS Tests
)
set_target_properties(Regression PROPERTIES FOLDER "Tests/Regression")

if (BUILD_TESTING)
    set_target_properties(Regression PROPERTIES EXCLUDE_FROM_ALL FALSE)
else()
    set_target_properties(Regression PROPERTIES EXCLUDE_FROM_ALL TRUE)
endif()
