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

> **This investigation is OPEN.** It closes on one criterion: a full-scale
> `steady_200`/`unsteady_200` (or the `mem_test` `full` case) documented
> completing on LUMI, with its `sacct` row (`ReqMem`, `MaxRSS`, `State`) and
> per-rank peak recorded in this document beside the May benchmark's own
> figures. That has not happened yet. See "The investigation's closing
> criterion", immediately below, before reading anything else here as a
> settled conclusion.

**Bottom line, for a reader arriving cold.** What is established by
measurement, across the whole host-side range now searched — April 2026 to
September 2026, including the ALE merge specifically alleged to be the
cause: **nothing increased per-element memory cost; it fell by about
4.8%**, across a four-point series (pre-ALE, post-ALE, the May anchor, the
September top endpoint) that is monotonically decreasing throughout. The
CPU-vs-CUDA device control agrees: both backends show the same endpoint
lower than the anchor, by a similar margin (CPU **-87.8 MB**, CUDA
**-59.3 MB**). Separately, `sacct` shows the cluster now grants these jobs
**5.25 GiB/rank** against **60 GiB/rank** in May — an 11.4x drop, from
`#SBATCH` blocks that are textually identical between the two jobs.

Put together, these measurements support a **leading hypothesis**, not yet a
demonstrated fact: that **the OOMs are an allocation change, not a code
change** — that it is the granted budget that shrank, not the code's memory
need that grew. That inference is strong: every measurement taken so far is
consistent with it and none contradicts it. But it is not confirmed, because
**nothing in this investigation has yet shown a full-scale LUMI run actually
succeeding since the failures began.** Until that is observed and recorded,
treat "allocation change, not code change" as the working explanation under
test, not as this investigation's conclusion. See "The investigation's
closing criterion", directly below, and "Exhausted, for everything this
container can test", further down, for what has and has not actually been
established.

**The investigation's closing criterion, stated explicitly.** This document
closes only when — and not before — a full-scale run (`steady_200`,
`unsteady_200`, or the `mem_test` `full` case) is documented completing on
LUMI, with its `sacct` row (`ReqMem`, `MaxRSS`, `State`) and its per-rank
peak recorded in this document alongside the May benchmark's own figures, so
the two can be compared directly. The captured logs under `mem_test/pass/`
and `mem_test/fail/` are the established place to add that evidence — the
same pattern already used for every other run recorded here. Nothing below
substitutes for this, however consistent the local measurements are with the
hypothesis: **if the confirmation run still fails, that refutes the leading
hypothesis above and reopens the search for a code-side cause** — see "The
actionable fix" under "The `ReqMem` gap, explained", below, which is the
immediate next action.

**Established.** The excess consumption is Neko-TOP's, not Neko's: the same
case passes against pure Neko at every size. The failing runs die building the
adjoint's Gauss-space coefficients. Memory instrumentation now exists and is
validated, and gives per-step attribution.

**Measured.** The Gauss over-integration stack is about a third of loadup on a
case that has dealiasing switched off, and it is built unconditionally. That
is real waste, but `git log -S` shows it is longstanding, so it is not the
regression itself — and it is worth gating or trimming on its own merits
regardless of how the regression question resolves; see the Progress log's
`_next_` entry.

**Answered, for the searched range — and the answer is no.** The bisect
anchor measurement this investigation was blocked on since it was written now
exists. On `bisect_4096.case` (4,096 elements, 2 ranks, CPU backend, double
precision, three runs each): anchor `f1ca7b11d64`/`99033428` (2026-05-26/
05-20) medians **2067.7 MB**; top endpoint `865225094`/`0cd5a6d`
(2026-09-08) medians **1979.9 MB**. The anchor is **87.8 MB higher**, about
55x the 1.6 MB run-to-run spread. **Per-element host memory cost has
improved by about 4.2% since May, not regressed, for this case at this size
on this backend.** Full result and scope: see "The anchor measurement, and
what it found" under Bisecting, below.

**Also answered: the ALE-specific hypothesis, and it is refuted.** ALE
(`53b425161`, 2026-04-13, which significantly altered `coef_t`) was proposed
as the actual cause, on the reasoning that it landed before both points
above and so would already sit inside both, invisible to that comparison.
Tested directly at the Neko-TOP alignment barrier on each side of the
merge: pre-ALE (`e8900582f`/`6b20dfb`) medians **2079.3 MB**, post-ALE
(`53b425161`/`b334750`) medians **2079.2 MB** — a **0.1 MB** delta against a
0.2-1.7 MB run-to-run spread here, nothing measurable, and the `mem_test`
case never configures ALE, so this is a genuine test of unconditional cost.
Placed with the anchor and top-endpoint numbers, the four-point series
April-to-September is **monotonically decreasing**, total change **-99.4
MB, about -4.8%**. Full result: see "The ALE hypothesis, tested and
refuted" under Bisecting, below.

**Resolved.** The open contradiction this measurement previously could not
explain — the May benchmark completing at 16,384 elements/rank while current
jobs OOM at half that, apparently under the same budget — is closed, and
without invoking a memory regression. `ReqMem` in `sacct` is a **job total**,
not a per-node or per-rank figure, which is provable directly from the
captured logs: the same `43008M` appears as the whole-job `ReqMem` on every
1-node `mem_test` run and as `688128M` ÷ 16 nodes on the 16-node `full` run.
Every `mem_test` job actually receives **42 GiB/node, 5.25 GiB/rank**. The May
job (`sacct` 18855130) received `ReqMem` 7864320M over 16 nodes — **480
GiB/node, 60 GiB/rank**, 11.4x more per rank — from an `#SBATCH` block
identical to the one used now, with memory requested explicitly in neither
case. **The headline finding is no longer "which commit increased memory" but
"memory did not increase; the allocation shrank."** Full arithmetic, the exact
log lines, and what this does and does not establish about *why* the default
changed: see "The `ReqMem` gap, explained" under Bisecting, below.

**Exhausted, for everything this container can test — not the same as this
investigation being closed.** The CPU-vs-CUDA device control is now complete
too, and agrees with the CPU result: CUDA anchor (2 ranks) medians
**2132.8 MB**, CUDA top endpoint medians **2073.5 MB**, a delta of
**-59.3 MB**, against the CPU delta of **-87.8 MB** — both negative and of
similar order, so CUDA shows no growth that the CPU measurement was hiding.
Device-side memory growth is ruled out for the shared and CUDA-specific code
paths measured here; the anchor runs that previously failed to complete turned
out to be a mixed-cubin build defect, not a memory finding — see "The
CPU-vs-CUDA control, completed" under Bisecting, below, for the full result
and the fix. That exhausts every avenue this container can actually test — it
shows the leading hypothesis is contradicted by nothing reachable here, which
is not the same as it being confirmed. Confirmation needs the cluster run in
"The investigation's closing criterion", above. What is left is narrower than
before, and is genuinely out of reach here:

- The **HIP-specific path** — principally Neko `10689388af1` "Zero-copy
  unified memory for MI300A" (#2666) — is confirmed unreachable in any CUDA
  build by source inspection: the new files are `.hip`, the relevant
  `Makefile.am` hunks sit inside `if ENABLE_HIP`, and the `device.F90` changes
  are inside `#ifdef HAVE_HIP` with nothing in the corresponding `#elif
  HAVE_CUDA` branch. This container has no ROCm toolchain. Testable only on
  the production cluster.

