"""Table tests of the Neko-TOP case-file schemas.

Every table row is a valid fixture with a few edits (see schema_helpers).
`ACCEPTED_BY_THE_CODE` rows are values the code reads without complaint, so
the schema must accept them (some of them look odd); `REJECTED_AS_THE_CODE_
ABORTS` rows are values on which the code aborts or computes garbage, with the
source line in the comment, and the error must be reported at the path named
in the last column. A rule that is removed from a schema turns its rows red.
"""

from __future__ import annotations

import copy

import pytest

from schema_helpers import (DEL, build, ensure_object, error_paths, errors,
                            load_base, short)

S, U, N = "steady", "unsteady", "neko"

# --------------------------------------------------------------------------- #
# Accepted: odd-looking values the code reads without complaint.
# (id, base, edits)
# --------------------------------------------------------------------------- #
ACCEPTED_BY_THE_CODE = [
    # continuation_scheduler.f90:248: iterations <= 0 disable the schedule.
    ("continuation_iterations_zero", S,
     {"optimization.design.mapping[0].r_iterations": 0}),
    # continuation_scheduler.f90:155,160: array form with its iterations.
    ("array_with_iterations", S,
     {"optimization.design.mapping[2].f_max": [1.0, 10.0],
      "optimization.design.mapping[2].f_max_iterations": 2}),
    # optimizer.f90:550: checkpoint.interval <= 0 disables checkpoints.
    ("checkpoint_interval_zero", S,
     {"optimization.solver.checkpoint": {"interval": 0, "format": "h5",
                                         "overwrite": True}}),
    # mma_optimizer.f90:132: max_iterations 0 evaluates the initial design.
    ("max_iterations_zero", S, {"optimization.solver.max_iterations": 0}),
    # optimizer.f90:428: a full D-H:M:S duration, or none at all.
    ("max_runtime_days", S, {"optimization.solver.max_runtime": "1-02:03:04"}),
    ("max_runtime_empty", S, {"optimization.solver.max_runtime": ""}),
    # optimizer.f90:433: empty restart_file means no restart.
    ("restart_file_empty", S, {"optimization.solver.restart_file": ""}),
    # mma.f90:290: both backends are known to the MMA object.
    ("mma_backend_cpu", S, {"optimization.solver.mma.backend": "cpu"}),
    # mma.f90:291: the other subsolver.
    ("mma_pdip", S, {"optimization.solver.mma.subsolver": "pdip"}),
    # mapping_fctry.f90: the alias is a case label of the factory.
    ("heaviside_projection_alias", S,
     {"optimization.design.mapping[1].type": "heaviside_projection"}),
    # krylov_fctry.f90: fused_cg is only an error on a CPU build.
    ("pde_filter_fused_cg", S,
     {"optimization.design.mapping[0].solver": "fused_cg"}),
    # PDE_filter_mapping.f90:436: ident is initialised by its constructor.
    ("pde_filter_ident", S,
     {"optimization.design.mapping[0].preconditioner": "ident"}),
    # design_brinkman.f90:293: SP/DP spellings.
    ("design_output_precision_DP", S,
     {"optimization.design.output_precision": "DP"}),
    # design_brinkman.f90:302: point_zone domain with its zone.
    ("design_domain_full", S,
     {"optimization.design.domain": {"type": "full"}}),
    # set_optimization_ic.f90:262-270: `field` is accepted (the abort found
    # while reading was inferred, not run).
    ("initial_distribution_field", S,
     {"optimization.design.initial_distribution":
      {"type": "field", "file_name": "mean0.f00001"}}),
    # set_optimization_ic.f90:108-110
    ("initial_distribution_point_zone", S,
     {"optimization.design.initial_distribution":
      {"type": "point_zone", "base_value": 0.0, "zone_value": 1.0,
       "zone_name": "optimization_domain"}}),
    # objective.f90:151: an empty mask_name means the whole domain.
    ("empty_mask_name", S, {"optimization.objectives[1].mask_name": ""}),
    # steady runs ignore start_time/end_time but read them.
    ("objective_window_in_steady_run", S,
     {"optimization.objectives[1].start_time": 1.0,
      "optimization.objectives[1].end_time": 2.0}),
    # volume_constraint.f90:134-136
    ("volume_constraint_is_max", S,
     {"optimization.constraints[0].is_max": True,
      "optimization.constraints[0].name": "V"}),
    # adjoint_fluid_pnpn_bc_fctry.f90:178: known type, factory branch
    # commented out: the BC is accepted and does nothing.
    ("adjoint_bc_user_velocity_pointwise", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "user_velocity_pointwise", "zone_indices": [1, 3, 4, 5, 6]}}),
    # adjoint_fluid_pnpn_bc_fctry.f90:149-195: types of the pressure factory.
    ("adjoint_bc_user_pressure", S,
     {"case.adjoint_fluid.boundary_conditions[1]":
      {"type": "user_pressure", "zone_indices": [2]}}),
    # neko src/bc/inflow.f90:77: velocity_value values go through the
    # constants lookup, so a name is fine.
    ("adjoint_bc_velocity_value_constant", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "velocity_value", "zone_indices": [1, 3, 4, 5, 6],
       "value": "inflow"}}),
    # adjoint_case.f90:452: output_value goes through the constants lookup.
    ("adjoint_output_value_constant", S,
     {"case.adjoint_fluid.output_control": "tsteps",
      "case.adjoint_fluid.output_value": "every"}),
    # adjoint_fluid_pnpn.f90:437: advection false uses the dummy advection;
    # only an OIFS flag aborts.
    ("advection_false", S, {"case.fluid.advection": False}),
    # adjoint_scalar_pnpn_bc_fctry.f90:73: the adjoint scalar `user` BC.
    ("adjoint_scalar_bc_user", S,
     {"case.adjoint_scalar.boundary_conditions[0]":
      {"type": "user", "zone_indices": [1]}}),
    # adjoint_case.f90:176: a disabled adjoint scalar reads nothing else.
    ("adjoint_scalar_disabled_with_scalar_disabled", S,
     {"case.scalar.enabled": False,
      "case.adjoint_scalar": {"enabled": False},
      "optimization.objectives[0]": {"type": "viscous_dissipation"}}),
    # steady_simcomp.f90:126-129
    ("steady_simcomp_keys", S,
     {"case.simulation_components[0].tol": 1.0e-9,
      "case.simulation_components[0].log_frequency": 1,
      "case.simulation_components[0].scalar_coupled": True}),
    # simulation.f90:271-287
    ("unsteady_with_variable_timestep_false", U,
     {"case.time.variable_timestep": False}),
    # checkpoint.f90:161: extra fields are looked up by name.
    ("state_recovery_extra_fields", U,
     {"state_recovery.extra_fields": ["s"]}),
    ("state_recovery_alias_and_case", U,
     {"state_recovery.type": "simulation_checkpoint",
      "state_recovery.algorithm": "LINEAR"}),
    # Neko itself: an unknown simulation component is a registered one.
    ("unknown_simcomp_type", S,
     {"case.simulation_components[1]": {"type": "my_simcomp", "my_key": 1}}),
    # neko_ext.f90: freeze_flow is a boolean read at every iteration.
    ("freeze_flow", S, {"case.fluid.freeze_flow": True,
                         "case.adjoint_fluid.freeze_flow": True}),
]

