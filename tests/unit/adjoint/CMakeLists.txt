# CMakeLists.txt for the adjoint-operator unit tests.
#
# adv_adjoint_scalar_transpose: verifies that the adjoint scalar advection
# operator is the discrete transpose of the forward scalar advection
# operator, using a boundary-tangential velocity so the surface term in the
# integration-by-parts identity vanishes. Motivated by known-bugs-backlog
# item #6, where a continuous-adjoint / discrete-adjoint mismatch would
# reproduce the observed sensitivity floor.

set(CMAKE_FOLDER "Tests/Unit/Adjoint")

# ============================================================================ #
# Define the tests themselves

add_pfunit_ctest(adv_adjoint_scalar_transpose
    TEST_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/adv_adjoint_scalar_transpose.pf
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    LINK_LIBRARIES Neko-TOP::neko-top
    MAX_PES 1
)
set_property(TEST adv_adjoint_scalar_transpose PROPERTY LABELS unit adjoint)
