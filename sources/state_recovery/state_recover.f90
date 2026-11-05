!> @file state_recover.f90
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
!
!> @brief Abstract interface for state recovery strategies.
!!
!! @par Factory API
!! `state_recover_factory(recover, neko_case, params)` allocates a recovery
!! implementation selected by the `type` entry in `params`, initializes it,
!! and associates it with `neko_case`. The allocatable `recover` argument is
!! replaced if it is already allocated.
!!
!! `state_recover_allocator(recover, recover_type)` only allocates the
!! implementation selected by `recover_type`; the caller remains responsible
!! for initializing it. The allocatable `recover` argument is replaced if it
!! is already allocated.
module state_recover
  use num_types, only: dp
  use case, only: case_t
  use json_file_module, only: json_file
  use time_state, only: time_state_t
  use utils, only: neko_error
  implicit none
  private

  !> Number of steps the time grid has room for at first. The grid doubles
  !! whenever a run takes more steps.
  integer, parameter :: TIME_GRID_INITIAL_CAPACITY = 64

  !> Abstract base type for state recovery implementations.
  !!
  !! @details Besides the states, which the implementations store, the base
  !! type records the time grid of the forward run: the time of every saved
  !! state and the time step that produced it. The grid is replicated on
  !! every rank and holds a few scalars per step. A copy of it can be frozen
  !! as a prescribed grid, which later runs replay step by step and which a
  !! `reset` leaves in place.
  type, abstract, public :: state_recover_t
     private
     !> Case associated with this recovery strategy at initialization.
     class(case_t), pointer, public :: neko_case => null()
     !> Number of states recorded by this recovery strategy.
     integer :: n_timesteps = 0
     !> Times of the recorded states, \f$ t_0 \f$ to \f$ t_N \f$.
     real(kind=dp), allocatable :: t_hist(:)
     !> Time steps that produced the recorded states, \f$ \Delta t_1 \f$ to
     !! \f$ \Delta t_N \f$.
     real(kind=dp), allocatable :: dt_hist(:)
     !> The time step of the time state before the first step.
     real(kind=dp) :: dt0 = 0.0_dp
     !> The time-step history before the first step, as the first step
     !! used it.
     real(kind=dp) :: dtlag0(10) = 0.0_dp
     !> The time history before the first step, as the first step used it.
     real(kind=dp) :: tlag0(10) = 0.0_dp
     !> Whether the time state before the first step has been recorded.
     logical :: initial_time_recorded = .false.
     !> Time steps of a frozen time grid, replayed by later runs.
     real(kind=dp), allocatable :: prescribed_dt(:)
   contains
     procedure(state_recover_init), pass(this), public, deferred :: init
     procedure(state_recover_free), pass(this), public, deferred :: free
     procedure(state_recover_reset), pass(this), public, deferred :: reset
     procedure(state_recover_save), pass(this), public, deferred :: save
     procedure(state_recover_restore), pass(this), public, deferred :: restore
     procedure, pass(this), public :: get_n_timesteps => &
          state_recover_get_n_timesteps
     procedure, pass(this), public :: set_n_timesteps => &
          state_recover_set_n_timesteps
     !> Free the time grid, for the `free` of the implementations.
     procedure, pass(this), public, non_overridable :: free_base => &
          state_recover_free_base
     !> Clear the time grid, for the `reset` of the implementations.
     procedure, pass(this), public, non_overridable :: reset_base => &
          state_recover_reset_base
     !> Record the time of the state with the current index.
     procedure, pass(this), public, non_overridable :: record_time => &
          state_recover_record_time
     !> Time of a recorded state.
     procedure, pass(this), public, non_overridable :: get_time => &
          state_recover_get_time
     !> Time step that produced a recorded state.
     procedure, pass(this), public, non_overridable :: get_dt => &
          state_recover_get_dt
     !> Time of the last recorded state.
     procedure, pass(this), public, non_overridable :: get_end_time => &
          state_recover_get_end_time
     !> Time state as Neko had it after a recorded step.
     procedure, pass(this), public, non_overridable :: get_time_state => &
          state_recover_get_time_state
     !> Number of steps the time grid has room for.
     procedure, pass(this), public, non_overridable :: time_grid_capacity => &
          state_recover_time_grid_capacity
     !> Freeze the recorded time grid as the prescribed grid.
     procedure, pass(this), public, non_overridable :: freeze_time_grid => &
          state_recover_freeze_time_grid
     !> Drop the prescribed grid.
     procedure, pass(this), public, non_overridable :: unfreeze_time_grid => &
          state_recover_unfreeze_time_grid
     !> Whether a prescribed grid is set.
     procedure, pass(this), public, non_overridable :: has_prescribed_grid => &
          state_recover_has_prescribed_grid
     !> Time step of a step of the prescribed grid.
     procedure, pass(this), public, non_overridable :: get_prescribed_dt => &
          state_recover_get_prescribed_dt
  end type state_recover_t

  abstract interface
     !> Initialize state recovery from JSON parameters.
     !! @param[inout] this State recovery instance.
     !! @param[inout] neko_case Case data structure.
     !! @param[inout] params JSON parameters.
     subroutine state_recover_init(this, neko_case, params)
       import state_recover_t, case_t, json_file
       class(state_recover_t), intent(inout) :: this
       class(case_t), target, intent(inout) :: neko_case
       type(json_file), intent(inout) :: params
     end subroutine state_recover_init

     !> Free state recovery resources.
     !! @param[inout] this State recovery instance.
     subroutine state_recover_free(this)
       import state_recover_t
       class(state_recover_t), intent(inout) :: this
     end subroutine state_recover_free

     !> Reset state recovery bookkeeping.
     !! @param[inout] this State recovery instance.
     subroutine state_recover_reset(this)
       import state_recover_t
       class(state_recover_t), intent(inout) :: this
     end subroutine state_recover_reset

     !> Save forward state for recovery.
     !! @details Saved before the first step, at time step 0, the state is
     !! the initial condition, restored as state 0. Saved after a step, it is
     !! the next state. Either way its time is recorded.
     !! @param[inout] this State recovery instance.
     subroutine state_recover_save(this)
       import state_recover_t
       class(state_recover_t), intent(inout) :: this
     end subroutine state_recover_save

     !> Restore forward state for adjoint.
     !! @param[inout] this State recovery instance.
     !! @param[in] tstep Timestep to restore, 0 for the initial condition.
     subroutine state_recover_restore(this, tstep)
       import state_recover_t
       class(state_recover_t), intent(inout) :: this
       integer, intent(in) :: tstep
     end subroutine state_recover_restore
  end interface

  interface
     ! Construct and initialize a state recovery object from JSON parameters.
     module subroutine state_recover_factory(recover, neko_case, params)
       class(state_recover_t), allocatable, intent(inout) :: recover
       class(case_t), target, intent(inout) :: neko_case
       type(json_file), intent(inout) :: params
     end subroutine state_recover_factory
  end interface

  public :: state_recover_factory

