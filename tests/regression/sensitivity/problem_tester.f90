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
  use num_types, only: rp
  use vector, only: vector_t
  use matrix, only: matrix_t
  use math, only: abscmp, copy, glmax
  use comm, only: pe_rank
  use sensitivity, only: compute_sensitivity
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
  real(kind=rp) :: tolerance
  real(kind=rp), parameter :: perturbations(4) = [ &
       1e-1_rp, 1e-2_rp, 1e-3_rp, 1e-4_rp]

  type(vector_t) :: sensitivities
  type(matrix_t) :: constraint_sensitivity

  integer :: i_max
  integer :: i_local
  real(kind=rp) :: local_abs_max, global_abs_max
  real(kind=rp) :: key_local, key_global, key_arr(1)

  ! True => testing an objective, F => testing a constraint
  logical :: is_objective
  character(len=12) :: nobj_str, ncon_str

  ! DIAGNOSTIC MODE (temporary) -- see NEKO_TOP_DBG_PROBE below.
  logical :: probe_mode
  character(len=32) :: probe_env
  integer :: probe_stat, i_probe, i_probe_int, i_probe_face, i_probe_bdry
  real(kind=rp), allocatable :: sel(:), on_bdry(:)
  real(kind=rp) :: probe_bdry_max
  real(kind=rp), parameter :: probe_perturbations(1) = [1e-3_rp]

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
  ! DIAGNOSTIC MODE (temporary, investigate-scalar-adjoint-floor):
  ! NEKO_TOP_DBG_PROBE=1 replaces the single max-sensitivity probe with two
  ! probes -- the highest-sensitivity dof that is *element-interior*
  ! (coef%mult == 1, not shared with any neighbour) and the highest that lies
  ! on an *element interface* (coef%mult < 1). If the FD-vs-adjoint error is
  ! systematically larger on interface dofs, the residual floor is an
  ! interface/mass-matrix assembly problem; if the two are comparable, it is
  ! not. Uses a single perturbation to keep the cost to two extra legs.
  call get_environment_variable('NEKO_TOP_DBG_PROBE', probe_env, &
       status = probe_stat)
  probe_mode = (probe_stat .eq. 0)

  if (probe_mode) then
     allocate(sel(sensitivities%size()))
     allocate(on_bdry(sensitivities%size()))

     ! Mark dofs lying on a physical domain boundary. Built the same way
     ! Neko builds multiplicity: a facet with no neighbour never receives a
     ! contribution from another element, so gather-scattering a field that
     ! is 1 on all *interior-facing* dofs leaves domain-boundary dofs
     ! distinguishable. Here we use the mesh's own boundary facet marking via
     ! the fluid's Dirichlet/known bc masks, which is exact rather than
     ! coordinate-guessed and so also copes with the periodic directions
     ! (y and z here, which must NOT count as boundaries).
     call mark_domain_boundary(sim, on_bdry, sensitivities%size())

     ! --- 1. element-INTERIOR dof: not shared, not on a boundary ---
     do i_probe = 1, sensitivities%size()
        if (abscmp(sim%fluid%c_Xh%mult(i_probe,1,1,1), 1.0_rp) .and. &
             on_bdry(i_probe) .lt. 0.5_rp) then
           sel(i_probe) = abs(sensitivities%x(i_probe))
        else
           sel(i_probe) = 0.0_rp
        end if
     end do
     call pick_owner(sel, sensitivities%size(), i_probe_int)

     ! --- 2. shared element-INTERFACE dof: shared, not on a boundary ---
     do i_probe = 1, sensitivities%size()
        if ((.not. abscmp(sim%fluid%c_Xh%mult(i_probe,1,1,1), 1.0_rp)) .and. &
             on_bdry(i_probe) .lt. 0.5_rp) then
           sel(i_probe) = abs(sensitivities%x(i_probe))
        else
           sel(i_probe) = 0.0_rp
        end if
     end do
     call pick_owner(sel, sensitivities%size(), i_probe_face)

     ! --- 3. domain-BOUNDARY dof ---
     do i_probe = 1, sensitivities%size()
        if (on_bdry(i_probe) .gt. 0.5_rp) then
           sel(i_probe) = abs(sensitivities%x(i_probe))
        else
           sel(i_probe) = 0.0_rp
        end if
     end do
     probe_bdry_max = glmax(sel, sensitivities%size())
     call pick_owner(sel, sensitivities%size(), i_probe_bdry)

     if (pe_rank .eq. 0) then
        write(*, '(A)') 'DBG_PROBE: leg 1 = element-INTERIOR dof (mult==1)'
        write(*, '(A)') 'DBG_PROBE: leg 2 = shared INTERFACE dof (mult<1)'
        write(*, '(A,E15.6)') &
             'DBG_PROBE: leg 3 = domain-BOUNDARY dof, max |sens| = ', &
             probe_bdry_max
        if (probe_bdry_max .le. 0.0_rp) then
           write(*, '(A)') 'DBG_PROBE: WARNING leg 3 carries NO sensitivity' &
                // ' -- the optimization domain does not reach the boundary;' &
                // ' leg 3 is not informative for this case.'
        end if
     end if

     call compute_sensitivity(prob, sim, des, sensitivities, &
          i_probe_int, probe_perturbations, tolerance, &
          trim(parameter_file), is_objective, sim%fluid%gs_Xh)
     call compute_sensitivity(prob, sim, des, sensitivities, &
          i_probe_face, probe_perturbations, tolerance, &
          trim(parameter_file), is_objective, sim%fluid%gs_Xh)
     call compute_sensitivity(prob, sim, des, sensitivities, &
          i_probe_bdry, probe_perturbations, tolerance, &
          trim(parameter_file), is_objective, sim%fluid%gs_Xh)

     deallocate(sel, on_bdry)
  else

  ! -------------------------------------------------------------------------- !
  ! Loop over the perturbations and compare the finite difference estimate with
  ! the sensitivity computed by our method.

  call compute_sensitivity(prob, sim, des, sensitivities, &
       i_max, perturbations, tolerance, trim(parameter_file), is_objective, &
       sim%fluid%gs_Xh)
  end if

  ! -------------------------------------------------------------------------- !
  ! Clean up the components

  call sensitivities%free()
  call constraint_sensitivity%free()

  call prob%free()
  call des%free()
  call sim%free()

  ! Finalize the Neko environment
  call neko_finalize()

