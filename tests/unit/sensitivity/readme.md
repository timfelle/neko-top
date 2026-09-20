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
takes two optional keys under `optimization`, alongside `fd_test_tolerance`:

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
driver keeps its own fixed eight-point sweep and is always in `dof` mode.

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
 FD probe: design value    1.000000, location [   0.410654   0.589346   0.160654]
 FD probe: reproduce this exact dof in another run by setting NEKO_TOP_FD_PROBE_INDEX to the number above.
```

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
  single-valued direction. Since `Σ_j g_j s_j = Σ_I s_I Σ_{j ∈ copies(I)} g_j`,
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
(`NEKO_TOP_RUN_SENSITIVITY_REGRESSION=1`) and not part of the default/PR-blocking
test budget, since it's too slow to gate every PR.

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