- The **`--mem=0` confirmation run** on LUMI — the one action that actually
  closes this investigation, not merely this container's part of it. It
  tests the leading hypothesis directly: that the OOMs follow from a budget
  reduction of 60 to 5.25 GiB/rank, not a code change. A pass confirms it; a
  failure refutes it and reopens the search. See "The actionable fix" under
  "The `ReqMem` gap, explained", above, and "The investigation's closing
  criterion" under "Status at a glance", above.

- A **cluster run with the probes**, for the per-rank component budget at real
  problem sizes, and recovery of the historical `single_node_capacity.csv`
  baseline — both still outstanding and independent of the regression
  question.

- The **Gauss over-integration stack**, worth trimming on its own merits
  regardless of the regression verdict — about a third of loadup on a case
  with dealiasing disabled, at precisely the allocation where the failing runs
  die. See "Measured", above.

## Context

Memory consumption has increased significantly. The evidence that this is a
code regression is the reference cases in `examples/unsteady_mixer/`:
`steady_200*` and `unsteady_200*` are known to have fitted on LUMI-G and no
longer do. The `mem_test` example was created to debug the consumption;
measurements and logs live on branch `fix/mem_regression`, now with full
output under `mem_test/pass/` and `mem_test/fail/`.

Two questions, in order:

1. **Where does the memory go?** The logs now answer much of this.
2. **Which change increased it?** Answered for the CPU/host range the bisect
   has actually searched — nothing did, per "Status at a glance" above.
   Still open for the device path that motivated the investigation.

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
`ReqMem` 43008M. **Correction:** the job's own `sacct` row reads `FAILED`,
exit code `1:0` — `22035605,mem_test/64x32x32,FAILED,1:0,1,,43008M,00:00:33`
— not the Slurm job state `OUT_OF_MEMORY` this line and the reference table
below previously recorded; only the `.1` step carries `OUT_OF_MEMORY` as its
own state (`22035605.1,select_gpu,OUT_OF_MEMORY,0:125,...`). The kernel
`oom_kill` confirming the physical cause is in `error.log`, not `sacct`'s job
row. See "The `ReqMem` gap, explained" under Bisecting, below, for the full
picture. Note the log banner also shows `Job Memory:` empty — that is not
evidence of no memory being granted, only that `SLURM_JOB_MEMORY`
(`scripts/functions.sh:151`) reflects an explicit `--mem`-family flag, which
is genuinely absent from the jobscript; `sacct`'s `ReqMem` field shows Slurm
granted a (default) budget regardless.

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
  gather-scatter comm backend and strategy pinned, then unset (`1ae0c94`,
  `5f0e2e4`), MPI thread level forced to `single` (`dfb5f25`), OpenMP
  threading disabled entirely (`1f1e957`). All four still failed. None
  changed the outcome, which the death site now explains: the failure is in
  a coefficient allocation, not in communication. **This closes the
  environment-knob axis.** The current jobscript's contents are the *end
  state* of this sweep, not configuration drift away from an earlier,
  working jobscript — worth stating plainly, since the difference between
  the two jobscripts looks like a lead and is not.

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
8. **Cluster action, independent of the bisect and not verifiable from this
   container — and the action that actually closes this investigation:** add
   `#SBATCH --mem=0` (the whole node, explicitly) to
   `scripts/jobscripts/LUMI-G/mem_test/full.sh` and its siblings
   (`default.sh`, `small.sh`), and re-run the ladder on LUMI. Record the
   outcome either way: if the OOMs disappear, the `ReqMem`-gap explanation in
   "The `ReqMem` gap, explained" is confirmed; if they do not, that refutes
   the leading hypothesis and reopens the search for a code-side cause. See
   "The investigation's closing criterion" under "Status at a glance" for
   exactly what recording the outcome requires.

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
- **`mem_test/bisect/measure.sh <binary> <case> [ranks]`** runs one build on
  one case (`ranks` defaults to 1; real bisect runs use 2, since at 1 rank
  there are no halos and gather-scatter growth is invisible), gates on
  Neko's own `Normal end.` banner plus a zero exit before trusting a peak —
  a run that dies partway through setup still exits and would otherwise
  report a low, falsely-reassuring peak — and prints that peak alongside the
  gather-scatter structural invariants (`Avg. internal:`/`Avg. external:`
  pairs), so two builds can be shown to have run the same workload rather
  than assumed to. **`/usr/bin/time` does not exist in this container** (no
  package provides it, and there is no root to install one), so where it is
  absent the script falls back to a `getrusage(RUSAGE_CHILDREN)`-based
  measurement — the same kernel peak-RSS accounting `/usr/bin/time -v`
  itself reads, verified equivalent here on a controlled allocation test.
- **`mem_test/bisect/bisect.case`** is the original measured case:
  `small.case` with a 256-element mesh, `end_time` cut to about three steps
  and `max_iterations` 1, so a run takes seconds. Run from the repository
  root so the relative mesh path resolves. **Superseded for the real
  comparison** by `bisect_4096.case` below: at 256 elements the measurement
  only resolves regressions above roughly 190 MB/rank, too coarse for what
  this investigation is looking for.
- **`mem_test/bisect/bisect_4096.case`** is the same case on a 4,096-element
  mesh (`mixer_64x8x8.nmsh`, 2,048 elements/rank at 2 ranks) — the case
  actually used for the anchor result below.

**Both repositories must move together.** Neko-TOP periodically realigns with
Neko API changes, the "Align with neko PR #NNNN" commits, so an old Neko
against current Neko-TOP generally will not compile. Bisect the pair by date.

### Build gotchas, all of them hit and solved

These cost several iterations; `build_pair.sh` encodes all of them.

- The vendored dependencies are not on the default pkg-config path. Export
  `PKG_CONFIG_PATH` for `external/json-fortran/lib/pkgconfig` and
  `external/hdf5/lib/pkgconfig`, as `scripts/dependencies.sh` does.
- Rebuilding without `FORCE_PKGCONF_PYPI=1` set in the environment fails
  silently, not loudly. This container's PyPI `pkgconf` shim returns an empty
  `Cflags` for json-fortran, so `configure` cheerfully reports `checking for
  json-fortran... yes` while the `FCFLAGS` it generates carry no `-I`, and
  the build only dies much later, in `common/json_utils.f90`, with `Cannot
  open module file 'json_module.mod'` — a confusing site to land on given
  `configure` said everything was fine. Set `FORCE_PKGCONF_PYPI=1` before
  configuring.
