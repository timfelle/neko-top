# Adjoint case-file keys {#adjoint_case_keys}

\tableofcontents

A topology optimization run solves the forward problem described by `case.fluid`
(and `case.scalar`) and its adjoint, which is configured under two further
objects of the `case` section: `case.adjoint_fluid` and `case.adjoint_scalar`.
This page lists their keys, what they fall back to, and the restrictions that
apply to the forward problem while it is being optimised. Both objects are
Neko-TOP additions: Neko itself does not read them.

The keys are also encoded in the case-file schemas, one file per component under
`documentation/schemas/`:

- `adjoint-fluid.schema.json` for `case.adjoint_fluid`,
- `adjoint-scalar.schema.json` for `case.adjoint_scalar`,
- `fluid.schema.json` and `scalar.schema.json` for `case.fluid.freeze_flow` and
  the restrictions on `case.fluid` and `case.scalar`,
- `case-file.schema.json` for the rules that tie these objects together.

Each rule in those files carries a `$comment` that cites the source line it
comes from; this page does not repeat every rule. How to check a case file
against them is described in \ref validating_case_files.

\note The adjoint is not a copy of the primal with every unspecified key
adopted from it. Only the keys marked "falls back" below are read from the
primal object when the adjoint object does not give them. Boundary conditions
and initial conditions are never taken from the primal.

## Which objects are needed {#adjoint_case_keys_needed}

- `case.adjoint_fluid` is needed by every optimization run: its
  `initial_condition` is read, without a fallback, at the start of every design
  iteration.
- A case with a scalar (`case.scalar`) needs an enabled `case.adjoint_scalar`.
  Without it, the first design iteration dereferences an unallocated component
  instead of stopping with a message. The `scalar_mixing` objective also needs
  it, and stops the set-up with "adjoint passive scalar not initialized"
  otherwise.
- With a scalar, write `"enabled": true` in `case.scalar` explicitly. Neko
  defaults the key to `true`, but the optimization drivers read it with a
  default of `false`, so without the key the scalar is built but is not reset to
  its initial condition between design iterations.

The adjoint needs a three-dimensional mesh and the Pn/Pn fluid scheme
(`case.fluid.scheme` equal to `"pnpn"`); other cases stop at set-up.

## `case.adjoint_fluid` {#adjoint_case_keys_fluid}

### Initial condition and boundary conditions

| Key | Type | Default | Notes |
|---|---|---|---|
| `initial_condition` | object | - (required) | Same form as `case.fluid.initial_condition`, with `type` one of `uniform`, `expression`, `blasius`, `point_zone` or `field`. The type `user` aborts. The set-up falls back to `case.fluid.initial_condition` when the key is missing, but the reset before every design iteration does not, so the key must be present. |
| `boundary_conditions` | array | - | Adjoint boundary conditions. Never taken from `case.fluid`. Every labelled zone of the mesh needs exactly one. The types are `velocity_value`, `no_slip`, `outflow`, `normal_outflow`, `outflow+dong`, `normal_outflow+dong`, `user_velocity`, `user_pressure` and `blasius_profile`; `symmetry`, `shear_stress` and `wall_model` abort. `zone_indices` is an array of integers or the name of an integer array constant (see \ref validating_case_files_constants). |

\warning `user_velocity_pointwise` is listed as a known type but its factory
branch is commented out: the zone counts as assigned and silently gets a natural
(do-nothing) condition. Do not use it for the adjoint. `normal_outflow` still
needs the tangential `value` (or `file_name`) of Neko's boundary condition, but
the adjoint discards it: only the zone masks are used.

### Solvers

| Key | Type | Default | Notes |
|---|---|---|---|
| `velocity_solver.type` | string | falls back to `case.fluid.velocity_solver.type` | Krylov solver of the adjoint velocity. |
| `velocity_solver.preconditioner` | object | falls back to `case.fluid.velocity_solver.preconditioner` | An object with a `type`, for example `{"type": "jacobi"}`. A bare string is not accepted. |
| `velocity_solver.absolute_tolerance` | real | falls back to `case.fluid.velocity_solver.absolute_tolerance` | A JSON real, or the name of a real constant. |
| `velocity_solver.max_iterations` | integer | falls back to `case.fluid.velocity_solver.max_iterations`, else `1000` | A JSON integer, or the name of an integer constant. |
| `velocity_solver.monitor` | bool | falls back to `case.fluid.velocity_solver.monitor`, else `false` | |
| `velocity_solver.projection_space_size` | integer | falls back to `case.fluid.velocity_solver.projection_space_size`, else `0` | A non-zero value builds a velocity projection space for the adjoint. |
| `velocity_solver.projection_hold_steps` | integer | falls back to `case.fluid.velocity_solver.projection_hold_steps`, else `5` | |
| `pressure_solver.projection_space_size` | integer | falls back to `case.fluid.pressure_solver.projection_space_size`, else `0` | |
| `pressure_solver.projection_hold_steps` | integer | falls back to `case.fluid.pressure_solver.projection_hold_steps`, else `5` | |

