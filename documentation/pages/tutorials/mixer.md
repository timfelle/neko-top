# Static Mixer {#mixer}

\tableofcontents

\attention
This tutorial is currently under construction. The figures do not reflect the
parameters documented, as these parameters will be finalized soon.

This tutorial aims to replicate the passive mixer problem by 
[C. S. Andreasen et al. 2009](https://doi.org/10.1002/fld.1964).

The goal of this optimization problem is to design a structure capable of
mixing fluids in a static manor, that is to say, without the use of moving
parts.

We begin by considering  a square duct seen in the figure below.

![Indication of the convergence history of the static mixer](mixer_animation.gif)

Fluid enters the domain upstream and is ejected downstream, with all other
boundary being considered solid walls. 
In addition, we consider a scalar field, representative of the two species one desires to
have mixed (denoted in red and blue in the above figure). 
The species enters the mixer upstream, originally separated into two distinct species. 
The goal of
the optimization problem is to design the interior structure such that the
two species are as homogeneous as possible in the downstream location 
(denoted in green in the above figure). The
system is assumed to be low Reynolds number, implying a steady state solution
can be found, and high Peclet number, implying the mixing must be performed
by advective transport, not diffusion.

In this tutorial you will learn how to
- [Formally define this problem in the context of a topology optimization problem.](@ref mixer_optimization_problem)
- [Mesh the domain.](@ref mixer_meshing)
- [Set up a fluid, scalar and their respective adjoint simulations.](@ref mixer_case_file)
- [Define different domains](@ref mixer_domains)
- [Define the objective functions and constraints being solved.](@ref mixer_objectives)
- [Define a mapping cascade.](@ref mixer_mapping)
- [Define parameters for the optimization algorithm.](@ref mixer_MMA)
- [Prepare a driver to solve the optimization problem.](@ref mixer_driver)
- [Solve the optimization problem.](@ref mixer_solve)
- [Post process the results.](@ref mixer_post)

## Defining the optimization problem {#mixer_optimization_problem}

![Indication of the computational domain and boundary conditions.](mixer_BCs.png)

We define the duct as the domain \f$\Omega\f$.
The equations being solved in \f$\Omega\f$ are the incompressible Navier-Stokes
equations with an additional passive scalar equation

\f[
    {\frac {\partial \mathbf {u} }{\partial t}}
    + (\mathbf {u} \cdot \nabla)\mathbf {u}
    =
    -\nabla p
    +{\frac {1}{Re}}\nabla ^{2}\mathbf {u}
    +  \mathbf{f}
    - \chi \mathbf{u}, \\
    \nabla \cdot \mathbf {u} = 0, \\
    {\frac {\partial \phi }{\partial t}}
    + (\mathbf {u} \cdot \nabla)\phi
    =
    {\frac {1}{Pe}}\nabla ^{2}\phi
    ,\\
\f]

subject to boundary conditions

\f[
    \frac{1}{Re} \nabla \mathbf{u} \cdot \mathbf{n} -p \mathbf{n} = 0, 
    \text{ on } \Gamma_\text{out}, \\
    \mathbf{u} = \mathbf{u}_\text{in}, \text{ on } \Gamma_\text{in}, \\
    \mathbf{u} = \mathbf{0} \text{ on } \Gamma_\text{wall}, \\
    \nabla \phi \cdot \mathbf{n} = 0, 
    \text{ on } \Gamma_\text{out} \cup \Gamma_\text{wall}, \\
    \phi = \phi_\text{in} \text{ on } \Gamma_\text{in}, \\
\f]

where 
\f$\mathbf {u}(\mathbf{x},t)\f$ denotes the velocity field,
\f$p(\mathbf{x},t)\f$ the pressure field, 
\f$\mathbf{f}\f$ a forcing term, 
\f$\phi(\mathbf{x},t)\f$ the scalar field 
and where \f$Re\f$ and \f$Pe\f$ denotes the Reynolds and Peclet numbers 
respectively. Here, \f$\chi(\mathbf{x})\f$ is a Brinkman penalization term used 
to impose the presence of material within the domain and acts as a simplified 
Immersed Boundary Method (IBM) proposed by 
[Goldstein](https://doi.org/10.1006/jcph.1993.1081). 
That is, \f$\chi\f$ is the spatially dependent Brinkman coefficient, satisfying 

\f[
    \chi =
    \begin{cases} 
    0 & \text{in the fluid region,} \\
    \overline{\chi} & \text{in the solid region,}
    \end{cases}
\f]

where it is assumed that \f$\overline{\chi}\f$ to be a large value, resulting in
a forcing term that models a momentum loss in solid region. We also define two
domains, an optimization domain \f$\Omega_\text{opt} \subset \Omega\f$ in which 
we can place material and
a domain downstream in which we want the scalar species to be mixed
\f$\Omega_\text{mix} \subset \Omega\f$. 

![indication of the optimization domain and objective domain](mixer_domains.png)

We can now define our objective function
to be minimized as

\f[
\mathcal{F} = \frac{1}{|\Omega_\text{mix}|}\int_{\Omega_\text{mix}} 
\frac{1}{2} (\phi - \phi_\text{ref})^2 d\Omega,
\f]

where \f$ \phi_\text{ref} \f$ is a target reference concentration and
\f$ |\Omega_\text{mix}| \f$ denotes the volume of the the domain 
\f$ \Omega_\text{mix} \f$.

\note In the original paper by 
[C. S. Andreasen et al. 2009](https://doi.org/10.1002/fld.1964)
they also constrained this optimization problem with a pressure drop constraint.
This functionality is still in the process of being implemented into `neko-top`.

We now introduce the abstract material indicator 
 \f$\rho(\mathbf{x})\f$, where \f$\rho = 1\f$ denotes the presence of solid 
 material, while \f$\rho=0\f$ denotes the absence of material. The material 
 indicator should ideally take discrete values, however, following a 
 density-based approach, we allow for intermediate values \f$\rho \in [0,1]\f$. 
 This avoids an integer-valued optimization problem and allows 
 gradient-based optimization techniques. A discussion on the mapping
 \f$ \rho \mapsto \chi\f$ is left for @ref mixer_mapping.

 Finally we can cast our optimization problem as

 \f[
\underset{\rho}{\text{min }}  \mathcal{F},\\
\text{subject to:} \\ 
\text{Governing equations}, \\
\text{Boundary conditions.}
\f]

Given this optimization consists of a single objective function and an
exhaustively large number of design variables, it is natural to solve this
problem with adjoint based sensitivity analysis and gradient decent algorithms.

The remained of this tutorial will guide you through the process of solving
such an optimization problem with the topology optimization framework `neko-top`.

## prepare.sh and meshing {#mixer_meshing}

`neko-top` provides users with the capability of executing custom scripts before
an the simulation begins but including a `prepare.sh` script in the example 
folder. This functionality is commonly used to generate
meshes or other preprocessing steps.

An extensive review of the meshing tools available in `neko` and `neko-top` can
be found in @ref meshing.
In this tutorial we will be utilizing the `neko` utility `genmeshbox` in the 
`prepare.sh` script to generate \f$ \Omega \f$ from a cartesian mesh. The
key excerpts in this script read

```bash
# Handle options
Nx=30 && Ny=10 && Nz=10

...

echo "Generating mesh with dimensions: $Nx $Ny $Nz"
genmeshbox 0 6 0 2 0 2 $Nx $Ny $Nz .false. .false. .false.
```

indicating that a box mesh of dimensions \f$[0,6] \times [0,2] \times [0,2] \f$
will be created with \f$30 \times 10 \times 10 \f$ elements.
\note The `.false.` arguments refer to periodic boundary conditions, which in
`neko` are treated as topologically linking these boundary. In the current
problem there are no periodic boundary conditions, hence the `.false.` arguments

An important consideration when using `genmeshbox` is the boundary identifiers,
which become relevant when prescribing boundary conditions. The convention is
to label from 1-6 in the order \f$[x_\text{start}, x_\text{finish}, y_\text{start}, y_\text{finish}, z_\text{start}, z_\text{finish}] \f$ 
or as indicated in the figure below.

![Indication of the face ordering used by `genmeshbox`](mixer_BC_order.png)

## The neko-top .case file {#mixer_case_file}

The `*.case` file allows the user to set up the case.
The high level case structure is described extensively in the `neko`
documentation which can be found 
[here](https://neko.cfd/docs/release/dd/d33/case-file.html). The reader is
strongly encouraged to refer to this documentation in regards to setting up
a forward simulation. In `neko-top`, the high level case structure is extended
to allow for additional adjoint and optimization parameters. The `neko-top`
high level case structure reads

```.json
{
    "version": 1.0,
    "case": {
        "time": {},
        "numerics": {},
        "fluid": {},
        "scalar": {},
        "statistics": {},
        "simulation_components" : [],
        "point_zones" : [],
        "adjoint_fluid": {},
        "adjoint_scalar": {}
    },
    "optimization": {
        "design": {},
        "solver": {},
        "objectives": [],
        "constraints": []
    }
}
```

The optimization domain is part of the design, `optimization.design.domain`,
and not a key of `optimization` itself. The keys of each section are listed in
the user guide, see \ref configuration and \ref adjoint_case_keys, and can be
checked with the validator described in \ref validating_case_files.

### Case
The top level of the case file allows the user to prescribe details on the
numerics and case set up.

```.json
"case": {
    "mesh_file": "box.nmsh",
    "output_checkpoints": false,
    "output_at_end": false,
    "output_boundary": false,
    "time": {
        "end_time": 8.0,
        "timestep": 2e-4
    },
    "numerics": {
        "time_order": 1,
        "polynomial_order": 5,
        "dealias": true
    }
}
```
\note The default name when using `genmeshbox` is `"box.nmsh"`.

It is common practice in `neko-top` to disable the inbuilt `neko` file outputs,
and instead rely on the output samplers provided by `neko-top` to alleviate
excessive outputs when looping between the forward and adjoint runs.

Here we have prescribed: 
- a time-step \f$\Delta t = 2\times 10^{-4} \f$ (`"timestep": 2e-4`, under
  `case.time`)
- a first order time integration scheme (`"time_order": 1`)
- a polynomial order of 5 (`"polynomial_order": 5`)
- the use of overintegration when evaluating the convective terms (`"dealias": true`)

\attention Despite intending to solve the steady Navier-Stokes equation,
currently an `end_time` (under `case.time`) must be prescribed in `neko`. More details regarding
steady state solutions can be found in [Simulation components](@ref simulation_components)  but there are
intentions to include steady state functionality directly within `neko`,
streamlining this process.

Instead, steady states are currently marched towards using the the steady
state simulation component

```.json
"simulation_components": [
    {
        "type": "steady",
        "tol": 1e-7,
        "compute_control": "tsteps",
        "compute_value": 1
    }
]
```

Do not set `"is_user": true` on this component: Neko's factory then skips the
entry before creating anything, so the component would silently never run.

\attention Currently certain features of `neko` are not supported by `neko-top`
due to a lack of adjoint support. Relevant to this section, it should be noted
that variable time-stepping (`case.time.variable_timestep`) and
`case.time.exact_output_time` are rejected for unsteady problems, see
\ref unsteady_simulation.

### Fluid
The fluid section of the case file allows the user to prescribe fluid properties,
solvers, boundary conditions and initial conditions.

```.json
"fluid": {
    "scheme": "pnpn",
    "Re": 2.0,
    "initial_condition": {
        "type": "uniform",
        "value": [ 0.0, 0.0, 0.0 ]
    },
    "velocity_solver": {
        "type": "cg",
        "preconditioner": {
            "type": "jacobi"
        },
        "projection_space_size": 0,
        "absolute_tolerance": 1e-4,
        "max_iterations": 50
    },
    "pressure_solver": {
        "type": "gmres",
        "preconditioner": {
            "type": "hsmg"
        },
        "projection_space_size": 0,
        "absolute_tolerance": 1e-4,
        "max_iterations": 50
    },
    "boundary_conditions": [
        {
            "type": "user_velocity",
            "zone_indices": [1]
        },
        {
            "type": "no_slip",
            "zone_indices": [3, 4, 5, 6]
        },
        {
            "type": "outflow",
            "zone_indices": [2]
        }
    ],
    "output_control": "never"
}
```

The key details which are prescribed are:
- a significantly low Reynolds number (`"Re": 2.0`, a JSON real: the integer
  `2` would abort, since the adjoint reads `Re` as a real)
- an initial \f$ \mathbf{u}|_{t=0} = \mathbf{0}\f$

```.json
"initial_condition": {
    "type": "uniform",
    "value": [ 0.0, 0.0, 0.0 ]
}
```

- no slip boundary conditions on \f$\Gamma_\text{wall}\f$

```.json
"type": "no_slip",
"zone_indices": [3, 4, 5, 6]
```

- an outflow boundary condition on \f$\Gamma_\text{out}\f$

```.json
"type": "outflow",
"zone_indices": [2]
```

- a user defined inflow condition on \f$\Gamma_\text{in}\f$

```.json
"type": "user_velocity",
"zone_indices": [1]
```

\note The velocity and pressure solvers have been set relatively conventionally,
however the interested reader can find more information 
[here](https://neko.cfd/docs/release/dd/d33/case-file.html#autotoc_md39).

\attention
It should be noted that some features in `neko` are not supported in `neko-top`
due to a lack of adjoint support. Relevant to this section, the adjoint reads
the projection settings of the fluid solvers (`projection_space_size` and
`projection_hold_steps`) and this tutorial sets the sizes to `0`, i.e. no
projection. A gradient jump penalty has no adjoint counterpart: nothing rejects
it in the case file, but the sensitivities would not account for it. See
\ref adjoint_case_keys for the adjoint's own keys.

To prescribe user defined conditions, such as the condition on
\f$\Gamma_\text{in}\f$ users can provide additional fortran code. In this
tutorial we will provide an additional `user.f90`. Further details on the `neko`
user interface can be found
[here](https://neko.cfd/docs/release/d6/def/user-file.html).

In this tutorial we wish to prescribe a paraboloid as an inflow condition. The
boundary condition type `"user_velocity"` takes its values from the routine
registered as `user%dirichlet_conditions`, which fills the velocity components
on the boundary zone; the same routine, `user_bc` of the `user.f90` included
below, fills the scalar inflow condition for the scalar's `"user_dirichlet"`
boundary condition. For the fluid the paraboloid is

```fortran
u%x(idx, 1, 1, 1) = -0.5_rp * (y - 1.0_rp)**2 - 0.5_rp * (z - 1.0_rp)**2 + 1.0_rp
v%x(idx, 1, 1, 1) = 0._rp
w%x(idx, 1, 1, 1) = 0._rp
```

### Scalar
Similarly, the scalar section of the case file allows the user to prescribe 
scalar properties, solvers, boundary conditions and initial conditions.

```.json
"scalar": {
    "enabled": true,
    "Pe": 5000.0,
    "solver": {
        "type": "cg",
        "preconditioner": {
            "type": "jacobi"
        },
        "projection_space_size": 0,
        "absolute_tolerance": 1e-6,
        "max_iterations": 50
    },
    "initial_condition": {
        "type": "user"
    },
    "boundary_conditions": [
        {
            "type": "user_dirichlet",
            "zone_indices": [1]
        },
        {
            "type": "neumann",
            "flux": 0.0,
            "zone_indices": [2, 3, 4, 5, 6]
        }
    ]
}
```

The key details which are prescribed are:
- a significantly high Peclet number (`"Pe": 5000.0`)
- a user defined initial condition

```.json
"initial_condition": {
    "type": "user"
}
```

- Neumann conditions on \f$ \Gamma_\text{out} \cup \Gamma_\text{wall} \f$

```.json
"type": "neumann",
"flux": 0.0,
"zone_indices": [2, 3, 4, 5, 6]
```

- a user defined scalar inflow condition on \f$ \Gamma_\text{in}\f$

```.json
"type": "user_dirichlet",
"zone_indices": [1]
```

The user defined scalar inflow condition and scalar initial condition are 
prescribed with `user%dirichlet_conditions` and `user%initial_conditions`. Here we wish
to prescribe a separation between the two scalar species where 
\f$\phi = 0\f$ represents one species and \f$\phi = 1\f$ represents the other.
It is well understood that spectral methods struggle to represent discontinuities,
hence, a sigmoid function is use to provide a sufficient amount of smoothing
across the interface of the two species. The completed `user.f90` should now
read:

\include{} "examples/passive_scalar/user.f90"

### Adjoint fluid and scalar {#mixer_adjoint}
This tutorial will focus on the practical aspects of setting up the adjoint 
simulation however the theory regarding adjoint sensitivity analysis can be 
found in [Adjoint sensitivity analysis](@ref adjoint).

```.json
"adjoint_scalar": {
    "enabled": true,
    "boundary_conditions": [
        {
            "type": "dirichlet",
            "value": 0.0,
            "zone_indices": [1]
        },
        {
            "type": "neumann",
            "flux": 0.0,
            "zone_indices": [2, 3, 4, 5, 6]
        }
    ],
    "initial_condition": {
        "type": "uniform",
        "value": 0.0
    }
},
"adjoint_fluid": {
    "initial_condition": {
        "type": "uniform",
        "value": [0.0, 0.0, 0.0]
    },
    "boundary_conditions": [
        {
            "type": "no_slip",
            "zone_indices": [1, 3, 4, 5, 6]
        },
        {
            "type": "outflow",
            "zone_indices": [2]
        }
    ]
}
```
\note An important feature to be aware of in the `neko-top` adjoint system is that
the adjoint *solvers* adopt the settings of their primal counterparts unless
they are specified: by not specifying a solver type for the adjoint fluid,
`neko-top` will use the solver type of the fluid. This holds for the solver
settings only. The boundary conditions and the initial conditions of the
adjoint are never taken from the primal, so `boundary_conditions` and
`initial_condition` of `adjoint_fluid` and `adjoint_scalar` must be written
(the initial condition is read at every design iteration, with no fallback).
The adjoint pressure solver cannot be configured at all: it always uses
`case.fluid.pressure_solver`. The material properties and source terms of the
adjoint scalar come from `case.scalar` as well. All of this is detailed in
\ref adjoint_case_keys.

The key details which are prescribed are:
- \f$ \phi^\dagger = 0\f$ on \f$ \Gamma_\text{in} \f$

```.json
"type": "dirichlet",
"value": 0.0,
"zone_indices": [1]
```

- \f$ \nabla  \phi^\dagger \cdot \mathbf{n} = 0\f$ on
\f$ \Gamma_\text{out} \cup \Gamma_\text{wall} \f$

```.json
"type": "neumann",
"flux": 0.0,
"zone_indices": [2, 3, 4, 5, 6]
```

- \f$ \mathbf{u}^\dagger = \mathbf{0}\f$ on 
\f$ \Gamma_\text{in} \cup \Gamma_\text{wall} \f$

```.json
"type": "no_slip",
"zone_indices": [1, 3, 4, 5, 6]
```

- an outflow velocity boundary condition on \f$ \Gamma_\text{out} \f$

```.json
"type": "outflow",
"zone_indices": [2]
```

### Domain specification {#mixer_domains}
Domains can be specified through the `neko` functionality `point_zones`, the
reader is referred [here](https://neko.cfd/docs/release/da/dd0/point-zones.html)
for extensive documentation on point zones.

In this tutorial we must define \f$\Omega_\text{opt}\f$ and
\f$\Omega_\text{mix}\f$ which we name `optimization_domain` and
`objective_domain` respectively.

```.json
"point_zones": [
    {
        "name": "optimization_domain",
        "geometry": "box",
        "x_bounds": [
            1.5,
            4.5,
        ],
        "y_bounds": [
            -1.0,
                3.0,
        ],
        "z_bounds": [
            -1.0,
            3.0,
        ]
    },
    {
        "name": "objective_domain",
        "geometry": "box",
        "x_bounds": [
            5.0,
            6.0,
        ],
        "y_bounds": [
            -1.0,
                3.0,
        ],
        "z_bounds": [
            -1.0,
            3.0,
        ]
    }
]
```

Assigning \f$\Omega_\text{opt}\f$ to the optimization domain is performed in
the `design` of the `optimization` section of the case file

```.json
"optimization": {
    "design": {
        "domain": {
            "type": "point_zone",
            "zone_name": "optimization_domain"
        }
    }
}
```

\attention The domain belongs to the design, `optimization.design.domain`. A
`domain` written directly under `optimization` is never read, and the design
then silently covers the full domain.

### Objectives and constraint {#mixer_objectives}
Various objectives and constraints can be provided as lists in the `objectives`
and `constraints` subsection of `optimization`. A full list of the available
objectives and constraints can be found in [Objectives and constraints](@ref objectives_and_constraints).

\attention In the future we wish to also include a tutorial teaching users how
to implement their own custom objectives and constraints, however this is yet
to come.

In this tutorial we wish to assign a `"scalar_mixing"` objective and no
constraints by prescribing
```.json
"objectives": [
    {
        "type": "scalar_mixing",
        "mask_name": "objective_domain",
        "target_concentration": 0.5,
        "weight": 1.0
    }
],
"constraints": [ ]
```

In `neko-top` multiple objectives can be prescribed in a list, resulting in
a multi-objective optimization problem which is handled by a weighted sum of all
prescribed objectives
\f[
\mathcal{F} = \sum_i w_i \mathcal{F}_i,
\f]
where \f$w_i\f$ is a prescribed weight.

Multiple constraints on the other hand are also entered in a list but are
handled through the MMA functionality discussed in [The Method of Moving Asymptotes (MMA)](@ref MMA).

Since the scalar \f$ \phi \in [0,1]\f$, we set a target value for the scalar
concentration to \f$ \phi = 0.5\f$ (`"target_concentration": 0.5`; the key is
not `phi_ref`, which nothing reads) and assert the area of
interest is in \f$ \Omega_{mix}\f$ (`"mask_name": "objective_domain"`).


### Mapping cascade {#mixer_mapping}
We saw in [Defining the optimization problem](@ref mixer_optimization_problem) that the design indicator field
\f$\rho\f$ must be mapped to the Brinkman amplitude \f$\chi\f$. This is achieved
through the use of the mapping cascade accessible in `optimization.design.mapping`.
A detailed description of the mapping cascade and available mappings in `neko-top`
can be found in [Mapping cascade](@ref mapping_cascade).

In this tutorial we use the composite mapping 
\f$\rho \mapsto \tilde{\rho} \mapsto \chi\f$ where
- \f$\rho \mapsto \tilde{\rho} \f$ is a spatial filter
-\f$\tilde{\rho} \mapsto \chi\f$ is a RAMP mapping

which can be prescribed with
```.json
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
    ]
}
```

\note It is important to note that the order in which the mappings occur in
the case file is the order in which they will be executed.

Here we have prescribed a spatial filter with radius 0.01 followed by a RAMP
mapping with maximum Brinkman amplitude 1000.

The mapping cascade takes care of both mapping the design forward and performing
the chain rule backward, i.e. 
\f[
    \frac{\partial F}{\partial \chi}
    \mapsto \frac{\partial F}{\partial \tilde{\rho}}
    \mapsto \frac{\partial F}{\partial \rho}
\f]

### Optimization parameters {#mixer_MMA}
The optimization algorithm used to solve optimization problem is prescribed
in the `"solver"` section of the case file.
Two optimizers are available, `"mma"` and `"steepest_descent"`, see
\ref configuration-solver. Here we use the MMA algorithm, of which more details
can be found in [The Method of Moving Asymptotes (MMA)](@ref MMA).

In this tutorial we we select the MMA algorithm by prescribing

```.json
"solver": {
    "type": "mma",
    "max_iterations": 100,
    "tolerance": 1.0e-3,
    "mma": {
        "scale": 1000.0,
        "xmin": 0.0,
        "xmax": 1.0
    }
}
```

The key parameters selected are
- a maximum of 100 optimization iterations (`"max_iterations": 100`)
- a convergence criterion of 1.0e-3 (`"tolerance": 1.0e-3`)
- a scaling factor of 1000 (`"scale": 1000.0`). It scales the constraint
  values and their sensitivities only, not the objective function
- no constraints: the `constraints` list is empty, and no `mma` key is needed
  for it (there is no `mma.m` key)
- assert that \f$ \rho \in [0,1] \f$

```.json
"xmin": 0.0,
"xmax": 1.0
```

Scaling factors can be adjusted to influence convergence rates of the optimization
problem.

### The final case file
The final case file should now read
\include{} "examples/passive_scalar/passive_scalar.case"

## Neko-top drivers {#mixer_driver}

`neko-top` exists as a library of tools to allow users to perform optimization
in conjunction with the `neko` library. As such, the user has the freedom to
create custom drivers to perform specific tasks. Further details regarding drivers
can be found in [Advanced example setups](@ref examples-advanced).

This functionality can be achieved by providing a `driver.f90` file in the
example folder along with a `CMakeLists.txt`.

For this tutorial, we provide the following `CMakeLists.txt`

\include{} "examples/passive_scalar/CMakeLists.txt"

This script performs the following task:
- allows `neko-top` to use a custom driver (`set(DRIVER_TYPE "custom")`)
- indicates to `neko-top` to use the `driver.f90` driver 
  (`set(DRIVER_SOURCE ${CMAKE_CURRENT_SOURCE_DIR}/driver.f90)`)
- includes the additional `user.f90` file used to prescribe user boundary
  conditions and initial conditions.

```CMake
set(EXTRA_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/user.f90
)
```

`neko-top` distinguishes between four key objects:
- [design](@ref design). The design space over which one optimizes.
- [problem](@ref problem). The definition of the optimization problem being solved.
- [optimizer](@ref optimizer). The optimization algorithm used to solve the optimization
problem.
- [simulation](@ref simulation). Specifically for problems involving fluid mechanics, a
simulation can allow for interfaces with `neko` to perform forward simulation
and additional `neko-top` libraries to perform adjoint sensitivity analysis.

Further details regarding these components can be found in [Code structure ](@ref code-structure).

The basic structure of `driver.f90` is to 

1) declare these objects
```fortran
type(simulation_t) :: simulation
type(problem_t) :: problem
class(design_t), allocatable :: design
class(optimizer_t), allocatable :: optimizer
```

2) initialize these objects along with the user specified boundary and initial
conditions
```fortran
call user_setup(simulation%neko_case%usr)
call simulation%init(parameters)
call design_factory(design, parameters, simulation)
call problem%init(parameters, design, simulation)
call optimizer_factory(optimizer, parameters, problem, design, simulation)
```

3) run the optimization algorithm
```fortran
call optimizer%run(problem, design, simulation)
```

4) clean
```fortran
call optimizer%free()
if (allocated(optimizer)) deallocate(optimizer)
call problem%free()
call design%free()
call simulation%free()
```

### The driver file
The complete driver takes the following form
\include{} "sources/drivers/topopt-user.f90"

## Solving the optimization problem {#mixer_solve}

Once the example has been constructed it can be run by simply executing

```bash
./run.sh passive_scalar
```

from the root `neko-top` directory. Further details on the functionality of the
run script `run.sh` can be found in [Examples](@ref examples).

## Post processing the results {#mixer_post}

The output from a `neko-top` topology optimization problem consists of three
key components

1) an optimization log, saved in the file `optimization_data.csv`.
2) a log of the steady state residual, saved in the file
   `steady_state_data.csv`.
3) a series of field files
    - the steady state forward solution `forward_fields0.nek5000`
    - the steady state adjoint solution `adjoint_fields0.nek5000`
    - the design field `design0.nek5000`
    - the sensitivity `sensitivity0.nek5000`

With the default `fld` output format (`case.fluid.output_format`,
`case.adjoint_fluid.output_format` and `optimization.design.output_format`)
each of these `.nek5000` files is the metadata file of a series of `.fld`
data files, which is what ParaView opens.

The design file holds two fields: the unmapped design field
\f$\rho \in [0,1]\f$ and the mapped design field
\f$\chi \in [0,\chi_{\text{max}}]\f$. With `verbose_design` the
intermediate stages of the mapping cascade are written as well. The
sensitivity \f$\partial \mathcal{F}/\partial \rho\f$ is written to its own
file, and with `verbose_sensitivity` the stages of the backward cascade too,
see \ref design_types.

Included in this example is a folder `passive_scalar/post_processing`
containing:
    - `plot_convergence.py`: A python script to plot the convergence history
    - `post_processing.pvsm`: A Paraview state file to assist you with
    visualizing the optimized designs.


\attention
The remainder of this tutorial is under construction, however it intends to help
you understand how to process these files and provide some scripts to help you 
visualize the results.