- Neko's own executable fails to link with `undefined reference to
  __cxa_guard_acquire`. The CUDA objects pull in C++ guard symbols and older
  configurations do not link the C++ runtime. **This bullet previously
  recommended `make LIBS=-lstdc++`, and that is wrong — corrected in
  `c3b8194`.** A `VAR=value` on a `make` command line *overrides* the
  Makefile's own `LIBS` rather than appending to it, so that form silently
  discards every configure-detected library (json-fortran, hdf5, parmetis,
  lapack/blas) and the link fails anyway, just with a different,
  dozens-of-undefined-references error instead of the one it was meant to
  fix. Pass `LIBS=-lstdc++` as a `./configure` argument instead: autoconf's
  own library checks prepend onto whatever `LIBS` already holds, so seeding
  it before configure runs leaves `-lstdc++` at the end of the link line
  without disturbing anything else. Note the library itself builds fine
  before this point, so if you only need `libneko.a` you can ignore it.
- This container also ships a **system HDF5 2.2.0 under `/usr/local` with
  the same SONAME as the vendored 2.0.0** (`libhdf5.so.320`, incompatible
  contents), and exports `LD_LIBRARY_PATH=/usr/local/lib:` globally for
  every process — which outranks a binary's own `DT_RUNPATH` in the
  loader's search order. That breaks HDF5 resolution two ways: at build
  time (the final executable's indirect `NEEDED` entries resolve to the
  wrong copy via the default path) and at run time (a binary that linked
  correctly still *loads* the wrong one), so a measurement taken without
  correcting for this is suspect either way. Tracked as backlog **#46**
  (`$AGENT_WORKSPACE/.claude/plans/known-bugs-backlog.md`); worked around in
  `build_pair.sh`/`measure.sh` only, by putting the vendored HDF5 directory
  first in `LD_LIBRARY_PATH` and exporting `HDF5_ROOT` (Neko-TOP's own
  `find_package(HDF5)` keys off `HDF5_ROOT`, not `HDF5_DIR`) — `c3b8194`.
- Neko-TOP hits the same `__cxa_guard_acquire` problem at its link. Use
  `-DCMAKE_Fortran_STANDARD_LIBRARIES=-lstdc++`, **not**
  `-DCMAKE_EXE_LINKER_FLAGS`. The latter is placed before the objects, where
  `-lstdc++` does nothing; `STANDARD_LIBRARIES` is appended after them.
- **Any Neko-TOP commit older than 2026-05-20 (before `99033428`) fails to
  link**, not compile, with undefined `GOMP_parallel`, `omp_get_thread_num`,
  `GOMP_barrier` — coming out of Neko's own objects, which are compiled with
  `--enable-openmp`. It is not a `neko.pc` problem: the generated `neko.pc`
  is byte-identical across April, May and September builds, carrying
  `-fopenmp` in `Cflags` and no `-lgomp` in `Libs` in every one, and
  pkg-config `Cflags` only ever reach compilation of Neko-TOP's own sources,
  never CMake's link step. The actual cause is that Neko-TOP's own
  `CMakeLists.txt` gained `find_package(OpenMP REQUIRED COMPONENTS Fortran)`
  and the `OpenMP::OpenMP_Fortran` link somewhere between `6b20dfb`
  (2026-04-14) and `99033428` (2026-05-20) — visible directly in the
  generated `build.ninja`: working builds carry `libgomp.so` in
  `LINK_LIBRARIES`, broken ones carry nothing. Fixed the same way as the
  `-lstdc++` case immediately above and for the same reason: append
  `-lgomp` via `CMAKE_Fortran_STANDARD_LIBRARIES` rather than
  `CMAKE_EXE_LINKER_FLAGS`, so it lands after the objects (`280aaa8`). A
  pair that already links libgomp simply names it twice, which is harmless.
  Verified not to disturb the established measurements — see "The ALE
  hypothesis, tested and refuted", below, for the rebuild-and-compare check.
  **Any future attempt to build a Neko-TOP commit older than this CMake
  change will hit this.**
- **A CUDA build of any Neko-TOP commit before `99033428` (2026-05-20) links
  and loads, then dies at the first Neko-TOP kernel launch** with `the
  provided PTX was compiled with an unsupported toolchain` (seen at
  `math_ext.cu:66`). Same class of bug as the `-lgomp` case immediately
  above, and for the same reason: `sources/CMakeLists.txt` only gained
  `if(DEFINED ENV{CUDA_ARCH}) set(CMAKE_CUDA_ARCHITECTURES ...)` after that
  commit, so older checkouts build their own five CUDA translation units
  (`RAMP_mapping.cu`, `SIMP_mapping.cu`, `heaviside_mapping.cu`, `mma.cu`,
  `math_ext.cu`) for CMake/CUDA-13's default architecture while Neko's own
  device code still gets the right one from Neko's `configure` — a mixed
  binary, 57 `sm_86` plus 5 `sm_75` cubins on this machine, that the driver
  cannot JIT. Fixed by passing `-DCMAKE_CUDA_ARCHITECTURES=<arch>` on the
  `cmake` command line, which takes precedence at every commit (`873852c`).
  Verified at the binary level, not by the build succeeding: `cuobjdump
  --list-elf` before/after, 57 `sm_86`/5 `sm_75` to 62 `sm_86`/0 `sm_75`.
  **Any future attempt to build a pre-`99033428` Neko-TOP commit for CUDA
  will hit this.** This unblocked the CPU-vs-CUDA control; see "The
  CPU-vs-CUDA control, completed", below, for the result.
- The `mem_test` example postdates the older commits, so it is copied into the
  old worktree and registered in `examples/CMakeLists.txt`. That keeps the
  measured case and its user code identical at every point in history.
- Build in **double precision**. Neko-TOP does not compile in a
  single-precision build, and the cluster is double precision anyway.

### Status (historical): the anchor pair builds, but the case does not run on it

**Superseded below — kept as the record of how the block was diagnosed.**
Everything in this subsection and the next was true when written; the
schema-drift block it describes was resolved in `0cd5a6d`, and the anchor
number it was waiting on now exists in "The anchor measurement, and what it
found", further down.

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

**Superseded: the noise floor is much better than this on the real
comparison case.** This 256-element estimate was one percent because the
fixed per-rank overhead (~356 MB) dominates a mesh this small. On
`bisect_4096.case` at 2 ranks — the case and rank count actually used for the
result below — the spread across three runs is about **1.6 MB on a ~1980 MB
peak, i.e. 0.08%**, over ten times tighter. The "take the median of three
runs" advice still stands; the one-percent resolution figure above does not.

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

**Resolved, per option 1 above.** `0cd5a6d` traced the actual failing key to
`optimization.solver.max_runtime`, not to the objectives block the stack
trace pointed at (the objectives block was mid-read when the error fired, but
the incompatible key was elsewhere in the file): the anchor code reads
`max_runtime` as a real, HEAD reads it as a string, so no single value
satisfies both. The fix is to drop the key — it plays no part in a memory
comparison and omitting it is safe at both ends. The same commit retired a
dead `phi_ref` objective key in favour of the current `target_concentration`,
dropped an inert `coarse_grid.solver`, and moved `velocity_solver.type` off
`fused_cg`, which is CUDA/HIP-only and aborts on a CPU build — the bisect
moved to the CPU backend in the same pass, both because it is what is
tractable to compare here and because it isolates the question this
investigation can actually answer (see the scope note below).

### Once the anchor number exists

*(Superseded by the result below — kept for the record.)* If the anchor is
materially below 645.7 MB, the regression is real and inside the range, and
a standard bisect over the pair finds it in about seven or eight steps. Each
step is one `build_pair.sh` plus one `measure.sh`, a few minutes. If the
anchor is close to 645.7 MB, the growth is not in this range and the search
has to widen or move.

The anchor came in *above* the top-endpoint figure, on the larger
`bisect_4096.case` rather than this 256-element `bisect.case`, so neither
branch of this plan applies as written; see below for what that means.

### The anchor measurement, and what it found

Both risks the anchor build carried came to nothing. `gfortran` in this
container is 15.2.0 (`GNU Fortran (Ubuntu 15.2.0-16ubuntu1) 15.2.0`,
confirmed in the anchor's own `configure.log`), and it compiled the
2026-05-26 Neko checkout without complaint. The rewritten
`bisect_4096.case` parses and runs to completion at both ends of the range
— the `max_runtime` string-vs-real incompatibility that blocked the
previous attempt is fixed.

**Result.** `bisect_4096.case` (4,096-element mesh, 2 MPI ranks, 2,048
elements/rank), CPU backend, double precision, three runs per point, each
gated on Neko's `Normal end.` banner plus a zero exit (see `measure.sh`'s
completion-marker comment above for why a bare peak is not trusted on its
own):

| Point | Neko | Neko-TOP | Date | Runs (MB) | Median |
| --- | --- | --- | --- | --- | --- |
| anchor | `f1ca7b11d64` | `99033428` | 2026-05-26 / 05-20 | 2067.5 / 2067.7 / 2067.7 | **2067.7** |
| top endpoint | `865225094` | `0cd5a6d` | 2026-09-08 | 1979.6 / 1981.2 / 1979.9 | **1979.9** |

The spread within each point (0.2 MB and 1.6 MB) is far below the 87.8 MB gap
between the medians — roughly 55x the noisier of the two. **The anchor is
higher.** Per-element host memory cost has *improved* by about 4.2% between
May and September on this case; it has not regressed.

The comparison is licensed by the gather-scatter structural invariants
`measure.sh` extracts from the `Avg. internal:`/`Avg. external:` pairs in
the log, identical character-for-character in all nine positions across all
six runs:

```
275456/18432 102144/8192 47552/4608 14336/2048 275456/18432 878592/51200 102144/8192 47552/4608 14336/2048
```

Both builds constructed the same objects on the same mesh, so the peak
difference reflects the code, not a changed workload. The anchor emits no
`[mem]` probe lines, as expected: `memory_probe.f90` does not exist at
`99033428`.

**What this does, and does not, show.** This falsifies the regression
hypothesis *for the range and configuration actually measured* — a
4,096-element mesh at 2 ranks on the CPU backend, in double precision — and
no further than that:

- **The device path is untested.** The cluster failure this investigation
  exists to explain is HIP, at 8,192 elements/rank — double the mesh size
  measured here. Pinned/managed device allocations are not compiled into a
  CPU build, so a device-side regression would be structurally invisible to
  this measurement. The CPU-vs-CUDA control that would test for exactly
  this has **not been run**. **Superseded: it has been run since, and
  agrees** — see "The CPU-vs-CUDA control, completed", below. The
  AMD-specific HIP path itself remains untested regardless.
- **An open contradiction stood here, and is now resolved — see below.**
  *(Superseded paragraph, kept for the trail.)* The May benchmark job
  (`sacct` 18855130, 2026-05-26, Neko 1.99.3) completed using **51.25
  GiB/rank at 16,384 elements/rank** with `n_memory=250`, while current jobs
  OOM at **8,192 elements/rank** — half that mesh size. Both jobscripts
  request identical resources and neither sets `--mem`. Half the elements,
  the same budget, and a *lower* measured per-element cost cannot all be true
  simultaneously. Candidates, none yet checked: a configuration difference
  between the benchmark case and the `mem_test` cases (`n_memory`, active
  fields, polynomial order); device-side memory growth invisible to this CPU
  measurement; or the two jobs not actually receiving the same budget, which
  is where the unexplained `ReqMem` 7864320M vs 43008M gap (the latter is the
  `64x32x32` failure's own figure, in "Where the failing run dies" above)
  still sits. **The last of those three was it** — "the two jobs not
  actually receiving the same budget" is exactly what happened, and the
  51.25 GiB/rank actually used by the May job is unremarkable once its real
  60 GiB/rank budget is known: it used about 85% of what it had, comfortably
  under, not against, the limit. See "The `ReqMem` gap, explained", next.

**Superseded.** The device path was the one open question this specific
(CPU-only) result could not answer on its own. It has since been answered for
CUDA — see "The CPU-vs-CUDA control, completed", below — leaving only the
HIP-specific path open (and the cluster confirmation the investigation
itself still needs); see "Exhausted, for everything this container can
test" under "Status at a glance", above.

### The `ReqMem` gap, explained

**`ReqMem` in `sacct` is a job total, not a per-node or per-rank figure.**
This is proven directly from the logs already captured in this repository,
not inferred from the jobscripts:

- `mem_test/fail/full/output.log`, the job-summary row:
  `22035606,mem_test/full,FAILED,1:0,16,,688128M,00:00:50`. `NNodes` is 16,
  `ReqMem` is `688128M`. 688128 ÷ 16 = **43008 MiB/node**.
- `mem_test/fail/64x32x32/output.log`, the job-summary row:
  `22035605,mem_test/64x32x32,FAILED,1:0,1,,43008M,00:00:33`. `NNodes` is 1,
  `ReqMem` is `43008M` outright.

The per-node figure is identical in both — 43008 MiB/node — which is what
establishes that the 16-node job's `ReqMem` is a whole-job total, not a
per-node one; if it were per-node, the two jobs would show wildly different
values instead of the same one scaled by node count. The same `43008M` also
appears, as a further check, on both passing 1-node runs:
`mem_test/pass/64x16x16/output.log` (`...,43008M,...`) and
`mem_test/pass/128x16x16/output.log` (`...,43008M,...`).

**So every `mem_test` job receives 42 GiB/node** (43008 MiB = 42 GiB exactly)
**— 5.25 GiB/rank** at 8 tasks/node (43008 ÷ 8 = 5376 MiB = 5.25 GiB).

The May 2026 benchmark (`sacct` job 18855130, 2026-05-26, referenced earlier
in this document as completing at 16,384 elements/rank) received `ReqMem`
7864320M over 16 nodes: 7864320 ÷ 16 = **491520 MiB/node = 480 GiB/node = 60
GiB/rank**.

**That is 11.4x more memory per rank** (60 ÷ 5.25 ≈ 11.43), **for jobs whose
`#SBATCH` blocks are identical.** Both the `mem_test/full` jobscript
(`scripts/jobscripts/LUMI-G/mem_test/full.sh`) and the May benchmark's
request `--partition=standard-g --nodes=16 --ntasks-per-node=8
--gpus-per-node=8 --cpus-per-task=6`, and **neither requests memory at all**:
there is no `--mem`, `--mem-per-cpu`, `--mem-per-gpu` or `--exclusive`
anywhere under `scripts/` (checked directly: `grep -rn -- '--mem' scripts/`
and `grep -rln -- '--exclusive' scripts/` both return nothing). The only
related line is `scripts/functions.sh:151`,
`printf "Job Memory: %s\n" $SLURM_JOB_MEMORY`, which only *prints*
`SLURM_JOB_MEMORY` — and it prints empty in the captured logs, confirming no
explicit request was made, not that none was granted.

