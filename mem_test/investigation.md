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

- `a7fdcd7f35f` (#2424, 2026-08-28), the mixed boundary-condition refactor,
  which purged `only_facets` so `bc_finalize` now always builds both `msk`
  and `facet_node_msk`/`facet` and device-maps both. 134 files, 34 new
  `allocate` and 9 new `device_map` lines. Test `67ddc2258c2`, just before.
- Recent `coef.f90` history: `ef249cdce43` (#2727), `07d5f8c6f17` (#2720),
  `7a1d960771a` (#2696). #2727 is described as a reducer, but it changed the
  type's layout and is worth confirming rather than assuming.
- Neko-TOP's own `48cdd402` (#490), `c6db059d` (#502), `a6ce985c` (#494).

**Recover a last-known-good point** if possible: which commits or what date
the last successful `unsteady_200` used. Old job directories under
`results/` or `logs/` may hold it, since Neko prints a job-info banner. This
bounds the bisect and is worth more than several runs.

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
- **_next_** — Fix measurement comparability, then bisect on per-rank peak.
