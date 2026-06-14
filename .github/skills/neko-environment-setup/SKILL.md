---
name: neko-environment-setup
description: "Configure runtime environment for Neko testing, examples, and development. Sets up LD_LIBRARY_PATH and PATH for JSON-Fortran, HDF5, and Neko binaries."
argument-hint: "No arguments needed; automatically detects installed dependencies"
user-invocable: true
disable-model-invocation: false
---

# Neko Environment Setup

Configure the runtime environment to make JSON-Fortran, HDF5, and Neko binaries available for testing, running examples, and development work.

## When to Use

- Before running any tests (unit tests, integration tests, regression tests).
- Before running or setting up Neko simulation examples.
- Before running simulation post-processing or utility commands.
- When `neko` or `makeneko` commands are not found in PATH.
- When library loading errors occur during test/example execution.

## What This Sets Up

The environment script configures:
- **LD_LIBRARY_PATH**: Adds `external/json-fortran/lib` and `external/hdf5/lib`
- **PATH**: Adds `external/neko/bin` for access to `neko`, `makeneko`, and other utilities
- **NEKO_DIR**: Ensures correct Neko installation directory is set

## Usage in Terminal

The environment can be configured using the skill-internal script located at `.github/skills/neko-environment-setup/env.sh`:

### Option 1: Source the environment script (Recommended for interactive work)
```bash
source .github/skills/neko-environment-setup/env.sh
```

This command will:
1. Load base environment from `prepare.env` if it exists
2. Locate JSON-Fortran, HDF5, and Neko installations
3. Configure all necessary environment variables
4. Keep the configuration for all subsequent commands in the terminal session

After sourcing, you can immediately run tests or examples:
```bash
# After sourcing .github/skills/neko-environment-setup/env.sh:
cd tests/unit && make check          # Run unit tests
./run.sh example_name                # Run an example
makeneko my_userfile.f90             # Compile user code
```

### Option 2: Inline sourcing (For single commands)
```bash
source .github/skills/neko-environment-setup/env.sh && your_command_here
```

### Option 3: In a subshell (For isolated commands)
```bash
bash -c "source .github/skills/neko-environment-setup/env.sh && your_command_here"
```

## Verification

After sourcing `.github/skills/neko-environment-setup/env.sh`, verify the environment is correctly set up:

```bash
# Check if neko binary is accessible
which neko

# Check if libraries are in LD_LIBRARY_PATH
echo $LD_LIBRARY_PATH | tr ':' '\n' | grep -E 'json-fortran|hdf5'

# Check NEKO_DIR is set
echo $NEKO_DIR
```

## Troubleshooting

### `neko` command not found
- Verify Neko was successfully built: `ls -la external/neko/bin/`
- Ensure setup.sh was run: `./setup.sh --device CUDA` (or your device type)
- Check that PATH includes neko bin: `echo $PATH | grep neko`

### Library loading errors (e.g., `libhdf5_fortran.so` not found)
- Verify libraries were built: `ls -la external/hdf5/lib/` and `ls -la external/json-fortran/lib/`
- Check LD_LIBRARY_PATH: `echo $LD_LIBRARY_PATH | tr ':' '\n'`
- Try a fresh sourcing of `.github/skills/neko-environment-setup/env.sh`

### Script not found or permission denied
- Ensure the script is executable: `chmod +x .github/skills/neko-environment-setup/env.sh`
- Verify you're running from the workspace root: `pwd` should show neko-top directory

## Implementation Notes

- The script is located in `.github/skills/neko-environment-setup/` as it is internal skill infrastructure, not a user-facing tool
- It is non-destructive: it prepends to existing PATH and LD_LIBRARY_PATH rather than replacing them
- Works with both relative and absolute paths for NEKO_DIR
- Automatically detects installation directories based on standard build layout
- Compatible with multiple shells: bash, zsh, and other POSIX shells
