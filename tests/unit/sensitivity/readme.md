# Finite difference Sensitivity Test

This test verifies the sensitivity analysis of a design variable using finite
difference methods. It checks that the computed sensitivities match the
expected values within a specified tolerance.

The test is tagged as a `unit` test, which means it is mandatory for the
build to pass our CI/CD pipeline.

## Test Overview

The test is done through a few common files:

- `prepare.sh`: Script designed to construct a mesh for us to work on.
- `sensitivity.f90`: The shared finite-difference sensitivity checker module
  (MPI-safe reduction handling + the tolerance assertion). This same file is
  also used by `tests/regression/sensitivity/` — it is the single source of
  truth for both, see that directory's `CMakeLists.txt`.
- `problem_tester.f90`: The generic driver. It auto-detects whether the case
  under test defines an objective or a constraint and drives
  `compute_sensitivity` accordingly — it does not need to change when a new
  case is added.
- `*.case`: One Neko case file per test, each exercising a single
  objective/constraint type. The `fd_test_tolerance` key under
  `optimization` (optional, JSON) overrides the default assertion tolerance
  — linear/state-independent functionals (e.g. the volume constraint) can use
  a tight round-off tolerance; PDE-coupled objectives need a looser one
  matched to their discretisation/steady-state floor (determine this
  empirically per case, don't guess).
- `CMakeLists.txt`: Defines the build process and, via the `test_list`
  variable, registers one CTest per case file.

## Configuring the sweep

The assertion is made on the error at the **smallest** perturbation of the
sweep, which is the rule this harness has always used: for a one-sided
forward difference the error at large perturbations is dominated by
truncation and must not be asserted against.

Separately, and for information only, the harness *reports* the minimum
`|error|` over the sweep and whether that minimum is interior to it
(`BRACKETED`). A minimum sitting at either end is reported as
`NOT BRACKETED`: at the smallest perturbation tried it means the round-off
upturn was never reached (extend the sweep to smaller perturbations), and at
the largest it means the error was still falling as the perturbation grew
(extend the sweep to larger perturbations). Either way the number is only a
bound on the floor, and the run says so explicitly rather than reporting an
end point as if it were the floor. **Nothing is asserted on it** — which
point of a sweep a gating assertion should use is an open question, not one
this change answers.

The regression driver (`tests/regression/sensitivity/problem_tester.f90`)
takes three optional keys under `optimization`, alongside
`fd_test_tolerance`:

- `fd_test_perturbations`: a JSON array of strictly positive perturbation
  magnitudes, any length and any order. Defaults to
  `[1e-1, 1e-2, 1e-3, 1e-4]`, exactly the sweep used before it was
  configurable. Bracketing a floor generally needs a much wider sweep than
  that, e.g. 1e-1 down to 1e-7 at two points per decade.
- `fd_test_central_difference`: `true` to use a central difference, whose
  truncation error is O(eps^2) rather than O(eps), so it reaches the floor at
  a far larger perturbation and separates floor from truncation much more
  cleanly. Costs two forward solves per perturbation instead of one, and
  needs the design variable to sit strictly inside its bounds. Defaults to
  `false`, the one-sided forward difference.
- `fd_test_mode`: `dof` (the default) to probe a single design degree of
  freedom, or `directional` for the Taylor test described below. See
  "Which direction the sweep differentiates along".

All three can also be set from the environment, which overrides the case file
and lets one sweep be driven across several cases without editing any of them:
`NEKO_TOP_FD_PERTURBATIONS="1e-1,5e-2,1e-2"`, `NEKO_TOP_FD_CENTRAL=1`
(strictly `1`/`true`/`yes`/`on` or `0`/`false`/`no`/`off` — anything else is
an error, never a silent false) and `NEKO_TOP_FD_MODE=directional`. The unit
driver is always in `dof` mode, and keeps its own fixed eight-point sweep
unless the strict criterion below is switched on, in which case it reads the
sweep the same way the regression driver does.

## The strict criterion (`fd_test_strict`)

The assertion on the smallest perturbation is a **false green whenever the
signed error crosses zero inside the sweep**. Bug #43 is the worked example:
its four measured rows read `2.3e-6` at the smallest perturbation, while the
bias of that gradient is `1.46e-5` — the sweep happened to sample near the
crossing. The error at one point of a sweep is not the bias.

`"fd_test_strict": true` under `optimization` swaps that assertion for one
that separates the bias from truncation first. It is **off by default**, so
no existing case changes verdict. Two certificates are computed, and the
sweep passes if either certifies that `|C| <= fd_test_tolerance`:

- **BOUNDED** — a window of at least three consecutive points whose signed
  errors span at most `fd_test_plateau_fraction * tolerance`. Truncation is
  negligible across such a window, so it *bounds* the bias by
  `|mean| + 2*spread`. This is what certifies `volume` and
  `volume_filtered`: both are exactly linear in the design variable, have no
  truncation branch, and find no order run at any order tolerance up to 2.0.
- **FIT** — the differences `d_k = e_k - e_{k+1}` cancel the bias exactly, so
  the truncation order can be measured without knowing it. Over the longest
  single-signed run of the expected order the bias is *estimated* by
  Richardson extrapolation and cross-checked against a three-term fit (a
  disagreement warns, it does not fail).

Anything else is `INCONCLUSIVE`, which is a **loud failure saying the sweep is
inadequate** — deliberately a different statement from the gradient being
wrong, because conflating the two is how a bad sweep gets read as a bad
adjoint. The same applies to `TOLERANCE_UNREACHABLE`: the harness measures
the smallest tolerance the functional's own reproducibility permits,
`sqrt(40*N*|A|)`, and a tolerance below it cannot be decided by any sweep of
any depth. Measured: `#43` 9.9e-6, `brinkman_dissipation` 1.1e-4,
`viscous_dissipation` 1.4e-4, `volume` 4.2e-9, `volume_filtered` 1.8e-7 —
note that the unit tier's default `fd_test_tolerance` of 1e-5 is unreachable
for any case with a real truncation slope, which is why the two dissipation
cases already override it.

Whether the sweep brackets the round-off upturn is **reported and never gated
on**. Requiring an upturn rejects bug #43's own sweep and lifts the false-red
rate from 0.012 to 0.73, with no value of the bracketing factor recovering
it. Sign crossings are counted for the same reason and never used to exclude
points.

Three further optional keys, all under `optimization`:

- `fd_test_order`: the truncation order to expect. Defaults to `1.0`, or
  `2.0` when `fd_test_central_difference` is on.
- `fd_test_order_tolerance`: half-width of the accepted band around that
  order. Defaults to `0.10`. Tightening it from 0.25 to 0.10 trims the
  largest-perturbation points, where the functional is strongly nonlinear,
  out of the fit window — measured false-red 0.0023 against 0.0123. It must
  be smaller than `fd_test_order`: a band as wide as the order accepts a
  measured order of zero, which is no truncation branch at all.
- `fd_test_plateau_fraction`: how flat, as a fraction of the tolerance, a
  window must be to bound the bias. Defaults to `0.25`.

With the criterion on, the sweep defaults to nine geometric points from 1e-1
to 1e-5 (ratio `sqrt(10)`) instead of the historical four. An explicit
`fd_test_perturbations` still wins. The order estimate is a statement about
successive *ratios*, so a geometric sweep is what it is calibrated on; a
non-geometric one (the unit tier's `[5e-1, 1e-1, 5e-2, ...]` alternates 5, 2,
5, 2) is still handled correctly, because the order is recovered by bisection
on `R(p) = (m0^p - m1^p)/(m1^p - m2^p)` rather than read off a single ratio.

Each strict run appends one row to **`FD_verdict_<case>.csv`**:
`p_hat, C_hat, branch, status, bracketed, min_abs_error, min_perturbation,
n_truncation_points, n_sign_crossings, C_hat_kind, tol_min`. `C_hat_kind`
distinguishes a FIT *estimate* from a BOUNDED *bound* — they are different
claims and must not be read as the same number. `FD_check_<case>.csv` is
untouched by all of this, schema and contents both.

The criterion refuses a sweep it cannot read rather than analysing it
anyway: one carrying a NaN, one mixing step signs, or one **repeating a
perturbation magnitude**. The last is the likely one in practice, because
the step is clamped against the design bounds and several requested points
can collapse onto the same bound-limited value; the error message names the
repeated magnitude. A repeat is one measurement recorded twice, and because
a plateau is priced by the *spread* of its errors, duplicates would lengthen
a window at zero spread and certify a bound from a single point.

## Two guards that apply whether or not the criterion is on

- **Degenerate sensitivities.** An analytic sensitivity below `1e-10` of the
  largest in the field is treated as degenerate and asserted on as an
  **absolute** difference. `max(|b|, NEKO_EPS)` only rules out an exact zero,
  so a sensitivity of 1e-12 in an O(1) field passed it and the quotient was
  then reported, and gated on, as though it were a relative error.
- **Single precision.** A `--enable-real=sp` build skips the assertion,
  loudly. There the functional is reproducible to only ~1e-7 relative, which
  puts the smallest perturbation that resolves anything above 0.3 — larger
  than any sweep — so the assertion was gating on round-off. The driver
  then exits with code 78, which both lanes report to CTest as a **SKIP**:
  a check that made no check must not read as a pass.

## Which direction the sweep differentiates along

### `dof` mode, and why the probed index is now always printed

The default sweep perturbs one design degree of freedom — the driver's
`maxloc(abs(sensitivities%x))`. That argmax **moves** whenever the sensitivity
field moves, so two runs of the same case can silently differentiate with
respect to two *different* design variables, which makes every cross-run
comparison unsound. Measured on this suite: at one timestep on one problem the
relative error spanned 0.42% to 23% purely by which dof the lottery selected.

Every run therefore now prints the dof it actually probed, in every mode:

```
 FD probe: mode = dof -- global design index 1276 (rank 1, local index 340)
 FD probe: design value    1.000000, location [   0.410654   0.589346
   0.160654]
 FD probe: reproduce this exact dof in another run by setting
 NEKO_TOP_FD_PROBE_INDEX to the number above.
```

(the last two records are each printed as a single line; they are wrapped
above only to fit the page.)

`NEKO_TOP_FD_PROBE_INDEX=<n>` pins the probe to that exact dof instead of the
argmax, which is what makes two runs comparable. The index is a 1-based index
into the globally concatenated design vector (the owning rank's offset plus its
local index), and is reproducible for a given mesh **and rank count** — the
scope in which two runs compare anyway. Run the same number on a different
number of ranks and it names a different dof; check the coordinates printed
beside it rather than assuming. It is ignored (with a warning) in
`directional` mode, which probes no single dof.

### `directional` mode: the Taylor test

`NEKO_TOP_FD_MODE=directional` (or `"fd_test_mode": "directional"`) perturbs
the **whole** design along the normalised sensitivity direction `s = g/||g||`
and compares the finite difference against the projected analytic value
`<g, s>`. That validates the entire gradient field in one sweep instead of one
lottery-selected component of it, and it raises the finite-difference signal by
roughly `||g||/|g_i|`, which buys back round-off headroom the single-dof probe
does not have. The single-dof probe is the one-hot special case of the same
code path (`fd_run_sweep`/`evaluate_perturbed` take a direction vector), so the
two cannot drift apart.

The step is clamped so that `x ± eps*s` stays in `[0,1]` at every design
coordinate, and a clamp is reported (`FD sweep: requested step … clamped to
…`) rather than silently substituted; a clamp below 1/1000 of the requested
perturbation is an error, since that sweep point is no longer the one that was
asked for. A design sitting **on** a bound has no room at all, so
`directional` mode needs a case whose design is initialised strictly inside
its bounds; the 0/1 indicator designs every case here currently uses will
error out instead.

### The inner product, and why it is not weighted by B again

**The design-space inner product used is the plain Euclidean one on the
assembled nodal design coefficients, for both the normalisation and the
projection.** This is the crux of the test: an inconsistency here silently
invalidates it.

The reasoning: both drivers call
`design%convert_to_directional_derivative(sensitivities)` before handing the
field to this harness, and that routine post-multiplies the adjoint's L2 Riesz
representative by the mass matrix (`col2(vec, coef%B)`, see
`sources/design/design_types/design_brinkman.f90`, added in commit `f870a46`
"Directional derivative vs gradient (#383)"). So what arrives here is already
`g = B g_L2`: the vector of partial derivatives with respect to the *nodal
coefficients*, not a function on the domain. Those coefficients are exactly
what the finite difference perturbs, so

    <g, s>_2 = s^T B g_L2 = ∫ g_L2 s dΩ

— the Euclidean pairing on coefficients **is** the B-weighted L2 pairing of
the underlying functions, expressed in the variables being perturbed. Applying
B a second time would count the mass matrix twice and is precisely the
inconsistency to avoid. (Note `project_sensitivity`, the *other* scaling added
in `f870a46`, multiplies by the scalar average mass `avg_B` and exists only to
stop MMA producing lumpy designs on non-uniform meshes; it is a deliberate
change of inner product for the optimiser and is not part of this test.)

Two further details make it exact rather than approximately right:

- the direction is built from the **assembled** gradient
  (`gs_h%op(..., GS_OP_ADD)`), so it is single-valued on shared dofs. A
  multi-valued direction would not be a perturbation of any real design
  variable;
- the projection pairs the *unassembled* per-copy sensitivities with that
  single-valued direction. Since
  `Σ_j g_j s_j = Σ_I s_I Σ_{j ∈ copies(I)} g_j`,
  this is the assembled Euclidean inner product without ever dividing by a
  multiplicity — and for a one-hot direction it reduces exactly to the
  assembled derivative at the single dof, which is what `dof` mode has always
  compared against. The norm, by contrast, *does* weight by the inverse
  multiplicity, so each design variable is counted once rather than once per
  element touching it.

The normalisation is itself a free scaling — any non-zero multiple of `g`
would do. What is load-bearing is that `<g,s>` uses exactly the same `s` that
is added to the design, which it does by construction: `s` is built once and
used for both. The run reports `||g||_2` and `<g,s>` side by side, and with a
consistent inner product they are the same number, so an inconsistency shows
up in the log rather than staying silent.

Currently, we have added tests for the following components:

- `volume_constraint_t` (`volume.case`, `volume_filtered.case`)
- `viscous_dissipation_objective_t` (`viscous_dissipation.case`) — isolates
  the always-on `augmented_lagrangian_objective_t` state-coupling term, since
  this objective's own `update_sensitivity` is empty.
- `brinkman_dissipation_objective_t` (`brinkman_dissipation.case`) — isolates
  the direct-partial-derivative sensitivity path.

`scalar_mixing_objective_t` is not yet covered here (its only existing case,
`tests/regression/sensitivity/cases/passive_scalar.case`, needed a Neko-core
scalar-scheme fix first — see `known-bugs-backlog.md` #9). The heavier,
realistic (~1000-timestep) versions of these and other cases
(`dissipation`, `dissipation_weights`, unsteady variants) live in
`tests/regression/sensitivity/` instead — that suite is opt-in
(`NEKO_TOP_RUN_SENSITIVITY_REGRESSION=1`) and not part of the
default/PR-blocking test budget, since it's too slow to gate every PR.

## Adding New Tests

Reuse the existing generic driver — you almost never need new Fortran code:

1. Add a new `.case` file exercising the objective/constraint you want to
   cover. Keep `time.end_time`/`time.timestep` short (a handful of steps, not
   a physically converged run — see `volume.case` and
   `viscous_dissipation.case` for the pattern) so the test stays fast; tune
   this and `fd_test_tolerance` empirically by running the case and reading
   the per-perturbation `error` output, not by guessing.
2. Add the case file name to the `test_list` variable in `CMakeLists.txt`:
   ```cmake
   set(test_list
       "volume.case"
       "volume_filtered.case"
       "viscous_dissipation.case"
       "brinkman_dissipation.case"
       "new_case.case"  # Add your new case here
   )
   ```
3. Only write new Fortran (in `problem_tester.f90`/`sensitivity.f90`) if the
   generic driver genuinely can't express what you need — it currently
   handles any single objective or single constraint automatically.
