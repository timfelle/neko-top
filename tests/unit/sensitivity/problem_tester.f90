program problem_tester

  use simulation_m, only: simulation_t
  use brinkman_design, only: brinkman_design_t
  use problem, only : problem_t

  ! Standard modules shared by most of our tests
  use neko, only: neko_init, neko_finalize
  use json_module, only: json_file
  use json_utils, only: json_get, json_get_or_default
  use json_utils_ext, only: json_read_file
  use utils, only: neko_error
  use neko_top, only: neko_top_register_types
  use mask_ops, only: mask_exterior_const
  use neko_config, only: NEKO_BCKND_DEVICE
  use device, only: device_memcpy, DEVICE_TO_HOST

  ! Modules specific to this test
  use num_types, only: rp
  use vector, only: vector_t
  use matrix, only: matrix_t
  use math, only: abscmp, copy
  use device_math, only: device_copy
  use sensitivity, only: compute_sensitivity, fd_read_strict_options, &
       fd_read_perturbations, fd_assertion_skipped, FD_SKIP_EXIT_CODE
  use fd_criterion, only: fd_strict_options_t
  implicit none

  ! JSON related arguments
  integer :: argc
  character(len=256) :: parameter_file
  type(json_file) :: parameters, design_parameters

  !> The simulation we are working with
  type(simulation_t) :: sim
  !> The design type
  type(brinkman_design_t) :: des
  !> The problem type
  type(problem_t) :: prob

  ! Test specific variables. The tolerance may be overridden per case via the
  ! optional JSON key `optimization.fd_test_tolerance`; it defaults to a tight
  ! round-off floor suited to linear functionals (e.g. the volume constraint).
  ! PDE-coupled objectives, whose finite-difference floor is set by the
  ! discretisation/steady-state, set a looser value in their case file.
  real(kind=rp) :: tolerance
  !> The sweep this tier has always run. Kept as the default so that the
  !! logged CSVs stay comparable run to run; the strict criterion asks for a
  !! geometric sweep instead, because its order estimate is a statement about
  !! successive ratios and these alternate 5, 2, 5, 2.
  real(kind=rp), parameter :: default_perturbations(8) = [ &
       5e-1_rp, 1e-1_rp, 5e-2_rp, 1e-2_rp, 5e-3_rp, 1e-3_rp, 5e-4_rp, 1e-4_rp]
  real(kind=rp), allocatable :: perturbations(:)
  !> Settings of the strict assertion criterion. Disabled unless the case
  !! file asks for it, so the historical assertion stays the default.
  type(fd_strict_options_t) :: strict_options

  type(vector_t) :: sensitivities
  type(matrix_t) :: constraint_sensitivity

  integer :: i_max

  ! True => testing an objective, F => testing a constraint
  logical :: is_objective
  character(len=12) :: nobj_str, ncon_str

  ! -------------------------------------------------------------------------- !
  ! Initialize the Neko environment

  call neko_init()
  call neko_top_register_types()

  ! -------------------------------------------------------------------------- !
  ! Read the parameters file as the first terminal argument

  argc = command_argument_count()
  if (argc .lt. 1) call neko_error('Missing parameter file')
  call get_command_argument(1, parameter_file)

  ! Read the parameters file
  parameters = json_read_file(trim(parameter_file))
  call json_get(parameters, 'optimization.design', design_parameters)
  call json_get_or_default(parameters, 'optimization.fd_test_tolerance', &
       tolerance, 1e-5_rp)

  ! This tier always takes a one-sided difference, hence the .false.
  call fd_read_strict_options(parameters, .false., strict_options)
  if (strict_options%enabled) then
     call fd_read_perturbations(parameters, .true., perturbations)
  else
     allocate(perturbations(size(default_perturbations)))
     perturbations = default_perturbations
  end if

  ! -------------------------------------------------------------------------- !
  ! Initialization of the components

  call sim%init(parameters)
  call des%init(design_parameters, sim)
  call prob%init(parameters, des, sim)

  ! -------------------------------------------------------------------------- !
  ! Determine if objective or constraint
  if ((prob%get_n_objectives() .gt. 0) .and. &
       (prob%get_n_constraints() .eq. 0)) then
     is_objective = .true.
  else if (prob%get_n_constraints() .eq. 1) then
     ! note we always have a dummy objective
     is_objective = .false.
  else
     write(nobj_str, '(I0)') prob%get_n_objectives()
     write(ncon_str, '(I0)') prob%get_n_constraints()
     call neko_error("Specify a) a single constraint b) multiple " // &
          "objectives. You have" // nobj_str // &
          "objectives and " // ncon_str // " constraints.")
  end if

  ! -------------------------------------------------------------------------- !
  ! Compute the sensitivity with our method

  call prob%compute(des, sim)
  call prob%compute_sensitivity(des, sim)
  if (is_objective) then
     call sensitivities%init(des%size())
     call des%get_sensitivity(sensitivities)
  else
     call constraint_sensitivity%init(prob%get_n_constraints(), des%size())
     call prob%get_constraint_sensitivities(constraint_sensitivity)
     call sensitivities%init(constraint_sensitivity%size())
     if (NEKO_BCKND_DEVICE .eq. 1) then
        call device_copy(sensitivities%x_d, constraint_sensitivity%x_d, &
             constraint_sensitivity%size())
     else
        call copy(sensitivities%x, constraint_sensitivity%x, &
             constraint_sensitivity%size())
     end if
  end if

  call des%convert_to_directional_derivative(sensitivities)

  call des%write(1)
  ! --------------------------------------
  ! Reset the simulation
  call sim%reset()

  if (NEKO_BCKND_DEVICE .eq. 1) then
     call device_memcpy(sensitivities%x, &
          sensitivities%x_d, sensitivities%size(), &
          DEVICE_TO_HOST, .true.)
  end if

  i_max = maxloc(abs(sensitivities%x), dim=1)

  ! -------------------------------------------------------------------------- !
  ! Loop over the perturbations and compare the finite difference estimate with
  ! the sensitivity computed by our method.

  call compute_sensitivity(prob, sim, des, sensitivities, &
       i_max, perturbations, tolerance, trim(parameter_file), is_objective, &
       sim%fluid%gs_Xh, strict_options = strict_options)

  ! -------------------------------------------------------------------------- !
  ! Clean up the components

  if (allocated(perturbations)) deallocate(perturbations)

  call sensitivities%free()
  call constraint_sensitivity%free()

  call prob%free()
  call des%free()
  call sim%free()

  ! Finalize the Neko environment
  call neko_finalize()

  ! A build that skipped the assertion made no gradient check at all, and a
  ! zero exit would be reported by CTest as a pass. Exit with the skip code
  ! instead -- `SKIP_RETURN_CODE` in this test's CMakeLists turns it into a
  ! reported SKIP.
  if (fd_assertion_skipped()) stop FD_SKIP_EXIT_CODE

end program problem_tester
