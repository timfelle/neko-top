# Sensitivity analysis of a steepest-descent mixer run {#sensitivity-test}

The scripts in this directory help diagnose why a steepest-descent
topology optimisation of a mixer does, or does not, move its design. They
read the output a Neko-TOP run has already written, change nothing, and
print plain-text reports:

- `sd_report.py`: how much of the design is held by a bound, what sets
  the step, and does the stored update follow from the stored
  sensitivity?
- `dissipation_split.py`: which part of the design carries the
  Brinkman-dissipation objective, and how much of it is set by the
  mapping alone?
- `fluid_sensitivity.py`: is the fluid's sensitivity the explicit
  Brinkman-dissipation derivative, and where does the fluid want
  material?
- `weight_scan.py`: which objective sets the seed sensitivity, and what
  would other weights free?
- `overintegration_check.py`: does the nodal Brinkman-dissipation
  integral agree with over-integration?

`sensitivity_tools.py` is the module the scripts share (output reader,
quadrature, volume weights, mapping formulas). Keep it next to the
scripts. The scripts need Python 3 with numpy and h5py
(`pip install -r requirements.txt`) and run on one core, without MPI.

## Output the scripts read

All scripts take a run directory, `RUN_DIR`, which holds the output series
of the run and its case file (`*.case`; pass `--case FILE` if it lives
elsewhere, e.g. when the case sets `output_directory`). Each series
`<name>` is a `<name>_0.vtkhdf` file with the mesh and a `<name>_0.data/`
directory with one `<k>.h5` file per iteration `k`. Both need the
`vtkhdf` output format:

- `design_0`: written by the Brinkman design when
  `optimization.design.output_format` is `"vtkhdf"`. The field
  `design_indicator` is always there; `PDE_filter_mapping` (the filtered
  design) and `brinkman_amplitude` (the Brinkman amplitude) need
  `"verbose_design": true`.
- `sensitivity_0`: the sensitivity `dFd_design_indicator`, written next to
  the design.
- `forward_fields_0`: the forward state (`Velocity`, `Pressure`, scalars)
  the optimiser writes at the end of each iteration's forward run, in the
  format of `case.fluid.output_format`.
- `optimization_data.csv`: echoed by `sd_report.py` if present; its
  objective values give the actual change of each step in `sd_report.py`
  and `weight_scan.py`.

What each script reads:

- `sd_report.py`: `design_indicator` and the sensitivity, every
  iteration, and `optimization_data.csv`.
- `dissipation_split.py`: all three design fields (`verbose_design`) and
  the forward fields.
- `fluid_sensitivity.py`: `design_indicator`, `PDE_filter_mapping`
  (`verbose_design`), the sensitivity and the forward fields.
- `weight_scan.py`: the sensitivity of every run and `design_indicator`
  of the total run, iteration 0; also the total run's iteration-1 design
  and `optimization_data.csv`, if present; the same of every `--check`
  run.
- `overintegration_check.py`: `brinkman_amplitude` (`verbose_design`) and
  the forward fields.

For `weight_scan.py`, evaluate the sensitivity of the seed design once
with all objectives (the total run) and once for each objective on its
own, by copying the case, keeping one entry of `optimization.objectives`
or setting the weight of the others to `0.0`, and setting
`"max_iterations": 0` in `optimization.solver`. Everything else (mesh,
mapping, initial design, time span) must be the same.

## Usage

Each script prints its options with `--help`.

### `sd_report.py`

```bash
python3 sd_report.py RUN_DIR
python3 sd_report.py RUN_DIR --iters 0,19 --top 20 --save peak.npz
```

For every iteration it prints the design's bound fractions, the
sensitivity range, the free set and its normaliser, the largest free
values, the move limits, and a replay check; a summary table with one
line per iteration closes the report.

- *Held by a bound*: a node at the lower bound whose sensitivity is
  positive (or at the upper bound with a negative one) is pushed against
  its bound and cannot move. The rest is the free set; if the free
  volume fraction is tiny, the run can only change a thin layer of the
  design.
- *Normaliser*: steepest descent scales the update with the largest free
  |g|, so every other free node moves by |g| / largest. The ratio
  "largest / median" shows how much one large value slows down the rest.
