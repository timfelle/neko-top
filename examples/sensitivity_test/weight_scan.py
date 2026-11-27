#!/usr/bin/env python3
"""Seed-design sensitivity split by objective, and what each weight frees.

Question: which objective sets the sensitivity of the seed design, and
how would other weights of the viscous- and Brinkman-dissipation
objectives change how much of the design is free to move?

Usage:
    weight_scan.py RUN [RUN ...] [--factors 1:1,1:0.1,0:0]
                   [--check RUN [--check RUN ...]]

Every RUN is an evaluation (max_iterations: 0 is enough) at the same
seed design with the same mapping. Exactly one of them, the total run,
holds several objectives; every other run holds a single objective of
the total run. Only active objectives count: an objective whose weight
at iteration 0 is zero contributes nothing, so a single-objective run
may list the others at weight 0, and such an objective of the total run
is not part of the total (the viscous- and Brinkman-dissipation weights
of the total run must not be zero, since they are scanned). An entry at
weight 0 is ignored whatever its type; two active entries of one type
stop the script, which splits the sensitivity by type. The script
finds out from each run's case file which objective it holds, in any
order. Reads (read-only) iteration 0 of sensitivity_0 (field
dFd_design_indicator) of every run, design_0 (field design_indicator) of
the total run, and the case files; also, if present, design 1 and
optimization_data.csv of the total run; and the same of every --check
run.

The sensitivity is linear in the objectives, so the total is the sum of
the parts, each with its weight in the total run. A single-objective run
whose weight differs from the total run's is rescaled to that weight. If
every objective of the total run has its own run, the additivity of the
parts is checked; if exactly one has none, its part is obtained as the
total minus the other parts (and the additivity cannot be checked).

It prints, over the fluid (design = 0) of the design domain, the median
and 90 % quantile of |g| of each part and the volume fraction where it is
negative (wants material). If the total run stores design 1 and its
optimization_data.csv, it prints each part's first-order prediction of
that step against the part's weighted change in the log. Then, for pairs
of factors on the viscous- and Brinkman-dissipation weights (the other
weights unchanged), it prints how much of the fluid is free to gain
material, how much of the solid is free to lose it, how dominant the
largest free value is, and the median |g| of the free fluid.

--check RUN (repeatable, not one of the RUNs) tests the scan against a
run made with other weights. The run must have the total run's mesh,
iteration-0 design (to float32 round-off), design mapping and design
domain, every objective active in it must be a part, and the file of
its iteration-0 sensitivity (symbolic links followed) must not be that
of a RUN or of another check run, or the script stops before it prints
anything. Its sensitivity is
predicted as the sum over the parts of (its weight / the total run's
weight) part and compared with the stored one node by node and in the
quantities of a scan row; if the run stores design 1 and its
optimization_data.csv, its own first step is split by objective as
above. The sensitivity at iteration 0 is linear in
the weights, so the agreement there tests the bookkeeping and the
additivity of the runs, not the physics; the step shows whether the
seed-design prediction carries over to the run's first step.
"""
import argparse
import os

import numpy as np

import sensitivity_tools as st

LABELS = {"scalar_mixing": "mixing", "viscous_dissipation": "viscous",
          "brinkman_dissipation": "Brinkman"}
SCANNED = ("viscous_dissipation", "brinkman_dissipation")
DEFAULT_FACTORS = ("1:1,1:0.3,1:0.1,1:0.03,1:0.01,1:0.003,1:0,"
                   "0.1:0.1,0.01:0.01,0:1,0:0.01,0:0")
# Largest difference of two iteration-0 designs taken as the same seed:
# float32 round-off of a value in [0, 1] (whose spacing at 1 is 1.2e-7).
DESIGN_TOL = 1e-6


def label(kind):
    """Short label of an objective type."""
    return LABELS.get(kind, kind)


def load(run, k=0):
    """Sensitivity of iteration k of a run, in double precision."""
    return st.Series(run, "sensitivity").read(
        k, "dFd_design_indicator").astype(np.float64)


