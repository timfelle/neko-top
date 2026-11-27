#!/usr/bin/env python3
"""Per-iteration report on a Neko-TOP steepest-descent run.

Question: why does the steepest-descent run move its design as much (or
as little) as it does?

Usage:
    sd_report.py RUN_DIR [--case FILE] [--iters 0,1,5 | all] [--top N]
                 [--save OUT.npz] [--box x0,x1,y0,y1,z0,z1]

Reads (read-only) from RUN_DIR: design_0.vtkhdf + design_0.data/ (field
design_indicator), sensitivity_0.vtkhdf + sensitivity_0.data/ (field
dFd_design_indicator), optionally optimization_data.csv, and the case file
(or pass --case). One iteration is held in memory at a time, about six
arrays of the mesh size (0.5 GB each at 256x64x64 order 3).

For every iteration k it prints:
  - how much of the design domain is held by a bound, and how much is free;
  - what the steepest-descent normaliser (largest free |sensitivity|) is,
    where it sits, and whether it is an isolated node or a smooth maximum;
  - what limits the step of the free nodes: the move limit, or the
    normaliser (step = |sensitivity| / largest);
  - how the per-node move limits have evolved (they shrink by the factor
    "decrease" at a node whose last two changes have opposite sign, and
    grow by "increase" where they have the same sign);
  - whether the stored design k+1 is what the algorithm gives from design k
    and sensitivity k (offline replay of the update);
and a one-line-per-iteration summary at the end.

--save writes the listed top nodes and all nodes inside --box (default: a
box around the largest free value) for the chosen iterations to a small
.npz, for plotting elsewhere.
"""
import argparse
import json
import os
import resource

import h5py
import numpy as np

import sensitivity_tools as st


def solver_parameters(case):
    """Steepest-descent parameters, with the Neko-TOP defaults."""
    sol = case["optimization"]["solver"]
    sd = sol.get("steepest_descent", {})
    ml = sd.get("move_limit", {})
    return dict(xmin=sd.get("xmin", 0.0), xmax=sd.get("xmax", 1.0),
                psi=sd.get("step_length", 1.0),
                d0=ml.get("initial", 0.1), dmin=ml.get("min", 0.001),
                dmax=ml.get("max", 0.1), dec=ml.get("decrease", 0.7),
                inc=ml.get("increase", 1.1))


def print_header(cf, case, par, dom):
    """Print the case file, solver, mapping, objectives and domain."""
    opt = case["optimization"]
    sol = opt["solver"]
    print(f"# case {cf}")
    print(f"# solver {sol.get('type')}: step_length {par['psi']}, "
          f"move limit initial {par['d0']} min {par['dmin']} "
          f"max {par['dmax']} decrease {par['dec']} "
          f"increase {par['inc']}; "
          f"stop_design_change {sol.get('stop_design_change')}, "
          f"max_iterations {sol.get('max_iterations')}")
    print(f"# mapping {json.dumps(opt['design'].get('mapping'))}")
    texts = []
    for o in opt.get("objectives", []):
        w, notes = st.weight_text(case, o)
        texts.append(f"{o['type']} (weight {'; '.join([w] + notes)})")
    print("# objectives " + ", ".join(texts))
    print(f"# design domain zone: {json.dumps(dom)}")


def print_csv(run):
    """Echo optimization_data.csv, if present, as a table."""
    csv = os.path.join(run, "optimization_data.csv")
    if os.path.exists(csv):
        print("\n## optimization_data.csv")
        with open(csv) as f:
            for line in f:
                print("  " + " | ".join(
                    c.strip() for c in line.rstrip("\n").split(",")))


