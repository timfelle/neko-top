# Investigating the increase in Neko-TOP memory consumption

> **This document lives at `mem_test/investigation.md`**, alongside the
> captured logs in `mem_test/pass/` and `mem_test/fail/`, on branch
> `fix/mem_regression`. It is the running record of this investigation:
> update it whenever a result comes in, so the state survives a change of
> machine. `mem_test.sh` clears only `mem_test/pass/` and `mem_test/fail/`,
> so this file is safe there.
>
> Keep the **Progress log** at the foot of the document current. Each entry:
> date, what was run or changed, the number it produced, and what it ruled
> in or out. A one-line entry that records a negative result is worth as
> much as one that records a positive.

## Status at a glance

**Established.** The excess consumption is Neko-TOP's, not Neko's: the same
case passes against pure Neko at every size. The failing runs die building the
adjoint's Gauss-space coefficients. Memory instrumentation now exists and is
validated, and gives per-step attribution.

**Measured.** The Gauss over-integration stack is about a third of loadup on a
case that has dealiasing switched off, and it is built unconditionally. That
is real waste, but `git log -S` shows it is longstanding, so it is not the
regression itself.

**Open.** Which change increased consumption. Bisect tooling is written and the
known-good anchor pair builds, but the anchor measurement is blocked on
case-file schema drift. Resolving that is the next step and it decides
everything else.

**Not yet done.** No cluster run with the probes. The per-rank component budget
on real problem sizes is still missing, and the historical baseline from the
May benchmarks has not been recovered.

## Context

Memory consumption has increased significantly. The evidence that this is a
code regression is the reference cases in `examples/unsteady_mixer/`:
`steady_200*` and `unsteady_200*` are known to have fitted on LUMI-G and no
longer do. The `mem_test` example was created to debug the consumption;
measurements and logs live on branch `fix/mem_regression`, now with full
output under `mem_test/pass/` and `mem_test/fail/`.

Two questions, in order:

1. **Where does the memory go?** The logs now answer much of this.
2. **Which change increased it?** Still open, and needs a memory bisect.

## Where the failing run dies

`mem_test/fail/64x32x32/output.log` localises it precisely. The tail, after
the forward case and its simulation components are complete:

```
 --------Gather-Scatter--------
 Avg. internal:      1095680      Avg. external:   129024
 Tuned comm   :   Device MPI

 --------Gather-Scatter--------
 Avg. internal:      3557376      Avg. external:   358400
 Tuned comm   :   Device MPI

 ---------Coefficients---------
 Metric condition :  4.00000E+00
ERROR: An error occurred during execution.
```

Compare the passing `128x16x16` log at the same point, lines 207-237: the
same two gather-scatters, then **two** `Coefficients` sections. The failing
run prints one and dies.

That sequence is `adjoint_fluid_scheme_init_base` in
`sources/adjoint/adjoint_fluid_scheme_incompressible.f90:185-189`:

```fortran
call this%gs_Xh%init(this%dm_Xh)         ! internal 1,095,680
call this%gs_Xh_GL%init(this%dm_Xh_GL)   ! internal 3,557,376
call this%c_Xh%init(this%gs_Xh)          ! first Coefficients
call this%c_Xh_GL%init(this%gs_Xh_GL)    ! dies here
```

**The run dies building the adjoint's Gauss-space coefficients.** The ratio
between the two gather-scatters is 3.25 here and 3.30 in the passing run,
consistent with the Gauss space carrying far more points per element than
the GLL space.

Accounting from the same log: `MaxRSS` 5.81 G, `AveRSS` 5.02 G over 8 tasks,
`ReqMem` 43008M, `State=OUT_OF_MEMORY`. Note the log banner also shows
`Job Memory:` empty, so no memory is being requested explicitly.

## The Gauss over-integration stack

This is the dominant consumer and the site of failure, so it deserves
precise description.

`adjoint_fluid_scheme_incompressible.f90:170-194` builds a complete Gauss
over-integration stack **unconditionally**:

```fortran
! over intergration order (hard coded now, should be optional)
lxd = (3 * (lx + 1)) / 2
...
call this%Xh_GL%init(GL, lxd, lxd, lxd)
call this%dm_Xh_GL%init(msh, this%Xh_GL)
call this%gs_Xh_GL%init(this%dm_Xh_GL)
call this%c_Xh_GL%init(this%gs_Xh_GL)
call this%GLL_to_GL%init(this%Xh_GL, this%Xh)
call this%scratch_GL%init(5, 2, this%dm_Xh_GL)
```

