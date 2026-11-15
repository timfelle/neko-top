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

Unsteady problems need a fixed timestep. The adjoint restores the forward
states one step at a time and assumes every step had the same `dt`, so a case
that sets `case.time.variable_timestep` together with `"unsteady": true` stops
with an error.

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

### Limitations of the recompute

The recompute restarts the forward simulation from a disc checkpoint and
takes its time steps again. A disc checkpoint is a Neko checkpoint, which
holds the fluid, the scalars and the time state. The recomputed time steps
run what prepares a time step, the `preprocess` of the user and of the
simulation components, and the fluid and the scalars. They do not run the
`compute` of the simulation components and of the user, nor the output,
which ran on these time steps in the forward simulation, so the recompute
writes no output and adds nothing to statistics. A `steady` component
freezes the fluid in the recompute at the time step it did so in the forward
simulation.

The recompute does not guarantee the forward simulation in the following:

- The state of an LES model. The restart computes the eddy viscosity anew
  from the restarted velocity, the running averages of the dynamic
  Smagorinsky model are not checkpointed, and the schedule on which the model
  updates the eddy viscosity is anchored anew at every restart. A scalar
  whose diffusivity depends on the eddy viscosity, through
  `alphat.nut_dependency`, is therefore rejected: an unsteady problem with
  checkpointing stops with an error on it. The check is conservative, it
  rejects such a scalar with any LES model. An eddy viscosity in the fluid
  needs `full_stress_formulation`, which the adjoint does not support.
- The schedules in time steps of the simulation components. They are started
  again from the time step of the checkpoint, so a schedule in time steps
  with a value of 1, or with one that divides the time step of every
  checkpoint, runs at the time steps it ran at in the forward simulation,
  and any other runs at other time steps.
- The `extra_fields` of the checkpoint, which are kept in memory only. At the
  time steps restored from a disc checkpoint, they hold what the restart
  leaves in them.
- The projection spaces of the Krylov solvers, which hold solutions of the
  time steps solved last. With a `projection_space_size` above zero, the
  recomputed states match those of the forward simulation only to within the
  tolerances of the solvers.

Lagrangian particle tracking, the `lagrangian_particles` component, is
passive: the particles do not act on the flow, so they do not change the
objectives or their sensitivities. Their state and their output are not part
of the adjoint, and they are not reset between design iterations. The
component advances the particles in its `preprocess`, so the recompute
advances them as well, while only the forward simulation writes their
output. The state of the particles after an adjoint simulation is therefore
not meaningful.

The time-step controllers of the forward, the adjoint and the recomputed
simulations of an unsteady problem are initialised from the root of the case
file rather than from `case.time`, so they never vary the time step. This
makes no difference as long as unsteady problems need a fixed time step, but
has to change if a variable time step is to be supported.
