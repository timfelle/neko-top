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

import validate_case_schema as vcs
from schema_helpers import (DEL, build, ensure_object, error_paths, errors,
                            load_base, short)

S, U, N = "steady", "unsteady", "neko"

SCALAR_ITEM = {"Pe": 1.0,
               "initial_condition": {"type": "uniform", "value": 0.0},
               "solver": {"type": "cg", "preconditioner": {"type": "jacobi"},
                          "absolute_tolerance": 1e-6}}

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
    # cg.f90:189-267: max_iter 1 runs (with a warning) unless strict, and a
    # strict Krylov solver other than cheby can converge.
    ("pde_filter_max_iter_one_nonstrict", S,
     {"optimization.design.mapping[0].max_iter": 1}),
    ("pde_filter_cheby_nonstrict", S,
     {"optimization.design.mapping[0].solver": "cheby"}),
    ("pde_filter_cheby_strict_false", S,
     {"optimization.design.mapping[0].solver": "cheby",
      "optimization.design.mapping[0].strict_convergence": False}),
    ("pde_filter_gmres_strict_max_iter_two", S,
     {"optimization.design.mapping[0].solver": "gmres",
      "optimization.design.mapping[0].max_iter": 2,
      "optimization.design.mapping[0].strict_convergence": True}),
    # utils.f90:499: an all-blank max_runtime is no limit, like ''.
    ("design_name_long_with_blank_max_runtime", S,
     {"optimization.design.name": "a" * 70,
      "optimization.solver.max_runtime": " ",
      "optimization.solver.checkpoint.interval": 0}),
    ("design_name_long_with_empty_restart_and_runtime", S,
     {"optimization.design.name": "a" * 70,
      "optimization.solver.restart_file": "",
      "optimization.solver.max_runtime": "",
      "optimization.solver.checkpoint.interval": 0}),
    # mma_cpu.f90:917-919: below 1 the subproblem runs.
    ("mma_epsimin_half", S, {"optimization.solver.mma.epsimin": 0.5}),
    # mma_cpu.f90:966: dip with a = 0 ignores a0.
    ("mma_a0_negative_dip_a_zero", S,
     {"optimization.solver.mma.a0": -1.0}),
    ("mma_a0_zero_pdip", S,
     {"optimization.solver.mma.subsolver": "pdip",
      "optimization.solver.mma.a0": 0.0}),
    ("mma_c_negative_dip_unconstrained", S,
     {"optimization.constraints": [], "optimization.solver.mma.c": -1.0}),
    # optimizer.f90:826-861: the longest names that still fit in 256.
    ("checkpoint_base_233_default_path", S,
     {"optimization.solver.checkpoint.base": "b" * 233}),
    ("checkpoint_path_226_default_base", S,
     {"optimization.solver.checkpoint.path": "p" * 226}),
    ("checkpoint_path_227_slash_default_base", S,
     {"optimization.solver.checkpoint.path": "p" * 226 + "/"}),
    ("checkpoint_path_and_base_given", S,
     {"optimization.solver.checkpoint.path": "p" * 200,
      "optimization.solver.checkpoint.base": "b" * 40}),
    ("fd_test_tolerance_positive", S,
     {"optimization.fd_test_tolerance": 1.0e-3}),
    ("time_window_tolerance_zero", U,
     {"optimization.time_window_test": {"tolerance": 0.0}}),
    # PDE_filter_mapping.f90:436: ident is initialised by its constructor.
    ("pde_filter_ident", S,
     {"optimization.design.mapping[0].preconditioner": "ident"}),
    # design_brinkman.f90:293: SP/DP spellings.
    ("design_output_precision_DP", S,
     {"optimization.design.output_precision": "DP"}),
    # design_brinkman.f90:302: point_zone domain with its zone.
    ("design_domain_full", S,
     {"optimization.design.domain": {"type": "full"}}),
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
    # checkpoint.f90:161: extra fields are looked up by name, and the
    # unsteady fixture has no scalar, so it registers `u` but not `s`. `u` is
    # harmless at run time (the finite-difference error equals the control).
    ("state_recovery_extra_fields", U,
     {"state_recovery.extra_fields": ["u"]}),
    ("state_recovery_alias_and_case", U,
     {"state_recovery.type": "simulation_checkpoint",
      "state_recovery.algorithm": "LINEAR"}),
    # Neko itself: an unknown simulation component is a registered one.
    ("unknown_simcomp_type", S,
     {"case.simulation_components[1]": {"type": "my_simcomp", "my_key": 1}}),
    # neko_ext.f90: freeze_flow is a boolean read at every iteration.
    ("freeze_flow", S, {"case.fluid.freeze_flow": True,
                         "case.adjoint_fluid.freeze_flow": True}),
    # --- round 1 of the code audit ---------------------------------------
    # neko src/common/utils.f90:598,662: read_duration trims the string and
    # does a list-directed read of the seconds.
    ("max_runtime_exponent", S, {"optimization.solver.max_runtime": "1e3"}),
    ("max_runtime_fortran_d", S, {"optimization.solver.max_runtime": "1d3"}),
    ("max_runtime_trailing_point", S,
     {"optimization.solver.max_runtime": "5."}),
    ("max_runtime_leading_point", S, {"optimization.solver.max_runtime": ".5"}),
    ("max_runtime_sign", S, {"optimization.solver.max_runtime": "+5"}),
    ("max_runtime_hms_point", S, {"optimization.solver.max_runtime": "1:2:3."}),
    ("max_runtime_padded", S, {"optimization.solver.max_runtime": " 3600"}),
    ("steepest_descent_max_runtime_exponent", U,
     {"optimization.solver.max_runtime": "1e3"}),
    # heaviside_mapping.f90:162-164: only a later 0.0 aborts; a negative beta
    # gives the same map as its absolute value.
    ("heaviside_later_negative_beta", S,
     {"optimization.design.mapping[1].beta": [1.0, -2.0],
      "optimization.design.mapping[1].beta_iterations": 2}),
    # PDE_filter_mapping.f90:138
    ("pde_filter_max_iter_one", S,
     {"optimization.design.mapping[0].max_iter": 1}),
    # RAMP_mapping_cpu.f90:96: well defined for -1 < q < 0.
    ("ramp_q_minus_half", S, {"optimization.design.mapping[2].q": -0.5}),
    # Borrvall_Petersson_mapping_cpu.f90:97: monotone for q > 0 and q < -1.
    ("bp_q_positive", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": 0.5}),
    ("bp_q_below_minus_one", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": -2.0}),
    # SIMP_mapping_cpu.f90:93,110: finite for p >= 1.
    ("simp_p_one", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p": 1.0}),
    # design_brinkman.f90:284: `bp` is the same file as `adios2`.
    ("design_output_format_bp", S,
     {"optimization.design.output_format": "bp"}),
    # steepest_descent_optimizer.f90:194-235: a key against the default of
    # its sibling that is absent.
    ("sd_xmin_below_default_xmax", U,
     {"optimization.solver.steepest_descent.xmin": 0.5,
      "optimization.solver.steepest_descent.xmax": DEL}),
    ("sd_xmax_above_default_xmin", U,
     {"optimization.solver.steepest_descent.xmax": 0.5,
      "optimization.solver.steepest_descent.xmin": DEL}),
    ("sd_move_limit_initial_alone", U,
     {"optimization.solver.steepest_descent.move_limit": {"initial": 0.05}}),
    # optimizer.f90:86: 256 characters is the length of the variable.
    ("restart_file_256_characters", S,
     {"optimization.solver.restart_file": "a" * 253 + ".h5"}),
    # steady_simcomp.f90:276,335: only 0 is a division by zero.
    ("steady_log_frequency_negative", S,
     {"case.simulation_components[0]":
      {"type": "steady", "log_frequency": -10}}),
    # adjoint_case.f90:473-481: a csv file and a tsteps interval of 1 or more.
    ("adjoint_norm_file_csv", S,
     {"case.adjoint_fluid.norm_output_control": "tsteps",
      "case.adjoint_fluid.norm_output_file": "norm.csv"}),
    ("adjoint_norm_tsteps_one", S,
     {"case.adjoint_fluid.norm_output_control": "tsteps",
      "case.adjoint_fluid.norm_output_value": 1.0}),
    # adjoint_case.f90:443-445: `org` reads case.nsamples.
    ("adjoint_output_control_org_with_nsamples", S,
     {"case.adjoint_fluid.output_control": "org", "case.nsamples": 10}),
    # adjoint_fluid_scheme_incompressible.f90:215-229: the adjoint key wins,
    # and Neko resolves the primal constant.
    ("pressure_projection_space_constant_with_adjoint_key", S,
     {"case.fluid.pressure_solver.projection_space_size": "nproj",
      "case.adjoint_fluid.pressure_solver": {"projection_space_size": 20}}),
    ("pressure_projection_hold_constant_with_adjoint_key", S,
     {"case.fluid.pressure_solver.projection_hold_steps": "nhold",
      "case.adjoint_fluid.pressure_solver": {"projection_hold_steps": 5}}),
    # advection_adjoint_fctry.f90:85-101: the order is read only after the
    # dummy-advection return, and U has no scalar.
    ("dealiased_order_constant_without_advection", U,
     {"case.fluid.advection": False,
      "case.numerics.dealiased_polynomial_order": "lxd"}),
    # adjoint_scalar_scheme.f90:301-316,376-380: the adjoint's own key wins,
    # and Neko resolves the primal constant.
    ("scalar_tolerance_constant_with_adjoint_key", S,
     {"case.scalar.solver.absolute_tolerance": "stol",
      "case.adjoint_scalar.solver": {"absolute_tolerance": 1.0e-6}}),
    ("scalar_max_iterations_constant_with_adjoint_key", S,
     {"case.scalar.solver.max_iterations": "smax",
      "case.adjoint_scalar.solver": {"max_iterations": 100}}),
    ("scalar_projection_space_constant_with_adjoint_key", S,
     {"case.scalar.solver.projection_space_size": "sps",
      "case.adjoint_scalar.solver": {"projection_space_size": 5}}),
    ("scalar_projection_hold_constant_with_adjoint_key", S,
     {"case.scalar.solver.projection_hold_steps": "sph",
      "case.adjoint_scalar.solver": {"projection_hold_steps": 5}}),
    # adjoint_scalar_pnpn_bc_fctry.f90:76-84: user-extensible, as in Neko.
    ("adjoint_scalar_bc_user_extra_key", S,
     {"case.adjoint_scalar.boundary_conditions[0]":
      {"type": "user", "zone_indices": [1], "comment": "free"}}),
    # adjoint_scalar_scheme.f90:284-337: a name that is not a field yet.
    ("adjoint_scalar_name_phi", S, {"case.adjoint_scalar.name": "phi"}),
    # adjoint_scalar_scheme.f90:370-373: `user` sources are fine.
    ("scalar_user_source_with_adjoint_scalar", S,
     {"case.scalar.source_terms": [{"type": "user"}]}),
    # adjoint_fluid_pnpn.f90:468-491 and simulation.f90:271,299: the topology
    # optimisation drivers read these; without `optimization` nothing does.
    ("neko_case_with_unsteady", N, {"unsteady": True}),
    ("neko_case_with_state_recovery", N, {"state_recovery": {}}),
    ("neko_case_with_output_file", N, {"output_file": "pw.txt"}),
    ("neko_case_with_integer_norm_scaling", N, {"norm_scaling": 1}),
    # time_window_tester.f90:128,137
    ("time_window_test_unsteady", U,
     {"optimization.time_window_test": {"tolerance": 1.0e-10}}),
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
    # krylov_fctry.f90:178,209 (aborts in the factory) and cg_coupled-style
    # single-field solves: each excluded coupled solver has its own row.
    ("pde_filter_fused_coupled_cg", S,
     {"optimization.design.mapping[0].solver": "fused_coupled_cg"},
     "mapping[0]"),
    ("pde_filter_coupled_bicgstab", S,
     {"optimization.design.mapping[0].solver": "coupled_bicgstab"},
     "mapping[0]"),
    # neko src/krylov/bcknd/cpu/cheby.f90:283,314 and krylov.f90:464: a
    # Chebyshev solve is never reported as converged, so the strict check
    # (PDE_filter_mapping.f90:412,425-430) aborts at the first application.
    ("pde_filter_cheby_strict", S,
     {"optimization.design.mapping[0].solver": "cheby",
      "optimization.design.mapping[0].strict_convergence": True},
     "mapping[0]"),
    # krylov.f90:464: iter >= max_iter is never converged, and one iteration
    # always reaches it; only strict_convergence turns that into an abort.
    ("pde_filter_max_iter_one_strict", S,
     {"optimization.design.mapping[0].max_iter": 1,
      "optimization.design.mapping[0].strict_convergence": True},
     "mapping[0]"),
    # the per-type "iterations only for an array" rule, scalar p / f_max
    # (continuation_scheduler.f90:144-158)
    ("simp_p_scalar_with_p_iterations", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p": 3.0,
      "optimization.design.mapping[2].p_iterations": 2}, "mapping[2]"),
    ("simp_f_max_scalar_with_iterations", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p": 3.0,
      "optimization.design.mapping[2].f_max_iterations": 2}, "mapping[2]"),
    ("bp_f_max_scalar_with_iterations", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].f_max_iterations": 2}, "mapping[2]"),
    # design_hdf5_io.f90:160,256,355-358: the name is held as bytes.
    ("design_name_40_two_byte_characters", S,
     {"optimization.design.name": "\u00e9" * 40,
      "optimization.solver.checkpoint.interval": 1}, "design.name"),
    # optimizer.f90:86,435: restart_file is character(len=256), in bytes.
    ("restart_file_non_ascii_over_256_bytes", S,
     {"optimization.solver.restart_file": "\u00e9" * 130 + ".h5"},
     "restart_file"),
    # tests/shared/sensitivity.f90:199: abs(error) > tolerance aborts.
    ("fd_test_tolerance_negative", S,
     {"optimization.fd_test_tolerance": -1.0e-3}, "fd_test_tolerance"),
    ("fd_test_tolerance_zero", S,
     {"optimization.fd_test_tolerance": 0.0}, "fd_test_tolerance"),
    # time_window_tester.f90:233,260,272: `difference <= tolerance`.
    ("time_window_tolerance_negative", U,
     {"optimization.time_window_test": {"tolerance": -1.0e-6}},
     "time_window_test"),
    # optimizer.f90:826-861: the file name is built in character(len=256).
    ("checkpoint_base_234_default_path", S,
     {"optimization.solver.checkpoint.base": "b" * 234}, "checkpoint.base"),
    ("checkpoint_path_227_default_base", S,
     {"optimization.solver.checkpoint.path": "p" * 227}, "checkpoint.path"),
    ("checkpoint_path_228_slash_default_base", S,
     {"optimization.solver.checkpoint.path": "p" * 227 + "/"},
     "checkpoint.path"),
    ("pde_filter_tol_integer", S,
     {"optimization.design.mapping[0].tol": 1}, "mapping[0]"),
    ("pde_filter_max_iter_real", S,
     {"optimization.design.mapping[0].max_iter": 200.0}, "mapping[0]"),
    ("pde_filter_unknown_key", S,
     {"optimization.design.mapping[0].eta": 0.5}, "mapping[0]"),
    ("linear_mapping_p_key", S,
     {"optimization.constraints[0].mapping[0].p": 3.0}, "mapping[0]"),
    # heaviside_mapping.f90:162-164, continuation_scheduler.f90:250-253: a
    # later beta of 0.0 aborts when the continuation reaches it.
    ("heaviside_later_beta_zero", S,
     {"optimization.design.mapping[1].beta": [1.0, 0.0]}, "mapping[1]"),
    # the per-type "iterations only for an array" rule, for every type
    ("simp_p_iterations_with_scalar", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p_iterations": 2}, "mapping[2]"),
    ("bp_q_iterations_with_scalar", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q_iterations": 2}, "mapping[2]"),
    ("ramp_q_iterations_with_scalar", S,
     {"optimization.design.mapping[2].q_iterations": 2}, "mapping[2]"),
    ("pde_r_iterations_with_scalar", S,
     {"optimization.design.mapping[0].r": 0.1}, "mapping[0]"),
    ("heaviside_beta_iterations_with_scalar", S,
     {"optimization.design.mapping[1].beta": 2.0,
      "optimization.design.mapping[1].beta_iterations": 2}, "mapping[1]"),
    ("linear_f_max_iterations_with_scalar", S,
     {"optimization.constraints[0].mapping[0].f_max_iterations": 2},
     "mapping[0]"),
    ("simp_unknown_key", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].eta": 0.5}, "mapping[2]"),
    ("bp_unknown_key", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].eta": 0.5}, "mapping[2]"),
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
    # continuation_scheduler.f90:132-138,155: without `weight` the key
    # weight_iterations is never read.
    ("objective_weight_iterations_without_weight", S,
     {"optimization.objectives[0].weight": DEL,
      "optimization.objectives[0].weight_iterations": 2}, "objectives[0]"),
    ("viscous_weight_iterations_with_scalar", S,
     {"optimization.objectives[1].weight": 1.0,
      "optimization.objectives[1].weight_iterations": 2}, "objectives[1]"),
    ("brinkman_weight_iterations_with_scalar", U,
     {"optimization.objectives[0].weight_iterations": 2}, "objectives[0]"),
    ("viscous_start_time_integer", S,
     {"optimization.objectives[1].start_time": 1}, "objectives[1]"),
    ("constraint_without_type", S,
     {"optimization.constraints[0].type": DEL}, "constraints[0]"),
    ("objective_without_type", S,
     {"optimization.objectives[1].type": DEL}, "objectives[1]"),
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
    # design_brinkman.f90:284: the design is written every iteration, and
    # csv_file.f90:96 aborts on it.
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
    # set_optimization_ic.f90:259-270: every `field` aborts, either at :262
    # (no .fNNNNN suffix) or at :270, where filename_chsuffix got a temporary
    # for its output argument (:267) and the suffix reaches neko
    # src/io/file.f90:133.
    ("initial_distribution_field", S,
     {"optimization.design.initial_distribution":
      {"type": "field", "file_name": "mean0.f00001"}}, "initial_distribution"),
    ("initial_distribution_field_interpolated", S,
     {"optimization.design.initial_distribution":
      {"type": "field", "file_name": "mean0.f00001", "interpolate": True,
       "tolerance": 1.0e-6, "mesh_file_name": "none"}},
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
    # read_duration (neko src/common/utils.f90:662): a `/` is read with ierr 0
    # and an undefined value.
    ("max_runtime_slash", S,
     {"optimization.solver.max_runtime": "1/2"}, "optimization.solver"),
    # optimizer.f90:1012
    ("restart_file_suffix", S,
     {"optimization.solver.restart_file": "state.txt"}, "optimization.solver"),
    # optimizer.f90:86,435: a character(len=256) variable cuts the name.
    ("restart_file_too_long", S,
     {"optimization.solver.restart_file": "a" * 254 + ".h5"},
     "optimization.solver"),
    ("checkpoint_path_too_long", S,
     {"optimization.solver.checkpoint.path": "p" * 257}, "checkpoint"),
    ("checkpoint_base_too_long", S,
     {"optimization.solver.checkpoint.base": "b" * 257}, "checkpoint"),
    # The keys that both solvers read through optimizer_read_base_settings
    # (optimizer.f90:415-449), on the steepest descent solver.
    ("sd_max_runtime_format", U,
     {"optimization.solver.max_runtime": "1:2:3:4"}, "optimization.solver"),
    ("sd_restart_file_suffix", U,
     {"optimization.solver.restart_file": "state.txt"}, "optimization.solver"),
    ("sd_checkpoint_format", U,
     {"optimization.solver.checkpoint.format": "json"}, "checkpoint"),
    ("sd_checkpoint_unknown_key", U,
     {"optimization.solver.checkpoint": {"verbose": True}}, "checkpoint"),
    ("sd_continuation_iterations_real", U,
     {"optimization.solver.continuation_iterations": 2.0},
     "optimization.solver"),
    ("sd_max_iterations_real", U,
     {"optimization.solver.max_iterations": 10.0}, "optimization.solver"),
    # steepest_descent_optimizer.f90:194-217: xmin >= xmax, with the default
    # of the key that is absent.
    ("sd_xmin_at_default_xmax", U,
     {"optimization.solver.steepest_descent.xmin": 1.0,
      "optimization.solver.steepest_descent.xmax": DEL}, "steepest_descent"),
    ("sd_xmax_at_default_xmin", U,
     {"optimization.solver.steepest_descent.xmax": -0.5,
      "optimization.solver.steepest_descent.xmin": DEL}, "steepest_descent"),
    # steepest_descent_optimizer.f90:200-235: move limits against the
    # defaults (initial 0.1, min 0.001, max 0.1) of the keys that are absent.
    ("sd_move_limit_initial_above_default_max", U,
     {"optimization.solver.steepest_descent.move_limit": {"initial": 0.2}},
     "move_limit"),
    ("sd_move_limit_initial_below_default_min", U,
     {"optimization.solver.steepest_descent.move_limit": {"initial": 0.0005}},
     "move_limit"),
    ("sd_move_limit_max_below_default_initial", U,
     {"optimization.solver.steepest_descent.move_limit": {"max": 0.05}},
     "move_limit"),
    ("sd_move_limit_min_above_default_initial", U,
     {"optimization.solver.steepest_descent.move_limit": {"min": 0.2}},
     "move_limit"),
    ("sd_decrease_integer", U,
     {"optimization.solver.steepest_descent.move_limit.decrease": 1},
     "move_limit"),
    ("sd_xmin_integer", U,
     {"optimization.solver.steepest_descent.xmin": 0}, "steepest_descent"),
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
    # No abort: checkpoint.f90:156 hands the string to chkp_output, which maps
    # anything but `hdf5` to `.chkp` (neko src/io/chkp_output.f90:69-74), so
    # `h5` would silently run as `chkp`; rejected as Neko's enum does.
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
    # simulation.f90:289-297: an unsteady run aborts for exact_output_time
    # (the same input is rejected by Neko's own time rule; the pure
    # Neko-TOP rule is tested in test_exact_output_time_rule_is_ours).
    # ---- optimization object ---------------------------------------------
    # time_window_tester.f90:128,137: the only reader aborts for a steady run
    # and for an empty objective list.
    ("time_window_test_in_steady_case", S,
     {"optimization.time_window_test": {"tolerance": 1.0e-10}}, "$"),
    ("time_window_test_without_objectives", U,
     {"optimization.time_window_test": {"tolerance": 1.0e-10},
      "optimization.objectives": []}, "objectives"),
    # problem.f90:358-364: only dealias_sensitivity is read.
    ("augmented_lagrangian_weight", S,
     {"optimization.augmented_lagrangian": {"weight": 1.0}},
     "augmented_lagrangian"),
    ("time_window_test_end_times_string", U,
     {"optimization.time_window_test": {"end_times": "1.0"}},
     "time_window_test"),
    ("fd_test_tolerance_integer", S, {"optimization.fd_test_tolerance": 1},
     "fd_test_tolerance"),
    # adjoint_fluid_pnpn.f90:468-491 (root keys of the power iteration)
    ("output_file_suffix", S, {"output_file": "power.dat"}, "output_file"),
    ("norm_target_integer", S, {"norm_target": 1}, "norm_target"),
    ("norm_tolerance_integer", S, {"norm_tolerance": 1}, "norm_tolerance"),
    ("state_recovery_extra_fields_integer", U,
     {"state_recovery.extra_fields": [1]}, "state_recovery"),
    # checkpoint.f90:154-160: typed readers abort on a wrong JSON type.
    ("state_recovery_path_integer", U,
     {"state_recovery.path": 5}, "state_recovery"),
    ("state_recovery_filename_integer", U,
     {"state_recovery.filename": 5}, "state_recovery"),
    ("state_recovery_keep_checkpoints_string", U,
     {"state_recovery.keep_checkpoints": "yes"}, "state_recovery"),
    ("state_recovery_extra_fields_string", U,
     {"state_recovery.extra_fields": "u"}, "state_recovery"),
    # steady_simcomp.f90:148-151 for every driver: a steady component and
    # more than one scalar, without an `optimization` object.
    # (base S minus its case.scalar and the adjoint scalar: next to
    # case.scalar, Neko never reads case.scalars, case.f90:319-353.)
    ("steady_with_two_scalars", S,
     {"case.scalar": DEL, "case.adjoint_scalar": DEL,
      "optimization.objectives[0]": {"type": "viscous_dissipation"},
      "case.scalars": [dict(SCALAR_ITEM, name="a", enabled=False),
                       dict(SCALAR_ITEM, name="b", enabled=False)]},
     "scalars"),
    ("steady_with_two_scalars_without_optimization", N,
     {"case.simulation_components": [{"type": "steady"}],
      "case.scalars": [dict(SCALAR_ITEM, name="a"),
                       dict(SCALAR_ITEM, name="b")]}, "scalars"),
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
    ("adjoint_norm_file_suffix", S,
     {"case.adjoint_fluid.norm_output_control": "tsteps",
      "case.adjoint_fluid.norm_output_file": "norm.dat"}, "adjoint_fluid"),
    ("adjoint_output_format", S,
     {"case.adjoint_fluid.output_format": "csv"}, "adjoint_fluid"),
    ("adjoint_fluid_unknown_key", S,
     {"case.adjoint_fluid.enabled": True}, "adjoint_fluid"),
    # adjoint_fluid_pnpn_bc_fctry.f90:178: a known type that builds no BC;
    # the zone gets a natural condition. (Owner decision pending.)
    ("adjoint_bc_user_velocity_pointwise", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "user_velocity_pointwise", "zone_indices": [1, 3, 4, 5, 6]}},
     "boundary_conditions[0]"),
    # neko src/fluid/fluid_pnpn_bc_fctry.f90:505,588: only Neko's own factory
    # reads `name`.
    ("adjoint_bc_name", S,
     {"case.adjoint_fluid.boundary_conditions[0].name": "inlet"},
     "boundary_conditions[0]"),
    ("adjoint_scalar_bc_name", S,
     {"case.adjoint_scalar.boundary_conditions[0].name": "inlet"},
     "adjoint_scalar.boundary_conditions[0]"),
    ("adjoint_scalar_bc_neumann_name", S,
     {"case.adjoint_scalar.boundary_conditions[1].name": "walls"},
     "adjoint_scalar.boundary_conditions[1]"),
    # adjoint_case.f90:118,427,432: `layout` is never assigned.
    ("adjoint_output_format_adios2", S,
     {"case.adjoint_fluid.output_format": "adios2"}, "adjoint_fluid"),
    # adjoint_case.f90:473-478: the norm is a vector_t, only csv writes it.
    ("adjoint_norm_file_fld", S,
     {"case.adjoint_fluid.norm_output_control": "tsteps",
      "case.adjoint_fluid.norm_output_file": "n.fld"}, "adjoint_fluid"),
    # neko src/common/time_based_controller.f90:232-235
    ("adjoint_norm_tsteps_below_one", S,
     {"case.adjoint_fluid.norm_output_control": "tsteps",
      "case.adjoint_fluid.norm_output_value": 0.5}, "adjoint_fluid"),
    # adjoint_case.f90:443-445: case.nsamples has no default.
    ("adjoint_output_control_org_without_nsamples", S,
     {"case.adjoint_fluid.output_control": "org"}, "$.case"),
    ("adjoint_scalar_solver_monitor_string", S,
     {"case.adjoint_scalar.solver": {"monitor": "yes"}},
     "adjoint_scalar.solver"),
    ("adjoint_scalar_enabled_string", S,
     {"case.adjoint_scalar.enabled": "yes"}, "adjoint_scalar.enabled"),
    ("adjoint_scalar_advection_string", S,
     {"case.adjoint_scalar.advection": "yes"}, "adjoint_scalar.advection"),
    ("adjoint_scalar_dealias_coupling_string", S,
     {"case.adjoint_scalar.dealias_coupling_term": "yes"},
     "adjoint_scalar.dealias_coupling_term"),
    # adjoint_case.f90:452-480 and neko src/common/json_utils.f90:599
    ("adjoint_output_value_simulationtime_without_value", S,
     {"case.adjoint_fluid.output_control": "simulationtime"}, "adjoint_fluid"),
    ("adjoint_output_value_without_control", S,
     {"case.adjoint_fluid.output_value": 5}, "adjoint_fluid"),
    ("adjoint_norm_output_control_unknown", S,
     {"case.adjoint_fluid.norm_output_control": "always"}, "adjoint_fluid"),
    ("adjoint_freeze_string", S, {"case.adjoint_fluid.freeze": "yes"},
     "adjoint_fluid"),
    ("adjoint_velocity_solver_monitor_string", S,
     {"case.adjoint_fluid.velocity_solver": {"monitor": "yes"}},
     "adjoint_fluid.velocity_solver"),
    ("adjoint_pressure_solver_projection_space_real", S,
     {"case.adjoint_fluid.pressure_solver": {"projection_space_size": 5.0}},
     "adjoint_fluid.pressure_solver"),
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
    # adjoint_scalar_scheme.f90:281,341: names that cannot match.
    ("adjoint_scalar_primal_name_mismatch_default", S,
     {"case.adjoint_scalar.primal_name": "temperature"}, "adjoint_scalar"),
    ("adjoint_scalar_primal_name_missing_for_named_scalar", S,
     {"case.scalar.name": "temperature"}, "adjoint_scalar"),
    # adjoint_case.f90:252
    # adjoint_case.f90:180-185: an object is counted by its members.
    ("adjoint_scalars_object", S,
     {"case.adjoint_scalar": DEL, "case.scalar.enabled": False,
      "case.adjoint_scalars": {"a": {"primal_name": "s"}}},
     "adjoint_scalars"),
    ("adjoint_scalars_array", S,
     {"case.adjoint_scalar": DEL, "case.scalar.enabled": False,
      "case.adjoint_scalars": [{"primal_name": "s"}]}, "adjoint_scalars"),
]

# --------------------------------------------------------------------------- #
# Numeric keys that the code reads through a constants lookup (Neko's
# json_get_or_lookup*): a literal of the kind the reader wants, or the name of
# a constant. A lookup still rejects an integer literal for a real key
# (neko src/common/json_utils.f90:510). (id, base, path, literal, name)
# --------------------------------------------------------------------------- #
NUMERIC_KEYS = [
    ("design_initial_value", S,
     "optimization.design.initial_distribution.value", 0.5, "v0"),
    ("design_base_value", U,
     "optimization.design.initial_distribution.base_value", 0.5, "v0"),
    ("design_zone_value", U,
     "optimization.design.initial_distribution.zone_value", 0.5, "v1"),
    ("pde_filter_tol", S, "optimization.design.mapping[0].tol", 1.0e-8, "t"),
    ("pde_filter_max_iter", S, "optimization.design.mapping[0].max_iter",
     100, "n"),
    ("heaviside_eta", S, "optimization.design.mapping[1].eta", 0.4, "eta"),
    ("ramp_f_min", S, "optimization.design.mapping[2].f_min", 0.1, "fmin"),
    ("linear_f_min", S, "optimization.constraints[0].mapping[0].f_min", 0.1,
     "fmin"),
    ("volume_limit", S, "optimization.constraints[0].limit", 0.2, "limit"),
    ("objective_start_time", S, "optimization.objectives[0].start_time",
     0.0, "t0"),
    ("objective_end_time", S, "optimization.objectives[0].end_time",
     1.0, "t1"),
    ("mixing_target_concentration", S,
     "optimization.objectives[0].target_concentration", 0.5, "target"),
    ("mma_scale", S, "optimization.solver.mma.scale", 10.0, "scale"),
    ("mma_xmax", S, "optimization.solver.mma.xmax", 1.0, "xmax"),
    ("mma_epsimin", S, "optimization.solver.mma.epsimin", 1.0e-9, "eps"),
    ("mma_max_iter", S, "optimization.solver.mma.max_iter", 100, "n"),
    ("mma_move_limit", S, "optimization.solver.mma.move_limit", 0.2, "ml"),
    ("solver_tolerance", S, "optimization.solver.tolerance", 1.0e-6, "tol"),
    ("solver_max_iterations", S, "optimization.solver.max_iterations", 10,
     "n"),
    ("solver_checkpoint_interval", S,
     "optimization.solver.checkpoint.interval", 5, "n"),
    ("steady_tol", S, "case.simulation_components[0].tol", 1.0e-6, "tol"),
    ("steady_log_frequency", S,
     "case.simulation_components[0].log_frequency", 10, "n"),
    ("state_recovery_n_memory", U, "state_recovery.n_memory", 20, "n"),
    ("root_norm_scaling", S, "norm_scaling", 0.5, "s"),
    ("root_norm_target", S, "norm_target", 0.5, "s"),
    ("root_norm_tolerance", S, "norm_tolerance", 1.0e-6, "s"),
    ("adjoint_norm_output_value", S,
     "case.adjoint_fluid.norm_output_value", 1.0, "n"),
    ("adjoint_velocity_tolerance", S,
     "case.adjoint_fluid.velocity_solver.absolute_tolerance", 1.0e-6, "t"),
    ("adjoint_velocity_max_iterations", S,
     "case.adjoint_fluid.velocity_solver.max_iterations", 50, "n"),
    ("adjoint_velocity_projection_space", S,
     "case.adjoint_fluid.velocity_solver.projection_space_size", 5, "n"),
    ("adjoint_pressure_projection_hold", S,
     "case.adjoint_fluid.pressure_solver.projection_hold_steps", 5, "h"),
    ("adjoint_scalar_tolerance", S,
     "case.adjoint_scalar.solver.absolute_tolerance", 1.0e-6, "t"),
    ("adjoint_scalar_max_iterations", S,
     "case.adjoint_scalar.solver.max_iterations", 50, "n"),
    ("adjoint_scalar_projection_space", S,
     "case.adjoint_scalar.solver.projection_space_size", 5, "n"),
    ("adjoint_scalar_projection_hold", S,
     "case.adjoint_scalar.solver.projection_hold_steps", 5, "h"),
    ("fluid_re", S, "case.fluid.Re", 2.0, "Re"),
    ("fluid_mu", S, "case.fluid.mu", 0.5, "mu"),
    ("fluid_rho", S, "case.fluid.rho", 1.5, "rho"),
    ("numerics_time_order", S, "case.numerics.time_order", 1, "order"),
    ("numerics_polynomial_order", S, "case.numerics.polynomial_order", 5,
     "p"),
    ("numerics_dealiased_order", S,
     "case.numerics.dealiased_polynomial_order", 8, "q"),
    ("pressure_solver_tolerance", S,
     "case.fluid.pressure_solver.absolute_tolerance", 1.0e-4, "ptol"),
    ("pressure_solver_max_iterations", S,
     "case.fluid.pressure_solver.max_iterations", 50, "pmax"),
    ("pressure_solver_projection_space", S,
     "case.fluid.pressure_solver.projection_space_size", 5, "k"),
    ("velocity_solver_projection_hold", S,
     "case.fluid.velocity_solver.projection_hold_steps", 5, "h"),
    ("velocity_solver_tolerance", S,
     "case.fluid.velocity_solver.absolute_tolerance", 1.0e-4, "vtol"),
    ("velocity_solver_max_iterations", S,
     "case.fluid.velocity_solver.max_iterations", 50, "vmax"),
    ("scalar_pe", S, "case.scalar.Pe", 500.0, "Pe"),
    ("scalar_lambda", S, "case.scalar.lambda", 0.5, "k"),
    ("scalar_cp", S, "case.scalar.cp", 1.0, "c0"),
    ("scalar_solver_tolerance", S, "case.scalar.solver.absolute_tolerance",
     1.0e-6, "stol"),
    ("scalar_solver_max_iterations", S, "case.scalar.solver.max_iterations",
     50, "smax"),
    ("scalar_solver_projection_space", S,
     "case.scalar.solver.projection_space_size", 5, "sps"),
    ("scalar_solver_projection_hold", S,
     "case.scalar.solver.projection_hold_steps", 5, "sph"),
    ("sd_step_length", U, "optimization.solver.steepest_descent.step_length",
     0.5, "step"),
    ("sd_move_limit_decrease", U,
     "optimization.solver.steepest_descent.move_limit.decrease", 0.5, "d"),
    ("sd_move_limit_increase", U,
     "optimization.solver.steepest_descent.move_limit.increase", 1.5, "i"),
    ("sd_stop_design_change", U, "optimization.solver.stop_design_change",
     1.0e-8, "s"),
    ("mma_stop_design_change", S, "optimization.solver.stop_design_change",
     1.0e-8, "s"),
    ("sd_xmax", U, "optimization.solver.steepest_descent.xmax", 0.9, "xmax"),
    ("adjoint_zone_indices", S,
     "case.adjoint_fluid.boundary_conditions[0].zone_indices", [1, 3, 4, 5, 6],
     "walls"),
    ("adjoint_scalar_zone_indices", S,
     "case.adjoint_scalar.boundary_conditions[0].zone_indices", [1],
     "inlet"),
    ("adjoint_scalar_user_zone_indices", S,
     "case.adjoint_scalar.boundary_conditions[0].zone_indices", [1],
     "inlet"),
    ("continuation_f_max", S, "optimization.design.mapping[2].f_max", 100.0,
     "big"),
    ("continuation_f_max_array", S, "optimization.design.mapping[2].f_max",
     [1.0, 10.0], "big"),
    ("continuation_q", S, "optimization.design.mapping[2].q", 0.1, "q"),
    ("continuation_r", S, "optimization.design.mapping[0].r", 0.1, "r"),
    ("continuation_weight", S, "optimization.objectives[1].weight", 1.0,
     "w"),
    ("continuation_beta", S, "optimization.design.mapping[1].beta", 1.0,
     "beta"),
    ("continuation_beta_array", S, "optimization.design.mapping[1].beta",
     [1.0, 2.0], "beta"),
]

# The key is read only next to another one, or replaces a default.
NUMERIC_PRE_EDITS = {
    "adjoint_norm_output_value": {
        "case.adjoint_fluid.norm_output_control": "tsteps"},
    "fluid_mu": {"case.fluid.Re": DEL, "case.fluid.rho": 1.5},
    "fluid_rho": {"case.fluid.Re": DEL, "case.fluid.mu": 0.5},
    "scalar_lambda": {"case.scalar.Pe": DEL, "case.scalar.cp": 1.0},
    "scalar_cp": {"case.scalar.Pe": DEL, "case.scalar.lambda": 1.0},
    # A scalar is no array: the per-array iteration count must go.
    "continuation_r": {"optimization.design.mapping[0].r_iterations": DEL},
    "continuation_weight": {
        "optimization.objectives[1].weight_iterations": DEL},
    "adjoint_scalar_user_zone_indices": {
        "case.adjoint_scalar.boundary_conditions[0]":
        {"type": "user", "zone_indices": [1]}},
}

# Constants names next to keys whose restriction depends on the value.
# (id, base, edits)
ACCEPTS_CONSTANT_NAMES = [
    # A constants name may name a vector, so the per-array iteration counts
    # (continuation_scheduler.f90:152-155) are accepted next to it.
    ("f_max_name_with_iterations", S,
     {"optimization.design.mapping[2].f_max": "big",
      "optimization.design.mapping[2].f_max_iterations": 2}),
    ("weight_name_with_iterations", S,
     {"optimization.objectives[1].weight": "w",
      "optimization.objectives[1].weight_iterations": 2}),
    ("beta_name_with_iterations", S,
     {"optimization.design.mapping[1].beta": "beta",
      "optimization.design.mapping[1].beta_iterations": 2}),
    ("iterations_name", S,
     {"optimization.design.mapping[0].r_iterations": "n"}),
    ("solver_continuation_iterations_name", S,
     {"optimization.solver.continuation_iterations": "n"}),
    # The primal solver keys that the adjoint reads when it has no block of
    # its own.
    ("primal_solver_names_without_adjoint_block", S,
     {"case.fluid.velocity_solver.absolute_tolerance": "vtol",
      "case.fluid.velocity_solver.max_iterations": "vmax",
      "case.fluid.pressure_solver.absolute_tolerance": "ptol",
      "case.fluid.pressure_solver.max_iterations": "pmax",
      "case.scalar.solver.absolute_tolerance": "stol",
      "case.scalar.solver.max_iterations": "smax"}),
    ("dealiased_order_name_with_adjoint_scalar_advecting", S,
     {"case.fluid.advection": False,
      "case.numerics.dealiased_polynomial_order": "lxd"}),
    ("dealiased_order_name_with_advection", U,
     {"case.numerics.dealiased_polynomial_order": "lxd"}),
]

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
    ("simcomp_steady_log_frequency_negative", S,
     {"case.simulation_components[0]":
      {"type": "steady", "log_frequency": -1}}, True),
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
        # Their init_from_json is empty (simple_brinkman_source_term.f90:
        # 110-123 and siblings): the first compute_ dereferences unset
        # pointers, so a case file cannot use them anywhere.
        (f"fluid_source_term_{_name}", S,
         {"case.fluid.source_terms": [{"type": _name}]}, False),
        (f"scalar_source_term_{_name}", S,
         {"case.scalar.source_terms": [{"type": _name}]}, False),
        (f"adjoint_source_term_{_name}", S,
         {"case.adjoint_fluid.source_term": [{"type": _name}]}, False),
    ]