The arithmetic pins this to a **per-CPU** default rather than a per-node or
per-GPU one. Each node requests 8 tasks x 6 cpus-per-task = 48 CPUs:

- now: 43008 MiB ÷ 48 CPUs = **896 MiB/CPU**
- May: 491520 MiB ÷ 48 CPUs = **10240 MiB/CPU = 10 GiB/CPU**

Both are clean round numbers, which is the signature of a partition or
account default applied per allocated CPU, not an explicit request computed
from case parameters. **The default changed between May and September.**

**This is why the fitted memory-per-rank curve was always going to cross the
new budget.** The two completed ladder points in "Reference measurements"
below give a rough linear fit: 2.74 G at 2,048 elements/rank and 4.56 G at
4,096 elements/rank imply roughly 0.9 MiB/element plus roughly 0.9-0.95 GiB
fixed per-rank overhead, i.e. **roughly 8.2-8.35 GiB/rank at 8,192
elements/rank**. Against the 5.25 GiB/rank now granted, that cannot fit and
no code change is required to explain the failure. It is also consistent with
the two other established results in this document: pure Neko passes every
size because its smaller footprint does fit ("Status at a glance", and
commit `f6b947f` in the Progress log), and per-element cost has *fallen* 4.2%
since May (previous section). All three now agree with a shrunk budget and
disagree with a growing one.

