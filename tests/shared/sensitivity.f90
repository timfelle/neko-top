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
!! The assertion is deliberately made on the error at the *smallest*
!! perturbation. For a one-sided forward difference the error at large
!! perturbations is dominated by truncation (\f$O(\epsilon)\f$) and must not be
!! asserted against; only as the perturbation shrinks does the estimate approach
!! the analytic sensitivity, exposing any genuine bias (missing coupling term,
!! wrong sign, wrong weighting) as a non-vanishing floor. Linear functionals
!! (e.g. the volume constraint) hit that floor at round-off; PDE-coupled
!! objectives hit a discretisation/steady-state floor set by the case.
!!
!! An unsteady problem is differentiated on a frozen time grid:
!! `freeze_time_grid` freezes the grid of the baseline run, which every
!! perturbed run then replays, and `unfreeze_time_grid` drops it again.
module sensitivity
  use simulation_m, only: simulation_t
  use design, only: design_t
  use utils, only: neko_error
  use num_types, only: rp, dp
  use time_step_controller, only: time_step_controller_t, LANDING_TOL
  use math, only: abscmp, NEKO_EPS, glsum
  use vector, only: vector_t
  use neko_config, only: NEKO_BCKND_DEVICE
  use problem, only : problem_t
  use device, only: device_memcpy, DEVICE_TO_HOST, HOST_TO_DEVICE
  use csv_file, only : csv_file_t
  use comm, only: pe_rank
  implicit none

  interface compute_sensitivity
     module procedure compute_sensitivity_list, &
          compute_sensitivity_i
  end interface compute_sensitivity