REGISTERED_BY_NEKO_TOP += [
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
    ("augmented_lagrangian", S, "optimization.augmented_lagrangian"),
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
    # Only the two projection keys are read; the object is a linear-solver
    # object, which Neko keeps open.
    ("adjoint_pressure_solver", S, "case.adjoint_fluid.pressure_solver"),
]

# --------------------------------------------------------------------------- #
# Restrictions of a case with an `optimization` object: the same edit makes a
# case that Neko's drivers accept (no `optimization`) and that the topology
# optimisation drivers abort on. (id, base, edits, path fragment)
# --------------------------------------------------------------------------- #
RESTART = {"case.restart_file": "restart.chkp"}
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
    # adjoint_scalar_scheme.f90:355-358
    ("scalar_variable_material_properties", S,
     {"case.scalar.variable_material_properties": {"lambda": {"type": "x"}}},
     "case.scalar"),
    # adjoint_curl_curl.f90:128-134
    ("primal_symmetry_boundary", S,
     {"case.fluid.boundary_conditions[2]":
      {"type": "symmetry", "zone_indices": [7]}}, "boundary_conditions"),
    ("primal_split_symmetry_boundary", S,
     {"case.fluid.boundary_conditions[2]":
      {"velocity": {"type": "symmetry"}, "pressure": {"type": "outflow"},
       "zone_indices": [7]}}, "boundary_conditions"),
    # adjoint_case.f90:180-185: an object is counted by its members.
    ("adjoint_scalars_object", S,
     {"case.scalar.enabled": False, "case.adjoint_scalar": DEL,
      "case.adjoint_scalars": {"a": {"primal_name": "s"}},
      "optimization.objectives[0]": {"type": "viscous_dissipation"}},
     "adjoint_scalars"),
    # adjoint_case.f90:252
    ("adjoint_scalars", S,
     {"case.scalar.enabled": False, "case.adjoint_scalar": DEL,
      "case.adjoint_scalars": [{"primal_name": "s"}],
      "optimization.objectives[0]": {"type": "viscous_dissipation"}},
     "adjoint_scalars"),
    # scalar_mixing_objective_function.f90:171
    ("scalar_mixing_without_adjoint_scalar", S,
     {"case.scalar.enabled": False, "case.adjoint_scalar.enabled": False},
     "adjoint_scalar"),
    # brinkman_dissipation_objective.f90:150-162: one flag differs from
    # case.numerics.dealias, which it defaults the other to.
    ("brinkman_single_dealias_flag", U,
     {"optimization.objectives[0].dealias_sensitivity": False,
      "optimization.objectives[0].dealias_forcing": DEL}, "objectives[0]"),
    # brinkman_dissipation_objective.f90:150-164: with case.numerics.dealias
    # false, a single flag that is true leaves the other at false.
    ("brinkman_single_dealias_flag_true", U,
     {"case.numerics.dealias": False,
      "optimization.objectives[0].dealias_sensitivity": True,
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
# --------------------------------------------------------------------------- #
# Round 2 of the code audit.
# --------------------------------------------------------------------------- #
_VOLUME = {"type": "volume", "mask_name": "optimization_domain",
           "limit": 0.1, "mapping": [{"type": "linear", "f_max": 1.0}]}
_NO_SCALAR = {"case.scalar": DEL, "case.adjoint_scalar": DEL,
              "optimization.objectives[0]": {"type": "viscous_dissipation"}}
_NO_ADJOINT_SCALAR_OBJECTIVE = {"optimization.objectives[0]":
                                {"type": "viscous_dissipation"}}
ACCEPTED_BY_THE_CODE += [
    # continuation_scheduler.f90:144-150, heaviside_mapping.f90:96-101: a
    # scalar beta is read with json_get.
    ("heaviside_scalar_beta", S,
     {"optimization.design.mapping[1].beta": 8.0,
      "optimization.design.mapping[1].beta_iterations": DEL}),
    # mapping_handler.f90:443-457,299-312: an empty cascade is the identity.
    ("design_empty_mapping", S, {"optimization.design.mapping": []}),
    # design_hdf5_io.f90:256: the name is only stored when a design checkpoint
    # is written (default interval -1: none).
    ("design_long_name_without_checkpoint", S,
     {"optimization.design.name": "a" * 70}),
    ("design_long_name_checkpoint_disabled", S,
     {"optimization.design.name": "a" * 70,
      "optimization.solver.checkpoint.interval": 0}),
    ("design_name_64_characters_with_checkpoint", S,
     {"optimization.design.name": "a" * 64,
      "optimization.solver.checkpoint.interval": 1}),
    # mma.f90:293-294: equal bounds leave the design fixed but run. These
    # three rows start from the fixture's uniform 0.0, which lies outside
    # the box, and MMA never projects it in (mma_cpu.f90:309-326,366-367,
    # 978-979): with dip the design stays near 0 and the volume constraint
    # is violated. They record only that the bound order itself is not
    # checked by the code; the schema cannot compare them with the design.
    ("mma_xmin_at_default_xmax", S,
     {"optimization.solver.mma.xmin": 1.0,
      "optimization.solver.mma.xmax": DEL}),
    ("mma_xmax_at_default_xmin", S,
     {"optimization.solver.mma.xmax": 0.0,
      "optimization.solver.mma.xmin": DEL}),
    ("mma_xmin_xmax_both_above_one", S,
     {"optimization.solver.mma.xmin": 1.5,
      "optimization.solver.mma.xmax": 2.0}),
    # mma_optimizer.f90:194,328-336: only the constraints are scaled.
    ("mma_negative_scale_without_constraints", S,
     {"optimization.solver.mma.scale": -1.0,
      "optimization.constraints": []}),
    # mma_optimizer.f90:328-331: abs(scale / g1) with auto_scale.
    ("mma_negative_scale_with_auto_scale", S,
     {"optimization.solver.mma.scale": -1000.0,
      "optimization.solver.mma.auto_scale": True}),
    ("mma_move_limit_zero", S, {"optimization.solver.mma.move_limit": 0.0}),
    # steepest_descent_optimizer.f90:214-235: equality is accepted, and keys
    # that are both given are not compared with the defaults.
    ("sd_move_limit_min_at_default_initial", U,
     {"optimization.solver.steepest_descent.move_limit": {"min": 0.1}}),
    ("sd_move_limit_max_at_default_initial", U,
     {"optimization.solver.steepest_descent.move_limit": {"max": 0.1}}),
    ("sd_move_limit_initial_at_default_max", U,
     {"optimization.solver.steepest_descent.move_limit": {"initial": 0.1}}),
    ("sd_move_limit_initial_at_default_min", U,
     {"optimization.solver.steepest_descent.move_limit": {"initial": 0.001}}),
    ("sd_move_limit_initial_and_max_raised", U,
     {"optimization.solver.steepest_descent.move_limit":
      {"initial": 0.2, "max": 0.3}}),
    ("sd_move_limit_initial_and_min_lowered", U,
     {"optimization.solver.steepest_descent.move_limit":
      {"initial": 0.0005, "min": 0.0001}}),
    ("sd_move_limit_initial_and_max_below_default_max", U,
     {"optimization.solver.steepest_descent.move_limit":
      {"initial": 0.05, "max": 0.07}}),
    ("sd_xmin_xmax_both_above_one", U,
     {"optimization.solver.steepest_descent.xmin": 1.5,
      "optimization.solver.steepest_descent.xmax": 2.0}),
    ("sd_xmin_xmax_both_negative", U,
     {"optimization.solver.steepest_descent.xmin": -2.0,
      "optimization.solver.steepest_descent.xmax": -1.0}),
    # continuation_scheduler.f90:151-158: array q with its iterations.
    ("bp_q_array_positive", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": [1.0, 3.0],
      "optimization.design.mapping[2].q_iterations": 2}),
    ("bp_q_array_below_minus_one", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": [-2.0, -3.0],
      "optimization.design.mapping[2].q_iterations": 2}),
    # time_based_controller.f90:210-235: simulationtime needs a positive
    # interval only.
    ("adjoint_norm_simulationtime_half", S,
     {"case.adjoint_fluid.norm_output_control": "simulationtime",
      "case.adjoint_fluid.norm_output_value": 0.5}),
    # advection_adjoint_fctry.f90:85-101: no advection anywhere, so the order
    # is never read as an integer.
    ("dealiased_order_constant_without_any_advection", S,
     {"case.fluid.advection": False,
      "case.adjoint_scalar.advection": False,
      "case.numerics.dealiased_polynomial_order": "lxd"}),
    # adjoint_scalar_scheme.f90:333-337: a name that is no field yet.
    ("adjoint_scalar_name_s_with_scalar_T", S,
     {"case.scalar.name": "T", "case.adjoint_scalar.primal_name": "T",
      "case.adjoint_scalar.name": "s"}),
    ("adjoint_scalar_disabled_named_s", S,
     dict(_NO_ADJOINT_SCALAR_OBJECTIVE,
          **{"case.scalar.enabled": False,
             "case.adjoint_scalar": {"enabled": False, "name": "s"}})),
    # adjoint_case.f90:175-196: a disabled adjoint scalar reads no primal_name.
    ("adjoint_scalar_disabled_with_named_scalar", S,
     dict(_NO_ADJOINT_SCALAR_OBJECTIVE,
          **{"case.scalar.name": "phi", "case.scalar.enabled": False,
             "case.adjoint_scalar": {"enabled": False}})),
    ("adjoint_scalar_primal_p_with_own_name", S,
     {"case.scalar.name": "p", "case.adjoint_scalar.primal_name": "p",
      "case.adjoint_scalar.name": "phi_adj"}),
    # neko_ext.f90:216-217: a disabled entry of the array form is not built.
    ("scalars_item_disabled", S,
     {"case.scalars": [dict(SCALAR_ITEM, enabled=False)]}),
    # time_window_tester.f90:199-202: a frozen fluid reaches a steady state.
    ("time_window_require_steady_with_freeze_flow", U,
     {"optimization.time_window_test": {"require_steady_state": True},
      "case.fluid.freeze_flow": True}),
    # checkpoint.f90:164: a name that exists at simulation init.
    ("state_recovery_extra_fields_adjoint_pressure", U,
     {"state_recovery.extra_fields": ["p_adj"]}),
    # Without `optimization` no driver builds the adjoint or reads these
    # (sources/drivers/neko.f90:42-45).
    ("neko_case_adjoint_fluid_freeze_only", N,
     {"case.adjoint_fluid": {"freeze_flow": True}}),
    ("neko_case_adjoint_fluid_without_initial_condition", N,
     {"case.adjoint_fluid": {"output_control": "tsteps"}}),
    ("neko_case_adjoint_scalar_without_initial_condition", N,
     {"case.adjoint_scalar": {"enabled": True}}),
    # neko src/case.f90:319-353: case.scalars is not read next to case.scalar.
    ("steady_with_scalar_and_two_scalars", N,
     {"case.simulation_components": [{"type": "steady"}],
      "case.scalar": dict(SCALAR_ITEM, enabled=True),
      "case.scalars": [dict(SCALAR_ITEM, name="s1"),
                       dict(SCALAR_ITEM, name="s2")]}),
    # simulation_component_fctry.f90:108-109: is_user entries are skipped.
    ("steady_type_with_is_user", N,
     {"case.simulation_components": [{"type": "steady", "is_user": True,
                                      "tol": "free"}]}),
    # cg.f90:189: any positive tolerance is a valid exit test.
    ("pde_filter_tol_tiny", S,
     {"optimization.design.mapping[0].tol": 1.0e-30}),
]

