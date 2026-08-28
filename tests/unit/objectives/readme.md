# Objective time-window tests

These tests check that an objective's reported value depends only on the time
window it is accumulated over, and not on how long the simulation happens to
run, nor on which of the two code paths — steady or unsteady — evaluated it.
They replace the former `examples/time_test`, which covered the same matrix but
could only be inspected by hand.

The tests are tagged as `unit`, so they are mandatory for CI to pass. Together
they take about nine seconds.

## Common files

- `prepare.sh`: builds the box mesh (`genmeshbox`), a short channel with all
  six boundary faces exposed as separate zones.
- `time_window_tester.f90`: the driver. It runs the case once per entry in
  `optimization.time_window_test.end_times` and compares the objective values
  across those runs and, optionally, against each other within a run.

With `compare_steady` set it also runs the case with `simulation_t%unsteady`
cleared — the flag `problem_t%compute` branches on — and requires that result
to agree with the unsteady ones.

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

## `steady_unsteady_equivalence`

The only test here that runs the steady path at all. It is the same case as
`time_window_run_length` — same mesh, physics, timestep and design — with a
`steady` simulation component added and every objective windowed to the final
timestep alone. It is run twice: once steady, where `problem_t%compute` skips
accumulation entirely and evaluates each objective on the final field, and once
unsteady, where each objective is accumulated over its window. A one-sample
average is that sample, so the two must agree exactly.

Before this test the steady path was reachable from `tests/unit/sensitivity`
but never compared against the unsteady one, so nothing caught the two
diverging in what they evaluate or when.

The steady run goes first, which matters more than it sounds. Both runs write
into the same objectives, so a steady path that quietly stopped evaluating them
would, running second, still be holding the unsteady run's numbers and would
agree with it. Running first it reports the objectives' initial zero instead.
Checked by deleting the `update_objectives` call from `problem_compute`'s
steady branch: the test fails with a relative difference of exactly `1.0`.

### How the single-sample window is made robust

`end_time` is `0.0475` against a `dt` of `0.005`, deliberately off a step
boundary. The time loop stops at the first step reaching `end_time`, so the run
takes ten steps and finishes at `t = 0.05`, and every objective's `start_time`
of `0.0475` admits that step and no other. Both ends of the accepted interval
sit half a timestep from a sample, so no amount of round-off in the accumulated
time can change which steps are counted.

An `end_time` sitting *on* a step boundary is what to avoid, and not for a
subtle reason: with `end_time = 0.05` and `dt = 0.005` the accumulated time
after ten steps lands just below `0.05`, the loop takes an eleventh step, and
the run ends at `t = 0.055`. The window then holds two samples while the steady
path still evaluates one, and the objectives disagree by 0.3%, 10% and 0.2% —
a real failure with a thoroughly misleading cause. It is written up as item 26
of the workspace bug backlog; the underlying overshoot is Neko's, not this
test's.

Measured agreement between the two paths is `4e-13`, `4e-12` and `6e-14`
relative, which is the same floor two identical unsteady runs of this case
reach. The tolerance is `1e-9`, as for the other two tests.

### Why the flow is not run to convergence

Comparing a converged steady solution against an unsteady average over the
converged tail is the more physical statement, but it is not what this test
does, for two measured reasons. The fluid residual on this case is still
`9e-6` at `t = 3.0` against the `1e-6` the `steady` component wants, and one
run to `t = 3.0` costs 39 s — two of them would dominate the whole unit lane.
And the scalar does not converge here at all: its residual is *rising* at
`t = 3.0`, because `steady_simcomp` freezes only the fluid and this case's
scalar has zero-flux conditions on every face, so it is merely stirred around a
conserved total. The tolerance on such a comparison would be a statement about
how converged the run happened to be, not about the objective machinery.

The unconverged run used here is also the stricter comparison of the two. A
frozen field would give the same objective value at every step near the end, so
a path that sampled the wrong step would still pass; a field that is still
moving will not.

## Choosing window boundaries in new cases

Prefer a closed `end_time` strictly inside the run rather than exactly equal
to the run's own `end_time`. Objectives hand their window to the adjoint
forcing source terms, and `source_term_t`'s gate compares against the
accumulated simulation time with no tolerance, so a boundary landing exactly
on the final step can silently lose that step's forcing.

Keep every window boundary away from a step time, by roughly half a timestep.
The accumulation gate has a `1e-6 * dt` tolerance, so a boundary sitting on a
step is decided by round-off in the accumulated time rather than by the case
file. The same applies to the simulation's own `end_time`, which decides how
many steps the run takes — see `steady_unsteady_equivalence` above.

To select the final step alone, set `start_time` to the simulation's
`end_time` and leave the objective's `end_time` unset. The run always overshoots
a non-boundary `end_time` by exactly one step, so that window holds one sample.
