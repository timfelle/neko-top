!> Shared finite-difference sensitivity checker.
!!
!! This single module is compiled into both the unit driver
!! (`tests/unit/sensitivity/problem_tester.f90`) and the regression driver
!! (`tests/regression/sensitivity/problem_tester.f90`). It contains:
!!  * MPI-safe perturbation/reduction handling (`glsum`, `pe_rank` guards) so it
!!    is correct both single-rank (unit) and multi-rank (regression, `mpirun`).
!!  * A real tolerance assertion on the analytic-vs-finite-difference agreement,
!!    so both lanes actually gate on correctness rather than only logging a CSV.
!!
!! The assertion is made on the *minimum* error over the sweep. The error of a
!! finite-difference estimate is the sum of a truncation term that shrinks with
!! the perturbation (\f$O(\epsilon)\f$ one-sided, \f$O(\epsilon^2)\f$ central)
!! and a round-off/solver-noise term that grows like \f$O(1/\epsilon)\f$, so the
!! error curve is V-shaped and its minimum is the finite-difference floor: the
!! closest agreement the sweep can demonstrate, and the quantity in which a
!! genuine bias (missing coupling term, wrong sign, wrong weighting) shows up.
!! Linear functionals (e.g. the volume constraint) reach that floor at
!! round-off; PDE-coupled objectives reach a discretisation/steady-state floor
!! set by the case.
!!
!! A minimum sitting at either *end* of the sweep is not a floor at all. At
!! the smallest perturbation it only says the sweep stopped before the
!! round-off upturn; at the largest it says the error was still falling as the
!! perturbation grew. Either way the value reported is only a bound on the
!! floor rather than the floor itself, and the sweep states explicitly which
!! outcome it observed, so that a result is never read as tighter than it is.
!!
!! Both the perturbation list and the choice of one-sided or central differences
!! are configurable per case -- see `fd_read_perturbations` and
!! `fd_read_central_difference` -- and default to the historical behaviour.
module sensitivity
  use simulation_m, only: simulation_t
  use design, only: design_t
  use utils, only: neko_error
  use num_types, only: rp
  use math, only: abscmp, NEKO_EPS, glsum
  use vector, only: vector_t
  use neko_config, only: NEKO_BCKND_DEVICE
  use problem, only : problem_t
  use device, only: device_memcpy, DEVICE_TO_HOST, HOST_TO_DEVICE
  use csv_file, only : csv_file_t
  use comm, only: pe_rank
  use gather_scatter, only : gs_t, GS_OP_ADD
  use json_module, only: json_file
  use json_utils, only: json_get
  implicit none

  private :: count_tokens

  !> Status returned by `get_environment_variable` when the value did not fit
  !! in the buffer supplied. Silently accepting a truncated list would run a
  !! different sweep from the one that was asked for.
  integer, parameter :: fd_env_truncated = -1

  !> The historical perturbation sweep: four points spanning three decades.
  !! Used whenever a case supplies no sweep of its own, so that every existing
  !! case file and the CI lane behave exactly as before.
  real(kind=rp), parameter :: fd_default_perturbations(4) = [ &
       1e-1_rp, 1e-2_rp, 1e-3_rp, 1e-4_rp]

  !> Bounds assumed for a design variable. These match the clamping heuristic
  !! the one-sided sweep has always used (perturb downwards once the design
  !! value is past the midpoint) and are what the central-difference sweep
  !! clamps its symmetric half-step against.
  real(kind=rp), parameter :: fd_design_lower = 0.0_rp
  real(kind=rp), parameter :: fd_design_upper = 1.0_rp

  interface compute_sensitivity
     module procedure compute_sensitivity_list, &
          compute_sensitivity_i
  end interface compute_sensitivity

