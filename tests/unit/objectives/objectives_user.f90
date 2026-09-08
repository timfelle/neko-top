!> @file objectives_user.f90
!! User-defined scalar inflow for the objective time-window tests.
!!
!! Restores the scalar setup `examples/time_test` used before it became these
!! tests, and matches `examples/unsteady_mixer`, this suite's reference
!! physics: two species split either side of a smooth interface enter the
!! duct and leave through the outlet, with every other face insulated for
!! the scalar.
!!
!! The velocity side of `examples/time_test` (a paraboloid inflow, no-slip
!! walls) is deliberately *not* restored here. These tests instead use a
!! uniform freestream velocity, expressed entirely in the case file via
!! `velocity_value` (see the readme), so this module carries no velocity
!! routine at all -- only the scalar Dirichlet inflow and initial condition,
!! which are unaffected by that substitution.
!!
!! The conversion to unit tests originally replaced the scalar inflow with a
!! zero-flux condition on all six faces plus a `point_zone` initial blob;
!! that was reverted in favour of the example's actual scalar setup.
module objectives_user
  use num_types, only: rp
  use field, only: field_t
  use field_list, only: field_list_t
  use field_dirichlet, only: field_dirichlet_t
  use time_state, only: time_state_t
  use user_intf, only: user_t
  use neko_config, only: NEKO_BCKND_DEVICE
  use device, only: HOST_TO_DEVICE, DEVICE_TO_HOST, device_memcpy
  implicit none
  private

  public :: objectives_user_setup

  !> Amplitude of the inflow split.
  real(kind=rp), parameter :: split_amplitude = 1.0_rp
  !> Steepness of the split.
  !!
  !! The example used 200 on a 32x8x8 mesh at polynomial order 5. These tests
  !! run on a coarser mesh at order 3, which puts far fewer points across the
  !! split direction, so 200 would be a step function in all but name and
  !! would ring. 20 spreads the transition over roughly a fifth of the
  !! height, which this mesh resolves; see the readme for the exact point
  !! count.
  real(kind=rp), parameter :: split_steepness = 20.0_rp
  !> Height at which the two species meet.
  real(kind=rp), parameter :: split_height = 0.5_rp

contains

  !> Register the user routines on a case's `user_t`.
  !!
  !! Must be called before the case is initialized: `user_intf_init` only
  !! substitutes its own defaults for pointers that are still null, so
  !! anything assigned here survives.
  !! @param user The user interface to populate.
  subroutine objectives_user_setup(user)
    type(user_t), intent(inout) :: user

    user%dirichlet_conditions => scalar_inflow
    user%initial_conditions => scalar_initial_condition
  end subroutine objectives_user_setup

  !> The scalar concentration at a point, as a smooth split in `z`.
  !! @param z Height.
  !! @return The concentration.
  pure function split_profile(z) result(phi)
    real(kind=rp), intent(in) :: z
    real(kind=rp) :: phi

    phi = split_amplitude / &
         (1.0_rp + exp(-split_steepness * (z - split_height)))
  end function split_profile

  !> Impose the scalar split on the inlet boundary.
  !!
  !! The only `user_dirichlet` boundary any case in this directory declares
  !! is the scalar inlet, so this is never called for velocity.
  !! @param fields The fields the boundary condition applies to.
  !! @param bc The boundary condition, carrying the mask.
  !! @param time The current time state.
  subroutine scalar_inflow(fields, bc, time)
    type(field_list_t), intent(inout) :: fields
    type(field_dirichlet_t), intent(in) :: bc
    type(time_state_t), intent(in) :: time
    type(field_t), pointer :: s
    integer :: i, idx

    if (fields%items(1)%ptr%name .ne. 's') return

    s => fields%get("s")
    call s%copy_from(DEVICE_TO_HOST, sync = .true.)

    do i = 1, bc%msk(0)
       idx = bc%msk(i)
       s%x(idx, 1, 1, 1) = split_profile(s%dof%z(idx, 1, 1, 1))
    end do

    call s%copy_from(HOST_TO_DEVICE, sync = .true.)
    nullify(s)
  end subroutine scalar_inflow

  !> Start the scalar from the same split the inflow imposes.
  !!
  !! Starting anywhere else only adds a transient the run then has to sit
  !! through before it can converge.
  !! @param scheme_name The scheme requesting an initial condition.
  !! @param fields The fields to initialize.
  subroutine scalar_initial_condition(scheme_name, fields)
    character(len=*), intent(in) :: scheme_name
    type(field_list_t), intent(inout) :: fields
    type(field_t), pointer :: s
    integer :: i

    if (scheme_name .eq. 'fluid') return

    s => fields%get("s")
    do i = 1, s%dof%size()
       s%x(i, 1, 1, 1) = split_profile(s%dof%z(i, 1, 1, 1))
    end do

    if (NEKO_BCKND_DEVICE .eq. 1) then
       call device_memcpy(s%x, s%x_d, s%size(), HOST_TO_DEVICE, sync = .false.)
    end if
    nullify(s)
  end subroutine scalar_initial_condition

end module objectives_user
