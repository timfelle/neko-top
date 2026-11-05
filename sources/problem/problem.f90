!> @file problem.f90
!! @copyright
!! Copyright (c) 2025-2026, The Neko-TOP Authors
!! All rights reserved.
!!
!! Redistribution and use in source and binary forms, with or without
!! modification, are permitted provided that the following conditions
!! are met:
!!
!!   * Redistributions of source code must retain the above copyright
!!     notice, this list of conditions and the following disclaimer.
!!
!!   * Redistributions in binary form must reproduce the above
!!     copyright notice, this list of conditions and the following
!!     disclaimer in the documentation and/or other materials provided
!!     with the distribution.
!!
!!   * Neither the name of the authors nor the names of its
!!     contributors may be used to endorse or promote products derived
!!     from this software without specific prior written permission.
!!
!! THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
!! "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
!! LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
!! FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
!! COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
!! INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
!! BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
!! LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
!! CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
!! LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
!! ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
!! POSSIBILITY OF SUCH DAMAGE.

!> Module for handling the optimization problem.
!!
!! This module defines the `problem_t` type which is the main interface for
!! the optimization problem. The problem is defined by a set of objectives and
!! constraints that are evaluated based on the design variables. The problem
!! also handles the output of the problem and the simulation.
module problem
  use num_types, only: rp, dp, xp
  use design, only: design_t
  use base_functional, only: base_functional_t
  use objective, only: objective_t, objective_wrapper_t, objective_factory
  use constraint, only: constraint_t, constraint_wrapper_t, constraint_factory
  use augmented_lagrangian_objective, only: augmented_lagrangian_objective_t
  use vector, only: vector_t
  use matrix, only: matrix_t
  use device, only: HOST_TO_DEVICE, DEVICE_TO_HOST
  use json_module, only: json_file
  use json_utils, only: json_extract_item, json_get, json_get_or_default
  use simulation_m, only: simulation_t
  use adjoint_fluid_pnpn, only: adjoint_fluid_pnpn_t
  use field_math, only: field_glsc2
  use logger, only: neko_log, LOG_SIZE
  use math, only: copy
  use time_state, only: time_state_t
  use vector_math, only: vector_add2, vector_cfill
  use time_step_controller, only: time_step_controller_t
  use case, only: case_t
  use simcomp_executor, only: neko_simcomps
  use simulation_adjoint, only: simulation_adjoint_init, &
       simulation_adjoint_step, simulation_adjoint_finalize
  use simulation, only: simulation_init, simulation_step, simulation_finalize
  use neko_ext, only: start_time_history
  use mpi_f08, only: MPI_WTIME
  use profiler, only: profiler_start_region, profiler_end_region
  use utils, only: neko_error
  implicit none
  private

  !> The abstract problem type.
  type, public :: problem_t
     private

     !> The number of design variables.
     integer :: n_design = 0
     !> Number of objectives in the problem.
     integer :: n_objectives = 0
     !> Number of constraints in the problem.
     integer :: n_constraints = 0
     !> Length of the last unsteady forward run. It is summed step by step
     !! as the functionals sum `value_weight`, so that it equals that of a
     !! functional without a time window bit for bit.
     real(kind=xp) :: run_time = 0.0_xp

     !> The objective of the problem.
     class(objective_wrapper_t), allocatable, dimension(:) :: objective_list
     !> The constraints of the problem.
     class(constraint_wrapper_t), allocatable, dimension(:) :: constraint_list
   contains

     ! ----------------------------------------------------------------------- !
     ! Interfaces

     !> Constructor for the base class.
     procedure, pass(this), public :: init => problem_init
     !> Destructor for the base class.
     procedure, pass(this), public :: free => problem_free

     !> Evaluate the optimization problem.
     !! This is the main function that evaluates the problem. It should be
     !! implemented in the derived classes.
     procedure, pass(this), public :: compute => problem_compute

     !> Evaluate the sensitivity of the optimization problem.
     !! This is the main function that evaluates the problem sensitivity to the
     !! design. It should be implemented in the derived classes.
     procedure, pass(this), public :: compute_sensitivity => &
          problem_compute_sensitivity
     !> Run the unsteady problem forward in time while time integrating the
     !! objective function.
     procedure, pass(this), public :: run_forward_unsteady => &
          problem_run_forward_unsteady
     !> Run the unsteady adjoint backwards in time while time integrating the
     !! sensitivity.
     procedure, pass(this), public :: run_backward_unsteady => &
          problem_run_backward_unsteady
     !> Warn about objectives whose time window never overlapped the run.
     procedure, pass(this) :: check_objective_windows => &
          problem_check_objective_windows
     ! ----------------------------------------------------------------------- !
     ! Base class methods

     !> Read objective json-file.
     procedure, pass(this), public :: read_objectives => problem_read_objectives
     !> Read constraint json-file.
     procedure, pass(this), public :: read_constraints => &
          problem_read_constraints

     ! ----------------------------------------------------------------------- !
     ! Actual methods

     !> Sample the problem.
     procedure, pass(this), public :: write => problem_write
     !> Fill optimization log values.
     procedure, pass(this), public :: get_log_values => problem_get_log_values

     !> Add an objective to the list.
     procedure, pass(this), public :: add_objective => problem_add_objective
     !> Add a constraint to the list.
     procedure, pass(this), public :: add_constraint => problem_add_constraint

     ! ----------------------------------------------------------------------- !
     ! Internal Updater methods

     !> Update the objective function.
     procedure, pass(this) :: update_objectives => &
          problem_update_objectives
     !> Update the constraints.
     procedure, pass(this) :: update_constraints => &
          problem_update_constraints
     !> Update the objective sensitivities.
     procedure, pass(this) :: update_objective_sensitivities => &
          problem_update_objective_sensitivities
     !> Update the constraint sensitivities.
     procedure, pass(this) :: update_constraint_sensitivities => &
          problem_update_constraint_sensitivities

     !> Reset the objective function.
     procedure, pass(this) :: reset_objectives => &
          problem_reset_objectives
     !> Reset the constraints.
     procedure, pass(this) :: reset_constraints => &
          problem_reset_constraints
     !> Reset the objective sensitivities.
     procedure, pass(this) :: reset_objective_sensitivities => &
          problem_reset_objective_sensitivities
     !> Reset the constraint sensitivities.
     procedure, pass(this) :: reset_constraint_sensitivities => &
          problem_reset_constraint_sensitivities

     !> Accumulate the objective function.
     procedure, pass(this) :: accumulate_objectives => &
          problem_accumulate_objectives
     !> Accumulate the constraints.
     procedure, pass(this) :: accumulate_constraints => &
          problem_accumulate_constraints
     !> Accumulate the objective sensitivities.
     procedure, pass(this) :: accumulate_objective_sensitivities => &
          problem_accumulate_objective_sensitivities
     !> Accumulate the constraint sensitivities.
     procedure, pass(this) :: accumulate_constraint_sensitivities => &
          problem_accumulate_constraint_sensitivities
     !> Accumulate the objective sensitivities of a restored forward state of
     !! an unsteady run.
     procedure, pass(this) :: accumulate_sensitivity_sample => &
          problem_accumulate_sensitivity_sample

     ! ----------------------------------------------------------------------- !
     ! Public Getters

     !> Return the objective.
     procedure, pass(this), public :: get_objective_value => &
          problem_get_objective_value
     !> Return all components of the objective.
     procedure, pass(this), public :: get_all_objective_values => &
          problem_get_all_objective_values
     !> Return the constraints.
     procedure, pass(this), public :: get_constraint_values => &
          problem_get_constraint_values
     !> Return the sensitivity of the objective.
     procedure, pass(this), public :: get_objective_sensitivities => &
          problem_get_objective_sensitivities
     !> Return the sensitivity of the constraints.
     procedure, pass(this), public :: get_constraint_sensitivities => &
          problem_get_constraint_sensitivities

     !> Return the number of objectives.
     procedure, pass(this) :: get_n_objectives => problem_get_num_objectives
     !> Return the number of constraints.
     procedure, pass(this) :: get_n_constraints => problem_get_num_constraints

     !> Return the logfile header
     procedure, pass(this) :: get_log_header => problem_get_log_header
     !> Return the logfile base size (excluding iter and optimizer extras)
     procedure, pass(this) :: get_log_size => problem_get_log_size

  end type problem_t

