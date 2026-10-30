"""Is the whole foot in the scan? Checks that the toes and the heel are there, before a scan is accepted.

A sole scan can lose a whole end of the foot and still pass the other checks: the toes curled
out of the scan or cut off at their bases, or the back of the heel never photographed. Object
Capture then closes the gap with a smooth guessed surface, so nothing is torn and the footprint
is still foot-sized, only shorter. An insole made from it is short, and its heel cup sits in the
wrong place.

Two things give it away, both read from the prepared foot (mat frame: toes toward +y, the floor at
z = 0), seen from above as the insole outline is (``insole.silhouette``, everything below
``insole.SILHOUETTE_HEIGHT_MM``):

1. **The shape of each end.** A foot narrows to both ends: the toes round off to the big toe, the
   heel rounds off to its back. Measured ``END_PROBE_MM`` in from each end, the outline is only a
   fraction as wide as the ball of the foot (at the toes) or the heel (at the heel). An end that
   was cut off is square instead: just as far in, it is nearly as wide as the foot there.
2. **The length against the person's other scans** (in the studio, which keeps them): an end that
   went missing makes the foot shorter than the other foot, or than an earlier scan of the same
   foot. The first real case: the left sole-up scan LIDAR_nwb_relaxed_L_20261027-151404-89df gave
   an outline of 227.0 x 86.3 mm, the right foot's scan the same afternoon 246.4 x 102.3 mm.

The thresholds are this module's own choices, set on the synthetic shapes above, not measured
limits of real feet: each is written next to the shape it was set on.
"""

from __future__ import annotations

import numpy as np

# Kinds of scan whose whole foot should be there: the sole scans. A foot standing on the floor and a
# foam print aren't checked (a print can be shallower than the toes; neither is the scan Brandon uses).
CHECKED_KINDS = ("sole_up", "sole_hanging")

END_PROBE_MM = 5.0        # how far in from each end the outline's width is measured
END_TURN_DEG = 8.0        # ...across lines up to this far off square to the foot's length
# Above these, an end is square: cut off. Set on SYNTHETIC sole-up scans (tests/synth.py's shaped_foot and
# curved_foot, 250 x 100 mm, heel 64 mm wide, both feet, prepared as Make insole prepares them), not on
# real feet. Toes (width 5 mm in / the ball's): whole 0.33; cut off 15 mm short 0.54 (missed: the length
# comparison is for that), 25 mm short 0.62, 50 mm short 0.83-0.84. Heel (width 5 mm in / the heel's):
# whole 0.47; cut off 8 mm in 0.66, 15 mm 0.75, 25-30 mm 0.79-0.80.
TOE_END_SQUARE = 0.6
HEEL_END_SQUARE = 0.65
HEEL_SHARE = 0.3          # the back of the foot that holds the heel
# Shorter than another scan of the same person by more than this (mm) is a missing end. The one real
# case so far: 19.4 mm (89df against the right foot's 2349, insole outlines).
SHORTER_THAN_OTHER_MM = 12.0


def _width_at(poly, y: float) -> float:
    """How wide the outline is (mm, across x) on the line at ``y``: the total length inside it."""
    from shapely.geometry import LineString

    x0, _, x1, _ = poly.bounds
    return float(poly.intersection(LineString([(x0 - 1.0, y), (x1 + 1.0, y)])).length)


def _along_its_length(poly):
    """The outline turned about its centre so its own length runs along y, toes still toward +y.

    Its length is the outline's principal axis (the line it's spread out along most, from the second
    moments of its area). The preparation points the toes along +y from the footprint, which can sit a
    few degrees off this (the arch is missing from the footprint), and seen at a slant a square end
    looks pointed."""
    import shapely
    from shapely import affinity

    tri = [t for t in shapely.delaunay_triangles(poly.segmentize(5.0)).geoms if t.centroid.within(poly)]
    c = np.array([[t.centroid.x, t.centroid.y] for t in tri])
    a = np.array([t.area for t in tri])
    mu = np.average(c, axis=0, weights=a)
    w, v = np.linalg.eigh(np.cov((c - mu).T, aweights=a))
    axis = v[:, np.argmax(w)]
    axis = axis if axis[1] >= 0 else -axis
    return affinity.rotate(poly, np.degrees(np.arctan2(axis[0], axis[1])), origin=tuple(mu))


