# pixelResolution/mantid_utils.py
"""
Mantid bridge: compute per-pixel solid angle (Ω) and Δ2θ for one or many DetectorIDs.

Design:
- Uses the pixel's PHYSICAL EDGE SIZES from the detector's shape bounding box.
- Builds an in-plane tangent frame at each pixel center using the ray to the sample,
  so the four corners truly lie on the pixel face even if per-pixel rotations are odd.
- Solid angle is exact via triangle solid angles (van Oosterom–Strackee).
- Δ2θ can be a fast corner-based estimate or a sampling-based exact max–min over the pixel.

All angles use the convention: beam along +z, +y up; 2θ = arccos(ẑ·r̂).
"""

from typing import Iterable, Tuple, Union
import numpy as np
from mantid.kernel import V3D
from mantid.geometry import BoundingBox
from mantid.simpleapi import *

# Reuse the already-tested core math
from .core import (
    solid_angle_square_from_corners,
    two_theta_batch,
    omega_rect_perp,  # handy for sanity checks
)

Array = np.ndarray


def _v3d_to_np(v: V3D) -> Array:
    return np.array([v.X(), v.Y(), v.Z()], dtype=float)


def _pixel_edges_from_shape(det) -> Tuple[float, float, float]:
    """
    Physical pixel edge lengths from the detector shape's bounding box.
    Supports both Mantid bindings (no-arg returning box or in-place).
    Returns (hx, hy, hz_thickness) in meters.
    """
    obj = det.shape()
    try:
        bb = obj.getBoundingBox()
        if isinstance(bb, tuple) and len(bb) == 2:
            mn, mx = bb
        else:
            mn, mx = bb.minPoint(), bb.maxPoint()
    except TypeError:
        bb = BoundingBox()
        obj.getBoundingBox(bb)
        mn, mx = bb.minPoint(), bb.maxPoint()

    hx_edge = float(mx.X() - mn.X())
    hy_edge = float(mx.Y() - mn.Y())
    hz_edge = float(mx.Z() - mn.Z())
    return hx_edge, hy_edge, hz_edge


def _tangent_frame(center: Array, sample: Array) -> Tuple[Array, Array, Array]:
    """
    Build an orthonormal frame at the pixel center:
      n̂ := r̂  (ray from sample to center),
      û := normalized projection of a world axis onto plane ⟂ n̂,
      v̂ := n̂ × û.
    Returns (û, v̂, n̂).
    """
    r = center - sample
    L = np.linalg.norm(r)
    if L == 0:
        raise RuntimeError("Sample coincides with detector center")
    n = r / L
    # choose a reference axis not parallel to n
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = ref - np.dot(ref, n) * n
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    v /= np.linalg.norm(v)
    return u, v, n


def _build_corners(centers: Array, u: Array, v: Array, hx: Array, hy: Array) -> Tuple[Array, Array, Array, Array]:
    """
    Construct the four corner points (world coords) for each pixel.
    centers: (N,3), u: (N,3), v: (N,3), hx,hy: (N,)
    Returns p1..p4, each (N,3).
    """
    ax = 0.5 * hx[:, None]
    ay = 0.5 * hy[:, None]
    p1 = centers - ax * u - ay * v
    p2 = centers + ax * u - ay * v
    p3 = centers + ax * u + ay * v
    p4 = centers - ax * u + ay * v
    return p1, p2, p3, p4


def _delta_two_theta_from_corners(sample: Array, p1: Array, p2: Array, p3: Array, p4: Array) -> Array:
    """
    Fast Δ2θ estimate using only the four corners (works well away from extreme geometries).
    """
    r1, r2, r3, r4 = p1 - sample, p2 - sample, p3 - sample, p4 - sample
    tt1 = two_theta_batch(r1)
    tt2 = two_theta_batch(r2)
    tt3 = two_theta_batch(r3)
    tt4 = two_theta_batch(r4)
    return np.maximum.reduce([tt1, tt2, tt3, tt4]) - np.minimum.reduce([tt1, tt2, tt3, tt4])


