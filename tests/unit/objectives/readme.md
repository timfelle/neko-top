# Objective time-window tests

These tests check that an objective's reported value depends only on the time
window it is accumulated over, and not on how long the simulation happens to
run, nor on which of the two code paths — steady or unsteady — evaluated it.
They replace the former `examples/time_test`, which covered the same matrix but
could only be inspected by hand.

The tests are tagged as `unit`, so they are mandatory for CI to pass. Together
they take about 35 s, almost all of it in `steady_unsteady_converged`, which
has to run a flow to a genuine steady state.

## Common files

- `prepare.sh`: builds the box mesh (`genmeshbox`), a short channel with all
  six boundary faces exposed as separate zones.
- `time_window_tester.f90`: the driver. It runs the case once per entry in
  `optimization.time_window_test.end_times` and compares the objective values
  across those runs and, optionally, against each other within a run.

With `compare_steady` set it also runs the case with `simulation_t%unsteady`
cleared — the flag `problem_t%compute` branches on — and requires that result
to agree with the unsteady ones. `require_steady_state` additionally asserts
that every run reached a steady state, which is what makes a window average
comparable to a single converged field at all.

Only the objectives declared in the case file are checked. `problem_t` appends
an internal augmented-Lagrangian objective of its own, which the driver skips.

The driver calls `problem_t%compute` and never `compute_sensitivity`, so no
adjoint is solved. That is what keeps these affordable as unit tests.

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

## `steady_unsteady_converged`

The steady and the unsteady approach are two ways of putting a number on the
same problem, and once that problem has reached a steady state they must give
the same number. This test is that statement: the flow is run to convergence,
the steady path evaluates each objective on the converged field, the unsteady
path averages the same objective over a window lying inside the converged
tail, and the two are required to agree.

Nothing checked this before. The steady path was reachable from
`tests/unit/sensitivity` but never compared against the unsteady one, so the
two were free to disagree about which field they evaluate, or when.

### Why the case looks the way it does

Every parameter that differs from `time_window_run_length` is there to get a
genuine steady state inside a unit test's budget.

| setting | value | why |
|---------|-------|-----|
| `Re` | `5.0` | At the sibling cases' `Re = 50` the fluid residual is still `9e-6` at `t = 3.0`, 39 s of run time short of the `1e-6` it needs. At `Re = 5` it converges at `t ≈ 1.27`. |
| `Pe` | `0.25` | The scalar is the slower of the two by a long way. Measured on this case: at the sibling cases' `Pe = 100` its residual is still `2.5e-2` at the end of the run and falling by only a few percent per `0.25` of time; `Pe = 5` and `Pe = 1` also fail to converge inside the budget. At `Pe = 0.25` it reaches `1.1e-8`. |
| `timestep` | `0.01` | Twice the sibling cases', halving the step count. |
| `f_max` | `50.0` | Halved alongside the timestep, so the Brinkman penalty keeps the `chi * dt` of `0.5` the other cases run at. Raising `dt` without this is what blows a Brinkman case up. |
| `end_time` | `1.995` | Half a step off a boundary, so the run is a deterministic 200 steps ending at `t = 2.0`. See the note on step boundaries below. |
| `scalar_coupled` | `true` | Without it `steady_simcomp` declares convergence on the velocity and pressure residuals alone and freezes the fluid while the scalar is still moving. At `Pe = 0.25` the fluid is in fact the binding criterion, so this changes nothing here — it is a guard against a future retune quietly reintroducing the trap, not load-bearing today. |
| `target_concentration` | `0.2` | The converged scalar sits very close to `0.5`, which is the default target, so on the default the objective collapses to `2.2e-4`. The scalar's absolute drift across the window is ~`2e-12` either way, so that collapse turns a `6e-11` relative difference into `9e-9` — past the tolerance. Measured, not reasoned: the run with the default target fails. |

`require_steady_state` makes the driver assert that each run really did
converge, by checking that `steady_simcomp` froze the fluid. A run that
quietly fell short would otherwise show up as an unexplained value mismatch
rather than as what it is.