def _end_share(poly, end: int, width: float) -> float:
    """How square one end is: the outline's width ``END_PROBE_MM`` in from that end (``end`` +1 the toes,
    -1 the heel), as a share of ``width`` (the toes: the widest the foot is anywhere; the heel: the widest
    the heel is, in the back ``HEEL_SHARE`` of the length). Taken at the turn, within
    ``END_TURN_DEG`` of the length, where it's widest: an end cut off at a slant is still square."""
    from shapely import affinity

    best = 0.0
    for deg in np.arange(-END_TURN_DEG, END_TURN_DEG + 0.5, 1.0):
        q = affinity.rotate(poly, deg, origin="centroid")
        _, y0, _, y1 = q.bounds
        best = max(best, _width_at(q, y1 - END_PROBE_MM if end > 0 else y0 + END_PROBE_MM))
    return best / width


def measure(placed) -> dict:
    """A prepared foot (toes toward +y) -> the outline's length and width, and how square each end is.

    ``toe_end`` and ``heel_end``: see ``_end_share``. ``ball_at``: where the foot is widest, as a share
    of the length from the heel. ``toe_tip_above_floor_mm``: the lowest point of the front
    ``END_PROBE_MM`` (recorded, not judged: relaxed toes hang up off the floor in a sole scan)."""
    from .. import insole
    from . import foot_prep

    poly = _along_its_length(insole.silhouette(placed))
    _, y0, _, y1 = poly.bounds
    L = y1 - y0
    ys = np.arange(y0 + 0.5, y1, 1.0)
    widths = np.array([_width_at(poly, y) for y in ys])
    W = float(widths.max())
    W_heel = float(widths[ys < y0 + HEEL_SHARE * L].max())  # the heel, narrower than the ball
    V = np.asarray(placed.vertices)
    ymax = V[V[:, 2] < insole.SILHOUETTE_HEIGHT_MM, 1].max()
    front = V[(V[:, 1] > ymax - END_PROBE_MM) & (V[:, 2] < insole.SILHOUETTE_HEIGHT_MM)]
    return dict(
        length_mm=round(float(L), 1), width_mm=round(W, 1),
        toe_end=round(_end_share(poly, +1, W), 2), heel_end=round(_end_share(poly, -1, W_heel), 2),
        ball_at=round(float((ys[int(np.argmax(widths))] - y0) / L), 2),
        toe_tip_above_floor_mm=round(float(front[:, 2].min()), 1) if len(front) else None,
        measured_as=foot_prep.prep_version(),  # see server.other_scans: measures taken another way are taken again
    )


def problems(m: dict) -> list[str]:
    """What's missing from a scan, in plain words (each ends with what to do), from ``measure``'s result.

    The toes and the heel first. Then, if both ends look whole, is the outline one foot at all? Its length
    and width against foot_prep's limits for an adult foot (the same ones Make insole warns with). The
    legs-flat scan LIDAR_nwb_relaxed_L_20261027-151815-2190 caught both feet merged into one piece:
    264.9 x 254.3 mm, its ends round. (In that order because a foot without its toes is short for its
    width too: the synthetic foot cut 50 mm short is 200 x 100 mm, wider for its length than the limit.)"""
    from . import foot_prep

    out = []
    if m["toe_end"] > TOE_END_SQUARE:
        out.append(f"THE TOES ARE MISSING: the front of the scan ends square ({m['toe_end']:.0%} of the foot's width "
                   f"{END_PROBE_MM:.0f} mm from its end), where toes would round off. They were cut off or curled up "
                   "out of the scan, so the insole would be too short. Scan again with the toes relaxed and flat, "
                   "and the phone going all the way round them.")
    if m["heel_end"] > HEEL_END_SQUARE:
        out.append(f"THE HEEL IS CUT OFF: the back of the scan ends square ({m['heel_end']:.0%} of the foot's width "
                   f"{END_PROBE_MM:.0f} mm from its end), where a heel rounds off. Its back wasn't scanned, so the "
                   "insole's length and heel cup would be wrong. Scan again, taking the phone round behind the heel.")
    L, W = m["length_mm"], m["width_mm"]
    lo, hi = foot_prep.FOOT_RATIO
    one_foot = foot_prep.FOOT_LENGTH_MM[0] <= L <= foot_prep.FOOT_LENGTH_MM[1] and lo <= W / max(L, 1e-9) <= hi
    if not out and not one_foot:
        out.append(f"THIS ISN'T ONE WHOLE FOOT: seen from above the scan is {L:.0f} x {W:.0f} mm, but a foot is about "
                   f"{foot_prep.FOOT_LENGTH_MM[0]:.0f}-{foot_prep.FOOT_LENGTH_MM[1]:.0f} mm long and {lo:.2f}-{hi:.2f} "
                   "times as wide as long. Both feet may have been caught together, or part of the bed or leg. Scan "
                   "again with only this foot in view, the other foot well out of the way.")
    return out