# --------------------------------------------------------------------------- #
# Rejected: values on which the code aborts or computes garbage.
# (id, base, edits, a fragment of the path of an error)
# --------------------------------------------------------------------------- #
REJECTED_AS_THE_CODE_ABORTS = [
    # ---- common: continuation reals ---------------------------------------
    # continuation_scheduler.f90:160: an integer is neither real nor array.
    ("continuation_integer", S,
     {"optimization.design.mapping[2].f_max": 100}, "mapping[2]"),
    ("continuation_string", S,
     {"optimization.design.mapping[2].f_max": "big"}, "mapping[2]"),
    # continuation_scheduler.f90:153: an empty array reads values(1).
    ("continuation_empty_array", S,
     {"optimization.design.mapping[2].f_max": []}, "mapping[2]"),
    # case_file_utils.f90:347: elements must be reals.
    ("continuation_integer_elements", S,
     {"optimization.design.mapping[2].f_max": [1, 2]}, "mapping[2]"),
    # continuation_scheduler.f90:155: iterations are read for arrays only.
    ("iterations_with_scalar", S,
     {"optimization.design.mapping[2].f_max_iterations": 3}, "mapping[2]"),
    ("iterations_real", S,
     {"optimization.design.mapping[2].f_max": [1.0, 2.0],
      "optimization.design.mapping[2].f_max_iterations": 2.0}, "mapping[2]"),
    ("objective_weight_integer", S,
     {"optimization.objectives[0].weight": 1}, "objectives[0]"),
    ("objective_weight_iterations_with_scalar", S,
     {"optimization.objectives[0].weight_iterations": 2}, "objectives[0]"),
    # ---- mapping ----------------------------------------------------------
    # mapping_fctry.f90:84: unknown type.
    ("mapping_unknown_type", S,
     {"optimization.design.mapping[2].type": "tanh"}, "mapping[2]"),
    # RAMP_mapping.f90:106-107: convex_up aborts whatever its value.
    ("ramp_convex_up", S,
     {"optimization.design.mapping[2].convex_up": True}, "mapping[2]"),
    # linear_mapping.f90:81 etc.: f_max is required.
    ("linear_without_f_max", S,
     {"optimization.constraints[0].mapping[0].f_max": DEL}, "mapping[0]"),
    # heaviside_mapping.f90:116, :112, :96
    ("heaviside_eta_above_one", S,
     {"optimization.design.mapping[1].eta": 1.5}, "mapping[1]"),
    ("heaviside_eta_negative", S,
     {"optimization.design.mapping[1].eta": -0.1}, "mapping[1]"),
    ("heaviside_beta_zero", S,
     {"optimization.design.mapping[1].beta": 0.0}, "mapping[1]"),
    ("heaviside_without_beta", S,
     {"optimization.design.mapping[1].beta": DEL}, "mapping[1]"),
    ("heaviside_projection_without_beta", S,
     {"optimization.design.mapping[1].type": "heaviside_projection",
      "optimization.design.mapping[1].beta": DEL}, "mapping[1]"),
    # PDE_filter_mapping.f90:136: r is required.
    ("pde_filter_without_r", S,
     {"optimization.design.mapping[0].r": DEL}, "mapping[0]"),
    # PDE_filter_mapping.f90:436-460: hsmg/phmg are never initialised.
    ("pde_filter_hsmg", S,
     {"optimization.design.mapping[0].preconditioner": "hsmg"}, "mapping[0]"),
    # PDE_filter_mapping.f90:290: coupled solvers abort on the first solve.
    ("pde_filter_coupled_cg", S,
     {"optimization.design.mapping[0].solver": "coupled_cg"}, "mapping[0]"),
    ("pde_filter_tol_integer", S,
     {"optimization.design.mapping[0].tol": 1}, "mapping[0]"),
    ("pde_filter_max_iter_real", S,
     {"optimization.design.mapping[0].max_iter": 200.0}, "mapping[0]"),
    ("pde_filter_unknown_key", S,
     {"optimization.design.mapping[0].eta": 0.5}, "mapping[0]"),
    ("linear_mapping_p_key", S,
     {"optimization.constraints[0].mapping[0].p": 3.0}, "mapping[0]"),
    # ---- objectives -------------------------------------------------------
    # objective_factory.f90:81
    ("objective_unknown_type", S,
     {"optimization.objectives[0].type": "drag"}, "objectives[0]"),
    # scalar_mixing_objective_function.f90:129: phi_ref is not read.
    ("scalar_mixing_phi_ref", S,
     {"optimization.objectives[0].phi_ref": 0.5}, "objectives[0]"),
    # target_concentration is read for scalar_mixing only.
    ("viscous_dissipation_target_concentration", S,
     {"optimization.objectives[1].target_concentration": 0.5},
     "objectives[1]"),
    ("objective_target_integer", S,
     {"optimization.objectives[0].target_concentration": 1}, "objectives[0]"),
    # brinkman_dissipation_objective.f90:162: the two flags must agree.
    ("brinkman_dealias_flags_differ", U,
     {"optimization.objectives[0].dealias_sensitivity": True,
      "optimization.objectives[0].dealias_forcing": False}, "objectives[0]"),
    ("objective_mask_name_integer", S,
     {"optimization.objectives[1].mask_name": 3}, "objectives[1]"),
    # ---- constraints ------------------------------------------------------
    # constraint_factory.f90:72
    ("constraint_unknown_type", S,
     {"optimization.constraints[0].type": "perimeter"}, "constraints[0]"),
    # volume_constraint.f90:137: limit is required, a JSON real.
    ("volume_without_limit", S,
     {"optimization.constraints[0].limit": DEL}, "constraints[0]"),
    ("volume_limit_integer", S,
     {"optimization.constraints[0].limit": 1}, "constraints[0]"),
    ("volume_limit_constant", S,
     {"optimization.constraints[0].limit": "V0"}, "constraints[0]"),
    # ---- design -----------------------------------------------------------
    # design.f90:262: simple always aborts in the shipped drivers.
    ("design_simple", S,
     {"optimization.design": {"type": "simple"}}, "optimization.design"),
    # mapping_handler.f90:644: no mapping, null pointer.
    ("design_without_mapping", S,
     {"optimization.design.mapping": DEL}, "optimization.design"),
    # design_brinkman.f90:302,307
    ("design_point_zone_without_zone", S,
     {"optimization.design.domain": {"type": "point_zone"}},
     "design.domain"),
    ("design_full_domain_with_zone", S,
     {"optimization.design.domain": {"type": "full",
                                     "zone_name": "optimization_domain"}},
     "design.domain"),
    ("design_domain_type", S,
     {"optimization.design.domain.type": "box"}, "design.domain"),
    # design_brinkman.f90:293
    ("design_output_precision", S,
     {"optimization.design.output_precision": "quad"}, "optimization.design"),
    # design_brinkman.f90:284 and neko src/io/file.f90:133
    ("design_output_format", S,
     {"optimization.design.output_format": "csv"}, "optimization.design"),
    # the Brinkman design reads domain.* itself: not under `optimization`.
    ("domain_under_optimization", S,
     {"optimization.domain": {"type": "point_zone", "zone_name": "z"}},
     "$.optimization"),
    # set_optimization_ic.f90:100-123
    ("initial_distribution_unknown_type", S,
     {"optimization.design.initial_distribution": {"type": "ball"}},
     "initial_distribution"),
    ("initial_distribution_uniform_without_value", S,
     {"optimization.design.initial_distribution": {"type": "uniform"}},
     "initial_distribution"),
    ("initial_distribution_value_integer", S,
     {"optimization.design.initial_distribution.value": 0},
     "initial_distribution"),
    ("initial_distribution_point_zone_without_value", S,
     {"optimization.design.initial_distribution":
      {"type": "point_zone", "base_value": 0.0, "zone_name": "z"}},
     "initial_distribution"),
    # set_optimization_ic.f90:262: a .fNNNNN file name.
    ("initial_distribution_field_name", S,
     {"optimization.design.initial_distribution":
      {"type": "field", "file_name": "mean0.fld"}}, "initial_distribution"),
    # ---- optimizer --------------------------------------------------------
    # optimizer_factory.f90:88
    ("solver_unknown_type", S,
     {"optimization.solver.type": "gradient_flow"}, "optimization.solver"),
    ("solver_without_type", S,
     {"optimization.solver.type": DEL}, "optimization.solver"),
    # optimization.f90 / the factory: solver and design are required.
    ("optimization_without_solver", S,
     {"optimization.solver": DEL}, "$.optimization"),
    ("optimization_without_design", S,
     {"optimization.design": DEL}, "$.optimization"),
    # optimizer.f90:429
    ("max_runtime_format", S,
     {"optimization.solver.max_runtime": "1:2:3:4"}, "optimization.solver"),
    ("max_runtime_hours_with_days", S,
     {"optimization.solver.max_runtime": "1-25:00:00"}, "optimization.solver"),
    # optimizer.f90:1012
    ("restart_file_suffix", S,
     {"optimization.solver.restart_file": "state.txt"}, "optimization.solver"),
    # optimizer.f90:851
    ("checkpoint_format", S,
     {"optimization.solver.checkpoint.format": "json"}, "checkpoint"),
    # mma.f90:496, :502; mma_cpu.f90:122
    ("mma_backend", S,
     {"optimization.solver.mma.backend": "gpu"}, "optimization.solver.mma"),
    ("mma_epsimin_zero", S,
     {"optimization.solver.mma.epsimin": 0.0}, "optimization.solver.mma"),
    ("mma_subsolver", S,
     {"optimization.solver.mma.subsolver": "ipopt"}, "optimization.solver.mma"),
    ("mma_unknown_key", S,
     {"optimization.solver.mma.m": 0}, "optimization.solver.mma"),
    ("mma_max_iter_real", S,
     {"optimization.solver.mma.max_iter": 100.0}, "optimization.solver.mma"),
    # the steepest_descent block is read for steepest_descent only.
    ("mma_with_steepest_descent_block", S,
     {"optimization.solver.steepest_descent": {"xmin": 0.0}},
     "optimization.solver"),
    ("steepest_descent_with_mma_block", U,
     {"optimization.solver.mma": {"scale": 1.0}}, "optimization.solver"),
    # mma_optimizer.f90:134: tolerance is an mma key.
    ("steepest_descent_tolerance", U,
     {"optimization.solver.tolerance": 1.0e-6}, "optimization.solver"),
    # steepest_descent_optimizer.f90:182: no constraints.
    ("steepest_descent_with_constraints", U,
     {"optimization.constraints": [{"type": "volume", "limit": 0.5}]},
     "constraints"),
    # steepest_descent_optimizer.f90:219,223,238,242
    ("steepest_descent_step_length_zero", U,
     {"optimization.solver.steepest_descent.step_length": 0.0},
     "steepest_descent"),
    ("steepest_descent_move_limit_min_zero", U,
     {"optimization.solver.steepest_descent.move_limit.min": 0.0},
     "move_limit"),
    ("steepest_descent_decrease_above_one", U,
     {"optimization.solver.steepest_descent.move_limit.decrease": 1.5},
     "move_limit"),
    ("steepest_descent_increase_below_one", U,
     {"optimization.solver.steepest_descent.move_limit.increase": 0.9},
     "move_limit"),
    # optimizer.f90:446: json_get_or_default type check.
    ("checkpoint_interval_real", S,
     {"optimization.solver.checkpoint.interval": 1.0}, "checkpoint"),
    ("continuation_iterations_real", S,
     {"optimization.solver.continuation_iterations": 2.0},
     "optimization.solver"),
    # ---- state recovery ---------------------------------------------------
    # checkpoint_linear.f90:69, checkpoint.f90:425
    ("n_memory_zero", U, {"state_recovery.n_memory": 0}, "state_recovery"),
    ("n_memory_negative", U, {"state_recovery.n_memory": -1},
     "state_recovery"),
    # checkpoint.f90:220
    ("state_recovery_algorithm", U,
     {"state_recovery.algorithm": "binomial"}, "state_recovery"),
    # state_recover_fctry.f90:75
    ("state_recovery_type", U, {"state_recovery.type": "memory"},
     "state_recovery"),
    ("state_recovery_format", U, {"state_recovery.format": "h5"},
     "state_recovery"),
    # `enabled` is not read.
    ("state_recovery_enabled", U, {"state_recovery.enabled": True},
     "state_recovery"),
    # simulation.f90:287
    ("unsteady_without_state_recovery", U, {"state_recovery": DEL}, "$"),
    # state_recovery is not read without unsteady.
    ("state_recovery_without_unsteady", U, {"unsteady": False}, "$"),
    ("state_recovery_in_steady_case", S,
     {"state_recovery": {"type": "checkpoint"}}, "$"),
    ("unsteady_integer", U, {"unsteady": 1}, "$.unsteady"),
    # simulation.f90:283
    ("unsteady_with_variable_timestep", U,
     {"case.time.variable_timestep": True, "case.time.max_timestep": 1.0e-2},
     "variable_timestep"),
    # ---- optimization object ---------------------------------------------
    ("optimization_unknown_key", S, {"optimization.cost": 1.0},
     "$.optimization"),
    ("augmented_lagrangian_integer", S,
     {"optimization.augmented_lagrangian": {"dealias_sensitivity": 1}},
     "augmented_lagrangian"),
    ("time_window_test_unknown_key", S,
     {"optimization.time_window_test": {"tol": 1.0}}, "time_window_test"),
    # ---- adjoint fluid ----------------------------------------------------
    # neko_ext.f90:356: reset_adjoint reads it with no fallback.
    ("adjoint_fluid_missing", S, {"case.adjoint_fluid": DEL}, "$.case"),
    ("adjoint_fluid_without_initial_condition", S,
     {"case.adjoint_fluid.initial_condition": DEL}, "adjoint_fluid"),
    # neko_ext.f90:372
    ("adjoint_fluid_ic_user", S,
     {"case.adjoint_fluid.initial_condition": {"type": "user"}},
     "adjoint_fluid.initial_condition"),
    ("adjoint_fluid_ic_unknown", S,
     {"case.adjoint_fluid.initial_condition": {"type": "random"}},
     "adjoint_fluid.initial_condition"),
    # adjoint_fluid_pnpn.f90:1042-1068
    ("adjoint_bc_symmetry", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "symmetry", "zone_indices": [1]}}, "boundary_conditions[0]"),
    ("adjoint_bc_shear_stress", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "shear_stress", "zone_indices": [1]}}, "boundary_conditions[0]"),
    ("adjoint_bc_wall_model", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "wall_model", "zone_indices": [1]}}, "boundary_conditions[0]"),
    # adjoint_fluid_pnpn.f90:1000: zone_indices is a literal array.
    ("adjoint_bc_zone_indices_constant", S,
     {"case.adjoint_fluid.boundary_conditions[0].zone_indices": "walls"},
     "boundary_conditions[0]"),
    ("adjoint_bc_without_zone_indices", S,
     {"case.adjoint_fluid.boundary_conditions[0].zone_indices": DEL},
     "boundary_conditions[0]"),
    ("adjoint_bc_unknown_type", S,
     {"case.adjoint_fluid.boundary_conditions[0].type": "slip"},
     "boundary_conditions[0]"),
    # neko src/bc/inflow.f90:77: velocity_value needs a value.
    ("adjoint_bc_velocity_value_without_value", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "velocity_value", "zone_indices": [1]}},
     "boundary_conditions[0]"),
    # adjoint_case.f90:452-463
    ("adjoint_output_control_unknown", S,
     {"case.adjoint_fluid.output_control": "always"}, "adjoint_fluid"),
    ("adjoint_output_control_without_value", S,
     {"case.adjoint_fluid.output_control": "tsteps"}, "adjoint_fluid"),
    ("adjoint_output_value_unread", S,
     {"case.adjoint_fluid.output_control": "never",
      "case.adjoint_fluid.output_value": 5}, "adjoint_fluid"),
    ("adjoint_output_value_zero", S,
     {"case.adjoint_fluid.output_control": "tsteps",
      "case.adjoint_fluid.output_value": 0}, "adjoint_fluid"),
    ("adjoint_output_value_real_for_tsteps", S,
     {"case.adjoint_fluid.output_control": "tsteps",
      "case.adjoint_fluid.output_value": 5.0}, "adjoint_fluid"),
    ("adjoint_output_value_integer_for_time", S,
     {"case.adjoint_fluid.output_control": "simulationtime",
      "case.adjoint_fluid.output_value": 5}, "adjoint_fluid"),
    # adjoint_case.f90:468-477
    ("adjoint_norm_value_unread", S,
     {"case.adjoint_fluid.norm_output_value": 2.0}, "adjoint_fluid"),
    ("adjoint_norm_value_constant", S,
     {"case.adjoint_fluid.norm_output_control": "tsteps",
      "case.adjoint_fluid.norm_output_value": "k"}, "adjoint_fluid"),
    ("adjoint_norm_file_suffix", S,
     {"case.adjoint_fluid.norm_output_control": "tsteps",
      "case.adjoint_fluid.norm_output_file": "norm.dat"}, "adjoint_fluid"),
    ("adjoint_output_format", S,
     {"case.adjoint_fluid.output_format": "csv"}, "adjoint_fluid"),
    ("adjoint_fluid_unknown_key", S,
     {"case.adjoint_fluid.enabled": True}, "adjoint_fluid"),
    # adjoint_fluid_scheme_incompressible.f90:211-336: literal reals/ints.
    ("adjoint_velocity_solver_tolerance_constant", S,
     {"case.adjoint_fluid.velocity_solver":
      {"absolute_tolerance": "tol"}}, "adjoint_fluid.velocity_solver"),
    ("adjoint_velocity_solver_max_iterations_constant", S,
     {"case.adjoint_fluid.velocity_solver": {"max_iterations": "n"}},
     "adjoint_fluid.velocity_solver"),
    ("adjoint_pressure_solver_unknown_key", S,
     {"case.adjoint_fluid.pressure_solver": {"type": "cg"}},
     "adjoint_fluid.pressure_solver"),
    ("adjoint_pressure_solver_projection_constant", S,
     {"case.adjoint_fluid.pressure_solver":
      {"projection_hold_steps": "h"}}, "adjoint_fluid.pressure_solver"),
    # ---- adjoint scalar ---------------------------------------------------
    # adjoint_case.f90:309-312
    ("adjoint_scalar_without_initial_condition", S,
     {"case.adjoint_scalar.initial_condition": DEL}, "adjoint_scalar"),
    # adjoint_case.f90:332
    ("adjoint_scalar_ic_user", S,
     {"case.adjoint_scalar.initial_condition": {"type": "user"}},
     "adjoint_scalar.initial_condition"),
    # adjoint_scalar_pnpn_bc_fctry.f90:89
    ("adjoint_scalar_bc_user_dirichlet", S,
     {"case.adjoint_scalar.boundary_conditions[0].type": "user_dirichlet"},
     "adjoint_scalar.boundary_conditions[0]"),
    ("adjoint_scalar_bc_zone_indices_constant", S,
     {"case.adjoint_scalar.boundary_conditions[0].zone_indices": "inlet"},
     "adjoint_scalar.boundary_conditions[0]"),
    # neko src/bc/dirichlet.f90:80: the value is a real or a name, not 0.
    ("adjoint_scalar_dirichlet_without_value", S,
     {"case.adjoint_scalar.boundary_conditions[0].value": DEL},
     "adjoint_scalar.boundary_conditions[0]"),
    # adjoint_scalar_scheme.f90:355
    ("adjoint_scalar_variable_material_properties", S,
     {"case.adjoint_scalar.variable_material_properties": {}},
     "adjoint_scalar"),
    ("adjoint_scalar_unknown_key", S,
     {"case.adjoint_scalar.Pe": 5.0}, "adjoint_scalar"),
    ("adjoint_scalar_solver_tolerance_constant", S,
     {"case.adjoint_scalar.solver": {"absolute_tolerance": "tol"}},
     "adjoint_scalar.solver"),
    # adjoint_scalar_scheme.f90:281,341: names that cannot match.
    ("adjoint_scalar_primal_name_mismatch_default", S,
     {"case.adjoint_scalar.primal_name": "temperature"}, "adjoint_scalar"),
    ("adjoint_scalar_primal_name_missing_for_named_scalar", S,
     {"case.scalar.name": "temperature"}, "adjoint_scalar"),
    # adjoint_case.f90:252
    ("adjoint_scalars_array", S,
     {"case.adjoint_scalar": DEL, "case.scalar.enabled": False,
      "case.adjoint_scalars": [{"primal_name": "s"}]}, "adjoint_scalars"),
]

