# Objective time-window tests

These tests check that an objective's reported value depends only on the time
window it is accumulated over, and not on how long the simulation happens to
run, nor on which of the two code paths — steady or unsteady — evaluated it.
They replace the former `examples/time_test`, which covered the same matrix but
could only be inspected by hand.

The tests are tagged as `unit`, so they are mandatory for CI to pass.

## Common files

- `prepare.sh`: builds the box mesh (`genmeshbox`), a short channel with all
  six boundary faces exposed as separate zones.
- `objectives_user.f90`: the user-defined scalar inflow, shared by every case
  here (see "The scalar setup" below). It carries no velocity routine; the
  velocity side is expressed entirely in the case file (see "Freestream
  velocity, not the example's paraboloid").
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

## Matching the reference physics

These tests were built by converting `examples/time_test` (now deleted) into
automated tests. In doing so they drifted from being *representative*
physics: they ran at `Re = 5` or `Re = 50`, `Pe = 100`, on a paraboloid-inlet,
no-slip-wall duct. The project's actual reference physics for a
`scalar_mixing` objective is `examples/unsteady_mixer`
(`examples/unsteady_mixer/user.f90` + `unsteady_200.case`): `Re = 200`,
`Pe = 1000`, a logistic scalar split (`k = 20`, `z_0 = 0.5`) at the inlet via
`user_dirichlet`, `no_slip` walls with the other five scalar faces Neumann-
insulated, `dong`-stabilized outflow, and a `scalar_mixing` objective masked
to a zone downstream of the inlet. `Pe = 100` is diffusion-dominated and does
not exercise advection the way `Pe = 1000` does, so every case here now runs
`Re = 200`, `Pe = 1000`.

### The scalar setup: unchanged from the reference

The scalar boundary and initial conditions are exactly the reference's:
`user_dirichlet` carrying the logistic split at the inlet, zero-flux Neumann
on the other five faces, and the same profile as the initial condition so no
run opens with a transient it then has to sit through. `objectives_user.f90`
implements this; the driver registers it on `sim%neko_case%user` before
`sim%init`, which works because `user_intf_init` only substitutes its own
defaults for pointers still null. No `makeneko` is involved.

The split uses `split_steepness = 20`, as the reference does. See "Mesh
resolution" below for how many points that puts across the transition on
this mesh.

For this profile a completely unmixed scalar gives a `scalar_mixing`
objective of `0.1000` against the default `target_concentration` of `0.5`
(`0.5^2 / 2`), and a uniformly mixed one gives `0`. (Note: the *documented*
key for the target is `target_concentration`
(`documentation/pages/user_guide/objectives_and_constraints.md`); the
reference example's own case files set a `phi_ref` key instead, which
`scalar_mixing_objective_function.f90` never reads — confirmed directly
against the source. None of the cases here set either key, so they all get
the documented default of `0.5`.)

### Freestream velocity, not the example's paraboloid

This substitution is deliberate and, unlike `Re`/`Pe`/the scalar setup, is
*not* meant to match the reference. `examples/time_test` and
`examples/unsteady_mixer` both drive a paraboloid inflow into a no-slip duct.
No-slip walls introduce a boundary layer that drastically slows the
*fluid's* approach to steady state, without changing what `scalar_mixing`
actually measures — mixing across the scalar split interface, not near-wall
shear. So here:

- Inlet (zone 1): `velocity_value`, `[1, 0, 0]`, replacing `user_velocity`'s
  paraboloid. `velocity_value` is the case-file-native Dirichlet-velocity
  type (`doc/pages/user-guide/case-file.md`, "Available conditions" —
  "Suitable for velocity inlets, moving walls, certain freestream
  conditions, etc."); no user routine is needed for it.
- Duct walls (zones 3-6): the same `velocity_value` `[1, 0, 0]`, replacing
  `no_slip`. The walls no longer enforce zero velocity.
- The fluid's initial condition is likewise uniform `[1, 0, 0]`, not `[0, 0,
  0]`: since every Dirichlet velocity boundary in the domain (everything but
  the outlet) already prescribes exactly that value, `[1, 0, 0]` is the
  domain's own steady solution — zero velocity gradient everywhere, so zero
  viscous term and zero convective term, satisfying the steady incompressible
  equations for any `Re`. Starting there means there is no startup transient
  to sit through at all, fluid-side.
- `outflow` at zone 2 and the adjoint velocity boundary conditions are
  unchanged: adjoint velocity BCs are homogeneous Dirichlet at exactly the
  locations the forward problem prescribes a value, regardless of what that
  forward value is, which is also why `examples/unsteady_mixer`'s own
  `adjoint_fluid` stays `no_slip` even though its forward BCs are a
  paraboloid/no-slip mix rather than matching its own forward values.

Because the velocity field becomes trivial in the continuous equations,
`Re = 200` is essentially inert here — it multiplies a viscous term that is
exactly zero on the exact solution — and is kept only to match the
reference's value rather than to mean anything numerically. The original
version of this section claimed this would make `steady_unsteady_converged`'s
fluid path converge in "on the order of one to a few steps." **That claim was
checked directly and is wrong** — see that case's own section below for what
was actually measured. The discrete solve, not the continuous one, is what
runs, and it does not reach its converged state quickly here.

### Objective masks: `objective_domain` and the new `inlet_region`

The masked `scalar_mixing` objective's zone is renamed from this suite's
`outlet_region` back to `objective_domain`, matching the reference's name for
the equivalent zone (`unsteady_200.case`'s `objective_domain`, `x ∈ [3.5,
6.5]` on its 8-unit-long mixer, i.e. its final ~40%). On this duct (length 2,
see "Mesh resolution") the equivalent span is `x ∈ [1.5, 2.0]`, the final
quarter — unchanged bounds from this suite's previous `outlet_region`, only
the name changes.

Every case that declares that downstream `scalar_mixing` objective now also
declares a second one masked to a new zone, `inlet_region`, `x ∈ [0.0, 0.5]`
— the first quarter, mirroring `objective_domain`'s span at the other end of
the duct. This is a second measurement point: the inlet reading is expected
to stay close to the fully-unmixed value of `0.1000` (there has been almost
no time or distance for advection and diffusion to act that close to the
inlet), while the downstream one is the actual mixing signal. `time_window_
equivalence` needs its objectives in consecutive matched pairs (see its own
section below), so there the inlet measurement is added as a second pair
using the same two window forms as the existing downstream pair, rather than
as a single extra objective.

The design-only zones, `optimization_domain` (the Brinkman design domain) and
`initial_blob` (the initial material distribution), are unrelated to the
objective masks and are unchanged.

## Mesh resolution

The mesh is still `genmeshbox` on a box, `x ∈ [0, 2]`, `y, z ∈ [0, 1]` —
`prepare.sh -N#` generates `Nx = 2N`, `Ny = Nz = N` elements, cubic, no
periodicity, so the six faces are the six zones. `N` was raised from `4` to
`6` (`12x6x6 = 432` elements, up from `128`) when the physics moved to `Pe =
1000`:

- The freestream substitution above means the velocity field needs no
  resolution at all beyond what any mesh already provides — it is uniform
  everywhere the case file doesn't leave to the pressure/outflow condition to
  decide, and the previous mesh's `N = 4` was never chosen for the velocity
  side in the first place (the duct's no-slip boundary layer was resolved by
  the paraboloid/no-slip pairing being smooth relative to the mesh, not by
  `N`).
- The `N = 4`, order-3 mesh was sized to resolve `objectives_user.f90`'s
  `split_steepness = 20` profile: 13 points across the split direction at
  `Pe = 100`. `Pe = 1000` is a tenth of the diffusivity, so the same profile
  is carried with a tenth of the physical smoothing once it starts advecting
  and diffusing downstream of the inlet. `N = 6` puts 19 points across the
  same direction, keeping the margin the original 13-point mesh had relative
  to `split_steepness = 20` closer to what it was, now that there is less
  physical diffusion to fall back on if the discrete profile rings.

**`N = 6` was run and is confirmed stable; it has not been compared against
other choices.** This container's shared Neko install currently fails to
build this branch's Neko-TOP sources from scratch (`ax_helm_factory`,
referenced by `sources/mapping_functions/PDE_filter_mapping.f90`, no longer
exists in Neko's `ax_product` module — confirmed directly against Neko's
current source; the shared install was rebuilt against a newer `develop`
after this branch's own build directory was last configured, and is
unrelated to anything in this directory or to the change described here).
That blocks rebuilding `time_window_tester_bin` from a source change, but a
copy of that binary built *before* the drift (2026-08-28) still runs, and the
scalar routine `objectives_user.f90` was only refactored, not behaviourally
changed, so it was used to actually run three of the four cases here end to
end against a freshly generated `N = 6` mesh:

