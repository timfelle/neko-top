#!/usr/bin/env python3
"""What the fluid's sensitivity is made of, and where it wants material.

Question: is the sensitivity on the fluid of the design domain the
explicit Brinkman-dissipation derivative, where is the fluid whose
sensitivity is negative (free to gain material), what did the design do
there, and is the forward flow steady between iterations?

Usage:
    fluid_sensitivity.py RUN_DIR [--case FILE] [--iters 0,19]
                         [--steady 0,1] [--box x0,x1,y0,y1,z0,z1]

Reads (read-only) from RUN_DIR: design_0.vtkhdf + design_0.data/ (fields
design_indicator and PDE_filter_mapping, written with verbose_design),
sensitivity_0.vtkhdf + sensitivity_0.data/ (field dFd_design_indicator),
forward_fields_0.vtkhdf + forward_fields_0.data/ (field Velocity), and the
case file (or pass --case). Reads in chunks of elements; the memory stays
below about 1.5 GB at 256x64x64 order 3.

The block (the seed of the design) is the box of the point zone of the
design's initial_distribution, or --box. Distances to it are measured in
element widths (the x extent of the first element).

For each iteration it prints, over the fluid (design = 0) of the design
domain:
  - the largest sensitivity and the explicit Brinkman-dissipation
    derivative 0.5 w_B / V * RAMP'(0) * |u|^2 at that node;
  - volume-weighted quantiles of the ratio of the sensitivity to that
    explicit estimate, at nodes faster than 0.3 (a 1/8 sample), overall
    and by distance to the block;
  - the fluid volume, and the share of it with negative sensitivity, by
    distance to the block;
  - where the fluid with negative sensitivity is, how fast the flow is
    there, and what the design is there at the last listed iteration;
and finally the relative L2 difference of the forward velocity between
the two iterations of --steady (skipped with a note if --steady is not
given and the iteration after the first listed one is not stored, as in
a run that stores a single iteration).

w_B is the weight of the active brinkman_dissipation entry at each
iteration, stepped through its continuation array if the weight is
given as an array; entries at weight 0 are ignored, and two active
entries stop the script. Where w_B is zero (or no entry is active), the
comparison with the explicit estimate is marked not applicable and the
rest is printed.
"""
import argparse

import h5py
import numpy as np

import sensitivity_tools as st

# Fluid nodes slower than this are left out of the ratio quantiles.
MIN_SPEED = 0.3
# Every SAMPLE-th fluid node enters the ratio quantiles.
SAMPLE = 8
# Bins of the distance to the block, in element widths.
DIST_BINS = np.array([0, 1, 2, 4, 8, 16, 1e9])


def block_box(case, box):
    """Lower and upper corner of the block: --box or the seed zone."""
    if box:
        b = [float(t) for t in box.split(",")]
        if len(b) != 6:
            raise SystemExit("--box needs six values x0,x1,y0,y1,z0,z1")
        return np.array(b[0::2]), np.array(b[1::2])
    init = case["optimization"]["design"].get("initial_distribution", {})
    zone = (st.point_zone(case, init["zone_name"])
            if init.get("type") == "point_zone" and "zone_name" in init
            else None)
    keys = ("x_bounds", "y_bounds", "z_bounds")
    if zone is None or not all(k in zone for k in keys):
        raise SystemExit(
            "the design has no box point zone as its initial distribution, "
            "so the block is unknown; pass --box x0,x1,y0,y1,z0,z1")
    return (np.array([zone[k][0] for k in keys]),
            np.array([zone[k][1] for k in keys]))