# --------------------------------------------------------------------------- #
# Keys the code reads without a constants lookup: a JSON real (or integer)
# only. (id, base, path, valid value, value that is a constants name or of
# the wrong number kind)
# --------------------------------------------------------------------------- #
LITERAL_ONLY_KEYS = [
    ("design_initial_value", S,
     "optimization.design.initial_distribution.value", 0.5, "v0"),
    ("pde_filter_tol", S, "optimization.design.mapping[0].tol", 1.0e-8, "t"),
    ("heaviside_eta", S, "optimization.design.mapping[1].eta", 0.4, "eta"),
    ("volume_limit", S, "optimization.constraints[0].limit", 0.2, "limit"),
    ("objective_start_time", S, "optimization.objectives[0].start_time",
     0.0, "t0"),
    ("mma_scale", S, "optimization.solver.mma.scale", 10.0, "scale"),
    ("mma_xmax", S, "optimization.solver.mma.xmax", 1.0, "xmax"),
    ("solver_tolerance", S, "optimization.solver.tolerance", 1.0e-6, "tol"),
    ("steady_tol", S, "case.simulation_components[0].tol", 1.0e-6, "tol"),
    ("root_norm_scaling", S, "norm_scaling", 0.5, "s"),
    ("adjoint_norm_output_value", S,
     "case.adjoint_fluid.norm_output_value", 1.0, "n"),
    ("adjoint_velocity_tolerance", S,
     "case.adjoint_fluid.velocity_solver.absolute_tolerance", 1.0e-6, "t"),
    ("adjoint_zone_indices", S,
     "case.adjoint_fluid.boundary_conditions[0].zone_indices", [1, 3, 4, 5, 6],
     "walls"),
]

