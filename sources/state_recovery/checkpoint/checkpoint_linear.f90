!> @file checkpoint_linear.f90
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

!> Implementation for the Linear Checkpointing algorithm.
!! In this case, we save the state of the simulation every `n_saves_memory`
!! time steps. When restoring to a given time step, we load the nearest
!! checkpoint and then we fill our cache with the following
!! `n_saves_memory` time steps. Finally, we copy the required time step from
!! our cache.
!!
!! This algorithm is the simplest one and do a minimum of re-computation. But
!! requires large amounts of memory and disk space.
submodule (state_recover_checkpoint) checkpoint_linear
  use num_types, only: dp
  use simulation, only: simulation_restart
  use simcomp_executor, only: neko_simcomps
  use time_state, only: time_state_t
  use time_scheme_controller, only: time_scheme_controller_t
  use time_step_controller, only: time_step_controller_t
  use profiler, only: profiler_start_region, profiler_end_region

contains

  !> Save the current state of the simulation in a linear fashion.
  !! We save every `n_saves_memory` time steps to disc and we always save
  !! any timestep leading up to the `first_valid_timestep` time steps to disc.
  module subroutine checkpoint_save_linear(this)
    class(state_recover_checkpoint_t), intent(inout) :: this
    integer :: index, tstep, counter, n_total
    real(kind=rp) :: time, start_time, end_time, dt

    time = this%neko_case%time%t
    dt = this%neko_case%time%dt
    tstep = this%neko_case%time%tstep
    start_time = this%neko_case%time%start_time
    end_time = this%neko_case%time%end_time

    ! We save to disc only every n_saves_memory time steps
    index = modulo(tstep, this%n_saves_memory)
    if (index .eq. 0 .or. tstep .le. this%first_valid_timestep) then
       this%loaded_checkpoint = tstep

       counter = determine_counter(tstep, this%n_saves_memory, &
            this%first_valid_timestep)

       call this%chkp_output%set_counter(counter)
       call profiler_start_region("Checkpoint write to disk")
       call this%chkp_output%sample(time)
       call profiler_end_region("Checkpoint write to disk")
       this%n_saves_disc = this%n_saves_disc + 1
    end if

    ! Only save to RAM from the last disc checkpoint to the end of the forward
    ! simulation. With fixed timesteps, the total count and the last disc-save
    ! timestep are known from the time object.
    ! Note: the plus 0.5 is to round up to the next integer, as the division can
    ! be slightly smaller than the actual number of steps due to floating point
    ! errors.
    n_total = int(((end_time - start_time) / dt) + 0.5_rp)
    if (tstep .ge. n_total - modulo(n_total, this%n_saves_memory)) then
       call this%save_data(index + 1)
    end if

  end subroutine checkpoint_save_linear

  !> Restore the forward simulation state in a linear fashion.
  !! If the requested time step is not in memory, we load the nearest
  !! checkpoint from disc and then we step forward in time to fill our cache.
  !! Finally, we copy the requested time step from our cache.
  !! @details The steps forward repeat those of the forward run, without the
  !! simulation components' `compute`, the user's `compute` and the output,
  !! see `checkpoint_recompute_step`. The fluid is frozen in them as it was in
  !! the forward run. The case is restarted from the checkpoint file at the
  !! time step of the file, so that the schedules in time steps of the
  !! simulation components restart from it.
  !! @param this The checkpoint object.
  !! @param tstep The time step to restore.
  module subroutine checkpoint_restore_linear(this, tstep)
    class(state_recover_checkpoint_t), intent(inout) :: this
    integer, intent(in) :: tstep
    type(time_step_controller_t) :: dt_controller
    integer :: k, previous_save, next_save, local_idx, counter

    ! Determine the nearest save states on both sides
    previous_save = tstep - modulo(tstep, this%n_saves_memory)
    next_save = previous_save + this%n_saves_memory

    ! Before the first valid state we always load from disc and we do not step
    ! forward in time.
    if (tstep .lt. this%first_valid_timestep) then
       previous_save = tstep
       next_save = previous_save + 1
    else if (previous_save .lt. this%first_valid_timestep) then
       previous_save = this%first_valid_timestep
    end if

    ! Load a new batch of checkpoints if needed
    if (this%loaded_checkpoint .ne. previous_save) then

       ! Restart the simulation form the checkpoint file
       counter = determine_counter(previous_save, this%n_saves_memory, &
            this%first_valid_timestep)
       call this%chkp_output%set_counter(counter)
       call profiler_start_region("Checkpoint read from disk")
       call this%chkp_output%file_%read(this%neko_case%chkp)
       call profiler_end_region("Checkpoint read from disk")

       ! The checkpoint file holds no time step, and the restart anchors the
       ! schedules in time steps at the current one, so it is set first
       this%neko_case%time%tstep = previous_save
       call simulation_restart(this%neko_case, this%neko_case%chkp)

       ! Initialize the time step controller
       call dt_controller%init(this%neko_case%params)
       this%loaded_checkpoint = this%neko_case%time%tstep

       call profiler_start_region("Checkpoint recompute")
       ! Step through the simulation and store field states in memory
       do k = previous_save, min(next_save - 1, this%get_n_timesteps())

          ! Do not run simulation step on the first iteration
          if (k .ne. previous_save) then
             if (this%neko_case%time%is_done()) exit
             call checkpoint_recompute_step(this%neko_case, dt_controller)
          end if

          ! Freeze the fluid, or not, as after this step of the forward run
          this%neko_case%fluid%freeze = this%fluid_frozen(k)

          ! Save the restored state in memory
          local_idx = modulo(k, this%n_saves_memory) + 1
          call this%save_data(local_idx)
       end do
       call profiler_end_region("Checkpoint recompute")
    end if

    ! Restore the required time step from memory
    local_idx = modulo(tstep, this%n_saves_memory) + 1
    call this%load_data(local_idx)
  end subroutine checkpoint_restore_linear

  !> Take a time step of the forward run again, to recompute its state.
  !! @details This is the time step of Neko's `simulation_step` up to the end
  !! of the fluid and scalar steps. What follows them there, the simulation
  !! components' `compute`, the user's `compute` and the output, ran on the
  !! step in the forward run, and must not run on it again: the output would
  !! be written twice and statistics would count the step twice, and the
  !! `steady` component, which compares the state with the one it last
  !! computed on, would freeze the fluid on finding a state it has seen
  !! already. The freezes of the forward run are set by the caller instead.
  !! Any other result of a `compute` that the next step reads is stale in
  !! the recompute.
  !!
  !! What prepares the step, the user's and the simulation components'
  !! `preprocess`, runs again. An LES model, for one, computes there the eddy
  !! viscosity the turbulent diffusivity of a scalar can depend on, through
  !! `alphat.nut_dependency`. In the fluid an eddy viscosity needs the full
  !! stress formulation, which the adjoint rejects. The user's `preprocess`
  !! must depend on the time state, not on how often it is called. A
  !! component's schedule in time steps is restarted from the checkpoint
  !! file's time step, so it is that of the forward run with a value of 1 or
  !! one that divides that time step, and is shifted against it otherwise.
  !! Neko's LPT component advances its particles in its `preprocess`, so they
  !! are advanced once more. They do not act on the flow, but their state
  !! means nothing after the backward sweep.
  !!
  !! Newer versions of Neko also fit the time step to the next output time in
  !! `simulation_step` (`land`), with `exact_output_time`, which requires a
  !! variable time step. Unsteady problems reject one, so that is left out.
  !! @param neko_case The case.
  !! @param dt_controller The time-step controller.
  subroutine checkpoint_recompute_step(neko_case, dt_controller)
    type(case_t), intent(inout) :: neko_case
    type(time_step_controller_t), intent(inout) :: dt_controller
    real(kind=dp) :: cfl

    cfl = neko_case%fluid%compute_cfl(neko_case%time%dt)
    call dt_controller%set_dt(neko_case%time, cfl)
    call checkpoint_recompute_settime(neko_case%time, neko_case%fluid%ext_bdf)

    call neko_case%time%status()
    call neko_log%begin()

    call neko_case%user%preprocess(neko_case%time)
    call neko_simcomps%preprocess(neko_case%time)

    call neko_log%section('Fluid')
    call neko_case%fluid%step(neko_case%time, dt_controller)
    call neko_log%end_section()

    if (allocated(neko_case%scalars)) then
       call neko_log%section('Scalar')
       call neko_case%scalars%step(neko_case%time, neko_case%fluid%ext_bdf, &
            dt_controller)
       call neko_log%end_section()
    end if

    call neko_log%end()
  end subroutine checkpoint_recompute_step

  !> Advance the time by one time step, as `simulation_step` does. This is a
  !! copy of `simulation_settime`, which is private to Neko's `simulation`
  !! module. A difference between the two would show as a difference between
  !! the recomputed states and those of the forward run.
  !! @param time The time state.
  !! @param ext_bdf The time scheme of the fluid.
  subroutine checkpoint_recompute_settime(time, ext_bdf)
    type(time_state_t), intent(inout) :: time
    type(time_scheme_controller_t), allocatable, intent(inout) :: ext_bdf
    integer :: i

    do i = 10, 2, -1
       time%tlag(i) = time%tlag(i-1)
       time%dtlag(i) = time%dtlag(i-1)
    end do

    time%dtlag(1) = time%dt
    time%tlag(1) = time%t

    if (allocated(ext_bdf)) then
       if (ext_bdf%ndiff .eq. 0) then
          time%dtlag(2) = time%dt
          time%tlag(2) = time%t
       end if

       call ext_bdf%set_coeffs(real(time%dtlag, kind=rp))
    end if

    time%tstep = time%tstep + 1
    time%t = time%t + time%dt
  end subroutine checkpoint_recompute_settime

  pure function determine_counter(tstep, n_memory, first) result(counter)
    integer, intent(in) :: tstep, n_memory, first
    integer :: counter

    if (tstep .le. first) then
       counter = tstep
    else
       counter = first + tstep / n_memory
    end if

  end function determine_counter

end submodule checkpoint_linear