def _delta_two_theta_sampled(sample: Array, center: Array, u: Array, v: Array, hx: Array, hy: Array, grid: int) -> Array:
    """
    Accurate Δ2θ via max–min over the *continuous* pixel area by sampling.
    center,u,v shapes (N,3); hx,hy (N,). Returns (N,) radians.
    """
    N = center.shape[0]
    uv = np.linspace(-1.0, 1.0, grid)
    uu, vv = np.meshgrid(uv, uv, indexing="xy")
    UU = uu.ravel()  # (G,)
    VV = vv.ravel()
    G = UU.size
    out = np.empty((N,), dtype=float)

    for i in range(N):
        a, b = 0.5 * hx[i], 0.5 * hy[i]
        # points across the pixel
        P = center[i] + (a * UU)[:, None] * u[i] + (b * VV)[:, None] * v[i]  # (G,3)
        R = P - sample  # broadcast sample (3,) -> (G,3)
        Rn = np.linalg.norm(R, axis=1)
        cz = np.clip(R[:, 2] / Rn, -1.0, 1.0)
        t = np.arccos(cz)
        out[i] = float(t.max() - t.min())
    return out

def pixel_metrics(
    ws,
    detids: Union[int, Iterable[int]],
    *,
    sample_pos: Array = None,
    k_neighbors: int = 80,         # more neighbors helps at edges
    axis_tol_deg: float = 15.0,    # starting tolerance; will relax adaptively
    return_debug: bool = False,
) -> Union[
    Tuple[float, float],
    Tuple[np.ndarray, np.ndarray],
    Tuple[float, float, dict],
    Tuple[np.ndarray, np.ndarray, dict],
]:
    """
    (Ω, Δ2θ) for one or many DetectorIDs, robust at edges.

    - Axes (û, v̂): PCA on K nearest neighbors projected into local plane.
    - Pitch hx, hy: smallest non-zero projection along û/v̂ among neighbors that are
      within ±axis_tol_deg of the axis; if empty, tolerance is relaxed (25°, 35°, 45°).
      If still empty, use the smallest projection among the top-10 most aligned neighbors.
      If still empty, fall back to isotropic pitch = min in-plane distance.
    - Ω: exact from two-triangle solid angles over pixel corners.
    - Δ2θ: max(corner 2θ) − center 2θ (fast and correct for flat, facing panels).
    - If return_debug=True, a third result provides hx_arr, hy_arr, u, v, centers, L, pitch_method.

    Returns scalars for a single detid, arrays otherwise.
    """
    scalar = isinstance(detids, (int, np.integer))
    detid_list = [int(detids)] if scalar else [int(d) for d in detids]
    N = len(detid_list)

    detInfo = ws.detectorInfo()

    # Sample position
    if sample_pos is None:
        sp = ws.spectrumInfo().samplePosition()
        sample = _v3d_to_np(sp)
    else:
        sample = np.asarray(sample_pos, dtype=float)

    # Cache all detector centers once
    M = detInfo.size()
    all_centers = np.empty((M, 3), dtype=float)
    for i in range(M):
        all_centers[i] = _v3d_to_np(detInfo.position(int(i)))

    idxs = [int(detInfo.indexOf(d)) for d in detid_list]

    centers = np.empty((N, 3), dtype=float)
    u = np.empty((N, 3), dtype=float)
    v = np.empty((N, 3), dtype=float)
    hx_arr = np.empty((N,), dtype=float)
    hy_arr = np.empty((N,), dtype=float)
    L_arr  = np.empty((N,), dtype=float)
    method = np.empty((N,), dtype=object)

    cos_start = float(np.cos(np.deg2rad(axis_tol_deg)))
    tol_len = 1e-6  # meters

    for j, idx in enumerate(idxs):
        c = all_centers[idx]
        centers[j] = c

        # Local plane normal from ray to sample
        r = c - sample
        L = np.linalg.norm(r); L_arr[j] = L
        if L == 0:
            raise RuntimeError("Sample coincides with detector center")
        n = r / L

        # K nearest neighbors (excluding self); expand if too few after filtering
        dv = all_centers - c
        dist = np.linalg.norm(dv, axis=1)
        order = np.argsort(dist)
        order = order[(order != idx)]
        k_use = max(k_neighbors, 20)
        dvn = dv[order[:k_use]]

        # Project neighbor offsets into the local plane and filter tiny ones
        dv_plane = dvn - np.outer(dvn @ n, n)
        norms = np.linalg.norm(dv_plane, axis=1)
        keep = norms > tol_len
        dv_plane = dv_plane[keep]; norms = norms[keep]
        if dv_plane.shape[0] < 4 and k_use < 400:
            # expand neighborhood and try again
            dvn = dv[order[:400]]
            dv_plane = dvn - np.outer(dvn @ n, n)
            norms = np.linalg.norm(dv_plane, axis=1)
            keep = norms > tol_len
            dv_plane = dv_plane[keep]; norms = norms[keep]

        if dv_plane.shape[0] < 4:
            # pathological; fallback to default square of 5 mm
            u[j], v[j] = _tangent_frame(c, sample)[:2]
            hx_arr[j] = hy_arr[j] = 0.005
            method[j] = "fallback_default"
            continue

        # PCA axis; enforce right-handed with n
        _, _, Vt = np.linalg.svd(dv_plane, full_matrices=False)
        u_axis = Vt[0] / np.linalg.norm(Vt[0])
        v_axis = np.cross(n, u_axis); v_axis /= np.linalg.norm(v_axis)

        # Normalize neighbor directions in plane
        dv_unit = dv_plane / norms[:, None]

        def pick_pitch(axis_vec, label):
            # Try progressive angle relaxations
            for cos_tol in (cos_start, np.cos(np.deg2rad(25.0)), np.cos(np.deg2rad(35.0)), np.cos(np.deg2rad(45.0))):
                mask = np.abs(dv_unit @ axis_vec) >= cos_tol
                proj = np.abs(dv_plane @ axis_vec)[mask]
                proj = proj[proj > tol_len]
                if proj.size:
                    return float(np.min(proj)), f"{label}@±{np.degrees(np.arccos(cos_tol)):.0f}°"
            # Fall back: pick among top-10 most aligned by |cos|
            cosvals = np.abs(dv_unit @ axis_vec)
            if cosvals.size:
                take = min(10, cosvals.size)
                top = np.argpartition(-cosvals, take-1)[:take]
                proj = np.abs(dv_plane[top] @ axis_vec)
                proj = proj[proj > tol_len]
                if proj.size:
                    return float(np.min(proj)), f"{label}_top10"
            return np.nan, f"{label}_nan"

        px, mx = pick_pitch(u_axis, "u")
        py, my = pick_pitch(v_axis, "v")

        if not np.isfinite(px) or not np.isfinite(py):
            # Isotropic fallback: smallest in-plane distance
            dmin = float(np.min(norms[norms > tol_len])) if np.any(norms > tol_len) else 0.005
            px = py = dmin
            method[j] = f"iso({dmin:.4g})"
        else:
            method[j] = f"{mx}|{my}"

        u[j] = u_axis
        v[j] = v_axis
        hx_arr[j] = px
        hy_arr[j] = py

    # Build corners from inferred pitch
    p1, p2, p3, p4 = _build_corners(centers, u, v, hx_arr, hy_arr)
    r1, r2, r3, r4 = p1 - sample, p2 - sample, p3 - sample, p4 - sample

    # Exact Ω (two triangles)
    Omega = solid_angle_square_from_corners(r1, r2, r3, r4, absolute=True)

    # Δ2θ = max(corner) - center
    tt_center = two_theta_batch(centers - sample)
    tt_corners = np.maximum.reduce([
        two_theta_batch(r1),
        two_theta_batch(r2),
        two_theta_batch(r3),
        two_theta_batch(r4)
    ])
    Delta2theta = tt_corners - tt_center

    if scalar:
        if return_debug:
            debug = dict(hx_arr=hx_arr, hy_arr=hy_arr, u=u, v=v, centers=centers, L=L_arr, pitch_method=method)
            return float(Omega[0]), float(Delta2theta[0]), debug
        return float(Omega[0]), float(Delta2theta[0])
    else:
        if return_debug:
            debug = dict(hx_arr=hx_arr, hy_arr=hy_arr, u=u, v=v, centers=centers, L=L_arr, pitch_method=method)
            return Omega, Delta2theta, debug
        return Omega, Delta2theta


