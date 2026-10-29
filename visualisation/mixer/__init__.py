# We want to expose the entire design_evolution.py script as a function that can
# be called from other scripts. This is useful for running the design evolution
# from a driver script, for example. The design evolution does not contain any
# functions that can be called from other scripts, so we need to wrap it in a
# function that can be called from other scripts. There is also no main
# function, it is a pure state export from ParaView.
__all__ = ["run_design_evolution"]


def run_design_evolution():
    import design_evolution
    design_evolution.main()