REJECTED_AS_THE_CODE_ABORTS += [
    # ---- mapping ----------------------------------------------------------
    # cg.f90:189,255,267: `rnorm < abs_tol` is never met by tol <= 0, which
    # aborts with strict_convergence (PDE_filter_mapping.f90:412,425-430) and
    # only logs without it.
    ("pde_filter_tol_zero_strict", S,
     {"optimization.design.mapping[0].tol": 0.0,
      "optimization.design.mapping[0].strict_convergence": True},
     "mapping[0]"),
    ("pde_filter_tol_negative_strict", S,
     {"optimization.design.mapping[0].tol": -1.0e-10,
      "optimization.design.mapping[0].strict_convergence": True},
     "mapping[0]"),
    ("pde_filter_preconditioner_hsmg", S,
     {"optimization.design.mapping[0].preconditioner": "hsmg"}, "mapping[0]"),
    # PDE_filter_mapping.f90:136: r is required (r_iterations goes too, so
    # that the rule of the required keys is what rejects the row).
    ("pde_filter_without_r_and_r_iterations", S,
     {"optimization.design.mapping[0].r": DEL,
      "optimization.design.mapping[0].r_iterations": DEL}, "mapping[0]"),
    # ---- design -----------------------------------------------------------
    # design_brinkman.f90:274,297-302: zone_name is read only for point_zone,
    # and without a type the domain is `full`.
    ("design_domain_zone_name_only", S,
     {"optimization.design.domain": {"zone_name": "optimization_domain"}},
     "domain"),
    # design_hdf5_io.f90:256,355-358: the read-back buffer has 64 characters.
    ("design_long_name_with_checkpoint_interval", S,
     {"optimization.design.name": "a" * 70,
      "optimization.solver.checkpoint.interval": 1}, "design.name"),
    ("design_long_name_with_restart_file", S,
     {"optimization.design.name": "a" * 70,
      "optimization.solver.restart_file": "checkpoints/c.h5"}, "design.name"),
    ("design_long_name_with_max_runtime", S,
     {"optimization.design.name": "a" * 70,
      "optimization.solver.max_runtime": "1:00:00"}, "design.name"),
    # ---- problem ----------------------------------------------------------
    # time_window_tester.f90:199-202: nothing freezes the fluid.
    ("time_window_require_steady_without_freeze_flow", U,
     {"optimization.time_window_test": {"require_steady_state": True}},
     "case.fluid"),
    # time_window_tester.f90:137: the key itself is required.
    ("time_window_test_without_objectives_key", U,
     {"optimization.time_window_test": {"tolerance": 1.0e-10},
      "optimization.objectives": DEL}, "optimization"),
    # problem_tester.f90:96-108: two constraints abort the sensitivity tester.
    ("fd_test_two_constraints", S,
     {"optimization.fd_test_tolerance": 1.0e-3,
      "optimization.constraints[1]": _VOLUME}, "constraints"),
    ("fd_test_continuation_iteration_two_constraints", S,
     {"optimization.fd_test_continuation_iteration": 1,
      "optimization.constraints[1]": _VOLUME}, "constraints"),
    # json_get_or_default checks the JSON type of what it reads.
    ("fd_test_continuation_iteration_real", S,
     {"optimization.fd_test_continuation_iteration": 2.0},
     "fd_test_continuation_iteration"),
    ("zero_fields_integer", S, {"optimization.zero_fields": 1}, "zero_fields"),
    ("time_window_pairwise_integer", U,
     {"optimization.time_window_test": {"pairwise": 1}}, "pairwise"),
    ("time_window_compare_steady_integer", U,
     {"optimization.time_window_test": {"compare_steady": 1}},
     "compare_steady"),
    ("time_window_require_steady_integer", U,
     {"optimization.time_window_test": {"require_steady_state": 1}},
     "require_steady_state"),
    ("objectives_object", S, {"optimization.objectives": {}},
     "optimization.objectives"),
    ("constraints_object", S, {"optimization.constraints": {}},
     "optimization.constraints"),
    ("scalar_mixing_name_integer", S,
     {"optimization.objectives[0].name": 1}, "objectives[0]"),
    ("viscous_dissipation_name_integer", S,
     {"optimization.objectives[1].name": 1}, "objectives[1]"),
    ("scalar_mixing_scalar_name_integer", S,
     {"optimization.objectives[0].scalar_name": 1}, "objectives[0]"),
    ("volume_is_max_integer", S,
     {"optimization.constraints[0].is_max": 1}, "constraints[0]"),
    ("volume_name_integer", S,
     {"optimization.constraints[0].name": 1}, "constraints[0]"),
    ("volume_mapping_object", S,
     {"optimization.constraints[0].mapping": {}}, "constraints[0]"),
    # ---- optimizer --------------------------------------------------------
    # utils.f90:607-612: any `-` is the days separator.
    ("max_runtime_negative_exponent", S,
     {"optimization.solver.max_runtime": "1e-3"}, "optimization.solver"),
    ("max_runtime_negative_exponent_fortran_d", S,
     {"optimization.solver.max_runtime": "1d-3"}, "optimization.solver"),
    ("max_runtime_integer", S, {"optimization.solver.max_runtime": 3600},
     "optimization.solver"),
    ("restart_file_integer", S, {"optimization.solver.restart_file": 1},
     "optimization.solver"),
    ("checkpoint_path_integer", S,
     {"optimization.solver.checkpoint.path": 1}, "optimization.solver"),
    ("checkpoint_base_integer", S,
     {"optimization.solver.checkpoint.base": 1}, "optimization.solver"),
    # steepest_descent_optimizer.f90:214-217,226-235: boundaries of the rules.
    ("sd_xmax_zero_alone", U,
     {"optimization.solver.steepest_descent.xmax": 0.0,
      "optimization.solver.steepest_descent.xmin": DEL}, "steepest_descent"),
    # ---- state recovery ---------------------------------------------------
    # checkpoint.f90:164: registered only after sim%init.
    ("state_recovery_extra_fields_brinkman_amplitude", U,
     {"state_recovery.extra_fields": ["brinkman_amplitude"]}, "extra_fields"),
    ("state_recovery_extra_fields_design_indicator", U,
     {"state_recovery.extra_fields": ["design_indicator"]}, "extra_fields"),
    ("state_recovery_extra_fields_sensitivity", U,
     {"state_recovery.extra_fields": ["sensitivity"]}, "extra_fields"),
    ("state_recovery_extra_fields_mapping", U,
     {"state_recovery.extra_fields": ["PDE_filter_mapping_2"]},
     "extra_fields"),
    # zero_dirichlet.f90:73-79 reads no key.
    ("adjoint_bc_no_slip_moving", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"type": "no_slip", "zone_indices": [1, 3, 4, 5, 6], "moving": True}},
     "boundary_conditions"),
    # ---- adjoint scalar ---------------------------------------------------
    # adjoint_scalar_pnpn_bc_fctry.f90:73,94: type and zone_indices, literal.
    ("adjoint_scalar_bc_user_without_zone_indices", S,
     {"case.adjoint_scalar.boundary_conditions[0]": {"type": "user"}},
     "adjoint_scalar"),
    ("adjoint_scalar_bc_without_type", S,
     {"case.adjoint_scalar.boundary_conditions[0]": {"zone_indices": [1]}},
     "adjoint_scalar"),
    # adjoint_case.f90:180-183,260: case.adjoint_scalars alone reads
    # case.scalars without `found`; a missing path leaves json-fortran in an
    # exception state and `case.time` is then reported missing.
    ("adjoint_scalars_empty_without_scalars", S,
     dict(_NO_SCALAR, **{"case.adjoint_scalars": []}), "$.case"),
    ("adjoint_scalars_empty_with_disabled_scalar", S,
     {"case.scalar.enabled": False, "case.adjoint_scalar": DEL,
      "optimization.objectives[0]": {"type": "viscous_dissipation"},
      "case.adjoint_scalars": []}, "$.case"),
]

