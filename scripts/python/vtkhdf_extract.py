# This python script should be used to extract data from a vtkhdf file format as
# written by Neko.
# We want to support a couple of operations:
# - Extracting a specific timestep and writing it to a new vtkhdf single file
#   without the virtual dataset.
# - Splitting a temporal vtkhdf file into chunks of a specific number of
#   timesteps, a specific time window, or given a specific storage footprint.
