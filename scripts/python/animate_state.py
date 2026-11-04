#!/usr/bin/env pvpython
"""Load a ParaView state and export an animation of all frames.

The output frames are stored in a subdirectory of the data directory, named
after the state file.

A state can be specified either as a .pvsm file or as a string corresponding to
a Python module in the visualisation directory.

Usage:
    pvpython paraview_runner.py STATE DATA_DIR [OPTIONS]

STATE and DATA_DIR are the first and second arguments. They must appear before
all options because --input-files accepts a greedy list.

Additional arguments:
    --resolution H: Set the height of the output images (default: 360)
    --frames START END: Export global frames from START to END (inclusive)
    --chunk START-END: Chunk suffix produced by vtkhdf_extract
    --input-files FILE [FILE ...]: Input files for the visualization state
    --overwrite: Overwrite existing files in the output directory
"""

import argparse
import os
import re
import runpy
import sys

from paraview.simple import (
    GetActiveViewOrCreate,
    GetAnimationScene,
    LoadState,
    LoadPlugin,
    SaveScreenshot,
)


def chunk_frame_info(chunk):
    CHUNK_PATTERN = re.compile(r"^(\d+)-(\d+)$")
    match = CHUNK_PATTERN.fullmatch(chunk)
    if match is None:
        raise ValueError(
            "--chunk must be the START-END suffix produced by vtkhdf_extract")

    start_text, end_text = match.groups()
    start_frame, end_frame = int(start_text), int(end_text)
    if end_frame < start_frame:
        raise ValueError("--chunk end must not precede its start")
    return start_frame, end_frame, max(len(start_text), len(end_text))


def input_file(file_name, chunk):
    if chunk:
        base_name, ext = os.path.splitext(file_name or "")
        return f"{base_name}_steps_{chunk}{ext}"
    else:
        return file_name


def main():
    parser = argparse.ArgumentParser(
        description="Run a ParaView animation export.")
    parser.add_argument("state",
                        help="First argument: .pvsm path or state name")
    parser.add_argument("data_dir",
                        help="Second argument: path to the data directory",
                        type=str)
    parser.add_argument(
        "--output-dir",
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
                        metavar=("START", "END"),
                        help="Global frame range to export (inclusive)")
    parser.add_argument("--chunk",
                        metavar="START-END",
                        help=("Chunk suffix produced by vtkhdf_extract, "
                              "including zero padding"))
    parser.add_argument("--overwrite",
                        action="store_true",
                        help="Overwrite existing files")
    parser.add_argument(
        "--input-files",
        nargs="+",
        default=[],
        metavar="FILE",
        help=("Input files for the visualization state; design_evolution "
              "uses the first as design and the second as forward fields"),
    )

    arguments = sys.argv[1:]
    if (len(arguments) >= 1 and arguments[0] not in {"-h", "--help"}
            and arguments[0].startswith("-")):
        parser.error("STATE must be the first argument")
    if (len(arguments) >= 2 and arguments[1] not in {"-h", "--help"}
            and arguments[1].startswith("-")):
        parser.error("DATA_DIR must be the second argument")
    args = parser.parse_args(arguments)

    if not os.path.isdir(args.data_dir):
        raise NotADirectoryError(args.data_dir)
    if args.data_dir[-1] != os.sep:
        args.data_dir += os.sep

    # Add our visualisation modules to the Python path so we can import them.
    visualisation_dir = os.path.join(os.path.dirname(__file__),
                                     "../../visualisation")
    if visualisation_dir not in sys.path:
        sys.path.append(visualisation_dir)

    for path in os.listdir(visualisation_dir):
        subdir = os.path.join(visualisation_dir, path)
        if os.path.isdir(subdir) and subdir not in sys.path:
            sys.path.append(subdir)

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
            input_files = args.input_files or [
                "design_0.vtkhdf", "forward_fields_0.vtkhdf"
            ]

            if len(input_files) != 2:
                raise ValueError(
                    "design_evolution requires exactly two --input-files")

            design_file = input_file(input_files[0], args.chunk)
            forward_file = input_file(input_files[1], args.chunk)

            if not os.path.isfile(os.path.join(args.data_dir, design_file)):
                raise FileNotFoundError(
                    f"Design file not found: {design_file} in {args.data_dir}")
            if not os.path.isfile(os.path.join(args.data_dir, forward_file)):
                raise FileNotFoundError(
                    f"Forward fields file not found: {forward_file} in {args.data_dir}"
                )

            runpy.run_module(args.state,
                             init_globals={
                                 "data_directory": args.data_dir,
                                 "design_file": design_file,
                                 "forward_file": forward_file,
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

    if args.chunk:
        global_start, global_end, frame_digits = chunk_frame_info(args.chunk)
        if global_end - global_start + 1 != frame_count:
            raise ValueError(
                f"Chunk covers frames {global_start}-{global_end}, "
                f"but the animation has {frame_count} frames")
    else:
        global_start, global_end = 0, frame_count - 1
        frame_digits = len(str(global_end))

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
        frame_file = os.path.join(output_dir,
                                  f"{global_frame:0{frame_digits}d}.png")
        frame_label = f"frame {global_frame}"

        if not args.overwrite and os.path.isfile(frame_file):
            continue

        print(f"Exporting {frame_label}")
        scene.AnimationTime = timestep
        scene.TimeKeeper.Time = timestep
        view.Update()
        view.StillRender()
        SaveScreenshot(
            frame_file,
            view,
            ImageResolution=output_resolution,
            CompressionLevel=0,
        )


if __name__ == "__main__":
    main()