def scan_iteration(run, k, k_last, nel, n3, w3, dom, blo, bhi, fmax, q,
                   wB):
    """Chunked pass over iteration k; returns the sums and samples.

    @return None if the design domain holds no fluid at iteration k.
    """
    des = st.Series(run, "design")
    sen = st.Series(run, "sensitivity")
    fwd = st.Series(run, "forward_fields")
    V = 0.0
    acc = dict(fluid=0.0, fluid_neg=0.0)
    best = (-np.inf, None)
    samp = {k_: [] for k_ in ("g", "E", "w", "d", "u", "x", "y", "z")}
    neg = {k_: [] for k_ in ("g", "w", "d", "x", "y", "z", "u", "xl")}
    fl_by = np.zeros(len(DIST_BINS) - 1)
    neg_by = np.zeros(len(DIST_BINS) - 1)
    h_el = None
    with h5py.File(des.f, "r") as hm:
        pts = hm["VTKHDF/Points"]
        for e0, e1, s in st.element_chunks(nel, n3, 16384):
            p = pts[s]
            if h_el is None:
                pe = p[:n3]
                h_el = float(pe[:, 0].max() - pe[:, 0].min())
            B = st.chunk_mass(p, n3, w3)
            V += B.sum()
            x = des.read(k, "design_indicator", s.start, s.stop) \
                .astype(np.float64)
            rf = des.read(k, "PDE_filter_mapping", s.start, s.stop) \
                .astype(np.float64)
            g = sen.read(k, "dFd_design_indicator", s.start, s.stop) \
                .astype(np.float64)
            u2 = (fwd.read(k, "Velocity", s.start, s.stop)
                  .astype(np.float64) ** 2).sum(axis=1)
            fl = st.zone_mask(p, dom) & (x <= 0.0)
            if not fl.any():
                continue
            dist = np.linalg.norm(
                np.maximum(0, np.maximum(blo - p, p - bhi)), axis=1) / h_el
            acc["fluid"] += B[fl].sum()
            ng = fl & (g < 0)
            acc["fluid_neg"] += B[ng].sum()
            ib = np.digitize(dist, DIST_BINS) - 1
            np.add.at(fl_by, ib[fl], B[fl])
            np.add.at(neg_by, ib[ng], B[ng])
            j = np.argmax(np.where(fl, g, -np.inf))
            if g[j] > best[0]:
                best = (float(g[j]),
                        (p[j].copy(), float(np.sqrt(u2[j])), float(rf[j])))
            # explicit Brinkman-dissipation derivative, unfiltered
            # estimate; divided by the volume later
            E = 0.5 * wB * st.ramp_slope(rf, fmax, q) * u2
            sel = np.flatnonzero(fl)[::SAMPLE]
            for key, arr in (("g", g), ("E", E), ("w", B), ("d", dist),
                             ("u", np.sqrt(u2)), ("x", p[:, 0]),
                             ("y", p[:, 1]), ("z", p[:, 2])):
                samp[key].append(arr[sel])
            seln = np.flatnonzero(ng)
            xl = des.read(k_last, "design_indicator", s.start, s.stop) \
                .astype(np.float64)
            for key, arr in (("g", g), ("w", B), ("d", dist),
                             ("x", p[:, 0]), ("y", p[:, 1]),
                             ("z", p[:, 2]), ("u", np.sqrt(u2)),
                             ("xl", xl)):
                neg[key].append(arr[seln])
    if best[1] is None:
        return None
    S = {k_: np.concatenate(v) for k_, v in samp.items()}
    N = {k_: np.concatenate(v) for k_, v in neg.items()}
    S["E"] /= V
    return V, acc, best, S, N, fl_by, neg_by


