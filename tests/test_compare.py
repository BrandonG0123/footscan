"""Comparing two scans of the same foot (recon/compare.py)."""

import numpy as np
import pytest

import synth


def _sole_up(foot="right", tip=25.0, yaw=63.0, noise=0.0, seed=0, arch_scale=1.0):
    """A synthetic sole-up scan as the app hands it over (metres, Y up), of the curved foot."""
    import trimesh

    from footscan.recon import imported

    m = synth.curved_foot(foot)
    if arch_scale != 1.0:  # a different foot: the arch higher or lower
        V = m.vertices.copy()
        s = synth.curved_sole(V[:, 0], V[:, 1], foot)
        low = V[:, 2] < s + 0.5
        V[low, 2] = s[low] * arch_scale
        m = trimesh.Trimesh(V, m.faces, process=False)
    if noise:
        m = synth.speckle(m, noise, seed=seed)
    return _as_scan(m, tip, yaw)


def _as_scan(m, tip=25.0, yaw=63.0):
    """A foot (foot coordinates, mm) placed as a sole-up scan as the app hands it over."""
    import trimesh

    from footscan.recon import imported

    m = m.copy()
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(tip), [0, 1, 0], [0, 45, 0]))
    m.apply_transform(np.diag([1.0, -1, -1, 1]))
    T = trimesh.transformations.rotation_matrix(np.radians(yaw), [0, 0, 1])
    T[:3, 3] = [40, -25, 7]
    m.apply_transform(T)
    m.apply_transform(np.block([[imported.UP["y"].T, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.apply_scale(0.001)
    return m


def test_the_same_foot_scanned_twice_differently_placed_agrees():
    """Two clean scans of one foot, placed and tipped differently: the preparation undoes both, so
    they agree to well under a tenth of a millimetre."""
    from footscan.recon import compare

    r = compare.compare_scans(_sole_up(tip=25, yaw=63), _sole_up(tip=40, yaw=200), "right")
    assert r["typical_mm"] < 0.05 and r["p95_mm"] < 0.15
    assert abs(r["arch_difference_mm"]) < 0.2 and r["outline"]["mean_gap_mm"] < 0.5


def test_scan_noise_shows_up_as_disagreement_of_about_its_size():
    from footscan.recon import compare

    r = compare.compare_scans(_sole_up(noise=0.6, seed=1), _sole_up(noise=0.6, seed=2, yaw=150), "right")
    assert 0.1 < r["typical_mm"] < 0.6 and r["p95_mm"] < 1.6


def test_a_different_arch_is_seen_as_a_different_arch():
    """A foot whose arch is 30% higher: the comparison says so, in the arch, not as noise."""
    from footscan.recon import compare

    r = compare.compare_scans(_sole_up(), _sole_up(arch_scale=1.3, yaw=120), "right")
    assert r["arch_difference_mm"] == pytest.approx(0.3 * synth.CURVED_ARCH_MM, abs=1.0)
    assert r["bias_mm"] > 0.3


def test_points_near_either_scans_edge_are_left_out():
    """b missed the toes: its edge falls inside a's sole. Only points more than EDGE_MM inside both
    count, so the toes' end doesn't read as a difference, and the count says less was compared."""
    from footscan.recon import compare

    full = synth.curved_foot("right")
    short = full.slice_plane([225.0, 0, 0], [-1.0, 0, 0], cap=True)  # the toes' last 25 mm missed
    assert short.bounds[1][0] < 226
    a, b = _as_scan(full), _as_scan(short, yaw=140)
    r = compare.compare_scans(a, b, "right")
    whole = compare.compare_scans(a, _as_scan(full, yaw=140), "right")
    assert r["p95_mm"] < 0.15 and abs(r["bias_mm"]) < 0.05 and r["outline"]["mean_gap_mm"] < 0.5
    # left out: a's sole past b's end and a band EDGE_MM deep before it (1 mm grid; the tapering toes,
    # already short of a's own edge band, make it about 900 points; without b's band, about 700)
    assert whole["points"] - r["points"] > 820
