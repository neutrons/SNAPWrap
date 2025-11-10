# pixelResolution/core.py
import numpy as np

__all__ = [
    "solid_angle_triangle_batch",
    "solid_angle_square_from_corners",
    "two_theta_batch",
    "omega_rect_perp",
    "delta_two_theta_over_rectangle",
]

def solid_angle_triangle_batch(r1: np.ndarray, r2: np.ndarray, r3: np.ndarray, *, absolute: bool = True) -> np.ndarray:
    """
    Van Oosterom–Strackee solid angle for triangles (vectorized).
    r1, r2, r3: arrays of shape (N, 3) (rays from sample to triangle corners).
    Returns (N,) steradians. If absolute=True, returns positive areas.
    """
    n = np.einsum("ij,ij->i", r1, np.cross(r2, r3))  # scalar triple product
    a = np.linalg.norm(r1, axis=1)
    b = np.linalg.norm(r2, axis=1)
    c = np.linalg.norm(r3, axis=1)
    d = (
        a * b * c
        + np.einsum("ij,ij->i", r1, r2) * c
        + np.einsum("ij,ij->i", r2, r3) * a
        + np.einsum("ij,ij->i", r3, r1) * b
    )
    omega = 2.0 * np.arctan2(n, d)
    return np.abs(omega) if absolute else omega

def solid_angle_square_from_corners(r1: np.ndarray, r2: np.ndarray, r3: np.ndarray, r4: np.ndarray, *, absolute: bool = True) -> np.ndarray:
    """
    Solid angle of a convex quad split into two triangles: (r1,r2,r3) + (r1,r3,r4).
    r1..r4: arrays of shape (N,3). Returns (N,) steradians.
    """
    w1 = solid_angle_triangle_batch(r1, r2, r3, absolute=absolute)
    w2 = solid_angle_triangle_batch(r1, r3, r4, absolute=absolute)
    return w1 + w2

def two_theta_batch(r: np.ndarray) -> np.ndarray:
    """
    Polar scattering angle 2θ when the beam is along +z.
    r: (N,3) rays from sample to points. Returns radians in [0, π].
    """
    rn = np.linalg.norm(r, axis=1)
    cz = np.divide(r[:, 2], rn, out=np.zeros_like(rn), where=rn > 0)  # ẑ·r̂
    cz = np.clip(cz, -1.0, 1.0)
    return np.arccos(cz)

def omega_rect_perp(L: float, hx: float, hy: float) -> float:
    """
    Analytic solid angle of a rectangle (hx × hy) centered and perpendicular to LOS at distance L.
    Ω = 4 * atan( (a*b) / (L * sqrt(L^2 + a^2 + b^2)) ), with a=hx/2, b=hy/2
    """
    a = 0.5 * hx
    b = 0.5 * hy
    return 4.0 * np.arctan((a * b) / (L * np.sqrt(L * L + a * a + b * b)))

def delta_two_theta_over_rectangle(center: np.ndarray,
                                   u_hat: np.ndarray,
                                   v_hat: np.ndarray,
                                   hx: float,
                                   hy: float,
                                   sample: np.ndarray,
                                   grid: int = 101) -> float:
    """
    Max-min 2θ over the *continuous* rectangle defined by:
        P(u,v) = center + u*u_hat + v*v_hat,   u ∈ [-hx/2, +hx/2], v ∈ [-hy/2, +hy/2]
    where 2θ is measured wrt +z beam: 2θ(P) = arccos( ẑ · (P - sample)/||P - sample|| ).

    Parameters
    ----------
    center: (3,) world coords of pixel center
    u_hat, v_hat: (3,) orthonormal in-plane axes of pixel
    hx, hy: edge lengths (meters)
    sample: (3,) sample/world coords
    grid: odd integer (>= 3), number of samples per axis for the search

    Returns
    -------
    float: Δ2θ (radians) = max 2θ over pixel − min 2θ over pixel
    """
    center = np.asarray(center, float)
    u_hat = np.asarray(u_hat, float) / np.linalg.norm(u_hat)
    v_hat = np.asarray(v_hat, float) / np.linalg.norm(v_hat)
    sample = np.asarray(sample, float)

    # Build a tensor grid of (u,v) offsets
    a, b = 0.5*hx, 0.5*hy
    uv = np.linspace(-1.0, 1.0, grid)
    uu, vv = np.meshgrid(uv, uv, indexing="xy")
    U = (a * uu).ravel()[:, None]  # (N,1)
    V = (b * vv).ravel()[:, None]  # (N,1)

    # Points across the pixel, rays from sample
    P = center[None, :] + U * u_hat[None, :] + V * v_hat[None, :]
    R = P - sample[None, :]
    Rn = np.linalg.norm(R, axis=1)
    cz = np.clip(R[:, 2] / Rn, -1.0, 1.0)
    t = np.arccos(cz)
    return float(t.max() - t.min())