**The failures are genuine kernel OOM kills**, worth recording precisely
since the `sacct` job-level `State` does not say so (next section corrects
the reference table for exactly this reason). From
`mem_test/fail/full/error.log`:

```
[2026-09-14T17:14:38.784] error: Detected 1 oom_kill event in StepId=22035606.1. Some of the step tasks have been OOM Killed.
srun: error: nid005475: tasks 0-2,5,7: Terminated
srun: Force Terminated StepId=22035606.1
```

and from `mem_test/fail/64x32x32/error.log`:

```
[2026-09-14T17:14:22.149] error: Detected 1 oom_kill event in StepId=22035605.1. Some of the step tasks have been OOM Killed.
srun: error: nid005651: task 3: Out Of Memory
srun: Terminating StepId=22035605.1
```

**What is, and is not, established.** The evidence shows the two jobs
received different per-CPU memory defaults from `#SBATCH` blocks that are
textually identical. *Why* the default changed cannot be determined from
this container — the possibilities, none checked against each other:

1. A LUMI site-policy or partition-configuration change to the
   `standard-g` default between May and September.
2. The May job having been submitted with additional `sbatch`
   command-line arguments (e.g. `--mem=0` or similar) not visible in any
   committed jobscript — command-line flags override a script's own
   `#SBATCH` lines and would not appear in this repository either way.
3. Some other account- or reservation-level default specific to that
   submission.

What **is** certain, and what matters for this investigation, is narrower
than any of those three: memory was never requested explicitly in either
case, so whichever default applied, it applied silently, and the fix does
not depend on knowing which of the three it was.

**The actionable fix, and the investigation's immediate next action.** Add an
explicit memory request — `#SBATCH --mem=0`, which requests the whole node
under Slurm — to `scripts/jobscripts/LUMI-G/mem_test/full.sh` and its
siblings (`default.sh`, `small.sh`), re-run the ladder on LUMI, and record
the outcome here either way. If the OOMs disappear, the `ReqMem`-gap
explanation is confirmed for this question — though closing *this
investigation* additionally needs the full-scale `steady_200`/`unsteady_200`
confirmation described in "The investigation's closing criterion" under
"Status at a glance", above. **If the OOMs do not disappear, that is a
result, not a disappointment: it refutes the leading hypothesis this
document currently favours and reopens the search for a code-side cause.**
Say so plainly if it happens, rather than treating a still-failing run as an
inconclusive retry. **This is a cluster action and is explicitly NOT VERIFIED
from this container** — it needs a real LUMI submission, which has not been
done as part of this change.

### The ALE hypothesis, tested and refuted

The repository owner proposed a specific reason the anchor result above
could be searching the wrong range: Neko's ALE work, `53b425161`
"Feature/ale (#2244)", significantly altered `coef_t` and landed
**2026-04-13** — before *both* endpoints already measured (`f1ca7b11d64`/
2026-05-26 and `865225094`/2026-09-08). If ALE were the actual cost, it
would already sit inside both builds compared above and be invisible to
that comparison; the anchor result would then have been searching the
wrong range rather than answering the question.

