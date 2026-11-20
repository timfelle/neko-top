#!/usr/bin/env python3
"""Where does the Brinkman-dissipation objective come from?

Question: which part of the design (fluid, the filter's tail, the rim,
the solid) carries the Brinkman-dissipation integral, and how much of its
value is set by the design mapping alone?

Usage:
    dissipation_split.py RUN_DIR [--case FILE] [--iters 0,19]

Reads (read-only) from RUN_DIR: design_0.vtkhdf + design_0.data/ (fields
design_indicator, PDE_filter_mapping and brinkman_amplitude, written with
verbose_design), forward_fields_0.vtkhdf + forward_fields_0.data/ (field
Velocity: the forward state stored after each iteration's forward run),
and the case file (or pass --case). Reads in chunks of elements, so the
memory stays below about 1 GB at any mesh size.

For each iteration it prints the integral of amplitude * |u|^2 over the
mesh for the stored snapshot, and splits it
  - by filtered design (bands from fluid to solid, with the volume share
    of each band), and
  - by raw design (nodes of the solid, design = 1, against all others);
then it recomputes the integral for the SAME velocity field with other
RAMP parameters q, and with a Heaviside projection ahead of RAMP, and
prints each as a ratio to the stored amplitude.
"""
import argparse
import json

import h5py
import numpy as np

import sensitivity_tools as st

# Bands of the filtered design: lower bound (exclusive), upper bound
# (inclusive), label.
BANDS = ((-1.0, 0.01, "below 0.01"), (0.01, 0.1, "0.01-0.1"),
         (0.1, 0.5, "0.1-0.5"), (0.5, 0.9, "0.5-0.9"),
         (0.9, 0.99, "0.9-0.99"), (0.99, 9.0, "above 0.99"))

# Alternative mappings recomputed from the filtered design.
RAMP_Q = (0.0, 1.0, 4.0, 8.0, 16.0)
HEAVISIDE_BETA = (4.0, 8.0, 16.0)


def split_iteration(des, fwd, k, nel, n3, w3, fmax, q0):
    """Accumulate the integral and its splits for iteration k, in chunks.

    @return total, mesh volume, per-band integral, per-band volume,
            integral over the solid, dict of alternative integrals
    """
    tot = 0.0
    vol_tot = 0.0
    band = np.zeros(len(BANDS))
    bvol = np.zeros(len(BANDS))
    solid = 0.0
    alt = {}
    with h5py.File(des.f, "r") as hm:
        pts = hm["VTKHDF/Points"]
        for e0, e1, s in st.element_chunks(nel, n3):
            B = st.chunk_mass(pts[s], n3, w3)
            u2 = (fwd.read(k, "Velocity", s.start, s.stop)
                  .astype(np.float64) ** 2).sum(axis=1)
            chi = des.read(k, "brinkman_amplitude", s.start, s.stop) \
                .astype(np.float64)
            rf = des.read(k, "PDE_filter_mapping", s.start, s.stop) \
                .astype(np.float64)
            x = des.read(k, "design_indicator", s.start, s.stop) \
                .astype(np.float64)
            d = B * chi * u2
            tot += d.sum()
            vol_tot += B.sum()
            solid += d[x >= 1.0 - 1e-12].sum()
            for i, (lo, hi, _) in enumerate(BANDS):
                m = (rf > lo) & (rf <= hi)
                band[i] += d[m].sum()
                bvol[i] += B[m].sum()
            if fmax is not None:
                for qq in RAMP_Q:
                    key = f"q = {qq:g}"
                    alt[key] = alt.get(key, 0.0) + \
                        (B * st.ramp(rf, fmax, qq) * u2).sum()
                for beta in HEAVISIDE_BETA:
                    key = f"Heaviside beta {beta:g} then RAMP q = {q0:g}"
                    alt[key] = alt.get(key, 0.0) + \
                        (B * st.ramp(st.heaviside(rf, beta), fmax, q0)
                         * u2).sum()
    return tot, vol_tot, band, bvol, solid, alt


def main():
    """Parse the arguments and print the split for each iteration."""
    ap = argparse.ArgumentParser(
        description="Split the Brinkman-dissipation integral by filtered "
        "design and recompute it with other mappings.")
    ap.add_argument("run", help="run directory")
    ap.add_argument("--case", help="case file (default: the *.case file "
                    "in the run directory)")
    ap.add_argument("--iters", default="0",
                    help="comma-separated iterations (default 0)")
    a = ap.parse_args()
    cf, case = st.load_case(a.run, a.case)
    lx = st.polynomial_order(case) + 1
    n3 = lx ** 3
    rp = st.mapping(case, "RAMP")
    fmax, q0 = ((rp.get("f_max", 1.0), rp.get("q", 1.0)) if rp
                else (None, None))
    w3 = st.tensor_weights(st.gll_weights(lx - 1))
    des = st.Series(a.run, "design")
    fwd = st.Series(a.run, "forward_fields")
    nel = des.npt // n3
    print(f"# case {cf}\n# mapping "
          f"{json.dumps(case['optimization']['design']['mapping'])}")
    print(f"# mesh: {nel} elements, order {lx - 1}")
    for k in [int(t) for t in a.iters.split(",")]:
        for ser in (des, fwd):
            if not ser.has(k):
                raise SystemExit(f"missing {ser.step_file(k)}")
        tot, vol_tot, band, bvol, solid, alt = split_iteration(
            des, fwd, k, nel, n3, w3, fmax, q0)
        print(f"\n## iteration {k}: integral of amplitude * |u|^2 over the "
              f"mesh = {tot:.6e}; divided by the mesh volume "
              f"{vol_tot:.4f}: {tot / vol_tot:.6e} "
              f"(half of that: {0.5 * tot / vol_tot:.6e})")
        print("  share by filtered design (and the volume share of each "
              "band):")
        for (lo, hi, lab), b, v in zip(BANDS, band, bvol):
            print(f"    {lab:11s} {b / tot:7.4f}   (volume "
                  f"{v / vol_tot:.5f})")
        print("  share from nodes of the solid (design = 1): "
              f"{solid / tot:.4f}; from all other nodes: "
              f"{1 - solid / tot:.4f}")
        if alt:
            print("  the same velocity field with the amplitude "
                  "recomputed from the filtered design (ratio to the "
                  "stored mapping):")
            for key, v in alt.items():
                print(f"    {key:38s} {v / vol_tot:.6e}   x{v / tot:.3f}")


if __name__ == "__main__":
    main()
