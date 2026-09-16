#!/usr/bin/env bash
#
# Measure peak host memory of one build on one case.
#
# Usage:
#   mem_test/bisect/measure.sh <path-to-neko-binary> <case-file> [ranks]
#
# Prints one line: peak resident memory in MB, wall time, and the
# Gather-Scatter structural invariants needed to confirm two builds ran the
# same workload. `ranks` defaults to 1, for backward compatibility with
# existing recorded measurements; set it to 2 for the real bisect runs (see
# "Ranks" below).
#
# ---------------------------------------------------------------------------
# Completion marker -- read this before changing it
#
# A run that crashes or half-parses partway through setup still exits, and
# under the old version of this script still printed a peak: a low number
# that reads exactly like "no regression here" and points a bisect at the
# wrong commit. So a peak is only ever printed if the run is proven to have
# completed rather than died early.
#
# Two markers were considered and rejected before landing on the one below.
# Both fail for the same underlying reason: they were only added recently,
# so most of the bisect range (down to the anchor, `f1ca7b11d64` /
# Neko-TOP `99033428`, from 2026-05-26) predates them and would never
# produce them, even on a build that ran to completion. A marker that is
# absent for most of history is not a completion check, it is a permanent
# refusal.
#
#   - `[mem] optimizer_factory` (the last of the `memory_probe.f90` loadup
#     probes): the instrumentation itself postdates the anchor.
#     `git ls-tree -r --name-only 99033428 -- sources/neko_ext/` in Neko-TOP
#     has no `memory_probe.f90`, and `sources/drivers/topopt-user.f90` at
#     that commit has zero references to `memory_probe` or
#     `NEKOTOP_SETUP_ONLY`. `build_pair.sh` only copies `examples/mem_test`
#     forward into old commits (its own comment says so); it does not carry
#     the driver instrumentation, so every historical build emits no `[mem]`
#     lines at all.
#   - The `Coefficients` section banner (`coef_t`, printed twice on a
#     complete adjoint setup): also too new. `call
#     neko_log%section('Coefficients')` exists at the top of the bisect
#     range (`src/sem/coef.f90:316` at Neko `865225094`) but
#     `git show f1ca7b11d64:src/sem/coef.f90 | grep neko_log` is empty --
#     the anchor's coef.f90 does not log at all.
#
# What actually is stable across the whole range is Neko's own end-of-run
# banner: `call neko_log%end_section('Normal end.')` in
# `src/simulation.f90`, at the identical line (116) in both `f1ca7b11d64`
# and `865225094`, i.e. unchanged for the entire span. It is also a
# strictly stronger proof than a setup-phase marker: it only fires after
# `simulation_finalize`, i.e. after the full run (not just setup)
# completed, verified by tracing Neko-TOP's own `simulation_run_forward` in
# `sources/simulation/simulation.f90`, which calls Neko's `simulation_init`
# then `simulation_finalize` around the time loop. This is why the bisect
# case is kept short (`end_time`/`max_iterations` cut down, per
# `mem_test/investigation.md`) rather than relying on a setup-only
# short-circuit: there isn't one that reaches this far back.
#
# The marker is required together with a zero exit status, not instead of
# it: a crash during shutdown after "Normal end." was already printed would
# otherwise still look like success.
#
# The surviving `[mem]` lines (present only in builds built from a
# Neko-TOP commit that already carries `memory_probe.f90`) are still read
# and, if present, the last one reached is printed alongside the peak as a
# bonus diagnostic -- useful for HEAD-of-range component attribution -- but
# their absence never fails the measurement.
#
# ---------------------------------------------------------------------------
# Ranks
#
# At 1 rank there are no halos, so gather-scatter halo buffers and
# distributed-structure growth -- a prime suspect in this investigation --
# are invisible. The local build used to be a device build sharing one GPU,
# where extra ranks meant contention; these are CPU builds, so that reason
# is gone, and 2 ranks is what real measurements should use.
#
# `/usr/bin/time -v` measures the process it launches, so under `mpirun`
# with more than one rank it reports the *launcher's* memory, not any
# rank's. The fix is to wrap each rank individually --
# `mpirun -n N /usr/bin/time -v <binary> <case>` launches N independent
# copies of the wrapped command, one per rank, each producing its own
# report -- with each rank's report captured to its own file (tagged by
# $OMPI_COMM_WORLD_RANK / $PMI_RANK) rather than trusting merged output to
# stay separable; verified empirically in this container with a
# deliberately-imbalanced two-rank test (150 MB / 300 MB allocations came
# back as two distinct, correctly-attributed numbers, not interleaved or
# averaged). The reported peak is the max across ranks; the spread between
# ranks is also printed, since a large imbalance is itself a finding.
#
# `/usr/bin/time` **is not installed in this container** (no
# `/usr/bin/time`, not even via the `time` package, and there is no root to
# install it) -- a portability gap in the original script beyond the ones
# it already knew about, discovered while hardening this one. Where it is
# available this script uses it as originally designed; where it is not,
# it falls back to an equivalent built from Python's `resource` module
# (`getrusage(RUSAGE_CHILDREN).ru_maxrss)`, the same kernel accounting
# `/usr/bin/time -v` itself reads. Verified equivalent here: a direct
# single-process run and an `mpirun -n 2` run of the same 200 MB-touching
# script both reported ~214 MB via this fallback, and the two-rank
# imbalance test above used it too (this container has no `/usr/bin/time`
# to compare against directly).
#
set -u

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
    sed -n '3,13p' "$0" >&2
    exit 1