- *Isolation*: |g| of a listed node over the mean |g| of its nearest
  GLL neighbours. Near 1 means a smooth maximum; far above 1 means a
  single-node peak sets the normaliser.
- *What limits the step*: the share of the free volume whose step is
  capped by the move limit rather than by the normaliser.
- *Replay check*: the update is replayed offline from design k and
  sensitivity k, and the result is compared with the stored design k+1.
  A largest difference at round-off level (about 1e-7 for single
  precision output) shows that the stored data explains the step; a
  larger one is flagged in the output.
- *First-order prediction*: the change of the objective that the
  sensitivity of iteration k predicts for the step to k+1, the sum over
  the design domain of B g_k (x_{k+1} - x_k) (the stored sensitivity is
  the function g with <g, phi> = delta F, and B the mass), against the
  change of `Total objective function` in `optimization_data.csv`, with
  each objective's weighted change at the weights of row k (those of
  sensitivity k). The sum runs over every node: Neko-TOP sets the
  design and the sensitivity to zero outside its design domain. A ratio
  actual / predicted near 1 means the step stays in the linear range;
  far from 1, or of the wrong sign, the step is too long for the
  sensitivity to describe it, unless a continued weight or design
  parameter (such as RAMP `q` given as an array) changes between the two
  rows: then the logged change includes that change at a fixed design,
  the block says which, and the summary table marks the ratio with `*`
  (a weight) or `^` (another parameter). The summary table repeats the
  ratio. A run stores only the weighted sum of the sensitivities, so the
  prediction is for the objective as a whole; `weight_scan.py` splits it
  by objective.

### `dissipation_split.py`

```bash
python3 dissipation_split.py RUN_DIR --iters 0,19
```

Prints the integral of amplitude * |u|^2 for the stored snapshot, its
share by band of the filtered design and by solid against the rest, and
the same integral with the amplitude recomputed for RAMP q = 0, 1, 4, 8,
16 and for a Heaviside projection (beta = 4, 8, 16) ahead of RAMP. A
large share in the bands between 0.01 and 0.99 means the objective is
dominated by the filter's grey rim rather than by the solid; the ratios
show how much of the value the mapping alone sets.

### `fluid_sensitivity.py`

```bash
python3 fluid_sensitivity.py RUN_DIR --iters 0,19 --steady 0,1
python3 fluid_sensitivity.py RUN_DIR --box 1.7,2.0,0.2,0.5,0.2,0.5
```

Over the fluid of the design domain it compares the sensitivity with the
explicit Brinkman-dissipation derivative 0.5 w_B / V * RAMP'(r) * |u|^2,
with the weight w_B of each iteration (stepped through a continuation
array as Neko-TOP does). Where w_B is zero, as in a run of another
objective alone, that comparison is marked not applicable and the rest
is printed. Quantiles of the ratio near 1 mean the sensitivity is that
explicit term (and positive, so the fluid stays fluid); the rows by
distance to the block show where the adjoint terms matter. It then
locates the fluid with negative sensitivity, which is free to gain
material, and prints the design there at the last listed iteration: if
the design has not grown there, something other than the sign holds it.
The last line compares the forward velocity of the two `--steady`
iterations; without `--steady`, it gets a note instead if the iteration
after the first listed one is not stored (as in a run that stores a
single iteration).

The block is the box of the point zone of the design's
`initial_distribution`. If the design is not seeded from a box point
zone, pass `--box`.

### `weight_scan.py`

```bash
python3 weight_scan.py TOTAL_RUN MIX_RUN VISC_RUN BRINK_RUN
python3 weight_scan.py MIX_RUN TOTAL_RUN VISC_RUN --factors 1:1,1:0.1,0:0
python3 weight_scan.py TOTAL_RUN MIX_RUN VISC_RUN BRINK_RUN --check RUN_B01
```

The runs can be given in any order; each case file says which objective
the run holds. Only active objectives count, those whose weight at
iteration 0 is not zero: a single-objective run may list the other
objectives at weight `0.0`, and an objective at weight `0.0` in the
total run is not part of the total. The viscous- and the
Brinkman-dissipation weight of the total run are scanned, so neither may
be zero there. An entry at weight `0.0` is ignored whatever its type,
but two active entries of one type (say two masked mixing objectives)
stop the script, which splits the sensitivity by type; this holds for
the Brinkman-dissipation entry of `fluid_sensitivity.py` too. The header
lines mark inactive objectives, default weights (1 where `weight` is not
set) and continuation arrays, whose first entry is the weight at
iteration 0. A single-objective run with a weight different from the
total run's is rescaled to the total run's weight (stated in the
header). With a run for every objective, the additivity line checks
that the parts add up to the total: a relative difference far above
round-off means the runs differ in more than the objectives. With one
objective missing, its part is the total minus the others and the
header says so.