\attention The adjoint pressure solver cannot be configured from
`case.adjoint_fluid`: only the two projection keys above are read there. Its
`type`, `preconditioner`, `absolute_tolerance`, `max_iterations` (default
`800`) and `monitor` are always read from `case.fluid.pressure_solver`. The
tolerance and iteration limit of the adjoint solvers, and the projection keys,
accept a JSON number or the name of a constant of the right kind, as Neko does
for the primal solvers (see \ref validating_case_files_constants).

### Freezing, source terms and output

| Key | Type | Default | Notes |
|---|---|---|---|
| `freeze_flow` | bool | `false` | Freeze the adjoint flow at every design iteration. This is the key that acts in an optimization run, see \ref adjoint_case_keys_freeze. |
| `freeze` | bool | falls back to `case.fluid.freeze`, else `false` | Read at initialisation only. It has no effect in an optimization run, because `freeze_flow` overwrites the flag before every adjoint run. |
| `source_term` | array | - | Source terms of the adjoint momentum equation. Note the singular key, unlike `case.fluid.source_terms`. Neko's state-dependent source-term types (for example Coriolis or Brinkman) read the primal velocity from the registry and would add a forcing built from the primal state; they are not meaningful here. The source terms registered by Neko-TOP cannot be used from a case file. |
| `output_filename` | string | `"adjoint"` | Base name of the adjoint output files. |
| `output_format` | string | `"fld"` | `"fld"`, `"nek5000"` or `"vtkhdf"`. `"adios2"` is not usable: the output layout is never set for the adjoint. |
| `output_mesh_in_all_files` | bool | `false` | |
| `output_subdivide` | bool | `false` | |
| `output_control` | string | `"never"` | `"org"`, `"never"`, `"tsteps"`, `"nsamples"` or `"simulationtime"`. With `"never"` the adjoint field is still written once at the end of every adjoint run when `case.output_at_end` is true (its default). |
| `output_value` | integer or real | - | Read for `"tsteps"` and `"nsamples"` (an integer) and `"simulationtime"` (a real), where it is required. |
| `norm_output_control` | string | `"never"` | When to write the adjoint norm. |
| `norm_output_value` | real | `1.0` | A JSON real or the name of a real constant. Read only when `norm_output_control` is not `"never"`. |
| `norm_output_file` | string | `"adjoint_norm.csv"` | A `.csv` file; read only when `norm_output_control` is not `"never"`. |

\note The forward output of an optimization run (`forward_fields`) takes its
format and subdivision from `case.fluid.output_format` and
`case.fluid.output_subdivide`, and the adjoint output (`adjoint_fields`) from
`case.adjoint_fluid.output_format` and `case.adjoint_fluid.output_subdivide`.
Both are written to `case.output_directory` by joining the strings without a
separator, so write the directory with a trailing slash (for example
`"results/"`): `"results"` puts the files beside the directory, as
`resultsforward_fields0.fld`.

\note The keys `norm_scaling`, `norm_target`, `norm_tolerance` and
`output_file` at the root of the case file are the leftovers of a power
iteration that no code calls any more. They are read, and `output_file` is
opened, so an unknown suffix still stops the run, but they have no other effect.

## `case.adjoint_scalar` {#adjoint_case_keys_scalar}

`case.adjoint_scalar` describes the adjoint of a single scalar. The plural
`case.adjoint_scalars` array is not usable: any non-empty array stops the run
after the whole initialisation, with an error saying that the adjoint scalar
coupling term is not implemented for multiple scalars.