- `time_window_run_length` and `time_window_equivalence` both ran to
  completion (`Normal end.`) with a stable `CFL` of `0.24`-`0.25` throughout,
  KSP residuals dropping many orders of magnitude within each step's
  iteration budget, and both tests' own pass/fail checks reporting
  `Time window check passed`. See their sections below for the actual
  objective values this produced.
- `steady_unsteady_final_step` likewise ran to completion and passed; see its
  section below.
- `steady_unsteady_converged` was attempted and did *not* complete in the
  time available — see its own section for what that run up to failure did
  measure, which is the most consequential finding in this update.

None of this is a resolution-vs-cost *sweep*: `N = 4` was not re-tried under
the new physics for comparison, and `polynomial_order = 3` was left
unchanged throughout on the reasoning in the bullets above, not because it
was tested against a higher order. What is now confirmed, rather than
reasoned, is that `N = 6` at `Pe = 1000` with the freestream substitution
does not visibly ring, oscillate, or destabilise the scalar over the three
short-to-medium runs above. A real resolution sweep, and a check of whether
`N = 6` is more than this problem needs, remain open; see NEXT in the
driving report.

## `time_window_run_length`

The regression guard. Every objective is given the closed window `[0.02,
0.04]`, which lies inside both runs (`end_times: [0.05, 0.1]`), so each
objective measures the same interval whether the run stops at `t = 0.05` or
continues to `t = 0.1`. The values must therefore be identical. This is also
this suite's case of a *strictly interior* window — `0 < 0.02` and `0.04 <
0.05` (and `< 0.1`) — touching neither end of either run.

The window and end times are unchanged from before the physics change:
`dt = 0.005` is also unchanged, so the window still holds the same eight
sample points it always did, and nothing about *why* an interior window
demonstrates run-length invariance depends on `Re`, `Pe`, or the velocity
boundary condition — only on `dt` and the window bounds, neither of which
moved.

This was confirmed with a real run (see "Mesh resolution" for how, given the
build blocker), not just re-asserted: both the `t = 0.05` and `t = 0.1` runs
report

| objective | run to `t = 0.05` | run to `t = 0.1` | relative difference |
|-----------|--------------------|--------------------|---------------------|
| viscous `[0.02, 0.04]` | `0.0187495650086777` | `0.0187495650088468` | `9.0e-12` |
| Brinkman `[0.02, 0.04]` | `0.0521469923581698` | `0.0521469923572002` | `1.9e-11` |
| mixing downstream `[0.02, 0.04]` | `0.0998679228786833` | `0.0998679228787245` | `4.1e-13` |
| mixing inlet `[0.02, 0.04]` | `0.0997612847260359` | `0.0997612847260050` | `3.1e-13` |

well inside the `1e-9` tolerance, and the driver reported `Time window check
passed`. The two mixing values also confirm the window is not vacuous: at
`t ∈ [0.02, 0.04]` — barely a fortieth of the residence time `L / u = 2` into
the run — both masks read close to the fully-unmixed `0.1000`, as expected
this early.

The two masks are *not*, however, evidence of a developing inlet-to-outlet
mixing gradient yet, and it would be a mistake to read them that way: the
scalar's initial condition is the same `split_profile(z)` at every `x`, not
just at the inlet, and the inlet's own boundary value matches it exactly, so
with a perfectly uniform `u = 1` and the zero-flux scalar condition applied
at every other face *including the outlet*, the exact solution is `x`-
independent for all time — `objective_domain` and `inlet_region` would read
identically forever, since both average the same `x`-independent field over
the same `y, z` range. The `~0.0001` difference actually measured between
them (`0.099868` vs `0.099761`) is therefore not a mixing signal at all at
this stage; it is a symptom of the same discrete departure from the exact
uniform-velocity solution documented in `steady_unsteady_converged` below —
the velocity field is not yet perfectly `x`-independent early in the run, so
neither is the scalar it advects. A genuine inlet-vs-downstream mixing
difference is expected to emerge only once diffusion has acted over
something like the residence time, which is exactly what
`steady_unsteady_converged`'s longer window is for.

This is the property that was broken before: accumulation was normalised by
the *simulation's* window rather than the objective's own, so doubling the run
halved every windowed objective. That regression is orthogonal to the physics
this case runs, so the fix it guards remains verified independent of the `Re`/
`Pe`/BC changes above.

The tolerance is `1e-9`, unchanged.

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

Pair 4 is new: the same two window forms as pair 3, applied to the new
`inlet_region` mask instead of `objective_domain`, so the inlet measurement's
window-form equivalence is checked too, not just the downstream one. It also
keeps the objective count at eight (four pairs), which `pairwise` requires to
be even.

Pairs 3 and 4 also exercise a window clipped by the end of the run: their
`end_time` of `0.06` is deliberately beyond the run's own `end_time` of
`0.05`.

Note that this test cannot catch a normalisation error on its own — every
objective in a single run shares the same divisor, so a global rescaling
cancels out of a within-run comparison. `time_window_run_length` is what
guards that; this one pins down what each window form means. Unchanged from
before the physics change, for the same reason as that case: this property
depends on `dt` and the window forms, not on `Re`/`Pe`/the velocity BC, and
neither `dt` nor the forms moved.

This was also run for real (see "Mesh resolution"). All four pairs agreed to
full printed precision:

| pair | first form | second form |
|------|-----------:|------------:|
| 1 (viscous) | `0.0145229234508958` | `0.0145229234508958` |
| 2 (Brinkman) | `0.0853496852651658` | `0.0853496852651658` |
| 3 (mixing downstream) | `0.0998431834475658` | `0.0998431834475658` |
| 4 (mixing inlet) | `0.0996998008491864` | `0.0996998008491864` |

and the driver reported `Time window check passed`. Pairs 1 and 2 agreeing to
every printed digit is expected — the two forms in each pair select exactly
the same accumulation, so any difference would be pure floating-point
reassociation, not something this printed precision would show. Pairs 3 and
4 read slightly differently from each other for the same reason pair 3 and 4
differed in `time_window_run_length` above (the discrete velocity field is
not yet exactly `x`-independent at `t = 0.05`), which is expected and not
what this test is checking.

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

This case previously carried `Re = 5` (rather than the reference's `200`)
purely so the *fluid* converged fast enough to make a 20-time-unit run
affordable, and `Pe = 100` matching its siblings. Both are gone: `Re = 200`
and `Pe = 1000` now match the reference and every other case here. The
freestream substitution was expected to make the fluid affordable at the
reference `Re` without a slow-`Re` trick — that expectation was checked
directly against a real (partial) run, and is only half right. See below.

### What was actually measured: a real but decelerating relaxation

A run of this case (using the pre-existing binary described in "Mesh
resolution") was let run for a little over 9 minutes of wall time before
being stopped, reaching `t = 5.8` (step 1160 of the run as it was then
configured, `end_time = 7.9975`) without the `steady` simcomp's `tol = 1e-6`
being satisfied — the fluid had not frozen. That is itself useful evidence:
the previous claim in "Freestream velocity, not the example's paraboloid"
above, that the fluid would converge "in on the order of one to a few
steps," is wrong for the *discrete* solve, even though the *continuous*
uniform field is an exact steady solution.

The `Pressure` solver's own start-of-step residual (`gmres`'s residual
before that step's iterations, printed each step, distinct from the
`steady` simcomp's own internal metric, which is not printed) was tracked
across the partial run and does genuinely decay — no divergence, no
oscillation, no plateau at a nonzero floor — but its own e-folding time
grows rather than staying fixed:

| step range | residual at range start | residual at range end | implied e-folding steps |
|-----------:|-------------------------:|-----------------------:|-------------------------:|
| 100-300 | `2.15e-3` | `4.65e-4` | `~130` |
| 300-500 | `4.65e-4` | `1.38e-4` | `~165` |
| 500-700 | `1.38e-4` | `4.68e-5` | `~185` |
| 700-888 | `4.68e-5` | `2.77e-5` | `~360` |
| 888-1100 | `2.77e-5` | `1.90e-5` | `~580` |

A single fixed-rate exponential relaxation would show the same e-folding
figure in every row; this shows it roughly quadrupling over the observed
range. Extrapolating the last, slowest rate forward, reaching `1e-6` from
`1.9e-5` at step 1100 would need on the order of `1700`-`2800` further
steps — putting genuine convergence somewhere around `t = 14`-`20`, not the
`t ≈ 3`-`4` the "one to a few steps" framing implied, and in the same range
as, or worse than, the 20 time units the old `Re = 5`/no-slip/`Pe = 100`
version of this case needed. If the true rate keeps slowing rather than
settling, that extrapolation itself may be optimistic.

**This is a real, measured, and unresolved finding, not a solved problem.**
Two explanations seem plausible and neither was checked: a genuine slow
eigenmode of the discretisation near the box's sharp corners (where the
uniform-velocity Dirichlet condition meets across two faces at a right
angle, technically compatible but not obviously benign for a spectral
method's pressure/velocity splitting), or an artefact of the fractional-step
scheme's own consistency error relaxing away from an initial condition that
is exact for the continuous equations but not discretely self-consistent for
the scheme. Deciding between them — and finding out whether it ever
actually reaches `1e-6`, rather than asymptoting to something just above it
— is exactly the kind of question `algo-verify` or `neko-investigate` exists
for, not something to guess at further in a case-file-authoring pass.

### The numeric choices made anyway

`end_time` was doubled from the `7.9975` (four residence times, `L / u = 2 /
1 = 2`) this section originally reasoned to, to `15.9975` — eight residence
times, landing the run at `t = 16.0` (see "Choosing window boundaries" for
the half-step-short convention). The window (`start_time = 14.9975`,
`end_time` unset) covers the run's last time unit. **This is a good-faith
increase in light of the measurement above, not a confident fix**: the
extrapolation above puts likely convergence close to this new `end_time`, or
possibly past it, so this may still be too short. It is, at least,
self-checking: `require_steady_state` remains set, so an insufficient
`end_time` fails loudly (`'The run finished without reaching a steady
state; lengthen it...'`) rather than silently. `tests/unit/objectives/
CMakeLists.txt` gives this one test a `3600`s `ctest` timeout rather than
the other three's `300`s, for the same reason — a rough ceiling, not a
measured figure.

Unaffected by any of this: `dt = 0.005` (unified with the other three
cases, previously `0.01`), `f_max = 100.0` (matching the other cases' `chi *
dt = 0.5` now that `dt` is unified, previously `50.0`), scalar
`absolute_tolerance = 1e-12` (kept from before — the previous version of
this case found the default `1e-9` was a solver-noise floor when comparing a
single converged field against a ~100-sample window average, since the
noise partly cancels out of the average and not the single sample; nothing
here removes that mechanism), and `scalar_coupled = false` (so the fluid
freezes, whenever it does, without waiting on the scalar too).

### What it measures

Three `scalar_mixing` objectives are declared: unmasked (whole domain,
carried over from before the physics change as a diagnostic of how much of
the split survives overall), masked to `objective_domain` (downstream, the
equivalent of the reference's own masked objective), and masked to
`inlet_region` (new, expected to stay close to `0.1000`). Actual values for
all of these — and the steady-vs-unsteady relative differences that are this
test's real assertion — could not be measured: the run was stopped before
reaching either `require_steady_state`'s check or the objective windows.
This, along with resolving the relaxation-rate question above, is squarely
what needs to happen next; see NEXT in the driving report.

## `steady_unsteady_final_step`

The same steady-versus-unsteady comparison with convergence taken out of it.
The case is `time_window_run_length` unchanged apart from a `steady`
simulation component and a window holding the final timestep alone; a
one-sample average is that sample, so the two paths must agree exactly
whatever the flow is doing. `dt` and `end_time` are unchanged (`0.005` and
`0.0475` respectively) since, as with `time_window_run_length`, nothing about
this case's assertion depends on `Re`/`Pe`/the velocity BC — only on `dt` and
where the window sits relative to it.

This exists to localise a failure of `steady_unsteady_converged`. If both
fail, the two paths disagree about which field they evaluate. If only the
converged one fails, the paths are fine and the run is not reaching a steady
state. An unconverged run is also the stricter comparison of the two: a frozen
field gives the same objective at every step near the end, so a path sampling
the wrong step would slip through, whereas a field still in motion catches it.
That the fluid genuinely has not converged by `t = 0.0475` is no longer just
assumed: `steady_unsteady_converged`'s partial run above shows the discrete
fluid residual is still five-plus orders of magnitude away from `tol = 1e-6`
at similar early times, so this case's field is certainly "still in motion"
in the sense this paragraph relies on.

As with `steady_unsteady_converged`, a second `scalar_mixing` objective
masked to `inlet_region` is now declared alongside the `objective_domain`
one. This case *did* run to completion (see "Mesh resolution"); the steady
and unsteady paths agreed to within `7.6e-12`-`1.8e-11` relative on the two
non-mixing objectives and `8.9e-14`-`3.4e-13` on the two mixing ones:

| objective | steady | unsteady | relative difference |
|-----------|-------:|---------:|---------------------:|
| viscous | `0.0279777973582449` | `0.0279777973580320` | `7.6e-12` |
| Brinkman | `0.0155842192166730` | `0.0155842192169611` | `1.8e-11` |
| mixing downstream | `0.0998019466198299` | `0.0998019466198388` | `8.9e-14` |
| mixing inlet | `0.0995974727418635` | `0.0995974727418974` | `3.4e-13` |

well inside the `1e-9` tolerance, and the driver reported `Time window check
passed`.

### Ordering, and why it matters

Both tests run the steady path first. Every run leaves its values in the same
objectives, so a steady path that quietly stopped evaluating them would,
running second, still be holding the unsteady run's numbers and would agree
with it. Running first it reports the objectives' initial zero instead.
Checked by deleting the `update_objectives` call from `problem_compute`'s
steady branch: the test fails with a relative difference of exactly `1.0`.
With the other order it passed. (This check predates, and is unaffected by,
the physics change above.)

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
steady path still evaluates one, and the objectives disagree — a real failure
with a thoroughly misleading cause. The underlying overshoot is Neko's, not
this test's. `steady_unsteady_converged`'s `end_time = 15.9975` uses the same
half-step-short pattern for the same reason, landing the run exactly at
`t = 16.0`.

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
many steps the run takes — see `steady_unsteady_converged` above.

To select the final step alone, set `start_time` to the simulation's
`end_time` and leave the objective's `end_time` unset. The run always overshoots
a non-boundary `end_time` by exactly one step, so that window holds one sample.
