! Copyright (c) 2026, The Neko-TOP Authors
! All rights reserved.
!
! Redistribution and use in source and binary forms, with or without
! modification, are permitted provided that the following conditions
! are met:
!
!   * Redistributions of source code must retain the above copyright
!     notice, this list of conditions and the following disclaimer.
!
!   * Redistributions in binary form must reproduce the above
!     copyright notice, this list of conditions and the following
!     disclaimer in the documentation and/or other materials provided
!     with the distribution.
!
!   * Neither the name of the authors nor the names of its
!     contributors may be used to endorse or promote products derived
!     from this software without specific prior written permission.
!
! THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
! "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
! LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
! FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
! COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
! INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
! BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
! LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
! CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
! LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
! ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
! POSSIBILITY OF SUCH DAMAGE.
!
!> Host memory probes for the loadup path.
!!
!! @details Reports resident and peak-resident host memory at named points,
!! reduced across ranks. Written for the memory-consumption investigation
!! recorded in `mem_test/investigation.md`.
!!
!! The peak is read from `VmHWM` in `/proc/self/status`, which the kernel
!! maintains as a high-water mark rather than a sample. That matters here:
!! the batch system's own accounting samples on an interval and has already
!! been observed to miss the peak of a short loadup entirely, reporting a
!! figure close to process start.
module memory_probe
  use comm, only: pe_rank, pe_size, NEKO_COMM
  use logger, only: neko_log, LOG_SIZE
  use num_types, only: dp
  use mpi_f08, only: MPI_Allreduce, MPI_IN_PLACE, MPI_INTEGER, &
       MPI_MAX, MPI_SUM
  implicit none

  private

  !> Resident set size on this rank at the previous probe, in kB.
  integer :: prev_rss = 0
  !> Whether prev_rss holds a reading yet.
  logical :: have_prev = .false.

  public :: memory_probe_report, memory_probe_reset, setup_only_requested

contains

  !> Whether NEKOTOP_SETUP_ONLY asks the run to stop after setup.
  !!
  !! @details Stopping after setup is what makes the loadup peak of one case
  !! comparable with another's: otherwise a case that survives runs on into
  !! the time loop and its peak picks up solver working memory, while a case
  !! that dies during setup reports only part of the story.
  !!
  !! Set the variable to enable. "0", "false" and "no" disable it, so that
  !! NEKOTOP_SETUP_ONLY=0 means what a reader expects rather than enabling
  !! the gate by virtue of being set at all.
  !!
  !! @return Whether to stop after setup.
  function setup_only_requested() result(setup_only)
    logical :: setup_only
    character(len=32) :: val
    integer :: length, i

    call get_environment_variable('NEKOTOP_SETUP_ONLY', val, length)

    setup_only = (length .gt. 0)
    if (.not. setup_only) return

    do i = 1, len(val)
       if (val(i:i) .ge. 'A' .and. val(i:i) .le. 'Z') then
          val(i:i) = achar(iachar(val(i:i)) + 32)
       end if
    end do

    select case (trim(adjustl(val)))
    case ('0', 'false', 'no', 'off')
       setup_only = .false.
    end select

  end function setup_only_requested

  !> Report host memory at a named point, reduced across all ranks.
  !!
  !! @details Emits a single line of the form
  !! @verbatim
  !! [mem] <label>   rss <max>/<avg>  hwm <max>  d <change since last> MB
  !! @endverbatim
  !! where `rss` is the current resident set, `hwm` the peak resident set so
  !! far, and `d` the change in this rank's resident set since the previous
  !! call. All figures are megabytes.
  !!
  !! Reducing to both max and average is deliberate: a max far above the
  !! average means the partition is uneven, which is a different problem
  !! from uniform growth and should not be mistaken for it.
  !!
  !! @param label Short name for the point being measured.
  subroutine memory_probe_report(label)
    character(len=*), intent(in) :: label
    character(len=LOG_SIZE) :: log_buf
    character(len=20) :: name
    integer :: rss, hwm, rss_max, rss_sum, hwm_max, delta
    real(kind=dp) :: rss_max_mb, rss_avg_mb, hwm_max_mb, delta_mb

    rss = read_status_kb('VmRSS:')
    hwm = read_status_kb('VmHWM:')

    if (have_prev) then
       delta = rss - prev_rss
    else
       delta = 0
    end if
    prev_rss = rss
    have_prev = .true.

    rss_max = rss
    rss_sum = rss
    hwm_max = hwm
    if (pe_size .gt. 1) then
       call MPI_Allreduce(MPI_IN_PLACE, rss_max, 1, MPI_INTEGER, MPI_MAX, &
            NEKO_COMM)
       call MPI_Allreduce(MPI_IN_PLACE, rss_sum, 1, MPI_INTEGER, MPI_SUM, &
            NEKO_COMM)
       call MPI_Allreduce(MPI_IN_PLACE, hwm_max, 1, MPI_INTEGER, MPI_MAX, &
            NEKO_COMM)
       call MPI_Allreduce(MPI_IN_PLACE, delta, 1, MPI_INTEGER, MPI_MAX, &
            NEKO_COMM)
    end if

    rss_max_mb = real(rss_max, dp) / 1024.0_dp
    rss_avg_mb = real(rss_sum, dp) / (1024.0_dp * real(pe_size, dp))
    hwm_max_mb = real(hwm_max, dp) / 1024.0_dp
    delta_mb = real(delta, dp) / 1024.0_dp

    name = label
    write(log_buf, '(A,A20,A,F9.1,A,F9.1,A,F9.1,A,F9.1)') &
         '[mem] ', name, ' rss ', rss_max_mb, '/', rss_avg_mb, &
         ' hwm ', hwm_max_mb, ' d ', delta_mb
    call neko_log%message(log_buf)

  end subroutine memory_probe_report

  !> Forget the previous reading, so the next report shows no change.
  subroutine memory_probe_reset()
    prev_rss = 0
    have_prev = .false.
  end subroutine memory_probe_reset

  !> Read one `key` from `/proc/self/status` and return its value in kB.
  !!
  !! @details Returns 0 where the file or the key is unavailable, so a
  !! platform without a Linux-style procfs degrades to reporting zeros
  !! rather than failing the run.
  !!
  !! @param key Field name including its colon, for example `VmRSS:`.
  !! @return The field's value in kB, or 0 if it could not be read.
  function read_status_kb(key) result(kb)
    character(len=*), intent(in) :: key
    integer :: kb
    integer :: unit_, ios, colon
    character(len=256) :: line

    kb = 0

    open(newunit = unit_, file = '/proc/self/status', status = 'old', &
         action = 'read', iostat = ios)
    if (ios .ne. 0) return

    do
       read(unit_, '(A)', iostat = ios) line
       if (ios .ne. 0) exit

       if (line(1:len(key)) .eq. key) then
          colon = index(line, ':')
          ! The remainder reads as "   12345 kB"; a list-directed read takes
          ! the integer and stops before the unit.
          read(line(colon + 1:), *, iostat = ios) kb
          if (ios .ne. 0) kb = 0
          exit
       end if
    end do

    close(unit_)

  end function read_status_kb

end module memory_probe
