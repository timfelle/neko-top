!> @file minimize_u.f90
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
!
!> Implements the `minimize_u_t` type.
module minimize_u
  use objective, only: objective_t
  use design, only: design_t
  use brinkman_design, only: brinkman_design_t
  use simulation_m, only: simulation_t
  use adjoint_lube_source_term, only: adjoint_lube_source_term_t
  use adjoint_fluid_pnpn, only: adjoint_fluid_pnpn_t
  use num_types, only: rp
  use field, only: field_t
  use scratch_registry, only: neko_scratch_registry, scratch_registry_t
  use neko_config, only: NEKO_BCKND_DEVICE
  use device, only: DEVICE_TO_HOST
  use mask_ops, only: mask_exterior_const, compute_masked_volume
  use utils, only: neko_error
  use json_module, only: json_file
  use json_utils, only: json_get_or_default
  use registry, only: neko_registry
  use interpolation, only: interpolator_t
  use space, only: space_t, GL
  use coefs, only: coef_t
  use math, only: glsc2, copy, col2, invcol2, cfill_mask
  use device_math, only: device_copy, device_glsc2, device_col2, device_invcol2
  use math_ext, only: copy_mask, glsc2_mask
  use field_math, only: field_col3, field_addcol3, field_cmult, field_col2
  use vector, only: vector_t
  use iso_c_binding, only: c_ptr
  use device, only: HOST_TO_DEVICE
  implicit none
  private

  !> An objective function corresponding to out of plane stresses
  !! \f$ F =  \int_Omega \frac{1}{2} \chi |\mathbf{u}|^2 d \Omega \f$
  type, public, extends(objective_t) :: minimize_u_t
     private

     type(field_t), pointer :: u => null()
     real(kind=rp), dimension(:,:,:,:), pointer :: B => null()
     type(c_ptr) :: B_d

   contains

     !> The common constructor using a JSON object.
     procedure, public, pass(this) :: init_json_sim => dummy_init_json_sim
     !> The actual constructor.
     procedure, public, pass(this) :: init_from_attributes => &
          dummy_init_attributes
     !> Destructor.
     procedure, public, pass(this) :: free => dummy_free
     !> Computes the value of the objective function.
     procedure, public, pass(this) :: update_value => &
          dummy_update_value
     !> Computes the sensitivity with respect to the coefficient \f$\chi\f$.
     procedure, public, pass(this) :: update_sensitivity => &
          dummy_update_sensitivity

  end type minimize_u_t

contains

  !> The common constructor using a JSON object.
  !! @param this The objective.
  !! @param json the JSON object.
  !! @param design the design.
  !! @param simulation the simulation.
  subroutine dummy_init_json_sim(this, json, design, simulation)
    class(minimize_u_t), intent(inout) :: this
    type(json_file), intent(inout) :: json
    class(design_t), intent(in) :: design
    type(simulation_t), target, intent(inout) :: simulation

    character(len=:), allocatable :: mask_name
    character(len=:), allocatable :: name
    real(kind=rp) :: weight

    call json_get_or_default(json, "weight", weight, 1.0_rp)
    call json_get_or_default(json, "mask_name", mask_name, "")
    call json_get_or_default(json, "name", name, "Minimize U")

    call this%init_from_attributes(design, simulation, weight, name, &
         mask_name)
  end subroutine dummy_init_json_sim

  !> The actual constructor.
  !! @param this The objective.
  !! @param design the design.
  !! @param simulation the simulation.
  !! @param weight the weight of the objective function.
  !! @param name the name of the objective.
  !! @param mask_name the name of the mask.
  !! @param dealias_sensitivity use dealiasing on the sensitivity.
  !! @param dealias_forcing use dealiasing on the adjoint forcing.
  subroutine dummy_init_attributes(this, design, simulation, weight, &
       name, mask_name)
    class(minimize_u_t), intent(inout) :: this
    class(design_t), intent(in) :: design
    type(simulation_t), target, intent(inout) :: simulation
    real(kind=rp), intent(in) :: weight
    character(len=*), intent(in) :: mask_name
    character(len=*), intent(in) :: name

    ! Call the base initializer
    call this%init_base(name, design%size(), weight, mask_name)

    ! Initialize the pointer to the velocity field
    this%u => simulation%fluid%u
    this%B => simulation%fluid%c_Xh%B
    this%B_d = simulation%fluid%c_Xh%B_d

    ! Compute the initial value of the objective function
    call this%update_value(design)
    call this%update_sensitivity(design)

  end subroutine dummy_init_attributes

  !> Destructor.
  subroutine dummy_free(this)
    class(minimize_u_t), intent(inout) :: this
    call this%free_base()

  end subroutine dummy_free

  !> Compute the objective function.
  !! @param this The objective.
  !! @param design the design.
  subroutine dummy_update_value(this, design)
    class(minimize_u_t), intent(inout) :: this
    class(design_t), intent(in) :: design

    call this%u%copy_from(DEVICE_TO_HOST, sync = .true.)

    ! Compute the integral of u in the masked region
    this%value = glsc2_mask(this%u%x, this%B, this%u%size(), &
         this%mask%mask%get(), this%mask%mask%size())

  end subroutine dummy_update_value

  !> update_value the sensitivity of the objective function with respect to
  !! \f$chi\f$
  !! @param this The objective.
  !! @param design the design.
  subroutine dummy_update_sensitivity(this, design)
    class(minimize_u_t), intent(inout) :: this
    class(design_t), intent(in) :: design

    call copy_mask(this%sensitivity%x, this%B, this%u%size(), &
         this%mask%mask%get(), this%mask%mask%size())

    call this%sensitivity%copy_from(HOST_TO_DEVICE, sync = .true.)
  end subroutine dummy_update_sensitivity

end module minimize_u
