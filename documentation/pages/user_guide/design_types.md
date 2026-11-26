# Design Types {#design_types}

\tableofcontents

This page documents the JSON options for `optimization.design`.

## Overview {#design_types-overview}

The design section is required and always lives under:

```json
"optimization": {
  "design": {
    "type": "..."
  }
}
```

All design keys, including `domain`, are read relative to this object, that is
from `optimization.design`. A `domain` written elsewhere, for example directly
under `optimization`, is never read: the design then optimises on the full
domain without any message.

The only design type that can be used from the shipped optimization drivers is:

- `"brinkman"`

\warning The factory also has a `"simple"` design, described in
\ref design_types-simple below, but it cannot be selected: both shipped drivers
build the design together with the simulation, and `simple` does not implement
that path, so the set-up stops with "Design type does not support
initialization with simulation".

The keys are checked by `documentation/schemas/design.schema.json`, see
\ref validating_case_files.

## Brinkman Design {#design_types-brinkman}

`"type": "brinkman"` is the main design used with the mapping cascade and
Brinkman source-term coupling.

### JSON keys {#design_types-brinkman-keys}

| Key | Type | Required | Default | Notes |
|---|---|---|---|---|
| `type` | string | Yes | - | Must be `"brinkman"` |
| `name` | string | No | `"Brinkman Design"` | Design name. It identifies the design in the HDF5 design checkpoint and is compared on every load, so a resumed run stops unless it equals the stored name. At most 64 bytes when a design checkpoint is written or read |
| `domain.type` | string | No | `"full"` | `"full"` or `"point_zone"` |
| `domain.zone_name` | string | Cond. | - | Required when `domain.type = "point_zone"` |
| `dealias` | bool | No | `case.numerics.dealias` | Controls dealiasing for Brinkman source terms, see [Adjoint over-integration](@ref configuration-adjoint-dealias). `case.numerics.dealias` must exist: it is read without a fallback, even when `dealias` is given |
| `verbose_design` | bool | No | `false` | Write all forward mapping stages |
| `verbose_sensitivity` | bool | No | `false` | Write all backward sensitivity stages |
| `output_precision` | string | No | `"sp"` | `"sp"` (or `"SP"`, `"single"`) or `"dp"` (or `"DP"`, `"double"`) for design/sensitivity field output |
| `output_format` | string | No | `"fld"` | Field-output format: `"fld"`, `"nek5000"`, `"vtkhdf"`, `"hdf5"`, `"h5"`, or `"adios2"`/`"bp"` (these two need an ADIOS2-enabled Neko). Other file formats abort on the first write |
| `mapping` | array | Yes | - | Mapping cascade definition, see [Mapping cascade](@ref mapping_cascade). Without it the first forward mapping dereferences an unset pointer |
| `initial_distribution` | object | No | omitted | Initial design field setup (details below) |

The `verbose_*`, `output_precision`, and `output_format` options control the
intermediate forward and backward fields written by the mapping cascade.

### `initial_distribution` options {#design_types-brinkman-initial}

If omitted, the design is initialized to zero. The `type` is `"uniform"` or
`"point_zone"`; any other string aborts with "Invalid initial condition". The
`"field"` type described below is listed for completeness but cannot be used.

#### Uniform

```json
"initial_distribution": {
  "type": "uniform",
  "value": 0.0
}
```

| Key | Type | Required | Default |
|---|---|---|---|
| `type` | string | Yes | - |
| `value` | real | Yes | - |

#### Point zone

```json
"initial_distribution": {
  "type": "point_zone",
  "base_value": 0.0,
  "zone_name": "my_zone",
  "zone_value": 1.0
}
```

| Key | Type | Required | Default |
|---|---|---|---|
| `type` | string | Yes | - |
| `base_value` | real | Yes | - |
| `zone_name` | string | Yes | - |
| `zone_value` | real | Yes | - |

#### Field file

\warning The `"field"` type always aborts in the current code. The file name is
changed to the `.fld` suffix in a temporary, not in the name that is then
opened, so the reader still sees the `.fNNNNN` suffix and stops with an unknown
file format error (`set_optimization_ic.f90`). A file name without a `.fNNNNN`
suffix stops earlier, with "Invalid file name for the initial condition". The
case-file schema does not accept this type.

```json
"initial_distribution": {
  "type": "field",
  "file_name": "design0.f00001",
  "interpolate": false,
  "tolerance": 1.0e-6,
  "mesh_file_name": "none"
}
```

| Key | Type | Required | Default | Notes |
|---|---|---|---|---|
| `type` | string | Yes | - | Must be `"field"` |
| `file_name` | string | Yes | - | Field sample file (e.g. `design0.f00001`) |
| `interpolate` | bool | No | `false` | Enable interpolation from another mesh |
| `tolerance` | real | No | `1.0e-6` | Interpolation tolerance |
| `mesh_file_name` | string | No | `"none"` | Optional mesh/source field file for interpolation |

## Simple Design {#design_types-simple}

`"type": "simple"` is a lightweight design representation.

\warning The `simple` design cannot be used from the shipped optimization
drivers, see the warning at the top of this page; this section describes what
its initialiser reads and is kept for reference only.

\note `simple` design currently supports only single-rank execution.
\warning In the current implementation, the `box` sizing keys are read with the
fully-qualified paths `optimization.design.domain.nx/ny/nz/limits` on the
design object itself, so the keys would have to be written at
`optimization.design.optimization.design.domain.nx` and so on, not at the
`domain.*` paths of the table below. A `domain.type` other than `"box"` leaves
the sizes uninitialised.

### JSON keys {#design_types-simple-keys}

| Key | Type | Required | Default | Notes |
|---|---|---|---|---|
| `type` | string | Yes | - | Must be `"simple"` |
| `name` | string | No | `"Simple Design"` | Design name |
| `domain.type` | string | Yes | - | Currently supports `"box"` |
| `domain.nx` | integer | Yes | - | Number of cells in x-direction |
| `domain.ny` | integer | Yes | - | Number of cells in y-direction |
| `domain.nz` | integer | Yes | - | Number of cells in z-direction |
| `domain.limits` | real[6] | Yes | - | `[xmin, xmax, ymin, ymax, zmin, zmax]` |

Example:

```json
"design": {
  "type": "simple",
  "name": "Simple Design",
  "domain": {
    "type": "box",
    "nx": 16,
    "ny": 16,
    "nz": 16,
    "limits": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
  }
}
```
