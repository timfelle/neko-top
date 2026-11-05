# Unsteady simulations {#unsteady_simulation}

Unsteady simulations are simulations which cannot be simply progressed to a
steady state solution which will be used to estimate the entire adjoint
solution. In the case of an unsteady problem, the adjoint simulation requires
the forward state to be restored at each timestep in reverse order. Neko-TOP
handles this through the `state_recovery_t` abstraction. A state recovery
implementation is responsible for storing enough forward information and then
restoring or reconstructing the forward state when the adjoint run asks for it.

At the user level, unsteady problems declare a `state_recovery` block at the
top level of the case file:

```json
"unsteady": true,
"state_recovery": {
  "type": "checkpoint"
}
```

The available implementation is `checkpoint`, which restarts the forward
problem from stored checkpoints.

## Variable time step

An unsteady problem may vary its time step, `case.time.variable_timestep`.
The state recovery records the time grid of the forward run, the time and the
time step of every state and the coefficients of the time scheme of the step
that produced it, and the adjoint replays it in reverse: it steps back over
each forward step with that step's time step, and every sample of the
sensitivity takes its time and its weight from the record. A state that is
recomputed from a checkpoint on disc is stepped with the recorded time steps
too.
The adjoint forcing of an objective with a time window is switched on at the
recorded time of every forward state it consumes, the same test the value
used, and scaled by the length of the run over the length of the window, both
summed from the recorded steps.

With `"unsteady": true`, a variable time step needs

- `case.time.exact_output_time` set to `true`, so that every run ends exactly
  at the end time, and
- `case.time.timestep` or `case.time.max_timestep`, which caps the first step
  of every run.

A case without them stops with an error. Krylov projection spaces,
`projection_space_size`, are not supported with a variable time step in an
unsteady problem, neither for the fluid and the scalars nor for their
adjoints, which take the primal setting unless `case.adjoint_fluid` or the
adjoint scalar sets its own: they are cleared when the time-step controller
changes the step, which a replayed step, and every adjoint step, does not do.
Nor is an MPMD run, in which the controller agrees every step with the
coupled simulations.

For an objective without a time window, the adjoint is the exact discrete
transpose of the time scheme of the forward run, at a fixed and at a variable
time step alike: it combines the coefficients the forward steps used, as the
state recovery recorded them; see [the adjoint under a variable time
step](@ref adjoint-variable-time-step). The time transpose is selected in
`case.adjoint_fluid`:

| Parameter        | Type     | Default   | Description |
| ---------------- | -------- | --------- | ----------- |
| `time_transpose` | `string` | `"exact"` | How the unsteady adjoint transposes the time scheme of the forward run. `"exact"` is its exact discrete transpose. `"reverse"` replays the forward steps in reverse with the coefficients of the adjoint's own history of steps, which is exact at a fixed time step only; under a variable time step it is consistent with the forward run, but the difference grows with how much the time step changes from one step to the next. |

The exact transpose needs a zero `case.adjoint_fluid.initial_condition` and an
adjoint fluid that is not frozen, and stops with an error otherwise. The
adjoint scalars have no exact transpose yet: with them the adjoint takes the
reverse one, and says so in the log.

The source terms of the adjoint fluid in the case file,
`case.adjoint_fluid.source_term`, including those that call the user file, are
always extrapolated in time. The exact transpose therefore treats them as
explicit operators on the adjoint velocity, combined over the next levels with
the EXT column like the Brinkman term. That is right for a term that acts on
the adjoint velocity, such as a Brinkman term. It is wrong for a forcing, a term
that does not depend on the adjoint velocity, such as the derivative of an
objective: the exact transpose adds the forcing of each sample at its own
level, while an extrapolated forcing is combined from the next levels instead.
Over the last levels of the run, where the column is truncated, that
combination is not even consistent, and the last level gets no forcing at all.
An objective whose adjoint forcing is such a source term needs `"reverse"`.

The sensitivity is the gradient on the time grid of the forward run: how the
grid itself depends on the design is not part of it. With `exact_output_time`
the time steps depend on the design only through the number of steps fitted
to the time left, so wherever that number does not change, the gradient on the
recorded grid is the gradient of the objective. A finite-difference check of
the sensitivity therefore freezes the time grid of its baseline run with
`freeze_time_grid` of the state recovery, and every perturbed run replays it.
The sensitivity test drivers do so for every unsteady case.

## Checkpoint based state recovery

A straight forward approach is to simply store the entire forward state at each
timestep, and then restore it when needed by the adjoint simulation. However,
storing all states in memory is impossible for large simulations, while it is
prohibitively slow to read and write the state to disc for every timestep.
Therefore we support a checkpoint based system.

During the forward simulation, we determine if the state should be placed in
memory or written to disc. The disc files are restart capable checkpoints
directly from Neko and are used to restart the forward simulation. The memory
checkpoints are a RAM based copy of the required state variables, and not a
complete memory of the forward state.

The current checkpoint implementation supports the following algorithms:

- Linear: Store a regular interval of restart capable checkpoints to disc.

By default, Neko-TOP stores pressure, velocity, and scalar fields in the
checkpoint, but users can specify extra fields to be included in the
checkpoint.

### Parameters

| Parameter          | Type           | Default        | Description                                                               |
| ------------------ | -------------- | -------------- | ------------------------------------------------------------------------- |
| `enabled`          | `bool`         | `false`        | Whether checkpointing is enabled.                                         |
| `algorithm`        | `string`       | `"linear"`     | The checkpointing algorithm to use. Currently only "linear" is supported. |
| `n_memory`         | `int`          | `10`           | The number of checkpoints to store in memory.                             |
| `filename`         | `string`       | `"checkpoint"` | The base name for checkpoint files.                                       |
| `format`           | `string`       | `"chkp"`       | The file format for checkpoint files. Currently "chkp" is supported.      |
| `keep_checkpoints` | `bool`         | `false`        | Whether to keep checkpoint files after the simulation.                    |
| `extra_fields`     | `string array` | `[]`           | A list of extra fields to include in the checkpoint.                      |

### Linear algorithm

The forward simulation will be restarted from the disc checkpoint when the
adjoint simulation requires the state. The forward simulation will be
progressed to the next checkpoint, and the intermediate states will be stored
in memory.