def pixel_metrics_tangent(
    ws,
    detids,
    *,
    hx: float,
    hy: float,
    sample_pos: np.ndarray = None,
    d2t_mode: str = "corner_span",   # "corner_span" | "linear" | "sampled"
    sample_grid: int = 41,           # used only if d2t_mode="sampled"
    return_debug: bool = False,
):
    """
    Vectorized (Ω, Δ2θ) using a tangent frame at each pixel center and fixed hx, hy.

    Ω: exact two-triangle solid angle (positive).
    Δ2θ:
      - "corner_span":  max(2θ at 4 corners) - min(2θ at 4 corners)  [fast, exact on corners]
      - "linear":       2a|∂(2θ)/∂u| + 2b|∂(2θ)/∂v| at the center   [very smooth, cheap]
      - "sampled":      true max–min over the rectangular face by sampling (slower)

    Returns scalars for a single detid, arrays otherwise. Optionally returns debug info.
    """
    import numpy as np

    # normalize input
    scalar = isinstance(detids, (int, np.integer))
    detid_list = [int(detids)] if scalar else [int(d) for d in detids]
    N = len(detid_list)

    detInfo = ws.detectorInfo()
    idxs = [int(detInfo.indexOf(d)) for d in detid_list]

    # sample
    if sample_pos is None:
        sp = ws.spectrumInfo().samplePosition()
        sample = np.array([sp.X(), sp.Y(), sp.Z()], dtype=float)
    else:
        sample = np.asarray(sample_pos, float)

    # centers
    centers = np.empty((N, 3), float)
    for j, i in enumerate(idxs):
        p = detInfo.position(int(i))
        centers[j] = (p.X(), p.Y(), p.Z())

    # tangent frame per pixel
    u = np.empty((N, 3), float)
    v = np.empty((N, 3), float)
    L = np.empty((N,), float)
    for j in range(N):
        r = centers[j] - sample
        L[j] = np.linalg.norm(r)
        n = r / L[j]
        ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        uj = ref - np.dot(ref, n) * n; uj /= np.linalg.norm(uj)
        vj = np.cross(n, uj);         vj /= np.linalg.norm(vj)
        u[j], v[j] = uj, vj

    # corners
    a, b = 0.5*float(hx), 0.5*float(hy)
    ax = a * np.ones((N, 1), float)
    ay = b * np.ones((N, 1), float)
    p1 = centers - ax * u - ay * v
    p2 = centers + ax * u - ay * v
    p3 = centers + ax * u + ay * v
    p4 = centers - ax * u + ay * v

    # rays
    r1, r2, r3, r4 = p1 - sample, p2 - sample, p3 - sample, p4 - sample

    # Ω (exact)
    Omega = solid_angle_square_from_corners(r1, r2, r3, r4, absolute=True)

    # Δ2θ
    if d2t_mode == "corner_span":
        tt1 = two_theta_batch(r1); tt2 = two_theta_batch(r2)
        tt3 = two_theta_batch(r3); tt4 = two_theta_batch(r4)
        Delta2theta = np.maximum.reduce([tt1, tt2, tt3, tt4]) - np.minimum.reduce([tt1, tt2, tt3, tt4])

    elif d2t_mode == "linear":
        # central differences along u and v at the center
        # choose a tiny step (fraction of edge): eps = min(hx, hy)/100
        eps = 0.01 * min(float(hx), float(hy))
        du_pts_plus  = centers + eps * u
        du_pts_minus = centers - eps * u
        dv_pts_plus  = centers + eps * v
        dv_pts_minus = centers - eps * v

        r_u_plus  = du_pts_plus  - sample
        r_u_minus = du_pts_minus - sample
        r_v_plus  = dv_pts_plus  - sample
        r_v_minus = dv_pts_minus - sample

        t_u = (two_theta_batch(r_u_plus) - two_theta_batch(r_u_minus)) / (2.0 * eps)
        t_v = (two_theta_batch(r_v_plus) - two_theta_batch(r_v_minus)) / (2.0 * eps)

        Delta2theta = 2.0 * (a * np.abs(t_u) + b * np.abs(t_v))

    elif d2t_mode == "sampled":
        # true max–min over the rectangle by sampling (slower)
        assert sample_grid >= 11 and sample_grid % 2 == 1, "sample_grid should be odd and >= 11"
        uv = np.linspace(-1.0, 1.0, sample_grid)
        uu, vv = np.meshgrid(uv, uv, indexing="xy")
        UU = uu.ravel()[:, None]  # (G,1)
        VV = vv.ravel()[:, None]
        Delta2theta = np.empty((N,), float)
        for j in range(N):
            P = centers[j] + (a * UU) * u[j] + (b * VV) * v[j]  # (G,3)
            R = P - sample
            t_all = two_theta_batch(R)
            Delta2theta[j] = float(t_all.max() - t_all.min())
    else:
        raise ValueError("d2t_mode must be one of: 'corner_span', 'linear', 'sampled'")

    if scalar:
        if return_debug:
            return float(Omega[0]), float(Delta2theta[0]), dict(centers=centers, u=u, v=v, L=L)
        return float(Omega[0]), float(Delta2theta[0])
    if return_debug:
        return Omega, Delta2theta, dict(centers=centers, u=u, v=v, L=L)
    return Omega, Delta2theta

