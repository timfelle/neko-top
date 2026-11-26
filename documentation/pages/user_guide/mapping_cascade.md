# Mapping cascade {#mapping_cascade}

\tableofcontents

In topology optimization problem we consider an abstract material indicator 
which we denote here by \f$\rho(\mathbf{x}) \in [0,1]\f$, 
where \f$\mathbf{x}\f$ are the spatial coordinates. The influence of this design
on a physics simulation is commonly modelled by introducing additional coefficients
into the PDE being solved. In the case of fluid mechanics problems, a common
approach is Brinkman penalization, where an additional forcing term
\f$\mathbf{f} = - \chi \mathbf{u}\f$ is added to the Navier-Stokes equations
(more information can be found in [Brinkman source term](@ref source_brinkman)).

\note For conjugate heat transfer problems one may also map to a thermal
conductivity \f$\kappa\f$, however this is currently not supported in `neko-top`.

A `mapping_t` provides functionality for the mapping 
\f$X_\text{in} \mapsto X_\text{out}\f$ as well as providing functionality to propagate sensitivity
information via the chain rule, i.e.
\f$\frac{\partial \mathcal{F}}{\partial X_\text{out}} \mapsto \frac{\partial \mathcal{F}}{\partial X_\text{in}}\f$. 

The `mapping_cascade_t` enables complex composite mappings to be combined
\f[
    X_1 \mapsto X_2 \mapsto ... \mapsto X_n,
\f]

and enables sensitivity information to be propagated back through the cascade

\f[
    \frac{\partial \mathcal{F}}{\partial X_n} \mapsto ... \mapsto \frac{\partial \mathcal{F}}{\partial X_1}.
\f]

The mapping cascade can be prescribed in the `"design"` section of the `.case`
file under the list `"mapping"`, for example:
```
        "design": {
            "type": "brinkman",
            "mapping" : [
                {
                    "type": "PDE_filter",
                    "r": 0.01
                },
                {
                    "type": "RAMP",
                    "f_max": 1000.0
                }
            ],
```

\attention It is important to note that the order in which the mappings occur in
the case file is the order in which they will be executed. In the above example
this corresponds to applying a filter first, and then a RAMP mapping.

\note Currently the mapping cascade is only applicable to the `"brinkman"` type
design. The list is read from `optimization.design.mapping`, and the
`"brinkman"` design needs it: without the key no cascade is set up and the
first forward mapping of the design dereferences an unset coefficient pointer
(a crash, not a diagnostic). The volume constraint (see
\ref objectives_and_constraints) can additionally carry a `mapping` list of its
own, in the same format.

\attention Every real-valued parameter in the tables below must be written as a
JSON real, for example `1000.0` and not `1000`: the parameter is read as a real
or an array of reals, and a JSON integer stops the set-up with an error.

\note The `type` of a mapping is one of `"linear"`, `"PDE_filter"`, `"RAMP"`,
`"Borrvall_Petersson"`, `"SIMP"` and `"heaviside_mapping"`. The spelling
`"heaviside_projection"` is accepted as an alias of `"heaviside_mapping"`.

## Parameters stepped by continuation {#mapping_continuation}

The following parameters accept an array of reals instead of a single real, and
are then stepped through by the continuation scheduler (see \ref continuation):
`r` of the PDE filter, `f_max` of the linear, RAMP, Borrvall & Petersson and
SIMP mappings, `q` of the RAMP and Borrvall & Petersson mappings, `p` of the
SIMP mapping and `beta` of the Heaviside mapping. The first entry is the
initial value. Each value is held for `<name>_iterations` iterations (for
example `beta_iterations`), which defaults to
`optimization.solver.continuation_iterations`, and the last value is held from
then on. `<name>_iterations` is only read when `<name>` is an array. A number of
iterations of `0` or below disables the schedule and the parameter keeps its
first entry. An empty array is not rejected, and is read out of bounds.
`f_min` is always a single real.

\note The intermediate forward and backward mapping fields written by the
Brinkman design use the `verbose_design`, `verbose_sensitivity`,
`output_precision`, and `output_format` options from `optimization.design`.

# Mappings {#mapping_list}

The following mappings are currently implemented in `Neko-top`.

1. [PDE filter](@ref mapping_PDE_filter)
2. [Linear mapping](@ref mapping_linear)
3. [RAMP mapping](@ref mapping_RAMP)
4. [Borrvall & Petersson mapping](@ref mapping_Borrvall_Petersson)
5. [SIMP mapping](@ref mapping_SIMP)
6. [Heaviside mapping](@ref mapping_heaviside_mapping)

