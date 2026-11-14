!> @file freeze_reset_tester.f90
!! Driver asserting that resetting a simulation keeps the `freeze` flags the
!! case file sets, for the fluid and for the adjoint fluid.
!!
!! `simulation_t%reset` runs before every forward run, the first one
!! included, so it must leave both flags as initialisation set them. Neko
!! reads `case.fluid.freeze`. The adjoint fluid reads
!! `case.adjoint_fluid.freeze`, and falls back to `case.fluid.freeze`. A
!! `steady` simulation component freezes the fluid once it has converged, so
!! the reset must also undo a freeze the case did not ask for.
!!
!! Arguments: the case file, then the values to give `case.fluid.freeze` and
!! `case.adjoint_fluid.freeze`, each `true`, `false` or `unset`. The case
!! file itself must set neither key.
program freeze_reset_tester

  use simulation_m, only: simulation_t

  ! Standard modules shared by most of our tests
  use neko, only: neko_init, neko_finalize
  use json_module, only: json_file
  use json_utils_ext, only: json_read_file
  use utils, only: neko_error
  use neko_top, only: neko_top_register_types
  use logger, only: neko_log
  use neko_config, only: NEKO_BCKND_DEVICE
  use device, only: device_memcpy, DEVICE_TO_HOST

  ! Modules specific to this test
  use num_types, only: rp
  use math, only: copy, glmax
  implicit none

  ! JSON related arguments
  integer :: argc
  character(len=256) :: parameter_file, fluid_arg, adjoint_arg
  type(json_file) :: parameters

  !> The simulation we are working with
  type(simulation_t) :: sim

  !> The flags initialisation is to set, from the documented keys.
  logical :: fluid_frozen, adjoint_frozen
  integer :: n, n_failed
  real(kind=rp), allocatable :: u_start(:), u_change(:)
  real(kind=rp) :: change
  character(len=256) :: log_buf

  ! -------------------------------------------------------------------------- !
  ! Initialize the Neko environment

  call neko_init()
  call neko_top_register_types()

  ! -------------------------------------------------------------------------- !
  ! Read the parameters file and the flags to set

  argc = command_argument_count()
  if (argc .lt. 3) then
     call neko_error('Usage: freeze_reset_tester_bin CASE ' // &
          'FLUID_FREEZE ADJOINT_FLUID_FREEZE')
  end if
  call get_command_argument(1, parameter_file)
  call get_command_argument(2, fluid_arg)
  call get_command_argument(3, adjoint_arg)

  parameters = json_read_file(trim(parameter_file))
  call set_flag(parameters, 'case.fluid.freeze', fluid_arg)
  call set_flag(parameters, 'case.adjoint_fluid.freeze', adjoint_arg)

  fluid_frozen = trim(fluid_arg) .eq. 'true'
  if (trim(adjoint_arg) .eq. 'unset') then
     adjoint_frozen = fluid_frozen
  else
     adjoint_frozen = trim(adjoint_arg) .eq. 'true'
  end if

  ! -------------------------------------------------------------------------- !
  ! Check the flags after initialisation and after a reset

  call sim%init(parameters)
  n_failed = 0
  call check_flags('initialisation')

  ! Flip both flags, as a steady component freezing the fluid during the
  ! previous run does, so that the reset has to set them itself.
  sim%neko_case%fluid%freeze = .not. fluid_frozen
  sim%adjoint_case%fluid_adj%freeze = .not. adjoint_frozen
  call sim%reset()
  call check_flags('the reset')

  ! -------------------------------------------------------------------------- !
  ! Check the fluid flag acts: a frozen fluid keeps the velocity the reset
  ! started it from, and a free one does not.

  n = sim%neko_case%fluid%u%size()
  allocate(u_start(n), u_change(n))
  call velocity_to_host()
  call copy(u_start, sim%neko_case%fluid%u%x, n)

  call sim%run_forward()

  call velocity_to_host()
  call copy(u_change, sim%neko_case%fluid%u%x, n)
  u_change = abs(u_change - u_start)
  change = glmax(u_change, n)

  write(log_buf, '(A,E15.7)') 'Largest change of u over the forward run: ', &
       change
  call neko_log%message(trim(log_buf))
  if (fluid_frozen .and. change .gt. 0.0_rp) then
     call neko_log%message('FAIL: the frozen fluid was solved for')
     n_failed = n_failed + 1
  else if (.not. fluid_frozen .and. .not. change .gt. 0.0_rp) then
     call neko_log%message('FAIL: the free fluid was not solved for')
     n_failed = n_failed + 1
  end if

  if (n_failed .gt. 0) then
     call neko_error('The freeze flags were not kept, see the log')
  end if
  call neko_log%message('The freeze flags were kept')

  ! -------------------------------------------------------------------------- !
  ! Clean up

  deallocate(u_start, u_change)
  call sim%free()

  call neko_finalize()

contains

  !> Give a key the value of a command line argument.
  !! @param json The parameters.
  !! @param key The key to set.
  !! @param value `true`, `false`, or `unset` to leave the key out.
  subroutine set_flag(json, key, value)
    type(json_file), intent(inout) :: json
    character(len=*), intent(in) :: key
    character(len=*), intent(in) :: value
    logical :: found

    if (key .in. json) then
       call neko_error('The case file must not set ' // key)
    end if

    select case (trim(value))
    case ('true')
       call json%update(key, .true., found)
    case ('false')
       call json%update(key, .false., found)
    case ('unset')
    case default
       call neko_error('Expected true, false or unset, got ' // trim(value))
    end select
  end subroutine set_flag

  !> Compare both freeze flags with the expected ones, and count a failure
  !! for each that differs.
  !! @param stage What the flags were just set by, for the log.
  subroutine check_flags(stage)
    character(len=*), intent(in) :: stage

    write(log_buf, '(A,L1,A,L1,A,L1,A,L1,A)') 'fluid freeze: ', &
         sim%neko_case%fluid%freeze, ' (expected ', fluid_frozen, &
         '), adjoint fluid freeze: ', sim%adjoint_case%fluid_adj%freeze, &
         ' (expected ', adjoint_frozen, ')'
    call neko_log%message('After ' // stage // ', ' // trim(log_buf))

    if (sim%neko_case%fluid%freeze .neqv. fluid_frozen) then
       call neko_log%message('FAIL: wrong fluid freeze after ' // stage)
       n_failed = n_failed + 1
    end if
    if (sim%adjoint_case%fluid_adj%freeze .neqv. adjoint_frozen) then
       call neko_log%message('FAIL: wrong adjoint fluid freeze after ' // &
            stage)
       n_failed = n_failed + 1
    end if
  end subroutine check_flags

  !> Bring the fluid velocity to the host, on a device backend.
  subroutine velocity_to_host()
    if (NEKO_BCKND_DEVICE .eq. 1) then
       call device_memcpy(sim%neko_case%fluid%u%x, sim%neko_case%fluid%u%x_d, &
            sim%neko_case%fluid%u%size(), DEVICE_TO_HOST, .true.)
    end if
  end subroutine velocity_to_host

end program freeze_reset_tester