def objectives_text(case):
    """The objectives of a case with their weights, for the header."""
    out = []
    for o in st.objective_entries(case):
        w, notes = st.weight_text(case, o)
        name = f" \"{o['name']}\"" if "name" in o else ""
        out.append(f"{o['type']}{name} x {w}"
                   + (f" ({'; '.join(notes)})" if notes else ""))
    return ", ".join(out)


def classify(runs):
    """Split the runs into the total run and single-objective runs.

    Only the active objectives (non-zero weight at iteration 0) count: a
    run may list others at weight 0, of any type.

    @return (total run, its case, its active weights), dict objective
            type -> (run, weight in that run, its case)
    """
    total, singles = None, {}
    for r in runs:
        _, case = st.load_case(r)
        try:
            w = st.active_weights(case)
        except SystemExit as e:
            raise SystemExit(f"{r}: {e}")
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
            singles[kind] = (r, wt, case)
        elif st.objective_entries(case):
            raise SystemExit(f"{r}: every objective of the case has "
                             "weight 0 at iteration 0")
        else:
            raise SystemExit(f"{r}: the case has no objective")
    if total is None:
        raise SystemExit("no run with several objectives (the total run)")
    for kind, (r, _, _) in singles.items():
        if kind in st.listed_types(total[1]) and kind not in total[2]:
            raise SystemExit(f"{r} holds {kind}, which has weight 0 at "
                             f"iteration 0 in the total run {total[0]}")
        if kind not in total[2]:
            raise SystemExit(f"{r} holds {kind}, which the total run "
                             f"{total[0]} does not have")
    return total, singles


TOTAL_STEP = dict(
    who="total run", what="the total sensitivity",
    weights="with the parts at the weights of the total run, whatever the "
    "header rescales or the scan below multiplies")


def step_prediction(run, case, des, x, G, parts, Wt, residual,
                    text=TOTAL_STEP, scale=None):
    """Print each part's first-order change of a run's own step 0 -> 1.

    A part's predicted change is the sum over the design domain of
    B part (x_1 - x_0), with the run's own design change and the parts at
    the run's weights; the actual one is its weighted change in the run's
    optimization_data.csv, at the weights of row 0. The sums run over
    every local node: Neko-TOP sets the design and the sensitivity to
    zero outside its design domain, so they are the sums over that
    domain, whatever its point zone.

    @param run, case, des The run, its case and its design series.
    @param x Its design at iteration 0.
    @param G Its sensitivity.
    @param parts Dict objective type -> part, at the run's weights once
           multiplied by scale.
    @param residual What the difference of G and the sum of the parts is.
    @param text Wording: who (the run), what (G), weights (of the parts).
    @param scale Dict objective type -> factor on its part (default 1).
    """
    head = ("\n## first-order prediction against the actual change of the "
            f"{text['who']}'s step 0 -> 1")
    if not des.has(1):
        print(head + f": not available (the {text['who']} stores no "
              "design 1)")
        return
    got, why = st.logged_change(st.optimization_log(run), 0)
    if got is None:
        print(head + f": not available ({why})")
        return
    dx = des.read(1, "design_indicator").astype(np.float64) - x
    pred = {kind: (scale or {}).get(kind, 1.0) * Wt.sum(g * dx)
            for kind, g in parts.items()}
    p_tot = Wt.sum(G * dx)
    del dx
    # the log holds the objectives in the order of the case entries
    entries = st.objective_entries(case)
    logged = got["parts"]
    act = {}
    if len(logged) == len(entries) and all(
            p[0] == e.get("name", st.DEFAULT_NAMES.get(e["type"], p[0]))
            for p, e in zip(logged, entries)):
        active = st.active_objectives(case)
        for kind in parts:
            j = next(i for i, e in enumerate(entries) if e is active[kind])
            act[kind] = logged[j][3]

    def row(lab, p, a):
        """One line: predicted, actual and their ratio."""
        r = f"{a / p:10.3f}" if a is not None and p else "       n/a"
        a = f"{a:+.4e}" if a is not None else "not matched"
        print(f"  {lab:12s}  {p:+.4e}  {a:11s}  {r}")
    print(head + " (sum over the design domain of B part (x_1 - x_0), "
          f"{text['weights']}; actual: the weighted changes in its "
          "optimization_data.csv, at the weights of row 0)")
    print("  part          predicted    actual       actual / predicted")
    for kind in parts:
        row(label(kind), pred[kind], act.get(kind))
    row("sum of parts", sum(pred.values()),
        sum(act.values()) if len(act) == len(parts) else None)
    row("total", p_tot, got["total"])
    if len(act) < len(parts):
        print("  (the objective columns of optimization_data.csv do not "
              "match the case's objectives, so the parts' actual changes "
              "are not shown)")
    if got["weights_change"]:
        print(f"  (a weight changes between rows 0 and 1, so the "
              f"{st.TOTAL} change includes that change)")
    if got["params_change"]:
        print("  (a continued parameter changes between rows 0 and 1: "
              + ", ".join(f"{n} {a:g} -> {b:g}"
                          for n, a, b in got["params_change"])
              + f"; the {st.TOTAL} change and the objectives' changes "
              "include its effect at a fixed design)")
    print(f"  check: sum of the part predictions {sum(pred.values()):+.4e} "
          f"against the prediction from {text['what']} "
          f"{p_tot:+.4e}, difference "
          f"{sum(pred.values()) - p_tot:+.2e} ({residual})")