OPTIMIZING_RESTRICTIONS += [
    # pc_hsmg.f90:224-225 through the adjoint's own precon_factory call.
    ("hsmg_adjoint_velocity_order_one", S,
     {"case.numerics.polynomial_order": 1,
      "case.fluid.pressure_solver.preconditioner": {"type": "jacobi"},
      "case.adjoint_fluid.velocity_solver":
      {"type": "cg", "preconditioner": {"type": "hsmg"}}},
     "adjoint_fluid.velocity_solver"),
    ("hsmg_adjoint_scalar_order_one", S,
     {"case.numerics.polynomial_order": 1,
      "case.fluid.pressure_solver.preconditioner": {"type": "jacobi"},
      "case.adjoint_scalar.solver":
      {"type": "cg", "preconditioner": {"type": "hsmg"}}},
     "adjoint_scalar.solver"),
    # adjoint_case.f90:452-459: only meaningful for the topology drivers.
    ("adjoint_fluid_without_initial_condition", S,
     {"case.adjoint_fluid.initial_condition": DEL},
     "case.adjoint_fluid"),
    ("adjoint_scalar_without_initial_condition", S,
     {"case.adjoint_scalar.initial_condition": DEL},
     "case.adjoint_scalar"),
    ("adjoint_fluid_output_control_without_value", S,
     {"case.adjoint_fluid.output_control": "tsteps",
      "case.adjoint_fluid.output_value": DEL}, "case.adjoint_fluid"),
]