**Tested directly, and refuted.** Two pairs, one on each side of the merge
and each pinned at the Neko-TOP alignment barrier nearest it (see "Both
repositories must move together", above, for what that means), same
`bisect_4096.case`, 2 ranks, CPU backend, three runs each:

| Point | Neko | Neko-TOP | Runs (MB) | Median |
| --- | --- | --- | --- | --- |
| pre-ALE | `e8900582f` | `6b20dfb` | 2080.6 / 2079.3 / 2079.1 | **2079.3** |
| post-ALE | `53b425161` | `b334750` | 2079.2 / 2079.2 / 2079.2 | **2079.2** |

**Delta across the ALE merge: 0.1 MB**, against a run-to-run spread of
0.2-1.7 MB here. Nothing measurable. This is a meaningful test rather than
a vacuous one precisely because **the `mem_test` case does not configure
ALE at all** — it measures whatever cost the ALE change imposes
*unconditionally*, on runs that never use it, which is exactly the shape of
cost this investigation has been looking for throughout. There is none.

Placed alongside the anchor and top-endpoint numbers already established,
the full series — same case, same rank count, same backend, four points
spanning April to September — is **monotonically decreasing**:

| Point | Neko | Neko-TOP | Date | Median |
| --- | --- | --- | --- | --- |
| pre-ALE | `e8900582f` | `6b20dfb` | 2026-04-13 | 2079.3 MB |
| post-ALE | `53b425161` | `b334750` | 2026-04-13 | 2079.2 MB |
| anchor | `f1ca7b11d64` | `99033428` | 2026-05-26 | 2067.7 MB |
| top endpoint | `865225094` | `0cd5a6d` | 2026-09-08 | 1979.9 MB |

**Total change, April to September: -99.4 MB, about -4.8%.** Gather-scatter
structural invariants were identical in all nine positions across all
twelve runs behind these four points, so every build constructed the same
objects on the same mesh — the comparison is licensed across the whole
series, not assumed at just the two ends.

**The control held.** The `-lgomp` fix needed to build the two April pairs
at all (see "Build gotchas", above) could in principle have perturbed the
already-established May/September numbers, so the top endpoint was rebuilt
from scratch with the fix in place: 1978.9 / 1979.5 / 1980.1 MB against
1979.6 / 1981.2 / 1979.9 MB before it — a 0.4 MB shift in the median, well
inside the run-to-run spread. The old and new top-endpoint numbers are the
same measurement to within noise. Recording this because it matters: a
series that changes its own tooling partway through and does not re-verify
against itself would not be trustworthy, however clean the rest of it looks.

**Scope, stated rather than left implicit.** This closes the ALE-specific
hypothesis and extends the "nothing increased it" host-side finding back to
2026-04-13, but it is still the same measurement as the anchor result
above: one 4,096-element case, 2 ranks, CPU backend, host memory only. It
says nothing on its own about device-side cost — that is answered
separately, and CUDA agrees; see "The CPU-vs-CUDA control, completed",
below, and "Exhausted, for everything this container can test" under
"Status at a glance", above, for what remains open (the HIP-specific path,
and the cluster confirmation this investigation still needs before it can
close).

### The CPU-vs-CUDA control, completed

The CPU-only bisect above cannot see a device-side memory regression: pinned
or managed device allocations only exist in a device build. This control
repeats the same anchor/top-endpoint comparison — same commit pairs
(`f1ca7b11d64`/`99033428` and `865225094`/`0cd5a6d`), same
`bisect_4096.case`, 2 ranks — built for CUDA instead of CPU, to test for
exactly that.

The CUDA anchor build initially failed all three runs, and a 1-rank retry
failed identically, which ruled out two hypotheses directly: not VRAM (it
returned to its pre-run baseline on the crash, rather than climbing towards a
limit) and not rank contention (a single rank failed the same way as two).
The actual cause was an architecture mismatch in the embedded cubins — full
detail, including the fix and its binary-level verification, is under "Build
gotchas", above (`873852c`).

With that fixed, the anchor completes at every rank count tried. Three runs
each, gated on the same completion marker as the CPU runs:

| Backend, ranks | Anchor | Top endpoint | Delta (top - anchor) |
| --- | --- | --- | --- |
| CPU, 2 | 2067.7 MB | 1979.9 MB | -87.8 MB |
| CUDA, 2 | 2132.8 MB | 2073.5 MB | -59.3 MB |

CUDA anchor: 2132.3 / 2132.8 / 2134.2 MB (median 2132.8). CUDA top endpoint:
2070.3 / 2073.5 / 2074.6 MB (median 2073.5) — measured earlier than the
anchor and reused unchanged here, since nothing about that build changed.
Gather-scatter structural invariants are identical between the two CUDA
endpoints, and match the CPU value character-for-character, so all four
builds (two backends times two endpoints) constructed the same objects on the
same mesh.

**The control held.** Both deltas are negative and of similar order — CPU
-87.8 MB, CUDA -59.3 MB — so CUDA does not show the top endpoint higher where
CPU showed it lower. Device-side memory growth is ruled out for the shared
and CUDA-specific code paths this configuration exercises. This corroborates
the CPU bisect result rather than merely failing to challenge it: two
independent backends, on the same commits and the same case, agree on the
direction and rough size of the change.

This is still the same case and rank count as the rest of the bisect, now on
CUDA rather than CPU. The AMD-specific HIP path — principally Neko
`10689388af1` "Zero-copy unified memory for MI300A" — is untouched by this
result; see "Exhausted, for everything this container can test" under
"Status at a glance", above.

## Reference measurements

Baseline to compare everything against. Bytes, from the `sacct` capture
appended to each log by `mem_test.sh`. Update as better numbers arrive.

| Case | Ranks | Elements/rank | MaxRSS | AveRSS | State | Phase reached |
| --- | --- | --- | --- | --- | --- | --- |
| `small` | 1 | 8,192 | 4 MiB (invalid) | — | FAILED, time limit | sampling missed it |
| `64x16x16` | 8 | 2,048 | 2.74 G | 2.66 G | TIMEOUT | into time loop |
| `128x16x16` | 8 | 4,096 | 4.56 G | 4.36 G | TIMEOUT | into time loop |
| `64x32x32` | 8 | 8,192 | 5.81 G | 5.02 G | FAILED, 1:0 (step `.1` OUT_OF_MEMORY) | adjoint Gauss coef |
| `full` | 128 | 8,192 | 5.42 G | 4.73 G | FAILED, 1:0 (step `.1` CANCELLED, oom_kill) | setup |

**Corrected.** `64x32x32` and `full` were previously recorded here as
`OUT_OF_MEMORY` and `OOM` respectively. Neither job's own `sacct` row says
that — both are `FAILED` with exit code `1:0` (Neko's own allocation call
aborting, hence exit 1), verified directly against the job-summary lines in
the two logs:

```
22035605,mem_test/64x32x32,FAILED,1:0,1,,43008M,00:00:33
22035606,mem_test/full,FAILED,1:0,16,,688128M,00:00:50
```

The memory kill is real, it just surfaces one level down, as a Slurm *step*
state rather than the job state: `64x32x32`'s `.1` step is
`22035605.1,select_gpu,OUT_OF_MEMORY,0:125,...`, a clean single-step OOM;
`full`'s `.1` step is `22035606.1,select_gpu,CANCELLED,0:15,...`, `error.log`
showing repeated `oom_kill` events across several nodes before the step is
force-terminated — a cascade rather than a single clean kill, consistent with
128 tasks across 16 nodes all hitting the same per-rank ceiling at once. Both
`error.log`s independently confirm the kernel event
(`error: Detected 1 oom_kill event in StepId=...`). **Anyone grepping `sacct`
output for `State=OUT_OF_MEMORY` at the job level will find nothing for
either row and should not conclude there was no OOM** — check the `.1` step
row and `error.log`, not the job-summary row. See "The `ReqMem` gap,
explained" above for why the budget these jobs actually received made this
inevitable.

Gather-scatter sizes from the logs, useful as a sanity check that a build
still constructs the same objects:

| Case | Adjoint GLL internal | Adjoint Gauss internal | Ratio |
| --- | --- | --- | --- |
| `128x16x16` | 476,160 | 1,570,816 | 3.30 |
| `64x32x32` | 1,095,680 | 3,557,376 | 3.25 |

## Resuming on another machine

**Machine-specific note.** This section, and the "Much of this runs locally"
paragraph earlier under "Finding the regression", were written on an earlier
machine: a CUDA device build sharing one GPU, `--enable-real=sp`, `sm_75`.
Treat every CUDA/`CUDA_DIR`/`sm_75`/single-precision detail below as a
description of *that* machine, not a requirement of the tooling. **The
current machine's work — including the bisect anchor and top-endpoint
measurements in "The anchor measurement, and what it found", above — is CPU
backend, double precision** (`BISECT_BACKEND=cpu`, `--enable-real=dp`), which
sidesteps the single-precision build failures logged below entirely; the
`--enable-real=dp is not optional` warning under "The build environment"
still applies on any machine, CPU or device.

### What is NOT in the repository

Three things this investigation depends on are gitignored, so a fresh
checkout does not have them. All three are reproducible.

**1. The meshes. `data_local/` is gitignored.** `mem_test/bisect/bisect.case`
and every `mem_test` case reference `data_local/static_mixer/mixer_*.nmsh`.
These are plain boxes: `x` in [0, 4], `y` in [0, 1], `z` in [0, 1], with
`Nx x Ny x Nz` cells and no periodicity, which is where the naming comes
from. Regenerate any of them with Neko's own tool:

```bash
export LD_LIBRARY_PATH=external/json-fortran/lib:external/hdf5/lib:$LD_LIBRARY_PATH
external/neko/bin/genmeshbox 0 4 0 1 0 1 <Nx> <Ny> <Nz> .false. .false. .false.
mv box.nmsh data_local/static_mixer/mixer_<Nx>x<Ny>x<Nz>.nmsh
```

Verified: a regenerated `16x4x4` gives 646.8 MB against 642 to 648 MB for
the archived one, so it is equivalent for this purpose. It is *not*
byte-identical, most likely a generator version difference, so do not expect
checksums to match. The `LD_LIBRARY_PATH` is needed or the tool fails to find
`libjsonfortran`.

**2. The build environment. `prepare.env` is gitignored.** What matters:

```bash
export CMAKE_GENERATOR="Ninja"
export CMAKE_BUILD_TYPE="Debug"
export CUDA_DIR="/usr/local/cuda"          # or the HIP equivalent
export HDF5_DIR="hdf5"
export NEKO_DIR="<repo>/external/neko"
export NEKO_FCFLAGS="-g -w -O2"
export NEKO_CUDA_ARCH="-arch=sm_75"        # match the local GPU
export NEKO_CUDA_CFLAGS="-g -w -O3"
export NEKO_CONFIG_FLAGS="--enable-real=dp --enable-openmp"
export CUDA_ARCH="75"
export OMP_NUM_THREADS="16"
```

**`--enable-real=dp` is not optional.** Neko-TOP does not compile in a
single-precision build; Neko keeps time quantities in `dp` while Neko-TOP
declares the receiving variables at working precision, and
`-Werror=conversion` rejects about fourteen sites. The cluster is double
precision anyway.

**3. `external/`, also gitignored**, holding Neko itself and the vendored
dependencies. `setup.sh` fetches and builds them.

### One thing that is easy to get wrong

`examples/mem_test/CMakeLists.txt` selects `topopt-user`, so the example
builds `sources/drivers/topopt-user.f90`, **not** `topopt.f90`. All three
drivers are instrumented, but if you add a probe and see no output, check
which driver the example actually uses. `easy-E` is the example that
exercises `neko-user.f90`.

### Procedure

The worktrees and builds live under `/tmp` and will be gone. Recreate them
with `build_pair.sh`, which is idempotent and skips work already done.

1. Recreate `prepare.env` and `external/` per above, and obtain or regenerate
   at least `data_local/static_mixer/mixer_16x4x4.nmsh`. Build in **double
   precision**.
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
- **2026-09-14** — Handoff audit. Found that `data_local/`, `prepare.env` and
  `external/` are all gitignored, so a fresh checkout lacks the meshes and the
  build configuration. All three are now documented and reproducible: the
  mixer meshes are `genmeshbox` boxes over [0,4]x[0,1]x[0,1], verified by
  regenerating `16x4x4` and measuring 646.8 MB against the archived mesh's
  642 to 648 MB band.
- **2026-09-15** — Fixed the build blocker that had nothing to do with the
  case file: `make LIBS=-lstdc++` overrides the Makefile's own `LIBS` instead
  of appending, silently discarding every configure-detected library.
  Corrected to pass `LIBS=-lstdc++` as a `./configure` argument (`c3b8194`).
  Same commit found and worked around a second hazard: this container's
  system HDF5 2.2.0 under `/usr/local` shares a SONAME with the vendored
  2.0.0 and is put first on the loader's path by a global
  `LD_LIBRARY_PATH`, silently substituting itself at build and run time —
  filed as backlog #46, worked around in the bisect scripts by pinning
  `LD_LIBRARY_PATH`/`HDF5_ROOT` to the vendored copy.
- **2026-09-15** — Resolved the case-schema drift that had blocked the anchor
  since it was written (`0cd5a6d`). The failing key was
  `optimization.solver.max_runtime` (real at the anchor, string at HEAD),
  not the objectives block the stack trace pointed at; dropped it, along
  with a dead `phi_ref` key, an inert `coarse_grid.solver`, and
  `fused_cg` (CUDA/HIP-only, aborts on CPU). Moved the bisect to the CPU
  backend and a 4,096-element case (`bisect_4096.case`) in the same pass,
  since 256 elements was too coarse to resolve the expected signal.
- **2026-09-15** — **The anchor measurement now exists, and it falsifies the
  regression hypothesis for the range searched.** `bisect_4096.case`, CPU,
  double precision, 2 ranks, three runs each: anchor (`f1ca7b11d64`/
  `99033428`) medians 2067.7 MB; top endpoint (`865225094`/`0cd5a6d`)
  medians 1979.9 MB — the anchor is 87.8 MB *higher*, about 55x the 1.6 MB
  run-to-run spread, with identical gather-scatter structural invariants
  confirming both builds ran the same workload. Per-element host memory
  cost improved roughly 4.2% between May and September on this case; it did
  not regress. Both anchor-build risks (gfortran 15.2 compiling four-month-
  old Neko, the case parsing at all) came to nothing. This is narrow: CPU
  only, 4,096 elements, and it leaves the May-vs-September capacity
  contradiction (51.25 GiB/rank at 16,384 elements/rank in May; OOM at
  8,192 elements/rank now, same requested resources) explicitly open, and
  the CPU-vs-CUDA control that would test for a device-side regression has
  not been run. Full detail in "The anchor measurement, and what it found",
  above.
- **2026-09-15** — **The May-vs-September capacity contradiction is
  resolved.** `ReqMem` in `sacct` is a job total, not a per-node figure:
  proven from the logs, where `full`'s `688128M` over 16 nodes and
  `64x32x32`'s `43008M` over 1 node agree exactly per-node (43008 MiB/node,
  5.25 GiB/rank at 8 tasks/node). The May job (`sacct` 18855130) received
  `7864320M` over 16 nodes — 60 GiB/rank, 11.4x more — from an `#SBATCH`
  block identical to the current one, which requests no memory explicitly in
  either case (896 MiB/CPU now vs 10240 MiB/CPU in May: both clean numbers,
  the signature of a changed partition/account default, not a changed
  request). The previously-recorded "51.25 GiB/rank" May figure was actual
  usage, not the budget, and sits comfortably under the now-known 60 GiB/rank
  it actually had. Against 5.25 GiB/rank now, the reference table's own
  fitted per-rank cost (~8.2-8.35 GiB at 8,192 elements/rank) cannot fit,
  which needs no code regression to explain. *Why* the default changed
  (LUMI policy, partition reconfiguration, or an `sbatch` flag on the May
  submission not visible in any committed jobscript) is not determinable from
  this container and is recorded as open possibilities, not a conclusion.
  Also corrected two termination-cause errors this carried: `64x32x32` and
  `full` are `sacct`-job-level `FAILED` (exit `1:0`), not `OUT_OF_MEMORY`/
  `OOM` — the kernel OOM is real and confirmed in both `error.log`s, it just
  surfaces as a step-level state (`.1` step `OUT_OF_MEMORY` for `64x32x32`,
  `.1` step `CANCELLED` after cascading `oom_kill` events for `full`), not
  the job's own state. Actionable fix, a cluster action not verifiable here:
  add `#SBATCH --mem=0` to the `mem_test` jobscripts and re-run. Full detail
  in "The `ReqMem` gap, explained" under Bisecting, above.