contains

  !> Read the finite-difference perturbation sweep to use for a case.
  !!
  !! Sources, highest precedence first:
  !!  1. the environment variable `NEKO_TOP_FD_PERTURBATIONS`, a comma- or
  !!     space-separated list such as `1e-1,5e-2,1e-2`. This exists because a
  !!     sweep is a property of the *investigation*, not of the case: it lets
  !!     one wide sweep be driven across every case file without editing any
  !!     of them;
  !!  2. the case-file key `optimization.fd_test_perturbations`, a JSON array
  !!     of numbers, sitting beside the existing `fd_test_tolerance`;
  !!  3. `fd_default_perturbations`, the historical four-point sweep.
  !!
  !! Entries are perturbation *magnitudes* and must be strictly positive; the
  !! sign is chosen by the sweep itself so that the perturbed design stays
  !! within its bounds. The list need not be ordered or evenly spaced.
  !!
  !! @param params The case file to read the optional key from.
  !! @param perturbations Allocated and filled with the sweep to use.
  subroutine fd_read_perturbations(params, perturbations)
    type(json_file), intent(inout) :: params
    real(kind=rp), allocatable, intent(out) :: perturbations(:)

    character(len=*), parameter :: env_name = 'NEKO_TOP_FD_PERTURBATIONS'
    !> Characters accepted between values. A blank is included so that
    !! replacing one below is a harmless no-op.
    character(len=*), parameter :: separators = ', ;'
    character(len=1024) :: env_value
    integer :: env_status, n_values, ios, ic

    call get_environment_variable(env_name, env_value, status = env_status)
    if (env_status .eq. fd_env_truncated) then
       call neko_error(env_name // ' is longer than the buffer available ' // &
            'to read it; shorten the sweep or use the case file')
    end if

    if (env_status .eq. 0 .and. len_trim(env_value) .gt. 0) then
       ! Accept commas and semicolons as separators by turning them into the
       ! blanks that list-directed input already understands.
       do ic = 1, len_trim(env_value)
          if (scan(env_value(ic:ic), separators) .gt. 0) then
             env_value(ic:ic) = ' '
          end if
       end do

       n_values = count_tokens(env_value)
       if (n_values .lt. 1) then
          call neko_error(env_name // ' is set but contains no values')
       end if

       allocate(perturbations(n_values))
       ! List-directed input stops quietly at a '/' and expands repeat
       ! counts such as 2*1e-2, both with iostat still zero, leaving any
       ! trailing elements unassigned. Pre-fill with a negative sentinel so
       ! every element the read skips fails the positivity check below
       ! instead of carrying whatever the allocation happened to hold.
       perturbations = -1.0_rp
       read(env_value, *, iostat = ios) perturbations
       if (ios .ne. 0) then
          call neko_error(env_name // ' could not be parsed as a list of ' // &
               'numbers')
       end if

    else if (params%valid_path('optimization.fd_test_perturbations')) then
       call json_get(params, 'optimization.fd_test_perturbations', &
            perturbations)
       ! json-fortran deallocates its result on an exception and Neko's
       ! json_get never checks failed(), so a key of the wrong type comes
       ! back unallocated rather than raising an error.
       if (.not. allocated(perturbations)) then
          call neko_error('optimization.fd_test_perturbations could not ' // &
               'be read as an array of numbers')
       end if
       if (size(perturbations) .lt. 1) then
          call neko_error('optimization.fd_test_perturbations is empty')
       end if

    else
       allocate(perturbations(size(fd_default_perturbations)))
       perturbations = fd_default_perturbations
    end if

    if (any(perturbations .le. 0.0_rp)) then
       call neko_error('Finite-difference perturbations must be strictly ' // &
            'positive magnitudes')
    end if

  end subroutine fd_read_perturbations

  !> Read whether the sweep uses a central rather than a one-sided difference.
  !!
  !! Sources, highest precedence first: the environment variable
  !! `NEKO_TOP_FD_CENTRAL` (true: `1`, `true`, `yes`, `on`; false: `0`,
  !! `false`, `no`, `off`; all case-insensitive, anything else is an error
  !! rather than a silent false that would also silently override the case
  !! file), then the case-file key `optimization.fd_test_central_difference`,
  !! then `.false.` -- the historical one-sided forward difference.
  !!
  !! A central difference has \f$O(\epsilon^2)\f$ truncation error instead of
  !! \f$O(\epsilon)\f$, so it reaches the finite-difference floor at a far
  !! larger perturbation and separates floor from truncation much more
  !! cleanly. It costs two forward solves per perturbation instead of one.
  !!
  !! @param params The case file to read the optional key from.
  !! @param central True to use a central difference.
  subroutine fd_read_central_difference(params, central)
    type(json_file), intent(inout) :: params
    logical, intent(out) :: central

    character(len=*), parameter :: env_name = 'NEKO_TOP_FD_CENTRAL'
    character(len=32) :: env_value
    integer :: env_status, ic

    call get_environment_variable(env_name, env_value, status = env_status)
    if (env_status .eq. fd_env_truncated) then
       call neko_error(env_name // ' is longer than the buffer available ' // &
            'to read it')
    end if

    if (env_status .eq. 0 .and. len_trim(env_value) .gt. 0) then
       do ic = 1, len_trim(env_value)
          if (env_value(ic:ic) .ge. 'A' .and. env_value(ic:ic) .le. 'Z') then
             env_value(ic:ic) = achar(iachar(env_value(ic:ic)) + 32)
          end if
       end do
       ! Strict: a value that is not recognisably true or false must not
       ! quietly mean false -- it would also quietly override the case file.
       select case (trim(adjustl(env_value)))
       case ('1', 'true', 'yes', 'on')
          central = .true.
       case ('0', 'false', 'no', 'off')
          central = .false.
       case default
          call neko_error(env_name // ' must be one of 1/true/yes/on or ' // &
               '0/false/no/off, not "' // trim(adjustl(env_value)) // '"')
       end select
    else if (params%valid_path('optimization.fd_test_central_difference')) then
       call json_get(params, 'optimization.fd_test_central_difference', &
            central)
    else
       central = .false.
    end if

  end subroutine fd_read_central_difference

  !> Count the blank-separated tokens in a string.
  !! @param string The string to inspect.
  !! @return The number of tokens found.
  function count_tokens(string) result(n_tokens)
    character(len=*), intent(in) :: string
    integer :: n_tokens
    integer :: ic, n
    logical :: in_token

    n = len_trim(string)
    n_tokens = 0
    in_token = .false.
    do ic = 1, n
       if (string(ic:ic) .eq. ' ' .or. string(ic:ic) .eq. achar(9)) then
          in_token = .false.
       else if (.not. in_token) then
          in_token = .true.
          n_tokens = n_tokens + 1
       end if
    end do

  end function count_tokens

  !> Sweep a set of perturbations at one design degree of freedom and assert
  !! that the finite-difference estimate agrees with the analytic sensitivity.
  !!
  !! @param problem The problem supplying the objective/constraint value.
  !! @param sim The simulation driving each forward solve.
  !! @param des The design being perturbed.
  !! @param target_sensitivities The analytic sensitivities to check against.
  !! @param i Local index of the dof to perturb, negative on ranks that do not
  !!          own it.
  !! @param perturbations The sweep of perturbation magnitudes, in any order.
  !! @param tolerance The largest acceptable minimum relative error.
  !! @param file_name The case file name, used to name the CSV log.
  !! @param is_objective True to test an objective, false a constraint.
  !! @param gs_h Gather-scatter handle for the design's dofmap. Used to keep a
  !!             perturbed *shared* design dof consistent across every element
  !!             that owns a copy of it -- see `perturb_marker` below.
  !! @param central_difference (Optional) True to use a central difference,
  !!        which halves the truncation order at the cost of a second forward
  !!        solve per perturbation. Defaults to the one-sided forward
  !!        difference used historically.
  subroutine compute_sensitivity_i(problem, sim, des, target_sensitivities, i, &
       perturbations, tolerance, file_name, is_objective, gs_h, &
       central_difference)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    type(vector_t), intent(inout) :: target_sensitivities
    integer, intent(in) :: i
    real(kind=rp), intent(in) :: perturbations(:)
    real(kind=rp), intent(in) :: tolerance
    character(len=*), intent(in) :: file_name
    logical, intent(in) :: is_objective
    type(gs_t), intent(inout) :: gs_h
    logical, intent(in), optional :: central_difference

    character(len=*), parameter :: fmt_head = '(4X,A12,4X,A10,6X,A11,5X,A5,10X)'
    character(len=*), parameter :: fmt_data = '(4X,4E15.6E3)'

    integer :: n_perturbations, ip
    real(kind=rp) :: perturb, work_arr(1)
    real(kind=rp) :: target_sensitivity_i
    type(vector_t) :: design_vector, design_perturbed, log_data, constraint_vec
    real(kind=rp) :: constraint, perturbed_constraint, minus_constraint
    real(kind=rp) :: restored_constraint
    real(kind=rp) :: fd_estimate, fd_error
    real(kind=rp) :: min_error, min_perturb, smallest_perturb, largest_perturb
    real(kind=rp) :: design_value
    real(kind=rp), allocatable :: sweep_perturbs(:), sweep_errors(:)
    logical, allocatable :: usable(:)
    character(len=:), allocatable :: sign_pattern
    character(len=16) :: value_str
    integer :: min_index, i_write, n_crossings
    logical :: sweep_set, central
    type(csv_file_t) :: logger
    integer :: n, slash
    !> Marks every element-local copy of the design dof being perturbed.
    real(kind=rp), allocatable :: perturb_marker(:)
    integer :: j

    central = .false.
    if (present(central_difference)) central = central_difference

    ! Initialize the vectors
    call design_vector%init(des%size())
    call design_perturbed%init(des%size())
    call log_data%init(4)
    call constraint_vec%init(problem%get_n_constraints())

    ! Get the design vector for reference
    ! This is the design vector we will perturb
    call des%get_values(design_vector)

    if (is_objective) then
       call problem%get_objective_value(constraint)
    else
       call problem%get_constraint_values(constraint_vec)
       constraint = constraint_vec%x(1)
    end if

    if (NEKO_BCKND_DEVICE .eq. 1) then
       call device_memcpy(design_vector%x, design_vector%x_d, &
            design_vector%size(), DEVICE_TO_HOST, .true.)
       call device_memcpy(target_sensitivities%x, &
            target_sensitivities%x_d, target_sensitivities%size(), &
            DEVICE_TO_HOST, .true.)
    end if

    ! Mark every element-local copy of the design dof we are about to perturb
    ! (see the detailed note at the perturbation loop below).
    allocate(perturb_marker(des%size()))
    perturb_marker = 0.0_rp
    if (i .ge. 0) perturb_marker(i) = 1.0_rp
    call gs_h%op(perturb_marker, des%size(), GS_OP_ADD)

    ! Get the global target sensitivity by summing the adjoint's value over
    ! *every copy* of the dof.
    !
    ! This has to match how the dof is perturbed. The adjoint stores, at each
    ! element-local index, the derivative with respect to that local copy; it
    ! does not assemble them. Since the perturbation below moves all copies
    ! together (keeping the design single-valued), the matching derivative is
    ! their sum. Measured directly: at a dof shared by two elements, moving
    ! both copies doubles the finite-difference response, and comparing that
    ! against a single copy's derivative reports a spurious ~-95% error while
    ! comparing against the assembled sum reports the same ~2.5% as the
    ! single-copy formulation. For an element-interior dof the sum is over one
    ! entry, so this reduces to the previous behaviour exactly.
    work_arr(1) = 0.0_rp
    do j = 1, des%size()
       if (perturb_marker(j) .gt. 0.5_rp) then
          work_arr(1) = work_arr(1) + target_sensitivities%x(j)
       end if
    end do
    target_sensitivity_i = glsum(work_arr, 1)

    ! Broadcast the design value at the perturbed dof -- only the owning rank
    ! holds it, and it is quoted in the central-difference error message
    ! below, which every rank must be able to compose.
    if (i .ge. 0) then
       work_arr(1) = design_vector%x(i)
    else
       work_arr(1) = 0.0_rp
    end if
    design_value = glsum(work_arr, 1)

    if (i .ge. 0 .and. pe_rank .eq. 0) then
       write(*, '(I0,1X,A,F10.6,1X,A,F10.6,F10.6,F10.6,A)') &
            i, 'Design variable ', design_vector%x(i), &
            'Location [', des%x(i), des%y(i), des%z(i), ']'
       write(*, fmt_head) "Perturbation", "Constraint", "FD Estimate", "Error"
       write(*, fmt_data) 0.0_rp, constraint, target_sensitivity_i, 0.0_rp
    end if

    ! Init the csv writer. Only rank 0 owns the file: under MPI every rank
    ! reaches this code (the surrounding solve is collective), and without
    ! this guard multiple ranks independently opening/writing the same path
    ! is a genuine race — depending on scheduling it can silently clobber
    ! down to one rank's data (usually harmless, since all ranks compute
    ! identical globally-reduced rows) or, observed in practice on a long
    ! (~1000-timestep) run, duplicate every row once per rank.
    !
    ! The passed file name may carry a directory prefix (a stray future
    ! caller might pass one, e.g. 'cases/<name>.case'); strip any leading
    ! directory and the '.case' extension. Today both unit and regression
    ! drivers pass a bare '<name>.case'.
    if (pe_rank .eq. 0) then
       n = len_trim(file_name)
       slash = index(file_name(:n), '/', back = .true.)
       call logger%init('FD_check_'//trim(file_name(slash+1:n-5))//'.csv')
       call logger%set_header('perturbation,F,dFdx,error')
    end if

    n_perturbations = size(perturbations)
    ! Collective-safe: the sweep size is the same on every rank.
    if (n_perturbations .lt. 1) then
       call neko_error('The perturbation sweep is empty')
    end if

    allocate(sweep_perturbs(n_perturbations))
    allocate(sweep_errors(n_perturbations))
    allocate(usable(n_perturbations))
    allocate(character(len=n_perturbations) :: sign_pattern)
    i_write = 0

    do ip = 1, n_perturbations

       ! Decide the step on the owning rank, then broadcast, so that every
       ! rank holding a copy of a shared dof applies the *same* perturbation.
       if (i .ge. 0) then
          if (central) then
             ! A central difference needs room on *both* sides of the design
             ! value, so the symmetric half-step is clamped to whichever bound
             ! is nearer. The alternative -- stepping outside the bounds --
             ! would evaluate a design that does not exist.
             perturb = min(abs(perturbations(ip)), &
                  design_vector%x(i) - fd_design_lower, &
                  fd_design_upper - design_vector%x(i))
          else
             ! Ensure the perturbation stays within the bounds
             perturb = abs(perturbations(ip))
             if (design_vector%x(i) .gt. &
                  0.5_rp * (fd_design_lower + fd_design_upper)) then
                perturb = -perturb
             end if
          end if
          work_arr(1) = perturb
       else
          work_arr(1) = 0.0_rp
       end if
       ! ensure all ranks have the same perturb
       perturb = glsum(work_arr, 1)

       if (central) then
          if (perturb .le. 0.0_rp) then
             ! Note that a design initialised as a 0/1 indicator field -- as
             ! every case in this suite is -- puts *every* dof on a bound, so
             ! this is the normal outcome there rather than a corner case.
             write(value_str, '(F12.6)') design_value
             call neko_error('Central difference impossible: the design ' // &
                  'variable being perturbed is ' // trim(adjustl(value_str)) &
                  // ', on or outside its bounds, so there is no room ' // &
                  'for a symmetric step. Either initialise the design ' // &
                  'strictly inside its bounds, or use the one-sided ' // &
                  'difference ' // &
                  '(unset NEKO_TOP_FD_CENTRAL / set ' // &
                  'fd_test_central_difference false).')
          end if

          ! A half-step clamped far below the requested perturbation no
          ! longer probes the sweep point that was asked for: the design
          ! variable is so close to a bound that the finite difference is
          ! round-off noise at a perturbation nobody requested, and its
          ! error could spuriously become the sweep minimum. Choice made
          ! here: abort rather than silently skip the point, so the sweep
          ! that ran is always the sweep that was requested. Collective-safe:
          ! `perturb` was broadcast above.
          if (perturb .lt. 1e-3_rp * abs(perturbations(ip))) then
             call neko_error('Central-difference half-step clamped below ' // &
                  '1/1000 of the requested perturbation: the design ' // &
                  'variable is too close to a bound for this sweep point ' // &
                  'to be meaningful. Start the sweep at smaller ' // &
                  'perturbations or move the design away from its bounds.')
          end if

          ! A clamped half-step is a different sweep point from the one
          ! requested, so say so rather than let the CSV be read as if the
          ! requested value had been used.
          if (pe_rank .eq. 0 .and. &
               perturb .lt. (1.0_rp - 1e-12_rp)*abs(perturbations(ip))) then
             write(*, '(A,E15.6E3,A,E15.6E3,A)') &
                  ' FD sweep: requested half-step', abs(perturbations(ip)), &
                  ' clamped to', perturb, ' by the design bounds.'
          end if

          i_write = i_write + 1
          call evaluate_perturbed(problem, sim, des, design_vector, &
               design_perturbed, perturb_marker, perturb, is_objective, &
               i_write, constraint_vec, perturbed_constraint)

          i_write = i_write + 1
          call evaluate_perturbed(problem, sim, des, design_vector, &
               design_perturbed, perturb_marker, -perturb, is_objective, &
               i_write, constraint_vec, minus_constraint)

          fd_estimate = perturbed_constraint - minus_constraint
          if (.not. abscmp(fd_estimate, 0.0_rp)) then
             fd_estimate = fd_estimate / (2.0_rp * perturb)
          end if
       else
          i_write = i_write + 1
          call evaluate_perturbed(problem, sim, des, design_vector, &
               design_perturbed, perturb_marker, perturb, is_objective, &
               i_write, constraint_vec, perturbed_constraint)

          fd_estimate = perturbed_constraint - constraint
          if (.not. abscmp(fd_estimate, 0.0_rp)) then
             fd_estimate = fd_estimate / perturb
          end if
       end if

       fd_error = relative_error(fd_estimate, target_sensitivity_i)

       ! The logged `F` is the forward leg in both variants, so the CSV schema
       ! is the same either way.
       if (pe_rank .eq. 0) then
          write(*, fmt_data) perturb, perturbed_constraint, fd_estimate, &
               fd_error
       end if
       if (pe_rank .eq. 0) then
          log_data%x(1) = perturb
          log_data%x(2) = perturbed_constraint
          log_data%x(3) = fd_estimate
          log_data%x(4) = fd_error
          call logger%write(log_data)
       end if

       ! Record the whole sweep; the minimum is selected afterwards, once
       ! sign crossings of the error have been inspected.
       sweep_perturbs(ip) = perturb
       sweep_errors(ip) = fd_error
    end do

    ! Restore the unperturbed design: the loop leaves the last perturbed
    ! design in place, and anything run after this sweep (another probe,
    ! another sweep) must start from the baseline, not from a leftover
    ! perturbation. The zero-step evaluation doubles as a free
    ! reproducibility check: it should reproduce the stored baseline value.
    ! Reported only, never asserted on.
    i_write = i_write + 1
    call evaluate_perturbed(problem, sim, des, design_vector, &
         design_perturbed, perturb_marker, 0.0_rp, is_objective, &
         i_write, constraint_vec, restored_constraint)
    if (pe_rank .eq. 0) then
       write(*, '(A,E15.6E3)') ' FD sweep: baseline restored; ' // &
            're-evaluated functional minus stored baseline =', &
            restored_constraint - constraint
    end if

    ! The relative error is signed, and a biased adjoint whose error
    ! crosses zero inside the sweep would show a spuriously tiny |error|
    ! near the crossing -- a property of where truncation and bias happen
    ! to cancel, not of adjoint accuracy. Detect sign changes between
    ! adjacent sweep points, warn, and exclude the two points around each
    ! crossing from the minimum.
    usable = .true.
    n_crossings = 0
    do ip = 1, n_perturbations - 1
       if (sweep_errors(ip) * sweep_errors(ip+1) .lt. 0.0_rp) then
          n_crossings = n_crossings + 1
          usable(ip) = .false.
          usable(ip+1) = .false.
       end if
    end do

    do ip = 1, n_perturbations
       if (sweep_errors(ip) .ge. 0.0_rp) then
          sign_pattern(ip:ip) = '+'
       else
          sign_pattern(ip:ip) = '-'
       end if
    end do

    if (n_crossings .gt. 0 .and. pe_rank .eq. 0) then
       write(*, '(A,I0,A)') ' FD sweep: WARNING -- the signed error ' // &
            'changes sign ', n_crossings, ' time(s) between adjacent'
       write(*, '(A)') ' FD sweep: WARNING -- sweep points. A near-zero ' // &
            '|error| beside a crossing is spurious (truncation and'
       write(*, '(A)') ' FD sweep: WARNING -- bias cancelling), so the ' // &
            'points adjacent to each crossing are excluded from'
       write(*, '(A)') ' FD sweep: WARNING -- the minimum. Error sign ' // &
            'pattern over the sweep: ' // sign_pattern
    end if

    ! Select the minimum |error| over the usable points. All quantities
    ! involved are globally reduced and identical on every rank, so every
    ! branch below is collective-safe.
    sweep_set = .false.
    min_error = 0.0_rp
    min_perturb = 0.0_rp
    min_index = 0
    do ip = 1, n_perturbations
       if (.not. usable(ip)) cycle
       if (.not. sweep_set .or. abs(sweep_errors(ip)) .lt. abs(min_error)) then
          min_error = sweep_errors(ip)
          min_perturb = sweep_perturbs(ip)
          min_index = ip
          sweep_set = .true.
       end if
    end do

    if (.not. sweep_set) then
       ! Every point sits beside a crossing. Fall back to asserting on the
       ! error at the smallest perturbation -- the historical rule.
       min_index = minloc(abs(sweep_perturbs), dim = 1)
       min_error = sweep_errors(min_index)
       min_perturb = sweep_perturbs(min_index)
       if (pe_rank .eq. 0) then
          write(*, '(A)') ' FD sweep: WARNING -- every sweep point is ' // &
               'adjacent to a sign crossing; falling back to the'
          write(*, '(A)') ' FD sweep: WARNING -- smallest-perturbation ' // &
               'error for the assertion.'
       end if
    end if

    smallest_perturb = minval(abs(sweep_perturbs))
    largest_perturb = maxval(abs(sweep_perturbs))

    call report_sweep(min_error, min_perturb, smallest_perturb, &
         largest_perturb, min_index, n_perturbations)

    ! Assert that the finite-difference estimate reached the analytic
    ! sensitivity *somewhere* in the sweep. The minimum, not the last point, is
    ! the meaningful quantity: at large perturbations truncation dominates and
    ! at small ones round-off does, so any single point is an upper bound on
    ! the agreement the sweep demonstrates. fd_error is built from globally
    ! reduced quantities and is therefore identical on every rank, so this
    ! branch is collective and safe under MPI.
    if (abs(min_error) .gt. tolerance) then
       call neko_error('Finite difference estimate does not match ' // &
            'sensitivity')
    end if

    ! Free the internal vectors
    call design_vector%free()
    call design_perturbed%free()
    call log_data%free()
    call constraint_vec%free()
    deallocate(perturb_marker)
    deallocate(sweep_perturbs, sweep_errors, usable, sign_pattern)

  end subroutine compute_sensitivity_i

  !> Evaluate the objective (or constraint) at a design perturbed by `step` on
  !! every element-local copy of the marked degree of freedom.
  !!
  !! Factored out of the sweep so that the central-difference variant can reuse
  !! it for both the \f$x + h\f$ and \f$x - h\f$ legs.
  !!
  !! The design field is stored per element, (lx, ly, lz, nelv), so a dof on an
  !! element interface has one copy per adjoining element, possibly on
  !! different MPI ranks. Perturbing only the owning index would leave the
  !! design multi-valued at that point, which is not a perturbation of any real
  !! design variable. `perturb_marker` was built by setting the owning entry to
  !! 1 and gather-scattering with GS_OP_ADD -- the same mechanism Neko uses to
  !! propagate values between elements -- so it is non-zero on every copy, on
  !! every rank holding one.
  !!
  !! @param problem The problem supplying the objective/constraint value.
  !! @param sim The simulation driving the forward solve.
  !! @param des The design, updated in place with the perturbed values.
  !! @param design_vector The unperturbed design values.
  !! @param design_perturbed Work vector receiving the perturbed design.
  !! @param perturb_marker Non-zero on every copy of the dof to perturb.
  !! @param step The signed perturbation applied to the marked dofs.
  !! @param is_objective True to read the objective, false the constraint.
  !! @param write_index Output index handed to `sim%write`.
  !! @param constraint_vec Work vector for the constraint values.
  !! @param functional The resulting objective or constraint value.
  subroutine evaluate_perturbed(problem, sim, des, design_vector, &
       design_perturbed, perturb_marker, step, is_objective, write_index, &
       constraint_vec, functional)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    type(vector_t), intent(in) :: design_vector
    type(vector_t), intent(inout) :: design_perturbed
    real(kind=rp), intent(in) :: perturb_marker(:)
    real(kind=rp), intent(in) :: step
    logical, intent(in) :: is_objective
    integer, intent(in) :: write_index
    type(vector_t), intent(inout) :: constraint_vec
    real(kind=rp), intent(out) :: functional

    integer :: j

    ! Reset the design field
    design_perturbed%x = design_vector%x

    ! Apply the step to every copy of the dof, keeping the design
    ! single-valued.
    do j = 1, size(perturb_marker)
       if (perturb_marker(j) .gt. 0.5_rp) then
          design_perturbed%x(j) = design_vector%x(j) + step
       end if
    end do

    if (NEKO_BCKND_DEVICE .eq. 1) then
       call device_memcpy(design_perturbed%x, design_perturbed%x_d, &
            design_perturbed%size(), HOST_TO_DEVICE, .true.)
    end if
    call des%update_design(design_perturbed)

    ! Compute the objective value of the perturbed design
    call problem%compute(des, sim)
    if (is_objective) then
       call problem%get_objective_value(functional)
    else
       call problem%get_constraint_values(constraint_vec)
       functional = constraint_vec%x(1)
    end if
    call sim%write(write_index)
    call sim%reset()

  end subroutine evaluate_perturbed

  !> Report the outcome of a perturbation sweep on rank 0.
  !!
  !! States whether the minimum error is interior to the sweep. If it is, the
  !! error fell and rose again around it and the finite-difference floor has
  !! genuinely been bracketed. If instead the minimum sits at an *end* of the
  !! sweep, nothing was bracketed: at the smallest perturbation the sweep
  !! stopped before the round-off upturn, and at the largest the error was
  !! still falling as the perturbation grew. Either way the number reported
  !! is only a bound on the floor, which must be said rather than left to be
  !! assumed.
  !!
  !! @param min_error The signed relative error at the minimum of the sweep.
  !! @param min_perturb The perturbation at which that minimum occurred.
  !! @param smallest_perturb The smallest perturbation the sweep reached.
  !! @param largest_perturb The largest perturbation the sweep reached.
  !! @param min_index Index into the sweep of the minimum.
  !! @param n_perturbations Number of points in the sweep.
  subroutine report_sweep(min_error, min_perturb, smallest_perturb, &
       largest_perturb, min_index, n_perturbations)
    real(kind=rp), intent(in) :: min_error, min_perturb, smallest_perturb
    real(kind=rp), intent(in) :: largest_perturb
    integer, intent(in) :: min_index, n_perturbations

    logical :: at_smallest, at_largest

    if (pe_rank .ne. 0) return

    write(*, '(A,E15.6E3,A,E15.6E3,A,I0,A,I0,A)') &
         ' FD sweep: minimum |error| of', abs(min_error), &
         ' at perturbation', min_perturb, &
         ' (point ', min_index, ' of ', n_perturbations, ')'

    ! Compared by magnitude rather than by index, so that a sweep whose
    ! perturbations collapse to the same effective value -- which the
    ! central-difference clamping can do -- is not misreported as bracketed.
    at_smallest = abs(min_perturb) .le. abs(smallest_perturb)
    at_largest = abs(min_perturb) .ge. abs(largest_perturb)

    if (at_smallest .and. at_largest) then
       write(*, '(A)') ' FD sweep: NOT BRACKETED -- the sweep has too few' &
            // ' distinct perturbations to bracket a floor at all; the value'
       write(*, '(A)') ' FD sweep: above is a single sample, not a floor.' &
            // ' Sweep several decades of perturbations to bracket one.'
    else if (at_smallest) then
       write(*, '(A)') ' FD sweep: NOT BRACKETED -- the minimum lies at the' &
            // ' smallest perturbation of the sweep, so no round-off upturn'
       write(*, '(A)') ' FD sweep: was observed. The value above is an upper' &
            // ' bound on the finite-difference floor, not the floor itself;'
       write(*, '(A)') ' FD sweep: extend the sweep to smaller perturbations' &
            // ' to bracket it.'
    else if (at_largest) then
       write(*, '(A)') ' FD sweep: NOT BRACKETED -- the minimum lies at the' &
            // ' largest perturbation of the sweep: the error was still'
       write(*, '(A)') ' FD sweep: falling as the perturbation grew, so no' &
            // ' floor was observed and the value above is only a bound on'
       write(*, '(A)') ' FD sweep: it. Extend the sweep to larger' &
            // ' perturbations to bracket the floor.'
    else
       write(*, '(A)') ' FD sweep: BRACKETED -- the error falls and rises' &
            // ' again around the minimum (round-off upturn observed at the'
       write(*, '(A)') ' FD sweep: small end), so the minimum above is a' &
            // ' genuine finite-difference floor.'
    end if

  end subroutine report_sweep

  !> Sweep the perturbations at each of a list of design degrees of freedom.
  !!
  !! @param problem The problem supplying the objective/constraint value.
  !! @param sim The simulation driving each forward solve.
  !! @param des The design being perturbed.
  !! @param target_sensitivities The analytic sensitivities to check against.
  !! @param list Local indices of the dofs to perturb.
  !! @param perturbations The sweep of perturbation magnitudes.
  !! @param tolerance The largest acceptable minimum relative error.
  !! @param file_name The case file name, used to name the CSV log.
  !! @param is_objective True to test an objective, false a constraint.
  !! @param gs_h Gather-scatter handle for the design's dofmap.
  !! @param central_difference (Optional) True to use a central difference.
  subroutine compute_sensitivity_list(problem, sim, des, target_sensitivities, &
       list, perturbations, tolerance, file_name, is_objective, gs_h, &
       central_difference)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    type(vector_t), intent(inout) :: target_sensitivities
    integer, dimension(:), intent(in) :: list
    real(kind=rp), dimension(:), intent(in) :: perturbations
    real(kind=rp), intent(in) :: tolerance
    character(len=*), intent(in) :: file_name
    logical, intent(in) :: is_objective
    type(gs_t), intent(inout) :: gs_h
    logical, intent(in), optional :: central_difference

    integer :: i, n

    n = size(list)
    do i = 1, n
       call compute_sensitivity_i(problem, sim, des, target_sensitivities, &
            list(i), perturbations, tolerance, file_name, is_objective, gs_h, &
            central_difference)
    end do
  end subroutine compute_sensitivity_list

  !> Computes the relative difference between two numbers
  !! \f$ \frac{a - b}{|b|} \f$
  function relative_error(a, b) result(err)
    real(kind=rp), intent(in) :: a, b
    real(kind=rp) :: err

    err = (a - b) / max(abs(b), NEKO_EPS)

  end function relative_error

end module sensitivity
