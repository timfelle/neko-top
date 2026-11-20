#!/usr/bin/env python3
"""Nodal against over-integrated Brinkman-dissipation integral.

Question: does the nodal (GLL) quadrature of amplitude * |u|^2 agree
with an over-integration of the interpolated amplitude and velocity, and
does the interpolated amplitude go negative?

Usage:
    overintegration_check.py RUN_DIR [--case FILE] [--iteration K]
                             [--points N]

Reads (read-only) from RUN_DIR: design_0.vtkhdf + design_0.data/ (field
brinkman_amplitude, written with verbose_design), forward_fields_0.vtkhdf
+ forward_fields_0.data/ (field Velocity), and the case file (or pass
--case). Works in chunks of elements, so the memory stays at a few
hundred MB at any mesh size.

The amplitude and each velocity component are interpolated from the GLL
nodes to N Gauss-Legendre points per direction (default 3 (N + 1) / 2 + 1
for polynomial order N, rounded down), where |u|^2 is formed and the
product integrated. It prints the nodal and interpolated range of the
amplitude and half the integral divided by the mesh volume for both
quadratures, with the part that comes from a negative interpolated
amplitude. A strongly varying amplitude (for instance after a Heaviside
projection) can undershoot between the nodes and turn the over-integrated
value negative.
"""
import argparse

import h5py
import numpy as np

import sensitivity_tools as st


def to_points(J, a):
    """Interpolate the element arrays a (nel, lx, lx, lx) with J."""
    a = np.einsum("ai,eijk->eajk", J, a)
    a = np.einsum("bj,eajk->eabk", J, a)
    return np.einsum("ck,eabk->eabc", J, a)


def main():
    """Parse the arguments and compare the two quadratures."""
    ap = argparse.ArgumentParser(
        description="Compare the nodal and the over-integrated "
        "Brinkman-dissipation integral of one stored iteration.")
    ap.add_argument("run", help="run directory")
    ap.add_argument("--case", help="case file (default: the *.case file "
                    "in the run directory)")
    ap.add_argument("--iteration", type=int, default=0,
                    help="iteration to check (default 0)")
    ap.add_argument("--points", type=int,
                    help="Gauss-Legendre points per direction (default "
                    "3 (N + 1) / 2 + 1, rounded down, for order N)")
    ap.add_argument("--chunk", type=int, default=st.CHUNK_ELEMENTS,
                    help="elements per chunk (default "
                    f"{st.CHUNK_ELEMENTS})")
    a = ap.parse_args()
    run, k = a.run, a.iteration
    _, case = st.load_case(run, a.case)
    lx = st.polynomial_order(case) + 1
    n3 = lx ** 3
    lxd = a.points if a.points else (3 * lx) // 2 + 1
    xd, wd = st.gauss_legendre(lxd)
    J = st.interp_matrix(st.gll_nodes(lx - 1), xd)
    W = st.tensor_weights(st.gll_weights(lx - 1)).reshape(lx, lx, lx)
    Wd = st.tensor_weights(wd).reshape(lxd, lxd, lxd)
    des = st.Series(run, "design")
    fwd = st.Series(run, "forward_fields")
    for ser in (des, fwd):
        if not ser.has(k):
            raise SystemExit(f"missing {ser.step_file(k)}")
    nel = des.npt // n3

    nodal = over = neg = V = 0.0
    cmin, cmax = np.inf, -np.inf
    dmin, dmax = np.inf, -np.inf
    with h5py.File(des.f, "r") as hm:
        pts = hm["VTKHDF/Points"]
        for e0, e1, s in st.element_chunks(nel, n3, a.chunk):
            vol = st.box_volumes(pts[s], n3)
            V += vol.sum()
            chi = des.read(k, "brinkman_amplitude", s.start, s.stop) \
                .astype(np.float64).reshape(-1, lx, lx, lx)
            U = fwd.read(k, "Velocity", s.start, s.stop) \
                .astype(np.float64).reshape(-1, lx, lx, lx, 3)
            cmin, cmax = min(cmin, chi.min()), max(cmax, chi.max())
            u2 = (U ** 2).sum(axis=-1)
            nodal += ((chi * u2 * W[None]).sum(axis=(1, 2, 3))
                      * vol / 8).sum()
            chid = to_points(J, chi)
            dmin, dmax = min(dmin, chid.min()), max(dmax, chid.max())
            u2d = sum(to_points(J, U[..., c]) ** 2 for c in range(3))
            over += ((chid * u2d * Wd[None]).sum(axis=(1, 2, 3))
                     * vol / 8).sum()
            neg += ((np.minimum(chid, 0) * u2d * Wd[None])
                    .sum(axis=(1, 2, 3)) * vol / 8).sum()
    print(f"{run} iteration {k}, {lxd} Gauss points per direction")
    print(f"  nodal amplitude {cmin:.3e} .. {cmax:.3e}; interpolated "
          f"{dmin:+.3e} .. {dmax:.3e}")
    print(f"  half the integral / volume: nodal {0.5 * nodal / V:+.6e}, "
          f"over-integrated {0.5 * over / V:+.6e} (part from negative "
          f"interpolated amplitude {0.5 * neg / V:+.6e})")


if __name__ == "__main__":
    main()
