# Unsteady simulations {#unsteady_simulation}

Unsteady simulations are simulations which cannot be simply progressed to a
steady state solution which will be used to estimate the entire adjoint
solution. In the case of an unsteady problem, the adjoint simulation requires
the forward state to be restored at each timestep in reverse order. Neko-TOP
handles this through the `state_recovery_t` abstraction. A state recovery
implementation is responsible for storing enough forward information and then
restoring or reconstructing the forward state when the adjoint run asks for it.

At the user level, unsteady problems declare a `state_recovery` block at the
top level of the case file (a sibling of `case` and `optimization`):

```json
"unsteady": true,
"state_recovery": {
  "type": "checkpoint"
}
```

`unsteady` is a boolean at the top level of the case file and defaults to
`false`. A case file without it, or with `false`, is a steady problem: its
`state_recovery` block, if present, is never read.

With `"unsteady": true` the `state_recovery` block is required: without it the
set-up stops because the parameter is missing. The block is read by the
state-recovery factory, whose `type` is `"checkpoint"`, or its alias
`"simulation_checkpoint"`; it defaults to `"checkpoint"` when `type` is absent.
The available implementation is `checkpoint`, which restarts the forward
problem from stored checkpoints.

Unsteady problems need a fixed timestep. The adjoint restores the forward
states one step at a time and assumes every step had the same `dt`, so a case
that sets `case.time.variable_timestep` to `true` together with
`"unsteady": true` stops with an error. The same holds for
`case.time.exact_output_time` set to `true`: Neko fits time steps to the output
times only with a variable timestep, so an unsteady problem rejects it as well.
Both keys are read at `case.time.*`; for steady problems the time-step
controller of Neko still applies and both keys are allowed.

\note The block is checked together with the rest of the case file by
`documentation/schemas/state-recovery.schema.json`, see
\ref validating_case_files.

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
| `type`             | `string`       | `"checkpoint"` | The state recovery implementation: `"checkpoint"` or its alias `"simulation_checkpoint"`. |
| `algorithm`        | `string`       | `"linear"`     | The checkpointing algorithm to use. Currently only "linear" is supported; `"LINEAR"` and `"Linear"` are accepted spellings. Anything else aborts. |
| `n_memory`         | `int`          | `10`           | The number of checkpoints to store in memory. Must be at least `1`: `0` is a modulo by zero at the first save.                             |
| `path`             | `string`       | `"checkpoints/"` | The directory the checkpoint files are written to; it is created if it does not exist. |
| `filename`         | `string`       | `"checkpoint"` | The base name for checkpoint files.                                       |
| `format`           | `string`       | `"chkp"`       | The file format for checkpoint files. `"hdf5"` writes an HDF5 `.h5` file; any other string, including `"chkp"`, writes a Neko `.chkp` file.      |
| `keep_checkpoints` | `bool`         | `false`        | Whether to keep checkpoint files after the simulation.                    |
| `extra_fields`     | `string array` | `[]`           | A list of extra fields to include in the checkpoint. Each name must already be registered as a field when the block is read; an unknown name aborts. |

There is no `enabled` key: nothing reads one, and the block is active whenever
`unsteady` is `true`.

### Linear algorithm

The forward simulation will be restarted from the disc checkpoint when the
adjoint simulation requires the state. The forward simulation will be
progressed to the next checkpoint, and the intermediate states will be stored
in memory.