# The key is read only next to another one.
LITERAL_PRE_EDITS = {
    "adjoint_norm_output_value": {
        "case.adjoint_fluid.norm_output_control": "tsteps"},
}

# Keys whose value goes through a constants lookup (Neko's reader): a name is
# accepted. (id, base, path, name)
LOOKUP_KEYS = [
    ("adjoint_velocity_value", S,
     "case.adjoint_fluid.boundary_conditions[0]",
     {"type": "velocity_value", "zone_indices": [1], "value": "u"}),
    ("adjoint_scalar_dirichlet_value", S,
     "case.adjoint_scalar.boundary_conditions[0].value", "T0"),
    ("adjoint_scalar_ic_value", S,
     "case.adjoint_scalar.initial_condition.value", "T0"),
]

# --------------------------------------------------------------------------- #
# Neko-TOP registers these types in Neko's unions; they are accepted through
# Neko's registered-type fallback, with their keys typed by overlays.
# (id, base, edits, accepted)
# --------------------------------------------------------------------------- #
REGISTERED_BY_NEKO_TOP = [
    ("simcomp_steady", S,
     {"case.simulation_components[0]": {"type": "steady"}}, True),
    ("simcomp_steady_with_base_keys", S,
     {"case.simulation_components[0]":
      {"type": "steady", "compute_control": "tsteps", "compute_value": 5,
       "tol": 1e-8}}, True),
    ("simcomp_steady_log_frequency_zero", S,
     {"case.simulation_components[0]":
      {"type": "steady", "log_frequency": 0}}, False),
    ("simcomp_steady_tol_integer", S,
     {"case.simulation_components[0]": {"type": "steady", "tol": 1}}, False),
    ("simcomp_steady_scalar_coupled_string", S,
     {"case.simulation_components[0]":
      {"type": "steady", "scalar_coupled": "yes"}}, False),
    ("simcomp_steady_base_key_wrong", S,
     {"case.simulation_components[0]":
      {"type": "steady", "compute_control": "sometimes"}}, False),
]
for _name in ("simple_brinkman", "adjoint_brinkman_dissipation",
              "adjoint_viscous_dissipation", "adjoint_scalar_convection",
              "adjoint_mixing_scalar"):
    REGISTERED_BY_NEKO_TOP += [
        (f"fluid_source_term_{_name}", S,
         {"case.fluid.source_terms": [{"type": _name}]}, True),
        (f"scalar_source_term_{_name}", S,
         {"case.scalar.source_terms": [{"type": _name}]}, True),
        (f"adjoint_source_term_{_name}", S,
         {"case.adjoint_fluid.source_term": [{"type": _name}]}, True),
    ]
