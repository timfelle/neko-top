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
!! both reduced across ranks and as one named rank's own unreduced series.
!! Written for the memory-consumption investigation recorded in
!! `mem_test/investigation.md`.
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
  !> Peak resident set size on this rank at the previous probe, in kB.
  integer :: prev_hwm = 0
  !> Whether prev_rss and prev_hwm hold a reading yet.
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

  !> Report host memory at a named point.
  !!
  !! @details Emits two greppable lines per probe: the first reduced over all
  !! ranks, the second rank 0's own unreduced reading.
  !! @verbatim
  !! [mem] <label>  rss <max>/<avg>  hwm <max>  d <d_rss>/<d_hwm>
  !! [mem0] <label> rss <own>  hwm <own>  d <d_rss>/<d_hwm>
  !! @endverbatim
  !! `rss` is the current resident set, `hwm` the peak resident set so far,
  !! and `d` the change in each since the previous probe. All figures are
  !! megabytes, and the fields are fixed width - the label is 18 characters,
  !! every absolute figure `F8.1` and every delta `F7.1` - so a parser may
  !! slice by column, but only relative to the tag: the logger prepends its
  !! current indentation, and the two tags differ in length. Note that
  !! `[mem]` is not a substring of `[mem0]`, so an existing grep for the
  !! reduced line still matches only reduced lines.
  !!
  !! Both deltas are reported because either alone mis-attributes, and
  !! neither reveals on its own that it has. A resident set is lazy: an
  !! array that is allocated but not yet written to costs no `VmRSS`, so the
  !! step that allocates it under-reports and the later step that first
  !! touches it is charged instead. A step that allocates and frees within
  !! itself reports no resident change at all, while having raised the
  !! process peak - and since glibc rarely returns freed memory to the
  !! operating system, that charge persists anyway. `VmHWM` is a kernel
  !! high-water mark and sees both cases. Where the two deltas disagree the
  !! attribution at that step is suspect, which is the point of printing
  !! them side by side:
  !!
  !! - `d_hwm` above `d_rss`: the step held more than it kept, so its cost
  !!   to the peak is `d_hwm` rather than the smaller resident change.
  !! - `d_rss` above `d_hwm`: the step's growth did not raise the peak, so
  !!   the pages were reserved under an earlier step's peak and part of the
  !!   charge belongs to that earlier step.
  !!
  !! The two lines answer two different questions. The reduced line shows
  !! imbalance: a max far above the average means the partition is uneven,
  !! which is a different problem from uniform growth and should not be
  !! mistaken for it. It cannot show whether the per-step deltas account for
  !! the peak, because each maximum is taken independently and may come from
  !! a different rank, so a series of per-step maxima does not sum to the
  !! maximum high-water mark. The `[mem0]` line is one rank throughout, so
  !! its deltas do sum to its own `VmHWM` growth, and a shortfall in that
  !! sum means memory allocated outside the instrumented paths.
  !!
  !! Every rank reaches every reduction; only the writes are rank 0's, both
  !! in the test below and inside the logger, so no collective sits behind a
  !! rank test.
  !!
  !! @param label Short name for the point being measured, truncated to 18
  !! characters to keep the reduced line at 77 of the LOG_SIZE characters the
  !! buffer holds. Widening a field is not the cosmetic matter it looks:
  !! an internal write longer than its buffer is a runtime error, not a
  !! silent truncation, so the two spare characters are the whole margin.
  subroutine memory_probe_report(label)
    character(len=*), intent(in) :: label
    character(len=LOG_SIZE) :: log_buf
    character(len=18) :: name
    integer :: rss, hwm, d_rss, d_hwm
    integer :: rss_max, rss_sum, hwm_max, d_rss_max, d_hwm_max

    rss = read_status_kb('VmRSS:')
    hwm = read_status_kb('VmHWM:')

    if (have_prev) then
       d_rss = rss - prev_rss
       d_hwm = hwm - prev_hwm
    else
       d_rss = 0
       d_hwm = 0
    end if
    prev_rss = rss
    prev_hwm = hwm
    have_prev = .true.

    ! Reduced in copies rather than in place, so that this rank's own
    ! readings survive for the [mem0] line below.
    rss_max = rss
    rss_sum = rss
    hwm_max = hwm
    d_rss_max = d_rss
    d_hwm_max = d_hwm
    if (pe_size .gt. 1) then
       call MPI_Allreduce(MPI_IN_PLACE, rss_max, 1, MPI_INTEGER, MPI_MAX, &
            NEKO_COMM)
       call MPI_Allreduce(MPI_IN_PLACE, rss_sum, 1, MPI_INTEGER, MPI_SUM, &
            NEKO_COMM)
       call MPI_Allreduce(MPI_IN_PLACE, hwm_max, 1, MPI_INTEGER, MPI_MAX, &
            NEKO_COMM)
       call MPI_Allreduce(MPI_IN_PLACE, d_rss_max, 1, MPI_INTEGER, MPI_MAX, &
            NEKO_COMM)
       call MPI_Allreduce(MPI_IN_PLACE, d_hwm_max, 1, MPI_INTEGER, MPI_MAX, &
            NEKO_COMM)
    end if

    name = label
    write(log_buf, '(A,A18,A,F8.1,A,F8.1,A,F8.1,A,F7.1,A,F7.1)') &
         '[mem] ', name, ' rss ', kb_to_mb(rss_max), '/', &
         kb_to_mb(rss_sum) / real(pe_size, dp), ' hwm ', &
         kb_to_mb(hwm_max), ' d ', kb_to_mb(d_rss_max), '/', &
         kb_to_mb(d_hwm_max)
    call neko_log%message(log_buf)

    ! Rank 0's own series. The logger writes on rank 0 alone in any case, so
    ! the test only makes plain which rank the figures describe; it is safe
    ! because nothing behind it is collective.
    if (pe_rank .eq. 0) then
       write(log_buf, '(A,A18,A,F8.1,A,F8.1,A,F7.1,A,F7.1)') &
            '[mem0] ', name, ' rss ', kb_to_mb(rss), ' hwm ', &
            kb_to_mb(hwm), ' d ', kb_to_mb(d_rss), '/', kb_to_mb(d_hwm)
       call neko_log%message(log_buf)
    end if

  end subroutine memory_probe_report

  !> Forget the previous reading, so the next report shows no change.
  !!
  !! @details Only the probe's own bookkeeping is cleared. `VmHWM` belongs to
  !! the kernel and is not resettable from here, so a peak reached before the
  !! reset still stands in every later `hwm` field.
  subroutine memory_probe_reset()
    prev_rss = 0
    prev_hwm = 0
    have_prev = .false.
  end subroutine memory_probe_reset

  !> Convert a reading in kilobytes to megabytes.
  !!
  !! @details Called from the output lists above, which keeps each format
  !! statement beside the values it formats rather than behind a screenful
  !! of conversions.
  !!
  !! @param kb A reading in kilobytes.
  !! @return The same reading in megabytes.
  pure function kb_to_mb(kb) result(mb)
    integer, intent(in) :: kb
    real(kind=dp) :: mb

    mb = real(kb, dp) / 1024.0_dp

  end function kb_to_mb

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
