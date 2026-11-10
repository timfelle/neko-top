#!/usr/bin/env pvpython
"""Load a ParaView state file (.pvsm) and export an animation of all frames.

The output frames are stored in a subdirectory of the data directory, named
after the state file.

Usage:
    pvpython paraview_runner.py state.pvsm data_dir

Additional arguments:
    --resolution H: Set the height of the output images (default: 360)
    --frames START END: Export only frames from START to END (inclusive)
    --index-source FILE: Chunked VTKHDF file that defines global frame indices
    --overwrite: Overwrite existing files in the output directory
"""

import argparse
import os
import re
import runpy
import subprocess
from pathlib import Path

from paraview.simple import (
    GetActiveViewOrCreate,
    GetAnimationScene,
    LoadState,
    LoadPlugin,
    SaveScreenshot,
)


def global_frame_range(index_source, data_directory):
    index_path = Path(index_source)
    if not index_path.is_absolute():
        index_path = Path(data_directory) / index_path
    if index_path.suffix.lower() != ".vtkhdf":
        raise ValueError(
            f"--index-source must point to a .vtkhdf file: {index_path}")
    if not index_path.is_file():
        raise ValueError(f"Unable to read index source {index_path}")

    try:
        import h5py
    except ImportError:
        try:
            result = subprocess.run(
                ["h5dump", "--attribute", "/source_steps",
                 str(index_path)],
                capture_output=True,
                check=False,
                text=True,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                "--index-source requires h5py or h5dump") from error
        if result.returncode:
            raise ValueError(
                f"--index-source is not a chunked VTKHDF file: {index_path}")
        source_steps_match = re.search(
            r"DATA\s*\{\s*(?:\(\d+\):\s*)?(-?\d+)\s*,\s*(-?\d+)",
            result.stdout,
            flags=re.DOTALL,
        )
        if source_steps_match is None:
            raise ValueError(f"Invalid source_steps metadata in {index_path}")
        source_steps = source_steps_match.groups()
    else:
        try:
            with h5py.File(index_path, "r") as index_file:
                source_steps = index_file.attrs.get("source_steps")
        except OSError as error:
            raise ValueError(
                f"Unable to read index source {index_path}") from error

    if source_steps is None:
        raise ValueError(
            f"--index-source is not a chunked VTKHDF file: {index_path}")

    try:
        start_frame, end_frame = source_steps
        start_frame = int(start_frame)
        end_frame = int(end_frame)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Invalid source_steps metadata in {index_path}") from error

    if start_frame < 0 or end_frame < start_frame:
        raise ValueError(f"Invalid source_steps metadata in {index_path}")
    return start_frame, end_frame