REGISTERED_BY_NEKO_TOP += [
    # simple_brinkman_source_term.f90:110-123: allocated by the factory for
    # case.scalars[i] too, and uninitialised.
    ("scalars_item_source_term_simple_brinkman", N,
     {"case.scalars": [dict(SCALAR_ITEM, name="s1",
                            source_terms=[{"type": "simple_brinkman"}])]},
     False),
    ("scalars_item_source_term_unknown_type", N,
     {"case.scalars": [dict(SCALAR_ITEM, name="s1",
                            source_terms=[{"type": "my_source"}])]}, True),
]

_LONG = "x" * 66

ACCEPTED_BY_THE_CODE += [
    # neko src/case.f90:319-353: case.scalars is not read next to case.scalar.
    ("scalars_enabled_entry_next_to_scalar", S,
     {"case.scalars": [dict(SCALAR_ITEM, enabled=True)]}),
    ("scalars_entry_without_enabled_next_to_scalar", S,
     {"case.scalars": [dict(SCALAR_ITEM)]}),
    ("scalars_enabled_entry_without_scalar_optimization_free", N,
     {"case.scalars": [dict(SCALAR_ITEM, enabled=True)]}),
    # adjoint_case.f90:175-186: case.adjoint_scalar wins; adjoint_scalars is
    # read only in the else branch.
    ("adjoint_scalars_next_to_adjoint_scalar", S,
     {"case.adjoint_scalars": [{"primal_name": "s"}]}),
    ("adjoint_scalars_empty_with_scalars", S,
     dict(_NO_SCALAR, **{"case.adjoint_scalars": [],
                         "case.scalars": []})),
    # adjoint_scalar_scheme.f90:321: 66 characters still fit the log line.
    ("adjoint_scalar_name_66_characters", S,
     {"case.adjoint_scalar.name": _LONG}),
    ("adjoint_scalar_default_name_from_62_characters", S,
     {"case.scalar.name": "y" * 62,
      "case.adjoint_scalar.primal_name": "y" * 62}),
    ("disabled_adjoint_scalar_name_with_slash", S,
     dict(_NO_SCALAR, **{"case.adjoint_scalar":
                         {"enabled": False, "name": "a/b"}})),
    # simulation_component_fctry.f90:108-109: is_user entries are skipped
    # before `type` is read, so no steady component is built.
    ("is_user_steady_label_in_unsteady_run", U,
     {"case.simulation_components": [{"type": "steady", "is_user": True}]}),
    ("is_user_steady_label_with_two_scalars", N,
     {"case.simulation_components": [{"type": "steady", "is_user": True}],
      "case.scalars": [dict(SCALAR_ITEM, name="s1"),
                       dict(SCALAR_ITEM, name="s2")]}),
    ("steady_is_user_false_is_a_steady_component", S,
     {"case.simulation_components[0].is_user": False}),
    # time_state.f90:76: start_time is read with a constants lookup.
    ("unsteady_start_time_constant_name", U,
     {"case.time.start_time": "t0"}),
    # problem.f90:533,553,625: no window means no clock mismatch.
    ("unsteady_restart_without_objective_window", U,
     {"case.restart_file": "restart.chkp"}),
    # time_window_tester.f90:113-115,199-202: checked only when true.
    ("time_window_require_steady_state_false", U,
     {"optimization.time_window_test": {"require_steady_state": False}}),
    # simulation_component_fctry.f90: an unsteady run may carry lambda2.
    ("unsteady_with_lambda2", U,
     {"case.simulation_components": [{"type": "lambda2"}]}),
    # simulation.f90:271-286: the variable timestep is checked for unsteady
    # runs only; tests/unit/sensitivity/CMakeLists.txt:13 registers one.
    ("steady_with_variable_timestep", S,
     {"case.time.variable_timestep": True}),
    ("unsteady_false_with_variable_timestep", S,
     {"unsteady": False, "case.time.variable_timestep": True}),
    ("unsteady_false_with_steady_simcomp", S, {"unsteady": False}),
    # pc_hsmg.f90:224-225 aborts for order 1 only.
    ("adjoint_hsmg_velocity_order_two", S,
     {"case.numerics.polynomial_order": 2,
      "case.adjoint_fluid.velocity_solver":
      {"type": "cg", "preconditioner": {"type": "hsmg"},
       "absolute_tolerance": 1.0e-4}}),
    # mma_optimizer.f90:194,328-336: without auto_scale the factor is scale.
    ("scale_positive_auto_scale_false", S,
     {"optimization.solver.mma.scale": 2.0,
      "optimization.solver.mma.auto_scale": False}),
]

