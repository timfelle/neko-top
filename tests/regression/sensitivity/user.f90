! User module for the user defined simulation component
module user
  use user_intf, only: user_t
  use json_module, only: json_file
  use steady_simcomp, only: steady_simcomp_t
  use simcomp_executor, only: neko_simcomps
  use num_types, only : rp
  use field, only : field_t
  use field_list, only : field_list_t
  use field_dirichlet, only : field_dirichlet_t
  use time_state, only : time_state_t
  use utils, only : nonlinear_index
  use registry, only : neko_registry
  use math, only : rzero, copy, chsign
  use device_math, only: device_copy, device_cmult
  use neko_config, only: NEKO_BCKND_DEVICE
  use operators, only: curl
  use scratch_registry, only : neko_scratch_registry
  use device, only: HOST_TO_DEVICE, device_memcpy
  implicit none
  !> Case parameters
  ! To define the initial boundary conditions we don't wish to introduce a
  ! discontinuity,
  !
  !    DONT                    DO (but smoother)
  !        _______               ______
  !       |                     /
  !       |                    /
  ! -------             -------
  !
  ! hence,
  !> we use a logistic function defined by
  !! $ \frac{L}{1 + exp{-k(z-z_0)}}$
  real(kind=rp), parameter :: L = 1.0_rp
  real(kind=rp), parameter :: k = 20.0_rp
  real(kind=rp), parameter :: y_0 = 0.5_rp
  real(kind=rp), parameter :: pi = acos(-1.0_rp)

contains

  ! Register user-defined functions (see user_intf.f90)
  subroutine user_setup(user)
    type(user_t), intent(inout) :: user
    user%dirichlet_conditions => user_bc
    user%initial_conditions => scalar_ic
  end subroutine user_setup

  !> user-defined boundary condition
  subroutine user_bc(fields, bc, time)
    type(field_list_t), intent(inout) :: fields
    type(field_dirichlet_t), intent(in) :: bc
    type(time_state_t), intent(in) :: time
    type(field_t), pointer :: u, v, w, s
    real(kind=rp) :: x, y, z
    integer :: i, idx(4)
    logical :: is_fluid

    is_fluid = (fields%items(1)%ptr%name .eq. 'u')

    if (is_fluid) then
       u => fields%get("u")
       v => fields%get("v")
       w => fields%get("w")

       do i = 1, bc%msk(0)
          idx = nonlinear_index(bc%msk(i), u%Xh%lx, u%Xh%ly, u%Xh%lz)
          x = u%dof%x%x(idx(1), idx(2), idx(3), idx(4))
          y = u%dof%y%x(idx(1), idx(2), idx(3), idx(4))
          z = u%dof%z%x(idx(1), idx(2), idx(3), idx(4))

          ! Inflow velocity is uniform
          u%x(idx(1), idx(2), idx(3), idx(4)) = 1.0_rp
          v%x(idx(1), idx(2), idx(3), idx(4)) = 0.0_rp
          w%x(idx(1), idx(2), idx(3), idx(4)) = 0.0_rp
       end do

       if (NEKO_BCKND_DEVICE .eq. 1) then
          call device_memcpy(u%x, u%x_d, u%size(), HOST_TO_DEVICE, sync=.false.)
          call device_memcpy(v%x, v%x_d, v%size(), HOST_TO_DEVICE, sync=.false.)
          call device_memcpy(w%x, w%x_d, w%size(), HOST_TO_DEVICE, sync=.true.)
       end if

    else
       s => fields%get("s")

       do i = 1, bc%msk(0)
          idx = nonlinear_index(bc%msk(i), s%Xh%lx, s%Xh%ly, s%Xh%lz)
          y = s%dof%y%x(idx(1), idx(2), idx(3), idx(4))
          ! Inflow scalar profile is a bump
          s%x(idx(1), idx(2), idx(3), idx(4)) = &
               0.5_rp * (1.0_rp - cos(2.0_rp*pi*y))
       end do
       if (NEKO_BCKND_DEVICE .eq. 1) then
          call device_memcpy(s%x, s%x_d, s%size(), HOST_TO_DEVICE, sync=.true.)
       end if
    end if
  end subroutine user_bc

  !> user-defined initial condition
  subroutine scalar_ic(scheme_name, fields)
    character(len=*), intent(in) :: scheme_name
    type(field_list_t), intent(inout) :: fields
    type(field_t), pointer :: s

    if (scheme_name .eq. 'fluid') return

    ! Initial scalar profile is a bump
    s => fields%get("s")
    s%x = 0.5_rp * (1.0_rp - cos(2.0_rp*pi*s%dof%y%x))

    if (NEKO_BCKND_DEVICE .eq. 1) then
       call device_memcpy(s%x, s%x_d, s%size(), HOST_TO_DEVICE, sync=.true.)
    end if
  end subroutine scalar_ic

end module user