REGISTERED_BY_NEKO_TOP += [
    # No key of theirs is read (empty init_from_json): extra keys are
    # rejected, as for any closed built-in object.
    ("fluid_source_term_simple_brinkman_extra_key", S,
     {"case.fluid.source_terms": [{"type": "simple_brinkman",
                                    "start_time": 0.0}]}, False),
    ("adjoint_source_term_extra_key", S,
     {"case.adjoint_fluid.source_term": [{"type": "adjoint_mixing_scalar",
                                           "value": 1.0}]}, False),
    # An unknown type is a registered one, as far as Neko can tell.
    ("fluid_source_term_unknown_type", S,
     {"case.fluid.source_terms": [{"type": "my_source", "my_key": 1}]}, True),
]

# Neko's own registered-type cases (tests/integration/tests/test_case_schema)
# must still pass with the Neko-TOP root. (id, base, edits)
NEKO_REGISTERED_TYPES = [
    ("simcomp", S, {"case.simulation_components[1]":
                    {"type": "my_simcomp", "my_key": [1, 2],
                     "compute_control": "tsteps", "compute_value": 10}}),
    ("fluid_source_term", S, {"case.fluid.source_terms":
                              [{"type": "my_source", "my_key": "value"}]}),
    ("scalar_source_term", S, {"case.scalar.source_terms":
                               [{"type": "my_source", "my_key": "value"}]}),
    ("point_zone", S, {"case.point_zones[2]":
                       {"name": "mine", "geometry": "my_geometry",
                        "my_key": 1.0}}),
    ("les_model", N, {"case.simulation_components":
                      [{"type": "les_model", "model": "my_model",
                        "my_key": 1.0}]}),
    ("preconditioner", N, {"case.fluid.velocity_solver.preconditioner":
                           {"type": "my_precon", "my_key": 1.0}}),
]