- **2026-09-15** — Fixed a second, pre-May-only build blocker: any
  Neko-TOP commit older than `99033428` (2026-05-20) fails to *link*, with
  undefined `GOMP_parallel`/`omp_get_thread_num`/`GOMP_barrier`, because
  Neko-TOP's own CMake only started linking `OpenMP::OpenMP_Fortran`
  between `6b20dfb` (04-14) and `99033428` (05-20); not a `neko.pc` issue,
  confirmed by a byte-identical `neko.pc` across April/May/September builds
  and by `libgomp.so` being present in working `build.ninja`s and absent
  from broken ones. Fixed the same way as the earlier `-lstdc++` case:
  `-lgomp` via `CMAKE_Fortran_STANDARD_LIBRARIES` (`280aaa8`). Verified
  harmless to the established numbers by rebuilding the top endpoint with
  it in place: 0.4 MB shift in the median, inside the run-to-run spread —
  see next entry for the full rebuild-and-compare numbers.
- **2026-09-15** — **The ALE hypothesis is tested and refuted.** Proposed
  reasoning: `53b425161` "Feature/ale (#2244)" (2026-04-13) significantly
  altered `coef_t` and landed before both points already measured, so its
  cost would sit inside both and be invisible to that comparison. Tested
  directly: pairs either side of the merge, same case/ranks/backend —
  pre-ALE (`e8900582f`/`6b20dfb`) medians 2079.3 MB, post-ALE
  (`53b425161`/`b334750`) medians 2079.2 MB, a 0.1 MB delta against a
  0.2-1.7 MB spread, and the `mem_test` case never configures ALE, so this
  is a genuine test of unconditional cost, not a vacuous one. Placed with
  the anchor and top-endpoint numbers, the four-point series
  April-to-September is monotonically decreasing, -99.4 MB / -4.8% total.
  The `-lgomp` fix needed to build the April pairs was checked for its own
  effect on the established numbers: the top endpoint rebuilt with it
  measures 1978.9/1979.5/1980.1 MB against 1979.6/1981.2/1979.9 MB before
  — a 0.4 MB shift in the median, inside the run-to-run spread, so the old
  and new numbers are comparable. Full detail in "The ALE hypothesis,
  tested and refuted" under Bisecting, above.
