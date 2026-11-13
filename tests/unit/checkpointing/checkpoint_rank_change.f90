!> Helpers for the checkpoint_rank_change driver below.
module checkpoint_rank_change_helpers
  use mpi_f08, only: MPI_Barrier
  use num_types, only: rp
  use comm, only: NEKO_COMM
  use vector, only: vector_t
  use design, only: design_t
  use device, only: HOST_TO_DEVICE, DEVICE_TO_HOST
  implicit none
  private

  !> Design that only holds its values.
  type, extends(design_t), public :: plain_design_t
     type(vector_t) :: values
   contains
     procedure, pass(this) :: init => plain_design_init
     procedure, pass(this) :: free => plain_design_free
     procedure, pass(this) :: get_values => plain_design_get_values
     procedure, pass(this) :: update_design => plain_design_update_design
     procedure, pass(this) :: map_forward => plain_design_map_forward
     procedure, pass(this) :: map_backward => plain_design_map_backward
     procedure, pass(this) :: write => plain_design_write
  end type plain_design_t

  public :: stop_on_every_rank

contains

  !> Error handler that stops only once every rank has raised an error.
  !! @details neko_error prints its message before calling this, so every
  !! message reaches the output before any rank stops. An error raised on
  !! some ranks only never passes the barrier, which the test reports as a
  !! hang.
  !! @param filename The file that raised the error.
  !! @param line_number The line that raised the error.
  !! @param message The error message, if any.
  subroutine stop_on_every_rank(filename, line_number, message)
    character(len=*), intent(in) :: filename
    integer, intent(in) :: line_number
    character(len=*), optional, intent(in) :: message

    call MPI_Barrier(NEKO_COMM)
    error stop 1

  end subroutine stop_on_every_rank

  !> Initialise the design with the values given on this rank.
  !! @param x0 The values.
  subroutine plain_design_init(this, x0)
    class(plain_design_t), intent(inout) :: this
    real(kind=rp), intent(in) :: x0(:)

    call this%init_base('plain_design', size(x0))
    this%values = x0

  end subroutine plain_design_init

  subroutine plain_design_free(this)
    class(plain_design_t), intent(inout) :: this

    call this%values%free()
    call this%free_base()

  end subroutine plain_design_free

  !> Copy the stored values into `values`, on the host and the device.
  !! @param values The vector to fill.
  subroutine plain_design_get_values(this, values)
    class(plain_design_t), intent(in) :: this
    type(vector_t), intent(inout) :: values

    if (this%size() .gt. 0) values%x(1:this%size()) = this%values%x(:)
    call values%copy_from(HOST_TO_DEVICE, .true.)

  end subroutine plain_design_get_values

  !> Store `values`, whose device side is current.
  !! @param values The new values.
  subroutine plain_design_update_design(this, values)
    class(plain_design_t), intent(inout) :: this
    type(vector_t), intent(inout) :: values

    if (this%size() .eq. 0) return
    call values%copy_from(DEVICE_TO_HOST, .true.)
    this%values%x(:) = values%x(1:this%size())
    call this%values%copy_from(HOST_TO_DEVICE, .true.)

  end subroutine plain_design_update_design

  subroutine plain_design_map_forward(this)
    class(plain_design_t), intent(inout) :: this
  end subroutine plain_design_map_forward

  subroutine plain_design_map_backward(this, sensitivity)
    class(plain_design_t), intent(inout) :: this
    type(vector_t), intent(in) :: sensitivity
  end subroutine plain_design_map_backward

  subroutine plain_design_write(this, idx)
    class(plain_design_t), intent(inout) :: this
    integer, intent(in) :: idx
  end subroutine plain_design_write

end module checkpoint_rank_change_helpers

!> Driver for check_checkpoint_rank_change.cmake: write or load the MMA and
!! the design HDF5 checkpoints on the ranks of the current run.
!! @details
!! Usage: `checkpoint_rank_change <mode> <file> [uneven]`, where `mode` is
!! `save` (both checkpoints into one file), `load_mma` or `load_design`.
!! The 6 design variables are spread as evenly as possible over the ranks,
!! or, with `uneven`, with one moved from the second rank to the first.
!! A load that does not match the save must stop with an error on every
!! rank; see stop_on_every_rank. A completed mode prints one line per rank.
program checkpoint_rank_change
  use, intrinsic :: iso_fortran_env, only: output_unit
  use num_types, only: rp
  use neko, only: neko_init, neko_finalize
  use comm, only: pe_rank, pe_size
  use utils, only: neko_error, throw_error
  use device, only: HOST_TO_DEVICE
  use vector, only: vector_t
  use mma, only: mma_t
  use checkpoint_rank_change_helpers, only: plain_design_t, &
       stop_on_every_rank
  implicit none

  !> Global number of design variables.
  integer, parameter :: n_global = 6
  !> Number of constraints.
  integer, parameter :: m = 1
  character(len=16) :: mode, layout
  character(len=256) :: filename
  type(mma_t) :: opt
  type(plain_design_t) :: des
  type(vector_t) :: x
  real(kind=rp), allocatable :: xmin(:), xmax(:)
  real(kind=rp) :: a(m), c(m), d(m)
  integer :: n

  call get_command_argument(1, mode)
  call get_command_argument(2, filename)
  call get_command_argument(3, layout)

  call neko_init()
  throw_error => stop_on_every_rank

  n = n_global / pe_size
  if (pe_rank .lt. mod(n_global, pe_size)) n = n + 1
  if (trim(layout) .eq. 'uneven' .and. pe_size .gt. 1) then
     if (pe_rank .eq. 0) n = n + 1
     if (pe_rank .eq. 1) n = n - 1
  end if

  call x%init(n)
  if (n .gt. 0) x%x = 0.5_rp
  call x%copy_from(HOST_TO_DEVICE, sync = .true.)

  allocate(xmin(n), xmax(n))
  xmin = 0.0_rp
  xmax = 1.0_rp
  a = 0.0_rp
  c = 1000.0_rp
  d = 1.0_rp
  call opt%init_from_components(x, n, m, 1.0_rp, a, c, d, xmin, xmax, &
       bcknd = 'cpu', subsolver = 'dip')
  ! Only the layout of the design values matters here
  call des%init(xmax)

  select case (trim(mode))
  case ('save')
     call opt%save_checkpoint(trim(filename))
     call des%save_checkpoint(trim(filename))
  case ('load_mma')
     call opt%load_checkpoint(trim(filename))
  case ('load_design')
     call des%load_checkpoint(trim(filename))
  case default
     call neko_error('checkpoint_rank_change: unknown mode "' // &
          trim(mode) // '"')
  end select

  write(output_unit, '(A,I0)') 'checkpoint_rank_change: ' // trim(mode) // &
       ' completed on rank ', pe_rank
  flush(output_unit)

  call des%free()
  call opt%free()
  call x%free()
  deallocate(xmin, xmax)
  call neko_finalize()

end program checkpoint_rank_change
