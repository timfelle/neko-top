!> @file lapack_interfaces.f90
!! @copyright
!! Copyright (c) 2024-2025, The Neko-TOP Authors
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

module lapack_interfaces
  use num_types, only: sp, dp

  implicit none
  private

  public :: gesv, sgesv, dgesv

  !> Solve a dense linear system with LAPACK in the precision of its
  !! arguments, with sgesv in single and dgesv in double precision. The
  !! dummy b is declared as a flat array of ldb * nrhs entries, so the
  !! generic interface matches only a rank-1 (vector) b. A rank-2 b (nrhs
  !! right-hand sides held as matrix columns) must call sgesv or dgesv
  !! directly: both still accept it via sequence association.
  interface gesv
     pure subroutine sgesv(n, nrhs, a, lda, ipiv, b, ldb, info)
       import :: sp
       integer, intent(in) :: n, nrhs, lda, ldb
       real(kind=sp), intent(inout), dimension(lda, n) :: a
       integer, intent(out), dimension(n) :: ipiv
       real(kind=sp), intent(inout), dimension(ldb * nrhs) :: b
       integer, intent(out) :: info
     end subroutine sgesv

     pure subroutine dgesv(n, nrhs, a, lda, ipiv, b, ldb, info)
       import :: dp
       integer, intent(in) :: n, nrhs, lda, ldb
       real(kind=dp), intent(inout), dimension(lda, n) :: a
       integer, intent(out), dimension(n) :: ipiv
       real(kind=dp), intent(inout), dimension(ldb * nrhs) :: b
       integer, intent(out) :: info
     end subroutine dgesv
  end interface gesv

end module lapack_interfaces