REJECTED_AS_THE_CODE_ABORTS += [
    # adjoint_scalar_scheme.f90:333-337 + design_brinkman.f90:365-371.
    ("adjoint_scalar_name_abx1", S,
     {"case.adjoint_scalar.name": "abx1"}, "adjoint_scalar.name"),
    ("adjoint_scalar_name_abx2", S,
     {"case.adjoint_scalar.name": "abx2"}, "adjoint_scalar.name"),
    # adjoint_scalar_scheme.f90:321 ('End of record'), checkpoint_payload.f90.
    ("adjoint_scalar_name_67_characters", S,
     {"case.adjoint_scalar.name": _LONG + "x"}, "adjoint_scalar.name"),
    ("adjoint_scalar_name_with_slash", S,
     {"case.adjoint_scalar.name": "s/adj"}, "adjoint_scalar.name"),
    ("adjoint_scalar_name_blank", S,
     {"case.adjoint_scalar.name": " "}, "adjoint_scalar.name"),
    ("adjoint_scalar_default_name_from_63_characters", S,
     {"case.scalar.name": "y" * 63,
      "case.adjoint_scalar.primal_name": "y" * 63}, "primal_name"),
    ("adjoint_scalar_implicitly_enabled_without_scalar", S,
     {"case.scalar": DEL, "case.adjoint_scalar": {
         "boundary_conditions": [], "initial_condition":
         {"type": "uniform", "value": 0.0}},
      "optimization.objectives[0]": {"type": "viscous_dissipation"}},
     "$.case"),
    # steady_simcomp.f90:149-151 / owner ruling: an entry with is_user false
    # is still a steady component.
    ("steady_is_user_false_with_bad_tol", S,
     {"case.simulation_components[0].is_user": False,
      "case.simulation_components[0].tol": 1}, "simulation_components"),
    ("unsteady_with_steady_is_user_false", U,
     {"case.simulation_components": [{"type": "steady", "is_user": False}]},
     "simulation_components"),
    # scalar_mixing_objective_function.f90:171: needs an enabled adjoint
    # scalar, so also an absent one.
    ("scalar_mixing_without_adjoint_scalar", S,
     {"case.adjoint_scalar": DEL}, "$.case"),
    # time_window_tester.f90:128-131,199-202
    ("time_window_test_with_unsteady_false", S,
     {"unsteady": False, "optimization.time_window_test": {}}, "unsteady"),
    ("time_window_require_steady_state_with_freeze_flow_absent", U,
     {"optimization.time_window_test": {"require_steady_state": True}},
     "fluid"),
    # adjoint_fluid_pnpn_bc_fctry.f90:87,149: `type` is read with no default.
    ("adjoint_bc_split_form_without_type", S,
     {"case.adjoint_fluid.boundary_conditions[0]":
      {"zone_indices": [1], "velocity": {"type": "no_slip"}}},
     "boundary_conditions"),
    # pc_hsmg.f90:224-225
    ("adjoint_hsmg_velocity_order_one", S,
     {"case.numerics.polynomial_order": 1,
      "case.adjoint_fluid.velocity_solver":
      {"type": "cg", "preconditioner": {"type": "hsmg"},
       "absolute_tolerance": 1.0e-4}}, "velocity_solver"),
    # output_file is read as a string (adjoint_fluid_pnpn.f90:468-491)
    ("root_output_file_integer", S, {"output_file": 5}, "output_file"),
]

