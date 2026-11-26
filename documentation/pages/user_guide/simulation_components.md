# Simulation components {#simulation_components}

\tableofcontents

This page documents the `neko-top` simulation component currently provided.

## Steady simulation component

The `steady` simulation component monitors the change between consecutive
forward fields and freezes the forward fluid solve when the change is below a
user-defined tolerance.

\warning The `steady` component belongs to **steady** problems. A case file with
`"unsteady": true` and a `steady` component is invalid: the unsteady adjoint
restores the forward states one step at a time, and freezing the fluid part way
through the run breaks that. The current code does not reject the combination
at set-up, so it is the user's responsibility to avoid it; the case-file schema
does reject it. See \ref unsteady_simulation.

In case files, enable it under `case.simulation_components`:

```json
"simulation_components": [
    {
        "type": "steady",
        "tol": 1e-7,
        "log_frequency": 50,
        "scalar_coupled": false,
        "compute_control": "tsteps",
        "compute_value": 1
    }
]
```

### Convergence measure

For each field, `steady` computes an energy-like norm of the increment
\f$\Delta q = q^n - q^{n-1}\f$,

\f[
\lVert \Delta q \rVert =
\frac{\sqrt{\int_\Omega (\Delta q)^2 \, d\Omega}}{\Delta t\,|\Omega|}.
\f]

The component evaluates this for fluid fields (`u`, `v`, `w`, `p`) and, when
present, one scalar field.

### Stopping behavior

- Fluid convergence is reached when `max(u, v, w, p)` is below `tol`.
- Scalar convergence is checked separately when a scalar is present.
- If `scalar_coupled = true`, both fluid and scalar must satisfy `tol` before
  fluid freezing is applied.
- Once converged, the component sets fluid `freeze = true`.

\note Scalar freezing is not yet applied by this component. The current
implementation only freezes the fluid solver.

### The scalar after the fluid is frozen

Since the scalar is not frozen, it keeps evolving in the frozen flow, and
`steady` keeps computing its increment after freezing the fluid.

With `scalar_coupled = false` the scalar takes no part in the decision to
freeze. The fluid is often frozen long before the scalar converges, more so
the higher `Pe`, so any scalar objective is evaluated on a scalar that may
still be evolving at the end of the run. `steady` therefore issues a warning:

- when it freezes the fluid while the scalar increment is above `tol`, and
- again on its last computation of that run, if the scalar increment is still
  above `tol`. If it has fallen below `tol` by then, a message says so
  instead.

The remedy is `scalar_coupled = true`, with an `end_time` long enough for both
fields to converge. With `scalar_coupled = true` neither warning is issued,
since the fluid is then only frozen once the scalar has converged too.

### Parameters

| Parameter         | Type         | Default   | Description                                                                       |
| ----------------- | ------------ | --------- | --------------------------------------------------------------------------------- |
| `type`            | string       | -         | Must be `"steady"`.                                                               |
| `tol`             | real         | `1e-6`    | Convergence threshold for the field-increment norm.                               |
| `log_frequency`   | integer      | `50`      | A row is written to the convergence file only on steps whose number is a multiple of `log_frequency`, and only on steps on which the component computes (see `compute_control`). Must not be `0` (integer modulo by zero at the first logged step); a negative value is accepted. |
| `scalar_coupled`  | bool         | `false`   | If `true`, require both fluid and scalar convergence before freezing fluid.       |
| `compute_control` | string       | `"tsteps"` | Neko base key of every simulation component: when the component computes. One of Neko's controls, for example `"tsteps"`, `"simulationtime"`, `"nsamples"`, `"fluid_output"` or `"never"`. |
| `compute_value`   | integer/real | `1`       | Neko base key: the interval associated with `compute_control` (an integer for `"tsteps"` and `"nsamples"`, a real for `"simulationtime"`). |

The remaining keys of Neko's simulation-component base (`preprocess_control`,
`preprocess_value`, `output_control`, `output_value`, `order`) are read as well;
see the Neko documentation. Setting `"is_user": true` on a component makes
Neko's factory return before allocating anything, so a `steady` entry with
`is_user` is silently never created.

Rows of the convergence file are thus sparser than `log_frequency` suggests
when `compute_value` does not divide it. Rows are written while the fluid is
not yet converged and, after the fluid has been frozen, while the scalar is
followed.

### Output

The component writes convergence data to `steady_state_data.csv`, opened in
the working directory (it ignores `case.output_directory`), with header:

`iter,time,u,v,w,p,scalar`

where each field column is the normed increment at that logging point.
Rows continue after the fluid is frozen, so the scalar column follows the
scalar to the end of the run. In those rows `u`, `v`, `w` and `p` are exactly
zero, the increment of a frozen field.

### Limitations

- The component currently supports at most one scalar field: with more than
  one scalar the set-up stops with "steady simcomp only works for a single
  scalar".
- For truly time-dependent optimization workflows, prefer the unsteady
  configuration described in \subpage unsteady_simulation.