| Key | Type | Default | Notes |
|---|---|---|---|
| `enabled` | bool | `true` | Disable the adjoint scalar. A scalar problem that is optimised needs it enabled. |
| `primal_name` | string | `"s"` | Name of the primal scalar field. It is looked up in the registry by name, so it must equal `case.scalar.name` (Neko's default is `"s"`). |
| `name` | string | `<primal_name>_adj` | Name of the adjoint scalar field. At most 66 characters, no `/`, not blank; it must not be `abx1` or `abx2`. A name that is already a field in the registry makes the adjoint reuse that field silently, so do not choose one that is. |
| `solver.type`, `solver.preconditioner`, `solver.absolute_tolerance`, `solver.max_iterations`, `solver.monitor`, `solver.projection_space_size`, `solver.projection_hold_steps` | as `case.scalar.solver` | each falls back to the same key of `case.scalar.solver`; `max_iterations` else `1000`, `monitor` else `false`, `projection_space_size` else `0`, `projection_hold_steps` else `5` | As for the adjoint velocity solver, `preconditioner` is an object with a `type`, and the numeric keys accept a JSON number or the name of a constant. |
| `advection` | bool | `true` | Never taken from `case.scalar.advection`. |
| `dealias_coupling_term` | bool | `case.numerics.dealias`, else `true` | Over-integrate the adjoint scalar-velocity coupling term, see \ref configuration-adjoint-dealias. |
| `boundary_conditions` | array | - | Never taken from `case.scalar`. Every labelled zone needs exactly one. The types are `dirichlet`, `neumann` and `user`; note that Neko's `user_dirichlet` is not an adjoint type. Write real values: `"value": 0.0` and `"flux": 0.0`, because a JSON integer (`0`) aborts. |
| `initial_condition` | object | - (required) | Same form as for the primal scalar, with `type` `uniform`, `expression`, `point_zone` or `field`. `user` aborts. It is reset at every design iteration. |

The adjoint scalar takes the following from `case.scalar` only, and any copy
under `case.adjoint_scalar` is ignored:

- the material properties `Pe`, or `lambda` and `cp`, each a JSON real or the
  name of a real constant;
- the `source_terms`, which are rebuilt on the adjoint scalar's right-hand side.
  A forcing source term of the primal scalar therefore also forces the adjoint
  equation, which is rarely what is intended.

`case.scalar.variable_material_properties` is rejected while the adjoint scalar
is enabled.

## `case.fluid.freeze_flow` {#adjoint_case_keys_freeze}

`case.fluid.freeze_flow` is a Neko-TOP key of the forward fluid. It is a boolean
with default `false`. At the start of every design iteration the optimization
drivers read it and set the forward fluid's freeze flag to it. Neko's fluid
time step returns immediately while the flag is set, so with `true` the fluid
is not advanced.

Neko's own `case.fluid.freeze` has no effect in an optimization run, since the
reset overwrites it with `freeze_flow`. The adjoint has the same pair:
`case.adjoint_fluid.freeze_flow` (default `false`, with no fallback to the
primal key) acts, and `case.adjoint_fluid.freeze` does not.

\note The `steady` simulation component freezes the fluid by a different route,
see \ref simulation_components.

## Restrictions on the primal while optimising {#adjoint_case_keys_restrictions}

A case file with an `optimization` object must also respect the following
restrictions on the forward problem, because the adjoint reads, transposes or
rejects them. The authoritative list is `documentation/schemas/fluid.schema.json`,
`scalar.schema.json` and `case-file.schema.json`; the main ones are:

- `case.fluid.scheme` must be `"pnpn"`.
- `case.fluid.full_stress_formulation` and `case.fluid.cyclic` must not be
  `true`, `symmetry` velocity boundary conditions are not allowed, and
  `flow_rate_force` aborts when present. `nut_field` is only accepted together
  with `full_stress_formulation`, which the adjoint rejects, so it cannot be
  used either.
- Every numeric key that the adjoint reads (`Re`, `mu`, `rho`, the solver
  tolerances, iteration limits and projection sizes, `Pe`, `lambda`, `cp`, the
  orders of `case.numerics`) accepts a JSON number or the name of a constant,
  see \ref validating_case_files_constants.
- `case.numerics.oifs` must not be `true`.
- `hsmg` as a preconditioner aborts for polynomial order 1.
- A case with `"unsteady": true` needs a `state_recovery` block, must not set
  `case.time.variable_timestep` or `case.time.exact_output_time` to `true`, and
  must not use the `steady` simulation component (see \ref unsteady_simulation).
- `case.numerics.dealias` must be present.
- The `brinkman_dissipation` objective's two `dealias_*` keys must end up equal,
  see \ref objectives_and_constraints.

The schemas deliberately check only structure and combinations that abort. Cases
that run to completion but give a degenerate or wrong result, such as a forcing
source term on the primal scalar (above) or a `scalar.advection` of `false` with
an adjoint scalar, are not rejected. See \ref validating_case_files.