def print_iteration(k, k_last, V, acc, best, S, N, fl_by, neg_by, blo, bhi,
                    fmax, q, wB):
    """Print the findings of one iteration."""
    wq = st.wquant
    na = f"not applicable: Brinkman-dissipation weight 0 at iteration {k}"
    print(f"\n## iteration {k}: mesh volume {V:.4f}; fluid of the design "
          f"domain {acc['fluid']:.4f}; of it with negative sensitivity "
          f"{acc['fluid_neg'] / acc['fluid']:.5f}")
    (pb, ub, rb) = best[1]
    est = (f"{0.5 * wB / V * st.ramp_slope(0.0, fmax, q) * ub ** 2:.2f}"
           if wB else na)
    print(f"  largest sensitivity on the fluid: {best[0]:.2f} at "
          f"({pb[0]:.4f}, {pb[1]:.4f}, {pb[2]:.4f}), speed there "
          f"{ub:.3f}, filtered design {rb:.2e}; explicit estimate "
          f"0.5 w_B/V slope(0) |u|^2 = {est}")
    ok = S["u"] > MIN_SPEED
    if not wB:
        print(f"  fluid nodes with speed above {MIN_SPEED:g}: sensitivity "
              "/ explicit Brinkman-dissipation estimate, overall and by "
              f"distance to the block, {na}")
    else:
        r = S["g"][ok] / S["E"][ok]
        qs = wq(r, S["w"][ok], np.array([0.05, 0.25, 0.5, 0.75, 0.95]))
        cc = np.corrcoef(S["g"][ok], S["E"][ok])[0, 1]
        print(f"  fluid nodes with speed above {MIN_SPEED:g} (1/{SAMPLE} "
              f"sample, {ok.sum()} nodes): sensitivity / explicit "
              "Brinkman-dissipation estimate, volume-weighted quantiles "
              "5/25/50/75/95 % = " + " ".join(f"{v:.3f}" for v in qs)
              + f"; correlation {cc:.4f}")
    for lab, m in (("within 2 elements of the block", S["d"] <= 2),
                   ("2 to 8 elements", (S["d"] > 2) & (S["d"] <= 8)),
                   ("farther", S["d"] > 8)):
        mm = ok & m
        if wB and mm.sum() > 10:
            qq = wq(S["g"][mm] / S["E"][mm], S["w"][mm],
                    np.array([0.25, 0.5, 0.75]))
            print(f"    {lab:32s}: 25/50/75 % = "
                  + " ".join(f"{v:.3f}" for v in qq))
    print("  fluid volume by distance to the block (elements), and the "
          "share of it with negative sensitivity:")
    for i in range(len(DIST_BINS) - 1):
        if fl_by[i] > 0:
            print(f"    {DIST_BINS[i]:g} to {DIST_BINS[i + 1]:g}: volume "
                  f"{fl_by[i]:.5f}, negative share "
                  f"{neg_by[i] / fl_by[i]:.5f}")
    if not len(N["g"]):
        return
    wn = N["w"]
    q3 = np.array([0.05, 0.5, 0.95])
    print(f"  the fluid with negative sensitivity ({len(N['g'])} local "
          f"nodes, volume {wn.sum():.6f}):")
    print("    |g| quantiles 50/90/99 %: " + " ".join(
        f"{v:.3e}" for v in wq(-N["g"], wn, np.array([0.5, 0.9, 0.99])))
        + f"; most negative {N['g'].min():.3e}")
    print("    position: x 5/50/95 % = "
          + " ".join(f"{v:.3f}" for v in wq(N["x"], wn, q3))
          + "; y " + " ".join(f"{v:.3f}" for v in wq(N["y"], wn, q3))
          + "; z " + " ".join(f"{v:.3f}" for v in wq(N["z"], wn, q3)))
    up = N["x"] < blo[0]
    down = N["x"] > bhi[0]
    print(f"    upstream of the block {wn[up].sum() / wn.sum():.3f}, "
          f"alongside {wn[~up & ~down].sum() / wn.sum():.3f}, downstream "
          f"{wn[down].sum() / wn.sum():.3f}; speed there, median "
          f"{wq(N['u'], wn, np.array([0.5]))[0]:.3f}")
    print(f"    design there at iteration {k_last}: volume-weighted mean "
          f"{(wn * N['xl']).sum() / wn.sum():.4f}, 90 % quantile "
          f"{wq(N['xl'], wn, np.array([0.9]))[0]:.4f}, largest "
          f"{N['xl'].max():.4f}; volume share above 0.01: "
          f"{wn[N['xl'] > 0.01].sum() / wn.sum():.4f}, above 0.1: "
          f"{wn[N['xl'] > 0.1].sum() / wn.sum():.4f}")


def steadiness(run, ka, kb, nel, n3):
    """Print the velocity difference between forward snapshots ka, kb."""
    fwd = st.Series(run, "forward_fields")
    for k in (ka, kb):
        if not fwd.has(k):
            raise SystemExit(f"missing {fwd.step_file(k)}")
    num = den = 0.0
    mx = 0.0
    for e0, e1, s in st.element_chunks(nel, n3, 16384):
        ua = fwd.read(ka, "Velocity", s.start, s.stop).astype(np.float64)
        ub = fwd.read(kb, "Velocity", s.start, s.stop).astype(np.float64)
        d = ((ua - ub) ** 2).sum(axis=1)
        num += d.sum()
        den += (ua ** 2).sum()
        mx = max(mx, float(np.sqrt(d.max())))
    print(f"\n## forward snapshots of iterations {ka} and {kb} (end of each "
          "forward run): relative L2 difference of the velocity "
          f"{np.sqrt(num / den):.3e}, largest pointwise difference "
          f"{mx:.3e}")


