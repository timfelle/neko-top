#!/usr/bin/env python3
"""Seed-design sensitivity split by objective, and what each weight frees.

Question: which objective sets the sensitivity of the seed design, and
how would other weights of the viscous- and Brinkman-dissipation
objectives change how much of the design is free to move?

Usage:
    weight_scan.py RUN [RUN ...] [--factors 1:1,1:0.1,0:0]

Every RUN is an evaluation (max_iterations: 0 is enough) at the same
seed design with the same mapping. Exactly one of them, the total run,
holds several objectives; every other run holds a single objective of
the total run. The script finds out from each run's case file which
objective it holds, in any order. Reads (read-only) iteration 0 of
sensitivity_0 (field dFd_design_indicator) of every run, design_0 (field
design_indicator) of the total run, and the case files.

The sensitivity is linear in the objectives, so the total is the sum of
the parts, each with its weight in the total run. A single-objective run
whose weight differs from the total run's is rescaled to that weight. If
every objective of the total run has its own run, the additivity of the
parts is checked; if exactly one has none, its part is obtained as the
total minus the other parts (and the additivity cannot be checked).

It prints, over the fluid (design = 0) of the design domain, the median
and 90 % quantile of |g| of each part and the volume fraction where it is
negative (wants material). Then, for pairs of factors on the viscous- and
Brinkman-dissipation weights (the other weights unchanged), it prints
how much of the fluid is free to gain material, how much of the solid is
free to lose it, how dominant the largest free value is, and the median
|g| of the free fluid.
"""
import argparse

import numpy as np

import sensitivity_tools as st

LABELS = {"scalar_mixing": "mixing", "viscous_dissipation": "viscous",
          "brinkman_dissipation": "Brinkman"}
SCANNED = ("viscous_dissipation", "brinkman_dissipation")
DEFAULT_FACTORS = ("1:1,1:0.3,1:0.1,1:0.03,1:0.01,1:0.003,1:0,"
                   "0.1:0.1,0.01:0.01,0:1,0:0.01,0:0")


def label(kind):
    """Short label of an objective type."""
    return LABELS.get(kind, kind)


def load(run, k=0):
    """Sensitivity of iteration k of a run, in double precision."""
    return st.Series(run, "sensitivity").read(
        k, "dFd_design_indicator").astype(np.float64)


def classify(runs):
    """Split the runs into the total run and single-objective runs.

    @return (total run, its case, its weights), dict objective type ->
            (run, weight in that run)
    """
    total, singles = None, {}
    for r in runs:
        _, case = st.load_case(r)
        w = st.objective_weights(case)
        if len(w) > 1:
            if total is not None:
                raise SystemExit(f"two runs with several objectives: "
                                 f"{total[0]} and {r}")
            total = (r, case, w)
        elif len(w) == 1:
            kind, wt = next(iter(w.items()))
            if kind in singles:
                raise SystemExit(f"two runs hold only {kind}: "
                                 f"{singles[kind][0]} and {r}")
            singles[kind] = (r, wt)
        else:
            raise SystemExit(f"{r}: the case has no objective")
    if total is None:
        raise SystemExit("no run with several objectives (the total run)")
    for kind, (r, _) in singles.items():
        if kind not in total[2]:
            raise SystemExit(f"{r} holds {kind}, which the total run "
                             f"{total[0]} does not have")
    return total, singles


def parse_factors(text):
    """Parse "av:ab,av:ab,..." into a list of float pairs."""
    out = []
    for item in text.split(","):
        av, ab = item.split(":")
        out.append((float(av), float(ab)))
    return out


