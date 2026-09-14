# Simple setup to compile the current example.
set(DRIVER_TYPE "neko-user")
set(EXTRA_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/user.f90
)

build_example(${DRIVER_TYPE})
