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
# CMakeLists.txt's own `find_package(HDF5 COMPONENTS Fortran)` (independent of
# Neko's pkg-config-based resolution above) keys off HDF5_ROOT, not HDF5_DIR --
# scripts/dependencies.sh:252-259 documents HDF5_DIR as only "a legacy
# spelling" it translates from, for exactly this reason. This script bypasses
# dependencies.sh entirely, so without also setting HDF5_ROOT here, Neko-TOP's
# CMake HDF5 discovery gets no root hint and falls through to system default
# paths -- landing on /usr/local's HDF5 even when the Neko side above
# correctly resolved the vendored one via PKG_CONFIG_PATH.
export HDF5_ROOT="$DEPS_ROOT/external/hdf5"

# This container now also ships a *system* parallel HDF5 at /usr/local
# (same SONAME, libhdf5.so.320, but a different, incompatible minor version --
# it defines three extra low-precision float types the vendored 2.0.0 does
# not have), and the image sets LD_LIBRARY_PATH=/usr/local/lib: globally for
# every process, which outranks an ELF's own DT_RUNPATH in the loader's
# search order. That breaks HDF5 resolution two ways that both have to be
# fixed the same way, by putting the vendored dir first in LD_LIBRARY_PATH:
#   - build time: linking the final `neko` executable resolves -lhdf5_fortran
#     to the vendored .so via -L (correct), but libhdf5_fortran.so's own
#     indirect NEEDED entries (libhdf5_f90cstub.so.320, libhdf5.so.320) are
#     resolved via ld's LD_LIBRARY_PATH/default-path fallback, not -L -- with
#     no LD_LIBRARY_PATH override, that fallback hits /usr/local's 2.2.0
#     f90cstub, which references symbols the vendored 2.0.0 core libhdf5.so
#     it gets paired with does not export, and the link fails.
#   - run time: even an already-linked binary carries the correct RUNPATH,
#     but the image's global LD_LIBRARY_PATH=/usr/local/lib: silently
#     overrides it, so every run (not just this build) silently loads the
#     wrong HDF5 unless this is set.
# Vendored is deliberately the one made to win here, not system: it is a
# fixed, version-pinned artifact this bisect already targets via
# --with-hdf5 below, the shared Neko install and the private Neko this
# session already built are both linked against it, and it will not move
# under the bisect if the image gets updated again mid-run -- unlike
# /usr/local, which is coming from outside the bisect's control.
export LD_LIBRARY_PATH="$DEPS_ROOT/external/hdf5/lib:$DEPS_ROOT/external/json-fortran/lib:${LD_LIBRARY_PATH:-}"

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
        LIBS=-lstdc++
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
# LIBS=-lstdc++ is set as a *configure* argument above, not a make-command-line
# override: autoconf's AC_CHECK_LIB/pkg-config detection (json-fortran, hdf5,
# parmetis, lapack/blas) all do `LIBS="$NEWLIB $LIBS"`, i.e. prepend onto
# whatever LIBS already held, so seeding it before configure runs places
# -lstdc++ at the end of the final link line -- the same position Neko's own
# CUDA>=13 check puts it at (configure.ac ~line 285) -- without disturbing
# anything else. `make LIBS=...` on the command line does the opposite: make
# variable assignments from the command line always win over a Makefile's own
# `LIBS = ...` line, so it was silently discarding every configure-detected
# library (json-fortran, hdf5, parmetis, lapack/blas) and leaving only
# -lstdc++, which fails to link with "undefined reference to
# __json_file_module_MOD_..." etc. -- caught by actually running this script,
# not by the dry-runs it shipped with.
make -j"$(nproc)" >make.log 2>&1 || {
    echo "MAKE FAILED"
    grep -nE "^Error:|^make.*\*\*\*|Fatal Error|\.f90:[0-9]+:[0-9]+:" make.log | tail -15
    exit 1; }