contains

  !> DIAGNOSTIC (temporary): mark dofs lying on a physical domain boundary.
  !!
  !! A dof that sits on an element *face* (index 1 or lx/ly/lz in any
  !! direction) but has multiplicity 1 received no contribution from a
  !! neighbouring element during the gather-scatter that builds `mult`, so
  !! there is no element on the other side: it is on a domain boundary.
  !! A face dof with mult < 1 is a shared interface instead -- which correctly
  !! classifies *periodic* faces (y and z here) as interfaces rather than
  !! boundaries, since periodicity connects them to a real neighbour.
  !! Dofs strictly inside the element index range are element-interior.
  !! @param sim The simulation, for the space/mesh/multiplicity.
  !! @param marker Set to 1 on domain-boundary dofs, 0 elsewhere.
  !! @param n Length of `marker`.
  subroutine mark_domain_boundary(sim, marker, n)
    type(simulation_t), intent(inout) :: sim
    real(kind=rp), intent(out) :: marker(:)
    integer, intent(in) :: n
    integer :: e, ii, jj, kk, idx, lx, ly, lz, nelv
    logical :: on_face

    lx = sim%fluid%c_Xh%Xh%lx
    ly = sim%fluid%c_Xh%Xh%ly
    lz = sim%fluid%c_Xh%Xh%lz
    nelv = sim%fluid%c_Xh%msh%nelv

    marker = 0.0_rp
    idx = 0
    do e = 1, nelv
       do kk = 1, lz
          do jj = 1, ly
             do ii = 1, lx
                idx = idx + 1
                if (idx .gt. n) cycle
                on_face = (ii .eq. 1) .or. (ii .eq. lx) .or. &
                     (jj .eq. 1) .or. (jj .eq. ly) .or. &
                     (kk .eq. 1) .or. (kk .eq. lz)
                if (on_face) then
                   if (abscmp(sim%fluid%c_Xh%mult(ii,jj,kk,e), 1.0_rp)) then
                      marker(idx) = 1.0_rp
                   end if
                end if
             end do
          end do
       end do
    end do
  end subroutine mark_domain_boundary

  !> DIAGNOSTIC (temporary): pick the globally-largest entry of `vals` and
  !! return its local index on exactly one rank (-1 on all others), reusing
  !! the same rank tie-break the main path uses. All reductions are collective
  !! and must be reached by every rank.
  !! @param vals Non-negative selection weights (already masked to the dof
  !!             class of interest; zero means "not a candidate").
  !! @param n Length of `vals`.
  !! @param idx Local index on the owning rank, -1 elsewhere.
  subroutine pick_owner(vals, n, idx)
    real(kind=rp), intent(in) :: vals(:)
    integer, intent(in) :: n
    integer, intent(out) :: idx
    integer :: il
    real(kind=rp) :: labs, gabs, kl, kg, karr(1)

    il = maxloc(vals, dim=1)
    labs = vals(il)
    gabs = glmax(vals, n)

    if (abscmp(labs, gabs)) then
       kl = 1.0_rp + 1.0e-12_rp*real(pe_rank, rp)
    else
       kl = 0.0_rp
    end if

    karr(1) = kl
    kg = glmax(karr, 1)
    if (abscmp(kl, kg)) then
       idx = il
    else
       idx = -1
    end if
  end subroutine pick_owner

end program problem_tester