def main():
    parser = argparse.ArgumentParser(
        description="Run a ParaView animation export.")
    parser.add_argument("state", help="Path to the .pvsm state file")
    parser.add_argument("data_dir", help="Path to the data directory")
    parser.add_argument(
        "--output_dir",
        help=
        "Path to the output directory (default: data_dir/visualisations/<state_name>)"
    )
    parser.add_argument("--resolution",
                        type=int,
                        default=360,
                        help="Height of the output images (default: 360)")
    parser.add_argument("--frames",
                        nargs=2,
                        type=int,
                        default=None,
                        metavar=("START", "END"))
    parser.add_argument(
        "--index-source",
        help=("Path to a chunked .vtkhdf file used to map local frames to "
              "global frame indices; relative paths use data_dir"),
    )
    parser.add_argument("--overwrite",
                        action="store_true",
                        help="Overwrite existing files")
    parser.add_argument(
        "--design-file",
        default="design_0.vtkhdf",
        help="Path to the design file (default: design_0.vtkhdf)")
    parser.add_argument(
        "--forward-file",
        default="forward_fields_0.vtkhdf",
        help=
        "Path to the forward fields file (default: forward_fields_0.vtkhdf)")

    args = parser.parse_args()

    if not os.path.isdir(args.data_dir):
        raise NotADirectoryError(args.data_dir)
    if args.data_dir[-1] != os.sep:
        args.data_dir += os.sep

    # Add our visualisation modules to the Python path so we can import them.
    visualisation_dir = os.path.join(os.path.dirname(__file__),
                                     "../../visualisation/mixer")
    print(
        f"Adding visualisation directory to Python path: {visualisation_dir}")
    if visualisation_dir not in os.sys.path:
        os.sys.path.append(visualisation_dir)

    # Load the VTKm plugin to enable VTKm filters in ParaView
    LoadPlugin("VTKmFilters", remote=True)

    # Load the ParaView state file and extract view and scene information
    if os.path.splitext(args.state)[1] == ".pvsm":
        LoadState(
            args.state,
            data_directory=args.data_dir,
            restrict_to_data_directory=True,
        )
    elif "." not in args.state:
        # If the state is a string, execute the corresponding visualization
        # module with the data directory available to its top-level code.
        if args.state == "design_evolution":
            runpy.run_module(args.state,
                             init_globals={
                                 "data_directory": args.data_dir,
                                 "design_file": args.design_file,
                                 "forward_file": args.forward_file,
                             })
        else:
            raise ValueError(f"Unknown state function: {args.state}")
    else:
        raise ValueError(
            f"State file must have a .pvsm extension or be a function name: {args.state}"
        )

    view = GetActiveViewOrCreate("RenderView")
    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    scene.PlayMode = "Snap To TimeSteps"

    # Scale the view and PPI to match the specified resolution.
    original_size = list(view.ViewSize)
    original_ppi = view.PPI

    scale = args.resolution / original_size[1]
    output_resolution = [int(original_size[0] * scale), args.resolution]

    view.ViewSize = output_resolution
    view.PPI = round(original_ppi * scale)
    view.UpdateVTKObjects()

    # Set the frame index range to export.
    timestep_values = list(scene.TimeKeeper.TimestepValues)
    frame_count = len(timestep_values)
    if frame_count == 0:
        raise ValueError("No animation frames are available")

    if args.index_source:
        global_start, global_end = global_frame_range(args.index_source,
                                                      args.data_dir)
        if global_end - global_start + 1 != frame_count:
            raise ValueError(
                f"Index source covers frames {global_start}-{global_end}, "
                f"but the animation has {frame_count} frames")
    else:
        global_start, global_end = 0, frame_count - 1

    if args.frames:
        if (args.frames[0] > args.frames[1] or args.frames[0] < global_start
                or args.frames[1] > global_end):
            raise ValueError(
                f"Frame range {args.frames} is out of bounds " +
                f"for available frames {global_start}-{global_end}")
        start_frame = args.frames[0] - global_start
        end_frame = args.frames[1] - global_start
    else:
        start_frame, end_frame = 0, frame_count - 1

    # Determine the output location and ensure the directory exists.
    state_name = os.path.splitext(os.path.basename(args.state))[0]
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(args.data_dir, "visualisations", state_name)
    os.makedirs(output_dir, exist_ok=True)

    for frame_index in range(start_frame, end_frame + 1):
        timestep = timestep_values[frame_index]
        global_frame = global_start + frame_index
        if args.state == "design_evolution":
            iteration = int(timestep)
            if timestep != iteration:
                raise ValueError(
                    "design_evolution timestep values must be integer design iterations"
                )
            frame_file = os.path.join(output_dir, f"{iteration:04d}.png")
            frame_label = f"design iteration {iteration}"
        else:
            frame_file = os.path.join(output_dir, f"{global_frame:04d}.png")
            frame_label = f"frame {global_frame}"

        if not args.overwrite and os.path.isfile(frame_file):
            continue

        print(f"Exporting {frame_label}")
        scene.AnimationTime = timestep
        scene.TimeKeeper.Time = timestep
        SaveScreenshot(
            frame_file,
            view,
            ImageResolution=output_resolution,
            CompressionLevel=0,
        )


if __name__ == "__main__":
    main()
