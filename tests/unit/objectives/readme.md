# Objective time-window tests

These tests check that an objective's reported value depends only on the time
window it is accumulated over, and not on how long the simulation happens to
run, nor on which of the two code paths — steady or unsteady — evaluated it.
They replace the former `examples/time_test`, which covered the same matrix
but could only be inspected by hand.

Four properties are checked, split across two lanes. Three cases are tagged
`unit` and gate every CI run: `time_window_run_length`,
`time_window_equivalence`, `steady_unsteady_final_step`. The fourth,
`steady_unsteady_converged`, now lives in `tests/regression/objectives/`
(its own `CMakeLists.txt`, registered as the `steady_unsteady_converged`
CTest) rather than here. Reaching a genuine steady state at this suite's
`Pe = 1000` is dominated by the design domain's diffusive equilibration, a
cost that is not tunable away by mesh or timestep choices the way the other
three cases' costs are, so it now runs as an opt-in regression check with a
much longer `ctest` `TIMEOUT` instead of gating every CI run. Its driver
(`time_window_tester.f90`) and shared user module (`objectives_user.f90`)
are unchanged and still live here, referenced by path from the regression
lane's `CMakeLists.txt`, since the three cases that remain in this directory
still need them too. See "`steady_unsteady_converged` (regression lane)"
below for that case's own numbers.

## Common files

- `prepare.sh`: builds the box mesh (`genmeshbox`), a short channel with all
  six boundary faces exposed as separate zones. `-N6` (the default) generates
  a `12x6x6`-element mesh (`Nx = 2N`, `Ny = Nz = N`, cubic, no periodicity).
  Also used, by reference, by `tests/regression/objectives/`'s own
  `CMakeLists.txt`, so both lanes run on the same mesh.
- `objectives_user.f90`: the user-defined inflow, shared by every case here
  — both the paraboloid velocity profile at the inlet and the scalar split,
  since both are imposed through the same `user_dirichlet`-style callback
  (`user%dirichlet_conditions`).
- `time_window_tester.f90`: the driver. It runs the case once per entry in
  `optimization.time_window_test.end_times` and compares the objective
  values across those runs and, optionally, against each other within a run.

With `compare_steady` set it also runs the case with `simulation_t%unsteady`
cleared — the flag `problem_t%compute` branches on — and requires that
result to agree with the unsteady ones. `require_steady_state` additionally
asserts that every run reached a steady state, which is what makes a window
average comparable to a single converged field at all.

Only the objectives declared in the case file are checked. `problem_t`
appends an internal augmented-Lagrangian objective of its own, which the
driver skips.

The driver calls `problem_t%compute` and never `compute_sensitivity`, so no
adjoint is solved. That is what keeps these affordable as unit tests.

## The physics

Every case here matches `examples/unsteady_mixer`
(`examples/unsteady_mixer/user.f90` + `unsteady_200.case`): `Re = 200`,
`Pe = 1000`, a paraboloid `user_velocity` inlet, `no_slip` duct walls
(zones 3-6), a logistic scalar split imposed via `user_dirichlet` at the
inlet, the other five scalar faces zero-flux Neumann, and a `scalar_mixing`
objective masked to a zone downstream of the inlet. This suite began as a
conversion of `examples/time_test` (now deleted), and for a time ran at
`Re = 5`-`50`, `Pe = 100` — diffusion-dominated conditions that do not
exercise advection the way the reference's `Pe = 1000` does — before being
brought in line with the reference physics.

`objectives_user.f90` implements the shared inflow. The inlet velocity is
`36 * y * (y - 1) * z * (z - 1)`, a paraboloid over the duct's unit-square
cross-section, scaled so its mean is 1 (unit flow rate through the duct) and
vanishing on all four walls, so it agrees with `no_slip` there instead of
being discontinuous at the inlet edges. The scalar boundary and initial
conditions are the same logistic split in `z`,
`1 / (1 + exp(-split_steepness * (z - 0.5)))` with `split_steepness = 20`,
imposed both at the inlet and as the initial condition, so no run opens with
a transient it then has to sit through before it can start measuring
anything.

### The scalar setup

For this split profile a completely unmixed scalar gives a `scalar_mixing`
objective of `0.1000` against the default `target_concentration` of `0.5`,
and a uniformly mixed one gives `0`. (Note: the *documented* key for the
target is `target_concentration`
(`documentation/pages/user_guide/objectives_and_constraints.md`); the
reference example's own case files set a `phi_ref` key instead, which
`scalar_mixing_objective_function.f90` never reads — confirmed directly
against the source. None of the cases here set either key, so they all get
the documented default of `0.5`.)