ACCEPTED_BY_THE_CODE += [
    # fluid_scheme_incompressible.f90:202,690-692: with the fluid named
    # `water` the registered fields are water_mu..., so fluid_rho is new.
    ("adjoint_scalar_name_fluid_rho_other_fluid_name", S,
     {"case.fluid.name": "water", "case.adjoint_scalar.name": "fluid_rho"}),
    # a disabled adjoint scalar never reads `name`
    ("disabled_adjoint_scalar_name_fluid_rho", S,
     dict(_NO_SCALAR, **{"case.adjoint_scalar":
                         {"enabled": False, "name": "fluid_rho"}})),
    ("disabled_adjoint_scalar_name_u", S,
     dict(_NO_SCALAR, **{"case.adjoint_scalar":
                         {"enabled": False, "name": "u"}})),
]

_CORIOLIS = {"type": "coriolis", "rotation_vector": [0.0, 0.0, 1.0]}
_CONSTANT = {"type": "constant", "values": [0.0, 0.0, 1.0]}

ACCEPTED_BY_THE_CODE += [
    # state-independent source terms need no adjoint counterpart.
    ("fluid_constant_source_term_with_optimization", S,
     {"case.fluid.source_terms": [_CONSTANT]}),
    ("adjoint_constant_source_term", S,
     {"case.adjoint_fluid.source_term": [_CONSTANT]}),
    # fluid_scheme_incompressible.f90:362-380: svv off is the default.
    ("fluid_svv_disabled_with_optimization", S,
     {"case.fluid.svv": {"enabled": False}}),
]

