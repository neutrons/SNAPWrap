# a set of function definitions and corresponding residual definitions that can be used
# by scipy.optimize leastsquares to determine lattice parameters from observed reflections

import numpy as np

def cubic_d2Inv(ref,a): #calculates 1/d^^2 given reflection ref and lattice param a
    # correct formula for cubic: (h^2 + k^2 + l^2) / a^2
    return (ref.h**2 + ref.k**2 + ref.l**2) / a**2

def residual_cubic(params,reflectionList):
    """
    Residual function for cubic lattice fitting.

    Returns a list of per-reflection residuals (d^-2 calculated - observed d^-2),
    optionally weighted by the reported extentOverPosition similar to residual_hex.
    """
    # unpack parameter (least_squares will pass an array-like)
    try:
        a = float(params[0]) if hasattr(params, '__len__') else float(params)
    except Exception:
        a = float(params)

    residuals = []

    # validate inputs and compute weighted residuals per reflection
    for ref in reflectionList:
        if not isinstance(ref.dObs, (float, np.floating)):
            raise TypeError(f"Error: d-spacing {ref.dObs!r} is not a float")

        d2Inv_calc = cubic_d2Inv(ref, a)
        d2Inv_obs = 1.0 / ref.dObs**2

        # use extentOverPosition as a proxy for uncertainty if available (same as hex)
        if ref.extentOverPosition is None:
            weight = 1.0
        else:
            uncertainty = 0.3 * ref.extentOverPosition * ref.dObs
            weight = 1.0 / uncertainty if uncertainty > 0 else 1.0

        residuals.append(weight * (d2Inv_calc - d2Inv_obs))

    return residuals

def hex_d2Inv(ref,a,c):

    hk_part = (ref.h**2 + ref.h*ref.k + ref.k**2)
    return (4/3) * hk_part / a**2 + (ref.l**2 / c**2)

# def residual_hex(params,reflectionList):

#     a,c = params #single parameter
#     residuals = []

#     NObs = 0
#     diff = 0
#     for ref in reflectionList:
#         d2Inv_calc = hex_d2Inv(ref,a,c)
#         d2Inv_obs = 1/ref.dObs**2
#         diff += np.sqrt((d2Inv_calc - d2Inv_obs)**2)
#         NObs += 1
    
#     residual = diff/NObs
   

#     return residual

def residual_hex(params, reflectionList):
    """
    Residual function for hexagonal lattice fitting with weighted residuals.

    Args:
        params (list): [a, c] lattice parameters.
        reflectionList (list): List of reflection objects.

    Returns:
        list: Weighted residuals for each reflection.
    """
    a, c = params
    residuals = []

    # validate required inputs
    for ref in reflectionList:
        if not isinstance(ref.dObs, (float, np.floating)):
            raise TypeError(f"Error: d-spacing {ref.dObs!r} is not a float")
        if ref.extentOverPosition is None or not isinstance(ref.extentOverPosition, (float, np.floating)):
            raise TypeError(f"Error: extentOverPosition {ref.extentOverPosition!r} is not a float")
        # print("debug:", ref.dObs, ref.extentOverPosition)

    for ref in reflectionList:
        d2Inv_calc = hex_d2Inv(ref, a, c)
        d2Inv_obs = 1 / ref.dObs**2
        uncertainty = 0.3*ref.extentOverPosition * ref.dObs  # Proxy for uncertainty a third of the peak extent
        weight = 1 / uncertainty if uncertainty > 0 else 1  # Avoid division by zero
        residuals.append(weight * (d2Inv_calc - d2Inv_obs))

    return residuals