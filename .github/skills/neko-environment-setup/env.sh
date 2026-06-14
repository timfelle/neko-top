#!/bin/bash
# Setup runtime environment for Neko execution (AGENT INTERNAL USE ONLY)
# This script configures LD_LIBRARY_PATH and PATH for testing, running examples, and other operations
# Sources: external/json-fortran/lib, external/hdf5/lib, external/neko/bin

set -e

# Get the project root from the skill directory
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$(dirname "$SKILL_DIR")")")"
EXTERNAL_DIR="$PROJECT_ROOT/external"

# Load prepare.env if it exists (for base environment variables like NEKO_DIR)
if [ -f "$PROJECT_ROOT/prepare.env" ]; then
    source "$PROJECT_ROOT/prepare.env"
fi

# Set default NEKO_DIR if not already set
if [ -z "$NEKO_DIR" ]; then
    NEKO_DIR="$EXTERNAL_DIR/neko"
fi

# Resolve NEKO_DIR to absolute path
if [[ "${NEKO_DIR:0:1}" != "/" ]]; then
    NEKO_DIR="$(cd "$PROJECT_ROOT" && cd "$NEKO_DIR" && pwd)"
else
    NEKO_DIR="$(cd "$NEKO_DIR" && pwd)"
fi
export NEKO_DIR

# Setup JSON-Fortran library path
if [ -d "$EXTERNAL_DIR/json-fortran" ]; then
    JSON_FORTRAN_LIB=$(find "$EXTERNAL_DIR/json-fortran" -type d -name 'lib*' \
        -exec test -f '{}'/libjsonfortran.so \; -print 2>/dev/null | head -1) || true
    if [ -n "$JSON_FORTRAN_LIB" ]; then
        export LD_LIBRARY_PATH="${JSON_FORTRAN_LIB}:${LD_LIBRARY_PATH}"
    fi
fi

# Setup HDF5 library path
if [ -d "$EXTERNAL_DIR/hdf5" ]; then
    HDF5_LIB=$(find "$EXTERNAL_DIR/hdf5" -type d -name 'lib*' \
        -exec test -f '{}'/libhdf5_fortran.so \; -print 2>/dev/null | head -1) || true
    if [ -n "$HDF5_LIB" ]; then
        export LD_LIBRARY_PATH="${HDF5_LIB}:${LD_LIBRARY_PATH}"
    fi
fi

# Setup Neko binary path
if [ -d "$NEKO_DIR/bin" ]; then
    export PATH="${NEKO_DIR}/bin:${PATH}"
fi

# Export the updated paths (already done above, but being explicit)
export LD_LIBRARY_PATH
export PATH