def top_nodes(G, fi, fa, des, lx, lo, hi, ntop):
    """The ntop largest free |g| unique nodes and their neighbourhoods.

    A node shared by several elements is counted once; the GLL neighbours
    of every element copy found are collected for the isolation ratio.
    @return list of local indices, rows [point, local index, neighbour
            |g| list, number of copies]
    """
    n3 = lx ** 3
    cand = fi[np.argsort(-fa)[:8 * ntop]]
    pc = des.points(cand)
    key = np.round(pc / (1e-6 * max(hi - lo))).astype(np.int64)
    seen, top, rows = {}, [], []
    for n_, p, kk in zip(cand, pc, map(tuple, key)):
        e, loc = divmod(int(n_), n3)
        ge = np.abs(G[e * n3:(e + 1) * n3])
        i3 = np.unravel_index(loc, (lx, lx, lx))
        nb = []
        for ax in range(3):
            for s_ in (-1, 1):
                j3 = list(i3)
                j3[ax] += s_
                if 0 <= j3[ax] < lx:
                    nb.append(ge[np.ravel_multi_index(j3, (lx, lx, lx))])
        if kk not in seen:
            if len(top) >= ntop:
                continue
            seen[kk] = len(top)
            top.append(int(n_))
            rows.append([p, loc, [], 0])
        rows[seen[kk]][2].extend(nb)
        rows[seen[kk]][3] += 1
    return np.array(top), rows