fi

BIN=$1
CASE=$2
RANKS=${3:-1}

[ -x "$BIN" ] || { echo "not executable: $BIN" >&2; exit 1; }
[ -f "$CASE" ] || { echo "no such case: $CASE" >&2; exit 1; }

case "$RANKS" in
    *[!0-9]*|'')
        echo "ranks must be a positive integer (got '$RANKS')" >&2
        exit 1
        ;;
esac
if [ "$RANKS" -lt 1 ]; then
    echo "ranks must be a positive integer (got '$RANKS')" >&2
    exit 1
fi
if [ "$RANKS" -gt 1 ] && ! command -v mpirun >/dev/null 2>&1; then
    echo "ranks=$RANKS requested but mpirun is not on PATH" >&2
    exit 1
fi

export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}

# Deliberately NOT setting NEKOTOP_SETUP_ONLY: older builds predate it, and a
# comparison across history has to run the same way everywhere. Use a case
# with a short end_time and max_iterations 1 so the run ends quickly.
unset NEKOTOP_SETUP_ONLY

BIN=$(readlink -f "$BIN")
CASE=$(readlink -f "$CASE")
TOP=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)

# This container ships a *system* parallel HDF5 at /usr/local (same SONAME as
# the vendored one build_pair.sh links against, but an incompatible minor
# version), and sets LD_LIBRARY_PATH=/usr/local/lib: globally for every
# process -- which outranks a binary's own DT_RUNPATH in the loader's search
# order. Without overriding it here, $BIN would silently load the wrong HDF5
# at measurement time regardless of which one it was built against, which
# would make "HDF5 resolves identically at every commit" depend on the
# caller's shell state instead of being guaranteed by this script. DEPS_ROOT
# mirrors build_pair.sh's own variable and layout (a directory holding
# external/hdf5); defaults to this script's own repo root, matching
# build_pair.sh's default, but a bisect worktree has no external/ of its own
# so the real bisect invocation must pass DEPS_ROOT explicitly (same as it
# already must for build_pair.sh).
: "${DEPS_ROOT:=$TOP}"
export LD_LIBRARY_PATH="$DEPS_ROOT/external/hdf5/lib:$DEPS_ROOT/external/json-fortran/lib:${LD_LIBRARY_PATH:-}"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Run in a scratch directory so the solver's own output files do not land in
# the repository. The case refers to meshes by repository-relative path, so
# link the data directories in rather than rewriting the case.
for d in data data_local; do
    [ -e "$TOP/$d" ] && ln -s "$TOP/$d" "$tmp/$d"
done

cd "$tmp" || exit 1

# Python fallback for /usr/bin/time -v, used only where the real thing is
# not installed. Reads the same kernel-maintained peak-RSS accounting
# (getrusage) that /usr/bin/time itself uses, so it is not a sampling
# approximation -- see the comment block above for the equivalence check.
cat >"$tmp/rusage_wrap.py" <<'PYEOF'
import subprocess
import resource
import sys

out_path = sys.argv[1]
rc = subprocess.call(sys.argv[2:])
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
with open(out_path, "w") as f:
    f.write("exit=%d maxrss_kb=%d\n" % (rc, ru.ru_maxrss))
sys.exit(rc)
PYEOF

# Per-rank runner: figures out its own rank (OpenMPI sets
# OMPI_COMM_WORLD_RANK; PMI_RANK covers MPICH-family launchers as a
# fallback for a possible future non-OpenMPI machine) and writes a
# normalized one-line report to its own file, using /usr/bin/time -v where
# available and the Python fallback above otherwise. Run directly (no
# mpirun) at ranks=1, so rank defaults to 0.
cat >"$tmp/run_rank.sh" <<'RANKEOF'
#!/usr/bin/env bash
set -u
bin=$1
case_file=$2
tmpdir=$3
rank=${OMPI_COMM_WORLD_RANK:-${PMI_RANK:-0}}
out="$tmpdir/rusage.$rank.txt"