contains

  !> Get the number of states recorded by this recovery strategy.
  !! @param[in] this State recovery instance.
  pure function state_recover_get_n_timesteps(this) result(n)
    class(state_recover_t), intent(in) :: this
    integer :: n

    n = this%n_timesteps
  end function state_recover_get_n_timesteps

  !> Set the number of states recorded by this recovery strategy.
  !! @param[inout] this State recovery instance.
  !! @param[in] n Number of recorded states.
  subroutine state_recover_set_n_timesteps(this, n)
    class(state_recover_t), intent(inout) :: this
    integer, intent(in) :: n

    this%n_timesteps = n
  end subroutine state_recover_set_n_timesteps

  ! ========================================================================== !
  ! Time grid

  !> Free the time grid, including the prescribed grid, and the counters.
  !! @param[inout] this State recovery instance.
  subroutine state_recover_free_base(this)
    class(state_recover_t), intent(inout) :: this

    if (allocated(this%t_hist)) deallocate(this%t_hist)
    if (allocated(this%dt_hist)) deallocate(this%dt_hist)
    if (allocated(this%prescribed_dt)) deallocate(this%prescribed_dt)

    this%n_timesteps = 0
    this%dt0 = 0.0_dp
    this%dtlag0 = 0.0_dp
    this%tlag0 = 0.0_dp
    this%initial_time_recorded = .false.
    nullify(this%neko_case)
  end subroutine state_recover_free_base

  !> Clear the recorded time grid for a new run. The capacity and the
  !! prescribed grid are kept.
  !! @param[inout] this State recovery instance.
  subroutine state_recover_reset_base(this)
    class(state_recover_t), intent(inout) :: this

    this%n_timesteps = 0
    this%dt0 = 0.0_dp
    this%dtlag0 = 0.0_dp
    this%tlag0 = 0.0_dp
    this%initial_time_recorded = .false.
  end subroutine state_recover_reset_base

  !> Record the time of the state with the current index, the number of
  !! recorded states, 0 for the state before the first step.
  !! @details State \f$ i \f$ is recorded right after step \f$ i \f$, when
  !! `time` holds \f$ t_i \f$ and the step \f$ \Delta t_i \f$ that produced
  !! it. State 0 is recorded before the first step, with the time state the
  !! run starts from. The history the first step used is taken from the
  !! time state after it, which is the history before it except that Neko
  !! replaces the second entry by the first step when the time scheme starts
  !! from order zero.
  !! @param[inout] this State recovery instance.
  !! @param[in] time The time state of the run.
  subroutine state_recover_record_time(this, time)
    class(state_recover_t), intent(inout) :: this
    type(time_state_t), intent(in) :: time
    integer :: n

    n = this%n_timesteps
    call state_recover_ensure_capacity(this, n)
    this%t_hist(n) = time%t

    if (n .eq. 0) then
       this%dt0 = time%dt
       this%dtlag0 = time%dtlag
       this%tlag0 = time%tlag
       this%initial_time_recorded = .true.
       return
    end if

    this%dt_hist(n) = time%dt
    if (n .eq. 1) then
       this%t_hist(0) = time%tlag(1)
       this%dtlag0(1:9) = time%dtlag(2:10)
       this%tlag0(1:9) = time%tlag(2:10)
    end if
  end subroutine state_recover_record_time

  !> Make room in the time grid for state `n`, doubling the capacity.
  !! @param[inout] this State recovery instance.
  !! @param[in] n Index of the state to record.
  subroutine state_recover_ensure_capacity(this, n)
    class(state_recover_t), intent(inout) :: this
    integer, intent(in) :: n
    real(kind=dp), allocatable :: t_tmp(:), dt_tmp(:)
    integer :: capacity, old_capacity

    if (.not. allocated(this%dt_hist)) then
       capacity = max(TIME_GRID_INITIAL_CAPACITY, n)
       allocate(this%t_hist(0:capacity))
       allocate(this%dt_hist(capacity))
       this%t_hist = 0.0_dp
       this%dt_hist = 0.0_dp
       return
    end if

    old_capacity = size(this%dt_hist)
    if (n .le. old_capacity) return

    capacity = max(2 * old_capacity, n)
    allocate(t_tmp(0:capacity))
    allocate(dt_tmp(capacity))
    t_tmp = 0.0_dp
    dt_tmp = 0.0_dp
    t_tmp(0:old_capacity) = this%t_hist
    dt_tmp(1:old_capacity) = this%dt_hist
    call move_alloc(t_tmp, this%t_hist)
    call move_alloc(dt_tmp, this%dt_hist)
  end subroutine state_recover_ensure_capacity

  !> Stop with an error if state `i` has no recorded time.
  !! @param[in] this State recovery instance.
  !! @param[in] i Index of the state.
  !! @param[in] first Smallest valid index.
  subroutine state_recover_check_index(this, i, first)
    class(state_recover_t), intent(in) :: this
    integer, intent(in) :: i, first
    character(len=256) :: msg
    integer :: lowest

    lowest = first
    if (lowest .eq. 0 .and. this%n_timesteps .eq. 0 .and. &
         .not. this%initial_time_recorded) lowest = 1

    if (i .lt. lowest .or. i .gt. this%n_timesteps) then
       write(msg, '(A,I0,A,I0,A,I0,A)') "No recorded time for state ", i, &
            ", recorded are [", lowest, ", ", this%n_timesteps, "]"
       call neko_error(trim(msg))
    end if
  end subroutine state_recover_check_index

  !> Time of a recorded state.
  !! @param[in] this State recovery instance.
  !! @param[in] i Index of the state, 0 for the initial condition.
  !! @return \f$ t_i \f$.
  function state_recover_get_time(this, i) result(t)
    class(state_recover_t), intent(in) :: this
    integer, intent(in) :: i
    real(kind=dp) :: t

    call state_recover_check_index(this, i, 0)
    t = this%t_hist(i)
  end function state_recover_get_time

  !> Time step that produced a recorded state.
  !! @param[in] this State recovery instance.
  !! @param[in] i Index of the state, from 1.
  !! @return \f$ \Delta t_i = t_i - t_{i-1} \f$, as the run took it.
  function state_recover_get_dt(this, i) result(dt)
    class(state_recover_t), intent(in) :: this
    integer, intent(in) :: i
    real(kind=dp) :: dt

    call state_recover_check_index(this, i, 1)
    dt = this%dt_hist(i)
  end function state_recover_get_dt

  !> Time of the last recorded state.
  !! @param[in] this State recovery instance.
  !! @return \f$ t_N \f$.
  function state_recover_get_end_time(this) result(t)
    class(state_recover_t), intent(in) :: this
    real(kind=dp) :: t

    t = this%get_time(this%n_timesteps)
  end function state_recover_get_end_time

  !> Time state as Neko had it after a recorded step.
  !! @details Fills `t`, `dt`, `tstep` and the histories `dtlag` and `tlag`
  !! of `time`, leaving its start and end time as they are. After step
  !! \f$ i \f$ the histories are \f$ \Delta t_{i-j+1} \f$ and
  !! \f$ t_{i-j} \f$ for \f$ j \le i \f$ and the history before the first
  !! step beyond that.
  !! @param[in] this State recovery instance.
  !! @param[in] i Index of the state, 0 for the state before the first step.
  !! @param[inout] time The time state to fill.
  subroutine state_recover_get_time_state(this, i, time)
    class(state_recover_t), intent(in) :: this
    integer, intent(in) :: i
    type(time_state_t), intent(inout) :: time
    integer :: j

    call state_recover_check_index(this, i, 0)
    if (i .eq. 0 .and. .not. this%initial_time_recorded) then
       call neko_error("The time state before the first step was not " // &
            "recorded")
    end if

    time%tstep = i
    time%t = this%t_hist(i)
    if (i .eq. 0) then
       time%dt = this%dt0
    else
       time%dt = this%dt_hist(i)
    end if

    do j = 1, size(time%dtlag)
       if (j .le. i) then
          time%dtlag(j) = this%dt_hist(i - j + 1)
          time%tlag(j) = this%t_hist(i - j)
       else
          time%dtlag(j) = this%dtlag0(j - i)
          time%tlag(j) = this%tlag0(j - i)
       end if
    end do
  end subroutine state_recover_get_time_state

  !> Number of steps the time grid has room for before it grows.
  !! @param[in] this State recovery instance.
  !! @return The number of steps, 0 before the first state is recorded.
  pure function state_recover_time_grid_capacity(this) result(capacity)
    class(state_recover_t), intent(in) :: this
    integer :: capacity

    capacity = 0
    if (allocated(this%dt_hist)) capacity = size(this%dt_hist)
  end function state_recover_time_grid_capacity

  !> Freeze the time steps of the recorded grid as the prescribed grid, which
  !! later runs replay and a `reset` keeps.
  !! @param[inout] this State recovery instance.
  subroutine state_recover_freeze_time_grid(this)
    class(state_recover_t), intent(inout) :: this

    if (this%n_timesteps .lt. 1) then
       call neko_error("There is no recorded time grid to freeze")
    end if

    if (allocated(this%prescribed_dt)) deallocate(this%prescribed_dt)
    allocate(this%prescribed_dt(this%n_timesteps))
    this%prescribed_dt = this%dt_hist(1:this%n_timesteps)
  end subroutine state_recover_freeze_time_grid

  !> Drop the prescribed grid, so that runs choose their time steps again.
  !! @param[inout] this State recovery instance.
  subroutine state_recover_unfreeze_time_grid(this)
    class(state_recover_t), intent(inout) :: this

    if (allocated(this%prescribed_dt)) deallocate(this%prescribed_dt)
  end subroutine state_recover_unfreeze_time_grid

  !> Whether a prescribed grid is set.
  !! @param[in] this State recovery instance.
  !! @return `.true.` from `freeze_time_grid` until `unfreeze_time_grid`.
  pure function state_recover_has_prescribed_grid(this) result(has_grid)
    class(state_recover_t), intent(in) :: this
    logical :: has_grid

    has_grid = allocated(this%prescribed_dt)
  end function state_recover_has_prescribed_grid

  !> Time step of a step of the prescribed grid.
  !! @param[in] this State recovery instance.
  !! @param[in] n Index of the step, from 1.
  !! @return \f$ \Delta t_n \f$ of the frozen grid.
  function state_recover_get_prescribed_dt(this, n) result(dt)
    class(state_recover_t), intent(in) :: this
    integer, intent(in) :: n
    real(kind=dp) :: dt
    character(len=256) :: msg

    if (.not. allocated(this%prescribed_dt)) then
       call neko_error("No prescribed time grid is set")
    end if
    if (n .lt. 1 .or. n .gt. size(this%prescribed_dt)) then
       write(msg, '(A,I0,A,I0,A)') "Step ", n, &
            " is past the prescribed time grid of ", &
            size(this%prescribed_dt), " steps"
       call neko_error(trim(msg))
    end if

    dt = this%prescribed_dt(n)
  end function state_recover_get_prescribed_dt

end module state_recover