- **2026-09-15** — Hit and documented a silent build-configuration trap:
  without `FORCE_PKGCONF_PYPI=1` set, this container's PyPI `pkgconf` shim
  returns an empty `Cflags` for json-fortran, so `configure` reports "yes"
  while the generated `FCFLAGS` carry no `-I`, and the build only fails much
  later in `common/json_utils.f90` with `Cannot open module file
  'json_module.mod'`. Documented alongside the existing pkg-config material
  under Build gotchas.
- **2026-09-15** — Diagnosed and fixed why the CUDA anchor build could not
  run: not VRAM and not rank contention (both tested and refuted — VRAM
  returned to baseline on the crash, and a 1-rank retry failed identically),
  but a mixed-architecture binary. Neko-TOP's own five CUDA translation units
  built for CMake/CUDA-13's default architecture rather than the host GPU on
  any Neko-TOP commit before `99033428` (2026-05-20), while Neko's own device
  code got the right one from Neko's `configure` — 57 `sm_86` cubins plus 5
  `sm_75` on this machine, which the driver cannot JIT, failing at the first
  Neko-TOP kernel launch (`math_ext.cu:66`). Fixed by passing
  `-DCMAKE_CUDA_ARCHITECTURES` on the `cmake` command line (`873852c`),
  verified at the binary level with `cuobjdump --list-elf`: 57/5 before, 62/0
  after. Same class of bug as the `-lgomp` fix (`280aaa8`). Full detail under
  "Build gotchas", above.
- **2026-09-15** — **The CPU-vs-CUDA control is complete, and agrees with the
  CPU result.** CUDA anchor (2 ranks) medians 2132.8 MB
  (2132.3/2132.8/2134.2), CUDA top endpoint medians 2073.5 MB
  (2070.3/2073.5/2074.6, measured earlier and reused unchanged) — a delta of
  -59.3 MB, against -87.8 MB on CPU. Both negative and of similar order: CUDA
  shows no growth the CPU measurement was hiding. Gather-scatter structural
  invariants identical between the two CUDA endpoints and matching the CPU
  value. Device-side memory growth is ruled out for the shared and
  CUDA-specific code paths measured; this corroborates the CPU bisect result
  rather than merely failing to challenge it. Full detail in "The CPU-vs-CUDA
  control, completed", above. This exhausts every avenue this container can
  test — it does not close the investigation, which still needs a documented
  full-scale LUMI success; see "Status at a glance", above, for what remains
  (the HIP-specific path, plus the cluster actions already queued, foremost
  the `--mem=0` confirmation run).
- **2026-09-16** — Corrected this document's own status framing; no
  measurement changed. The bottom line and the section formerly headed
  "Closed, for everything this container can test" (now "Exhausted, for
  everything this container can test") stated the allocation-change
  explanation as this investigation's settled conclusion. It is a leading
  hypothesis with strong local supporting evidence, not a demonstrated fact:
  no full-scale LUMI run has yet been observed succeeding since the failures
  began. Added an explicit closing criterion — the investigation closes only
  when a full-scale run is documented completing on LUMI, its `sacct` row
  and per-rank peak recorded here beside the May benchmark's own figures, in
  the already-established `mem_test/pass/`/`mem_test/fail/` logs — and made
  explicit throughout that a still-failing confirmation run would refute the
  hypothesis and reopen the search, not merely disappoint. Reordered
  `_next_`, below, so the LUMI confirmation run is item one.
- **_next_** — **(1) The investigation's closing action: add
  `#SBATCH --mem=0` to the `mem_test` jobscripts (`full.sh` and its
  siblings), re-run the full-scale ladder on LUMI, and record the outcome in
  this document — the `sacct` row (`ReqMem`, `MaxRSS`, `State`) and per-rank
  peak, set beside the May benchmark's own figures, in
  "The investigation's closing criterion" under "Status at a glance".
  Completing this is the only thing that closes the investigation; if the
  OOMs persist, that refutes the allocation-change hypothesis and reopens the
  search for a code-side cause, which is itself a result worth recording in
  full, not a null outcome.** (2) The HIP-specific path — principally Neko
  `10689388af1` "Zero-copy unified memory for MI300A" — is confirmed
  unreachable in any CUDA build by source inspection (new files are `.hip`,
  the `Makefile.am` hunks sit inside `if ENABLE_HIP`, `device.F90` changes are
  inside `#ifdef HAVE_HIP` with nothing in the `#elif HAVE_CUDA` branch), and
  this container has no ROCm toolchain, so it is testable only on the
  production cluster. (3) Run the ladder on LUMI with the probes for the
  per-rank component budget. (4) Recover the May benchmark results from LUMI
  for a historical baseline, since `single_node_capacity.csv` swept to
  16,384 elements per rank at `n_memory=100`, double what fails now.
  (5) Independently of the regression question, now answered negatively
  across the whole host-side and CUDA range searched: the unconditional
  adjoint Gauss over-integration stack (about a third of loadup on a
  `dealias: false` case) remains worth gating or trimming on its own merits.
