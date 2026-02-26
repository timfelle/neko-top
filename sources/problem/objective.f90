!> @file objective.f90
!! @copyright
!! Copyright (c) 2025, The Neko-TOP Authors
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

!> Implements the `objective_t` type.
module objective
  use base_functional, only: base_functional_t
  use simulation_m, only: simulation_t
  use design, only: design_t
  use num_types, only: rp
  use point_zone_registry, only: neko_point_zone_registry
  use json_module, only: json_file
  use json_utils, only: json_get_or_default
  use logger, only: neko_log, LOG_SIZE
  implicit none
  private

  public :: objective_t, objective_factory, objective_wrapper_t

  !> The abstract objective type.
  !!
  !! This is the base class for objectives, which is a type of base functional.
  !! Each objective contain a weight that is used to scale the objective value.
  type, abstract, extends(base_functional_t) :: objective_t
     !> Weight of the objective in the overall cost function.
     !! The target attribute allows adjoint source terms to reference this weight
     !! by pointer, so that continuation updates are reflected automatically.
     real(kind=rp), target :: weight = 1.0_rp

     ! Continuation parameters for the weight
     !> Multiplicative update factor for the weight (continuation).
     !! A value of 1.0 means no continuation is applied.
     real(kind=rp) :: weight_factor = 1.0_rp
     !> Maximum weight (upper bound for continuation).
     real(kind=rp) :: weight_max = huge(0.0_rp)
     !> Number of iterations between weight continuation updates.
     integer :: weight_update_interval = 1

   contains

     !> Initializer for the base class
     procedure, pass(this) :: init_base => objective_init_base
     !> Destructor of the base class
     procedure, pass(this) :: free_base => objective_free_base
     !> Get the weight of the objective
     procedure, pass(this) :: get_weight => objective_get_weight
     !> Read weight continuation parameters from JSON.
     procedure, pass(this) :: init_weight_continuation => &
          objective_init_weight_continuation
     !> Update the weight for continuation.
     !! @param iter The current optimization iteration.
     procedure, pass(this) :: update_weight => objective_update_weight

  end type objective_t

  !> Wrapper for objectives for use in lists.
  type :: objective_wrapper_t
     class(objective_t), allocatable :: objective
   contains
     procedure, pass(this) :: free => objective_wrapper_free
  end type objective_wrapper_t

  ! -------------------------------------------------------------------------- !
  ! Explicit interfaces

  !> Factory function
  !! Allocates and initializes an objective function object
  !! @param object The objective function object to be created
  !! @param type The type of the objective function
  !! @param design The design object
  !! @param simulation The simulation object
  interface objective_factory
     module subroutine objective_factory(object, json, design, simulation)
       class(objective_t), allocatable, intent(inout) :: object
       type(json_file), intent(inout) :: json
       class(design_t), intent(in) :: design
       type(simulation_t), target, optional, intent(inout) :: simulation
     end subroutine objective_factory
  end interface objective_factory

contains

  ! -------------------------------------------------------------------------- !
  ! Implementations for the base class

  !> Initialize the objective base class.
  !! @param this The objective.
  !! @param name The name of the objective.
  !! @param design_size The number of design variables.
  !! @param weight The weight of the objective function.
  !! @param mask_name The name design the mask. [optional]
  subroutine objective_init_base(this, name, design_size, weight, mask_name)
    class(objective_t), intent(inout) :: this
    character(len=*), intent(in) :: name
    integer, intent(in) :: design_size
    real(kind=rp), intent(in) :: weight
    character(len=*), intent(in), optional :: mask_name

    call this%free_base()

    this%name = name
    call this%sensitivity%init(design_size)
    call this%sensitivity_old%init(design_size)

    this%weight = weight

    if (present(mask_name)) then
       if (mask_name .ne. "") then
          this%has_mask = .true.
          this%mask => neko_point_zone_registry%get_point_zone(mask_name)
       end if
    end if

  end subroutine objective_init_base

  !> Free the base class
  subroutine objective_free_base(this)
    class(objective_t), target, intent(inout) :: this

    this%name = ""
    this%weight = 1.0_rp
    this%weight_factor = 1.0_rp
    this%weight_max = huge(0.0_rp)
    this%weight_update_interval = 1

    this%value = 0.0_rp
    this%value_old = 0.0_rp
    call this%sensitivity%free()
    call this%sensitivity_old%free()

    this%has_mask = .false.
    if (associated(this%mask)) nullify(this%mask)

  end subroutine objective_free_base

  ! -------------------------------------------------------------------------- !
  ! Implementations for the wrapper

  !> Free the objective wrapper.
  subroutine objective_wrapper_free(this)
    class(objective_wrapper_t), intent(inout) :: this
    if (allocated(this%objective)) then
       call this%objective%free()
       deallocate(this%objective)
    end if
  end subroutine objective_wrapper_free

  !> Get the weight of the objective
  pure function objective_get_weight(this) result(w)
    class(objective_t), intent(in) :: this
    real(kind=rp) :: w
    w = this%weight
  end function objective_get_weight

  !> Read weight continuation parameters from JSON.
  !! @param this The objective.
  !! @param json The JSON parameters.
  subroutine objective_init_weight_continuation(this, json)
    class(objective_t), intent(inout) :: this
    type(json_file), intent(inout) :: json

    call json_get_or_default(json, 'continuation.weight_factor', &
         this%weight_factor, 1.0_rp)
    call json_get_or_default(json, 'continuation.weight_max', &
         this%weight_max, huge(0.0_rp))
    call json_get_or_default(json, 'continuation.update_interval', &
         this%weight_update_interval, 1)

  end subroutine objective_init_weight_continuation

  !> Update the objective weight for continuation.
  !! @param this The objective.
  !! @param iter The current optimization iteration.
  subroutine objective_update_weight(this, iter)
    class(objective_t), intent(inout) :: this
    integer, intent(in) :: iter
    character(len=LOG_SIZE) :: log_buf

    if (this%weight_factor .eq. 1.0_rp) return
    if (iter .le. 0) return
    if (mod(iter, this%weight_update_interval) .ne. 0) return

    this%weight = min(this%weight * this%weight_factor, this%weight_max)

    write(log_buf, '(A,A,A,ES13.6)') 'Objective [', trim(this%name), &
         '] weight updated to ', this%weight
    call neko_log%message(log_buf)

  end subroutine objective_update_weight

end module objective

