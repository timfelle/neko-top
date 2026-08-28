# Objective time-window tests

These tests check that an objective's reported value depends only on the time
window it is accumulated over, and not on how long the simulation happens to
run. They replace the former `examples/time_test`, which covered the same
matrix but could only be inspected by hand.

The tests are tagged as `unit`, so they are mandatory for CI to pass. Together
they take about six seconds.

## Common files

- `prepare.sh`: builds the box mesh (`genmeshbox`), a short channel with all
  six boundary faces exposed as separate zones.
- `time_window_tester.f90`: the driver. It runs the case once per entry in
  `optimization.time_window_test.end_times` and compares the objective values
  across those runs and, optionally, against each other within a run.

Only the objectives declared in the case file are checked. `problem_t` appends
an internal augmented-Lagrangian objective of its own, which the driver skips.

The driver calls `problem_t%compute` and never `compute_sensitivity`, so no
adjoint is solved. That is what keeps these cheap enough to be unit tests.

## `time_window_run_length`

The regression guard. Every objective is given the closed window
`[0.02, 0.04]`, which lies inside both runs, so each objective measures the
same interval whether the run stops at `t = 0.05` or continues to `t = 0.1`.
The values must therefore be identical.

This is the property that was broken before: accumulation was normalised by
the *simulation's* window rather than the objective's own, so doubling the run
halved every windowed objective. Against that code all three objectives fail
here with a relative difference of exactly `0.5`.

The tolerance is `1e-9`. Two independent runs of the same case agree to about
`1e-11` — the residual is the iterative solvers, not the windowing — so this
leaves ample headroom while staying far below the factor of two a
normalisation regression would produce.

## `time_window_equivalence`

The semantic check, covering the four ways a window can be written. The
objectives are read as consecutive pairs, each pair selecting the same samples
by different means:

| pair | objective | first form | second form |
|------|-----------|------------|-------------|
| 1 | viscous dissipation | `end_time` only | the same window written out in full |
| 2 | Brinkman dissipation | no window at all | an explicit `start_time` of zero |
| 3 | scalar mixing | `start_time` only | a closed window running past the end of the run |

Pair 3 also exercises a window clipped by the end of the run: its `end_time`
of `0.06` is deliberately beyond the run's own `end_time` of `0.05`.

Note that this test cannot catch a normalisation error on its own — every
objective in a single run shares the same divisor, so a global rescaling
cancels out of a within-run comparison. It passes against the pre-fix code.
`time_window_run_length` is what guards that; this one pins down what each
window form means.

## Choosing window boundaries in new cases

Prefer a closed `end_time` strictly inside the run rather than exactly equal
to the run's own `end_time`. Objectives hand their window to the adjoint
forcing source terms, and `source_term_t`'s gate compares against the
accumulated simulation time with no tolerance, so a boundary landing exactly
on the final step can silently lose that step's forcing.