def freed(g, x, M, fl, so, Wt):
    """What a sensitivity frees: the quantities of a scan row.

    @param g Sensitivity.
    @param x Design.
    @param M Design-domain mask; fl, so its fluid and solid.
    @param Wt Volume weights.
    @return fluid volume fraction free to gain material, solid volume
            fraction free to lose it, largest free |g| over the free-set
            median (None if nothing is free), median |g| of the free fluid
            (nan if there is none)
    """
    S = -g
    frozen = ((x >= 1.0) & (S > 0)) | ((x <= 0.0) & (S < 0))
    free = M & ~frozen & (g != 0)
    idx = np.flatnonzero(free)
    ff = free & fl
    out = (Wt.sum(ff) / Wt.sum(fl), Wt.sum(free & so) / Wt.sum(so))
    if not idx.size:
        return out + (None, float("nan"))
    aa = np.abs(g[idx])
    med = st.wquant(aa, Wt.of(idx), np.array([0.5]))[0]
    fmed = (st.wquant(np.abs(g[ff]), Wt.of(np.flatnonzero(ff)),
                      np.array([0.5]))[0]
            if ff.any() else float("nan"))
    return out + (aa.max() / med, fmed)


def freed_row(lead, q):
    """A scan row: lead, then the quantities q of freed()."""
    row = f"{lead}{q[0]:26.4f} | {q[1]:20.4f} | "
    if q[2] is None:
        # e.g. every weight at zero: g vanishes, nothing is free
        return row + f"{'n/a':>33s} | n/a (nothing is free)"
    return row + f"{q[2]:33.1f} | {q[3]:.3e}"


def mapping_difference(m0, m1):
    """How two design mappings differ, as text (None if they do not)."""
    if m0 == m1:
        return None
    t0, t1 = [m.get("type") for m in m0], [m.get("type") for m in m1]
    if t0 != t1:
        return f"steps {t0} against {t1}"
    return "; ".join(f"{a['type']} {key} {a.get(key)} against {b.get(key)}"
                     for a, b in zip(m0, m1)
                     for key in sorted(set(a) | set(b))
                     if a.get(key) != b.get(key))


def design_domain_of(case):
    """The design domain as Neko-TOP reads it, for comparing two cases.

    Neko-TOP masks the design only for domain type point_zone (the
    default is the full mesh); the zone is compared by its definition,
    not its name.
    """
    d = case["optimization"]["design"].get("domain", {})
    if d.get("type", "full") != "point_zone":
        return "the full mesh"
    z = st.point_zone(case, d.get("zone_name"))
    return ({k: v for k, v in z.items() if k != "name"} if z else
            f"the undefined point zone {d.get('zone_name')}")


def sensitivity_data(run):
    """Real path of the file read for a run's iteration-0 sensitivity.

    As Series.read: the step file if it exists, else the .vtkhdf.
    """
    ser = st.Series(run, "sensitivity")
    p = ser.step_file(0)
    return os.path.realpath(p if os.path.exists(p) else ser.f)