def save_box(a, des, saved, vol, lo, hi, lx):
    """Write the nodes inside the box and the top nodes to a .npz."""
    ks = sorted(saved.get("g", {}))
    if not ks:
        return
    k0 = ks[0]
    if a.box:
        b = [float(t) for t in a.box.split(",")]
    else:
        c = des.points(saved["top_index"][k0][:1])[0]
        span = 6 * (vol.mean() ** (1 / 3))
        b = [float(max(lo[i // 2], c[i // 2] - span)) if i % 2 == 0 else
             float(min(hi[i // 2], c[i // 2] + span)) for i in range(6)]
    sel = np.zeros(des.npt, dtype=bool)
    with h5py.File(des.f, "r") as h:
        pts = h["VTKHDF/Points"]
        ch = 4_000_000
        for i0 in range(0, des.npt, ch):
            p = pts[i0:i0 + ch]
            sel[i0:i0 + ch] = ((p[:, 0] >= b[0]) & (p[:, 0] <= b[1])
                               & (p[:, 1] >= b[2]) & (p[:, 1] <= b[3])
                               & (p[:, 2] >= b[4]) & (p[:, 2] <= b[5]))
    idx = np.flatnonzero(sel)
    out = dict(box=np.array(b), index=idx, points=des.points(idx), lx=lx,
               iterations=np.array(ks))
    for k in ks:
        out[f"design_{k}"] = saved["x"][k][idx]
        out[f"sensitivity_{k}"] = saved["g"][k][idx]
        out[f"top_index_{k}"] = saved["top_index"][k]
        out[f"top_points_{k}"] = des.points(saved["top_index"][k])
    np.savez_compressed(a.save, **out)
    print(f"\n# saved {len(idx)} nodes inside box {b} for iterations {ks} "
          f"to {a.save}")


def print_summary(summ):
    """Print the one-line-per-iteration summary table."""
    print("\n## summary (one line per iteration)")
    print("  iter  free vol.frac  normaliser    /median  isolation  "
          "move-limited  at min limit  median intended step | change INTO "
          "this iteration: largest, vol.frac > 1e-3")
    for k in sorted(summ):
        r = summ[k]
        if "smax" not in r:
            continue

        def f(key, fmt):
            """Format r[key], or a dash if it is not there."""
            return (fmt % r[key]) if key in r else "     -"
        print(f"  {k:4d}  {r['free']:12.5f}  {r['smax']:11.4e}  "
              f"{r['ratio']:7.1f}  {f('iso', '%8.2f')}  "
              f"{f('limited', '%11.4f')}  {f('atmin', '%11.4f')}  "
              f"{f('step', '%14.3e')}      | {f('dmax', '%.4e')}, "
              f"{f('moved', '%.5f')}")


def main():
    """Parse the arguments and print the report."""
    ap = argparse.ArgumentParser(
        description="Per-iteration report on a Neko-TOP steepest-descent "
        "run, from its design and sensitivity output.")
    ap.add_argument("run", help="run directory")
    ap.add_argument("--case", help="case file (default: the *.case file "
                    "in the run directory)")
    ap.add_argument("--iters", default="all",
                    help="comma-separated iterations to report in full, "
                    "or 'all' (default); the replay and the summary "
                    "always go through every iteration")
    ap.add_argument("--top", type=int, default=12,
                    help="number of largest free values listed "
                    "(default 12)")
    ap.add_argument("--save", metavar="OUT.npz",
                    help="write the nodes inside --box and the listed "
                    "nodes of the reported iterations to this file")
    ap.add_argument("--box", metavar="x0,x1,y0,y1,z0,z1",
                    help="box for --save (default: around the largest "
                    "free value of the first reported iteration)")
    a = ap.parse_args()

    cf, case = st.load_case(a.run, a.case)
    N = st.polynomial_order(case)
    lx = N + 1
    n3 = lx ** 3
    par = solver_parameters(case)
    xmin, xmax, psi = par["xmin"], par["xmax"], par["psi"]
    d0, dmin = par["d0"], par["dmin"]
    dmax, dec, inc = par["dmax"], par["dec"], par["inc"]
    dom = st.design_domain(case)
    print_header(cf, case, par, dom)

    des = st.Series(a.run, "design")
    sen = st.Series(a.run, "sensitivity")
    if des.npt != sen.npt or des.npt % n3:
        raise SystemExit(f"point counts do not fit: design {des.npt}, "
                         f"sensitivity {sen.npt}, order {N}")
    nel, vol, M, lo, hi = st.geometry(des, lx, dom)
    Wt = st.Weights(lx, vol)
    V = Wt.sum(M)
    cls = st.local_class(lx)
    print(f"# mesh: {nel} elements, order {N}, {des.npt} local nodes, "
          f"box {lo} .. {hi}; element volume min {vol.min():.4e} "
          f"max {vol.max():.4e}; design-domain volume {V:.6f} "
          f"({M.sum()} local nodes)")
    print(f"# steps on disk: design {des.nsteps}, sensitivity "
          f"{sen.nsteps}; fields: design {des.names(0)}, sensitivity "
          f"{sen.names(0)}")
    print_csv(a.run)

    nit = max(des.nsteps, sen.nsteps)
    summ = {}
    want = (list(range(nit)) if a.iters == "all"
            else [int(t) for t in a.iters.split(",")])
    saved = {}

    x1 = x2 = None      # designs k-1, k-2
    delta = None        # per-node move limit used for the step k -> k+1
    replay_ok = True
    xr = None           # replayed design k (from the step k-1 -> k)
    for k in range(nit):
        if not des.has(k):
            print(f"\n## iteration {k}: design file missing; "
                  "replay stops here")
            replay_ok = False
            x2, x1 = None, None
            continue
        x = des.read(k, "design_indicator").astype(np.float64)
        report = k in want
        summ[k] = {}
        if report:
            print(f"\n## iteration {k}")
            grey = Wt.sum(M & (x > xmin + 1e-12) & (x < xmax - 1e-12)) / V
            print(f"  design: range {x.min():.6f} .. {x.max():.6f}; "
                  "volume fraction of the design domain at the lower "
                  f"bound {Wt.sum(M & (x <= xmin + 1e-12)) / V:.5f}, "
                  "at the upper bound "
                  f"{Wt.sum(M & (x >= xmax - 1e-12)) / V:.5f}, in between "
                  f"{grey:.5f}; mean {Wt.sum(np.where(M, x, 0.0)) / V:.6f}")
        if xr is not None:
            dif = np.abs(x - xr)
            dif[~M] = 0.0
            j = int(dif.argmax())
            if report:
                print(f"  replay check: stored design {k} against the "
                      f"update replayed from iteration {k - 1}: largest "
                      f"difference {dif[j]:.3e}"
                      + ("" if dif[j] < 1e-6 else
                         "  <-- the offline replay does NOT reproduce "
                         "the stored design"))
            del dif
            xr = None
        if x1 is not None:
            d = np.abs(x - x1)
            d[~M] = 0.0
            mv = d > 1e-12
            summ[k]["dmax"] = float(d.max())
            summ[k]["moved"] = Wt.sum(d > 1e-3) / V
            if report:
                if mv.any():
                    idx = np.flatnonzero(mv)
                    w = Wt.of(idx)
                    q = st.wquant(d[idx], w, np.array([0.5, 0.9, 0.99]))
                    print(f"  change from iteration {k - 1}: {mv.sum()} "
                          "local nodes moved, volume fraction "
                          f"{Wt.sum(mv) / V:.5f}; largest {d.max():.4e}; "
                          "volume-weighted quantiles of the moved "
                          f"50/90/99 % = {q[0]:.3e} {q[1]:.3e} {q[2]:.3e}; "
                          "volume fraction moved by more than 1e-3: "
                          f"{Wt.sum(d > 1e-3) / V:.5f}, 1e-2: "
                          f"{Wt.sum(d > 1e-2) / V:.5f}, 0.05: "
                          f"{Wt.sum(d > 0.05) / V:.5f}")
                    up = Wt.sum(mv & (x > x1)) / V
                    print(f"    of which material added on volume fraction "
                          f"{up:.5f}, removed on "
                          f"{Wt.sum(mv & (x < x1)) / V:.5f}")
                else:
                    print(f"  change from iteration {k - 1}: none")
            del d, mv

        if not sen.has(k):
            if report:
                print("  sensitivity file missing for this iteration")
            x2, x1 = x1, x
            replay_ok = False
            continue
        G = sen.read(k, "dFd_design_indicator").astype(np.float64)
        S = -G
        frozen = ((x >= xmax) & (S > 0)) | ((x <= xmin) & (S < 0))
        S[frozen] = 0.0
        S[~M] = 0.0
        aS = np.abs(S)
        free = aS > 0
        smax = float(aS.max())
        if report:
            f_lo = Wt.sum(M & (x <= xmin) & (G > 0)) / V
            f_hi = Wt.sum(M & (x >= xmax) & (G < 0)) / V
            print(f"  sensitivity: range {G.min():+.4e} .. {G.max():+.4e}; "
                  "largest |g| in the design domain "
                  f"{np.abs(G[M]).max():.4e}")
            print(f"  held by a bound: lower (rho = {xmin:g}, g > 0) volume "
                  f"fraction {f_lo:.5f}; upper (rho = {xmax:g}, g < 0) "
                  f"{f_hi:.5f}; free {Wt.sum(free) / V:.5f} "
                  f"({free.sum()} local nodes)")
        if smax <= 0:
            if report:
                print("  no free node: nothing can move")
            x2, x1 = x1, x
            continue
        if not report and not replay_ok:
            x2, x1 = x1, x
            continue
        fi = np.flatnonzero(free)
        fw = Wt.of(fi)
        fa = aS[fi]
        q = st.wquant(fa, fw, np.array([0.5, 0.9, 0.99, 0.999]))
        summ[k].update(free=fw.sum() / V, smax=smax, ratio=smax / q[0])
        if report:
            print(f"  normaliser (largest free |g|) {smax:.5e}; free-set "
                  "volume-weighted quantiles 50/90/99/99.9 % = "
                  f"{q[0]:.3e} {q[1]:.3e} {q[2]:.3e} {q[3]:.3e}; "
                  f"largest / median = {smax / q[0]:.1f}")
            print("  free local nodes with |g| above half the largest: "
                  f"{(fa >= 0.5 * smax).sum()}, above a tenth: "
                  f"{(fa >= 0.1 * smax).sum()}; of the free volume: free "
                  f"solid-side (g > 0) {fw[G[fi] > 0].sum() / fw.sum():.4f}"
                  ", free fluid-side (g < 0) "
                  f"{fw[G[fi] < 0].sum() / fw.sum():.4f}")
            top, rows = top_nodes(G, fi, fa, des, lx, lo, hi, a.top)
            print(f"  the {len(top)} largest free |g| unique nodes "
                  "(isolation = |g| over the mean |g| of its nearest GLL "
                  "neighbours, taken from every element copy found; near 1 "
                  "is a smooth maximum, far above 1 a single-node peak):")
            print("        x         y         z       class    copies  "
                  "rho      g           isolation")
            for n_, (p, loc, nb, nc) in zip(top, rows):
                iso = (abs(G[n_]) / np.mean(nb) if np.mean(nb) > 0
                       else np.inf)
                print(f"    {p[0]:9.5f} {p[1]:9.5f} {p[2]:9.5f}  "
                      f"{st.CLASSES[cls[loc]]:8s} {nc:4d}  {x[n_]:7.4f}  "
                      f"{G[n_]:+.4e}  {iso:8.2f}")
            summ[k]["iso"] = abs(G[top[0]]) / np.mean(rows[0][2])
            saved.setdefault("top_index", {})[k] = top
            fc = cls[fi % n3]
            parts = []
            for c in range(4):
                m = fc == c
                mean = (fw[m] * fa[m]).sum() / max(fw[m].sum(), 1e-300)
                parts.append(f"{st.CLASSES[c]} {int(m.sum())} / {mean:.3e}")
            print("  free set by element-local class (count, "
                  "volume-weighted mean |g|): " + ", ".join(parts))

        # move limits for the step k -> k+1, and the replay
        if replay_ok:
            if delta is None:
                delta = np.full(des.npt, d0)
            if k >= 2 and x1 is not None and x2 is not None:
                dd = x - x1
                t = x1 - x2
                dd *= t
                del t
                delta[dd < 0] *= dec
                delta[dd > 0] *= inc
                np.clip(delta, dmin, dmax, out=delta)
                del dd
            r = psi * aS / smax
            summ[k]["step"] = float(st.wquant(
                np.minimum(r[fi], delta[fi]), fw, np.array([0.5]))[0])
            summ[k]["atmin"] = float(
                fw[delta[fi] <= dmin * 1.0000001].sum() / fw.sum())
            summ[k]["limited"] = float(fw[r[fi] >= delta[fi]].sum()
                                       / fw.sum())
            if report:
                df = delta[fi]
                rf = r[fi]
                lim = rf >= df
                qd = st.wquant(df, fw, np.array([0.0, 0.5, 1.0]))
                step = np.minimum(rf, df)
                qs = st.wquant(step, fw, np.array([0.5, 0.9]))
                at_min = fw[df <= dmin * 1.0000001].sum() / fw.sum()
                shrunk = fw[df < d0 * 0.999].sum() / fw.sum()
                print(f"  move limits on the free set: min {df.min():.4g} "
                      f"median {qd[1]:.4g} max {df.max():.4g}; free volume "
                      f"at the smallest allowed limit ({dmin:g}): "
                      f"{at_min:.4f}; shrunk below the initial {d0:g}: "
                      f"{shrunk:.4f}")
                print("  what limits the step of the free volume: move "
                      f"limit {fw[lim].sum() / fw.sum():.4f}, normaliser "
                      f"(|g| / largest) {fw[~lim].sum() / fw.sum():.4f}; "
                      "intended step, volume-weighted median "
                      f"{qs[0]:.3e}, 90 % {qs[1]:.3e}")
                for lab, nv in (("99.9 % quantile", q[3]),
                                ("99 % quantile", q[2])):
                    stp = np.minimum(psi * fa / nv, df)
                    print(f"    if the normaliser were the {lab} of the "
                          f"free |g| ({nv:.3e}): median intended step "
                          f"{st.wquant(stp, fw, np.array([0.5]))[0]:.3e}")
                del df, rf, lim, step
            del r, aS
            # the update, in place in S: move limit first, box second
            S *= psi / smax
            S += x
            t = x - delta
            np.maximum(S, t, out=S)
            np.add(x, delta, out=t)
            np.minimum(S, t, out=S)
            del t
            np.clip(S, xmin, xmax, out=S)
            np.copyto(S, x, where=~M)
            xr, S = S, None
        if a.save and report:
            saved.setdefault("x", {})[k] = x
            saved.setdefault("g", {})[k] = G
        x2, x1 = x1, x
        S = aS = free = frozen = None
        if not (a.save and report):
            G = None

    print_summary(summ)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576
    print(f"\n# peak memory of this script: {peak:.2f} GB")
    if a.save:
        save_box(a, des, saved, vol, lo, hi, lx)


if __name__ == "__main__":
    main()
