import numpy as np
from snapwrap.pixelResolution import delta_two_theta_over_rectangle

def _z_rect(center_z, hx, hy):
    # rectangle in plane z=L, centered on z-axis; pixel axes along x/y
    center = np.array([0.0, 0.0, center_z])
    u = np.array([1.0, 0.0, 0.0])
    v = np.array([0.0, 1.0, 0.0])
    sample = np.array([0.0, 0.0, 0.0])
    return center, u, v, sample

def test_delta2theta_centered_square_matches_analytic():
    L  = 0.505
    h  = 0.004944
    center, u, v, sample = _z_rect(L, h, h)
    d2t_num = delta_two_theta_over_rectangle(center, u, v, h, h, sample, grid=201)
    # analytic for centered rectangle: Δ2θ = atan( sqrt(a^2+b^2) / L )
    a = b = 0.5*h
    d2t_ref = np.arctan(np.sqrt(a*a + b*b) / L)
    assert np.isclose(d2t_num, d2t_ref, rtol=0, atol=5e-6), (d2t_num, d2t_ref)

def test_delta2theta_degenerate_line_matches_atan_a_over_L():
    L  = 0.505
    hx = 0.004944
    hy = 0.0
    center, u, v, sample = _z_rect(L, hx, hy)
    d2t_num = delta_two_theta_over_rectangle(center, u, v, hx, hy, sample, grid=201)
    a = 0.5*hx
    d2t_ref = np.arctan(a / L)  # nearest point at center, farthest at edge
    assert np.isclose(d2t_num, d2t_ref, rtol=0, atol=5e-6), (d2t_num, d2t_ref)
