---
name: neko-style-checks
description: "Run strict Fortran formatting and lint checks for Neko-TOP and external/Neko using repository CI settings. Use when validating code style, preparing PRs, or fixing lint/format failures."
argument-hint: "Target repo: neko-top or external/neko; scope: changed files or full"
user-invocable: true
disable-model-invocation: false
---

# Neko Style Checks

Apply the same formatting and linting conventions used by CI in this workspace.

Scope policy: always run on changed files only.

## When to Use
- Before committing Fortran changes.
- When a PR fails formatting or lint checks.
- When reviewing code style compliance in `neko-top` or `external/neko`.

## Required Environment Setup
1. Always configure Python for the Neko-TOP workspace before any Python or pip step.
2. Use `configure_python_environment` with resource path set to the Neko-TOP workspace.
3. In terminal workflows, always activate the configured environment before running formatter or linter commands:
  `source /home/tife/Projects/neko-top/.venv/bin/activate`
4. If tools are missing, install them in the configured Python environment.

## Tool Packages
Use CI-aligned packages:
- Formatting: `findent>=4.2.6`.
- Linting for `neko-top`: `flinter`, `nobvisual`, `setuptools<82.0.0`.
- Linting for `external/neko`: `flinter` (latest default), `nobvisual`.
- Do not pin `flinter` to `0.4.0` in this skill workflow.

## Repository-Specific Rules
### 1) Neko-TOP
- Formatting workflow reference: `.github/workflows/check_formatting.yml`.
- Lint workflow reference: `.github/workflows/check_linting.yml`.
- Flint config: `flinter_rc.yml`.
- Findent flags:
  `findent -Rr -i2 -d3 -f3 -s3 -c3 -w3 -t3 -j3 -k5 --ws_remred --openmp=0`
- Lint targets:
  - Score branch quality on `sources/ tests/`.
  - Optional develop baseline includes `examples/` as in CI.

### 2) external/Neko
- Formatting workflow reference: `external/neko/.github/workflows/check_format.yml`.
- Lint workflow reference: `external/neko/.github/workflows/check_lint.yml`.
- Flint config: `external/neko/flinter_rc.yml`.
- Findent flags:
  `findent -Rr -i2 -d3 -f3 -s3 -c3 -w3 -t3 -j3 -k- --ws_remred --openmp=0`
- Lint targets:
  - Score branch quality on `src/`.
  - For changed-file lint, skip `src/adt/stack.f90` and `src/adt/htable.f90` to match CI.

## Strict Procedure
1. Identify target repository root (`neko-top` or `external/neko`).
2. Configure Python environment from Neko-TOP workspace.
3. Activate the configured environment in the current shell.
4. Ensure required formatter/linter packages are installed for the target repository.
5. Collect changed files against `origin/develop`.
6. Run formatting on changed `*.f90` and `*.F90` files using repository-specific findent flags.
7. Fail if formatting produced diffs; include exact command to reproduce.
8. Run per-file flint score checks for changed Fortran files and report files with score `< 10`.
9. For failing files, run `flint lint -r <rc-file> <file>`, fallback to `flint stats` if empty.
10. Return a final strict report with:
- Repository and config used.
- Commands executed.
- Changed files detected.
- Files reformatted.
- Lint scores (changed files only).
- Remaining violations and fixes needed.

## Command Templates
Use these templates and adapt paths to the chosen repository root.

```bash
# Activate Neko-TOP Python environment first
source /home/tife/Projects/neko-top/.venv/bin/activate

# Common: fetch develop baseline
git fetch --unshallow origin develop || git fetch origin develop
changes=$(git diff --name-only --diff-filter=d origin/develop)
```

```bash
# Neko-TOP formatting (changed Fortran files)
for file in $changes; do
  [[ ${file: -4} == ".f90" || ${file: -4} == ".F90" ]] || continue
  findent -Rr -i2 -d3 -f3 -s3 -c3 -w3 -t3 -j3 -k5 --ws_remred --openmp=0 < "$file" > "$file.tmp"
  mv -f "$file.tmp" "$file"
done
```

```bash
# external/Neko formatting (changed Fortran files)
for file in $changes; do
  [[ ${file: -4} == ".f90" || ${file: -4} == ".F90" ]] || continue
  findent -Rr -i2 -d3 -f3 -s3 -c3 -w3 -t3 -j3 -k- --ws_remred --openmp=0 < "$file" > "$file.tmp"
  mv -f "$file.tmp" "$file"
done
```

```bash
# Changed-file score (both repos)
for file in $changes; do
  [[ ${file: -4} == ".f90" || ${file: -4} == ".F90" ]] || continue
  # external/Neko CI exclusions:
  [[ "$file" == "src/adt/stack.f90" || "$file" == "src/adt/htable.f90" ]] && continue
  flint score -r flinter_rc.yml "$(realpath "$file")"
done
```

## Enforcement Notes
- This skill is strict-by-default. Do not downgrade checks unless the user explicitly asks.
- Do not defer stricter checks to follow-up; run full strict checks in the same task.
- Always restrict checks to changed Fortran files; do not run full-repository scoring in this skill.
- Keep this skill in the Neko-TOP repository at `.github/skills/neko-style-checks/SKILL.md`.