def pixel_metrics_panel_oriented(
    ws,
    detids,
    *,
    hx: float,
    hy: float,
    sample_pos: np.ndarray = None,
    d2t_mode: str = "corner_span",   # "corner_span" | "linear" | "isotropic" | "sampled"
    sample_grid: int = 41,           # used only if d2t_mode="sampled"
    return_debug: bool = False,
):
    """
    Vectorized (Ω, Δ2θ) using the pixel axes from the Mantid detector rotation
    and fixed hx, hy (meters). This avoids basis flips from heuristic tangent frames.

    Ω: exact two-triangle solid angle (positive).
    Δ2θ modes:
      - "corner_span":  max(2θ at 4 corners) − min(2θ at 4 corners)   [fast, default]
      - "linear":       2a|∂(2θ)/∂u| + 2b|∂(2θ)/∂v| at the center      [very smooth]
      - "isotropic":    2r_c |∇(2θ)| at the center (r_c=√(a²+b²))     [perfectly radial]
      - "sampled":      true max–min over the rectangle by sampling    [slower]
    """
    import numpy as np
    from mantid.kernel import V3D

    def _v3d_to_np(v):  # local helper
        return np.array([v.X(), v.Y(), v.Z()], dtype=float)

    def _uv_from_rotation(R):
        ex = V3D(1.0, 0.0, 0.0)
        ey = V3D(0.0, 1.0, 0.0)
        if hasattr(R, "rotate"):          # Quat: in-place
            R.rotate(ex); R.rotate(ey)
        else:
            try:
                M = R.toRotationMatrix()  # RotationMatrix
            except AttributeError:
                M = R
            ex = M * ex; ey = M * ey
        u = _v3d_to_np(ex); u /= np.linalg.norm(u)
        v = _v3d_to_np(ey); v /= np.linalg.norm(v)
        return u, v

    # normalize input
    scalar = isinstance(detids, (int, np.integer))
    detid_list = [int(detids)] if scalar else [int(d) for d in detids]
    N = len(detid_list)

    detInfo = ws.detectorInfo()
    idxs = [int(detInfo.indexOf(d)) for d in detid_list]

    # sample position
    if sample_pos is None:
        sp = ws.spectrumInfo().samplePosition()
        sample = np.array([sp.X(), sp.Y(), sp.Z()], dtype=float)
    else:
        sample = np.asarray(sample_pos, float)

    # centers and axes from rotation
    centers = np.empty((N, 3), float)
    u = np.empty((N, 3), float)
    v = np.empty((N, 3), float)
    L = np.empty((N,), float)
    for j, i in enumerate(idxs):
        pj = detInfo.position(int(i))
        centers[j] = (pj.X(), pj.Y(), pj.Z())
        Rj = detInfo.rotation(int(i))
        uj, vj = _uv_from_rotation(Rj)
        # ensure in-plane and orthonormal (be cautious with oddly-defined rotations)
        # re-orthogonalize just in case:
        vj = vj - np.dot(vj, uj) * uj
        vj /= np.linalg.norm(vj)
        u[j], v[j] = uj, vj
        r = centers[j] - sample
        L[j] = np.linalg.norm(r)

    # corners
    a, b = 0.5 * float(hx), 0.5 * float(hy)
    ax = a * np.ones((N, 1), float)
    ay = b * np.ones((N, 1), float)
    p1 = centers - ax * u - ay * v
    p2 = centers + ax * u - ay * v
    p3 = centers + ax * u + ay * v
    p4 = centers - ax * u + ay * v

    # rays from sample
    r1, r2, r3, r4 = p1 - sample, p2 - sample, p3 - sample, p4 - sample

    # Ω (exact)
    Omega = solid_angle_square_from_corners(r1, r2, r3, r4, absolute=True)

    # Δ2θ
    if d2t_mode == "corner_span":
        tt1 = two_theta_batch(r1); tt2 = two_theta_batch(r2)
        tt3 = two_theta_batch(r3); tt4 = two_theta_batch(r4)
        Delta2theta = np.maximum.reduce([tt1, tt2, tt3, tt4]) - np.minimum.reduce([tt1, tt2, tt3, tt4])

    elif d2t_mode in ("linear", "isotropic"):
        eps = 0.01 * min(float(hx), float(hy))  # small central-diff step
        du_p = centers + eps * u; du_m = centers - eps * u
        dv_p = centers + eps * v; dv_m = centers - eps * v
        t_u = (two_theta_batch(du_p - sample) - two_theta_batch(du_m - sample)) / (2.0 * eps)
        t_v = (two_theta_batch(dv_p - sample) - two_theta_batch(dv_m - sample)) / (2.0 * eps)
        if d2t_mode == "linear":
            Delta2theta = 2.0 * (a * np.abs(t_u) + b * np.abs(t_v))
        else:  # isotropic: use circumscribed-circle radius
            rc = np.sqrt(a*a + b*b)
            grad = np.sqrt(t_u*t_u + t_v*t_v)
            Delta2theta = 2.0 * rc * grad

    elif d2t_mode == "sampled":
        assert sample_grid >= 11 and (sample_grid % 2 == 1), "sample_grid must be odd and >=11"
        uv = np.linspace(-1.0, 1.0, sample_grid)
        uu, vv = np.meshgrid(uv, uv, indexing="xy")
        UU, VV = uu.ravel()[:, None], vv.ravel()[:, None]
        Delta2theta = np.empty((N,), float)
        for j in range(N):
            P = centers[j] + (a * UU) * u[j] + (b * VV) * v[j]
            t_all = two_theta_batch(P - sample)
            Delta2theta[j] = float(t_all.max() - t_all.min())
    else:
        raise ValueError("d2t_mode must be 'corner_span', 'linear', 'isotropic', or 'sampled'")

    if scalar:
        if return_debug:
            return float(Omega[0]), float(Delta2theta[0]), dict(centers=centers, u=u, v=v, L=L)
        return float(Omega[0]), float(Delta2theta[0])
    if return_debug:
        return Omega, Delta2theta, dict(centers=centers, u=u, v=v, L=L)
    return Omega, Delta2theta