# --------------------------------------------------------------------------- #
# Neko-TOP's own objects are closed: an unknown key is rejected. Objects that
# Neko leaves open (and Neko-TOP leaves open with them) are listed apart.
# (id, base, path of the object)
# --------------------------------------------------------------------------- #
NEKO_TOP_OBJECTS_STAY_CLOSED = [
    ("optimization", S, "optimization"),
    ("design", S, "optimization.design"),
    ("design_domain", S, "optimization.design.domain"),
    ("initial_distribution", S, "optimization.design.initial_distribution"),
    ("mapping_pde_filter", S, "optimization.design.mapping[0]"),
    ("mapping_heaviside", S, "optimization.design.mapping[1]"),
    ("mapping_ramp", S, "optimization.design.mapping[2]"),
    ("mapping_linear", S, "optimization.constraints[0].mapping[0]"),
    ("objective_scalar_mixing", S, "optimization.objectives[0]"),
    ("objective_viscous_dissipation", S, "optimization.objectives[1]"),
    ("objective_brinkman_dissipation", U, "optimization.objectives[0]"),
    ("constraint_volume", S, "optimization.constraints[0]"),
    ("solver_mma", S, "optimization.solver"),
    ("solver_mma_block", S, "optimization.solver.mma"),
    ("solver_checkpoint", S, "optimization.solver.checkpoint"),
    ("solver_steepest_descent", U, "optimization.solver"),
    ("solver_steepest_descent_block", U,
     "optimization.solver.steepest_descent"),
    ("solver_move_limit", U,
     "optimization.solver.steepest_descent.move_limit"),
    ("state_recovery", U, "state_recovery"),
    ("adjoint_fluid", S, "case.adjoint_fluid"),
    ("adjoint_fluid_ic", S, "case.adjoint_fluid.initial_condition"),
    ("adjoint_scalar", S, "case.adjoint_scalar"),
]
NEKO_TOP_OBJECTS_STAY_OPEN = [
    ("root", S, ""),
    ("case", S, "case"),
    ("fluid", S, "case.fluid"),
    ("scalar", S, "case.scalar"),
    ("steady_simcomp", S, "case.simulation_components[0]"),
    ("adjoint_velocity_solver", S, "case.adjoint_fluid.velocity_solver"),
    ("adjoint_scalar_solver", S, "case.adjoint_scalar.solver"),
]

# --------------------------------------------------------------------------- #
# Restrictions of a case with an `optimization` object: the same edit makes a
# case that Neko's drivers accept (no `optimization`) and that the topology
# optimisation drivers abort on. (id, base, edits, path fragment)
# --------------------------------------------------------------------------- #
RESTART = {"case.restart_file": "restart.chkp"}
SCALAR_ITEM = {"Pe": 1.0,
               "initial_condition": {"type": "uniform", "value": 0.0},
               "solver": {"type": "cg", "preconditioner": {"type": "jacobi"},
                          "absolute_tolerance": 1e-6}}