REJECTED_AS_THE_CODE_ABORTS += [
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


# --------------------------------------------------------------------------- #
# Inputs of rules that were removed when the schemas were cut back to
# structure and aborts: the code accepts them and runs to completion (the
# result may be degenerate or wrong). See removed-rules.md for each one.
# (id, base, edits, where it used to be rejected)
# --------------------------------------------------------------------------- #
ACCEPTED_AFTER_THE_TRIM = [
    ("ic_uniform_negative_with_simp", S,
     {"optimization.design.initial_distribution.value": -0.5,
      "optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p": 2.5}, "initial_distribution"),
    ("ic_uniform_above_one", S,
     {"optimization.design.initial_distribution.value": 1.5},
     "initial_distribution"),
    ("ic_point_zone_zone_value_negative", S,
     {"optimization.design.initial_distribution":
      {"type": "point_zone", "base_value": 0.0, "zone_value": -0.5,
       "zone_name": "optimization_domain"}}, "initial_distribution"),
    ("mma_epsimin_one", S,
     {"optimization.solver.mma.epsimin": 1.0}, "mma.epsimin"),
    ("mma_epsimin_above_one_pdip", S,
     {"optimization.solver.mma.epsimin": 1.2,
      "optimization.solver.mma.subsolver": "pdip"}, "mma.epsimin"),
    ("mma_c_zero_with_constraints", S,
     {"optimization.solver.mma.c": 0.0}, "mma.c"),
    ("mma_c_negative_with_constraints", S,
     {"optimization.solver.mma.c": -1.0}, "mma.c"),
    ("mma_c_negative_pdip_unconstrained", S,
     {"optimization.constraints": [],
      "optimization.solver.mma.subsolver": "pdip",
      "optimization.solver.mma.c": -1.0}, "mma.c"),
    ("mma_a0_negative_pdip", S,
     {"optimization.solver.mma.subsolver": "pdip",
      "optimization.solver.mma.a0": -0.001}, "mma.a0"),
    ("mma_a0_negative_dip_with_a", S,
     {"optimization.solver.mma.a": 1.0,
      "optimization.solver.mma.a0": -1.0}, "mma.a0"),
    ("pde_filter_max_iter_zero", S,
     {"optimization.design.mapping[0].max_iter": 0}, "mapping[0]"),
    ("pde_filter_max_iter_negative", S,
     {"optimization.design.mapping[0].max_iter": -5}, "mapping[0]"),
    ("ramp_q_minus_one", S,
     {"optimization.design.mapping[2].q": -1.0}, "mapping[2]"),
    ("ramp_q_below_minus_one", S,
     {"optimization.design.mapping[2].q": -2.0}, "mapping[2]"),
    ("ramp_q_array_with_minus_one", S,
     {"optimization.design.mapping[2].q": [1.0, -1.0],
      "optimization.design.mapping[2].q_iterations": 2}, "mapping[2]"),
    ("bp_q_zero", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": 0.0}, "mapping[2]"),
    ("bp_q_minus_half", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": -0.5}, "mapping[2]"),
    ("bp_q_minus_one", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": -1.0}, "mapping[2]"),
    ("bp_q_array_with_zero", S,
     {"optimization.design.mapping[2].type": "Borrvall_Petersson",
      "optimization.design.mapping[2].q": [1.0, 0.0],
      "optimization.design.mapping[2].q_iterations": 2}, "mapping[2]"),
    ("simp_p_half", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p": 0.5}, "mapping[2]"),
    ("simp_p_negative", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p": -1.0}, "mapping[2]"),
    ("simp_p_array_below_one", S,
     {"optimization.design.mapping[2].type": "SIMP",
      "optimization.design.mapping[2].q": DEL,
      "optimization.design.mapping[2].p": [2.0, 0.5],
      "optimization.design.mapping[2].p_iterations": 2}, "mapping[2]"),
    ("state_recovery_extra_fields_u_adj", U,
     {"state_recovery.extra_fields": ["u_adj"]}, "extra_fields"),
    ("state_recovery_extra_fields_v_adj", U,
     {"state_recovery.extra_fields": ["v_adj"]}, "extra_fields"),
    ("state_recovery_extra_fields_w_adj", U,
     {"state_recovery.extra_fields": ["w_adj"]}, "extra_fields"),
    ("scalar_constant_source_with_adjoint_scalar", S,
     {"case.scalar.source_terms": [{"type": "constant", "values": [1.0]}]},
     "case.scalar"),
    ("scalar_field_source_with_adjoint_scalar", S,
     {"case.scalar.source_terms": [{"type": "field", "field_names": ["f"]}]},
     "case.scalar"),
    ("adjoint_scalar_name_primal", S, {"case.adjoint_scalar.name": "s"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_velocity", S, {"case.adjoint_scalar.name": "u"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_adjoint_velocity", S,
     {"case.adjoint_scalar.name": "u_adj"}, "adjoint_scalar.name"),
    ("adjoint_scalar_name_adjoint_pressure", S,
     {"case.adjoint_scalar.name": "p_adj"}, "adjoint_scalar.name"),
    ("design_blank_name_with_checkpoint_interval", S,
     {"optimization.design.name": "",
      "optimization.solver.checkpoint.interval": 1}, "design.name"),
    ("mma_max_iter_zero", S, {"optimization.solver.mma.max_iter": 0},
     "max_iter"),
    ("mma_max_iter_negative", S, {"optimization.solver.mma.max_iter": -5},
     "max_iter"),
    ("mma_asyinit_zero", S, {"optimization.solver.mma.asyinit": 0.0},
     "asyinit"),
    ("mma_asyinit_negative", S, {"optimization.solver.mma.asyinit": -0.2},
     "asyinit"),
    ("mma_xmin_above_default_xmax", S,
     {"optimization.solver.mma.xmin": 1.5,
      "optimization.solver.mma.xmax": DEL}, "mma"),
    ("mma_xmax_below_default_xmin", S,
     {"optimization.solver.mma.xmax": -0.5,
      "optimization.solver.mma.xmin": DEL}, "mma"),
    ("mma_scale_negative", S, {"optimization.solver.mma.scale": -1000.0},
     "scale"),
    ("mma_scale_zero", S, {"optimization.solver.mma.scale": 0.0}, "scale"),
    ("mma_scale_zero_with_auto_scale", S,
     {"optimization.solver.mma.scale": 0.0,
      "optimization.solver.mma.auto_scale": True}, "scale"),
    ("state_recovery_path_300_characters", U,
     {"state_recovery.path": "a" * 300}, "state_recovery.path"),
    ("state_recovery_filename_300_characters", U,
     {"state_recovery.filename": "a" * 300}, "state_recovery.filename"),
    ("adjoint_bc_outflow_dong", S,
     {"case.adjoint_fluid.boundary_conditions[1]":
      {"type": "outflow+dong", "zone_indices": [2]}}, "boundary_conditions"),
    ("adjoint_bc_normal_outflow_dong", S,
     {"case.adjoint_fluid.boundary_conditions[1]":
      {"type": "normal_outflow+dong", "zone_indices": [2],
       "value": [1.0, 0.0, 0.0]}},
     "boundary_conditions"),
    ("adjoint_scalar_name_u_e", S, {"case.adjoint_scalar.name": "u_e"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_u_adj_e", S, {"case.adjoint_scalar.name": "u_adj_e"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_fluid_rho", S,
     {"case.adjoint_scalar.name": "fluid_rho"}, "adjoint_scalar.name"),
    ("adjoint_scalar_name_s_cp", S, {"case.adjoint_scalar.name": "s_cp"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_s_lambda_tot", S,
     {"case.adjoint_scalar.name": "s_lambda_tot"}, "adjoint_scalar.name"),
    ("adjoint_scalar_primal_name_u_default_name", S,
     {"case.scalar.name": "u", "case.adjoint_scalar.primal_name": "u"},
     "adjoint_scalar.primal_name"),
    ("adjoint_scalar_primal_name_p_default_name", S,
     {"case.scalar.name": "p", "case.adjoint_scalar.primal_name": "p"},
     "adjoint_scalar.primal_name"),
    ("scalars_item_enabled", S,
     dict(_NO_SCALAR, **{"case.scalars": [dict(SCALAR_ITEM, enabled=True)]}),
     "case.scalars"),
    ("scalars_item_without_enabled", S,
     dict(_NO_SCALAR, **{"case.scalars": [dict(SCALAR_ITEM)]}),
     "case.scalars"),
    ("scalar_enabled_implicit", S, {"case.scalar.enabled": DEL},
     "case.scalar"),
    ("scalar_advection_false", S, {"case.scalar.advection": False},
     "case.scalar"),
    ("scalar_alphat", S, {"case.scalar.alphat": {"nut_dependency": False,
                           "alphat_field": "at"}},
     "case.scalar"),
    ("scalar_svv_enabled", S, {"case.scalar.svv": {"enabled": True,
      "kernel": {"type": "power", "power_coefficient": 1.0},
      "nu": {"type": "value", "value": 1.0}}},
     "case.scalar"),
    ("scalar_freeze", S, {"case.scalar.freeze": True}, "case.scalar"),
    ("start_time_in_unsteady_run", U, {"case.time.start_time": 1.0},
     "start_time"),
    ("adjoint_scalar_name_design_indicator", S,
     {"case.adjoint_scalar.name": "design_indicator"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_sensitivity", S,
     {"case.adjoint_scalar.name": "sensitivity"}, "adjoint_scalar.name"),
    ("scalar_name_brinkman_amplitude", S,
     {"case.scalar.name": "brinkman_amplitude",
      "case.adjoint_scalar.primal_name": "brinkman_amplitude"},
     "scalar.name"),
    ("adjoint_scalar_name_fluid_rho_default_fluid", S,
     {"case.adjoint_scalar.name": "fluid_rho"}, "adjoint_scalar.name"),
    ("adjoint_scalar_name_fluid_rho_explicit_fluid_name", S,
     {"case.fluid.name": "fluid", "case.adjoint_scalar.name": "fluid_rho"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_s_cp_explicit_scalar_name", S,
     {"case.scalar.name": "s", "case.adjoint_scalar.name": "s_cp"},
     "adjoint_scalar.name"),
    ("adjoint_scalar_name_u_implicitly_enabled", S,
     {"case.adjoint_scalar.enabled": DEL, "case.adjoint_scalar.name": "u"},
     "adjoint_scalar.name"),
    ("unsteady_restart_with_objective_window", U,
     {"case.restart_file": "restart.chkp",
      "optimization.objectives[0].start_time": 0.01}, "objectives"),
    ("unsteady_restart_with_objective_end_time", U,
     {"case.restart_file": "restart.chkp",
      "optimization.objectives[0].end_time": 0.02}, "objectives"),
    ("scale_negative_auto_scale_false", S,
     {"optimization.solver.mma.scale": -1.0,
      "optimization.solver.mma.auto_scale": False}, "mma.scale"),
    ("fluid_svv_enabled_with_optimization", S,
     {"case.fluid.svv": {"enabled": True,
                         "kernel": {"type": "power",
                                    "power_coefficient": 1.0},
                         "nu": {"type": "value", "value": 0.1}}},
     "fluid.svv.enabled"),
    ("fluid_coriolis_source_term_with_optimization", S,
     {"case.fluid.source_terms": [_CORIOLIS]}, "fluid.source_terms"),
    ("adjoint_coriolis_source_term", S,
     {"case.adjoint_fluid.source_term": [_CORIOLIS]},
     "adjoint_fluid.source_term"),
]


def ids(table):
    return [row[0] for row in table]


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, base, edits", ACCEPTED_BY_THE_CODE,
                         ids=ids(ACCEPTED_BY_THE_CODE))
def test_accepted_by_the_code(validator, name, base, edits):
    found = errors(validator, build(base, edits))
    assert not found, short(found)


@pytest.mark.parametrize("name, base, edits, where",
                         ACCEPTED_AFTER_THE_TRIM,
                         ids=ids(ACCEPTED_AFTER_THE_TRIM))
def test_accepted_after_the_trim(validator, name, base, edits, where):
    """The code accepts these and runs to completion, so the schemas do not
    reject them any more (removed-rules.md lists each rule)."""
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


@pytest.mark.parametrize("name, base, path, literal, constant", NUMERIC_KEYS,
                         ids=ids(NUMERIC_KEYS))
def test_numeric_keys_accept_names(validator, name, base, path, literal,
                                   constant):
    pre = NUMERIC_PRE_EDITS.get(name, {})
    found = errors(validator, build(base, dict(pre, **{path: literal})))
    assert not found, f"{name}: the literal: {short(found)}"
    found = errors(validator, build(base, dict(pre, **{path: constant})))
    assert not found, f"{name}: the constants name: {short(found)}"
    # An empty name is no name.
    assert error_paths(validator, build(base, dict(pre, **{path: ""}))), (
        f"{name}: an empty string is accepted")
    if isinstance(literal, float):
        # json-fortran stores 1 and 1.0 as different types; the reader of a
        # real rejects the integer (neko src/common/json_utils.f90:510), with
        # or without the lookup.
        assert error_paths(
            validator, build(base, dict(pre, **{path: int(literal)}))), (
            f"{name}: an integer is accepted where a real is read")
    if isinstance(literal, int):
        assert error_paths(
            validator, build(base, dict(pre, **{path: literal + 0.5}))), (
            f"{name}: a real is accepted where an integer is read")


@pytest.mark.parametrize("name, base, edits", ACCEPTS_CONSTANT_NAMES,
                         ids=ids(ACCEPTS_CONSTANT_NAMES))
def test_accepts_constant_names(validator, name, base, edits):
    found = errors(validator, build(base, edits))
    assert not found, short(found)


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
    for name, base, edits, _ in ACCEPTED_AFTER_THE_TRIM:
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


@pytest.mark.parametrize("path, value", [
    ("case.fluid.Re", 100),            # a real, written as an integer
    ("case.time.timestep", 1),         # likewise
    ("case.time.end_time", 2),
    ("case.numerics.polynomial_order", 5.0),   # an integer, written as a real
    ("case.numerics.time_order", 2.0),
])
def test_neko_typed_keys_stay_strict_below_the_neko_reference(
        validator, neko_validator, path, value):
    """The root reaches Neko's case-file schema through a `$ref` to the whole
    resource, which declares `$schema` 2020-12. Without care the validator
    class is swapped there for the stock Draft202012Validator, which accepts
    100 for a real and 5.0 for an integer, where Neko's reader rejects both.
    Neko's own root is the control: it must reject the same inputs."""
    instance = build(N, {path: value})
    assert error_paths(neko_validator, instance), "control: Neko accepts it"
    found = error_paths(validator, instance)
    assert any(p.endswith(path.split(".", 1)[1]) or path in p
               for p in found), f"{path}={value!r} accepted: {found}"


def test_strict_class_survives_a_whole_resource_ref(registry, schemas):
    """Direct check of the cause: descending into Neko's case-file resource
    must keep the strict class (x-neko-real and the strict integer type)."""
    root = vcs.make_validator(registry, schemas, "neko-top")
    resolved = registry.get_or_retrieve(vcs.ROOT_IDS["neko"]).value.contents
    inner = root.evolve(schema=resolved)
    assert "x-neko-real" in type(inner).VALIDATORS
    assert not inner.is_type(5.0, "integer")


# --------------------------------------------------------------------------- #
# Rules that Neko's own root already enforces by another route are tested on
# Neko-TOP's `optimizing` definition alone, so that they cannot hide behind it.
# --------------------------------------------------------------------------- #
def test_exact_output_time_rule_is_ours(registry):
    """simulation.f90:289-297 aborts an unsteady run with
    case.time.exact_output_time true, whatever variable_timestep says. Neko's
    time schema rejects the input through its own rule; this rule must not
    depend on that."""
    validator = vcs.strict_validator_class()(
        {"$ref": "urn:neko-top:schema:case-file#/$defs/optimizing"},
        registry=registry)
    good = build(U, {"case.time.exact_output_time": False})
    assert not errors(validator, good)
    bad = build(U, {"case.time.exact_output_time": True,
                    "case.time.variable_timestep": False})
    assert any("exact_output_time" in path
               for path in error_paths(validator, bad))


def test_common_solver_keys_are_defined_once(top_schemas):
    """mma and steepest_descent read these keys through one Fortran routine
    (optimizer.f90:415-449): both closed objects refer to one definition, so
    the two cannot drift."""
    schema = top_schemas["urn:neko-top:schema:optimizer"]["$defs"]
    shared = ["max_iterations", "enable_output", "max_runtime",
              "stop_design_change", "restart_file", "checkpoint",
              "continuation_iterations"]
    for key in shared:
        mma = schema["mmaSolver"]["properties"][key]
        sd = schema["steepestDescentSolver"]["properties"][key]
        assert mma == sd and list(mma) == ["$ref"], key
