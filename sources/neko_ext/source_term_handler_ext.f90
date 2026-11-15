!> @file source_term_handler_ext.f90
!! @copyright
!! Copyright (c) 2026, The Neko-TOP Authors
!! All rights reserved.
!!
!! Redistribution and use in source and binary forms, with or without
!! modification, are permitted provided that the following conditions
!! are met:
!!
!!   * Redistributions of source code must retain the above copyright
!!     notice, this list of conditions and the following disclaimer.
!!
!!   * Redistributions in binary form must reproduce the above
!!     copyright notice, this list of conditions and the following
!!     disclaimer in the documentation and/or other materials provided
!!     with the distribution.
!!
!!   * Neither the name of the authors nor the names of its
!!     contributors may be used to endorse or promote products derived
!!     from this software without specific prior written permission.
!!
!! THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
!! "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
!! LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
!! FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
!! COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
!! INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
!! BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
!! LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
!! CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
!! LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
!! ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
!! POSSIBILITY OF SUCH DAMAGE.

!> Extensions to Neko's `source_term_handler` module.
module source_term_handler_ext
  use source_term, only: source_term_t, source_term_wrapper_t
  use source_term_handler, only: source_term_handler_t
  implicit none
  private

  public :: remove_source_term

contains

  !> Remove a source term from a source term handler, which can only add
  !! them. The term is freed, and the others are kept in their order.
  !! @param handler The handler holding the term.
  !! @param source_term The term to remove, as held by `handler`. Nothing is
  !! removed if `handler` holds no such term.
  subroutine remove_source_term(handler, source_term)
    class(source_term_handler_t), target, intent(inout) :: handler
    class(source_term_t), pointer, intent(in) :: source_term
    class(source_term_wrapper_t), allocatable :: kept(:)
    integer :: i, n

    if (.not. allocated(handler%source_terms)) return

    n = 0
    do i = 1, size(handler%source_terms)
       if (.not. associated(source_term, &
            handler%source_terms(i)%source_term)) n = n + 1
    end do
    if (n .eq. size(handler%source_terms)) return

    allocate(kept(n))
    n = 0
    do i = 1, size(handler%source_terms)
       if (associated(source_term, handler%source_terms(i)%source_term)) then
          call handler%source_terms(i)%free()
       else
          n = n + 1
          call move_alloc(handler%source_terms(i)%source_term, &
               kept(n)%source_term)
       end if
    end do
    call move_alloc(kept, handler%source_terms)

    ! Counted anew, as the handler counts them when a term is added.
    handler%n_unextrapolated = 0
    do i = 1, size(handler%source_terms)
       if (.not. handler%source_terms(i)%source_term%extrapolate) then
          handler%n_unextrapolated = handler%n_unextrapolated + 1
       end if
    end do

  end subroutine remove_source_term

end module source_term_handler_ext