def check_setup(r, case, tot_w, des, x, seen):
    """Test the preconditions of a check run; stop if one fails.

    The run must have the total run's mesh, iteration-0 design, design
    mapping and design domain, and every objective active in it must be
    one of the total run's, each of which is a part (from its own run or
    by subtraction). The file of its iteration-0 sensitivity (symbolic
    links followed) must not be that of a RUN or of an earlier check run,
    which would agree by construction.

    @param seen Dict real path of an iteration-0 sensitivity file -> what
           it belongs to; the check run's is added.
    @return its case, its active weights, how its design compares
    """
    path = sensitivity_data(r)
    if path in seen:
        raise SystemExit(f"check run {r}: its iteration-0 sensitivity file "
                         f"{path} is "
                         f"that of {seen[path]}, so it would agree by "
                         "construction; a check run must be a run of its "
                         "own")
    seen[path] = f"the earlier check run {r}"
    _, cc = st.load_case(r)
    cdes, csen = st.Series(r, "design"), st.Series(r, "sensitivity")
    n0 = st.polynomial_order(case)
    n1 = st.polynomial_order(cc)
    if (cdes.npt, csen.npt, n1) != (des.npt, des.npt, n0):
        raise SystemExit(f"check run {r}: {cdes.npt} local nodes (design), "
                         f"{csen.npt} (sensitivity) of order {n1}, against "
                         f"the total run's {des.npt} of order {n0}; it must "
                         "have the same mesh")
    why = mapping_difference(
        case["optimization"]["design"].get("mapping", []),
        cc["optimization"]["design"].get("mapping", []))
    if why:
        raise SystemExit(f"check run {r}: its design mapping differs from "
                         f"the total run's ({why}, total run first)")
    d0, d1 = design_domain_of(case), design_domain_of(cc)
    if d0 != d1:
        raise SystemExit(f"check run {r}: its design domain differs from "
                         f"the total run's ({d0} against {d1}, total run "
                         "first)")
    xc = cdes.read(0, "design_indicator").astype(np.float64)
    dd = np.abs(xc - x)
    if dd.max() > DESIGN_TOL:
        raise SystemExit(f"check run {r}: its iteration-0 design differs "
                         f"from the total run's by up to {dd.max():.3e} at "
                         f"{int((dd > DESIGN_TOL).sum())} local nodes; it "
                         "must start from the same seed design")
    same = ("identical" if not dd.any() else
            f"equal to within {dd.max():.1e} (float32 round-off)")
    del dd
    try:
        cw = st.active_weights(cc)
    except SystemExit as e:
        raise SystemExit(f"check run {r}: {e}")
    if not cw:
        raise SystemExit(f"check run {r}: every objective of the case has "
                         "weight 0 at iteration 0")
    for kind in cw:
        if kind not in tot_w:
            raise SystemExit(f"check run {r}: {kind} is active in it, but "
                             f"the scan has no {kind} part (its parts: "
                             + ", ".join(tot_w) + ")")
    return cc, cw, same


