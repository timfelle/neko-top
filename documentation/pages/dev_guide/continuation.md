# Continuation {#continuation}

This document describes the continuation framework introduced in Neko-TOP to
support gradual variation of optimization parameters during the optimization
loop.

The implementation is based on the module `continuation_scheduler`.


## 1. Overview

The continuation framework allows selected parameters to change over
optimization iterations according to a predefined schedule.

Instead of keeping parameters fixed, users can define:

- A sequence of values for a parameter
- How many iterations each value should persist

This adds the flexibility to guide the optimizer using different values for
various parameters through the optimization loop.


## 2. Core Concept

Each continuation parameter is defined as:

- A **name**
- A **target pointer** (link to actual runtime variable)
- A **list of values**
- A number of iterations per value

At runtime at the end of each optimization iteration:

- The scheduler updates all registered parameters
- Each parameter selects a value based on the current iteration and assigned
  list of values


## 3. Module: `continuation_scheduler`

### 3.1 Main Types

#### continuation_parameter_t

Represents a single continuation-controlled variable.

```fortran
type continuation_parameter_t
   character(len=:), allocatable :: name
   real(rp), pointer :: target => null()
   real(rp), allocatable :: values(:)
   integer :: iterations_per_value = 0
end type
```


### 3.2 Continuation Scheduler
This is a `continuation_scheduler_t`, which allows registration of multiple
continuation parameters and provides an update functionality that updates all
registered parameters.
```fortran
type continuation_scheduler_t
     type(continuation_parameter_t), allocatable :: params(:)
     integer :: default_iterations = 1
   contains
     procedure :: init => init_scheduler
     procedure :: free => free_scheduler
     procedure :: json_get_or_register
     procedure :: register_parameter
     procedure :: update
     procedure :: get_param_name
     procedure :: get_n_params
end type
```

### 3.3 Global Instance
A global instance of the continuation scheduler is provided as
`nekotop_continuation`. It is initialized in the driver after the simulation has
been initialised (see section 4). Any other module that requires a
continuation strategy for one or more of its parameters can register them
through this global object. Note that `nekotop_continuation%update(iter)` is
called at each iteration in the optimization loop.

```fortran
type(continuation_scheduler_t), public, target :: nekotop_continuation
```

## 4. Initialization

```fortran
call nekotop_continuation%init(json)
```
Reads `optimization.solver.continuation_iterations` in the case file, an
integer that defaults to `1`, as the default number of iterations for which each
value of a registered parameter is held. It may be an integer literal or the
name of an integer constant of `case.constants`. Note that an individual number
of iterations can be given in the case file, next to the parameter, as
`{parameters_name}_iterations`, which may likewise be an integer literal or the
name of an integer constant. A number of iterations of `0` or below is not
rejected: `update` then returns early for that parameter, which silently stays
at its first value.

The parameters that are registered from a case file are `r` of the PDE filter,
`f_max` (linear, RAMP, Borrvall & Petersson, SIMP), `q` (RAMP, Borrvall &
Petersson), `p` (SIMP) and `beta` (Heaviside) of the mappings, and the `weight`
of the three objectives. Each is given in the case file as a real, as an array
of reals, or as the name of a real or vector constant of `case.constants`. A
vector constant takes the array path, and so is registered for continuation; a
real constant takes the scalar path. An integer literal is rejected, and so is
any other type.

The constants are looked up when the parameters are read, so
`nekotop_continuation%init` has to be called after the simulation has been
initialised (`sim%init`), which is what registers the constants. The drivers
`sources/drivers/topopt.f90` and `sources/drivers/topopt-user.f90` do so.

`init` also deallocates the array of registered parameters (it starts from an
empty one). User code, that is the startup or `user_setup` of a user file, must
therefore not register continuation parameters before the driver calls
`nekotop_continuation%init`: that call runs after `sim%init`, and it resets the
registered parameters, so anything registered earlier is lost. (In
`sources/drivers/topopt-user.f90`, `user_setup` is called even before
`sim%init`.) Register parameters only after `nekotop_continuation%init` has
run.


## 5. Registering Parameters
```fortran
call nekotop_continuation%register_parameter(name, target, values, iterations)
```
It is possible to use `json_get_or_register` function in the scheduler to read
the parameter from the json file. Note that if the parameter in the json is an
array, or the name of a vector constant, then it will automatically register in
the scheduler as well. If a single real, or the name of a real constant, is
given in the json, then this function will work as a single call of
`json_get_or_lookup_or_default` (or `json_get_or_lookup`, when no default is
given).
```fortran
call nekotop_continuation%json_get_or_register(json, name, target, value, default_value)
```
`target` is the variable that the scheduler updates, `value` returns the
initial value (the scalar, or the first entry of the array), and
`default_value` is optional: without it, a parameter that is absent from the
case file stops the run with "`name` not found and no default provided". With
an array the entries are read with Neko's constants lookup, and the optional
`{name}_iterations` is read as an integer, or the name of an integer constant.
An empty array is not rejected and its first entry is read out of bounds.

A string value is resolved against `case.constants`: a vector constant is
treated as an array, a real constant as a real. Otherwise the run stops with
one of these errors:

- `name: the constant 'X' is an integer. Give its value as a real, e.g. 2.0.`,
  when `X` names an integer constant;
- `name: no real or vector constant 'X' in case.constants.`, when no constant of
  a real or vector type has that name;
- `name can only be a real, a real array or the name of a constant!`, for any
  other type, which includes an integer literal.

## 6. Update Mechanism
```fortran
call nekotop_continuation%update(iter)
```
`idx = (iter - 1) / iterations_per_value + 1` `target = values(idx)`


## 7. JSON Integration
The routine that reads a parameter with a continuation strategy from the case
file is `json_get_or_register`, described in section 5. If the parameter is a
single real, or the name of a real constant, it is a constant parameter in the
optimization loop and is not registered to `nekotop_continuation`. If it is an
array, or the name of a vector constant, it is registered with
these values and `optimization.solver.continuation_iterations` as the default
number of iterations per value, unless the individual number is given for that
particular parameter as `{parameters_name}_iterations`.

The case-file side of this is described, for users, in
\ref mapping_continuation and \ref objectives_weight_continuation.


## 8. Integration Points

### Optimizer loop
```fortran
call nekotop_continuation%update(current_iteration)
```
### Logging
Continuation parameters are appended to log headers and values in the
`optimizer`.


## 9. Free()
The scheduler should be freed at the end of the simulation in the driver.
```fortran
call nekotop_continuation%free()
```

## 10. Example
```json
"beta": [1.0, 5.0, 10.0],
"beta_iterations": 50
```
or, with the values taken from `case.constants`:
```json
"beta": "beta_schedule",
"beta_iterations": "beta_steps"
```
where `beta_schedule` is a vector constant and `beta_steps` an integer
constant.

## 11. Summary

Continuation enables gradual parameter variation during optimization to improve
robustness and convergence.