OPTIMIZING_RESTRICTIONS = [
    # adjoint_fluid_fctry.f90:60
    ("fluid_scheme_compressible", S, {"case.fluid.scheme": "compressible",
      "case.fluid.boundary_conditions":
      [{"type": "no_slip", "zone_indices": [1, 3, 4, 5, 6]},
       {"type": "outflow", "zone_indices": [2]}]},
     "case.fluid.scheme"),
    # adjoint_fluid_pnpn.f90:316
    ("full_stress_formulation", S,
     {"case.fluid.full_stress_formulation": True}, "full_stress"),
    # adjoint_fluid_pnpn.f90:338
    ("nut_field", S, {"case.fluid.full_stress_formulation": True,
                      "case.fluid.nut_field": "nut"}, "full_stress"),
    # adjoint_fluid_scheme_incompressible.f90:242
    ("flow_rate_force", S,
     {"case.fluid.flow_rate_force": {"direction": "X", "value": 1.0,
                                      "use_averaged_flow": False}},
     "case.fluid"),
    # adjoint_curl_curl.f90:136
    ("cyclic", S, {"case.fluid.cyclic": True}, "cyclic"),
    # advection_adjoint_fctry.f90:105, adjoint_fluid_pnpn.f90:741
    ("oifs", S, {"case.numerics.oifs": True}, "oifs"),
    ("oifs_without_advection", S,
     {"case.numerics.oifs": True, "case.fluid.advection": False}, "oifs"),
    # adjoint_fluid_scheme_incompressible.f90:716,728,729
    ("re_constant", S, {"case.fluid.Re": "Re"}, "case.fluid.Re"),
    ("mu_rho_constants", S,
     {"case.fluid.Re": DEL, "case.fluid.mu": "mu", "case.fluid.rho": 1.0},
     "case.fluid.mu"),
    # adjoint_fluid_pnpn.f90:309, adjoint_case.f90:136,
    # advection_adjoint_fctry.f90:100
    ("time_order_constant", S, {"case.numerics.time_order": "order"},
     "time_order"),
    ("polynomial_order_constant", S, {"case.numerics.polynomial_order": "p"},
     "polynomial_order"),
    ("dealiased_polynomial_order_constant", S,
     {"case.numerics.dealiased_polynomial_order": "q"},
     "dealiased_polynomial_order"),
    # adjoint_fluid_pnpn.f90:411-420
    ("pressure_solver_tolerance_constant", S,
     {"case.fluid.pressure_solver.absolute_tolerance": "ptol"},
     "pressure_solver"),
    ("pressure_solver_max_iterations_constant", S,
     {"case.fluid.pressure_solver.max_iterations": "pmax"},
     "pressure_solver"),
    ("pressure_solver_projection_constant", S,
     {"case.fluid.pressure_solver.projection_space_size": "k"},
     "pressure_solver"),
    # adjoint_fluid_scheme_incompressible.f90:211-336: read from the primal
    # solver while the adjoint's own block has no such key.
    ("velocity_solver_tolerance_constant", S,
     {"case.fluid.velocity_solver.absolute_tolerance": "vtol"},
     "velocity_solver"),
    ("velocity_solver_max_iterations_constant", S,
     {"case.fluid.velocity_solver.max_iterations": "vmax"},
     "velocity_solver"),
    # neko_ext.f90:170: the initial conditions are read at every iteration,
    # also when the case restarts.
    ("fluid_initial_condition_with_restart", S,
     dict(RESTART, **{"case.fluid.initial_condition": DEL}),
     "case.fluid"),
    ("scalar_initial_condition_with_restart", S,
     dict(RESTART, **{"case.scalar.initial_condition": DEL}),
     "case.scalar"),
    # neko_ext.f90:404: no adjoint scalar for an enabled scalar.
    ("scalar_without_adjoint_scalar", S,
     {"case.adjoint_scalar": DEL, "optimization.objectives[0]":
      {"type": "viscous_dissipation"}}, "$.case"),
    ("scalar_with_disabled_adjoint_scalar", S,
     {"case.adjoint_scalar.enabled": False, "optimization.objectives[0]":
      {"type": "viscous_dissipation"}}, "adjoint_scalar"),
    # adjoint_case.f90:204: an adjoint scalar needs the scalar.
    ("adjoint_scalar_without_scalar", S,
     {"case.scalar": DEL, "optimization.objectives[0]":
      {"type": "viscous_dissipation"}}, "$.case"),
    ("adjoint_scalar_with_disabled_scalar", S,
     {"case.scalar.enabled": False, "optimization.objectives[0]":
      {"type": "viscous_dissipation"}}, "scalar"),
    # adjoint_scalar_scheme.f90:616-637
    ("scalar_pe_constant", S, {"case.scalar.Pe": "Pe"}, "scalar.Pe"),
    ("scalar_lambda_cp_constants", S,
     {"case.scalar.Pe": DEL, "case.scalar.lambda": "k",
      "case.scalar.cp": 1.0}, "scalar.lambda"),
    # adjoint_scalar_scheme.f90:355-358
    ("scalar_variable_material_properties", S,
     {"case.scalar.variable_material_properties": {"lambda": {"type": "x"}}},
     "case.scalar"),
    ("scalar_solver_tolerance_constant", S,
     {"case.scalar.solver.absolute_tolerance": "stol"}, "scalar.solver"),
    # adjoint_curl_curl.f90:128-134
    ("primal_symmetry_boundary", S,
     {"case.fluid.boundary_conditions[2]":
      {"type": "symmetry", "zone_indices": [7]}}, "boundary_conditions"),
    ("primal_split_symmetry_boundary", S,
     {"case.fluid.boundary_conditions[2]":
      {"velocity": {"type": "symmetry"}, "pressure": {"type": "outflow"},
       "zone_indices": [7]}}, "boundary_conditions"),
    # adjoint_case.f90:252
    ("adjoint_scalars", S,
     {"case.scalar.enabled": False, "case.adjoint_scalar": DEL,
      "case.adjoint_scalars": [{"primal_name": "s"}],
      "optimization.objectives[0]": {"type": "viscous_dissipation"}},
     "adjoint_scalars"),
    # steady_simcomp.f90:149
    ("steady_with_two_scalars", S,
     {"case.scalars": [dict(SCALAR_ITEM, name="a"),
                       dict(SCALAR_ITEM, name="b")]},
     "scalars"),
    # scalar_mixing_objective_function.f90:171
    ("scalar_mixing_without_adjoint_scalar", S,
     {"case.scalar.enabled": False, "case.adjoint_scalar.enabled": False},
     "adjoint_scalar"),
    # brinkman_dissipation_objective.f90:150-162: one flag differs from
    # case.numerics.dealias, which it defaults the other to.
    ("brinkman_single_dealias_flag", U,
     {"optimization.objectives[0].dealias_sensitivity": False,
      "optimization.objectives[0].dealias_forcing": DEL}, "objectives[0]"),
    # simulation.f90:283
    ("unsteady_variable_timestep", U,
     {"case.time.variable_timestep": True, "case.time.max_timestep": 1.0e-2},
     "variable_timestep"),
    # Owner ruling 2026-11-16: steady simulation component, unsteady run.
    ("steady_simcomp_in_unsteady_run", U,
     {"case.simulation_components": [{"type": "steady"}]},
     "simulation_components"),
]
# Edits that need a Neko-valid case without `optimization` to compare with.
_WITHOUT_OPTIMIZATION_EXTRA = {
    "unsteady_variable_timestep": {"unsteady": False, "state_recovery": DEL},
    "steady_simcomp_in_unsteady_run": {"unsteady": False,
                                       "state_recovery": DEL},
}


