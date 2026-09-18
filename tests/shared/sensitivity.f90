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
!!
!! The sweep can differentiate along either of two directions, selected by
!! `fd_read_mode`:
!!  * `dof` (the default, historical) perturbs one design degree of freedom and
!!    compares against the assembled derivative at that dof. Which dof that is
!!    is now always reported, because the caller's usual choice -- the
!!    largest-|sensitivity| dof -- *moves* whenever the sensitivity field
!!    moves, so two runs of the same case can otherwise silently differentiate
!!    with respect to two different design variables;
!!  * `directional` perturbs the *whole* design along a normalised direction
!!    \f$s\f$ and compares against the projection \f$\langle g, s\rangle\f$ of
!!    the gradient onto it. It raises the finite-difference signal by roughly
!!    \f$\|g\|/|g_i|\f$ relative to a single dof, which buys back round-off
!!    headroom.
!!
!! Both go through one perturbation code path (`fd_run_sweep` and
!! `evaluate_perturbed`, which take a direction vector); the single-dof probe
!! is the one-hot special case of it, so the two cannot drift apart.
!!
!! **What a directional sweep does and does not cover.** A directional sweep
!! tests exactly one scalar contraction of the gradient field, \f$\langle
!! g, s\rangle\f$, so which \f$s\f$ is used decides what it can see. With
!! \f$s = g/\|g\|\f$ -- the default, `fd_read_direction` returning `gradient`
!! -- the direction is built from the gradient being tested, so writing the
!! computed gradient as \f$g = G + \delta\f$ for a true \f$G\f$ gives
!! projection \f$= \|g\|\f$, finite difference \f$\approx \langle G, s\rangle
!! = \|g\| - \langle \delta, s\rangle\f$ and hence relative error
!! \f$-\langle \delta, g\rangle/\|g\|^2\f$. **Any gradient error orthogonal to
!! \f$g\f$ therefore passes that sweep exactly.** It is sound for a sign error
!! (a flip reports \f$-2\f$) and for a global scale error (a factor two
!! reports \f$-0.5\f$), and it is not degenerate in the other direction --
!! \f$\langle g,s\rangle = \|g\|\f$ is asserted, not merely printed -- but it
!! is one contraction, along \f$g\f$ itself, and not "the whole gradient
!! field".
!!
!! `fd_read_direction` returning `random` instead builds \f$s\f$ from a seeded
!! pseudo-random field, assembled and normalised exactly as the gradient
!! direction is. Its blind spot is a different one: it is a single random
!! contraction, so it misses an error that happens to be orthogonal to *that*
!! draw, but it has no systematic relationship to \f$g\f$ and so does cover
!! error orthogonal to \f$g\f$. The two are complementary and a thorough check
!! runs both.
!!
!! **Inner product.** The design-space inner product used for both the
!! normalisation and the projection is the Euclidean one on the *assembled
!! nodal design coefficients*. It is not additionally weighted by the mass
!! matrix \f$B\f$, because the \f$B\f$ weighting is already inside the
!! sensitivities the harness is handed: the drivers call
!! `design%convert_to_directional_derivative`, which post-multiplies the
!! adjoint's \f$L^2\f$ Riesz representative \f$g_{L^2}\f$ by \f$B\f$, so what
!! arrives here is \f$g = B g_{L^2}\f$, the vector of partial derivatives with
!! respect to the nodal coefficients. Those are the variables the
!! finite difference actually perturbs, so
!! \f$ \langle g, s\rangle_2 = s^\mathsf{T} B g_{L^2}
!!     = \int_\Omega g_{L^2}\, s \,\mathrm{d}\Omega \f$:
!! the Euclidean pairing on coefficients *is* the \f$B\f$-weighted \f$L^2\f$
!! pairing of the underlying functions, expressed in the right variables.
!! Applying \f$B\f$ a second time would count it twice and is exactly the
!! inconsistency that would silently invalidate the test.
module sensitivity
  use simulation_m, only: simulation_t
  use design, only: design_t
  use utils, only: neko_error
  use num_types, only: rp, i8
  use math, only: abscmp, NEKO_EPS, glsum, glmin, glmax
  use vector, only: vector_t
  use neko_config, only: NEKO_BCKND_DEVICE
  use problem, only : problem_t
  use device, only: device_memcpy, DEVICE_TO_HOST, HOST_TO_DEVICE
  use csv_file, only : csv_file_t
  use comm, only: pe_rank, NEKO_COMM
  use mpi_f08, only: MPI_Allreduce, MPI_Exscan, MPI_SUM, MPI_INTEGER8
  use gather_scatter, only : gs_t, GS_OP_ADD
  use json_module, only: json_file
  use json_utils, only: json_get
  implicit none

  private :: count_tokens, fd_lowercase, fd_sync_to_host, fd_project, &
       fd_step_headroom, fd_report_probe, fd_run_sweep, fd_global_offset, &
       evaluate_perturbed, report_sweep, fd_random_next, &
       fd_require_host_backend

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

  !> Sentinel step limit used where a design coordinate constrains nothing --
  !! larger than any perturbation a sweep could sensibly request, so `min`
  !! against it is a no-op.
  real(kind=rp), parameter :: fd_no_limit = huge(1.0_rp)

  !> Park-Miller "minimal standard" multiplicative congruential generator,
  !! \f$x \leftarrow 16807\,x \bmod (2^{31}-1)\f$, used to build the `random`
  !! perturbation direction.
  !!
  !! Written out rather than calling `random_number` because the intrinsic
  !! generator is compiler- and version-dependent: the same seed would give a
  !! different direction under a different compiler, and a run that prints its
  !! seed would then not be reproducible in the way it claims. Both constants
  !! and the intermediate product fit in `i8` (\f$16807 \times (2^{31}-2)
  !! \approx 3.6\times 10^{13}\f$), so the sequence never overflows -- which
  !! matters because signed integer overflow is not defined in Fortran.
  integer(kind=i8), parameter :: fd_random_modulus = 2147483647_i8
  integer(kind=i8), parameter :: fd_random_multiplier = 16807_i8

  !> Seed used for the `random` perturbation direction when none is requested.
  !! Fixed rather than time- or entropy-derived, so that two runs of the same
  !! case on the same rank count differentiate along the *same* direction and
  !! are therefore comparable -- the same property `NEKO_TOP_FD_PROBE_INDEX`
  !! buys for the single-dof probe.
  integer(kind=i8), parameter :: fd_default_random_seed = 20260911_i8

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
    integer :: env_status

    call get_environment_variable(env_name, env_value, status = env_status)
    if (env_status .eq. fd_env_truncated) then
       call neko_error(env_name // ' is longer than the buffer available ' // &
            'to read it')
    end if

    if (env_status .eq. 0 .and. len_trim(env_value) .gt. 0) then
       call fd_lowercase(env_value)
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

  !> Read whether the sweep perturbs a single design degree of freedom or the
  !! whole design along the sensitivity direction.
  !!
  !! Sources, highest precedence first: the environment variable
  !! `NEKO_TOP_FD_MODE` (`dof` or `directional`, case-insensitive), then the
  !! case-file key `optimization.fd_test_mode`, then `dof` -- the historical
  !! single-degree-of-freedom probe. Anything else is an error rather than a
  !! silent fall back to `dof`, which would also silently override the case
  !! file, matching how `fd_read_central_difference` treats its value.
  !!
  !! `directional` perturbs every design dof at once along
  !! \f$ s = g/\|g\|_2 \f$ and compares the finite difference against
  !! \f$ \langle g, s \rangle = \|g\|_2 \f$, so it tests the whole gradient
  !! field in one sweep instead of one lottery-selected component of it, and
  !! its finite-difference signal is larger by roughly \f$\|g\|/|g_i|\f$.
  !!
  !! @param params The case file to read the optional key from.
  !! @param directional True to perturb along the sensitivity direction.
  subroutine fd_read_mode(params, directional)
    type(json_file), intent(inout) :: params
    logical, intent(out) :: directional

    character(len=*), parameter :: env_name = 'NEKO_TOP_FD_MODE'
    character(len=32) :: env_value
    character(len=:), allocatable :: mode_string
    integer :: env_status

    call get_environment_variable(env_name, env_value, status = env_status)
    if (env_status .eq. fd_env_truncated) then
       call neko_error(env_name // ' is longer than the buffer available ' // &
            'to read it')
    end if

    if (env_status .eq. 0 .and. len_trim(env_value) .gt. 0) then
       mode_string = trim(adjustl(env_value))
    else if (params%valid_path('optimization.fd_test_mode')) then
       call json_get(params, 'optimization.fd_test_mode', mode_string)
       ! json-fortran deallocates its result on an exception and Neko's
       ! json_get never checks failed(), so a key of the wrong type comes
       ! back unallocated rather than raising an error.
       if (.not. allocated(mode_string)) then
          call neko_error('optimization.fd_test_mode could not be read as ' // &
               'a string')
       end if
    else
       mode_string = 'dof'
    end if

    call fd_lowercase(mode_string)

    select case (trim(mode_string))
    case ('dof')
       directional = .false.
    case ('directional')
       directional = .true.
    case default
       call neko_error('The finite-difference mode must be "dof" or ' // &
            '"directional", not "' // trim(mode_string) // '"')
    end select

    deallocate(mode_string)

  end subroutine fd_read_mode

  !> Read which direction the `directional` sweep differentiates along.
  !!
  !! Sources, highest precedence first: the environment variable
  !! `NEKO_TOP_FD_DIRECTION` (`gradient` or `random`, case-insensitive), then
  !! the case-file key `optimization.fd_test_direction`, then `gradient` --
  !! preserving the behaviour the directional mode has had since it was added.
  !! Anything else is an error rather than a silent fall back to `gradient`,
  !! which would also silently override the case file, matching how
  !! `fd_read_mode` treats its value.
  !!
  !! The two exist because they have *different blind spots*, which is the
  !! whole point of offering a choice (see the module header for the algebra):
  !!  * `gradient` uses \f$s = g/\|g\|\f$, so it validates the one contraction
  !!    \f$\langle g, s\rangle = \|g\|\f$ and is blind, exactly, to any
  !!    gradient error orthogonal to \f$g\f$;
  !!  * `random` uses a seeded pseudo-random field, which has no systematic
  !!    relationship to \f$g\f$ and therefore *does* see error orthogonal to
  !!    it, at the cost of being one arbitrary contraction rather than the one
  !!    aligned with the steepest descent direction.
  !!
  !! Neither subsumes the other; a thorough check runs both.
  !!
  !! Only meaningful in `directional` mode -- the single-dof probe's direction
  !! is the one-hot vector at the probed dof.
  !!
  !! @param params The case file to read the optional key from.
  !! @param random True to differentiate along a seeded pseudo-random field
  !!        rather than along the gradient.
  subroutine fd_read_direction(params, random)
    type(json_file), intent(inout) :: params
    logical, intent(out) :: random

    character(len=*), parameter :: env_name = 'NEKO_TOP_FD_DIRECTION'
    character(len=32) :: env_value
    character(len=:), allocatable :: direction_string
    integer :: env_status

    call get_environment_variable(env_name, env_value, status = env_status)
    if (env_status .eq. fd_env_truncated) then
       call neko_error(env_name // ' is longer than the buffer available ' // &
            'to read it')
    end if

    if (env_status .eq. 0 .and. len_trim(env_value) .gt. 0) then
       direction_string = trim(adjustl(env_value))
    else if (params%valid_path('optimization.fd_test_direction')) then
       call json_get(params, 'optimization.fd_test_direction', &
            direction_string)
       ! json-fortran deallocates its result on an exception and Neko's
       ! json_get never checks failed(), so a key of the wrong type comes
       ! back unallocated rather than raising an error.
       if (.not. allocated(direction_string)) then
          call neko_error('optimization.fd_test_direction could not be ' // &
               'read as a string')
       end if
    else
       direction_string = 'gradient'
    end if

    call fd_lowercase(direction_string)

    select case (trim(direction_string))
    case ('gradient')
       random = .false.
    case ('random')
       random = .true.
    case default
       call neko_error('The finite-difference direction must be ' // &
            '"gradient" or "random", not "' // trim(direction_string) // '"')
    end select

    deallocate(direction_string)

  end subroutine fd_read_direction

  !> Read the seed for the `random` perturbation direction.
  !!
  !! Sources, highest precedence first: the environment variable
  !! `NEKO_TOP_FD_SEED`, then the case-file key
  !! `optimization.fd_test_direction_seed`, then `fd_default_random_seed`.
  !!
  !! The seed is **printed by every random-direction run**, so a run can be
  !! reproduced by copying the number out of its log -- the same contract
  !! `NEKO_TOP_FD_PROBE_INDEX` offers for the single-dof probe. Reproducible
  !! for a given mesh **and rank count**: each rank offsets the seed by its own
  !! rank so that the field differs across ranks rather than repeating, which
  !! means a different decomposition draws a different field. That is the only
  !! scope in which two finite-difference runs are comparable anyway.
  !!
  !! Must be strictly positive: zero and any multiple of the modulus are the
  !! fixed points of a multiplicative congruential sequence, which would give a
  !! constant direction rather than a random one.
  !!
  !! @param params The case file to read the optional key from.
  !! @param seed The seed to use.
  subroutine fd_read_random_seed(params, seed)
    type(json_file), intent(inout) :: params
    integer(kind=i8), intent(out) :: seed

    character(len=*), parameter :: env_name = 'NEKO_TOP_FD_SEED'
    character(len=64) :: env_value
    integer :: env_status, ios, json_seed

    call get_environment_variable(env_name, env_value, status = env_status)
    if (env_status .eq. fd_env_truncated) then
       call neko_error(env_name // ' is longer than the buffer available ' // &
            'to read it')
    end if

    if (env_status .eq. 0 .and. len_trim(env_value) .gt. 0) then
       read(env_value, *, iostat = ios) seed
       if (ios .ne. 0) then
          call neko_error(env_name // ' could not be parsed as an integer ' // &
               'seed')
       end if
    else if (params%valid_path('optimization.fd_test_direction_seed')) then
       call json_get(params, 'optimization.fd_test_direction_seed', json_seed)
       seed = int(json_seed, i8)
    else
       seed = fd_default_random_seed
    end if

    if (seed .lt. 1_i8 .or. mod(seed, fd_random_modulus) .eq. 0_i8) then
       call neko_error('The finite-difference random seed must be ' // &
            'strictly positive and not a multiple of 2147483647; those ' // &
            'are the fixed points of the generator and would give a ' // &
            'constant direction rather than a random one')
    end if

  end subroutine fd_read_random_seed

  !> Read the fixed design degree of freedom to probe, if one was requested.
  !!
  !! `NEKO_TOP_FD_PROBE_INDEX` names a **global design index**: a 1-based index
  !! into the globally concatenated design vector, i.e. the owning rank's
  !! offset plus the local index. It is what `fd_report_probe` prints for
  !! whichever dof a run actually probed, so pinning it is a copy-paste out of
  !! a previous log -- and pinning it is what makes two runs comparable, since
  !! the default probe is the largest-|sensitivity| dof and that argmax moves
  !! whenever the sensitivity field moves. Without it two runs of the same case
  !! can silently differentiate with respect to two different design variables.
  !!
  !! The index is unique and reproducible for a given mesh **and rank count**,
  !! which is the only scope in which two runs are comparable anyway. Run the
  !! same number on a different number of ranks and it names a different dof;
  !! the coordinates printed beside it make that visible immediately, so check
  !! them rather than assuming.
  !!
  !! Only meaningful in `dof` mode; the directional sweep probes no single dof.
  !!
  !! @param probe_index The global design index requested, unset if `is_set` is
  !!        false.
  !! @param is_set True if the environment variable was set and non-blank.
  subroutine fd_read_probe_index(probe_index, is_set)
    integer(kind=i8), intent(out) :: probe_index
    logical, intent(out) :: is_set

    character(len=*), parameter :: env_name = 'NEKO_TOP_FD_PROBE_INDEX'
    character(len=64) :: env_value
    integer :: env_status, ios

    probe_index = -1_i8
    is_set = .false.

    call get_environment_variable(env_name, env_value, status = env_status)
    if (env_status .eq. fd_env_truncated) then
       call neko_error(env_name // ' is longer than the buffer available ' // &
            'to read it')
    end if
    if (env_status .ne. 0 .or. len_trim(env_value) .eq. 0) return

    read(env_value, *, iostat = ios) probe_index
    if (ios .ne. 0) then
       call neko_error(env_name // ' could not be parsed as an integer ' // &
            'global design index')
    end if
    if (probe_index .lt. 1_i8) then
       call neko_error(env_name // ' must be a positive global design index')
    end if
    is_set = .true.

  end subroutine fd_read_probe_index

  !> Offset of this rank's design degrees of freedom within the globally
  !! concatenated design vector.
  !!
  !! Collective: every rank must call this.
  !!
  !! @param n Number of design degrees of freedom held locally.
  !! @return The number held by all lower-numbered ranks together.
  function fd_global_offset(n) result(offset)
    integer, intent(in) :: n
    integer(kind=i8) :: offset

    integer(kind=i8) :: local(1), scanned(1)
    integer :: ierr

    local(1) = int(n, i8)
    scanned(1) = 0_i8
    call MPI_Exscan(local, scanned, 1, MPI_INTEGER8, MPI_SUM, NEKO_COMM, ierr)
    ! The result on rank 0 is undefined by the standard, so do not read it.
    if (pe_rank .eq. 0) scanned(1) = 0_i8
    offset = scanned(1)

  end function fd_global_offset

  !> Resolve a global design index to a local index on exactly one rank.
  !!
  !! The per-rank index ranges are disjoint by construction, so at most one
  !! rank can claim the index; a count of claims is reduced so that an index
  !! past the end of the global design vector is an error rather than a silent
  !! fall back to whatever the argmax happened to pick.
  !!
  !! Collective: every rank must call this.
  !!
  !! @param n Number of design degrees of freedom held locally.
  !! @param probe_index The requested global design index.
  !! @param i Local index on the owning rank, -1 on every other rank.
  subroutine fd_resolve_probe_index(n, probe_index, i)
    integer, intent(in) :: n
    integer(kind=i8), intent(in) :: probe_index
    integer, intent(out) :: i

    integer(kind=i8) :: offset, local, claims(1), total_claims(1)
    integer :: ierr
    character(len=32) :: index_str

    offset = fd_global_offset(n)
    local = probe_index - offset

    if (local .ge. 1_i8 .and. local .le. int(n, i8)) then
       i = int(local)
       claims(1) = 1_i8
    else
       i = -1
       claims(1) = 0_i8
    end if

    call MPI_Allreduce(claims, total_claims, 1, MPI_INTEGER8, MPI_SUM, &
         NEKO_COMM, ierr)

    if (total_claims(1) .ne. 1_i8) then
       write(index_str, '(I0)') probe_index
       call neko_error('The requested probe index (' // trim(index_str) // &
            ') is outside the global design vector; take the number from ' // &
            'the "FD probe" line of a previous run of the same case, mesh ' // &
            'and rank count')
    end if

  end subroutine fd_resolve_probe_index

  !> Fold a string to lower case, in place.
  !! @param string The string to fold.
  subroutine fd_lowercase(string)
    character(len=*), intent(inout) :: string
    integer :: ic

    do ic = 1, len(string)
       if (string(ic:ic) .ge. 'A' .and. string(ic:ic) .le. 'Z') then
          string(ic:ic) = achar(iachar(string(ic:ic)) + 32)
       end if
    end do

  end subroutine fd_lowercase

  !> Copy a vector's device buffer back to the host, if there is one.
  !!
  !! Every reduction and loop in this module works on the host array, so a
  !! device build has to synchronise first.
  !!
  !! @param vec The vector to synchronise.
  subroutine fd_sync_to_host(vec)
    type(vector_t), intent(inout) :: vec

    if (NEKO_BCKND_DEVICE .eq. 1) then
       call device_memcpy(vec%x, vec%x_d, vec%size(), DEVICE_TO_HOST, .true.)
    end if

  end subroutine fd_sync_to_host

  !> Advance a Park-Miller sequence one step and map it into \f$(-1, 1)\f$.
  !!
  !! Deliberately not `random_number`: see `fd_random_modulus`. Symmetric about
  !! zero so the resulting direction has no built-in bias towards increasing
  !! the design, which would interact with the bound clamping.
  !!
  !! @param state The generator state, advanced in place. Must be in
  !!        \f$[1, 2^{31}-2]\f$ on first entry, which
  !!        `compute_sensitivity_directional` guarantees.
  !! @return A pseudo-random value in \f$(-1, 1)\f$.
  function fd_random_next(state) result(value)
    integer(kind=i8), intent(inout) :: state
    real(kind=rp) :: value

    state = mod(fd_random_multiplier * state, fd_random_modulus)
    value = 2.0_rp * (real(state, rp) / real(fd_random_modulus, rp)) - 1.0_rp

  end function fd_random_next

  !> Refuse to run on a device build, with an explanation.
  !!
  !! Both directional and single-dof paths gather-scatter a plain `allocate`d
  !! host array (the perturbation direction, and the multiplicity count) to
  !! make it single-valued on shared dofs. On a device build `gs_t%op` reaches
  !! `gs_device`'s `gather`/`scatter`, which call `device_get_ptr` on that
  !! buffer and abort because it was never `device_map`ped. The abort happens
  !! deep inside the gather-scatter backend with no hint that the caller is at
  !! fault, so this refuses at the harness boundary instead and names the fix.
  !!
  !! Deliberately a refusal rather than a `device_map`/`device_memcpy`/
  !! `device_unmap` triple around each call: this is host-only test tooling --
  !! every reduction, loop, `maxloc` and CSV row in it works on the host array
  !! -- and the mirrored device plumbing could not be executed, let alone
  !! tested, on the CPU-only machine this was written on. Adding unreachable
  !! device code would recreate the exact defect being fixed here, which is a
  !! module that *reads* as though device builds work. Whoever needs a device
  !! build should map these buffers and delete this guard in the same change
  !! that proves it on hardware.
  !!
  !! @param context Name of the routine refusing, for the message.
  subroutine fd_require_host_backend(context)
    character(len=*), intent(in) :: context

    if (NEKO_BCKND_DEVICE .eq. 1) then
       call neko_error(context // ': the finite-difference harness is ' // &
            'host-only. It gather-scatters plain host arrays, which ' // &
            'gs_device aborts on because they are not device-mapped. Run ' // &
            'the sensitivity checks against a CPU build of Neko and ' // &
            'Neko-TOP, or device_map/device_memcpy the direction and copy ' // &
            'buffers in tests/shared/sensitivity.f90 (device_unmap before ' // &
            'deallocate) and verify it on real hardware.')
    end if

  end subroutine fd_require_host_backend

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

  !> Pair the per-copy analytic sensitivities with a perturbation direction.
  !!
  !! `sensitivities` holds, at each element-local index, the derivative of the
  !! functional with respect to *that copy* of the design dof; the copies are
  !! not assembled. `direction` is single-valued (equal on every copy of a
  !! shared dof), so
  !! \f$ \sum_j g_j s_j = \sum_I s_I \sum_{j\in\mathrm{copies}(I)} g_j
  !!     = \sum_I s_I \, \partial F/\partial x_I \f$:
  !! the Euclidean inner product of the *assembled* gradient with the
  !! direction, obtained without ever dividing by a multiplicity. For a
  !! one-hot direction this reduces exactly to the assembled derivative at the
  !! single dof, which is what the single-dof sweep has always compared
  !! against.
  !!
  !! @param sensitivities Per-copy analytic derivatives.
  !! @param direction Single-valued perturbation direction.
  !! @param n Number of design degrees of freedom held locally.
  !! @return The globally reduced inner product.
  function fd_project(sensitivities, direction, n) result(projection)
    real(kind=rp), intent(in) :: sensitivities(:)
    real(kind=rp), intent(in) :: direction(:)
    integer, intent(in) :: n
    real(kind=rp) :: projection

    real(kind=rp) :: work_arr(1)
    integer :: j

    work_arr(1) = 0.0_rp
    do j = 1, n
       if (direction(j) .ne. 0.0_rp) then
          work_arr(1) = work_arr(1) + sensitivities(j) * direction(j)
       end if
    end do
    projection = glsum(work_arr, 1)

  end function fd_project

  !> Largest step magnitudes that keep the perturbed design inside its bounds.
  !!
  !! Returns the largest \f$t\f$ for which \f$x + t\,s\f$ (and, separately,
  !! \f$x - t\,s\f$) is within \f$[0,1]\f$ at *every* design coordinate. Both
  !! limits are globally reduced, so every rank agrees: a shared dof is held by
  !! several ranks and each must clamp identically or the design stops being
  !! single-valued. Coordinates with a zero direction entry never move and so
  !! place no limit.
  !!
  !! For the one-hot direction of the single-dof sweep this reduces to
  !! \f$x_i\f$ of headroom downwards and \f$1-x_i\f$ upwards, exactly the
  !! clamp that sweep has always used.
  !!
  !! @param design_values The unperturbed design.
  !! @param direction The single-valued perturbation direction.
  !! @param n Number of design degrees of freedom held locally.
  !! @param limit_plus Largest step magnitude along `+direction`.
  !! @param limit_minus Largest step magnitude along `-direction`.
  subroutine fd_step_headroom(design_values, direction, n, limit_plus, &
       limit_minus)
    real(kind=rp), intent(in) :: design_values(:)
    real(kind=rp), intent(in) :: direction(:)
    integer, intent(in) :: n
    real(kind=rp), intent(out) :: limit_plus, limit_minus

    real(kind=rp) :: local_plus(1), local_minus(1), up, down
    integer :: j

    local_plus(1) = fd_no_limit
    local_minus(1) = fd_no_limit
    do j = 1, n
       if (direction(j) .eq. 0.0_rp) cycle
       up = (fd_design_upper - design_values(j)) / abs(direction(j))
       down = (design_values(j) - fd_design_lower) / abs(direction(j))
       if (direction(j) .gt. 0.0_rp) then
          local_plus(1) = min(local_plus(1), up)
          local_minus(1) = min(local_minus(1), down)
       else
          local_plus(1) = min(local_plus(1), down)
          local_minus(1) = min(local_minus(1), up)
       end if
    end do

    limit_plus = glmin(local_plus, 1)
    limit_minus = glmin(local_minus, 1)

  end subroutine fd_step_headroom

  !> Report which design variable (or which direction) the sweep differentiates
  !! with respect to.
  !!
  !! Printed in **every** mode, unconditionally. The default single-dof probe
  !! is the largest-|sensitivity| dof, and that argmax *moves* whenever the
  !! sensitivity field moves: without this line two runs of the same case can
  !! differentiate with respect to two different design variables and nothing
  !! in the output says so. Measured on this suite, that alone spread the
  !! relative error of one case at one timestep from 0.42% to 23%.
  !!
  !! The number printed is the **global design index**: this rank's offset in
  !! the globally concatenated design vector plus the local index. That is
  !! exactly what `NEKO_TOP_FD_PROBE_INDEX` consumes, so a later run can be
  !! pinned to this run's dof by copying the number out of the log. It is
  !! reproducible for a given mesh and rank count, which is the only scope in
  !! which two runs compare anyway; the coordinates are printed beside it so
  !! that a mismatch is obvious rather than assumed away.
  !!
  !! Collective: every rank must call this.
  !!
  !! @param des The design, for the probed dof's coordinates.
  !! @param n Number of design degrees of freedom held locally.
  !! @param probe_index Local index of the probed dof. **Any non-positive value
  !!        means "not owned by this rank"** -- `maxloc` on a zero-size array
  !!        returns 0, so 0 arrives from a rank holding no design dofs -- and
  !!        it is non-positive on every rank in directional mode.
  !! @param design_value The design value at the probed dof.
  !! @param directional True when the whole design is perturbed along a
  !!        direction rather than one dof being probed.
  subroutine fd_report_probe(des, n, probe_index, design_value, directional)
    class(design_t), intent(inout) :: des
    integer, intent(in) :: n
    integer, intent(in) :: probe_index
    real(kind=rp), intent(in) :: design_value
    logical, intent(in) :: directional

    integer(kind=i8) :: send(4), recv(4), offset
    real(kind=rp) :: coords(3), work_arr(1)
    integer :: ierr, k, owner, local_index
    integer(kind=i8) :: global_index

    if (directional) then
       if (pe_rank .eq. 0) then
          write(*, '(A)') ' FD probe: mode = directional -- every design ' // &
               'degree of freedom is perturbed together'
          write(*, '(A)') ' FD probe: along the normalised direction ' // &
               'reported above, so no single dof is probed'
          write(*, '(A)') ' FD probe: and NEKO_TOP_FD_PROBE_INDEX does not' &
               // ' apply.'
       end if
       return
    end if

    ! Collective on every rank, so it must sit outside the ownership test.
    offset = fd_global_offset(n)

    ! Reduce the probed dof's identity off the owning rank so that rank 0 --
    ! which owns the log -- can report it. Reduced as integers rather than
    ! through `glsum` so that a large global index stays exact.
    send = 0_i8
    coords = 0.0_rp
    if (probe_index .gt. 0) then
       send(1) = offset + int(probe_index, i8)
       send(2) = int(pe_rank, i8)
       send(3) = int(probe_index, i8)
       send(4) = 1_i8
       coords(1) = des%x(probe_index)
       coords(2) = des%y(probe_index)
       coords(3) = des%z(probe_index)
    end if
    call MPI_Allreduce(send, recv, 4, MPI_INTEGER8, MPI_SUM, NEKO_COMM, ierr)
    do k = 1, 3
       work_arr(1) = coords(k)
       coords(k) = glsum(work_arr, 1)
    end do

    ! The sweep perturbs one dof and compares against the derivative summed
    ! over its copies, which is only the right pairing if exactly one rank
    ! nominated it. Two owners would perturb two design variables while
    ! comparing against a one-dof derivative, and report a spurious error.
    if (recv(4) .ne. 1_i8) then
       call neko_error('The finite-difference probe must be owned by ' // &
            'exactly one rank; the caller nominated it on none or on ' // &
            'several. Use the rank tie-break the drivers already apply.')
    end if

    global_index = recv(1)
    owner = int(recv(2))
    local_index = int(recv(3))

    if (pe_rank .eq. 0) then
       write(*, '(A,I0,A,I0,A,I0,A)') ' FD probe: mode = dof -- global ' &
            // 'design index ', global_index, ' (rank ', owner, &
            ', local index ', local_index, ')'
       write(*, '(A,F12.6,A,3F11.6,A)') ' FD probe: design value', &
            design_value, ', location [', coords(1), coords(2), coords(3), ']'
       write(*, '(A)') ' FD probe: reproduce this exact dof in another run ' &
            // 'by setting NEKO_TOP_FD_PROBE_INDEX to the number above.'
    end if

  end subroutine fd_report_probe

  !> Sweep a set of perturbations at one design degree of freedom and assert
  !! that the finite-difference estimate agrees with the analytic sensitivity.
  !!
  !! A thin wrapper over `fd_run_sweep`: it builds the one-hot perturbation
  !! direction for the requested dof and hands it to the single perturbation
  !! path the directional sweep also uses.
  !!
  !! @param problem The problem supplying the objective/constraint value.
  !! @param sim The simulation driving each forward solve.
  !! @param des The design being perturbed.
  !! @param target_sensitivities The analytic sensitivities to check against.
  !! @param i Local index of the dof to perturb. **Any non-positive value means
  !!          "not owned by this rank"** -- the callers pass -1 explicitly, but
  !!          `maxloc` on a zero-size array returns 0, so a rank holding no
  !!          design dofs at all arrives here with 0 and must be treated the
  !!          same way. Indexing element 0 would be out of bounds.
  !! @param perturbations The sweep of perturbation magnitudes, in any order.
  !! @param tolerance The largest acceptable minimum relative error.
  !! @param file_name The case file name, used to name the CSV log.
  !! @param is_objective True to test an objective, false a constraint.
  !! @param gs_h Gather-scatter handle for the design's dofmap. Used to keep a
  !!             perturbed *shared* design dof consistent across every element
  !!             that owns a copy of it -- see `evaluate_perturbed`.
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

    real(kind=rp), allocatable :: direction(:)
    real(kind=rp) :: target_sensitivity_i
    logical :: central
    integer :: n

    central = .false.
    if (present(central_difference)) central = central_difference

    call fd_require_host_backend('compute_sensitivity_i')

    n = des%size()
    call fd_sync_to_host(target_sensitivities)

    ! Build the one-hot direction: set the owning entry to 1 and
    ! gather-scatter with GS_OP_ADD -- the same mechanism Neko uses to
    ! propagate values between elements -- so that it is 1 on *every*
    ! element-local copy of the dof, on every rank holding one. Perturbing only
    ! the owning index would leave the design multi-valued at that point, which
    ! is not a perturbation of any real design variable.
    !
    ! The ownership test is `> 0`, not `>= 0`: a rank that holds no design dofs
    ! reaches here with i = 0, because `maxloc` on a zero-size array returns 0
    ! rather than a negative sentinel, and `direction(0)` is out of bounds.
    allocate(direction(n))
    direction = 0.0_rp
    if (i .gt. 0) direction(i) = 1.0_rp
    call gs_h%op(direction, n, GS_OP_ADD)

    ! The target is the derivative summed over every copy of the dof, which is
    ! what moving all the copies together responds to -- see `fd_project`.
    ! Measured directly: at a dof shared by two elements, moving both copies
    ! doubles the finite-difference response, and comparing that against a
    ! single copy's derivative reports a spurious ~-95% error while comparing
    ! against the assembled sum reports the same ~2.5% as the single-copy
    ! formulation. For an element-interior dof the sum is over one entry.
    target_sensitivity_i = fd_project(target_sensitivities%x, direction, n)

    call fd_run_sweep(problem, sim, des, direction, target_sensitivity_i, i, &
         perturbations, tolerance, file_name, is_objective, central, .false.)

    deallocate(direction)

  end subroutine compute_sensitivity_i

  !> Sweep a set of perturbations along a normalised direction in design space
  !! and assert that the finite-difference estimate agrees with the projection
  !! of the analytic gradient onto that direction.
  !!
  !! This is the Taylor test. It compares against \f$\langle g, s\rangle\f$ and
  !! raises the finite-difference signal by roughly \f$\|g\|/|g_i|\f$ relative
  !! to the single-dof probe, which buys back round-off headroom.
  !!
  !! **It validates one scalar contraction of the gradient, not the whole
  !! field**, and which contraction depends on `random_direction`:
  !!  * `.false.` (the default) takes \f$s = g/\|g\|_2\f$, giving
  !!    \f$\langle g,s\rangle = \|g\|\f$. Writing the computed gradient as
  !!    \f$g = G + \delta\f$, the relative error the sweep reports is
  !!    \f$-\langle\delta, g\rangle/\|g\|^2\f$, so **any \f$\delta\f$
  !!    orthogonal to \f$g\f$ passes exactly**. A sign flip reports \f$-2\f$ and
  !!    a factor-two scale error reports \f$-0.5\f$, so it catches those
  !!    completely;
  !!  * `.true.` takes \f$s\f$ from a seeded pseudo-random field instead,
  !!    assembled and normalised identically. \f$\langle g,s\rangle\f$ is then
  !!    genuinely independent of \f$\|g\|\f$ and the sweep does see error
  !!    orthogonal to \f$g\f$, at the cost of testing one arbitrary direction
  !!    rather than the one that matters most to a descent step.
  !!
  !! Neither subsumes the other. Run both.
  !!
  !! **Inner product** (see also the module header): Euclidean on the assembled
  !! nodal design coefficients, for both the normalisation and the projection.
  !! The drivers have already applied `convert_to_directional_derivative`, so
  !! the sensitivities handed in are \f$g = B g_{L^2}\f$ -- derivatives with
  !! respect to the nodal coefficients, which are the variables perturbed here.
  !! Weighting again by \f$B\f$ would count the mass matrix twice.
  !!
  !! The direction -- gradient or random -- is **assembled** with `GS_OP_ADD`
  !! before it is used, so it is single-valued on shared dofs; that is what
  !! makes the projection exact and makes the perturbation a perturbation of
  !! real design variables. The normalisation is itself a free scaling -- what
  !! is load-bearing is that \f$\langle g,s\rangle\f$ uses exactly the same
  !! \f$s\f$ that is added to the design, which it does by construction.
  !!
  !! @param problem The problem supplying the objective/constraint value.
  !! @param sim The simulation driving each forward solve.
  !! @param des The design being perturbed.
  !! @param target_sensitivities The analytic sensitivities to check against.
  !! @param perturbations The sweep of perturbation magnitudes, in any order.
  !! @param tolerance The largest acceptable minimum relative error.
  !! @param file_name The case file name, used to name the CSV log.
  !! @param is_objective True to test an objective, false a constraint.
  !! @param gs_h Gather-scatter handle for the design's dofmap, used both to
  !!             assemble the direction and to count the copies of each dof.
  !! @param central_difference (Optional) True to use a central difference.
  !! @param random_direction (Optional) True to differentiate along a seeded
  !!        pseudo-random direction rather than along \f$g\f$. Defaults to
  !!        false, the gradient direction used since this mode was added.
  !! @param random_seed (Optional) Seed for that direction; reported so the run
  !!        can be reproduced. Defaults to `fd_default_random_seed`. Ignored
  !!        when `random_direction` is false.
  subroutine compute_sensitivity_directional(problem, sim, des, &
       target_sensitivities, perturbations, tolerance, file_name, &
       is_objective, gs_h, central_difference, random_direction, random_seed)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    type(vector_t), intent(inout) :: target_sensitivities
    real(kind=rp), intent(in) :: perturbations(:)
    real(kind=rp), intent(in) :: tolerance
    character(len=*), intent(in) :: file_name
    logical, intent(in) :: is_objective
    type(gs_t), intent(inout) :: gs_h
    logical, intent(in), optional :: central_difference
    logical, intent(in), optional :: random_direction
    integer(kind=i8), intent(in), optional :: random_seed

    real(kind=rp), allocatable :: direction(:), copies(:)
    real(kind=rp) :: work_arr(1), gradient_norm, projection, max_component
    real(kind=rp) :: n_design, direction_norm
    logical :: central, random
    integer(kind=i8) :: seed, state
    integer :: j, n

    central = .false.
    if (present(central_difference)) central = central_difference
    random = .false.
    if (present(random_direction)) random = random_direction
    seed = fd_default_random_seed
    if (present(random_seed)) seed = random_seed

    call fd_require_host_backend('compute_sensitivity_directional')

    n = des%size()
    if (target_sensitivities%size() .lt. n) then
       call neko_error('compute_sensitivity_directional: the sensitivity ' // &
            'vector is shorter than the design')
    end if
    call fd_sync_to_host(target_sensitivities)

    allocate(direction(n))
    allocate(copies(n))

    ! Assemble the gradient. `target_sensitivities` holds one partial
    ! derivative per *copy* of a shared dof; GS_OP_ADD leaves their sum -- the
    ! derivative with respect to the single design variable -- at every copy.
    ! The direction is therefore single-valued by construction, which is both
    ! what makes it a perturbation of real design variables and what makes
    ! `fd_project` exact.
    do j = 1, n
       direction(j) = target_sensitivities%x(j)
    end do
    call gs_h%op(direction, n, GS_OP_ADD)

    ! Number of copies of each dof, built the way Neko builds multiplicity, so
    ! that the norm below counts each design variable exactly once instead of
    ! once per element touching it.
    copies = 1.0_rp
    call gs_h%op(copies, n, GS_OP_ADD)

    work_arr(1) = 0.0_rp
    do j = 1, n
       work_arr(1) = work_arr(1) + direction(j)*direction(j) / copies(j)
    end do
    gradient_norm = sqrt(glsum(work_arr, 1))

    if (.not. (gradient_norm .gt. 0.0_rp)) then
       call neko_error('The assembled sensitivity is identically zero, so ' // &
            'there is no direction to differentiate along and the ' // &
            'directional finite-difference test would compare zero with ' // &
            'zero. Check that the adjoint ran and that the design domain ' // &
            'influences the functional.')
    end if

    if (random) then
       ! Overwrite the assembled gradient -- `gradient_norm` has already been
       ! taken from it and is all that is still needed -- with a seeded
       ! pseudo-random field, then put it through *exactly* the same assembly
       ! and normalisation. Same GS_OP_ADD, so it is single-valued on shared
       ! dofs; same inverse-multiplicity-weighted norm, so `fd_project` pairs
       ! with it on the same footing; and the same `fd_step_headroom` clamp
       ! inside `fd_run_sweep`, which sees only a direction vector and cannot
       ! tell the two apart.
       !
       ! Offset by the rank so the field differs across ranks rather than
       ! repeating the same local sequence on each. That makes the draw a
       ! function of the decomposition as well as the seed, which is the same
       ! (mesh, rank count) reproducibility scope the probe index has.
       state = 1_i8 + mod(seed + int(pe_rank, i8), fd_random_modulus - 1_i8)
       do j = 1, n
          direction(j) = fd_random_next(state)
       end do
       call gs_h%op(direction, n, GS_OP_ADD)

       work_arr(1) = 0.0_rp
       do j = 1, n
          work_arr(1) = work_arr(1) + direction(j)*direction(j) / copies(j)
       end do
       direction_norm = sqrt(glsum(work_arr, 1))

       if (.not. (direction_norm .gt. 0.0_rp)) then
          call neko_error('The random perturbation direction assembled to ' // &
               'identically zero, which a Park-Miller sequence cannot do ' // &
               'by chance. Check the seed and the gather-scatter handle.')
       end if
    else
       direction_norm = gradient_norm
    end if

    do j = 1, n
       direction(j) = direction(j) / direction_norm
    end do

    projection = fd_project(target_sensitivities%x, direction, n)

    ! The one guard on inner-product consistency, and now asserted rather than
    ! only printed: with a consistent inner product <g, g/||g||> = ||g||
    ! exactly, so a divergence means the normalisation and the projection are
    ! using two different pairings and every number downstream -- including a
    ! plausible-looking CSV -- is measuring the wrong thing. Only true for the
    ! gradient direction; for a random s, <g,s> is genuinely not ||g||.
    ! Collective-safe: both operands are `glsum` results and so identical on
    ! every rank.
    if (.not. random) then
       if (abs(projection - gradient_norm) .gt. 1e-10_rp*gradient_norm) then
          call neko_error('The projection <g,s> disagrees with ||g|| for ' // &
               's = g/||g||, so the normalisation and the projection are ' // &
               'not using the same inner product. Every finite-difference ' // &
               'number in this sweep would be comparing against the wrong ' // &
               'quantity -- see the inner-product note in the module header.')
       end if
    end if

    work_arr(1) = 0.0_rp
    do j = 1, n
       work_arr(1) = work_arr(1) + 1.0_rp / copies(j)
    end do
    n_design = glsum(work_arr, 1)
    ! `copies` has served its purpose as the multiplicity count -- both norms
    ! and `n_design` are already reduced -- so it is reused here as scratch for
    ! abs(direction). Nothing below reads it as a multiplicity.
    copies = abs(direction)
    max_component = glmax(copies, n)

    if (pe_rank .eq. 0) then
       ! Which direction was used is printed first and unconditionally: the two
       ! measure different things, so a sweep read without knowing which one
       ! produced it cannot be interpreted at all.
       if (random) then
          write(*, '(A,I0)') ' FD directional: direction = random ' // &
               '(seeded pseudo-random field), seed = ', seed
          write(*, '(A)') ' FD directional: this covers gradient error ' // &
               'orthogonal to g, which the gradient'
          write(*, '(A)') ' FD directional: direction is blind to; it is ' // &
               'still one contraction, of one draw.'
       else
          write(*, '(A)') ' FD directional: direction = gradient, ' // &
               's = g/||g||_2'
          write(*, '(A)') ' FD directional: this validates ONE scalar ' // &
               'contraction of the gradient, along g itself;'
          write(*, '(A)') ' FD directional: error orthogonal to g passes ' // &
               'it exactly. Use NEKO_TOP_FD_DIRECTION=random'
          write(*, '(A)') ' FD directional: for a direction with a ' // &
               'different blind spot.'
       end if
       write(*, '(A,E15.6E3,A,E15.6E3)') &
            ' FD directional: gradient 2-norm = ', gradient_norm, &
            '   projection onto s = ', projection
       ! `nint(..., i8)`, not `nint(...)`: the count is a global dof count and
       ! a default integer would silently wrap on a large enough mesh. Rounded
       ! rather than truncated with `int` because 1/copies is inexact for any
       ! multiplicity that is not a power of two, so a count of 272 can arrive
       ! as 271.999... and `int` would print 271.
       write(*, '(A,E15.6E3,A,I0)') &
            ' FD directional: largest direction entry = ', max_component, &
            '   design variables = ', nint(n_design, i8)
       write(*, '(A)') ' FD directional: inner product = Euclidean on the ' &
            // 'assembled nodal design'
       write(*, '(A)') ' FD directional: coefficients (the mass-matrix ' &
            // 'weighting is already inside g).'
    end if

    call fd_run_sweep(problem, sim, des, direction, projection, -1, &
         perturbations, tolerance, file_name, is_objective, central, .true.)

    deallocate(direction)
    deallocate(copies)

  end subroutine compute_sensitivity_directional

  !> Run a perturbation sweep along a given direction and assert that the
  !! finite-difference estimate agrees with the analytic directional
  !! derivative.
  !!
  !! The single perturbation path for both modes: the single-dof probe is the
  !! one-hot special case of it, so the two cannot drift apart.
  !!
  !! @param problem The problem supplying the objective/constraint value.
  !! @param sim The simulation driving each forward solve.
  !! @param des The design being perturbed.
  !! @param direction Single-valued perturbation direction, one entry per local
  !!        design degree of freedom.
  !! @param target_derivative The analytic derivative along `direction`.
  !! @param probe_index Local index of the probed dof in single-dof mode.
  !!        **Any non-positive value means "not owned by this rank"** --
  !!        `maxloc` on a zero-size array returns 0, so 0 arrives from a rank
  !!        holding no design dofs -- and it is non-positive on every rank in
  !!        directional mode.
  !! @param perturbations The sweep of perturbation magnitudes, in any order.
  !! @param tolerance The largest acceptable minimum relative error.
  !! @param file_name The case file name, used to name the CSV log.
  !! @param is_objective True to test an objective, false a constraint.
  !! @param central True to use a central difference.
  !! @param directional True when the whole design is perturbed along
  !!        `direction`; false for the historical single-dof probe.
  subroutine fd_run_sweep(problem, sim, des, direction, target_derivative, &
       probe_index, perturbations, tolerance, file_name, is_objective, &
       central, directional)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    real(kind=rp), intent(in) :: direction(:)
    real(kind=rp), intent(in) :: target_derivative
    integer, intent(in) :: probe_index
    real(kind=rp), intent(in) :: perturbations(:)
    real(kind=rp), intent(in) :: tolerance
    character(len=*), intent(in) :: file_name
    logical, intent(in) :: is_objective
    logical, intent(in) :: central
    logical, intent(in) :: directional

    character(len=*), parameter :: fmt_head = '(4X,A12,4X,A10,6X,A11,5X,A5,10X)'
    character(len=*), parameter :: fmt_data = '(4X,4E15.6E3)'

    integer :: n_perturbations, ip
    real(kind=rp) :: perturb, work_arr(1)
    type(vector_t) :: design_vector, design_perturbed, log_data, constraint_vec
    real(kind=rp) :: constraint, perturbed_constraint, minus_constraint
    real(kind=rp) :: restored_constraint
    real(kind=rp) :: fd_estimate, fd_error
    real(kind=rp) :: min_error, min_perturb, smallest_perturb, largest_perturb
    real(kind=rp) :: design_value, limit_plus, limit_minus
    real(kind=rp), allocatable :: sweep_perturbs(:), sweep_errors(:)
    logical, allocatable :: usable(:)
    character(len=:), allocatable :: sign_pattern
    character(len=16) :: value_str
    integer :: min_index, i_write, n_crossings
    logical :: sweep_set, prefer_negative
    type(csv_file_t) :: logger
    integer :: n, name_len, slash

    n = des%size()

    ! Initialize the vectors
    call design_vector%init(n)
    call design_perturbed%init(n)
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
    end if

    ! Broadcast the design value at the probed dof -- only the owning rank
    ! holds it, and it decides the sign of the one-sided step and is quoted in
    ! the central-difference error message, both of which every rank must
    ! compose identically.
    !
    ! `> 0`, not `>= 0`: a rank holding no design dofs arrives with
    ! probe_index = 0 (`maxloc` on a zero-size array returns 0), and
    ! `design_vector%x(0)` is out of bounds. Matches `fd_report_probe`.
    if (probe_index .gt. 0) then
       work_arr(1) = design_vector%x(probe_index)
    else
       work_arr(1) = 0.0_rp
    end if
    design_value = glsum(work_arr, 1)

    ! Historical rule, kept exactly: a single dof past the middle of its range
    ! is perturbed downwards, so that a one-sided step on a design initialised
    ! as a 0/1 indicator field stays inside the bounds. A whole-field direction
    ! has no such freedom -- flipping it would flip the sign of the projection
    ! it is compared against -- so it is clamped in magnitude instead.
    prefer_negative = (.not. directional) .and. (design_value .gt. &
         0.5_rp * (fd_design_lower + fd_design_upper))

    call fd_step_headroom(design_vector%x, direction, n, limit_plus, &
         limit_minus)

    call fd_report_probe(des, n, probe_index, design_value, directional)

    if (pe_rank .eq. 0) then
       write(*, fmt_head) "Perturbation", "Constraint", "FD Estimate", "Error"
       write(*, fmt_data) 0.0_rp, constraint, target_derivative, 0.0_rp
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
       name_len = len_trim(file_name)
       slash = index(file_name(:name_len), '/', back = .true.)
       call logger%init('FD_check_' // &
            trim(file_name(slash+1:name_len-5)) // '.csv')
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

       ! Decide the step. Every quantity it is built from -- `design_value`
       ! and the two headroom limits -- is already globally reduced, so every
       ! rank holding a copy of a shared dof necessarily applies the *same*
       ! perturbation without a further broadcast.
       if (central) then
          ! A central difference needs room on *both* sides of the design,
          ! so the symmetric half-step is clamped to whichever bound is
          ! nearer. The alternative -- stepping outside the bounds -- would
          ! evaluate a design that does not exist.
          perturb = min(abs(perturbations(ip)), limit_plus, limit_minus)
       else
          ! Ensure the perturbation stays within the bounds
          perturb = abs(perturbations(ip))
          if (prefer_negative) perturb = -perturb
          if (directional) perturb = min(perturb, limit_plus)
       end if

       ! Clamping diagnostics, shared by every path that clamps: the
       ! central-difference half-step, and the one-sided directional step.
       ! The historical one-sided single-dof step is not clamped at all -- it
       ! keeps itself in bounds by its sign -- and so is deliberately excluded.
       if (central .or. directional) then
          if (perturb .le. 0.0_rp) then
             if (directional) then
                call neko_error('No room to step along the sensitivity ' // &
                     'direction: the design already sits on a bound that ' // &
                     'the direction pushes it through. Initialise the ' // &
                     'design strictly inside its bounds -- see ' // &
                     'passive_scalar_interior.case, whose design is 0.3/0.7 ' &
                     // 'for exactly this reason.')
             else
                ! Note that a design initialised as a 0/1 indicator field --
                ! as most cases in this suite are -- puts *every* dof on a
                ! bound, so this is the normal outcome there rather than a
                ! corner case.
                write(value_str, '(F12.6)') design_value
                call neko_error('Central difference impossible: the ' // &
                     'design variable being perturbed is ' // &
                     trim(adjustl(value_str)) // ', on or outside its ' // &
                     'bounds, so there is no room for a symmetric step. ' // &
                     'Either initialise the design strictly inside its ' // &
                     'bounds, or use the one-sided difference (unset ' // &
                     'NEKO_TOP_FD_CENTRAL / set ' // &
                     'fd_test_central_difference false).')
             end if
          end if

          ! A step clamped far below the requested perturbation no longer
          ! probes the sweep point that was asked for: the design is so close
          ! to a bound that the finite difference is round-off noise at a
          ! perturbation nobody requested, and its error could spuriously
          ! become the sweep minimum. Choice made here: abort rather than
          ! silently skip the point, so the sweep that ran is always the sweep
          ! that was requested. Collective-safe: every input to `perturb` is
          ! globally reduced.
          if (abs(perturb) .lt. 1e-3_rp * abs(perturbations(ip))) then
             call neko_error('Finite-difference step clamped below 1/1000 ' // &
                  'of the requested perturbation: the design is too close ' // &
                  'to a bound for this sweep point to be meaningful. ' // &
                  'Start the sweep at smaller perturbations or move the ' // &
                  'design away from its bounds.')
          end if

          ! A clamped step is a different sweep point from the one requested,
          ! so say so rather than let the CSV be read as if the requested
          ! value had been used.
          if (pe_rank .eq. 0 .and. &
               abs(perturb) .lt. (1.0_rp - 1e-12_rp)*abs(perturbations(ip))) &
               then
             write(*, '(A,E15.6E3,A,E15.6E3,A)') &
                  ' FD sweep: requested step', abs(perturbations(ip)), &
                  ' clamped to', abs(perturb), ' by the design bounds.'
          end if
       end if

       if (central) then
          i_write = i_write + 1
          call evaluate_perturbed(problem, sim, des, design_vector, &
               design_perturbed, direction, perturb, is_objective, &
               i_write, constraint_vec, perturbed_constraint)

          i_write = i_write + 1
          call evaluate_perturbed(problem, sim, des, design_vector, &
               design_perturbed, direction, -perturb, is_objective, &
               i_write, constraint_vec, minus_constraint)

          fd_estimate = perturbed_constraint - minus_constraint
          if (.not. abscmp(fd_estimate, 0.0_rp)) then
             fd_estimate = fd_estimate / (2.0_rp * perturb)
          end if
       else
          i_write = i_write + 1
          call evaluate_perturbed(problem, sim, des, design_vector, &
               design_perturbed, direction, perturb, is_objective, &
               i_write, constraint_vec, perturbed_constraint)

          fd_estimate = perturbed_constraint - constraint
          if (.not. abscmp(fd_estimate, 0.0_rp)) then
             fd_estimate = fd_estimate / perturb
          end if
       end if

       fd_error = relative_error(fd_estimate, target_derivative)

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
         design_perturbed, direction, 0.0_rp, is_objective, &
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
    deallocate(sweep_perturbs, sweep_errors, usable, sign_pattern)

  end subroutine fd_run_sweep

  !> Evaluate the objective (or constraint) at the design displaced by
  !! `step * direction`.
  !!
  !! The one perturbation path: a single-dof probe passes a one-hot
  !! `direction`, the Taylor test passes a whole normalised gradient field, and
  !! nothing downstream distinguishes them. Factored out of the sweep so that
  !! the central-difference variant can reuse it for both the \f$x + h s\f$ and
  !! \f$x - h s\f$ legs, and the sweep can reuse it once more with a zero step
  !! to restore the baseline design.
  !!
  !! The design field is stored per element, (lx, ly, lz, nelv), so a dof on an
  !! element interface has one copy per adjoining element, possibly on
  !! different MPI ranks. `direction` must therefore be **single-valued**:
  !! equal on every copy of a shared dof, on every rank holding one. Both
  !! callers guarantee that by gather-scattering it with GS_OP_ADD -- the same
  !! mechanism Neko uses to propagate values between elements. Displacing only
  !! one copy would leave the design multi-valued at that point, which is not a
  !! perturbation of any real design variable.
  !!
  !! @param problem The problem supplying the objective/constraint value.
  !! @param sim The simulation driving the forward solve.
  !! @param des The design, updated in place with the perturbed values.
  !! @param design_vector The unperturbed design values.
  !! @param design_perturbed Work vector receiving the perturbed design.
  !! @param direction Single-valued perturbation direction; zero entries are
  !!        left untouched.
  !! @param step The signed step scaling `direction`.
  !! @param is_objective True to read the objective, false the constraint.
  !! @param write_index Output index handed to `sim%write`.
  !! @param constraint_vec Work vector for the constraint values.
  !! @param functional The resulting objective or constraint value.
  subroutine evaluate_perturbed(problem, sim, des, design_vector, &
       design_perturbed, direction, step, is_objective, write_index, &
       constraint_vec, functional)
    class(problem_t), intent(inout) :: problem
    type(simulation_t), intent(inout) :: sim
    class(design_t), intent(inout) :: des
    type(vector_t), intent(in) :: design_vector
    type(vector_t), intent(inout) :: design_perturbed
    real(kind=rp), intent(in) :: direction(:)
    real(kind=rp), intent(in) :: step
    logical, intent(in) :: is_objective
    integer, intent(in) :: write_index
    type(vector_t), intent(inout) :: constraint_vec
    real(kind=rp), intent(out) :: functional

    integer :: j

    ! Reset the design field
    design_perturbed%x = design_vector%x

    ! Displace along the direction, keeping the design single-valued. Entries
    ! with a zero direction are skipped rather than having zero added, so that
    ! the untouched part of the design is bit-for-bit the baseline.
    do j = 1, size(direction)
       if (direction(j) .ne. 0.0_rp) then
          design_perturbed%x(j) = design_vector%x(j) + step * direction(j)
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