def check_run(r, cc, cw, same, tot_w, parts, x, M, fl, so, Wt):
    """Test the parts against a run made with other weights.

    The run's sensitivity is predicted as g_pred = sum over the parts of
    (its weight / the total run's weight) part, and compared node by node,
    in what it frees, and over the run's own step 0 -> 1. check_setup has
    tested its preconditions.
    """
    cdes = st.Series(r, "design")
    xc = cdes.read(0, "design_indicator").astype(np.float64)
    fac = {kind: cw.get(kind, 0.0) / tot_w[kind] for kind in parts}
    g = load(r)
    g_pred = sum(f * parts[kind] for kind, f in fac.items())
    dev = float(np.abs(g - g_pred).max())
    ref = float(np.abs(g).max())

    print(f"\n## check run {r}: {objectives_text(cc)}")
    print("  factors on the parts (check-run weight / total-run weight): "
          + ", ".join(f"{label(k)} {f:.6g}" for k, f in fac.items())
          + "; same mesh, design mapping and design domain; "
          f"iteration-0 design {same}")
    print("  node-wise: largest |g_check - g_pred| over all nodes "
          f"{dev:.3e} against largest |g_check| {ref:.3e} (relative "
          f"{dev / ref:.2e}), g_pred = sum of factor x part")
    print("  what it frees, predicted from g_pred and actual from the "
          "check run's sensitivity:")
    print(f"  {'':19s} | fluid free to gain material | solid free to lose "
          "it | largest free |g| / free-set median | median |g| of the "
          "free fluid")
    print(freed_row(f"  {'predicted':19s} | ",
                    freed(g_pred, x, M, fl, so, Wt)))
    del g_pred
    print(freed_row(f"  {'actual':19s} | ", freed(g, x, M, fl, so, Wt)))
    step_prediction(
        r, cc, cdes, xc, g, {k: parts[k] for k, f in fac.items() if f},
        Wt, "the integral of g_pred - g_check over the step",
        text=dict(who="check run", what="the check run's sensitivity",
                  weights="with the parts times their factors, at the "
                  "check run's weights"), scale=fac)


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
    ap.add_argument("--check", action="append", default=[], metavar="RUN",
                    help="a run made with other weights from the total "
                    "run's mesh, seed design, mapping and design domain, "
                    "and not one of the RUNs; its sensitivity is "
                    "predicted from the "
                    "parts and compared node by node, in what it frees "
                    "and, if it stores design 1 and its "
                    "optimization_data.csv, over its first step "
                    "(repeatable)")
    a = ap.parse_args()
    factors = parse_factors(a.factors)

    (tot_run, case, tot_w), singles = classify(a.runs)
    for kind in SCANNED:
        if kind not in st.listed_types(case):
            raise SystemExit(f"the total run has no {kind} objective, "
                             "so its weight cannot be scanned")
        if kind not in tot_w:
            raise SystemExit(f"{kind} has weight 0 at iteration 0 in the "
                             f"total run {tot_run}, so it is not part of "
                             "the total and factors on its weight scan "
                             "nothing; give it a non-zero weight")
    lx = st.polynomial_order(case) + 1
    dom = st.design_domain(case)
    des = st.Series(tot_run, "design")
    nel, vol, M, lo, hi = st.geometry(des, lx, dom)
    Wt = st.Weights(lx, vol)
    x = des.read(0, "design_indicator").astype(np.float64)
    # the check runs' preconditions, before anything is printed
    seen = {sensitivity_data(r): f"the RUN {r}" for r in a.runs}
    checks = [(r,) + check_setup(r, case, tot_w, des, x, seen)
              for r in a.check]

    print(f"# {'total':8s} {tot_run}: " + objectives_text(case))
    scale = {}
    for kind in tot_w:
        if kind in singles:
            r, w, scase = singles[kind]
            scale[kind] = tot_w[kind] / w
            note = ("" if scale[kind] == 1.0 else
                    f"; rescaled x {scale[kind]:.6g} to the weight of the "
                    "total run")
            print(f"# {label(kind):8s} {r}: {objectives_text(scase)}"
                  f"{note}")

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
    step_prediction(tot_run, case, des, x, G, parts, Wt,
                    "zero by construction, as one part is the total minus "
                    "the others" if missing else "the additivity residual")

    fixed = [kind for kind in parts if kind not in SCANNED]
    print("\n## what a choice of weights frees (factors multiply the "
          "weights of the total run"
          + ("; " + ", ".join(label(k_) for k_ in fixed)
             + " weight unchanged" if fixed else "") + ")")
    print("  viscous x  Brinkman x | fluid free to gain material | solid "
          "free to lose it | largest free |g| / free-set median | median "
          "|g| of the free fluid")
    rest = sum(parts[kind] for kind in fixed) if fixed else 0.0
    Gv, Gb = parts["viscous_dissipation"], parts["brinkman_dissipation"]
    for av, ab in factors:
        print(freed_row(f"  {av:8g}  {ab:9g} | ",
                        freed(rest + av * Gv + ab * Gb, x, M, fl, so, Wt)))

    for r, cc, cw, same in checks:
        check_run(r, cc, cw, same, tot_w, parts, x, M, fl, so, Wt)


if __name__ == "__main__":
    main()