def against_others(m: dict, others: list[dict]) -> list[str]:
    """Compared with the person's other scans: ``others`` is [{"foot", "same_foot", "capture_id", "length_mm"}].

    Shorter by more than ``SHORTER_THAN_OTHER_MM`` than any of them: an end is probably missing from
    this one. (Longer is not judged here: then the other scan is the one to doubt.)"""
    out = []
    for o in others:
        d = o["length_mm"] - m["length_mm"]
        if d > SHORTER_THAN_OTHER_MM:
            whose = f"an earlier scan of the same foot ({o['capture_id']})" if o["same_foot"] else \
                f"your {o['foot']} foot's scan ({o['capture_id']})"
            out.append(f"THIS FOOT IS {d:.0f} MM SHORTER than {whose}: {m['length_mm']:.0f} against "
                       f"{o['length_mm']:.0f} mm. The toes or the heel are probably missing from this scan. "
                       "Scan again with the whole foot in view, toes flat and the heel included.")
    return out


def from_prep(info: dict) -> list[str]:
    """What the preparation (foot_prep) already found missing or wrong, worded for a retake: the heel's
    underside (the back of the scan far above the floor), open edges near the floor (a torn-off part), a
    front too steep to be toes hanging up (left as scanned, so short), and a forefoot rolled onto one edge
    (the insole would fill under the raised side: a wedge, which a first fit must not have). Make insole
    warns about the same (foot_prep.plausibility); on arrival they refuse the scan."""
    from . import foot_prep

    out = []
    if info.get("heel_back_above_floor_mm", 0.0) > foot_prep.HEEL_OFF_FLOOR_MM:
        out.append(f"THE HEEL IS MISSING: the back of the scan is {info['heel_back_above_floor_mm']:.0f} mm above the "
                   "floor, but a heel rests on it, so the underside of the heel wasn't scanned. Scan again, taking the "
                   "phone round behind and under the heel.")
    if "toes_warning" in info:
        out.append(info["toes_warning"])
    if info.get("open_edges_near_floor_mm", 0.0) > foot_prep.OPEN_EDGE_WARN_MM:
        if "two_feet_note" in info:
            # cut apart from the other foot (foot_prep._one_foot): the side they touched along was never scanned
            out.append(f"PART OF THE FOOT IS MISSING: both feet were in the scan, touching, so the side of this one "
                       f"that lay against the other wasn't scanned ({info['open_edges_near_floor_mm']:.0f} mm of "
                       "open edges near the floor once they were cut apart). Scan again with the other foot out of "
                       "the box.")
        else:
            out.append(f"PART OF THE FOOT IS MISSING: the scan is torn open near the floor "
                       f"({info['open_edges_near_floor_mm']:.0f} mm of open edges), where the toes, the heel or a side "
                       "should be. Scan again, covering the whole foot.")
    sides = info.get("ball_sides_above_floor_mm")
    if sides and abs(sides["plus_x"] - sides["minus_x"]) > foot_prep.BALL_ROLL_WARN_MM:
        out.append(f"THE FOREFOOT WAS ROLLED ONTO ONE EDGE: one side of the ball of the foot is "
                   f"{abs(sides['plus_x'] - sides['minus_x']):.0f} mm higher than the other, so the insole would put "
                   "a wedge under it. Scan again with the ankle held at a right angle and the sole facing straight up.")
    return out