contains

  ! ========================================================================== !
  ! Base class methods

  !> The constructor for the base problem.
  subroutine problem_init(this, parameters, design, simulation)
    class(problem_t), intent(inout) :: this
    type(json_file), intent(inout) :: parameters
    class(design_t), intent(in) :: design
    type(simulation_t), optional, intent(inout) :: simulation

    call this%free()

    this%n_design = design%size()

    ! Read the objectives and constraints
    call this%read_objectives(parameters, design, simulation)
    call this%read_constraints(parameters, design, simulation)

  end subroutine problem_init

  !> Destructor for the base class
  subroutine problem_free(this)
    class(problem_t), intent(inout) :: this
    integer :: i

    this%n_design = 0
    this%n_objectives = 0
    this%n_constraints = 0
    this%run_time = 0.0_xp

    ! Free the objective list
    if (allocated(this%objective_list)) then
       do i = 1, size(this%objective_list)
          call this%objective_list(i)%free()
       end do
       deallocate(this%objective_list)
    end if

    ! Free the constraint list
    if (allocated(this%constraint_list)) then
       do i = 1, size(this%constraint_list)
          call this%constraint_list(i)%free()
       end do
       deallocate(this%constraint_list)
    end if
  end subroutine problem_free

  !> Sample the fields/design.
  subroutine problem_write(this, idx)
    class(problem_t), intent(inout) :: this
    integer, intent(in) :: idx

  end subroutine problem_write

  !> Fill optimization log values in caller-provided array.
  !! @param[in] this The problem object.
  !! @param[out] values Array to populate with log values.
  !! @param[in] include_constraints Include constraints in the log values.
  subroutine problem_get_log_values(this, values, include_constraints)
    class(problem_t), intent(in) :: this
    real(kind=rp), intent(out) :: values(:)
    logical, intent(in), optional :: include_constraints
    integer :: i, n, offset
    real(kind=rp) :: objective_value
    real(kind=rp), allocatable :: tmp(:)
    logical :: do_constraints

    if (present(include_constraints)) then
       do_constraints = include_constraints
    else
       do_constraints = .true.
    end if

    call this%get_objective_value(objective_value)
    values = 0.0_rp
    values(1) = objective_value

    offset = 2
    do i = 1, this%n_objectives
       n = this%objective_list(i)%objective%get_log_size()
       if (n .gt. 0) then
          allocate(tmp(n))
          call this%objective_list(i)%objective%get_log_values(tmp)
          values(offset:offset + n - 1) = tmp
          offset = offset + n
          deallocate(tmp)
       end if
    end do

    if (do_constraints) then
       do i = 1, this%n_constraints
          n = this%constraint_list(i)%constraint%get_log_size()
          if (n .gt. 0) then
             allocate(tmp(n))
             call this%constraint_list(i)%constraint%get_log_values(tmp)
             values(offset:offset + n - 1) = tmp
             offset = offset + n
             deallocate(tmp)
          end if
       end do
    end if
  end subroutine problem_get_log_values

  ! ========================================================================== !
  ! Handling constraints and objectives

  !> Read the objective from a parameters file.
  subroutine problem_read_objectives(this, parameters, design, simulation)
    class(problem_t), intent(inout) :: this
    type(json_file), intent(inout) :: parameters
    class(design_t), intent(in) :: design
    type(simulation_t), optional, intent(inout) :: simulation
    class(objective_t), allocatable :: objective

    ! A single objective term as its own json_file.
    character(len=:), allocatable :: path, type
    type(json_file) :: objective_json
    integer :: n_objectives, i
    logical :: dealias, dealias_fallback

    call neko_log%section("Reading objectives")

    ! Get the number of objectives.
    path = "optimization.objectives"
    if (parameters%valid_path(path)) then
       call parameters%info(path, n_children = n_objectives)

       ! Grab a single parameters entry and create a constraint from it.
       do i = 1, n_objectives
          call json_extract_item(parameters, path, i, objective_json)
          call json_get(objective_json, "type", type)
          call neko_log%message(type)

          call objective_factory(objective, objective_json, design, simulation)
          call this%add_objective(objective)
       end do
    end if

    if (present(simulation)) then
       if (allocated(objective)) deallocate(objective)
       allocate(augmented_lagrangian_objective_t::objective)
       select type (ALO => objective)
       class is (augmented_lagrangian_objective_t)
          call json_get(parameters, 'case.numerics.dealias', dealias_fallback)
          call json_get_or_default(parameters, &
               "optimization.augmented_lagrangian.dealias_sensitivity", &
               dealias, dealias_fallback)
          call ALO%init_from_attributes(design, simulation, weight = 1.0_rp, &
               name = "Augmented Lagrangian", mask_name = "", &
               dealias = dealias)
       end select
       call this%add_objective(objective)
    end if

    call neko_log%end_section()

  end subroutine problem_read_objectives

  !> Read the constraint from a parameters file.
  subroutine problem_read_constraints(this, parameters, design, simulation)
    class(problem_t), intent(inout) :: this
    type(json_file), intent(inout) :: parameters
    class(design_t), intent(in) :: design
    class(constraint_t), allocatable :: constraint
    type(simulation_t), optional, intent(inout) :: simulation

    ! A single constraint term as its own json_file.
    character(len=:), allocatable :: path, type
    type(json_file) :: constraint_json
    integer :: n_constraints, i

    call neko_log%section("Reading constraints")

    ! Get the number of constraints.
    path = "optimization.constraints"

    if (parameters%valid_path(path)) then
       call parameters%info(path, n_children = n_constraints)

       ! Grab a single parameters entry and create a constraint from it.
       do i = 1, n_constraints
          call json_extract_item(parameters, path, i, constraint_json)
          call json_get(constraint_json, "type", type)
          call neko_log%message(type)

          call constraint_factory(constraint, constraint_json, design, &
               simulation)
          call this%add_constraint(constraint)
       end do
    end if

    call neko_log%end_section()

  end subroutine problem_read_constraints

  !> Add an objective to the list.
  subroutine problem_add_objective(this, objective)
    class(problem_t), intent(inout) :: this
    class(objective_t), allocatable, intent(inout) :: objective
    class(objective_wrapper_t), allocatable, dimension(:) :: temp_list
    integer :: i, n

    n = 0
    if (allocated(this%objective_list)) then
       n = size(this%objective_list)
       call move_alloc(this%objective_list, temp_list)
       allocate(this%objective_list(n + 1))
       if (allocated(temp_list)) then
          do i = 1, n
             call move_alloc(temp_list(i)%objective, &
                  this%objective_list(i)%objective)
          end do
       end if
    else
       allocate(this%objective_list(1))
    end if

    call move_alloc(objective, this%objective_list(n + 1)%objective)
    this%n_objectives = n + 1
  end subroutine problem_add_objective

  !> Add an objective to the list.
  subroutine problem_add_constraint(this, constraint)
    class(problem_t), intent(inout) :: this
    class(constraint_t), allocatable, intent(inout) :: constraint
    class(constraint_wrapper_t), allocatable, dimension(:) :: temp_list
    integer :: i, n

    n = 0
    if (allocated(this%constraint_list)) then
       n = size(this%constraint_list)
       call move_alloc(this%constraint_list, temp_list)
       allocate(this%constraint_list(n + 1))
       if (allocated(temp_list)) then
          do i = 1, n
             call move_alloc(temp_list(i)%constraint, &
                  this%constraint_list(i)%constraint)
          end do
       end if
    else
       allocate(this%constraint_list(1))
    end if

    call move_alloc(constraint, this%constraint_list(n + 1)%constraint)
    this%n_constraints = n + 1
  end subroutine problem_add_constraint

  ! ========================================================================== !
  ! Problem part computation

  !> The computation of the objective function and constraints.
  subroutine problem_compute(this, design, simulation)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(inout) :: design
    class(simulation_t), optional, intent(inout) :: simulation

    if (present(simulation)) then
       call simulation%reset()
       if (simulation%unsteady) then
          ! Objective value accumulated
          call this%run_forward_unsteady(simulation, design)
       else
          call simulation%run_forward()
          ! Compute objective value on steady field
          call this%update_objectives(design)
       end if
    else
       call this%update_objectives(design)
    end if

    call this%update_constraints(design)

  end subroutine problem_compute

  !> The computation of the objective function and constraints.
  subroutine problem_compute_sensitivity(this, design, simulation)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(inout) :: design
    class(simulation_t), optional, intent(inout) :: simulation

    type(vector_t) :: objective_sensitivity

    if (present(simulation)) then
       if (simulation%unsteady) then
          ! Objective sensitivity accumulated
          call this%run_backward_unsteady(simulation, design)
       else
          call simulation%run_backward()
          ! Compute sensitivity on steady field
          call this%update_objective_sensitivities(design)
       end if
    else
       call this%update_objective_sensitivities(design)
    end if

    call this%update_constraint_sensitivities(design)

    call objective_sensitivity%init(this%n_design)
    call this%get_objective_sensitivities(objective_sensitivity)

    call design%map_backward(objective_sensitivity)

    call objective_sensitivity%free()
  end subroutine problem_compute_sensitivity

  !> Run the unsteady forward simulation and save its states for the adjoint.
  !! @details A time grid frozen in the state recovery is replayed step by
  !! step; otherwise the time-step controller of the case sets the steps.
  !! @param this The problem, whose objectives are accumulated over the run.
  !! @param simulation The simulation to run. Its state recovery is handed
  !! the initial state and the state after every step.
  !! @param design The design the objectives are evaluated for.
  subroutine problem_run_forward_unsteady(this, simulation, design)
    class(problem_t), intent(inout) :: this
    class(simulation_t), intent(inout) :: simulation
    class(design_t), intent(inout) :: design
    type(time_step_controller_t) :: dt_controller
    real(kind=dp) :: loop_start, dt_first
    logical :: replay, seeded
    character(len=LOG_SIZE) :: log_buf

    if (.not. allocated(simulation%state_recover)) then
       call neko_error("State recovery not initialized.")
    end if

    ! A prescribed time grid is replayed with the default controller, which
    ! keeps the time step, so that neither set_dt nor land changes the
    ! prescribed step.
    replay = simulation%state_recover%has_prescribed_grid()
    if (.not. replay) call simulation%init_dt_controller(dt_controller)

    call simulation%reset()
    if (replay) then
       simulation%neko_case%time%dt = &
            simulation%state_recover%get_prescribed_dt(1)
    end if
    call simulation_init(simulation%neko_case, dt_controller)

    ! The reset starts the time scheme at full order, so the first step uses
    ! the whole time-step history. Start it from equal steps of the first
    ! step, the same in a replay as in the run that recorded the grid.
    seeded = replay .or. dt_controller%is_variable_dt
    if (seeded) then
       call forward_first_dt(simulation%neko_case, dt_controller, dt_first)
       call start_time_history(simulation%neko_case%time, dt_first)
    end if

    ! Reset the objective value to zero
    call this%reset_objectives()

    call profiler_start_region("Forward simulation")
    loop_start = MPI_WTIME()
    simulation%n_timesteps = 0
    this%run_time = 0.0_xp
    ! save the initial state
    call simulation%state_recover%save()
    do while (.not. simulation%neko_case%time%is_done())
       simulation%n_timesteps = simulation%n_timesteps + 1
       if (replay) then
          simulation%neko_case%time%dt = &
               simulation%state_recover%get_prescribed_dt( &
               simulation%n_timesteps)
       end if
       ! step forward
       call simulation_step(simulation%neko_case, dt_controller, loop_start)
       ! The first step has to take the step its history was started from.
       ! The prediction repeats the arithmetic of simulation_step on the same
       ! state, so the two agree exactly unless they have drifted apart.
       if (seeded .and. simulation%n_timesteps .eq. 1) then
          if (.not. (abs(simulation%neko_case%time%dt - dt_first) .le. &
               0.0_dp)) then
             write (log_buf, '(A,ES24.16)') "First forward time step: ", &
                  simulation%neko_case%time%dt
             call neko_log%message(log_buf)
             write (log_buf, '(A,ES24.16)') "Predicted time step:     ", &
                  dt_first
             call neko_log%message(log_buf)
             call neko_error("The first forward step did not take the " // &
                  "time step forward_first_dt predicted for it")
          end if
       end if
       this%run_time = this%run_time + &
            real(simulation%neko_case%time%dt, kind=xp)
       ! accumulate objective value
       call this%accumulate_objectives(design, simulation%neko_case%time)
       ! save a checkpoint
       call simulation%state_recover%save()
    end do
    call profiler_end_region("Forward simulation")

    call this%check_objective_windows()

    call simulation_finalize(simulation%neko_case)

  end subroutine problem_run_forward_unsteady

  !> The time step the first step of a forward run is going to take.
  !! @details Computed on copies of the time-step controller and the time
  !! state, the way `simulation_step` computes it: the step the controller
  !! chooses, fitted to the next output time or to the end time with
  !! `exact_output_time`. The case holds the fields and the time the first
  !! step starts from, so the step then takes the same time step, which the
  !! forward run checks. With the default controller, as in a replay, it is
  !! the time step the time state holds.
  !! @param neko_case The case, about to take its first step.
  !! @param dt_controller The time-step controller of the run.
  !! @param dt The time step of the first step.
  subroutine forward_first_dt(neko_case, dt_controller, dt)
    type(case_t), intent(in) :: neko_case
    type(time_step_controller_t), intent(in) :: dt_controller
    real(kind=dp), intent(out) :: dt
    type(time_step_controller_t) :: controller
    type(time_state_t) :: time
    real(kind=dp) :: cfl

    controller = dt_controller
    time = neko_case%time
    cfl = neko_case%fluid%compute_cfl(time%dt)
    call controller%set_dt(time, cfl)
    if (controller%exact_output_time) then
       call controller%land(time, &
            min(neko_case%output_controller%time_to_next(time), &
            neko_simcomps%time_to_next(time)))
    end if
    dt = time%dt

  end subroutine forward_first_dt

  !> Warn about objectives whose time window never overlapped the run.
  !!
  !! Such an objective accumulates nothing and reports zero, which is easy to
  !! mistake for a well-performing design. Say so rather than staying silent.
  !! @param this The problem.
  subroutine problem_check_objective_windows(this)
    class(problem_t), intent(inout) :: this
    character(len=LOG_SIZE) :: log_buf
    integer :: i

    do i = 1, this%n_objectives
       if (this%objective_list(i)%objective%value_weight .gt. 0.0_rp) cycle

       write (log_buf, '(A,A,A)') "Objective '", &
            this%objective_list(i)%objective%get_name(), &
            "' was never sampled; its time window misses the run."
       call neko_log%warning(trim(log_buf))
    end do
  end subroutine problem_check_objective_windows

  !> Run the adjoint backwards
  !! @details The adjoint replays the time grid of the forward run in
  !! reverse: it steps back over forward step \f$ i \f$ with that step's
  !! \f$ \Delta t_i \f$, using the default time-step controller, which keeps
  !! the time step it is given. Its time-step history starts saturated with
  !! the last forward step, as the forward's starts with the first.
  !!
  !! The exact transpose of the time scheme, `simulation%exact_adjoint`,
  !! sets the columns of the adjoint level of state \f$ i \f$ from the
  !! coefficients the forward run recorded before every step, and the
  !! adjoint fluid takes them instead of those of its own history. The
  !! sensitivity of state \f$ i \f$ is sampled after the step, which forms
  !! the combined adjoint the state is paired with. Otherwise it is sampled
  !! before the step, with the adjoint's own coefficients, which is exact at
  !! a fixed time step only.
  !! @param this The problem.
  !! @param simulation The simulation, whose state recovery holds the forward
  !! run.
  !! @param design The design.
  subroutine problem_run_backward_unsteady(this, simulation, design)
    class(problem_t), intent(inout) :: this
    class(simulation_t), intent(inout) :: simulation
    class(design_t), intent(inout) :: design
    type(time_step_controller_t) :: dt_controller
    type(adjoint_fluid_pnpn_t), pointer :: fluid_adj
    real(kind=dp) :: loop_start
    real(kind=rp) :: cfl
    real(kind=rp) :: total_time
    real(kind=rp) :: ext_col(4), bdf_col(4)
    integer :: i, j, n
    logical :: exact
    type(time_state_t) :: sample

    if (.not. allocated(simulation%state_recover)) then
       call neko_error("State recovery not initialized.")
    end if
    n = simulation%n_timesteps

    exact = simulation%exact_adjoint
    nullify(fluid_adj)
    if (exact) call exact_adjoint_fluid(simulation, fluid_adj)

    ! The reset starts the adjoint's history from its initial time step,
    ! before the forward run chose its steps. Start it from equal steps of
    ! the last forward step instead, which the adjoint takes first, so that
    ! the history is saturated with equal steps at both ends of the run.
    simulation%adjoint_case%time%dt = simulation%state_recover%get_dt(n)
    call start_time_history(simulation%adjoint_case%time, &
         simulation%state_recover%get_dt(n))
    call simulation_adjoint_init(simulation%adjoint_case, dt_controller)

    ! Reset the sensitivity value to zero
    call this%reset_objective_sensitivities()

    cfl = simulation%adjoint_case%fluid_adj%compute_cfl( &
         simulation%adjoint_case%time%dt)
    loop_start = MPI_WTIME()

    ! Total time of the forward simulation
    total_time = real(simulation%state_recover%get_end_time() - &
         simulation%state_recover%get_time(0), kind=rp)

    call profiler_start_region("Adjoint simulation")

    do i = n, 1, -1
       ! restore primal field
       call simulation%state_recover%restore(i)
       if (exact) then
          call simulation%state_recover%get_adjoint_ext_column(i, ext_col)
          call simulation%state_recover%get_adjoint_bdf_column(i, bdf_col)
          call fluid_adj%set_exact_coeffs(ext_col, bdf_col)
       else
          ! accumulate objective sensitivity
          call this%accumulate_sensitivity_sample(design, simulation, i)
       end if
       ! The step's forcings consume the same primal sample, so each
       ! objective gates and scales its forcing by its own window there,
       ! at the time and step the forward run recorded for the sample.
       call simulation%state_recover%get_time_state(i, sample)
       do j = 1, this%n_objectives
          call this%objective_list(j)%objective%update_forcing_scale( &
               sample, this%run_time)
       end do
       ! step the adjoint backwards over forward step i
       simulation%adjoint_case%time%dt = simulation%state_recover%get_dt(i)
       call simulation_adjoint_step(simulation%adjoint_case, dt_controller, &
            cfl, loop_start, total_time)
       if (exact) then
          call this%accumulate_sensitivity_sample(design, simulation, i)
       end if
    end do

    ! The initial state, paired with the adjoint state the run ends at
    call simulation%state_recover%restore(0)
    if (exact) then
       call simulation%state_recover%get_adjoint_ext_column(0, ext_col)
       call fluid_adj%combine_adjoint(ext_col)
    end if
    call this%accumulate_sensitivity_sample(design, simulation, 0)
    if (exact) then
       call fluid_adj%clear_exact_coeffs()
       nullify(fluid_adj)
    end if

    ! Leave every forcing scale at one, as the steady path assumes
    do j = 1, this%n_objectives
       call this%objective_list(j)%objective%reset_forcing_scale()
    end do

    call profiler_end_region("Adjoint simulation")

    call simulation_adjoint_finalize(simulation%adjoint_case, n)

  end subroutine problem_run_backward_unsteady

  !> Accumulate the objective sensitivities of a restored forward state of an
  !! unsteady run.
  !! @details This is the one place that decides how the sensitivity of an
  !! unsteady run is integrated in time. With the forward state \f$ u_i \f$
  !! restored, the explicit sensitivity of an objective at \f$ u_i \f$ is
  !! weighted by \f$ \Delta t_i \f$, as its value was. The coupling term of
  !! the augmented Lagrangian comes from the explicit terms of the forward
  !! steps \f$ i + 1 \f$ to \f$ i + 3 \f$, which apply the design to
  !! \f$ u_i \f$. Its pairing depends on the time transpose of the adjoint:
  !! - The exact transpose samples after the adjoint step over forward step
  !!   \f$ i \f$. That step combines the adjoint levels those explicit terms
  !!   enter, with their EXT column, into \f$ u^\dagger_{e,i} \f$, and the
  !!   term \f$ (u_i, u^\dagger_{e,i}) \f$ is weighted by \f$ \Delta t_i \f$
  !!   at every time order. This pairing is exact.
  !! - The reverse replay samples before that step, with the adjoint at
  !!   \f$ \lambda_{i+1} \f$. The term \f$ (u_i, \lambda_{i+1}) \f$ is
  !!   weighted by \f$ \Delta t_i \f$ at time order 2 and 3, and at time
  !!   order 1 by the step the adjoint took to \f$ \lambda_{i+1} \f$,
  !!   \f$ \Delta t_{i+1} \f$, or at \f$ i = N \f$, where
  !!   \f$ \lambda_{N+1} \f$ is the terminal condition, by the step the
  !!   adjoint starts from, \f$ \Delta t_N \f$. At time order 1 step
  !!   \f$ i + 1 \f$ alone applies the design to \f$ u_i \f$, so that
  !!   weight is exact. At time order 2 and 3 no single weight is exact
  !!   under a variable time step; measured against the exact discrete
  !!   gradient, \f$ \Delta t_i \f$ is the closer by a constant factor.
  !!
  !! The initial state, \f$ i = 0 \f$, has the coupling term only, weighted
  !! by \f$ \Delta t_1 \f$ and paired with the adjoint the run ends at: the
  !! combination of the first three levels with the EXT column of the
  !! initial state in the exact transpose, \f$ \lambda_1 \f$ in the reverse
  !! replay. The first forward step applies the design to \f$ u_0 \f$ in its
  !! explicit terms, but the value has no sample there. The time \f$ t_i \f$
  !! and the steps are those the forward run recorded. Every other sample
  !! spans \f$ \Delta t_i \f$ of the normalisation, so that the sensitivity
  !! is normalised by the same time as the value.
  !! @param this The problem.
  !! @param design The design.
  !! @param simulation The simulation, whose state recovery holds the time
  !! grid of the forward run.
  !! @param i Index of the restored forward state, 0 for the initial state.
  subroutine problem_accumulate_sensitivity_sample(this, design, simulation, &
       i)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    class(simulation_t), intent(in) :: simulation
    integer, intent(in) :: i
    type(time_state_t) :: sample
    real(kind=dp) :: coupling_weight
    integer :: j, n

    n = simulation%state_recover%get_n_timesteps()
    call simulation%state_recover%get_time_state(i, sample)
    if (simulation%exact_adjoint .or. &
         simulation%neko_case%fluid%ext_bdf%diffusion_time_order .ne. 1) then
       coupling_weight = simulation%state_recover%get_dt(max(i, 1))
    else
       coupling_weight = simulation%state_recover%get_dt(min(i + 1, n))
    end if

    do j = 1, this%n_objectives
       select type (objective => this%objective_list(j)%objective)
       class is (augmented_lagrangian_objective_t)
          if (i .eq. 0) then
             call objective%accumulate_sensitivity(design, sample, &
                  weight = coupling_weight, span = 0.0_dp)
          else
             call objective%accumulate_sensitivity(design, sample, &
                  weight = coupling_weight)
          end if
       class default
          if (i .gt. 0) call objective%accumulate_sensitivity(design, sample)
       end select
    end do

  end subroutine problem_accumulate_sensitivity_sample

  !> The adjoint fluid of the exact transpose of the time scheme, checked
  !! against what the transpose assumes.
  !! @details The exact transpose starts from a zero adjoint past the last
  !! step, which is the terminal condition of a time integral, and every
  !! step forms the combined adjoint, which a frozen adjoint fluid does not.
  !! It takes every coefficient from the record of the forward run, and it
  !! is verified for forward steps at the time orders of the case, which the
  !! reset of the forward run gives every step from the first. A recorded
  !! step of other orders stops the run.
  !! @param simulation The simulation.
  !! @param fluid_adj The adjoint fluid.
  subroutine exact_adjoint_fluid(simulation, fluid_adj)
    class(simulation_t), intent(in) :: simulation
    type(adjoint_fluid_pnpn_t), pointer, intent(out) :: fluid_adj
    character(len=256) :: msg
    real(kind=rp) :: terminal
    integer :: i, ndiff, nadv

    nullify(fluid_adj)
    select type (f => simulation%adjoint_fluid)
    type is (adjoint_fluid_pnpn_t)
       fluid_adj => f
    class default
       call neko_error("The exact time transpose needs adjoint_fluid_pnpn_t")
    end select

    if (fluid_adj%freeze) then
       call neko_error("The exact time transpose of the unsteady adjoint " // &
            "does not support a frozen adjoint fluid, " // &
            "case.adjoint_fluid.freeze_flow")
    end if

    terminal = field_glsc2(fluid_adj%u_adj, fluid_adj%u_adj) + &
         field_glsc2(fluid_adj%v_adj, fluid_adj%v_adj) + &
         field_glsc2(fluid_adj%w_adj, fluid_adj%w_adj) + &
         field_glsc2(fluid_adj%p_adj, fluid_adj%p_adj)
    if (terminal .gt. 0.0_rp) then
       call neko_error("The exact time transpose of the unsteady adjoint " // &
            "needs a zero case.adjoint_fluid.initial_condition, or set " // &
            "case.adjoint_fluid.time_transpose to ""reverse""")
    end if

    do i = 1, simulation%state_recover%get_n_timesteps()
       call simulation%state_recover%get_scheme_orders(i, ndiff, nadv)
       if (ndiff .ne. fluid_adj%ext_bdf%diffusion_time_order .or. &
            nadv .ne. fluid_adj%ext_bdf%advection_time_order) then
          write(msg, '(A,I0,A,I0,A,I0,A,I0,A,I0)') "The exact time " // &
               "transpose of the unsteady adjoint is verified for BDF ", &
               fluid_adj%ext_bdf%diffusion_time_order, " and EXT ", &
               fluid_adj%ext_bdf%advection_time_order, &
               " in every step, but forward step ", i, " took BDF ", &
               ndiff, " and EXT ", nadv
          call neko_error(trim(msg))
       end if
    end do
  end subroutine exact_adjoint_fluid

  ! ========================================================================== !
  ! Update the objectives and constraints

  !> Update the objectives.
  !!
  !! This function should be called after the design has been updated.
  !! It will update the value of all the objectives.
  !! @param[inout] this The problem to update the objectives with.
  !! @param[in] design The design to update the objectives with.
  subroutine problem_update_objectives(this, design)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    integer :: i

    do i = 1, this%n_objectives
       call this%objective_list(i)%objective%update_value(design)
    end do
  end subroutine problem_update_objectives

  !> Update the constraints.
  !!
  !! This function should be called after the design has been updated.
  !! It will update the value of all the constraints.
  !! @param[inout] this The problem to update the objectives with.
  !! @param[in] design The design to update the constraints with.
  subroutine problem_update_constraints(this, design)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    integer :: i

    do i = 1, this%n_constraints
       call this%constraint_list(i)%constraint%update_value(design)
    end do
  end subroutine problem_update_constraints

  !> Update the sensitivity of the objectives.
  !!
  !! This function should be called after the design has been updated.
  !! It will update the sensitivity of all the objectives.
  !! @param[inout] this The problem to update the objectives with.
  !! @param[in] design The design to update the objectives with.
  subroutine problem_update_objective_sensitivities(this, design)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    integer :: i

    do i = 1, this%n_objectives
       call this%objective_list(i)%objective%update_sensitivity(design)
    end do
  end subroutine problem_update_objective_sensitivities

  !> Update the sensitivity of the constraints.
  !!
  !! This function should be called after the design has been updated.
  !! It will update the sensitivity of all the constraints.
  !! @param[inout] this The problem to update the objectives with.
  !! @param[in] design The design to update the constraints with.
  subroutine problem_update_constraint_sensitivities(this, design)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    integer :: i

    do i = 1, this%n_constraints
       call this%constraint_list(i)%constraint%update_sensitivity(design)
    end do
  end subroutine problem_update_constraint_sensitivities

  ! ========================================================================== !
  ! Reset the objectives and constraints

  !> Reset the objectives.
  !!
  !! This function will reset all objectives to zero.
  !! @param[inout] this The problem to reset the objectives with.
  subroutine problem_reset_objectives(this)
    class(problem_t), intent(inout) :: this
    integer :: i

    do i = 1, this%n_objectives
       call this%objective_list(i)%objective%reset_value()
    end do
  end subroutine problem_reset_objectives

  !> Reset the constraints.
  !!
  !! This function will reset all the constraints to zero.
  !! @param[inout] this The problem to reset the objectives with.
  subroutine problem_reset_constraints(this)
    class(problem_t), intent(inout) :: this
    integer :: i

    do i = 1, this%n_constraints
       call this%constraint_list(i)%constraint%reset_value()
    end do
  end subroutine problem_reset_constraints

  !> Reset the sensitivity of the objectives.
  !!
  !! This function will reset all the objective sensitivity to zero.
  !! @param[inout] this The problem to reset the objectives with.
  subroutine problem_reset_objective_sensitivities(this)
    class(problem_t), intent(inout) :: this
    integer :: i

    do i = 1, this%n_objectives
       call this%objective_list(i)%objective%reset_sensitivity()
    end do
  end subroutine problem_reset_objective_sensitivities

  !> Reset the sensitivity of the constraints.
  !!
  !! This function will reset all the constraint sensitivity to zero.
  !! @param[inout] this The problem to reset the objectives with.
  subroutine problem_reset_constraint_sensitivities(this)
    class(problem_t), intent(inout) :: this
    integer :: i

    do i = 1, this%n_constraints
       call this%constraint_list(i)%constraint%reset_sensitivity()
    end do
  end subroutine problem_reset_constraint_sensitivities

  ! ========================================================================== !
  ! Accumulate the objectives and constraints

  !> Accumulate the objectives.
  !!
  !! This function will accumulate all objectives.
  !! @param[inout] this The problem to accumulate the objectives with.
  !! @param[in] design The design to accumulate the objectives with.
  !! @param[in] time The current time state.
  subroutine problem_accumulate_objectives(this, design, time)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    type(time_state_t), intent(in) :: time
    integer :: i

    do i = 1, this%n_objectives
       call this%objective_list(i)%objective%accumulate_value(design, time)
    end do
  end subroutine problem_accumulate_objectives

  !> Accumulate the constraints.
  !!
  !! This function will accumulate all the constraints.
  !! @param[inout] this The problem to accumulate the objectives with.
  !! @param[in] design The design to accumulate the constraints with.
  !! @param[in] time The current time state.
  subroutine problem_accumulate_constraints(this, design, time)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    type(time_state_t), intent(in) :: time
    integer :: i

    do i = 1, this%n_constraints
       call this%constraint_list(i)%constraint%accumulate_value(design, time)
    end do
  end subroutine problem_accumulate_constraints

  !> Accumulate the sensitivity of the objectives.
  !!
  !! This function will accumulate all the objective sensitivity.
  !! @param[inout] this The problem to accumulate the objectives with.
  !! @param[in] design The design to accumulate the objectives with.
  !! @param[in] time The current time state.
  subroutine problem_accumulate_objective_sensitivities(this, design, time)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    type(time_state_t), intent(in) :: time
    integer :: i

    do i = 1, this%n_objectives
       call this%objective_list(i)%objective%accumulate_sensitivity(design, &
            time)
    end do
  end subroutine problem_accumulate_objective_sensitivities

  !> Accumulate the sensitivity of the constraints.
  !!
  !! This function will accumulate all the constraint sensitivity.
  !! @param[inout] this The problem to accumulate the objectives with.
  !! @param[in] design The design to accumulate the constraints with.
  !! @param[in] time The current time state.
  subroutine problem_accumulate_constraint_sensitivities(this, design, time)
    class(problem_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    type(time_state_t), intent(in) :: time
    integer :: i

    do i = 1, this%n_constraints
       call this%constraint_list(i)%constraint%accumulate_sensitivity(design, &
            time)
    end do
  end subroutine problem_accumulate_constraint_sensitivities

  ! ========================================================================== !
  ! Problem part getters

  !> Construct and get the objective.
  !!
  !! This function constructs the objective value from the individual
  !! objectives and their weights.
  !! @param[in] this The problem to update the objectives with.
  !! @param[out] objective_value The weighted sum of all objective values.
  subroutine problem_get_objective_value(this, objective_value)
    class(problem_t), intent(in) :: this
    real(kind=rp), intent(out) :: objective_value
    integer :: i

    objective_value = 0.0_rp
    do i = 1, this%n_objectives
       objective_value = objective_value + &
            this%objective_list(i)%objective%get_weight() * &
            this%objective_list(i)%objective%get_value()
    end do

  end subroutine problem_get_objective_value

  !> Construct and get the objective.
  !!
  !! This function returns all the indivual objectives comprising the
  !! objective function
  !! @param[in] this The problem to update the objectives with.
  !! @param[inout] all_objective_values A vector containing all objectives
  subroutine problem_get_all_objective_values(this, all_objective_values)
    class(problem_t), intent(in) :: this
    type(vector_t), intent(inout) :: all_objective_values
    integer :: i

    do i = 1, this%n_objectives
       all_objective_values%x(i) = this%objective_list(i)%objective%value
    end do

    call all_objective_values%copy_from(HOST_TO_DEVICE, sync = .true.)

  end subroutine problem_get_all_objective_values

  !> Construct and get the constraints.
  !!
  !! This function constructs the constraint values from the individual
  !! constraints.
  !! @param[in] this The problem to update the objectives with.
  !! @param[inout] constraint_value The vector of all constraint values.
  subroutine problem_get_constraint_values(this, constraint_value)
    class(problem_t), intent(in) :: this
    type(vector_t), intent(inout) :: constraint_value
    integer :: i

    do i = 1, this%n_constraints
       constraint_value%x(i) = this%constraint_list(i)%constraint%value
    end do

    call constraint_value%copy_from(HOST_TO_DEVICE, sync = .true.)

  end subroutine problem_get_constraint_values

  !> Construct and get the sensitivity of the objective.
  !!
  !! This function constructs the sensitivity of the objective value from the
  !! individual objectives and their weights.
  !! @param[in] this The problem to update the objectives with.
  !! @param[inout] sensitivity The weighted sum of all objective sensitivities.
  subroutine problem_get_objective_sensitivities(this, sensitivity)
    class(problem_t), intent(in) :: this
    type(vector_t), intent(inout) :: sensitivity
    integer :: i

    call vector_cfill(sensitivity, 0.0_rp)
    do i = 1, this%n_objectives
       call vector_add2(sensitivity, &
            this%objective_list(i)%objective%sensitivity)
    end do

  end subroutine problem_get_objective_sensitivities

  !> Construct and get the sensitivity of the constraints.
  !!
  !! This function constructs the sensitivity of the constraint values from the
  !! individual constraints.
  !! @param[in] this The problem to update the objectives with.
  !! @param[inout] sensitivity The matrix of all constraint sensitivities.
  subroutine problem_get_constraint_sensitivities(this, sensitivity)
    class(problem_t), intent(inout) :: this
    type(matrix_t), target, intent(inout) :: sensitivity
    real(kind=rp), pointer :: row(:)
    integer :: i

    ! Copy all constraint sensitivities to host, sync on last one
    do i = 1, this%n_constraints
       call this%constraint_list(i)%constraint%sensitivity%copy_from( &
            DEVICE_TO_HOST, sync = i .eq. this%n_constraints)
    end do

    do i = 1, this%n_constraints
       row(1:this%n_design) => sensitivity%x(i, :)

       call copy(row, this%constraint_list(i)%constraint%sensitivity%x, &
            this%n_design)
    end do

    call sensitivity%copy_from(HOST_TO_DEVICE, sync = .true.)

  end subroutine problem_get_constraint_sensitivities

  ! ========================================================================== !
  ! Simple getters

  !> Return the number of objectives.
  pure function problem_get_num_objectives(this) result(n)
    class(problem_t), intent(in) :: this
    integer :: n

    n = this%n_objectives
  end function problem_get_num_objectives

  !> Return the number of constraints.
  pure function problem_get_num_constraints(this) result(n)
    class(problem_t), intent(in) :: this
    integer :: n

    n = this%n_constraints
  end function problem_get_num_constraints

  !> Return the header for the problem.
  !! @param[in] this The problem object.
  !! @param[in] include_constraints Include constraints in the header.
  !! @return buff Comma-separated header string.
  function problem_get_log_header(this, include_constraints) result(buff)
    class(problem_t), intent(in) :: this
    logical, intent(in), optional :: include_constraints
    character(len=:), allocatable :: buff
    integer :: i
    logical :: do_constraints

    buff = "Total objective function"
    if (present(include_constraints)) then
       do_constraints = include_constraints
    else
       do_constraints = this%get_n_constraints() .gt. 0
    end if

    do i = 1, this%get_n_objectives()
       call problem_append_log_headers(buff, this%objective_list(i)%objective)
    end do

    if (do_constraints) then
       do i = 1, this%get_n_constraints()
          call problem_append_log_headers(buff, &
               this%constraint_list(i)%constraint)
       end do
    end if

  end function problem_get_log_header

  !> Append the log headers of a functional to a comma-separated header.
  !!
  !! The headers are the functional's name plus a suffix of its own choosing,
  !! such as `.weight`. Their buffer holds at least `min_width` characters,
  !! the room every header has always had, and grows with the name to leave
  !! `suffix_len` characters after it. A name of any length therefore
  !! arrives in full, and a short name still leaves room for a long suffix.
  !! Only a header longer than both can be cut, and that cut is made inside
  !! `get_log_headers`, which fills a buffer of fixed length. A header that
  !! fills its buffer is reported, since it may have been cut. A cut that
  !! leaves a blank as the last character kept looks like padding, and
  !! cannot be detected through this interface.
  !! @param[inout] buff The header to append to.
  !! @param[in] functional The functional whose headers are appended.
  subroutine problem_append_log_headers(buff, functional)
    character(len=:), allocatable, intent(inout) :: buff
    class(base_functional_t), intent(in) :: functional
    integer, parameter :: width = 256
    character(len=width), allocatable :: headers(:)
    integer :: j, n

    n = functional%get_log_size()
    if (n .lt. 1) return

    allocate(headers(n))
    call functional%get_log_headers(headers)

    do j = 1, n
       if (len_trim(headers(j)) .eq. width) then
          call neko_log%warning("Log header may be truncated: " // headers(j))
       end if
       buff = buff // ", " // trim(headers(j))
    end do

    deallocate(headers)
  end subroutine problem_append_log_headers

  !> Return the base log size (excluding iter and optimizer extras).
  !! @param[in] this The problem object.
  !! @param[in] include_constraints Include constraints in the size count.
  !! @return n Number of log entries excluding iteration and optimizer extras.
  function problem_get_log_size(this, include_constraints) result(n)
    class(problem_t), intent(in) :: this
    logical, intent(in), optional :: include_constraints
    integer :: n, i
    logical :: do_constraints

    n = 1
    if (present(include_constraints)) then
       do_constraints = include_constraints
    else
       do_constraints = .true.
    end if
    do i = 1, this%get_n_objectives()
       n = n + this%objective_list(i)%objective%get_log_size()
    end do

    if (do_constraints) then
       do i = 1, this%get_n_constraints()
          n = n + this%constraint_list(i)%constraint%get_log_size()
       end do
    end if

  end function problem_get_log_size
end module problem
