#!/usr/bin/env bash
#
# Build a (Neko, Neko-TOP) commit pair in isolated worktrees, so that the same
# case can be measured against any point in history without disturbing the
# working checkout.
#
# Usage:
#   mem_test/bisect/build_pair.sh <neko-commit> <nekotop-commit> <label>
#
# Example, the known-good anchor:
#   mem_test/bisect/build_pair.sh f1ca7b11d64 99033428 anchor
#
# Produces <workdir>/<label>/nt/examples/mem_test/neko, which
# mem_test/bisect/measure.sh then runs.
#
# Why the two repositories must move together: Neko-TOP periodically realigns
# with Neko API changes ("Align with neko PR #NNNN" commits), so an old Neko
# against current Neko-TOP generally will not compile. Bisect the pair by date.
#
set -u

if [ $# -ne 3 ]; then
    sed -n '3,18p' "$0" >&2
    exit 1
fi

NEKO_COMMIT=$1
NT_COMMIT=$2
LABEL=$3

TOP=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
WORKDIR=${BISECT_WORKDIR:-/tmp/neko-top-bisect}
OUT=$WORKDIR/$LABEL

mkdir -p "$OUT"

# ---------------------------------------------------------------------------- #
# Dependencies
#
# The vendored dependencies are not on the default pkg-config search path; the
# normal build exports these from scripts/dependencies.sh.

export PKG_CONFIG_PATH="$TOP/external/json-fortran/lib/pkgconfig:$TOP/external/hdf5/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export CUDA_DIR=${CUDA_DIR:-/usr/local/cuda}
export HDF5_DIR="$TOP/external/hdf5"

# Match the working build. Double precision matters: Neko-TOP does not compile
# in a single-precision build, and the cluster is double precision anyway.
: "${REAL_PRECISION:=dp}"
: "${CUDA_ARCH_NUM:=75}"

# ---------------------------------------------------------------------------- #
# Neko

echo "=== worktree: neko @ $NEKO_COMMIT ==="
if [ ! -d "$OUT/neko" ]; then
    git -C "$TOP/external/neko" worktree add -f --detach "$OUT/neko" "$NEKO_COMMIT" \
        >"$OUT/neko_worktree.log" 2>&1 || { echo "WORKTREE FAILED"; tail -5 "$OUT/neko_worktree.log"; exit 1; }
fi

cd "$OUT/neko" || exit 1

if [ ! -f configure ]; then
    echo "=== neko: regen ==="
    ./regen.sh >regen.log 2>&1 || { echo "REGEN FAILED"; tail -20 regen.log; exit 1; }
fi

if [ ! -f Makefile ]; then
    echo "=== neko: configure ==="
    ./configure \
        --prefix="$OUT/neko/install" \
        --enable-contrib \
        --with-hdf5="$TOP/external/hdf5" \
        --with-parmetis="$TOP/external/parmetis" \
        --with-cuda="$CUDA_DIR" \
        CUDA_ARCH="-arch=sm_${CUDA_ARCH_NUM}" \
        --enable-real="$REAL_PRECISION" \
        --enable-openmp \
        FC=/usr/bin/mpifort MPIFC=/usr/bin/mpif90 \
        CC=/usr/bin/mpicc MPICC=/usr/bin/mpicc MPICXX=/usr/bin/mpicxx \
        FCFLAGS="-g -w -O2" CFLAGS= \
        HIPCC= HIP_HIPCC_FLAGS= \
        CUDA_CFLAGS="-g -w -O3" \
        >configure.log 2>&1 || { echo "CONFIGURE FAILED"; tail -30 configure.log; exit 1; }
fi

echo "=== neko: make ==="
# LIBS=-lstdc++ : the CUDA objects pull in C++ guard symbols and older
# configurations do not link the C++ runtime themselves.
make LIBS="-lstdc++" -j"$(nproc)" >make.log 2>&1 || {
    echo "MAKE FAILED"
    grep -nE "^Error:|^make.*\*\*\*|Fatal Error|\.f90:[0-9]+:[0-9]+:" make.log | tail -15
    exit 1; }

make install LIBS="-lstdc++" >install.log 2>&1 || { echo "INSTALL FAILED"; tail -20 install.log; exit 1; }

# ---------------------------------------------------------------------------- #
# Neko-TOP

echo "=== worktree: neko-top @ $NT_COMMIT ==="
if [ ! -d "$OUT/nt" ]; then
    git -C "$TOP" worktree add -f --detach "$OUT/nt" "$NT_COMMIT" \
        >"$OUT/nt_worktree.log" 2>&1 || { echo "WORKTREE FAILED"; tail -5 "$OUT/nt_worktree.log"; exit 1; }
fi

# The mem_test example postdates the older commits, so carry it in from the
# working checkout and register it. This keeps the measured case and its user
# code identical across every point in history.
if [ ! -d "$OUT/nt/examples/mem_test" ]; then
    cp -r "$TOP/examples/mem_test" "$OUT/nt/examples/"
    if ! grep -q "EXAMPLES_DIR}/mem_test" "$OUT/nt/examples/CMakeLists.txt"; then
        sed -i '0,/add_subdirectory(${EXAMPLES_DIR}/s//add_subdirectory(${EXAMPLES_DIR}\/mem_test)\nadd_subdirectory(${EXAMPLES_DIR}/' \
            "$OUT/nt/examples/CMakeLists.txt"
    fi
fi

export NEKO_DIR="$OUT/neko/install"
export PKG_CONFIG_PATH="$NEKO_DIR/lib/pkgconfig:$PKG_CONFIG_PATH"
export CUDA_ARCH="$CUDA_ARCH_NUM"

echo "=== neko-top: configure ==="
# CMAKE_Fortran_STANDARD_LIBRARIES rather than CMAKE_EXE_LINKER_FLAGS: the
# former is appended AFTER the objects, which is where -lstdc++ has to sit.
cmake -S "$OUT/nt" -B "$OUT/nt-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_TESTING=OFF \
    -DBUILD_DOCS=OFF \
    -DCMAKE_Fortran_STANDARD_LIBRARIES="-lstdc++" \
    >"$OUT/nt_configure.log" 2>&1 || {
    echo "CONFIGURE FAILED"; tail -30 "$OUT/nt_configure.log"; exit 1; }

echo "=== neko-top: build mem_test ==="
ninja -C "$OUT/nt-build" mem_test >"$OUT/nt_build.log" 2>&1 || {
    echo "BUILD FAILED"
    grep -nE "Error|error:" "$OUT/nt_build.log" | head -25
    exit 1; }

echo "PAIR BUILT: $LABEL (neko $NEKO_COMMIT, neko-top $NT_COMMIT)"
echo "binary: $OUT/nt/examples/mem_test/neko"