contains

  subroutine compute_sensitivity_i(problem, sim, des, target_sensitivities, i, &
       perturbations, tolerance, file_name, is_objective)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    type(vector_t), intent(inout) :: target_sensitivities
    integer, intent(in) :: i
    real(kind=rp), intent(in) :: perturbations(:)
    real(kind=rp), intent(in) :: tolerance
    character(len=*), intent(in) :: file_name
    logical, intent(in) :: is_objective

    character(len=*), parameter :: fmt_head = '(4X,A12,4X,A10,6X,A11,5X,A5,10X)'
    character(len=*), parameter :: fmt_data = '(4X,4E15.6E3)'

    integer :: n_perturbations, ip
    real(kind=rp) :: perturb, work_arr(1)
    real(kind=rp) :: target_sensitivity_i
    type(vector_t) :: design_vector, design_perturbed, log_data, constraint_vec
    real(kind=rp) :: constraint, perturbed_constraint
    real(kind=rp) :: fd_estimate, fd_error
    real(kind=rp) :: floor_error, floor_perturb
    logical :: floor_set
    type(csv_file_t) :: logger
    integer :: n, slash

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

    ! Get global target sensitivity. Only the owning rank (i >= 0) holds the
    ! entry; every other rank contributes zero to the reduction so all ranks
    ! end up with the same global value.
    if (i .ge. 0) then
       work_arr(1) = target_sensitivities%x(i)
    else
       work_arr(1) = 0.0_rp
    end if
    target_sensitivity_i = glsum(work_arr, 1)

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

    floor_set = .false.
    floor_error = 0.0_rp
    floor_perturb = 0.0_rp

    n_perturbations = size(perturbations)
    do ip = 1, n_perturbations
       perturb = perturbations(ip)

       ! Reset the design field
       design_perturbed%x = design_vector%x
       ! only one rank perturbs, we assume i < 0 implies this rank doesn't
       if (i .ge. 0) then
          ! Ensure the perturbation stays within the bounds
          if (design_vector%x(i) .gt. 0.5_rp) perturb = -perturb
          design_perturbed%x(i) = design_vector%x(i) + perturb
          work_arr(1) = perturb
       else
          work_arr(1) = 0.0_rp
       end if
       ! ensure all ranks have the same perturb
       perturb = glsum(work_arr, 1)

       if (NEKO_BCKND_DEVICE .eq. 1) then
          call device_memcpy(design_perturbed%x, design_perturbed%x_d, &
               design_perturbed%size(), HOST_TO_DEVICE, .true.)
       end if
       call des%update_design(design_perturbed)

       ! Compute the objective value of the perturbed design
       call problem%compute(des, sim)
       if (is_objective) then
          call problem%get_objective_value(perturbed_constraint)
       else
          call problem%get_constraint_values(constraint_vec)
          perturbed_constraint = constraint_vec%x(1)
       end if
       call sim%write(ip)
       call sim%reset()

       fd_estimate = perturbed_constraint - constraint
       if (.not. abscmp(fd_estimate, 0.0_rp)) then
          fd_estimate = fd_estimate / perturb
       end if

       fd_error = relative_error(fd_estimate, target_sensitivity_i)

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

       ! Track the error at the smallest-magnitude perturbation: this is the
       ! Taylor floor the analytic sensitivity must converge to.
       if (.not. floor_set .or. abs(perturb) .lt. abs(floor_perturb)) then
          floor_perturb = perturb
          floor_error = fd_error
          floor_set = .true.
       end if
    end do

    ! Assert that the finite-difference estimate has converged to the analytic
    ! sensitivity at the smallest perturbation. fd_error is built from globally
    ! reduced quantities and is therefore identical on every rank, so this
    ! branch is collective and safe under MPI.
    if (abs(floor_error) .gt. tolerance) then
       call neko_error('Finite difference estimate does not match ' // &
            'sensitivity')
    end if

    ! Free the internal vectors
    call design_vector%free()
    call design_perturbed%free()
    call log_data%free()
    call constraint_vec%free()

  end subroutine compute_sensitivity_i

  subroutine compute_sensitivity_list(problem, sim, des, target_sensitivities, &
       list, perturbations, tolerance, file_name, is_objective)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    type(vector_t), intent(inout) :: target_sensitivities
    integer, dimension(:), intent(in) :: list
    real(kind=rp), dimension(:), intent(in) :: perturbations
    real(kind=rp), intent(in) :: tolerance
    character(len=*), intent(in) :: file_name
    logical, intent(in) :: is_objective

    integer :: i, n

    n = size(list)
    do i = 1, n
       call compute_sensitivity_i(problem, sim, des, target_sensitivities, &
            list(i), perturbations, tolerance, file_name, is_objective)
    end do
  end subroutine compute_sensitivity_list

  !> Freeze the time grid of the baseline run of an unsteady problem, so that
  !! every perturbed run replays it.
  !! @details The adjoint of an unsteady problem differentiates the objective
  !! on the time grid of the forward run, so the finite differences have to
  !! compare runs on that grid too. A case with a variable time step has to
  !! vary it, or it tests nothing a fixed time step does not: its frozen grid
  !! must hold at least two different time steps, and the first one must not
  !! be the placeholder of 1 of Neko's time state. Call it after the baseline
  !! run, before the simulation is reset. A steady problem keeps no time
  !! grid and is left alone.
  !! @param sim The simulation, after its baseline run.
  subroutine freeze_time_grid(sim)
    type(simulation_t), intent(inout) :: sim
    type(time_step_controller_t) :: dt_controller
    real(kind=dp), allocatable :: distinct(:)
    real(kind=dp) :: dt
    integer :: n, n_distinct, k

    if (.not. sim%unsteady) return

    call sim%state_recover%freeze_time_grid()

    call sim%init_dt_controller(dt_controller)
    if (.not. dt_controller%is_variable_dt) return

    n = sim%state_recover%get_n_timesteps()
    allocate(distinct(n))
    n_distinct = 0
    do k = 1, n
       dt = sim%state_recover%get_prescribed_dt(k)
       if (any(abs(distinct(1:n_distinct) - dt) .le. LANDING_TOL * dt)) cycle
       n_distinct = n_distinct + 1
       distinct(n_distinct) = dt
    end do

    if (pe_rank .eq. 0) then
       write(*, '(A,I0,A,I0,A)') 'Frozen time grid: ', n, ' steps, ', &
            n_distinct, ' distinct time steps'
       write(*, '(4X,ES24.16)') distinct(1:n_distinct)
    end if

    if (n_distinct .lt. 2 .or. &
         abscmp(sim%state_recover%get_prescribed_dt(1), 1.0_dp)) then
       call neko_error('The case varies the time step, but its time ' // &
            'grid holds a single time step or starts from the ' // &
            'placeholder of 1')
    end if

    deallocate(distinct)
  end subroutine freeze_time_grid

  !> Drop the time grid frozen by `freeze_time_grid`.
  !! @param sim The simulation.
  subroutine unfreeze_time_grid(sim)
    type(simulation_t), intent(inout) :: sim

    if (.not. sim%unsteady) return
    call sim%state_recover%unfreeze_time_grid()
  end subroutine unfreeze_time_grid

  !> Computes the relative difference between two numbers
  !! \f$ \frac{a - b}{|b|} \f$
  function relative_error(a, b) result(err)
    real(kind=rp), intent(in) :: a, b
    real(kind=rp) :: err

    err = (a - b) / max(abs(b), NEKO_EPS)

  end function relative_error

end module sensitivity
