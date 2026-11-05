#!/bin/bash

# In this file make changes to the BSUB variables to control the DTU hpc
# settings.
#
# In addition, all modules should be loaded and python virtualenv should be
# setup if python is used in either testing or visualisation.
# Modules and python setups can be done in a seperate file and supplied through
# the FILES variable in submit.sh. This will ensure a uniform setup.

# =============================================================================
# Define the BSUB options here.

# --  Technical Options

# Queue name
#BSUB -q "gpuv100"

# Ask for n cores placed on R host.
#BSUB -n 4
#BSUB -R "span[ptile=4]"
#BSUB -gpu "num=1:mode=exclusive_process"

# Memory specifications. Amount we need and when to kill the
# program using too much memory.

#BSUB -R "rusage[mem=4GB]"
#BSUB -M 4GB

# Time specifications (hh:mm)
#BSUB -W 02:00

# -- Notification options

# Set the email to recieve to and when to recieve it
#BSUB -Ne    # Send notification at completion

# -- Mandatory options, change with great care.

# Definitions of output files.
#BSUB -oo output.log
#BSUB -eo error.err

# ============================================================================ #
# Determine if the script is run on the HPC or locally

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

source ~/Software/load.sh
cd ~/Projects/neko-top

RESULT_ROOT=${RESULT_ROOT:-results/static_mixer}
gifmaker=scripts/python/gif_maker.py
visualiser=examples/static_mixer/visualise.py

experiments=$(find $RESULT_ROOT -type d | sort)

colors=(
    black
    white
)

for exp in "${experiments[@]}"; do
    exp=${exp##$RESULT_ROOT/}
    if [[ ! -d "$RESULT_ROOT/$exp" ]]; then
        echo "Results for experiment $exp not found. Skipping visualization."
        continue
    elif [[ ! -f "$RESULT_ROOT/$exp/brinkman_0.vtkhdf" ]]; then
        echo "Required file brinkman_0.vtkhdf for experiment $exp not found. Skipping visualization."
        continue
    else
        echo "Visualizing results for experiment $exp."
    fi

    for color in "${colors[@]}"; do
        Temp_gif=$RESULT_ROOT/$exp/visualisation/Temperature_${color}.gif
        Vel_gif=$RESULT_ROOT/$exp/visualisation/Velocity_${color}.gif
        if [[ ! -f "$Temp_gif" || ! -f "$Vel_gif" ]]; then

            # Run the ParaView visualizer.
            pvbatch $visualiser --text-color=$color $RESULT_ROOT/$exp/

            # If the srun was cancelled, skip the gif creation to avoid errors
            if [[ $? -ne 0 ]]; then
                echo "Visualization for $exp with color $color was cancelled."
                continue
            fi

            # Create the gifs from the generated png files.
            python $gifmaker --pattern Temperature_[0-9]*.png --fps 25 \
                --quality high $RESULT_ROOT/$exp/visualisation/${color}/
            python $gifmaker --pattern Velocity_[0-9]*.png --fps 25 \
                --quality high $RESULT_ROOT/$exp/visualisation/${color}/
        fi
    done
done


# ==============================   End of File   ==============================
