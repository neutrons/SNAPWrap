# tests/test_solid_angle_core.py
import numpy as np
import pytest
from snapwrap.pixelResolution import *

def build_rect_corners_world(L, hx, hy):
    """
    Build 4 corner points for a rectangle centered on z-axis at z=L,
    lying in the plane z=L, edges aligned with x/y.
    Returns p1..p4 each of shape (1,3) so they work with the batch API.
    """
    a = 0.5 * hx
    b = 0.5 * hy
    p1 = np.array([[-a, -b, L]])
    p2 = np.array([[+a, -b, L]])
    p3 = np.array([[+a, +b, L]])
    p4 = np.array([[-a, +b, L]])
    return p1, p2, p3, p4

def rot_z(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[ c, -s, 0.0],
                     [ s,  c, 0.0],
                     [0.0, 0.0, 1.0]])

def test_rectangle_matches_analytic_small_pixel():
    L  = 0.505
    hx = 0.004944
    hy = 0.004944
    p1, p2, p3, p4 = build_rect_corners_world(L, hx, hy)
    omega = solid_angle_square_from_corners(p1, p2, p3, p4)[0]
    omega_ref = omega_rect_perp(L, hx, hy)
    assert np.isclose(omega, omega_ref, rtol=0, atol=1e-12), (omega, omega_ref)

def test_rectangle_scale_invariance():
    L, hx, hy = 1.2, 0.02, 0.01
    p1, p2, p3, p4 = build_rect_corners_world(L, hx, hy)
    omega = solid_angle_square_from_corners(p1, p2, p3, p4)[0]
    k = 5.0
    omega_scaled = solid_angle_square_from_corners(k*p1, k*p2, k*p3, k*p4)[0]
    assert np.isclose(omega, omega_scaled, rtol=1e-12, atol=0)

def test_rectangle_rotation_invariance_about_origin():
    L, hx, hy = 0.505, 0.004944, 0.004944
    p1, p2, p3, p4 = build_rect_corners_world(L, hx, hy)
    omega = solid_angle_square_from_corners(p1, p2, p3, p4)[0]
    R = rot_z(np.deg2rad(37.0))
    omega_rot = solid_angle_square_from_corners(p1@R.T, p2@R.T, p3@R.T, p4@R.T)[0]
    assert np.isclose(omega, omega_rot, rtol=1e-12, atol=0)

def test_small_angle_limit_matches_area_over_L2():
    L, hx, hy = 10.0, 1e-3, 2e-3  # tiny rectangle far away
    p1, p2, p3, p4 = build_rect_corners_world(L, hx, hy)
    omega = solid_angle_square_from_corners(p1, p2, p3, p4)[0]
    approx = (hx*hy) / (L*L)
    assert np.isclose(omega, approx, rtol=3e-6, atol=0)