The first table gives each part's size over the fluid and where it wants
material (negative). If the total run also stores its iteration-1
design and `optimization_data.csv` (one steepest-descent step), the
second table splits the first-order prediction of that step by
objective, the sum of B part (x_1 - x_0), against each objective's
weighted change in the log, all at the weights of the total run; the
sum of the parts' predictions is checked against the prediction from
the total sensitivity, which `sd_report.py` prints. Otherwise a one-line
note stands in its place. The scan multiplies the viscous- and the
Brinkman-dissipation weight by the factors in `--factors` and reports how
much fluid is free to gain material and how much solid is free to lose
it; a scan row where both are large is a weight choice that lets the
design move. A row where nothing is free (every weight at zero, say)
shows n/a for the ratio and the median.

`--check RUN` (repeatable) tests the scan against a run made with other
weights, say the Brinkman-dissipation weight times 0.1. The check run is
not one of the runs above; it must have the total run's mesh, seed
design (to float32 round-off), design mapping and design domain, every
objective active in it must be a part, and the file of its
iteration-0 sensitivity (symbolic links followed) must not be that of
one of the runs above or of another check run (which would agree by
construction), or the script stops before it prints anything. After
the scan it prints, for each check run, the factor on each part (its
weight over the total run's), the largest node-wise difference between
its stored sensitivity and the sum of the parts times their factors,
the scan-row quantities from both side by side, and, if it stores
design 1 and its `optimization_data.csv`, its own first step split by
objective. At iteration 0 the sensitivity is linear in the weights, so
a difference at the level of the additivity line, and identical
scan-row quantities, confirm the bookkeeping and the additivity of the
runs; they do not test the physics. The step section does: it shows
whether the first-order prediction from the seed design holds for the
step the run actually took.

### `overintegration_check.py`

```bash
python3 overintegration_check.py RUN_DIR --iteration 0 --points 7
```

Prints the nodal and the interpolated range of the Brinkman amplitude,
and half the integral of amplitude * |u|^2 over the volume with nodal
quadrature and with over-integration on `--points` Gauss-Legendre points
per direction. For a smooth amplitude the two agree closely. A negative
interpolated amplitude, as after a sharp Heaviside projection, can make
the over-integrated value negative even though every nodal value is
positive; the last number gives that negative contribution.

## Run time and memory

Measured on a 256x64x64 mesh of order 3 (67 million local nodes, single
precision output, 20 iterations), reading from a local disk:

- `sd_report.py`: about 6 s per iteration (114 s for 20 iterations),
  4.8 GB.
- `dissipation_split.py --iters 0,19`: 18 s, 0.2 GB.
- `fluid_sensitivity.py --iters 0,19`: 23 s, 1.0 GB.
- `overintegration_check.py` (7 points): 32 s, 0.4 GB.
- `weight_scan.py`: not measured at this size; it holds about as many
  mesh-sized arrays as `sd_report.py`, so expect about 5 GB.

`sd_report.py` and `weight_scan.py` hold several mesh-sized arrays at a
time; the other three read in chunks of elements and stay well below
2 GB at any mesh size. Expect slower runs on network file systems.

## Limits

- The volume weights use one box volume per element (the extent of its
  nodes), so the mesh must consist of axis-aligned box elements; they may
  differ in size, but curved or skewed elements get wrong weights.
- The replay in `sd_report.py` needs every design and sensitivity file
  from iteration 0 on, since the per-node move limits depend on the whole
  history. It stops at the first missing file.
- The explicit-term comparison in `fluid_sensitivity.py` uses the stored
  velocity at the end of each forward run, not the time average that an
  unsteady objective integrates, and it leaves out the filter.
- `sd_report.py` takes the solver parameters from the case file, with the
  defaults of the steepest-descent solver where an option is not set.