def main():
    """Parse the arguments, split the sensitivity and scan the weights."""
    ap = argparse.ArgumentParser(
        description="Split the seed sensitivity by objective and report "
        "what each choice of weights frees.")
    ap.add_argument("runs", nargs="+", metavar="RUN",
                    help="run directories, in any order: one total run "
                    "and single-objective runs")
    ap.add_argument("--factors", default=DEFAULT_FACTORS,
                    help="comma-separated pairs VISC:BRINK of factors on "
                    "the viscous- and Brinkman-dissipation weights of "
                    f"the total run (default {DEFAULT_FACTORS})")
    a = ap.parse_args()
    factors = parse_factors(a.factors)

    (tot_run, case, tot_w), singles = classify(a.runs)
    for kind in SCANNED:
        if kind not in tot_w:
            raise SystemExit(f"the total run has no {kind} objective, "
                             "so its weight cannot be scanned")
    print(f"# {'total':8s} {tot_run}: " + ", ".join(
        f"{o['type']} x {o['weight']}"
        for o in case["optimization"]["objectives"]))
    scale = {}
    for kind in tot_w:
        if kind in singles:
            r, w = singles[kind]
            scale[kind] = tot_w[kind] / w
            note = ("" if scale[kind] == 1.0 else
                    f"; rescaled x {scale[kind]:.6g} to the weight of the "
                    "total run")
            print(f"# {label(kind):8s} {r}: {kind} x {w}{note}")

    lx = st.polynomial_order(case) + 1
    dom = st.design_domain(case)
    des = st.Series(tot_run, "design")
    nel, vol, M, lo, hi = st.geometry(des, lx, dom)
    Wt = st.Weights(lx, vol)
    x = des.read(0, "design_indicator").astype(np.float64)
    G = load(tot_run)
    parts = {kind: scale[kind] * load(singles[kind][0])
             for kind in tot_w if kind in singles}
    missing = [kind for kind in tot_w if kind not in singles]
    res = G.copy()
    for g in parts.values():
        res -= g
    if not missing:
        names = " - ".join(label(kind) for kind in tot_w)
        print(f"# additivity: largest |total - {names}| = "
              f"{np.abs(res[M]).max():.3e} against largest |total| "
              f"{np.abs(G[M]).max():.3e} (relative "
              f"{np.abs(res[M]).max() / np.abs(G[M]).max():.2e})")
    elif len(missing) == 1:
        kind = missing[0]
        parts[kind] = res
        others = " - ".join(label(o) for o in tot_w if o != kind)
        print(f"# no {label(kind)}-only run: {label(kind)} part = total - "
              f"{others} (additivity not checked)")
    else:
        raise SystemExit("no single-objective run for "
                         + ", ".join(missing)
                         + "; at most one part can be obtained by "
                         "subtraction")
    del res
    parts = {kind: parts[kind] for kind in tot_w}

    fl = M & (x <= 0.0)
    so = M & (x >= 1.0)
    Vf, Vs = Wt.sum(fl), Wt.sum(so)
    fi = np.flatnonzero(fl)
    fw = Wt.of(fi)
    print(f"# fluid volume in the design domain {Vf:.4f}, solid {Vs:.4f}")
    print("\n## the parts over the fluid of the design domain "
          "(volume-weighted)")
    print("  part        median |g|   90 % |g|    volume fraction negative "
          "(wants material)")
    for lab, g in [(label(k_), g_) for k_, g_ in parts.items()] + \
            [("total", G)]:
        q = st.wquant(np.abs(g[fi]), fw, np.array([0.5, 0.9]))
        print(f"  {lab:9s}  {q[0]:10.3e}  {q[1]:10.3e}   "
              f"{fw[g[fi] < 0].sum() / fw.sum():.4f}")

    fixed = [kind for kind in parts if kind not in SCANNED]
    print("\n## what a choice of weights frees (factors multiply the "
          "weights of the total run; "
          + ", ".join(label(k_) for k_ in fixed) + " weight unchanged)")
    print("  viscous x  Brinkman x | fluid free to gain material | solid "
          "free to lose it | largest free |g| / free-set median | median "
          "|g| of the free fluid")
    rest = sum(parts[kind] for kind in fixed) if fixed else 0.0
    Gv, Gb = parts["viscous_dissipation"], parts["brinkman_dissipation"]
    for av, ab in factors:
        g = rest + av * Gv + ab * Gb
        S = -g
        frozen = ((x >= 1.0) & (S > 0)) | ((x <= 0.0) & (S < 0))
        free = M & ~frozen & (g != 0)
        idx = np.flatnonzero(free)
        w = Wt.of(idx)
        aa = np.abs(g[idx])
        med = st.wquant(aa, w, np.array([0.5]))[0]
        ff = free & fl
        fmed = (st.wquant(np.abs(g[ff]), Wt.of(np.flatnonzero(ff)),
                          np.array([0.5]))[0]
                if ff.any() else float("nan"))
        print(f"  {av:8g}  {ab:9g} | {Wt.sum(ff) / Vf:26.4f} | "
              f"{Wt.sum(free & so) / Vs:20.4f} | {aa.max() / med:33.1f} | "
              f"{fmed:.3e}")


if __name__ == "__main__":
    main()
