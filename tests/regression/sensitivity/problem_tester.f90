program problem_tester

  use simulation_m, only: simulation_t
  use brinkman_design, only: brinkman_design_t
  use problem, only : problem_t

  ! Standard modules shared by most of our tests
  use json_module, only: json_file
  use json_utils, only: json_get, json_get_or_default
  use json_utils_ext, only: json_read_file
  use utils, only: neko_error
  use neko_top, only: neko_top_register_types
  use neko, only: neko_init, neko_finalize
  use mask_ops, only: mask_exterior_const
  use neko_config, only: NEKO_BCKND_DEVICE
  use device, only: device_memcpy, DEVICE_TO_HOST

  ! Modules specific to this test
  use num_types, only: rp, i8
  use vector, only: vector_t
  use matrix, only: matrix_t
  use math, only: abscmp, copy, glmax
  use comm, only: pe_rank
  use sensitivity, only: compute_sensitivity, &
       compute_sensitivity_directional, fd_read_perturbations, &
       fd_read_central_difference, fd_read_mode, fd_read_probe_index, &
       fd_resolve_probe_index
  use user, only: user_setup
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
  ! optional JSON key `optimization.fd_test_tolerance`; it defaults to a value
  ! appropriate for the fully steady-state-converged regression cases.
  !
  ! The perturbation sweep, the one-sided/central choice and the dof/directional
  ! mode are likewise optional per case (`optimization.fd_test_perturbations`,
  ! `optimization.fd_test_central_difference` and `optimization.fd_test_mode`,
  ! each also overridable from the environment for a sweep driven across
  ! several cases at once), and default to the historical four-point one-sided
  ! single-dof sweep. See `fd_read_perturbations`, `fd_read_central_difference`
  ! and `fd_read_mode` in tests/shared/sensitivity.f90.
  real(kind=rp) :: tolerance
  real(kind=rp), allocatable :: perturbations(:)
  logical :: use_central
  !> True to perturb the whole design along the normalised sensitivity
  !! direction (the Taylor test) rather than probing a single dof.
  logical :: fd_directional
  !> A fixed global design index to probe, from NEKO_TOP_FD_PROBE_INDEX. The
  !! default probe is the argmax of |sensitivity|, which *moves* whenever the
  !! sensitivity field moves, so two runs of the same case can otherwise
  !! silently differentiate with respect to two different design variables.
  integer(kind=i8) :: probe_dof
  logical :: probe_dof_set

  type(vector_t) :: sensitivities
  type(matrix_t) :: constraint_sensitivity

  integer :: i_max
  integer :: i_local
  real(kind=rp) :: local_abs_max, global_abs_max
  real(kind=rp) :: key_local, key_global, key_arr(1)

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
       tolerance, 1e-3_rp)
  call fd_read_perturbations(parameters, perturbations)
  call fd_read_central_difference(parameters, use_central)
  call fd_read_mode(parameters, fd_directional)
  call fd_read_probe_index(probe_dof, probe_dof_set)

  ! -------------------------------------------------------------------------- !
  ! Initialization of the components

  call user_setup(sim%neko_case%user)
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
     call constraint_sensitivity%init(des%size(), prob%get_n_constraints())

     call prob%get_constraint_sensitivities(constraint_sensitivity)

     call sensitivities%init(constraint_sensitivity%size())

     call copy(sensitivities%x, constraint_sensitivity%x, &
          constraint_sensitivity%size())
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

  i_local = maxloc(abs(sensitivities%x), dim=1)
  local_abs_max = abs(sensitivities%x(i_local))
  global_abs_max = glmax(abs(sensitivities%x), sensitivities%size()) ! DEVICE?

  ! rank-based tie-breaker: only those within eps of the global max get key=1
  if (abscmp(local_abs_max, global_abs_max)) then
     key_local = 1.0_rp + 1.0e-12_rp*real(pe_rank, rp)
  else
     key_local = 0.0_rp
  end if

  ! reduce the key to pick a single owner
  key_arr(1) = key_local
  key_global = glmax(key_arr, 1)
  if (abscmp(key_local, key_global)) then
     i_max = i_local
  else
     i_max = -1 ! to indicate that this proc doesn't participate
  end if

  ! -------------------------------------------------------------------------- !
  ! Loop over the perturbations and compare the finite difference estimate with
  ! the sensitivity computed by our method.

  ! Override the argmax probe with an explicitly named design dof, if one was
  ! requested. This is what makes two runs comparable: the argmax above moves
  ! whenever the sensitivity field moves, so two runs of the same case can
  ! otherwise silently differentiate with respect to two different design
  ! variables. The global design index to use is printed by every run (the
  ! 'FD probe' line), so pinning one run to another is a copy-paste.
  if (probe_dof_set) then
     if (fd_directional) then
        if (pe_rank .eq. 0) then
           write(*, '(A)') ' FD probe: WARNING -- NEKO_TOP_FD_PROBE_INDEX ' // &
                'is set but the mode is directional, which perturbs'
           write(*, '(A)') ' FD probe: WARNING -- every design dof at once. ' &
                // 'The requested dof is ignored.'
        end if
     else
        call fd_resolve_probe_index(des%size(), probe_dof, i_max)
     end if
  end if

  if (fd_directional) then
     ! Perturb the whole design along s = g/||g|| and compare against <g, s>.
     ! Validates the entire gradient field in one sweep rather than one
     ! argmax-selected component of it.
     call compute_sensitivity_directional(prob, sim, des, sensitivities, &
          perturbations, tolerance, trim(parameter_file), is_objective, &
          sim%fluid%gs_Xh, use_central)
  else
     call compute_sensitivity(prob, sim, des, sensitivities, &
          i_max, perturbations, tolerance, trim(parameter_file), &
          is_objective, sim%fluid%gs_Xh, use_central)
  end if

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

end program problem_tester
