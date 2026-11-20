"""Shared helpers for the sensitivity-test analysis scripts.

The scripts read the output of a Neko-TOP run with the ``vtkhdf`` output
format. Each output series ``<base>`` (``design``, ``sensitivity``,
``forward_fields``) is written as

  - ``<base>_0.vtkhdf``: the mesh (``VTKHDF/Points``, element-local, so a
    point shared by several elements appears once per element) and virtual
    datasets that collect every time step, and
  - ``<base>_0.data/<k>.h5``: one file per output step ``k`` with one
    dataset per field, in the same element-local order as the points.

The per-step files are read when present; otherwise the virtual datasets
of the ``.vtkhdf`` are used.

This module provides that reader, the case-file lookup, Gauss-Lobatto-
Legendre (GLL) and Gauss-Legendre quadrature, Lagrange interpolation,
per-element volumes and the design-domain mask computed in chunks,
volume-weighted sums and quantiles, the element-local node classes, and
the RAMP and Heaviside formulas. Only numpy and h5py are needed.
"""
import glob
import json
import os
import sys

import h5py
import numpy as np
from numpy.polynomial import legendre

# Element-local node classes, indexed by the number of element faces a
# node lies on.
CLASSES = ("interior", "face", "edge", "corner")

# Number of elements read at a time by the chunked loops.
CHUNK_ELEMENTS = 20000


# --------------------------------------------------------------------------
# Case file

def load_case(run, case=None):
    """Return the path and the parsed content of a run's case file.

    @param run Run directory; searched for ``*.case`` if case is None.
    @param case Explicit path of the case file, or None.
    """
    path = case or (sorted(glob.glob(os.path.join(run, "*.case")))
                    or [None])[0]
    if path is None:
        sys.exit(f"no case file in {run}; pass --case")
    with open(path) as f:
        return path, json.load(f)


def polynomial_order(case):
    """Polynomial order of the simulation in a parsed case file."""
    return case["case"]["numerics"]["polynomial_order"]


def point_zone(case, name):
    """Return the point zone called name, or None if there is none."""
    for zone in case["case"].get("point_zones", []):
        if zone["name"] == name:
            return zone
    return None


def design_domain(case):
    """Point zone of the design domain, or None (whole mesh)."""
    name = case["optimization"]["design"].get("domain", {}).get("zone_name")
    return point_zone(case, name) if name else None


def mapping(case, kind):
    """First design mapping of the given type, or None."""
    for m in case["optimization"]["design"].get("mapping", []):
        if m["type"] == kind:
            return m
    return None


def objective_weights(case):
    """Ordered dict of objective type -> weight (default 1)."""
    return {o["type"]: float(o.get("weight", 1.0))
            for o in case["optimization"].get("objectives", [])}


# --------------------------------------------------------------------------
# Output series

class Series:
    """One output series: mesh in the .vtkhdf, one <k>.h5 per step."""

    def __init__(self, run, base):
        """Open the series base (e.g. "design") of the run directory."""
        self.f = os.path.join(run, f"{base}_0.vtkhdf")
        self.d = os.path.join(run, f"{base}_0.data")
        if not os.path.exists(self.f):
            sys.exit(f"missing {self.f}")
        with h5py.File(self.f, "r") as h:
            self.nsteps = int(h["VTKHDF/Steps"].attrs.get("NSteps", 1))
            self.npt = int(h["VTKHDF/Points"].shape[0])

    def step_file(self, k):
        """Path of the per-step file of step k."""
        return os.path.join(self.d, f"{k}.h5")

    def has(self, k):
        """Whether step k is on disk."""
        if os.path.isdir(self.d):
            return os.path.exists(self.step_file(k))
        return k < self.nsteps

    def read(self, k, name, start=0, stop=None):
        """Field name of step k, local nodes start to stop (all: None)."""
        stop = self.npt if stop is None else stop
        p = self.step_file(k)
        if os.path.exists(p):
            with h5py.File(p, "r") as h:
                return h[name][start:stop]
        with h5py.File(self.f, "r") as h:
            off = int(h[f"VTKHDF/Steps/PointDataOffsets/{name}"][k])
            return h[f"VTKHDF/PointData/{name}"][off + start:off + stop]

    def names(self, k):
        """Sorted field names of step k."""
        p = self.step_file(k)
        if os.path.exists(p):
            with h5py.File(p, "r") as h:
                return sorted(h.keys())
        with h5py.File(self.f, "r") as h:
            return sorted(h["VTKHDF/PointData"].keys())

    def points(self, idx):
        """Coordinates of the local nodes idx (any order), shape (n, 3)."""
        idx = np.asarray(idx)
        out = np.empty((len(idx), 3))
        if len(idx):
            o = np.argsort(idx)
            with h5py.File(self.f, "r") as h:
                out[o] = h["VTKHDF/Points"][np.sort(idx).tolist()]
        return out


def element_chunks(nel, n3, size=CHUNK_ELEMENTS):
    """Yield (first element, end element, slice of local nodes)."""
    for e0 in range(0, nel, size):
        e1 = min(nel, e0 + size)
        yield e0, e1, slice(e0 * n3, e1 * n3)


# --------------------------------------------------------------------------
# Quadrature and interpolation