make install >install.log 2>&1 || { echo "INSTALL FAILED"; tail -20 install.log; exit 1; }

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
#
# -lgomp is appended here for the same reason as -lstdc++: Neko is configured
# --enable-openmp above, so libneko.a's objects (comm.F90, dofmap.f90,
# coef.f90, schwarz.f90, cpu_opgrad.f90, fdm_cpu.f90, device_mpi.c, ...)
# reference omp_get_thread_num/omp_get_num_threads/GOMP_parallel/GOMP_barrier,
# and something has to put libgomp on the final link line. Neko's own
# neko.pc carries `-fopenmp` in Cflags (verified identical across the April,
# May and September pairs -- this is not a neko.pc regression), but pkg-config
# Cflags never reach CMake's *link* step, only compilation of Neko-TOP's own
# sources, and neko.pc's Libs: line has never carried -lgomp/-fopenmp at any
# of those commits either. Neko-TOP's own sources/CMakeLists.txt separately
# gained `find_package(OpenMP REQUIRED COMPONENTS Fortran)` +
# `target_link_libraries(... OpenMP::OpenMP_Fortran)` sometime between the
# April ALE-adjacent commits (6b20dfb, b334750 -- neither has it) and the May
# anchor (99033428, which does) -- confirmed by grepping CMakeLists.txt at
# each worktree. Pairs built before that CMake change have no other path to
# libgomp, hence the link failure; pairs built after it already get libgomp
# via OpenMP::OpenMP_Fortran, so this flag is redundant-but-harmless there
# (same libgomp.so, just named twice on the link line; the dynamic linker
# de-dupes the DT_NEEDED entry).

# -DCMAKE_CUDA_ARCHITECTURES on the command line (cuda only): same class of
# problem as the -lstdc++/-lgomp flags above -- an old Neko-TOP commit
# lacking CMake plumbing that a later commit added. sources/CMakeLists.txt
# only sets CMAKE_CUDA_ARCHITECTURES from $CUDA_ARCH itself `if(DEFINED
# ENV{CUDA_ARCH})`; that `if` was added after the anchor commit (99033428,
# 2026-05-20) -- confirmed absent via `git show 99033428:sources/CMakeLists.txt`
# -- so at the anchor CMake falls back to CMake/CUDA-13's own default
# architecture (sm_75) for Neko-TOP's own five .cu translation units
# (RAMP_mapping.cu, SIMP_mapping.cu, heaviside_mapping.cu, mma.cu,
# math_ext.cu), while Neko's own device code (57 cubins) still gets sm_86
# from Neko's own `configure`'s CUDA_ARCH, which predates this plumbing
# entirely. The two halves of one binary then embed two different
# architectures for the same GPU. At runtime the driver has no native SASS
# for the five sm_75 kernels and JITs the embedded compute_75 PTX instead,
# which fails on this driver (max CUDA 13.2) against nvcc 13.3's PTX ISA:
# "the provided PTX was compiled with an unsupported toolchain" in
# math_ext.cu:66 -- confirmed by `cuobjdump --list-elf` on the anchor-cuda
# binary showing exactly 57 sm_86 + 5 sm_75 cubins, matching the 5 .cu
# files above, versus 69/69 sm_86 in the top-cuda binary (which already
# gets CMAKE_CUDA_ARCHITECTURES from its CMakeLists.txt's env-var read).
# Passing it as a command-line -D instead takes precedence over whatever
# (if anything) the target commit's own CMakeLists.txt does with it, so it
# works uniformly at every commit in the bisect range, not just the ones
# that added the env-var plumbing. Derived from the same auto-detected
# CUDA_ARCH_NUM used for Neko's own CUDA_ARCH above, so it tracks whatever
# GPU this script is actually run on rather than hardcoding this machine's
# 86.
cmake_extra_args=()
if [ "$BISECT_BACKEND" = cuda ]; then
    cmake_extra_args+=(-DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH_NUM")
fi

cmake -S "$OUT/nt" -B "$OUT/nt-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_TESTING=OFF \
    -DBUILD_DOCS=OFF \
    -DCMAKE_Fortran_STANDARD_LIBRARIES="-lstdc++ -lgomp" \
    "${cmake_extra_args[@]}" \
    >"$OUT/nt_configure.log" 2>&1 || {
    echo "CONFIGURE FAILED"; tail -30 "$OUT/nt_configure.log"; exit 1; }

echo "=== neko-top: build mem_test ==="
ninja -C "$OUT/nt-build" mem_test >"$OUT/nt_build.log" 2>&1 || {
    echo "BUILD FAILED"
    grep -nE "Error|error:" "$OUT/nt_build.log" | head -25
    exit 1; }

echo "PAIR BUILT: $LABEL (neko $NEKO_COMMIT, neko-top $NT_COMMIT, backend $BISECT_BACKEND)"
echo "binary: $OUT/nt/examples/mem_test/neko"
