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
# ---------------------------------------------------------------------------
# Machine layout, parameterized
#
# This script was written on a machine where the Neko-TOP checkout, the
# vendored dependencies, and a nested `external/neko` Neko checkout all lived
# under one root ($TOP, this script's own repo). That is not universal: a
# worktree of Neko-TOP has no `external/` of its own, and Neko may live in a
# completely separate checkout. Three roots, independently overridable, each
# defaulting to the original machine's layout so an unqualified invocation
# there still works unchanged:
#
#   NEKO_SRC   -- repo to cut the Neko worktree from.      Default: $TOP/external/neko
#   DEPS_ROOT  -- root holding external/{json-fortran,hdf5,parmetis}.
#                                                           Default: $TOP
#   NT_SRC     -- repo to cut the Neko-TOP worktree from.   Default: $TOP
#
# NEKO_SRC and NT_SRC only need to be repositories that hold the requested
# commit -- a linked worktree shares its parent's full history, so pointing
# either at a worktree instead of the main checkout works fine.
#
# BISECT_BACKEND selects the device backend for the Neko build: "cuda"
# (default, preserves this script's original behaviour) or "cpu". Neko-TOP
# needs no matching flag: sources/CMakeLists.txt:13 reads DEVICE_TYPE from
# Neko's own installed neko.pc (backend=@NEKO_BCKND@, configure.ac:294-306),
# so a CPU Neko yields a CPU Neko-TOP automatically -- verified by reading
# both files, not assumed.
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

: "${NEKO_SRC:=$TOP/external/neko}"
: "${DEPS_ROOT:=$TOP}"
: "${NT_SRC:=$TOP}"
: "${BISECT_BACKEND:=cuda}"

case "$BISECT_BACKEND" in
    cpu|cuda) ;;
    *)
        echo "BISECT_BACKEND must be 'cpu' or 'cuda' (got '$BISECT_BACKEND')" >&2
        exit 1
        ;;
esac

mkdir -p "$OUT"

# ---------------------------------------------------------------------------- #
# Dependencies
#
# The vendored dependencies are not on the default pkg-config search path; the
# normal build exports these from scripts/dependencies.sh.

export PKG_CONFIG_PATH="$DEPS_ROOT/external/json-fortran/lib/pkgconfig:$DEPS_ROOT/external/hdf5/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export HDF5_DIR="$DEPS_ROOT/external/hdf5"

# Match the working build. Double precision matters: Neko-TOP does not compile
# in a single-precision build, and the cluster is double precision anyway.
: "${REAL_PRECISION:=dp}"

if [ "$BISECT_BACKEND" = cuda ]; then
    export CUDA_DIR=${CUDA_DIR:-/usr/local/cuda}

    # Auto-detect the GPU's compute capability where possible, rather than
    # trusting a hardcoded number: this script has already shipped one stale
    # default (sm_60 originally, then sm_75) that silently mismatched the
    # machine it was run on. Only used if the caller has not set
    # CUDA_ARCH_NUM explicitly.
    if [ -z "${CUDA_ARCH_NUM:-}" ] && command -v nvidia-smi >/dev/null 2>&1; then
        detected_cc=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null \
            | head -n1 | tr -d '. \r')
        if [ -n "$detected_cc" ]; then
            CUDA_ARCH_NUM=$detected_cc
        fi
    fi
    # Historical fallback if nvidia-smi is unavailable or detection failed.
    # On this workspace's machine (RTX A3000 Laptop GPU) the correct value is
    # 86; verify with `nvidia-smi --query-gpu=compute_cap --format=csv,noheader`
    # rather than trusting this default.
    : "${CUDA_ARCH_NUM:=75}"
fi

# ---------------------------------------------------------------------------- #
# Neko

echo "=== worktree: neko @ $NEKO_COMMIT (backend: $BISECT_BACKEND) ==="
if [ ! -d "$OUT/neko" ]; then
    git -C "$NEKO_SRC" worktree add -f --detach "$OUT/neko" "$NEKO_COMMIT" \
        >"$OUT/neko_worktree.log" 2>&1 || { echo "WORKTREE FAILED"; tail -5 "$OUT/neko_worktree.log"; exit 1; }
fi

cd "$OUT/neko" || exit 1

if [ ! -f configure ]; then
    echo "=== neko: regen ==="
    ./regen.sh >regen.log 2>&1 || { echo "REGEN FAILED"; tail -20 regen.log; exit 1; }
fi

if [ ! -f Makefile ]; then
    echo "=== neko: configure ==="
    configure_args=(
        --prefix="$OUT/neko/install"
        --enable-contrib
        --with-hdf5="$DEPS_ROOT/external/hdf5"
        --with-parmetis="$DEPS_ROOT/external/parmetis"
        --enable-real="$REAL_PRECISION"
        --enable-openmp
        FC=/usr/bin/mpifort MPIFC=/usr/bin/mpif90
        CC=/usr/bin/mpicc MPICC=/usr/bin/mpicc MPICXX=/usr/bin/mpicxx
        FCFLAGS="-g -w -O2" CFLAGS=
        HIPCC= HIP_HIPCC_FLAGS=
    )
    if [ "$BISECT_BACKEND" = cuda ]; then
        configure_args+=(
            --with-cuda="$CUDA_DIR"
            CUDA_ARCH="-arch=sm_${CUDA_ARCH_NUM}"
            CUDA_CFLAGS="-g -w -O3"
        )
    fi
    ./configure "${configure_args[@]}" \
        >configure.log 2>&1 || { echo "CONFIGURE FAILED"; tail -30 configure.log; exit 1; }
fi

echo "=== neko: make ==="
# LIBS=-lstdc++ : the CUDA objects pull in C++ guard symbols and older
# configurations do not link the C++ runtime themselves. Kept for the CPU
# backend too: it is a harmless extra link flag there, and this is one build
# recipe for both backends.
make LIBS="-lstdc++" -j"$(nproc)" >make.log 2>&1 || {
    echo "MAKE FAILED"
    grep -nE "^Error:|^make.*\*\*\*|Fatal Error|\.f90:[0-9]+:[0-9]+:" make.log | tail -15
    exit 1; }

make install LIBS="-lstdc++" >install.log 2>&1 || { echo "INSTALL FAILED"; tail -20 install.log; exit 1; }

# ---------------------------------------------------------------------------- #
# Neko-TOP

echo "=== worktree: neko-top @ $NT_COMMIT ==="
if [ ! -d "$OUT/nt" ]; then
    git -C "$NT_SRC" worktree add -f --detach "$OUT/nt" "$NT_COMMIT" \
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
if [ "$BISECT_BACKEND" = cuda ]; then
    export CUDA_ARCH="$CUDA_ARCH_NUM"
fi

echo "=== neko-top: configure ==="
# CMAKE_Fortran_STANDARD_LIBRARIES rather than CMAKE_EXE_LINKER_FLAGS: the
# former is appended AFTER the objects, which is where -lstdc++ has to sit.
# No backend flag needed here: sources/CMakeLists.txt reads DEVICE_TYPE from
# Neko's installed neko.pc, so it follows the Neko build above automatically.
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

echo "PAIR BUILT: $LABEL (neko $NEKO_COMMIT, neko-top $NT_COMMIT, backend $BISECT_BACKEND)"
echo "binary: $OUT/nt/examples/mem_test/neko"