def gll_nodes(n):
    """Gauss-Lobatto-Legendre nodes on [-1, 1] for polynomial order n."""
    c = np.zeros(n + 1)
    c[n] = 1
    inner = legendre.legroots(legendre.legder(c)).real
    return np.sort(np.concatenate(([-1.0], inner, [1.0])))


def gll_weights(n):
    """Gauss-Lobatto-Legendre weights for polynomial order n."""
    c = np.zeros(n + 1)
    c[n] = 1
    return 2.0 / (n * (n + 1) * legendre.legval(gll_nodes(n), c) ** 2)


def gauss_legendre(n):
    """Gauss-Legendre nodes and weights with n points."""
    return legendre.leggauss(n)


def tensor_weights(w):
    """Flattened 3-D tensor product of the 1-D weights w."""
    return (w[:, None, None] * w[None, :, None]
            * w[None, None, :]).reshape(-1)


def interp_matrix(xs, xt):
    """Lagrange interpolation matrix from the nodes xs to the points xt."""
    jm = np.ones((len(xt), len(xs)))
    for j in range(len(xs)):
        for m in range(len(xs)):
            if m != j:
                jm[:, j] *= (xt - xs[m]) / (xs[j] - xs[m])
    return jm


# --------------------------------------------------------------------------
# Geometry

def box_volumes(p, n3):
    """Volumes of the elements of the local points p, as boxes.

    Each element is taken as the axis-aligned box spanned by its nodes,
    which is exact for the uniform box meshes these scripts are used on.
    """
    pe = p.reshape(-1, n3, 3)
    return np.prod(pe.max(axis=1) - pe.min(axis=1), axis=1)


def zone_mask(p, zone, tol=1e-9):
    """Points p inside the box zone (all points if zone is None)."""
    m = np.ones(len(p), dtype=bool)
    if zone is not None:
        for ax, key in enumerate(("x_bounds", "y_bounds", "z_bounds")):
            if key in zone:
                m &= ((p[:, ax] >= zone[key][0] - tol)
                      & (p[:, ax] <= zone[key][1] + tol))
    return m


def geometry(ser, lx, dom, chunk_el=CHUNK_ELEMENTS):
    """Element volumes, design-domain mask and bounding box, in chunks.

    @param ser Series whose mesh is read.
    @param lx Number of GLL points per direction.
    @param dom Point zone of the design domain, or None.
    @return nel, element volumes, local-node mask, lower and upper corner.
    """
    n3 = lx ** 3
    nel = ser.npt // n3
    vol = np.empty(nel)
    mask = np.empty(ser.npt, dtype=bool)
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    with h5py.File(ser.f, "r") as h:
        pts = h["VTKHDF/Points"]
        for e0, e1, s in element_chunks(nel, n3, chunk_el):
            p = pts[s]
            lo = np.minimum(lo, p.min(axis=0))
            hi = np.maximum(hi, p.max(axis=0))
            vol[e0:e1] = box_volumes(p, n3)
            mask[s] = zone_mask(p, dom)
    return nel, vol, mask, lo, hi


def local_class(lx):
    """Element-local class (index into CLASSES) of every local node."""
    i = np.arange(lx)
    end = ((i == 0) | (i == lx - 1)).astype(np.int8)
    return (end[:, None, None] + end[None, :, None]
            + end[None, None, :]).reshape(-1)


class Weights:
    """Volume-weighted sums over element-local arrays without storing B.

    The mass B_i of local node i is the product of the GLL weights and an
    eighth of the element volume (the Jacobian of a box element).
    """

    def __init__(self, lx, vol):
        """Set up for lx points per direction and element volumes vol."""
        self.W = tensor_weights(gll_weights(lx - 1))
        self.s = vol / 8.0
        self.n3 = lx ** 3

    def sum(self, a):
        """sum_i B_i a_i for a boolean or float local array a."""
        return float((a.reshape(-1, self.n3) @ self.W) @ self.s)

    def of(self, idx):
        """Masses B_i of the local nodes idx."""
        return self.s[idx // self.n3] * self.W[idx % self.n3]


def chunk_mass(p, n3, w3):
    """Masses B_i of the local points p (whole elements) in a chunk."""
    return ((box_volumes(p, n3) / 8.0)[:, None] * w3[None, :]).reshape(-1)


def wquant(v, w, qs):
    """Quantiles qs of the values v weighted by w."""
    o = np.argsort(v, kind="stable")
    cw = np.cumsum(w[o])
    cw /= cw[-1]
    return np.interp(qs, cw, v[o])


# --------------------------------------------------------------------------
# Design mappings

def ramp(r, fmax, q):
    """RAMP interpolation of the Brinkman amplitude."""
    return fmax * r / (1.0 + q * (1.0 - r))


def ramp_slope(r, fmax, q):
    """Derivative of ramp with respect to r."""
    return fmax * (1 + q) / (1 + q * (1 - r)) ** 2


def heaviside(r, beta, eta=0.5):
    """Smoothed Heaviside projection with sharpness beta, threshold eta."""
    return ((np.tanh(beta * eta) + np.tanh(beta * (r - eta)))
            / (np.tanh(beta * eta) + np.tanh(beta * (1.0 - eta))))
