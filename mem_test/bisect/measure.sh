#!/usr/bin/env bash
#
# Measure peak host memory of one build on one case, single rank.
#
# Usage:
#   mem_test/bisect/measure.sh <path-to-neko-binary> <case-file>
#
# Prints one line: peak resident memory in MB, and wall time.
#
# Single rank on purpose. The local build is a device build with one GPU, so
# several ranks contend for it, and every allocation this investigation cares
# about scales with local element count rather than rank count. Single rank is
# faster, avoids contention entirely, and still shows the step change.
#
# Peak comes from the kernel via /usr/bin/time, not from sampling, so it cannot
# miss a short-lived spike the way interval-based accounting can.
#
set -u

if [ $# -ne 2 ]; then
    sed -n '3,10p' "$0" >&2
    exit 1
fi

BIN=$1
CASE=$2

[ -x "$BIN" ] || { echo "not executable: $BIN" >&2; exit 1; }
[ -f "$CASE" ] || { echo "no such case: $CASE" >&2; exit 1; }

export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}

# Deliberately NOT setting NEKOTOP_SETUP_ONLY: older builds predate it, and a
# comparison across history has to run the same way everywhere. Use a case with
# a short end_time and max_iterations 1 so the run ends quickly; the peak is
# then reached during setup regardless.
unset NEKOTOP_SETUP_ONLY

BIN=$(readlink -f "$BIN")
CASE=$(readlink -f "$CASE")
TOP=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Run in a scratch directory so the solver's own output files do not land in
# the repository. The case refers to meshes by repository-relative path, so
# link the data directories in rather than rewriting the case.
for d in data data_local; do
    [ -e "$TOP/$d" ] && ln -s "$TOP/$d" "$tmp/$d"
done

cd "$tmp" || exit 1
/usr/bin/time -v "$BIN" "$CASE" >"$tmp/run.log" 2>"$tmp/time.txt"
status=$?

peak_kb=$(grep "Maximum resident set size" "$tmp/time.txt" | grep -oE "[0-9]+$")
wall=$(grep "Elapsed (wall clock)" "$tmp/time.txt" | awk '{print $NF}')

if [ -z "${peak_kb:-}" ]; then
    echo "MEASURE FAILED: no peak recorded (exit $status)"
    tail -5 "$tmp/run.log"
    exit 1
fi

printf 'peak %8.1f MB   wall %s   exit %d   %s\n' \
    "$(echo "$peak_kb" | awk '{print $1/1024}')" "$wall" "$status" "$(basename "$CASE")"

if [ $status -ne 0 ]; then
    echo "  NOTE: non-zero exit, peak may not be comparable. Last lines:"
    tail -5 "$tmp/run.log" | sed 's/^/    /'
fi