# --- optional utility: quick comparison to Ω ≈ A cosθ / L^2 at the pixel center ---
def pixel_center_small_angle(ws, detid: int, hx: float = None, hy: float = None) -> float:
    """
    Small-pixel approximation at the *center*: Ω ≈ (hx*hy) * cosθ / L^2.
    Useful as a sanity check near the detector center.
    """
    detInfo = ws.detectorInfo()
    instr = ws.getInstrument()
    i = int(detInfo.indexOf(int(detid)))
    c = _v3d_to_np(detInfo.position(i))
    s = _v3d_to_np(ws.spectrumInfo().samplePosition())
    r = c - s
    L = np.linalg.norm(r)
    if hx is None or hy is None:
        rep_det = instr.getDetector(int(detid))
        hx_edge, hy_edge, _ = _pixel_edges_from_shape(rep_det)
        A = hx_edge * hy_edge
    else:
        A = float(hx) * float(hy)
    # assume face perpendicular to ray (good for flat panels facing sample)
    cos_th = 1.0
    return A * cos_th / (L * L)

def make_resolution_workspaces(donorWSName,
                            pixelEdgeMultiplier=1,
                            solidAngleWSName="omega",
                            d2tWSName="d2t"):
    """
    Using a supplied donor workspace, which should be unfocussed, to
    manufacture workspaces containing calculated omega (solid angle) and d2t
    (2theta uncertainty) for every pixel as their y-values.

    a detailed investigation revealled that the active pixel size appears to be significantly
    bigger than the IDF description. This is handled by allowing an option to supply a multiplier
    to increase the edge size of a pixel.
    """

    ws = mtd[donorWSName]

    id_list = []
    id_map = {}
    #first need to collect a list of detectorID's from the donor
    # instr = ws.getInstrument()
    detInfo = ws.detectorInfo()

    nHisto = ws.getNumberHistograms()
    print(f"nHisto: {nHisto}")
    for s in range(nHisto):
        dids = list(ws.getSpectrum(s).getDetectorIDs())
        if len(dids) != 1:
            print("Error: input workspace should be unfocussed")
            return
        
        if not dids:
            continue
        
        did = int(dids[0])

        #TODO: why is this not correct?
        # if detInfo.isMonitor(did):
        #     print(f"histogram:{s} is a monitor")
        #     continue

        id_list.append(did)
        id_map[did]= s #map pixels id to spectrum number

    
    #determine which instrument we have
    nPix = len(id_list)
    if nPix == 18432:
        #instrument is SNAPLite
        h = pixelEdgeMultiplier*0.004944 # size of lite pixel edge from IDF
    elif nPix == 1179648:
        #instrument is SNAP
        h = pixelEdgeMultiplier*0.000618 # size of pixel edge from IDF
    else:
        print(f"Error: instrument not recognised, donorWS has: {nPix} pixels != 18432 or 1179648")


    # using donor, create a clone workspace with a single bin and no events.
    Rebin(InputWorkspace=donorWSName,
          OutputWorkspace=solidAngleWSName,
          Params = "0,1,1",
          PreserveEvents=False) #should ensure single bin , while discarding eventsSW
    
    ws_om = mtd[solidAngleWSName]

    CloneWorkspace(InputWorkspace=solidAngleWSName,
            OutputWorkspace=d2tWSName)
    ws_d2t = mtd[d2tWSName]


    # calculate lists of solid angles (omega) and delta 2theta (d2t) for all pixel ids in list
    # generate from donorWS

    omegaList, d2tList = pixel_metrics_panel_oriented(ws, id_list, hx=h, hy=h)

    #using these, populate output workspaces with appropriate y-values

    for i,did in enumerate(id_list):
        wi = id_map[did]
        ws_om.dataY(wi)[0] = omegaList[i]
        #calculated d2t is full 2theta range. But typically will be comparing with
        #std deviation from Gaussian peak fits. Take full range to be equiv to 2*FWHM
        #then std deviation given by: 
        sig = (d2tList[i]/2)/(2*np.sqrt(2*np.log(2)))
        ws_d2t.dataY(wi)[0] = sig
    
    print(f"generated workspaces: {solidAngleWSName} containing pixel solid angles and {d2tWSName} containing their 2theta uncertainty")