def main():
    """Parse the arguments and print the analysis."""
    ap = argparse.ArgumentParser(
        description="Compare the fluid's sensitivity with the explicit "
        "Brinkman-dissipation derivative and locate the fluid that wants "
        "material.")
    ap.add_argument("run", help="run directory")
    ap.add_argument("--case", help="case file (default: the *.case file "
                    "in the run directory)")
    ap.add_argument("--iters",
                    help="comma-separated iterations; the design at the "
                    "last one is reported where the sensitivity is "
                    "negative (default: the first and the last stored)")
    ap.add_argument("--steady", metavar="KA,KB",
                    help="pair of iterations whose forward snapshots are "
                    "compared (default: the first iteration of --iters "
                    "and the next)")
    ap.add_argument("--box", metavar="x0,x1,y0,y1,z0,z1",
                    help="box of the block (default: the point zone of "
                    "the design's initial distribution)")
    a = ap.parse_args()
    run = a.run
    cf, case = st.load_case(run, a.case)
    lx = st.polynomial_order(case) + 1
    n3 = lx ** 3
    rp = st.mapping(case, "RAMP")
    if rp is None:
        raise SystemExit("the design mapping has no RAMP step")
    fmax, q = rp.get("f_max", 1.0), rp.get("q", 1.0)
    dom = st.design_domain(case)
    blo, bhi = block_box(case, a.box)
    w3 = st.tensor_weights(st.gll_weights(lx - 1))
    des = st.Series(run, "design")
    nel = des.npt // n3
    if a.iters:
        its = [int(t) for t in a.iters.split(",")]
    else:
        stored = [k for k in range(des.nsteps) if des.has(k)]
        its = sorted({stored[0], stored[-1]})
    # Brinkman-dissipation weight of each iteration: that of the entry
    # active there (continuation), or 0 if none is
    kind = "brinkman_dissipation"
    wB = {}
    for k in its:
        b = st.active_objectives(case, k, kind).get(kind)
        wB[k] = st.weight_at(case, b, k) if b else 0.0
    listed = [o for o in st.objective_entries(case) if o["type"] == kind]
    if not listed:
        wtext, notes = f"none (no {kind} entry)", []
    elif len(listed) == 1:
        wtext, notes = st.weight_text(case, listed[0])
    else:
        wtext, notes = f"from {len(listed)} {kind} entries", []
    if len(listed) > 1 or (listed
                           and isinstance(listed[0].get("weight"), list)):
        notes.append(", ".join(f"{wB[k]} at iteration {k}" for k in its))
    if a.steady:
        pair = [int(t) for t in a.steady.split(",")]
        if len(pair) != 2:
            raise SystemExit("--steady needs two iterations KA,KB")
        ka, kb = pair
    else:
        ka, kb = its[0], its[0] + 1
    box = {"x_bounds": [blo[0], bhi[0]], "y_bounds": [blo[1], bhi[1]],
           "z_bounds": [blo[2], bhi[2]]}
    print(f"# {run}: {nel} elements, order {lx - 1}; RAMP f_max {fmax} "
          f"q {q}; Brinkman-dissipation weight "
          + "; ".join([wtext] + notes) + "; block box "
          + ", ".join(f"{k_} [{float(v[0])}, {float(v[1])}]"
                     for k_, v in box.items()))
    for k in its:
        for base in ("design", "sensitivity", "forward_fields"):
            ser = st.Series(run, base)
            if not ser.has(k):
                raise SystemExit(f"missing {ser.step_file(k)}")
        res = scan_iteration(run, k, its[-1], nel, n3, w3, dom, blo, bhi,
                             fmax, q, wB[k])
        if res is None:
            print(f"\n## iteration {k}: no fluid (design = 0) in the "
                  "design domain, so there is nothing to report")
            continue
        print_iteration(k, its[-1], *res, blo, bhi, fmax, q, wB[k])
    if a.steady or st.Series(run, "forward_fields").has(kb):
        steadiness(run, ka, kb, nel, n3)
    else:
        print(f"\n## forward snapshots: iteration {kb} is not stored, so "
              f"the velocity of iterations {ka} and {kb} is not compared "
              "(--steady KA,KB compares another pair)")


if __name__ == "__main__":
    main()