There is no `dealias` guard, and the comment concedes the order is "hard
coded now, should be optional". **The `mem_test` case sets
`numerics.dealias: false`.** At order 5, `lx` is 6 and `lxd` is 10, so the
Gauss space carries 1,000 points per element against 216, a factor of 4.6.

Pure Neko never does this. Its dealiased advection at
`external/neko/src/fluid/bcknd/advection/adv_oifs.f90:160` builds a bare
`coef_GL` with no dofmap and no gather-scatter. The `dm_Xh_GL` and
`gs_Xh_GL` pair is unique to Neko-TOP.

**It is not the regression, though.** `git log -S "Xh_GL"` traces it back
through `dd9630a5` "Feature/adjoint (#12)" and `1dcc8146` "added
overintegration to u u_adj", so it is longstanding. It is why the case is
large, not why it grew.

### A second, smaller finding at the same site

`c_Xh_GL%init(this%gs_Xh_GL)` is called with no scope argument.
`external/neko/src/sem/coef.f90:174` defaults `scope` to `COEF_FULL`, and
the note at line 804 records that under `COEF_OPERATOR` the facet area and
normals are not allocated at all, with more released at the end of init.

So the Gauss-space coef is being built in full, including facet area and
normal arrays that nothing reads on an over-integration space. PHMG already
does this correctly for its coarse levels at `phmg.f90:249-251`. `COEF_FULL`
versus `COEF_OPERATOR` arrived with `ef249cdce43` (#2727), which Neko-TOP
has not adopted. This is a missed optimization rather than a regression, but
it applies exactly where the run dies.

## Fixing the measurement before bisecting

The accounting so far is not comparable run to run, and that must be fixed
or the bisect will be misleading.

**Runs stop at different points.** The passing cases ran their full wall
clock and entered the time loop, so their peaks include solver working
memory; the failing case died during setup. One pair measures loadup plus
stepping, the other part of loadup. Add a switch that exits cleanly after
setup, so every case yields a comparable loadup peak.

**Short runs report meaningless peaks.** `small` reports `MaxRSS` of 4 MiB
over a 23-second step, roughly a process at startup, because SLURM's default
gather interval of about 30 seconds sampled it once at best. It exited on
the job time limit. Set `#SBATCH --acctg-freq=task=1`, and raise the
two-minute wall clock where runs are cut off before setup finishes.

**`small` is not a control.** It runs 1 rank where the others run 8, and its
`ReqMem` is `65536M` against `43008M`. Both the rank count and the per-rank
budget differ, so nothing should be inferred by setting it beside the 8-rank
ladder.

**Add per-rank high-water instrumentation.** Read `VmHWM` and `VmRSS` from
`/proc/self/status`, reduce across ranks to max, min and mean, and report at
named points. `VmHWM` is a kernel high-water mark rather than a sample, so
unlike `sacct` it cannot miss a spike. Model the interface on Neko's
`runtime_statistics.f90`. Neither codebase has any memory instrumentation
today.

Place probes around the eight loadup steps that `sources/drivers/topopt.f90`
makes explicit: `neko_init`, `neko_top_register_types`, `json_read_file`,
`nekotop_continuation%init`, `sim%init`, `design_factory`, `prob%init`,
`optimizer_factory`. Subdivide `sim%init` into the forward and adjoint
cases, and the adjoint into its GLL and Gauss halves, since that is where
the logs say the memory is.

## Finding the regression

**Bisect on measured memory, never on pass/fail.** Every experiment on
`fix/mem_regression` so far has been binary, which discards nearly all the
information each run produced. `128x16x16` passes at a measured 4.56 GB per
rank, so every build yields a number, and a commit adding a few hundred
megabytes is obvious in that signal and invisible in a binary outcome.

**Use the reference cases as the test.**
`examples/unsteady_mixer/steady_200_short_small.case` and
`unsteady_200_short_small.case` run `mixer_64x16x16.nmsh`, 16,384 elements,
on one node at 8 ranks. They are cheap enough to iterate on and are the same
family as the cases known to have fitted. Full-size `steady_200` and
`unsteady_200` on `mixer_256x64x64.nmsh` are the acceptance test.

**Bisect both repositories.** Neko-TOP's history is short. Neko's matters
too even though pure Neko passes: Neko-TOP builds a forward and a full
adjoint scheme, and the adjoint carries both a GLL and a Gauss space each
with its own dofmap, gather-scatter and coef. A change adding X to one
scheme can appear as several times X here, and the Gauss multiplier of 4.6
amplifies anything that scales with points per element. **Pure Neko passing
does not exonerate Neko.**

Given the death site, changes to `coef_t` and to boundary conditions deserve
first look:

**Neko candidates inside the range**, newest first. Note that several are
described as reducers; they changed type layouts and are worth confirming
rather than assuming.

| Commit | Date | Subject |
| --- | --- | --- |
| `8a38b9b5dbf` | 2026-09-04 | Refactor GS tuner with device backends (#2757) |
| `a7fdcd7f35f` | 2026-08-28 | Mixed BCs on non-axis-aligned meshes (#2424) |
| `66c71178d51` | 2026-08-31 | Mesh representation refactor, "~80% less" (#2744) |
| `ef249cdce43` | 2026-08-25 | Coef fixes, "reduced footprint" (#2727) |
| `2596d0d646a` | 2026-08-12 | phmg/tamg improvements (#2702) |
| `10689388af1` | 2026-07-20 | Zero-copy unified memory for MI300A (#2666) |
| `fec678e3d6a` | 2026-07-06 | Fused multi-component gather-scatter (#2615) |

`a7fdcd7f35f` is the strongest prior: it purged `only_facets`, so
`bc_finalize` now always builds both `msk` and `facet_node_msk`/`facet` and
device-maps both, where it previously built one or the other. 134 files, 34
new `allocate` and 9 new `device_map` lines. Test `67ddc2258c2`, just before
it. `fec678e3d6a` introduced `GS_VEC_NC` buffers at three times the halo,
eagerly allocated in every backend's init; that was made lazy by
`d9acf9f2cbb` (#2783) which is at HEAD, so it should no longer bite, but it
was live between July and September.

**Neko-TOP candidates inside the range**, touching the adjoint, simulation
or design paths:

| Commit | Date | Subject |
| --- | --- | --- |
| `48cdd402` | 2026-09-10 | Introduce state recovery type (#490) |
| `bb2175a0` | 2026-09-08 | Align with neko PR #2424 (#503) |
| `37020fd1` | 2026-09-07 | Neko: Axhelm update (#499) |
| `f14bed1a` | 2026-08-18 | Update preconditioner references to allocator (#479) |
| `240763ef` | 2026-06-02 | Add missing frees (#442) |

`bb2175a0` is the Neko-TOP half of the boundary-condition refactor, so it
and `a7fdcd7f35f` should be considered together rather than bisected
independently.

**Last-known-good: 2026-05-26.** Benchmarking data records equivalent-sized
runs performed on that date. This is the boundary to bisect from.

Anchors and ranges:

| Repo | Anchor | Date | Commits to HEAD |
| --- | --- | --- | --- |
| Neko | `f1ca7b11d64` "Rework operators and field handling (#2547)" | 2026-05-26 | 200 |
| Neko-TOP | `99033428` "Updates from LUMI (#435)" | 2026-05-20 | 77 |

Roughly eight bisection steps for Neko, seven for Neko-TOP. Pin one
repository while bisecting the other.

**An earlier, weaker bound is superseded and should not be used.**
`results/unsteady_mixer/steady_200_short_small/output.log` shows the
reference case completing 10 optimization iterations on 2026-07-10, and
`39f63b5de09` (2026-07-09) is `git merge-base v1.1.0 HEAD`. Those agree with
each other, but that run was the `_short_small` variant on 16,384 elements
executed **locally**, judging by the output path and the OpenMPI
`[1,0]<stdout>` prefix. It says nothing about full-scale LUMI capacity, so
2026-05-26 is the bound that matters. Note this widens the search: the
suspects clustered in late August are inside the range, but so is everything
back to May.

**The capacity reference worth recovering.**
`bench/lumi/experiments/single_node_capacity.csv` defines a single-node
sweep at `n_memory=100` running up to `128x32x32`, which is 131,072 elements
on one node at 8 ranks, so **16,384 elements per rank**. That is double the
8,192 per rank that now fails, and with 100 in-RAM checkpoints on top. If
that sweep completed, capacity has dropped by well over a factor of two.

The results are not in the local archive, which holds only 2024-era
benchmark output under `results/bm` and `results/hpc`. They are presumably
on LUMI. Recovering how far up that sweep actually got, and its recorded
memory figures, would give a historical baseline to compare current numbers
against, which is the one thing this investigation still lacks.

**Much of this runs locally.** This machine has MPI, 16 cores, 31 GB and a
built Neko. A few hundred megabytes of growth per scheme is visible at small
scale. The local build is `--enable-real=sp` with CUDA while the cluster is
HIP and likely double precision, so compare ratios rather than absolutes, or
reconfigure to match.

## Already cleared

- **MMA.** `mma.f90` keeps `n` local, computes `n_global` at line 447 and
  uses it only for the `epsimin` scalar at 456 and logging at 492. All
  arrays are local, including `dfdx` at `(m, n)`.
  `design_brinkman.f90:416` sizes the design from the local dofmap.
- **Scratch registry.** 85 requests against 51 relinquishes looks
  unbalanced, but `relinquish` takes an array of indices, as at
  `mma_optimizer.f90:279` and `385`. No leak.
- **Parallel HDF5.** No host buffer is sized by `n_global`; `ddim` feeds a
  dataspace handle, not an allocation. Handles balance.
- **Native Neko internals, on arithmetic.** PHMG and TAMG peak around
  0.21 GB, mesh hash tables are tens of MB, and the parallel-only inventory
  of Neko's setup path totals about 100 MB.
- **Environment knobs**, from the `fix/mem_regression` experiments:
  gather-scatter comm backend and strategy, MPI thread level, OpenMP
  threading. None changed the outcome, which the death site now explains:
  the failure is in a coefficient allocation, not in communication.

One latent defect found in passing, unrelated to consumption:
`IO/hdf5/design_hdf5_io.f90:214` and `mma_hdf5_io.f90:281,288,295,302,309,316`
pass `ddim`, the global size, as the `dims` argument of `h5dwrite_f` while
the buffer is only `this%n` long. It should be `dcount`. Harmless under the
F2003 interface, but misleading.

## Order of work

1. Add the exit-after-setup switch, the per-rank `VmHWM` probes, and
   `--acctg-freq=task=1`.
2. Re-run the `mem_test` ladder for comparable loadup peaks, replacing the
   current mixed-phase numbers.
3. Produce a component budget for `128x16x16`, including the Neko-TOP versus
   pure Neko split and the adjoint's GLL versus Gauss split. The logs
   predict the Gauss half dominates; confirm it with numbers.
4. Recover a last-known-good commit or date for `unsteady_200`.
5. Bisect on per-rank peak using `steady_200_short_small`, locally where
   possible, starting with `67ddc2258c2` and the `coef.f90` commits.
6. Independently of the bisect, reduce the footprint at the death site: gate
   the Gauss stack on the dealias setting, make `lxd` configurable as the
   code comment asks, and pass `COEF_OPERATOR` where the full coef is not
   needed.
7. Confirm against full-size `steady_200` and `unsteady_200`.

## Verification

1. Every case reports a loadup peak measured at the same point.
2. The component budget sums to approximately the process high-water mark.
   A shortfall is itself a finding: it would mean the memory is outside the
   instrumented paths.
3. A commit is identified at which per-rank peak steps up, with before and
   after figures recorded.
4. That step accounts for the difference between the reference cases fitting
   and not fitting.
5. With the Gauss stack gated off for a `dealias: false` case, per-rank peak
   falls measurably, and results are unchanged for cases that genuinely
   dealias.
6. `steady_200` and `unsteady_200` run again at full size, with the peak
   recorded so the next regression is caught by comparison rather than by a
   failed job.

## First probe measurements, local

A 256-element mixer case, the same `small.case` configuration with only the
mesh swapped, run locally in double precision with `NEKOTOP_SETUP_ONLY`.
Deltas are megabytes of resident memory attributable to each step.

| Step | 1 rank | 4 ranks |
| --- | --- | --- |
| forward case, up to `adj before spaces` | 66.8 | 28.9 |
| `adj dm_Xh` | 1.9 | 0.5 |
| **`adj dm_Xh_GL`** | **8.8** | **2.2** |
| `adj gs_Xh` | 2.5 | 2.8 |
| **`adj gs_Xh_GL`** | **4.7** | **4.1** |
| `adj c_Xh` | 10.2 | 1.3 |
| **`adj c_Xh_GL`** | **65.2** | **16.5** |
| `adj scratch_GL` | 0.0 | 0.0 |
| rest of `simulation_init` | 32.8 | 10.4 |
| `design_factory` | 24.9 | 21.4 |
| `problem_init` | 3.4 | 0.9 |
| `optimizer_factory` | 8.1 | 2.1 |
| **total loadup** | **229.7** | **87.9** |

**The Gauss over-integration stack is 78.7 MB of the 229.7 MB single-rank
loadup, about a third of it, on a case that sets `numerics.dealias: false`.**

The ratio is worse than the points-per-element ratio predicts. The Gauss
coefficient costs 65.2 MB against 10.2 MB for the GLL one, a factor of 6.4
where the space itself is only 4.6 times denser. The extra is
`COEF_FULL`: the Gauss coef is built with facet areas and normals that
nothing reads on an over-integration space. `phmg.f90:249-251` already
passes `COEF_OPERATOR` for exactly this reason on its coarse levels.

`adj scratch_GL` costs nothing at init, so the `5, 2` scratch registry is
lazy and is not a target.

Caveat: this is 256 elements on a workstation, not 8,192 elements per rank
on LUMI. The proportions should hold since every term scales with local
element count, but confirm on the cluster before acting.

**Running locally, note the backend.** The local build reports
`Bcknd type: Accelerator (CUDA)` and `Real type : double precision`, so it
matches the cluster's device-plus-double profile, which is what makes these
numbers meaningful. But there is only one GPU. Multiple local ranks contend
for it, which has caused significant bottlenecks before. For memory figures
that contention is tolerable, and the four-rank column above was collected
that way. **Prefer single rank for anything local**, including the bisect:
it avoids contention entirely, runs faster, and still captures the per-rank
allocations that matter, since every suspect term scales with local element
count rather than rank count.

## Bisecting: tooling, and where it stands

### The scripts

Two committed scripts, both used and working:

- **`mem_test/bisect/build_pair.sh <neko-commit> <nekotop-commit> <label>`**
  builds a commit pair in isolated git worktrees under `/tmp/neko-top-bisect`,
  override with `BISECT_WORKDIR`. It leaves the working checkout untouched.
- **`mem_test/bisect/measure.sh <binary> <case>`** runs one build on one case,
  single rank, and prints peak resident memory from the kernel via
  `/usr/bin/time`.
- **`mem_test/bisect/bisect.case`** is the measured case: `small.case` with a
  256-element mesh, `end_time` cut to about three steps and
  `max_iterations` 1, so a run takes seconds. Run from the repository root so
  the relative mesh path resolves.

**Both repositories must move together.** Neko-TOP periodically realigns with
Neko API changes, the "Align with neko PR #NNNN" commits, so an old Neko
against current Neko-TOP generally will not compile. Bisect the pair by date.

### Build gotchas, all of them hit and solved

These cost several iterations; `build_pair.sh` encodes all of them.

- The vendored dependencies are not on the default pkg-config path. Export
  `PKG_CONFIG_PATH` for `external/json-fortran/lib/pkgconfig` and
  `external/hdf5/lib/pkgconfig`, as `scripts/dependencies.sh` does.
- Neko's own executable fails to link with `undefined reference to
  __cxa_guard_acquire`. The CUDA objects pull in C++ guard symbols and older
  configurations do not link the C++ runtime. Pass `LIBS=-lstdc++` to `make`.
  Note the library itself builds fine before this point, so if you only need
  `libneko.a` you can ignore it.
- Neko-TOP hits the same thing at its link. Use
  `-DCMAKE_Fortran_STANDARD_LIBRARIES=-lstdc++`, **not**
  `-DCMAKE_EXE_LINKER_FLAGS`. The latter is placed before the objects, where
  `-lstdc++` does nothing; `STANDARD_LIBRARIES` is appended after them.
- The `mem_test` example postdates the older commits, so it is copied into the
  old worktree and registered in `examples/CMakeLists.txt`. That keeps the
  measured case and its user code identical at every point in history.
- Build in **double precision**. Neko-TOP does not compile in a
  single-precision build, and the cluster is double precision anyway.

### Status: the anchor pair builds, but the case does not run on it

| Point | Neko | Neko-TOP | Builds | Peak on `bisect.case` |
| --- | --- | --- | --- | --- |
| HEAD | `4a6a208aab2` | working tree | yes | **642 to 648 MB** |
| anchor | `f1ca7b11d64` | `99033428` | yes | **not yet obtained** |

**Know the noise floor before reading a bisect.** Three HEAD runs gave 641.9,
645.7 and 647.6 MB, a spread of about one percent. Anything smaller than that
is not a signal. If the regression turns out to be a few percent, take the
median of three runs per commit rather than one, or move to a larger mesh
where the variable part dominates the fixed overhead. Note the fixed
overhead is substantial here: on a 256-element case the baseline at
`neko_init` is already about 356 MB, so only a third of this number moves
with the mesh.

The anchor pair compiles and links. The measurement is blocked on case-file
schema drift, which is the classic bisect hazard: the case evolved with the
code.

The anchor run dies after printing `------Reading objectives------` and the
three objective names, with:

```
ERROR STOP
#3  __utils_MOD_neko_error_msg at common/utils.f90:349
#4  __json_utils_MOD_json_get_or_default_double
```

So a `double` key the current objectives block supplies, or fails to supply,
is not what the May code expects. **This is the next thing to resolve.**
Options, cheapest first:

1. Diff the objective handling between `99033428` and HEAD in
   `sources/problem/objectives/` and find the key whose name or default
   changed. Then write a `bisect.case` that satisfies both, since only the
   common subset matters for a memory comparison.
2. Failing that, drop to a case with a single objective, or none, accepting
   that the comparison then covers less of the stack. The Gauss stack, coef
   and gather-scatter costs all sit in `simulation_init`, well before
   objectives, so a reduced case still measures the parts that matter.
3. Note that `examples/unsteady_mixer/steady_200_short_small.case` **did not
   exist** at the anchor, so it cannot serve as the common case without the
   same treatment.

### Once the anchor number exists

If the anchor is materially below 645.7 MB, the regression is real and inside
the range, and a standard bisect over the pair finds it in about seven or
eight steps. Each step is one `build_pair.sh` plus one `measure.sh`, a few
minutes. If the anchor is close to 645.7 MB, the growth is not in this range
and the search has to widen or move.

## Reference measurements

Baseline to compare everything against. Bytes, from the `sacct` capture
appended to each log by `mem_test.sh`. Update as better numbers arrive.

| Case | Ranks | Elements/rank | MaxRSS | AveRSS | State | Phase reached |
| --- | --- | --- | --- | --- | --- | --- |
| `small` | 1 | 8,192 | 4 MiB (invalid) | — | FAILED, time limit | sampling missed it |
| `64x16x16` | 8 | 2,048 | 2.74 G | 2.66 G | TIMEOUT | into time loop |
| `128x16x16` | 8 | 4,096 | 4.56 G | 4.36 G | TIMEOUT | into time loop |
| `64x32x32` | 8 | 8,192 | 5.81 G | 5.02 G | OUT_OF_MEMORY | adjoint Gauss coef |
| `full` | 128 | 8,192 | 5.42 G | 4.73 G | OOM | setup |

Gather-scatter sizes from the logs, useful as a sanity check that a build
still constructs the same objects:

| Case | Adjoint GLL internal | Adjoint Gauss internal | Ratio |
| --- | --- | --- | --- |
| `128x16x16` | 476,160 | 1,570,816 | 3.30 |
| `64x32x32` | 1,095,680 | 3,557,376 | 3.25 |

## Resuming on another machine

Everything needed is committed. The worktrees and builds are not: they live
under `/tmp` and will be gone. Recreate them with `build_pair.sh`, which is
idempotent and skips work already done.

1. Build and check the working tree, in **double precision**. `prepare.env`
   should carry `--enable-real=dp`; a single-precision build will not compile
   Neko-TOP.
2. Sanity-check the probes: `ninja -C build mem_test`, then from the
   repository root
   `./mem_test/bisect/measure.sh examples/mem_test/neko mem_test/bisect/bisect.case`.
   Expect a peak near 645 MB on a comparable machine. The absolute number is
   machine-dependent; only comparisons on the *same* machine mean anything.
3. To see the per-step trace instead, run the binary directly with
   `NEKOTOP_SETUP_ONLY=1` and grep for `[mem]`.
4. To resume the bisect:
   `./mem_test/bisect/build_pair.sh f1ca7b11d64 99033428 anchor`, then measure
   `/tmp/neko-top-bisect/anchor/nt/examples/mem_test/neko`.

A caution worth repeating: the local build is a device build with one GPU.
Several ranks contend for it and that has caused real bottlenecks. Keep local
runs single rank, which the measure script does.

## The instrumentation

`sources/neko_ext/memory_probe.f90` provides `memory_probe_report(label)`.
It reads `VmRSS` and `VmHWM` from `/proc/self/status`, reduces across ranks,
and emits one greppable line:

```
[mem] <label>    rss <max>/<avg>  hwm <max>  d <change> MB
```

`VmHWM` is a kernel high-water mark rather than a sample, so it cannot miss
a short peak the way the batch accounting already has. Both max and average
are reported because a max far above the average means an uneven partition,
which is a different problem from uniform growth.

Probe points, in execution order:

| Label | What it follows |
| --- | --- |
| `neko_init` | Neko initialisation |
| `register_types` | `neko_top_register_types` |
| `read_case` | case file read and design subdict |
| `continuation_init` | continuation scheduler |
| `simulation_init` | forward case **and** adjoint case |
| `design_factory` | design, mapping cascade, filter |
| `problem_init` | objectives and constraints |
| `optimizer_factory` | MMA |

Inside the adjoint scheme, the death site is probed object by object:
`adj before spaces`, `adj dm_Xh`, `adj dm_Xh_GL`, `adj gs_Xh`,
`adj gs_Xh_GL`, `adj c_Xh`, `adj c_Xh_GL`, `adj scratch_GL`. The
`_GL` entries are the Gauss-space half, which is what the logs point at.

**`NEKOTOP_SETUP_ONLY`** stops the run after `optimizer_factory` instead of
optimizing, so every case reports a peak at the same point. Without it a case
that survives runs on into the time loop and its peak picks up solver working
memory, while a case that dies during setup reports only part of the story.
Setting it to `0`, `false`, `no` or `off` disables it; anything else enables
it. It is an environment variable rather than a case setting because the case
files are held fixed for this comparison. The `mem_test` job scripts set it;
comment that line out for a full run. The shared helper is
`setup_only_requested()` in `memory_probe.f90`.

Note it is deliberately **not** used by `mem_test/bisect/measure.sh`, since
older builds predate it and a comparison across history has to run the same
way at every point. The bisect case ends quickly instead.

## Progress log

Newest last. Keep entries to a line or two.

- **2026-09-14** — `mem_test` created. Ladder run with the Neko-TOP driver:
  `small`, `64x16x16`, `128x16x16` pass; `64x32x32` and `full` OOM.
- **2026-09-14** — Environment sweep, all still failing: gather-scatter comm
  and strategy pinned, then unset; `NEKO_MPI_THREAD_LEVEL=single`;
  `OMP_NUM_THREADS=1`. Communication and threading ruled out.
- **2026-09-14** — First driver-swap test appeared to exonerate Neko-TOP,
  but CMake had not actually switched drivers. Result void.
- **2026-09-14** — CMake corrected. **Pure Neko passes every size**, so the
  excess consumption is Neko-TOP's.
- **2026-09-14** — `sacct` capture added to every run, and logs committed
  under `mem_test/pass/` and `mem_test/fail/`. First real numbers, in the
  table above.
- **2026-09-14** — Death site localised from the failing log: the run dies
  building the adjoint's Gauss-space coefficients, after the two adjoint
  gather-scatters. Static reading confirms the Gauss stack is built
  unconditionally despite `numerics.dealias: false`, and `git log -S` shows
  it is longstanding, so it is the dominant consumer but not the regression.
- **2026-09-14** — Searched the archive for a last-known-good point. Found
  a local run of the `_short_small` reference variant dated 2026-07-10, but
  it proves nothing about full-scale LUMI capacity.
- **2026-09-14** — **Last-known-good set to 2026-05-26** from benchmarking
  data recording equivalent-sized runs on that date. Bisect anchors:
  Neko `f1ca7b11d64` with 200 commits to HEAD, Neko-TOP `99033428` with 77.
  This supersedes the weaker 2026-07-09 bound and widens the search back
  past the late-August suspects.
- **2026-09-14** — Instrumentation landed. `sources/neko_ext/memory_probe.f90`
  reports `VmRSS` and `VmHWM` per rank, reduced to max and average, with the
  change since the previous probe. Probes placed at the eight driver steps
  in `sources/drivers/topopt.f90` and object by object across the adjoint's
  GLL and Gauss halves in `adjoint_fluid_scheme_incompressible.f90`.
  `NEKOTOP_SETUP_ONLY` stops the run after setup so every case reports a
  peak at the same point. Job scripts now set `--acctg-freq=task=1` and a
  ten-minute wall clock.
- **2026-09-14** — Incidental build fix. `adjoint_compute_cfl` in
  `adjoint_fluid_scheme_incompressible.f90` passed an `rp` timestep to
  Neko's `cfl`, which takes and returns `dp` regardless of working
  precision. In a double-precision build the two coincide and it compiles;
  in a single-precision build no specific procedure matches and the module
  fails to build. Verified pre-existing by building the file with the probe
  changes stashed. Fixed with explicit conversions, which are no-ops in a
  `dp` build. This says the cluster builds in double precision, since
  Neko-TOP could not compile there otherwise.
- **2026-09-14** — Local builds are blocked, and it is not this
  investigation's bug. Neko-TOP does not compile in a single-precision
  build: Neko keeps time quantities (`time%t`, `time%dt`, `chkp%dtlag`,
  `chkp%tlag`) in `dp` while Neko-TOP declares the receiving variables at
  working precision, so `-Werror=conversion` rejects about fourteen sites
  across `checkpoint_linear.f90`, `steady_simcomp.f90`,
  `set_optimization_ic.f90` and `adjoint_scalar_pnpn.f90`. All pre-existing.
  The local `prepare.env` sets `--enable-real=sp`; the cluster is double
  precision. **To do local work, rebuild locally in double precision**,
  which the plan wants anyway so that local and cluster numbers compare
  directly. Fixing single-precision support is a separate piece of work and
  is not required here.
- **2026-09-14** — Instrumentation validated end to end locally after the
  double-precision rebuild. Compiles and links in all three drivers, runs
  clean at 1 and 4 ranks with no deadlock in the collective reduction, and
  the setup-only gate works. First numbers in the table above: the Gauss
  over-integration stack is about a third of loadup on a case with
  dealiasing off, and the Gauss coefficient alone is 6.4 times the GLL one.
- **2026-09-14** — Instrumentation adversarially reviewed across MPI, Fortran
  and behavioural dimensions, with each finding sent to an independent
  refuter. Three findings were raised and all three were refuted on
  verification: the label attribution of the forward case, the meaning of the
  MPI-reduced delta, and a 32-bit overflow in `rss_sum` that would need about
  2 TiB of aggregate resident memory to bite. Three further verifications did
  not complete, having hit a session limit, so treat the review as thorough
  but not exhaustive. Acting on one of the unverified ones anyway:
  `NEKOTOP_SETUP_ONLY=0` used to *enable* the gate, because any non-empty
  value counted. Now `0`, `false`, `no` and `off` disable it.
- **2026-09-14** — Bisect tooling written, committed under `mem_test/bisect/`,
  and exercised. The known-good anchor pair builds. HEAD measures 645.7 MB on
  the bisect case. The anchor measurement is blocked on case-file schema
  drift; details and three ways forward are in the bisect section above.
- **_next_** — (1) Resolve the anchor case-schema incompatibility and get the
  anchor number, which decides whether the regression is in the range.
  (2) Run the ladder on LUMI with the probes for the per-rank component
  budget. (3) Recover the May benchmark results from LUMI for a historical
  baseline, since `single_node_capacity.csv` swept to 16,384 elements per
  rank at `n_memory=100`, double what fails now.
