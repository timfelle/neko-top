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
  matched to the bias their discretisation and unconverged steady state
  leave (determine this empirically per case, don't guess).
- `CMakeLists.txt`: Defines the build process and, via the `test_list`
  variable, registers one CTest per case file.

Currently, we have added tests for the following components:

- `volume_constraint_t` (`volume.case`, `volume_filtered.case`)
- `viscous_dissipation_objective_t` (`viscous_dissipation.case`) — isolates
  the always-on `augmented_lagrangian_objective_t` state-coupling term, since
  this objective's own `update_sensitivity` is empty.
- `brinkman_dissipation_objective_t` (`brinkman_dissipation.case`) — isolates
  the direct-partial-derivative sensitivity path.
- `viscous_dissipation_variable_dt.case` — the same objective with
  `case.time.variable_timestep`, a regression gate for backlog #55. It fails
  if the driver ignores the `case.time` settings (the run then marches at a
  placeholder `dt = 1.0`), or if one run's last `dt` leaks into the next
  run's time-step history. Its time steps do not depend on the design, by
  construction: the CFL stays far below `target_cfl`, so every run ramps
  from `timestep` by the controller's largest factor, 1.2 per step, until
  `max_timestep` caps it. The finite differences therefore compare runs with
  identical steps. The flow starts from the inflow velocity rather than from
  rest, because Neko's controller divides by the CFL of the first step, and
  a zero CFL stops a Debug build on a floating-point trap (backlog #103).
  The finite-difference estimate converges at first order to a limit about
  0.6% above the adjoint sensitivity. That limit is a bias, not a floor:
  the forward run has not reached a steady state at `end_time`, while the
  steady adjoint assumes it has. Starting from rest doubles it to 1.3%; the
  fixed-timestep `viscous_dissipation.case` has 0.6% too.
- `viscous_dissipation_variable_dt_weighted.case` — the same case with the
  objective weighted by 1e4. The adjoint equations are linear, so its
  relative finite-difference error must equal that of the unweighted case.
  It fails if the adjoint sizes its time steps by the adjoint velocity, whose
  amplitude follows the weight, instead of by the primal velocity that
  convects it.
- `adjoint_joblimit_variable_dt.case`, run by its own driver
  `adjoint_joblimit_tester.f90`. A steady adjoint takes as many steps as the
  forward run did, with time steps of its own, so its clock can stop short
  of `end_time`. It must still count as complete and write no job-limit
  checkpoint. The forward run starts almost at rest, so its first step is
  the full `timestep`; its later steps follow the CFL of the developing
  flow. Every adjoint step follows the CFL of the developed flow, which is
  higher, so the adjoint steps are shorter. `max_timestep` caps every step
  at 8e-3, which keeps the explicit Brinkman term stable: BDF3/EXT3 needs
  `chi * dt` below 20/21, and `chi` reaches 100 here. The driver also
  checks that the adjoint's clock did stop short, so that the check cannot
  pass vacuously.
- The guard against a variable timestep without the `timestep` that caps its
  first step (`variable_timestep_without_timestep.case`). It is not in
  `test_list`: it passes only if the run stops with its error.
- The four rejections of a variable timestep in an unsteady problem. None is
  in `test_list`, so a change that drops one still passes the suite; each
  passes only if the run stops with its error. They are checked by hand:
  copy the case into this directory of the build tree, where the mesh is,
  and run the driver there, `./problem_tester_sensitivity_bin <case>`, on:
  - `unsteady_variable_timestep_without_timestep.case`, which has neither
    `timestep` nor `max_timestep`. It stops with `case.time.variable_timestep
    needs case.time.timestep or case.time.max_timestep`.
  - A copy of `unsteady_variable_timestep.case` with `exact_output_time` set
    to `false`. It stops with `case.time.variable_timestep needs
    case.time.exact_output_time`.
  - A copy with a `projection_space_size` above 0 in
    `case.fluid.velocity_solver` or `pressure_solver`, in
    `case.adjoint_fluid.velocity_solver` or `pressure_solver`, or in the
    `solver` of a scalar or an adjoint scalar. It stops with
    `case.time.variable_timestep does not support projection_space_size`.
    With `case.adjoint_fluid.velocity_solver.projection_space_size` at 4, a
    run that does not stop gives an error of `-1.54e-2` at the smallest
    perturbation, against `+2.17e-3` without it, both with the adjoint that
    replays the steps in reverse.
  - `unsteady_variable_timestep.case` in an MPMD run, two copies of the
    driver launched together with `NEKO_COMM_ID` set to 0 and 1, e.g.
    `mpirun -np 1 -x NEKO_COMM_ID=0 <driver> <case> : -np 1 -x
    NEKO_COMM_ID=1 <driver> <case>`. It stops with `is not supported in an
    MPMD run`.
- `brinkman_dissipation_objective_t`, unsteady
  (`unsteady_brinkman_dissipation.case`) — 20 time steps at polynomial order
  3, with a PDE filter and the objective's default over-integration. It checks
  that the reported value is integrated with the quadrature its adjoint
  forcing and sensitivity differentiate. With the value on the GLL points and
  its derivatives on the GL points, the error at the smallest perturbation was
  `+1.775e-2`; with one quadrature it is `+1.05e-5`, which is first-order
  truncation (`+5.25e-5` at `5e-4`). The tolerance of `1e-4` lies between the
  two.
- `brinkman_dissipation_objective_t`, unsteady and masked
  (`unsteady_brinkman_dissipation_masked.case`) — the same case with the
  objective masked to the design domain. The PDE filter's transpose carries
  any sensitivity reported outside the mask onto the design variables next to
  the domain boundary, and the probed variable lies `0.015` inside it. With
  the sensitivity unmasked the error was `-6.24e-2`; masked it is `+1.13e-5`.
  The driver probes the variable with the largest |sensitivity|, today number
  1259 at `y = 0.2155`: `0.0155` inside the mask's `y = 0.2` boundary, so
  within the filter radius (`0.05`) of the region outside it. The test guards
  the mask only while its probe stays that close to the boundary. Whenever the
  case or the driver's probe selection changes, confirm again that the test
  fails with the mask removed from `update_sensitivity`.
- `brinkman_dissipation_objective_t`, unsteady from a moving start
  (`unsteady_brinkman_dissipation_moving_start.case`) — the unsteady case with
  the flow starting at the inflow velocity instead of at rest, 10 time steps
  and 4 states in RAM, so that the adjoint also recomputes states from disk.
  The first forward step applies the Brinkman term to the initial velocity,
  which gives the sensitivity a sample at the initial state, paired with the
  adjoint state the adjoint run ends at. Without that sample the error at the
  smallest perturbation was `-4.34e-2`; with it, it is `-1.72e-5`, which is
  first-order truncation (`-1.71e-4` at `1e-3`). The tolerance of `1e-4` lies
  between the two. From rest the sample is zero, so no other case sees it.
- `brinkman_dissipation_objective_t`, unsteady with a variable timestep
  (`unsteady_variable_timestep.case`) — time order 3, starting at rest, with
  `exact_output_time`. The step ramps from `timestep` towards `max_timestep`
  and is fitted to the end time on the way, so the frozen grid holds 15 steps
  of 10 different sizes, from `1e-3` to `3.69e-3`. The driver checks only
  that the grid holds at least two different steps and that its first step
  is not Neko's placeholder of 1. The adjoint is the exact transpose of the
  time scheme of the forward run: the error at the smallest perturbation is
  `+3.02e-6`, which is first-order truncation (`+3.02e-5` at `1e-3`), and
  the tolerance is `1e-4`. The adjoint that replays the steps in reverse
  with the coefficients of its own history, `time_transpose` set to
  `"reverse"`, gives `+2.17e-3`, and the exact transpose with the implicit
  solve of that history, its `b_1` instead of the forward step's own,
  `-6.88e-2`. With the reverse replay, an adjoint that takes the mean step
  instead of replaying the grid gave `+7.39e-2`, and one that weights the
  coupling term by `dt_(i+1)` at this time order, as at time order 1,
  `-1.46e-2`. The same case at a fixed step of `2.5e-3` gave `+3.5e-6`
  with the reverse replay, which is exact at a fixed step.
- `brinkman_dissipation_objective_t`, unsteady with a variable timestep that
  the CFL number limits (`unsteady_variable_timestep_cfl_limited.case`) — the
  same case starting at the inflow velocity, with a `target_cfl` of `0.02` and
  an end time of `0.02`. The CFL number limits the first step below
  `timestep`, and the landing on the end time fits it to `6.90e-4`; the
  frozen grid holds 39 steps of 3 sizes, from `6.90e-4` down to `4.56e-4`.
  Every run starts its time-step history from equal steps of the step its
  first step takes, which the forward run checks. The error at the smallest
  perturbation is `+9.87e-6`, which is first-order truncation (`+9.87e-5` at
  `1e-3`), and the tolerance is `1e-4`. The reverse replay gives
  `-5.14e-4`, and the exact transpose with the `b_1` of the reverse history
  `+2.24e-2`. With the reverse replay, a history started from `timestep`
  instead gave `-2.55e-3`.
- `brinkman_dissipation_rejection` — checks the invalid mixed-dealias
  configuration directly through Neko's pFUnit error-redirection fixture. A
  mixed setting has no value its sensitivity is the gradient of, so the
  objective must raise `neko_error`; pFUnit consumes that expected exception
  as a successful test.

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
  For a configuration that a constructor must reject, add a focused pFUnit
  test using Neko's `error_redirection.f90` fixture and
  `@assertExceptionRaised()`.
3. Only write new Fortran (in `problem_tester.f90`/`sensitivity.f90`) if the
   generic driver genuinely can't express what you need — it currently
   handles any single objective or single constraint automatically.
