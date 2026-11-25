"""Where a sole scan's floor goes: on what the sole stands on, however the scan was held. SYNTHETIC shapes only.

A sole scan arrives with up to 300 mm of shin. Its floor used to be the convex hull's face right under the whole
scan's centre, which the shin pulls over (or behind) the heel; on a real scan's rounded, irregular underside that
face changed with a few degrees of how the foot was held, and so did the length, the toes and the rolled-forefoot
check (docs/insole.md). These shapes show the two failures the floor must not have; the real-scan numbers are in
foot_prep.rest_on_hull's docstring.
"""

import numpy as np
import pytest
import trimesh

import synth
from footscan.recon import completeness, foot_prep

PADS = np.array([[0.0, 0.0, 0.0], [170.0, 28.0, 0.0], [160.0, -28.0, 0.0]])  # the bottoms of heel, inner and outer ball


def _tripod_with_a_leg(lean_back_mm: float, leg_mm: float):
    """SYNTHETIC: a foot that stands on three round pads (the heel, 20 mm radius, and the two sides of the ball,
    12 mm: their bottoms at PADS, all on z = 0), the rubber band round them, and a 28 mm radius leg rising from
    over the heel, its top ``lean_back_mm`` behind it. Split to 4 mm triangles, as a scan's surface is."""
    pads = []
    for c, r in zip(PADS + [[0, 0, 20.0], [0, 0, 12.0], [0, 0, 12.0]], (20.0, 12.0, 12.0)):
        s = trimesh.creation.icosphere(4, r)
        s.apply_translation(c)
        pads.append(s)
    foot = trimesh.convex.convex_hull(np.vstack([p.vertices for p in pads]))
    top = [-lean_back_mm, 0.0, 30.0 + np.sqrt(leg_mm ** 2 - lean_back_mm ** 2)]
    leg = trimesh.creation.cylinder(28.0, segment=[[0.0, 0.0, 30.0], top], sections=48)
    parts = [trimesh.Trimesh(*trimesh.remesh.subdivide_to_size(p.vertices, p.faces, 4.0)) for p in (foot, leg)]
    return trimesh.util.concatenate(parts)


def _pads_after(mesh, turn, by):
    """Heights of the three pads' bottoms once ``mesh``, turned by ``turn`` (4 x 4), is rested ``by`` that rule."""
    m = mesh.copy()
    m.apply_transform(turn)
    _, _, T = foot_prep.rest_on_hull(m, by=by)
    return trimesh.transform_points(PADS, T @ turn)[:, 2]


@pytest.mark.parametrize("tilt_deg", [0.0, 4.0, -4.0])
def test_a_sole_scan_is_rested_on_its_heel_and_ball_however_heavy_the_shin_leaning_behind_it(tilt_deg):
    """A long shin leaning back (a relaxed ankle) puts the scan's centre behind the heel. Under the centre is the
    leg's side, not the floor the foot stands on; the floor the sole stands on most is the three pads', however
    the scan is turned."""
    body = _tripod_with_a_leg(lean_back_mm=170.0, leg_mm=400.0)
    turn = trimesh.transformations.rotation_matrix(np.radians(tilt_deg), [1.0, 0.3, 0.0])
    assert _pads_after(body, turn, "contact") == pytest.approx([0.0, 0.0, 0.0], abs=0.1)
    # resting it on the face under its centre, as a sole scan was, lays it on its leg: the pads end up in the air
    assert _pads_after(body, turn, "centre").max() > 50.0


def test_a_floor_along_the_leg_is_never_taken_even_where_more_of_the_surface_lies_on_it():
    """A plane along the back of the leg has more of the surface near it than the three pads have (a strip the
    leg's length), but it lies along the leg, and no ankle holds a foot that far round (foot_prep.REST_MAX_TIP_DEG):
    never the floor. The real legs-flat scan LIDAR_nwb_relaxed_L_20261027-151815-2190 read 399 mm long before
    that limit (2026-11-25)."""
    body = _tripod_with_a_leg(lean_back_mm=200.0, leg_mm=400.0)  # leaning back 30 degrees: that plane is 60 off level
    assert _pads_after(body, np.eye(4), "contact") == pytest.approx([0.0, 0.0, 0.0], abs=0.1)


def test_a_sole_up_scan_measures_the_same_however_it_was_turned_before_it_was_sent():
    """The same SYNTHETIC sole-up scan, turned a few degrees and any way round before preparing (a foot held a
    little differently): the same length, width and ball of the foot."""
    scan = synth.sole_up_capture(synth.curved_foot("right"))
    rng = np.random.default_rng(0)
    seen = []
    for i in range(3):
        m = scan.copy()
        if i:
            m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(rng.uniform(-4, 4)), [1.0, 0.0, 0.0])
                              @ trimesh.transformations.rotation_matrix(np.radians(rng.uniform(0, 360)), [0.0, 1.0, 0.0]))
        placed, info = foot_prep.prepare_sole_up(m, foot="right")
        c = completeness.measure(placed, "sole_up")
        sides = info["ball_sides_above_floor_mm"]
        seen.append((c["length_mm"], c["width_mm"], abs(sides["plus_x"] - sides["minus_x"])))
    lengths, widths, rolls = np.array(seen).T
    assert np.ptp(lengths) < 0.5 and np.ptp(widths) < 0.5
    assert rolls.max() < 1.0