def _without_optimization(base, edits, name):
    """The case of the row with the `optimization` object removed."""
    edits = {k: v for k, v in edits.items() if not k.startswith("optimization")}
    edits["optimization"] = DEL
    edits.update(_WITHOUT_OPTIMIZATION_EXTRA.get(name, {}))
    return build(base, edits)


def ids(table):
    return [row[0] for row in table]


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, base, edits", ACCEPTED_BY_THE_CODE,
                         ids=ids(ACCEPTED_BY_THE_CODE))
def test_accepted_by_the_code(validator, name, base, edits):
    found = errors(validator, build(base, edits))
    assert not found, short(found)


@pytest.mark.parametrize("name, base, edits, where",
                         REJECTED_AS_THE_CODE_ABORTS,
                         ids=ids(REJECTED_AS_THE_CODE_ABORTS))
def test_rejected_as_the_code_aborts(validator, name, base, edits, where):
    paths = error_paths(validator, build(base, edits))
    assert paths, f"{name} is accepted"
    assert any(where in path for path in paths), (
        f"{name}: rejected, but not at {where}: {sorted(paths)}")


@pytest.mark.parametrize("name, base, path, good, bad", LITERAL_ONLY_KEYS,
                         ids=ids(LITERAL_ONLY_KEYS))
def test_literal_only_keys(validator, name, base, path, good, bad):
    pre = LITERAL_PRE_EDITS.get(name, {})
    assert not errors(validator, build(base, dict(pre, **{path: good})))
    assert error_paths(validator, build(base, dict(pre, **{path: bad})))
    if isinstance(good, float):
        # json-fortran stores 1 and 1.0 as different types; the reader of a
        # real rejects the integer (neko src/common/json_utils.f90:510).
        assert error_paths(
            validator, build(base, dict(pre, **{path: int(good)}))), (
            f"{name}: an integer is accepted where a real is read")


@pytest.mark.parametrize("name, base, path, value", LOOKUP_KEYS,
                         ids=ids(LOOKUP_KEYS))
def test_lookup_keys_accept_names(validator, name, base, path, value):
    found = errors(validator, build(base, {path: value}))
    assert not found, short(found)


@pytest.mark.parametrize("name, base, edits, accepted",
                         REGISTERED_BY_NEKO_TOP,
                         ids=ids(REGISTERED_BY_NEKO_TOP))
def test_registered_by_neko_top(validator, name, base, edits, accepted):
    found = errors(validator, build(base, edits))
    if accepted:
        assert not found, short(found)
    else:
        assert found, f"{name} is accepted"


@pytest.mark.parametrize("name, base, edits", NEKO_REGISTERED_TYPES,
                         ids=ids(NEKO_REGISTERED_TYPES))
def test_nekos_registered_types_still_pass(validator, name, base, edits):
    found = errors(validator, build(base, edits))
    assert not found, short(found)


@pytest.mark.parametrize("name, base, path", NEKO_TOP_OBJECTS_STAY_CLOSED,
                         ids=ids(NEKO_TOP_OBJECTS_STAY_CLOSED))
def test_neko_top_objects_stay_closed(validator, name, base, path):
    instance = copy.deepcopy(load_base(base))
    assert not errors(validator, instance)
    ensure_object(instance, path)["no_such_key_anywhere"] = 1.0
    assert error_paths(validator, instance), f"{name} accepts an unknown key"


@pytest.mark.parametrize("name, base, path", NEKO_TOP_OBJECTS_STAY_OPEN,
                         ids=ids(NEKO_TOP_OBJECTS_STAY_OPEN))
def test_objects_neko_leaves_open_stay_open(validator, name, base, path):
    instance = copy.deepcopy(load_base(base))
    ensure_object(instance, path)["no_such_key_anywhere"] = 1.0
    found = errors(validator, instance)
    assert not found, short(found)


@pytest.mark.parametrize("name, base, edits, where",
                         OPTIMIZING_RESTRICTIONS,
                         ids=ids(OPTIMIZING_RESTRICTIONS))
def test_optimizing_restrictions(validator, neko_validator, name, base,
                                 edits, where):
    """Accepted without `optimization` (where Neko's own root accepts it
    too), rejected with it."""
    with_optimization = build(base, edits)
    paths = error_paths(validator, with_optimization)
    assert paths, f"{name} is accepted with `optimization`"
    assert any(where in path for path in paths), (
        f"{name}: rejected, but not at {where}: {sorted(paths)}")
    without = _without_optimization(base, edits, name)
    found = errors(validator, without)
    assert not found, f"{name} without `optimization`: {short(found)}"
    found = errors(neko_validator, without)
    assert not found, f"{name}: Neko's own root rejects it: {short(found)}"


def test_optimizing_restrictions_have_a_pair_each():
    assert len(set(ids(OPTIMIZING_RESTRICTIONS))) == len(
        OPTIMIZING_RESTRICTIONS)


def _accepted_instances():
    for name, base, edits in ACCEPTED_BY_THE_CODE:
        yield name, build(base, edits)
    for name, base, edits, accepted in REGISTERED_BY_NEKO_TOP:
        if accepted:
            yield name, build(base, edits)
    for name, base, edits in NEKO_REGISTERED_TYPES:
        yield name, build(base, edits)
    for base in (S, U, N):
        yield f"fixture_{base}", load_base(base)


def test_what_the_neko_top_root_accepts_neko_accepts(validator,
                                                     neko_validator):
    """The subset invariant: Neko-TOP's schemas only narrow or add under
    open objects, so every instance of this suite that the Neko-TOP root
    accepts passes Neko's root as well."""
    count = 0
    for name, instance in _accepted_instances():
        if not errors(validator, instance):
            found = errors(neko_validator, instance)
            assert not found, f"{name}: {short(found)}"
            count += 1
    assert count > 40