### What it measures

Convergence at `t ≈ 1.27`; the window is `[1.5, 2.0]`, 51 samples, so it
sits about 23 steps clear of the freeze. At the last logged step before the
freeze, `t = 1.25`, the residuals are `1.1e-6` on the velocity (the binding
one, against a `1e-6` tolerance) and `1.1e-8` on the scalar — the scalar is
some ninety times better converged than it needs to be, so the choice of `Pe`
is not sitting on a cliff edge.

The scalar boundary conditions are the sibling cases' unchanged: zero-flux
Neumann on all six zones, with the same `point_zone` initial condition. Only
`Pe` and the objective's target differ.

| objective | steady | unsteady average | relative difference |
|-----------|--------|------------------|---------------------|
| viscous dissipation | `3.08157224397083` | `3.08157224397083` | `0` |
| Brinkman dissipation | `0.390671241523987` | `0.390671241523987` | `0` |
| scalar mixing | `0.0514533959878988` | `0.0514533959908935` | `5.8e-11` |

The two velocity-based objectives are bit-identical, and that is not luck:
`steady_simcomp` freezes the fluid on convergence, so the velocity field is
literally constant across the window and the average of a constant is that
constant. It also means the test checks its own margin — had the freeze landed
inside the window, these two would stop agreeing exactly.

The scalar is converged but not frozen (freezing it is an open `@todo` in
`steady_simcomp`), so it keeps relaxing through the window and its average
lags the endpoint slightly. `5.8e-11` is that drift. The tolerance is `1e-9`,
as for the other tests here, which leaves the scalar an order of magnitude of
headroom and the other two objectives all of it.

The test costs 26 s, the most expensive in this directory by a wide margin,
which is the price of a real steady state.

## `steady_unsteady_final_step`

The same steady-versus-unsteady comparison with convergence taken out of it.
The case is `time_window_run_length` unchanged apart from a `steady`
simulation component and a window holding the final timestep alone; a
one-sample average is that sample, so the two paths must agree exactly
whatever the flow is doing. It costs 3 s.

This exists to localise a failure of `steady_unsteady_converged`. If both
fail, the two paths disagree about which field they evaluate. If only the
converged one fails, the paths are fine and the run is not reaching a steady
state. An unconverged run is also the stricter comparison of the two: a frozen
field gives the same objective at every step near the end, so a path sampling
the wrong step would slip through, whereas a field still in motion catches it.

### Ordering, and why it matters

Both tests run the steady path first. Every run leaves its values in the same
objectives, so a steady path that quietly stopped evaluating them would,
running second, still be holding the unsteady run's numbers and would agree
with it. Running first it reports the objectives' initial zero instead.
Checked by deleting the `update_objectives` call from `problem_compute`'s
steady branch: the test fails with a relative difference of exactly `1.0`.
With the other order it passed.

### Step boundaries

`steady_unsteady_final_step` runs to `end_time = 0.0475` against a `dt` of
`0.005`, deliberately off a step boundary. The time loop stops at the first
step reaching `end_time`, so the run takes ten steps and finishes at
`t = 0.05`, and every objective's `start_time` of `0.0475` admits that step
and no other. Both ends of the accepted interval sit half a timestep from a
sample, so no amount of round-off in the accumulated time can change which
steps are counted.

An `end_time` sitting *on* a step boundary is what to avoid, and not for a
subtle reason: with `end_time = 0.05` and `dt = 0.005` the accumulated time
after ten steps lands just below `0.05`, the loop takes an eleventh step, and
the run ends at `t = 0.055`. The window then holds two samples while the
steady path still evaluates one, and the objectives disagree by 0.3%, 10% and
0.2% — a real failure with a thoroughly misleading cause. The underlying
overshoot is Neko's, not this test's.

Measured agreement between the two paths, with the window right, is `4e-13`,
`4e-12` and `6e-14` relative, the same floor two identical unsteady runs of
this case reach.

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