## PDE based filter {#mapping_PDE_filter}
A filter based on the work of   [B. S. Lazarov, O. Sigmund]( https://doi.org/10.1002/nme.3072)
that solves a Helmholtz-type differential equation to provide smoothing. The
equation has the form
\f[
    -\tilde{r}^2 \nabla^2 X_\text{out} + X_\text{out} = X_\text{in},
\f]
subject to Neumann boundary conditions (\f$\nabla X_\text{out} \cdot n = 0\f$).

**Note on the locality of the filter:**<br>
Although the Helmholtz-type PDE filter is formally a global operator (i.e. the
solution is affected in the entire domain), its influence exhibits a rapid
exponential decay.
For a point source in \f$X_\text{in}\f$, the filtered response \f$X_\text{out}\f$
behaves as
\f[
X_\text{out}(\mathbf{x}) \propto \exp\left(-\frac{|\mathbf{x}|}{\tilde{r}}\right),
\f]
where \f$|\mathbf{x}|\f$ denotes the distance from the source. This exponential
decay ensures that the filter acts in a localized manner.
In the implementation, the effective filter radius \f$\tilde{r}\f$ is related to
the user-prescribed parameter \f$r\f$ by
\f[
    \tilde{r} = \frac{r}{2\sqrt{3}},
\f]
such that the parameter \f$r\f$ corresponds to the physical filter radius
commonly used in the topology optimization literature.
This scaling ensures that the influence of the filter is strongly localized, with more than 95\% of its
effect contained within a distance \f$r\f$.
The filter can be selected by prescribing `"type": "PDE_filter"` and has the
following input parameters:


| Name                 | Description                                                       | Admissible values         | Default value  |
| -------------------- | ----------------------------------------------------------------- | ------------------------- | -------------- |
| `r`                  | Physical filter radius. Internally scaled as \f$r/(2\sqrt{3})\f$. | Real, or array of reals (continuation) | *(required)* |
| `tol`                | The desired tolerance used when solving the system.               | Real                      | `1.0e-10`      |
| `max_iter`           | Maximum number of iterations when solving the system.             | Integer                   | `200`          |
| `solver`             | Krylov solver used to solve the system. Any single-field Krylov type of Neko is accepted, for example `cg` or `gmres`; the coupled types (`coupled_cg`, `fused_coupled_cg`, `coupled_bicgstab`) abort. | String | `cg` |
| `preconditioner`     | Preconditioner used to solve the system. Only the Jacobi family is initialised by the filter. | `jacobi`, `ident` | `jacobi`       |
| `strict_convergence` | Stop with an error when a filter solve does not converge.         | `true` or `false`         | `false`        |

\note `hsmg` and `phmg` are not usable as the filter preconditioner. They are
allocated by Neko's preconditioner factory but the filter initialises only the
Jacobi family (`filter_precon_factory`, `PDE_filter_mapping.f90`), so they would
be used uninitialised. Use `jacobi` or `ident`.

Since the Helmholtz operator is Symmetric Positive Definite (SPD), `CG` is recommended.
The convergence rate is highly dependent on the filter radius; larger radii typically improve the condition number.

The tolerance `tol` applies to the absolute residual, so the number of
iterations needed to reach it depends on the mesh, the polynomial order, the
filter radius and the magnitude of the field being filtered.
A filter solve that does not reach it within
`max_iter` iterations is reported with a warning in the log, and the
unconverged result is used. With `"strict_convergence": true` the run stops
with an error instead. A solve can then never be reported as converged, and the
run therefore stops at the first filter application, with the `cheby` solver,
with `max_iter` below 2, or with a `tol` of `0` or below. The filter does not follow
`case.fluid.strict_convergence`; set the key on each filter that needs it.

## Linear mapping {#mapping_linear}
A linear mapping of the form
\f[
    X_\text{out} = f_\text{min} + (f_\text{max} - f_\text{min}) X_\text{in}.
\f]

The mapping can be selected by prescribing `"type": "linear"` and has the
following input parameters:


| Name    | Description                               | Admissible values | Default value |
| ------- | ----------------------------------------- | ----------------- | ------------- |
| `f_max` | \f$f_\text{max}\f$ in the above equation. | Real, or array of reals (continuation) | *(required)* |
| `f_min` | \f$f_\text{min}\f$ in the above equation. | Real              | `0.0`         |

## RAMP mapping {#mapping_RAMP}
A mapping based on the [RAMP](10.1007/s001580100129) taking the form
\f[
    X_\text{out} = f_\text{min} + (f_\text{max} - f_\text{min})  \frac{X_\text{in}}{1 +q(1 - X_\text{in})},
\f]
where \f$q\f$ is a penalty parameter.

This is increasing, with \f$X_\text{out}(0) = f_\text{min}\f$ (fluid) and
\f$X_\text{out}(1) = f_\text{max}\f$ (solid), for the convention
x=0: fluid, x=1: solid. For the converse convention (x=0: solid,
x=1: fluid) use the [Borrvall & Petersson mapping](@ref mapping_Borrvall_Petersson)
instead.

The mapping can be selected by prescribing `"type": "RAMP"` and has the
following input parameters:


| Name    | Description                               | Admissible values | Default value |
| ------- | ----------------------------------------- | ----------------- | ------------- |
| `f_max` | \f$f_\text{max}\f$ in the above equation. | Real, or array of reals (continuation) | *(required)* |
| `f_min` | \f$f_\text{min}\f$ in the above equation. | Real              | `0.0`         |
| `q`     | \f$q\f$ in the above equation.            | Real, or array of reals (continuation) | `1.0`         |

## Borrvall & Petersson mapping {#mapping_Borrvall_Petersson}
A mapping based on the material interpolation of
[Borrvall & Petersson](https://doi.org/10.1002/fld.426) taking the form
\f[
    X_\text{out} = f_\text{max} + (f_\text{min} - f_\text{max}) \frac{X_\text{in}(q + 1)}{X_\text{in} + q},
\f]
where \f$q\f$ is a penalty parameter.

This is decreasing, with \f$X_\text{out}(0) = f_\text{max}\f$ (solid) and
\f$X_\text{out}(1) = f_\text{min}\f$ (fluid), steepest near
\f$X_\text{in} \to 0\f$, for the convention x=0: solid, x=1: fluid. It is the
converse of the ordinary RAMP mapping and uses the same shape function.

The mapping can be selected by prescribing `"type": "Borrvall_Petersson"` and
has the following input parameters:


| Name    | Description                               | Admissible values | Default value |
| ------- | ----------------------------------------- | ----------------- | ------------- |
| `f_max` | \f$f_\text{max}\f$ in the above equation. | Real, or array of reals (continuation) | *(required)* |
| `f_min` | \f$f_\text{min}\f$ in the above equation. | Real              | `0.0`         |
| `q`     | \f$q\f$ in the above equation.            | Real, or array of reals (continuation) | `1.0`         |

## SIMP mapping {#mapping_SIMP}
A mapping based on the [SIMP](https://doi.org/10.1007/BF01650949) taking the following form

\f[
    X_\text{out} = f_\text{min} + (f_\text{max} - f_\text{min})  X_\text{in}^p,
\f]

where \f$p\f$ is a penalty parameter.

The mapping can be selected by prescribing `"type": "SIMP"` and has the
following input parameters:


| Name    | Description                               | Admissible values | Default value |
| ------- | ----------------------------------------- | ----------------- | ------------- |
| `f_max` | \f$f_\text{max}\f$ in the above equation. | Real, or array of reals (continuation) | *(required)* |
| `f_min` | \f$f_\text{min}\f$ in the above equation. | Real              | `0.0`         |
| `p`     | \f$p\f$ in the above equation.            | Real, or array of reals (continuation) | `1.0`         |

## Heaviside mapping {#mapping_heaviside_mapping}
A smooth Heaviside mapping taking the form,
\f[
    X_\text{out} =
    \frac{\tanh(\beta \eta) + \tanh(\beta (X_\text{in} - \eta))}
         {\tanh(\beta \eta) + \tanh(\beta (1-\eta))},
\f]
where \f$\beta>0\f$ controls the steepness and \f$\eta\in[0,1]\f$ describes
the threshold.

The mapping can be selected by prescribing `"type": "heaviside_mapping"` and
has the following input parameters:

| Name   | Description                                 | Admissible values | Default value |
| ------ | ------------------------------------------- | ----------------- | ------------- |
| `beta` | Projection sharpness parameter \f$\beta\f$. | Real, `> 0`, or array of reals (continuation) | *(required)* |
| `eta`  | Projection threshold parameter \f$\eta\f$.  | Real in `[0,1]`   | `0.5`         |

`beta` has no default: a mapping without it stops the set-up with the error
"beta not found and no default provided". The initial value (the first entry of
an array) is checked to be positive, and `eta` to lie in `[0,1]`, when the
mapping is created. Later entries of a `beta` array are not checked at that
point; a later entry of `0.0` stops the run when it is reached, with "invalid
denominator in heaviside mapping".