if command -v /usr/bin/time >/dev/null 2>&1; then
    /usr/bin/time -v "$bin" "$case_file" 2>"$tmpdir/time_raw.$rank.txt"
    rc=$?
    kb=$(grep "Maximum resident set size" "$tmpdir/time_raw.$rank.txt" | grep -oE '[0-9]+$')
    printf 'exit=%d maxrss_kb=%s\n' "$rc" "${kb:-0}" >"$out"
else
    python3 "$tmpdir/rusage_wrap.py" "$out" "$bin" "$case_file"
    rc=$?
fi
exit "$rc"
RANKEOF
chmod +x "$tmp/run_rank.sh"

t_start=$(date +%s.%N)
if [ "$RANKS" -eq 1 ]; then
    "$tmp/run_rank.sh" "$BIN" "$CASE" "$tmp" >"$tmp/run.log" 2>"$tmp/stderr.txt"
else
    mpirun -n "$RANKS" "$tmp/run_rank.sh" "$BIN" "$CASE" "$tmp" >"$tmp/run.log" 2>"$tmp/stderr.txt"
fi
status=$?
t_end=$(date +%s.%N)
wall=$(awk -v a="$t_start" -v b="$t_end" 'BEGIN { printf "%.2f", b - a }')

# The one hard gate: the run must both print Neko's own end-of-run banner
# and exit zero. Only rank 0 ever emits this line (Neko's logger silences
# all other ranks), so it is unambiguous regardless of rank count.
marker_seen=false
grep -qF 'Normal end.' "$tmp/run.log" && marker_seen=true

# Last [mem] probe reached, if the binary carries the instrumentation at
# all -- informational only, never gates the result.
last_probe_line=$(awk '$1 == "[mem]"' "$tmp/run.log" | tail -1)
last_probe_label=$(printf '%s\n' "$last_probe_line" | awk '{print $2}')
[ -n "$last_probe_label" ] || last_probe_label="(none -- binary predates memory_probe instrumentation)"

if ! "$marker_seen" || [ "$status" -ne 0 ]; then
    echo "MEASURE FAILED: run did not prove completion (exit $status, 'Normal end.' seen: $marker_seen)"
    echo "  last [mem] probe reached: $last_probe_label"
    echo "  last lines of the run log:"
    tail -5 "$tmp/run.log" | sed 's/^/    /'
    exit 1
fi

# Per-rank peaks: one rusage.<rank>.txt per rank, written by run_rank.sh.
kb_values=()
for f in "$tmp"/rusage.*.txt; do
    [ -e "$f" ] || continue
    kb=$(grep -oE 'maxrss_kb=[0-9]+' "$f" | cut -d= -f2)
    [ -n "$kb" ] && kb_values+=("$kb")
done

if [ "${#kb_values[@]}" -eq 0 ]; then
    echo "MEASURE FAILED: completion marker seen but no per-rank memory reading was captured"
    exit 1
fi

max_kb=$(printf '%s\n' "${kb_values[@]}" | sort -n | tail -1)
min_kb=$(printf '%s\n' "${kb_values[@]}" | sort -n | head -1)
peak_mb=$(awk -v kb="$max_kb" 'BEGIN { printf "%.1f", kb / 1024 }')
spread_mb=$(awk -v mx="$max_kb" -v mn="$min_kb" 'BEGIN { printf "%.1f", (mx - mn) / 1024 }')

# Gather-Scatter structural invariants: 'Avg. internal:'/'Avg. external:'
# are printed once per gs_t built (forward, and each adjoint half), always
# as an internal/external pair in that order, and this text has not
# changed anywhere in the bisect range (no commit between the anchor and
# the top of the range touches it). Two builds measuring the same
# workload must report the identical sequence; if they do not, the peak
# difference reflects a changed workload, not a regression.
gs_pairs=$(awk '
    /Avg\. internal:/ { match($0, /[0-9]+/); internal = substr($0, RSTART, RLENGTH) }
    /Avg\. external:/ { match($0, /[0-9]+/); external = substr($0, RSTART, RLENGTH); printf "%s/%s ", internal, external }
' "$tmp/run.log")
[ -n "$gs_pairs" ] || gs_pairs="(none found)"

printf 'peak %8.1f MB   wall %ss   exit %d   ranks %d   spread %s MB   gs %s  probe %s   %s\n' \
    "$peak_mb" "$wall" "$status" "$RANKS" "$spread_mb" "$gs_pairs" "$last_probe_label" "$(basename "$CASE")"