### Objective masks

Every case that declares a downstream `scalar_mixing` objective, masked to
`objective_domain` (`x ∈ [1.5, 2.0]`, the final quarter of the duct, the
equivalent of the reference's own downstream mask), now also declares a
second one masked to `inlet_region` (`x ∈ [0.0, 0.25]`) — deliberately
upstream of the design region (`optimization_domain`, `x ∈ [0.25, 0.75]`,
and `initial_blob`, `x ∈ [0.25, 0.5]`), so it is a clean reference reading
rather than one straddling the stagnant Brinkman blob's own slow diffusive
equilibration (see "`steady_unsteady_converged`" below). This gives every
case two measurement points: an inlet reading, and a downstream reading, the
actual mixing signal. `time_window_equivalence` needs its objectives in
consecutive matched pairs (see its own section below), so there the inlet
measurement is added as a second pair using the same two window forms as the
downstream pair, rather than as a single extra objective.

The design-only zones, `optimization_domain` (the Brinkman design domain)
and `initial_blob` (the initial material distribution), are unrelated to the
objective masks and are the same in every case here.

## Mesh resolution

`prepare.sh -N6` (the default) generates `Nx = 12`, `Ny = Nz = 6` cubic
elements. With `polynomial_order = 3` (every case here), that puts
`N * polynomial_order + 1` GLL points across a mesh direction: 19 across `y`
and `z`, up from the 13 an earlier `N = 4` mesh gave at this suite's
previous `Pe = 100`. `Pe = 1000` is a tenth of the diffusivity, so
`split_steepness = 20`'s transition is carried with a tenth of the physical
smoothing once it starts advecting and diffusing downstream of the inlet;
`N = 6` was chosen to keep the resolving margin relative to that steepness
comparable to what the `N = 4` mesh had at `Pe = 100`, not measured against
it directly.

This is a reasoned default, not a resolution-vs-cost sweep: `N = 4` has not
been re-tried at `Pe = 1000` for comparison, and `polynomial_order` has not
been tried at anything other than `3`. What the measurements below do show
is that `N = 6` runs to completion in all four cases without a solver
failure, and produces mixing values that behave the way the physics
predicts — in particular the converged ordering in
`steady_unsteady_converged` below, which is exactly what a physically
sensible mixing measurement should look like. That is evidence this mesh is
*workable* at the current physics, not evidence that it is the coarsest
mesh that would be.

## `time_window_run_length`

The regression guard. Every objective is given the closed window `[0.02,
0.04]`, which lies inside both runs (`end_times: [0.05, 0.1]`), so each
objective measures the same interval whether the run stops at `t = 0.05` or
continues to `t = 0.1`. The values must therefore be identical. This is also
this suite's case of a *strictly interior* window — `0 < 0.02` and `0.04 <
0.05` (and `< 0.1`) — touching neither end of either run.

This is the property that was broken before: accumulation was normalised by
the *simulation's* window rather than the objective's own, so doubling the
run halved every windowed objective.

Measured (wall time `15.43 s`): both end times reported the same values to
full printed precision, as the invariance being checked requires. The two
`scalar_mixing` readings, common to both runs, were

| mask | value |
|---|---|
| `objective_domain` (downstream) | `0.0998678386316453` |
| `inlet_region` (upstream) | `0.0986633038105423` |

well inside the `1e-9` tolerance (unchanged).

**Read this table carefully: the ordering is the opposite of what a
converged run shows.** The upstream reading sits noticeably further from
the fully-unmixed `0.1000` (about `0.0013` away) than the downstream one
(about `0.0001` away) — as if more mixing had happened upstream than
downstream. That is correct, not a mask or sign error, and it is purely a
consequence of how little time has passed. This window sits at
`t ∈ [0.02, 0.04]`, only 1-2% of the residence time `L / u = 2`. Nothing has
advected as far as the downstream mask yet, so it is still reading
essentially its undisturbed initial split; the only place anything is
happening at all is the inlet, where the entrance flow is establishing real
shear against the paraboloid profile and the no-slip walls. The practical
upshot is that at these short times the *inlet* objective is the one
carrying genuine temporal variation, which is what makes it a meaningful
test of a time accumulator here — the downstream one, this early, would
pass even if the accumulator did nothing at all.

## `time_window_equivalence`

The semantic check, covering the four ways a window can be written. The
objectives are read as consecutive pairs, each pair selecting the same
samples by different means:

| pair | objective | first form | second form |
|------|-----------|------------|-------------|
| 1 | viscous dissipation | `end_time` only | the same window written out in full |
| 2 | Brinkman dissipation | no window at all | an explicit `start_time` of zero |
| 3 | scalar mixing, downstream | `start_time` only | a closed window running past the end of the run |
| 4 | scalar mixing, inlet | `start_time` only | a closed window running past the end of the run |

Pair 4 keeps the objective count at eight (four pairs), which `pairwise`
requires to be even, and checks the inlet measurement's window-form
equivalence alongside the downstream one. Pairs 3 and 4 also exercise a
window clipped by the end of the run: their `end_time` of `0.06` is
deliberately beyond the run's own `end_time` of `0.05`.

Note that this test cannot catch a normalisation error on its own — every
objective in a single run shares the same divisor, so a global rescaling
cancels out of a within-run comparison. `time_window_run_length` is what
guards that; this one pins down what each window form means.

Measured (wall time `6.54 s`): all four pairs agreed to full printed
precision, and the driver's own pass/fail check accepted the run. The two
mixing pairs also give this run's two-measurement-point readings:

| mask | value |
|---|---|
| `objective_domain` (downstream) | `0.0998430862370785` |
| `inlet_region` (upstream) | `0.0983705834616011` |

The same inversion as `time_window_run_length` is visible here (upstream
about `0.0016` from `0.1000`, downstream about `0.0002`), for the same
reason: this run covers `t ∈ [0, 0.06]`, still only a few per cent of the
residence time, so the inlet is where the visible action is. See that
case's section above for the full explanation.

## `steady_unsteady_final_step`

The same steady-versus-unsteady comparison with convergence taken out of
it. The case is `time_window_run_length` unchanged apart from a `steady`
simulation component and a window holding the final timestep alone; a
one-sample average is that sample, so the two paths must agree exactly
whatever the flow is doing. `dt` and `end_time` are `0.005` and `0.0475`
respectively.

This exists to localise a failure of `steady_unsteady_converged`. If both
fail, the two paths disagree about which field they evaluate. If only the
converged one fails, the paths are fine and the run is not reaching a
steady state. An unconverged run is also the stricter comparison of the
two: a frozen field gives the same objective at every step near the end, so
a path sampling the wrong step would slip through, whereas a field still in
motion catches it. That the fluid genuinely has not converged by
`t = 0.0475` is not just assumed here: `steady_unsteady_converged` (below)
measures the fluid freezing at `t ≈ 12.69` under this same physics — over
260 times this case's own duration — so a field at `t = 0.0475` is
certainly "still in motion" in the sense this test relies on.

Measured (wall time `10.96 s`):

| mask | steady | unsteady | relative difference |
|---|---|---|---|
| `objective_domain` (downstream) | `0.0998018277746947` | `0.0998018277746764` | `1.8e-13` |
| `inlet_region` (upstream) | `0.0978798025626617` | `0.0978798025626720` | `1.1e-13` |

both well inside the `1e-9` tolerance. The same early-time inversion as the
other two cases shows up again (upstream about `0.0021` from `0.1000`,
downstream about `0.0002`), for the same reason given under
`time_window_run_length` above.

### Ordering, and why it matters

Both tests that use `compare_steady` run the steady path first. Every run
leaves its values in the same objectives, so a steady path that quietly
stopped evaluating them would, running second, still be holding the
unsteady run's numbers and would agree with it. Running first it reports
the objectives' initial zero instead. Checked by deleting the
`update_objectives` call from `problem_compute`'s steady branch: the test
failed with a relative difference of exactly `1.0`. With the other order it
passed.

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
after ten steps lands just below `0.05`, the loop takes an eleventh step,
and the run ends at `t = 0.055`. The window then holds two samples while
the steady path still evaluates one, and the objectives disagree — a real
failure with a thoroughly misleading cause. The underlying overshoot is
Neko's, not this test's. `steady_unsteady_converged` (now in
`tests/regression/objectives/`) uses the same half-step-short pattern for
the same reason: its `end_time = 99.9975` lands its run exactly at
`t = 100.0`.

## `steady_unsteady_converged` (regression lane)

**This case now lives in `tests/regression/objectives/cases/
steady_unsteady_converged.case`, registered as the `steady_unsteady_
converged` CTest in `tests/regression/objectives/CMakeLists.txt`, not in
this directory.** See the introduction above for why. The driver and user
module it needs are unchanged and still live here.

The steady and the unsteady approach are two ways of putting a number on
the same problem, and once that problem has reached a steady state they
must give the same number. This test is that statement: the flow is run to
convergence, the steady path evaluates each objective on the converged
field, the unsteady path averages the same objective over a window lying
inside the converged tail, and the two are required to agree.

`end_time = 99.9975` (timestep `0.005`, landing the run at `t = 100.0`, half
a timestep short of a step boundary — see "Step boundaries" above), and the
objectives' window is `start_time = 98.9975` (`end_time` unset), i.e.
`[99, 100]`. Wall time for the full two-pass (steady + unsteady) test was
`1382.56 s`; `ctest`'s `TIMEOUT` is `3600 s`.

### The fluid freezes long before the scalar settles

The `steady` simulation component (`tol = 1e-6`, `scalar_coupled = false`)
freezes the fluid between `t = 12.690` and `t = 12.695`: `Fluid step time`
drops from `0.8479822E-01` to `0.6800000E-06` at step 2538→2539. With
`scalar_coupled = false` the fluid's own convergence alone decides the
freeze — the scalar's is tracked but does not gate it (`steady_simcomp.f90`
computes and logs a scalar residual regardless, but only lets it affect the
freeze decision when `scalar_coupled` is set). At the moment the fluid
freezes, the scalar residual is `3.856e-05` and e-folding every roughly
`3.38` time units — nowhere near settled. This is exactly why the case
still needs to run to `t = 100` rather than stopping once the fluid
freezes: the fluid gets cheap quickly, but the scalar keeps evolving,
advecting and diffusing on the now-frozen velocity field, for a long time
afterwards.

That last point is also what makes the long run affordable: extending
`end_time` from `49.9975` to `99.9975` — doubling the simulated duration —
cost only about 3% more wall time (`1339 s` → `1382 s`), because every step
after the freeze costs about `0.009 s` against about `0.5 s` during the
transient. Do not shorten `end_time` to save wall time without re-deriving
the margins below, since that is exactly what reintroduces the failure they
describe.

### Converged objective values

Against the test's `1e-9` tolerance:

| objective | value | rel. diff. (steady vs unsteady) | margin |
|---|---|---|---|
| `viscous [99,100]` | `0.232570375417663` | `4.296e-15` | `232756x` |
| `brinkman [99,100]` | `0.0537448808899309` | `3.744e-15` | `267085x` |
| `mixing whole [99,100]` | `0.0935233106515700` | `8.607e-15` | `116191x` |
| `mixing down [99,100]` | `0.0902515503183729` | `5.536e-15` | `180647x` |
| `mixing inlet [99,100]` | `0.0986744602166589` | `4.079e-15` | `245181x` |

At this converged state the ordering **is** the physically expected one —
the opposite of the short unit tests above, because there has now been
enough time for it to develop: downstream is the most mixed (`0.0903`),
upstream is nearly untouched (`0.0987`, i.e. 98.7% of the fully-unmixed
`0.1000`), and the unmasked whole-domain reading sits between the two
(`0.0935`).

### Why the window is `[99, 100]` and not `[49, 50]`

`[49, 50]` was tried first and **failed**: `mixing whole` came out at a
relative steady-vs-unsteady difference of `2.014e-9` against the `1e-9`
tolerance, with `mixing down` marginal at `9.187e-10` and `mixing inlet`
passing comfortably at `4.280e-10`. The two velocity-based objectives were
unaffected either way, at about `4e-15`.

The mechanism, because it is not obvious: the steady path evaluates a
single field at the final step, while the unsteady path averages over the
window. While the scalar is still drifting monotonically, the window
average systematically lags the endpoint by roughly (drift rate × half
window). **Averaging does not cancel a systematic drift** — it only shrinks
it, and how much it shrinks depends on how far the drift itself has decayed
by the start of the window.

The ordering across objectives confirms this reading: the unmasked `mixing
whole` contains the Brinkman blob, which is stagnant (velocity driven to
~0 by the Brinkman penalisation) and so equilibrates only diffusively, on a
`Pe * L^2 ≈ 62` time-unit scale — far slower than the masked objectives,
which exclude it and do better; the upstream one, furthest from where
anything at all is still happening, does best of all.

Independent settling data confirms the trend directly: one forward pass to
`t = 300`, sampling all three masks at four windows, gives this relative
drift between consecutive windows:

| mask | `[49,50]`→`[99,100]` | `[99,100]`→`[199,200]` | `[199,200]`→`[299,300]` |
|---|---|---|---|
| whole domain | `2.956e-10` | `1.211e-12` | `2.566e-13` |
| downstream | `1.346e-10` | `1.008e-12` | `1.595e-13` |
| inlet | `6.279e-11` | `1.458e-13` | `1.966e-13` |

— three to four orders of magnitude smaller by `[99,100]` than by `[49,50]`
for every mask, matching the tolerance now being met with several orders of
margin.

## The rejected freestream experiment

Inlet and walls were briefly set to a uniform `velocity_value: [1, 0, 0]`,
on the theory that the no-slip boundary layer was what made the scalar slow
to settle. That was checked directly, not just reasoned about, and it was
rejected on every count it was tried against:

- The scalar became **roughly 6.6x slower** to equilibrate, not faster
  (e-folding roughly `4.9` time units, versus roughly `0.74` under the
  no-slip/paraboloid physics that replaced it). The bottleneck was never
  the boundary layer; it is the stagnant Brinkman blob, which equilibrates
  diffusively regardless of the outer boundary condition.
- It destroyed the mixing signal this suite exists to check. With slip
  walls and a uniform inlet there is no shear to stretch the split
  interface, so all three `scalar_mixing` objectives read `0.0948`-`0.0950`
  against the fully-unmixed `0.1000` — about 5% mixed, versus roughly 35%
  mixed under the physics that replaced it. The inlet and downstream
  readings also agreed to within `0.02%` of each other, making the second
  measurement point (`inlet_region`) worthless: there was essentially
  nothing left for it to distinguish.
- The fluid also froze much later (`t ≈ 22.4` versus `t ≈ 12.69`), and the
  three short unit tests ran `2.5`-`3x` slower (`42.4 s` / `18.3 s` /
  `32.5 s`, against the `15.43 s` / `6.54 s` / `10.96 s` measured above).

The point of recording this compactly is so a future reader proposing the
same simplification — removing the no-slip boundary layer to speed
convergence — finds out it was tried and what it actually measured, rather
than re-discovering all of the above the slow way.

## Choosing window boundaries in new cases

Prefer a closed `end_time` strictly inside the run rather than exactly
equal to the run's own `end_time`. Objectives hand their window to the
adjoint forcing source terms, and `source_term_t`'s gate compares against
the accumulated simulation time with no tolerance, so a boundary landing
exactly on the final step can silently lose that step's forcing.

Keep every window boundary away from a step time, by roughly half a
timestep. The accumulation gate has a `1e-6 * dt` tolerance, so a boundary
sitting on a step is decided by round-off in the accumulated time rather
than by the case file. The same applies to the simulation's own `end_time`,
which decides how many steps the run takes — see "Step boundaries" and
`steady_unsteady_converged` above.

To select the final step alone, set `start_time` to the simulation's
`end_time` and leave the objective's `end_time` unset. The run always
overshoots a non-boundary `end_time` by exactly one step, so that window
holds one sample.

## Also worth knowing

- Objective names are capped at 25 characters by `base_functional_t`
  (`character(len=25)`), which silently truncates rather than erroring
  (backlog item #41, pre-existing on `develop`, not fixed here). Treat this
  as a live constraint on any new objective added to a case in this suite:
  keep the name, window suffix included (e.g. `[0.02,0.04]`), inside 25
  characters, following the abbreviated form already used throughout this
  directory and in `steady_unsteady_converged.case` (`mixing down
  [99,100]` rather than `mixing downstream [99,100]`). A name over the cap
  would not affect the pass/fail result here, since `time_window_tester.f90`
  compares objectives by their position in the case file's list, never by
  name — but it is still what a person reads in the log when working out
  which objective misbehaved, so it is worth getting right regardless.
- `ctest -R <test>` does **not** build the custom targets in a test's
  `DEPENDS` — those are ordering hints between CTest tests, not build
  dependencies — so after editing a `.case` file you must
  `cmake --build build` first, or you will run the previous copy.
