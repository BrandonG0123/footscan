"""The printed clog: generated shapes and synthetic feet with known answers. No number here is from a person.

A shoe built from two ruler numbers alone has a flat footbed; one built on ``synth.curved_foot`` (a SYNTHETIC
foot whose arch stands 14 mm off the floor on the inner side) must carry that foot's first-fit fill in its
floor: the arch less the insole generator's 1 mm relief, on the inner side only.
Shoe coordinates: x forward from the back of the shoe, y toward the foot's left (a right foot's inner side is
+y), z up, the sole on z = 0.
"""

import json
from dataclasses import fields, replace

import numpy as np
import pytest

import synth
from footscan import cli, footwear as fw, insole

RULER = dict(foot_length_mm=260.0, foot_width_mm=97.0)


@pytest.fixture(scope="module")
def plain():
    """A closed-upper shoe from ruler numbers alone: no windows for a probing ray to slip through."""
    return fw.build("right", fw.ShoeParams(style="stone", **RULER))


@pytest.fixture(scope="module")
def curved():
    return insole.from_scan(synth.curved_foot("right", leg=False), "right")


@pytest.fixture(scope="module")
def block():
    """The first-fit insole of the SYNTHETIC block foot (a right one): 11 mm of fill under its arch tunnel, none elsewhere."""
    return insole.from_scan(synth.block_foot(37.0, "right"), "right")


@pytest.fixture(scope="module")
def shod(curved):
    """The default shoe on the SYNTHETIC curved foot's footbed, sized by that foot's own outline."""
    return fw.build("right", fw.ShoeParams(), footbed=curved)


def _hit(mesh, origin, direction):
    """Where a ray from ``origin`` first meets the shoe (None if it meets nothing)."""
    hit, _, _ = mesh.ray.intersects_location([origin], [direction], multiple_hits=False)
    return hit[0] if len(hit) else None


def _floor(mesh, x, y, from_z=45.0):
    """Height of the footbed at (x, y): a ray straight down from inside the shoe."""
    hit = _hit(mesh, [x, y, from_z], [0, 0, -1.0])
    return None if hit is None else float(hit[2])


def test_the_shoe_is_one_closed_solid_standing_on_its_sole(plain, shod):
    for shoe in (plain, shod):
        m = shoe.mesh
        assert m.is_watertight and m.is_winding_consistent and m.volume > 0
        assert m.body_count == 1
        assert m.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-6)   # flat on the bed
        assert m.vertices[:, 0].min() == pytest.approx(0.0, abs=1e-6)   # the back of the shoe at x = 0


def test_no_two_points_of_the_surface_are_a_hair_apart(shod, tmp_path):
    """Cutting the footbed, the opening and the windows leaves hair-length edges; they are welded, so the file
    a slicer reads (rounded to single precision) is still one closed surface."""
    import trimesh
    from scipy.spatial import cKDTree

    assert len(cKDTree(shod.mesh.vertices).query_pairs(fw.WELD_MM)) == 0
    shod.mesh.export(tmp_path / "shoe.stl")
    back = trimesh.load(tmp_path / "shoe.stl")   # an STL has no shared points: they are merged again on reading
    assert back.is_watertight and back.volume == pytest.approx(shod.mesh.volume, rel=1e-4)


@pytest.mark.parametrize("fit", ["snug", "regular", "roomy"])
def test_the_inside_is_the_foot_plus_the_fits_room(fit):
    shoe = fw.build("right", fw.ShoeParams(style="stone", fit=fit, **RULER))
    r, room = shoe.report, fw.FIT[fit]
    assert r["inside"]["length_mm"] == pytest.approx(260.0 + room["toe_room_mm"], abs=0.1)
    assert r["inside"]["width_mm"] == pytest.approx(97.0 + room["width_mm"], abs=0.1)
    assert r["made_for"] == dict(foot_length_mm=260.0, foot_width_mm=97.0, length_from="ruler", width_from="ruler",
                                 fit=fit, sock_mm=0.0)
    # and the shoe itself measures that, not just its report. Length: from the back wall where a heel reaches
    # it (20 mm above the footbed) to the front wall where the toes do (10 mm above it)
    m, sole = shoe.mesh, r["sole"]
    back = min(_hit(m, [60.0, y, sole["under_heel_mm"] + 20.0], [-1.0, 0, 0])[0] for y in np.linspace(-12, 12, 9))
    front = max(_hit(m, [200.0, y, sole["under_ball_mm"] + 10.0], [1.0, 0, 0])[0] for y in np.linspace(-10, 30, 21))
    assert front - back == pytest.approx(r["inside"]["length_mm"], abs=1.0)
    # width: the furthest the walls stand apart across the ball, 12 mm above the footbed
    xs = np.linspace(0.5, 0.9, 41) * r["length_mm"]
    z = sole["under_ball_mm"] + 12.0
    inner = max(_hit(m, [x, 0.0, z + 4.0 * (x < 170)], [0, 1.0, 0])[1] for x in xs)
    outer = min(_hit(m, [x, 0.0, z + 4.0 * (x < 170)], [0, -1.0, 0])[1] for x in xs)
    assert inner - outer == pytest.approx(r["inside"]["width_mm"], abs=1.0)


def test_a_thicker_sock_adds_room_all_round():
    bare = fw.build("right", fw.ShoeParams(style="stone", **RULER)).report["inside"]
    sock = fw.build("right", fw.ShoeParams(style="stone", sock_mm=1.5, **RULER)).report["inside"]
    assert sock["length_mm"] == pytest.approx(bare["length_mm"] + 1.5, abs=0.1)
    assert sock["width_mm"] == pytest.approx(bare["width_mm"] + 3.0, abs=0.1)
    assert sock["roof_over_ball_mm"] == pytest.approx(bare["roof_over_ball_mm"] + 1.5, abs=0.3)


def test_a_long_narrow_foot_gets_a_normal_shoe_not_a_long_thin_one():
    """The foot sets the size; the proportions stay a shoe's. Too narrow or too wide for its length, the inside
    is held at the nearest normal width and the shoe says how far off the foot's own width that is."""
    narrow = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=280.0, foot_width_mm=70.0)).report
    assert narrow["inside"]["width_mm"] == pytest.approx(fw.BALL_SHARE[0] * narrow["inside"]["length_mm"], abs=0.2)
    assert any("narrow for its length" in w and "room at the sides" in w for w in narrow["warnings"])
    wide = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=125.0)).report
    assert wide["inside"]["width_mm"] == pytest.approx(fw.BALL_SHARE[1] * wide["inside"]["length_mm"], abs=0.2)
    assert any("wide for its length" in w and "tight" in w for w in wide["warnings"])
    usual = fw.build("right", fw.ShoeParams(style="stone", **RULER)).report
    assert not any("for its length" in w for w in usual["warnings"])


def test_left_is_the_mirror_of_right(plain):
    left = fw.build("left", plain.params)
    assert left.mesh.is_watertight and left.mesh.volume == pytest.approx(plain.mesh.volume, rel=1e-6)
    a = np.asarray(plain.mesh.vertices)
    b = np.asarray(left.mesh.vertices) * [1.0, -1.0, 1.0]
    assert len(a) == len(b)
    key = lambda v: v[np.lexsort(np.round(v, 2).T[::-1])]  # noqa: E731
    assert np.abs(np.sort(a, axis=0) - np.sort(b, axis=0)).max() < 1e-3   # the same points, each axis in order
    assert np.abs(key(a) - key(b)).max() < 0.05
    assert {k: v for k, v in left.report.items() if k not in ("foot", "bed_fit")} == \
           {k: v for k, v in plain.report.items() if k not in ("foot", "bed_fit")}


def test_the_front_is_closed_and_the_back_is_open(plain):
    m, r = plain.mesh, plain.report
    heel, ball = r["sole"]["under_heel_mm"], r["sole"]["under_ball_mm"]
    # over the toes a ray from above lands on the roof, well above the footbed...
    assert _hit(m, [0.85 * r["length_mm"], 5.0, 300.0], [0, 0, -1.0])[2] > ball + 25.0
    # ...and over the heel it goes straight in, down to the footbed
    assert _hit(m, [40.0, 0.0, 300.0], [0, 0, -1.0])[2] == pytest.approx(heel, abs=0.05)
    # behind the heel: a lip up to heel_rim_mm above the footbed, nothing above it until the instep
    assert _hit(m, [-50.0, 0.0, heel + r["heel_rim_mm"] - 4.0], [1.0, 0, 0])[0] < 1.0
    over_the_lip = _hit(m, [-50.0, 0.0, heel + r["heel_rim_mm"] + 4.0], [1.0, 0, 0])
    assert over_the_lip is None or over_the_lip[0] > 0.3 * r["length_mm"]


def test_the_floor_has_no_sideways_tilt(plain):
    """A heel-to-ball drop is front to back only. Any tilt across the foot would be posting, which a first fit
    never has: the shoe has no setting for it, and its floor is level across at every point along it."""
    assert not any("post" in f.name or "tilt" in f.name or "wedge" in f.name for f in fields(fw.ShoeParams))
    r = plain.report
    for x in np.linspace(30.0, 0.8 * r["length_mm"], 12):
        assert _floor(plain.mesh, x, 14.0) == pytest.approx(_floor(plain.mesh, x, -14.0), abs=0.02)
    assert _floor(plain.mesh, 40.0, 0.0) - _floor(plain.mesh, 0.72 * r["length_mm"], 0.0) == pytest.approx(plain.params.drop_mm, abs=0.05)


@pytest.mark.parametrize("foot, inner", [("right", 1.0), ("left", -1.0)])
def test_the_footbed_is_the_first_fit_insoles_surface_built_into_the_floor(foot, inner):
    """SYNTHETIC block foot: 240 x 90 mm, a 12 mm-high tunnel under its inner 36 mm from 70 to 150 mm. Its
    first-fit fill is 11 mm there (12 less the relief) and nothing anywhere else, and that is exactly what the
    shoe's floor carries: under the arch, on the inner side only (a left foot's is the other side), no higher
    than the insole generator made it."""
    block = insole.from_scan(synth.block_foot(37.0, foot), foot)
    shoe = fw.build(foot, fw.ShoeParams(style="stone"), footbed=block)
    fb = shoe.report["footbed"]
    assert fb["max_fill_mm"] == block.report["max_fill_mm"] == pytest.approx(11.0, abs=0.05)
    assert fb["posting_deg"] == dict(rearfoot=0.0, forefoot=0.0) and fb["relief_mm"] == block.params.relief_mm
    assert shoe.report["made_for"] == dict(foot_length_mm=240.0, foot_width_mm=90.0, length_from="scan", width_from="scan",
                                           fit="regular", sock_mm=0.0)
    assert fb["scaled_percent"] == 0.0
    # the same shoe with a flat floor: the difference between the two floors is the fill. The foot's heel
    # stands 3.5 mm in from the back of the shoe (the upper, and the rounding of the heel's end)
    flat = fw.build(foot, replace(shoe.params, foot_length_mm=240.0, foot_width_mm=90.0))
    assert flat.report["inside"] == shoe.report["inside"]
    fill = {(x, y): _floor(shoe.mesh, x, inner * y, 36.0) - _floor(flat.mesh, x, inner * y, 36.0)   # y: toward the inner side
            for x in np.arange(40.0, 205.0, 5.0) for y in np.arange(-30.0, 31.0, 3.0)}
    for (x, y), f in fill.items():
        if 85.0 <= x <= 140.0 and y >= 15.0:
            assert f == pytest.approx(11.0, abs=0.1), (x, y)          # under the tunnel
        elif x <= 65.0 or x >= 160.0 or y <= 0.0:
            assert abs(f) < 0.05, (x, y)                              # heel, ball, toes and the whole outer side
        assert -0.05 < f < 11.05, (x, y)                              # never above the insole's own fill
    # a block's square toes don't fit a shoe's rounded front, and the shoe says so
    assert any("wider than the shoe's inside at the toes" in w for w in shoe.report["warnings"])


def test_a_real_shaped_footbed_stays_within_the_insoles_own_fill(curved, shod):
    """SYNTHETIC curved foot (a smooth 14 mm arch on the inner side): the floor rises under the arch on the
    inner side, rests flat under the heel and along the outer side, and is nowhere above the insole's fill."""
    fb = shod.report["footbed"]
    assert fb["max_fill_mm"] == pytest.approx(curved.report["max_fill_mm"], abs=0.05)
    flat = fw.build("right", replace(shod.params, foot_length_mm=fb["scan_length_mm"], foot_width_mm=fb["scan_width_mm"]))
    fill = {(x, y): _floor(shod.mesh, x, y) - _floor(flat.mesh, x, y)
            for x in np.arange(70.0, 160.0, 5.0) for y in np.arange(-24.0, 33.0, 4.0)}
    highest = max(fill, key=fill.get)
    assert 0.7 * fb["max_fill_mm"] < fill[highest] <= fb["max_fill_mm"] + 0.1
    assert highest[1] > 10.0 and 95.0 < highest[0] < 135.0            # under the arch, on the inner side
    assert max(v for (x, y), v in fill.items() if -20.0 <= y <= -4.0) < 0.5   # the outer side rests flat
    assert min(fill.values()) > -0.05
    assert _floor(shod.mesh, 35.0, 0.0) == pytest.approx(_floor(flat.mesh, 35.0, 0.0), abs=0.3)   # under the heel


def test_a_ruler_wins_over_the_scans_size_and_the_footbed_is_scaled_to_it(curved, shod):
    fb = shod.report["footbed"]
    longer = fw.build("right", fw.ShoeParams(foot_length_mm=round(fb["scan_length_mm"] * 1.05, 1),
                                             foot_width_mm=fb["scan_width_mm"]), footbed=curved)
    r = longer.report
    assert r["made_for"]["length_from"] == "ruler" and r["made_for"]["foot_length_mm"] == pytest.approx(fb["scan_length_mm"] * 1.05, abs=0.06)
    assert r["inside"]["length_mm"] == pytest.approx(r["made_for"]["foot_length_mm"] + 12.0, abs=0.1)
    assert r["footbed"]["scaled_percent"] == pytest.approx(5.0, abs=0.1)
    assert r["footbed"]["max_fill_mm"] == pytest.approx(fb["max_fill_mm"], abs=0.05)   # heights are never scaled
    assert any("sized by the ruler" in w and "scaled +5.0% along and across" in w for w in r["warnings"])
    assert not any("scaled" in w for w in shod.report["warnings"])
    with pytest.raises(fw.FootwearError, match="mm long and the ruler .* too far apart to be the same foot"):
        fw.build("right", fw.ShoeParams(foot_length_mm=round(fb["scan_length_mm"] * 1.2, 1), foot_width_mm=fb["scan_width_mm"]),
                 footbed=curved)


def test_a_scan_that_reads_short_is_scaled_the_same_along_and_across_and_no_higher(block):
    """SYNTHETIC block foot (240 mm long, its fill a level 11 mm over the 80 x 36 mm arch tunnel), given a ruler
    length of 264 mm: the scan reads 10% short, so the patch of fill is 10% longer and 10% wider (1.21 times
    the area), and still 11 mm high."""
    import shapely

    def patch(length):
        bed = fw.Footbed(block, "right")
        bed.size_to(length, None)
        p = fw.ShoeParams(style="stone")
        loft = fw._loft_for(fw.size_inside(length or 240.0, 99.0, p), p, 13.0, 0.0, 0)
        bed.place(loft.floor.polygon, loft.inside_ends()[0])
        foot = bed.in_shoe("outline")
        x0, y0, x1, y1 = foot.bounds
        X, Y = np.meshgrid(np.arange(x0, x1, 0.25), np.arange(y0, y1, 0.25))
        H = np.where(shapely.contains_xy(foot, X, Y), bed.height(X, Y), 0.0)
        return (H > 5.5).sum() * 0.25 ** 2, np.ptp(X[H > 5.5]), H.max(), foot.bounds[2] - foot.bounds[0]

    (area, along, top, length), (area2, along2, top2, length2) = patch(None), patch(264.0)
    assert area == pytest.approx(80.0 * 36.0, rel=0.02) and along == pytest.approx(80.0, abs=1.0)
    assert area2 / area == pytest.approx(1.21, abs=0.01) and along2 / along == pytest.approx(1.10, abs=0.01)
    assert top == pytest.approx(11.0, abs=0.05) and top2 == pytest.approx(11.0, abs=0.05)
    assert length2 / length == pytest.approx(1.10, abs=0.005)


def test_the_rulers_width_sizes_the_shoe_and_is_only_compared_with_the_scans(block):
    """SYNTHETIC block foot, 90 mm across. A ruler's width sets the shoe's width and never stretches the
    footbed; a few percent between the two is a standing foot spreading and isn't mentioned, more is said, and
    far more isn't the same foot."""
    near = fw.build("right", fw.ShoeParams(style="stone", foot_width_mm=93.0), footbed=block).report
    assert near["made_for"]["width_from"] == "ruler" and near["inside"]["width_mm"] == pytest.approx(95.0, abs=0.1)
    assert near["footbed"]["scaled_percent"] == 0.0 and not any("across the ball" in w for w in near["warnings"])
    far = fw.build("right", fw.ShoeParams(style="stone", foot_width_mm=98.0), footbed=block).report
    assert far["footbed"]["scaled_percent"] == 0.0
    assert any("90.0 mm across the ball, the ruler 98.0 mm" in w and "worth measuring again" in w for w in far["warnings"])
    with pytest.raises(fw.FootwearError, match="across the ball and the ruler 110 mm: too far apart"):
        fw.build("right", fw.ShoeParams(style="stone", foot_width_mm=110.0), footbed=block)


def test_a_ruler_length_alone_scales_the_scans_width_with_it(block):
    """SYNTHETIC block foot, 240 x 90 mm as scanned, given only a ruler length of 252 mm (5% longer): the
    footbed is scaled 5% along and across, so the shoe is sized for the foot it holds, 94.5 mm across, not
    for the scan's 90."""
    r = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=252.0), footbed=block).report
    assert r["footbed"]["scaled_percent"] == pytest.approx(5.0, abs=0.05)
    assert r["made_for"]["width_from"] == "scan" and r["made_for"]["foot_width_mm"] == pytest.approx(94.5, abs=0.1)
    assert r["inside"]["width_mm"] == pytest.approx(94.5 + 2.0, abs=0.1)        # the regular fit's ease


def test_a_foot_wide_for_its_length_is_let_out_at_the_ball_and_not_told_it_may_be_tight():
    """SYNTHETIC block foot made 20% wider (240 x 108 mm): wider than a normal shoe's proportions allow, so the
    standard shape is narrower than the fit alone would make it. The scan shows the foot there, so the walls
    are let out for it across the ball, and the sheet says that instead of 'it may be tight'. From ruler
    numbers alone nothing can be let out, and the warning stays."""
    m = synth.block_foot(0.0, "right")
    m.apply_transform(np.diag([1.0, 1.2, 1.0, 1.0]))
    wide = insole.from_scan(m, "right")
    r = fw.build("right", fw.ShoeParams(style="stone"), footbed=wide).report
    note = [w for w in r["warnings"] if "wide for its length" in w]
    assert len(note) == 1 and "may be tight" not in note[0] and "let out" in note[0]
    let = r["footbed"]["let_out"]
    assert let["inner"]["max_mm"] > 1.0 and let["outer"]["max_mm"] > 1.0
    assert not r["footbed"]["overhang"]["where"] or "ball" not in r["footbed"]["overhang"]["where"]
    ruler = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=108.0)).report
    assert any("wide for its length" in w and "may be tight across the ball" in w for w in ruler["warnings"])


def _wall(mesh, x, z, toward):
    """Where the inside's wall stands at (x, z): a level ray from the middle of the shoe toward +y or -y."""
    return float(_hit(mesh, [x, 0.0, z], [0.0, toward, 0.0])[1])


def _skin(mesh, x, z, side):
    """Where the outside stands at (x, z) on the +y or -y side: a level ray from far outside, inward."""
    return float(_hit(mesh, [x, 200.0 * side, z], [0.0, -side, 0.0])[1])


def test_the_wall_is_let_out_where_the_foot_is_wider_above_the_floor_and_the_sole_stands_under_it(block):
    """SYNTHETIC: the block foot with a 10 mm block standing out of its inner side from 14 to 25 mm up, over
    95 to 135 mm from the heel (as a flat foot's inner side stands out over its own footprint). What stands on
    the floor is the same foot, so it is stood in the shoe exactly as without the bulge; the inner wall is
    10 mm further out beside the bulge and nowhere else, the outside and the sole with it (the ground under
    the let-out wall), and the footbed under the bulge is its underside less the relief."""
    bulged = insole.from_scan(synth.block_foot(37.0, "right", inner_bulge=10.0), "right")
    p = fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=90.0)
    a, b = fw.build("right", p, footbed=block), fw.build("right", p, footbed=bulged)
    fa, fb = a.report["footbed"], b.report["footbed"]
    assert (fb["turned_deg"], fb["slid_mm"]) == (fa["turned_deg"], fa["slid_mm"])     # stood by its sole
    assert a.report["inside"] == b.report["inside"]                                    # the same standard shape
    assert fb["let_out"]["inner"]["max_mm"] == pytest.approx(fa["let_out"]["inner"]["max_mm"] + 10.0, abs=1.0)
    assert fb["let_out"]["outer"] == fa["let_out"]["outer"]
    assert any("wider above the floor than the standard shape on its inner side" in w for w in b.report["warnings"])
    for x in (105.0, 118.0, 130.0):                       # beside the bulge (the heel stands 3.5 mm into the shoe)
        assert _wall(b.mesh, x, 38.0, 1.0) - _wall(a.mesh, x, 38.0, 1.0) == pytest.approx(10.0, abs=0.7), x
        assert _wall(b.mesh, x, 38.0, -1.0) == pytest.approx(_wall(a.mesh, x, 38.0, -1.0), abs=0.05), x
        for z in (2.0, 10.0, 30.0):                       # the sole's side near the ground and half way up, the upper
            assert _skin(b.mesh, x, z, 1.0) - _skin(a.mesh, x, z, 1.0) == pytest.approx(10.0, abs=0.7), (x, z)
            assert _skin(b.mesh, x, z, -1.0) == pytest.approx(_skin(a.mesh, x, z, -1.0), abs=0.05), (x, z)
    for x in (45.0, 175.0):                               # well behind it and well in front: as without
        assert _wall(b.mesh, x, 38.0, 1.0) == pytest.approx(_wall(a.mesh, x, 38.0, 1.0), abs=0.3), x
    # the bulge is held: what still hangs over is the block's square toes, as without it
    assert fb["overhang"]["where"] == "toes" and fb["overhang"]["max_mm"] == pytest.approx(fa["overhang"]["max_mm"], abs=0.5)
    # under the bulge the footbed is its underside (14 mm up) less the 1 mm relief; beside it, the tunnel's 11
    edge = _wall(a.mesh, 118.0, 38.0, 1.0)
    assert _floor(b.mesh, 118.0, edge + 5.0) - _floor(a.mesh, 118.0, edge - 12.0) == pytest.approx(13.0 - 11.0, abs=0.15)
    # ruler numbers alone: nothing is known of the foot's sides, so nothing is let out
    assert fw.build("right", p).report["footbed"] is None


def test_what_stands_out_above_the_floor_does_not_move_where_the_foot_stands(block):
    """Two made-up feet with the same outline near the floor (the shoe's own floor outline, 8 mm smaller all
    round, a rubber band round it), one of them up to 17 mm wider above the floor along its inner side from
    heel to arch, as a flat foot is. Both are stood in the shoe in exactly the same place: a foot stands where
    its sole does. (Stood by its whole outline instead, the wider one is moved toward its bulge.)"""
    import shapely

    p = fw.ShoeParams(style="stone")
    loft = fw._loft_for(fw.size_inside(240.0, 90.0, p), p, 13.0, 0.0, 0)
    floor, L = loft.floor.polygon, loft.L
    standing = floor.buffer(-8.0).convex_hull
    bulge = floor.buffer(9.0).intersection(shapely.box(0.15 * L, float(loft.floor.middle(0.3 * L)), 0.5 * L, 200.0))
    fits = []
    for whole in (standing, standing.union(bulge)):
        bed = fw.Footbed(block, "right")
        bed.outline, bed.standing, bed.heel_x = whole, standing, whole.bounds[0]
        fits.append(bed.place(floor, loft.inside_ends()[0]))
        assert bed.in_shoe("standing").difference(floor).area == 0.0     # the sole is on the floor
    assert (fits[0]["turned_deg"], fits[0]["slid_mm"]) == (fits[1]["turned_deg"], fits[1]["slid_mm"])


def test_the_shoe_is_never_narrower_than_the_standard_shape(block):
    """SYNTHETIC block foot (90 mm across) in a shoe sized by a ruler width of 98 mm: across the ball the
    standard shape is wider than the scanned foot, and stays exactly as wide (letting out only ever adds room);
    further back, where the block's straight sides are wider than a shoe's waist, it is wider than standard."""
    p = fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=98.0)
    scanned, standard = fw.build("right", p, footbed=block), fw.build("right", p)
    for x in np.arange(40.0, 215.0, 12.5):
        for side in (1.0, -1.0):
            more = side * (_wall(scanned.mesh, x, 36.0, side) - _wall(standard.mesh, x, 36.0, side))
            assert more > -0.05, (x, side)
            if 175.0 <= x <= 195.0:
                assert abs(more) < 0.05, (x, side)                      # across the ball: the standard shape
    assert max(_wall(scanned.mesh, x, 36.0, 1.0) - _wall(standard.mesh, x, 36.0, 1.0) for x in (90.0, 105.0, 120.0)) > 2.0


def test_a_foot_too_wide_to_let_out_for_is_let_out_to_the_limit_and_the_rest_is_said(block):
    """SYNTHETIC: the block foot with a 40 mm block standing out of its inner side. The inside is let out by
    the limit and no more, and the sheet says where the foot is still wider than the shoe."""
    wide = insole.from_scan(synth.block_foot(37.0, "right", inner_bulge=40.0), "right")
    p = fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=90.0)
    r = fw.build("right", p, footbed=wide).report
    assert r["footbed"]["let_out"]["inner"]["max_mm"] == pytest.approx(fw.LET_OUT_MAX_MM, abs=0.1)
    plain = fw.build("right", p, footbed=block).report["footbed"]["let_out"]["inner"]["max_mm"]
    over = r["footbed"]["overhang"]
    assert over["where"] == "arch, inner side" and over["max_mm"] == pytest.approx(plain + 40.0 - fw.LET_OUT_MAX_MM, abs=1.0)
    assert any("wider than the shoe's inside at the arch, inner side" in w and "It may press there" in w for w in r["warnings"])


def test_the_whole_heel_goes_against_the_back_not_only_its_footprint(block):
    """SYNTHETIC: the block foot with a 4 mm block standing out of the back of its heel from 14 to 25 mm up (a
    heel reaches further back above the floor than on it). The foot is 244 mm long then, the inside 12 mm
    longer than that, and the foot stands with that bulge against the back: the same room past its toes as
    the plain block has, and nothing hanging over behind."""
    heeled = insole.from_scan(synth.block_foot(37.0, "right", heel_bulge=4.0), "right")
    p = fw.ShoeParams(style="stone")
    a, b = fw.build("right", p, footbed=block).report, fw.build("right", p, footbed=heeled).report
    assert b["made_for"]["foot_length_mm"] == pytest.approx(244.0, abs=0.1) and b["inside"]["length_mm"] == pytest.approx(256.0, abs=0.1)
    assert b["footbed"]["room_past_scanned_toes_mm"] == pytest.approx(a["footbed"]["room_past_scanned_toes_mm"], abs=0.3)
    assert b["footbed"]["room_past_scanned_toes_mm"] == pytest.approx(12.0, abs=1.5)   # (less what the turn takes)
    assert (b["footbed"]["turned_deg"], b["footbed"]["slid_mm"]) == (a["footbed"]["turned_deg"], a["footbed"]["slid_mm"])
    assert b["footbed"]["overhang"]["where"] == "toes"


def test_the_footbed_runs_level_past_the_foots_edge_without_the_dip_the_insole_has_there(block):
    """SYNTHETIC block foot: its tunnel runs out through the inner side, so the true fill is a level 11 mm right
    up to the foot's edge. The insole's own surface dips at that edge (its smoothing blends in the bare floor
    beside the foot); the shoe's footbed doesn't build the dip in: just inside the edge, at it and past it, it
    is what the insole's surface is 3 mm in, and never above the true 11 mm."""
    s = block.surface
    j = int(np.argmin(abs(s["xs"] - 110.0)))
    under = np.flatnonzero(s["under_foot"][:, j])
    assert s["fill"][under[-1], j] < 7.0 and s["fill"][under[-7], j] == pytest.approx(10.84, abs=0.1)   # the insole's dip
    bed = fw.Footbed(block, "right")
    p = fw.ShoeParams(style="stone")
    loft = fw._loft_for(fw.size_inside(240.0, 90.0, p), p, 13.0, 0.0, 0)
    bed.place(loft.floor.polygon, loft.inside_ends()[0])
    foot = bed.in_shoe("outline")
    for x in foot.bounds[0] + np.array([95.0, 110.0, 130.0]):
        edge = fw._across(foot, np.array([x]))[1][0]                  # the foot's inner edge here
        h = bed.height(np.full(7, x), edge + np.array([-3.5, -2.0, -1.0, -0.25, 0.5, 2.0, 5.0]))
        assert np.all(np.abs(h - 10.85) < 0.2) and h.max() <= 11.0, (x, h)


def test_the_footbed_climbs_between_the_insoles_two_caps_instead_of_stepping(block):
    """SYNTHETIC: an insole whose fill stands at both of the generator's caps, 12 mm round the heel and 20 mm
    from there on (as a sole that is high everywhere would leave it), so its surface steps 8 mm on the line
    where the heel zone ends (30% of the length). In the shoe that step would be a ledge inside the wall: the
    footbed climbs it over the next 15% of the length instead, never above the insole's own surface."""
    s = block.surface
    x0, length = 0.0, 240.0
    stepped = np.where(s["under_foot"], np.where(s["xs"][None, :] <= x0 + 0.30 * length, 12.0, 20.0), 0.0)
    bed = fw.Footbed(replace(block, surface={**s, "fill": stepped}), "right")
    p = fw.ShoeParams(style="stone")
    loft = fw._loft_for(fw.size_inside(240.0, 90.0, p), p, 13.0, 0.0, 0)
    fit = bed.place(loft.floor.polygon, loft.inside_ends()[0])
    heel = bed.in_shoe("outline").bounds[0]
    x = heel + np.arange(20.0, 160.0, 0.5)
    h = bed.height(x, np.full(len(x), -10.0))
    assert h[x < heel + 0.29 * length].max() == pytest.approx(12.0, abs=0.01)
    assert h[x > heel + 0.46 * length].min() == pytest.approx(20.0, abs=0.01)
    assert np.abs(np.diff(h)).max() < 0.2                                   # per half millimetre: a slope, not a step
    assert np.all(np.diff(h) > -1e-9)
    assert abs(fit["turned_deg"]) < 3.0                                      # (so "along x" is along the foot)


def test_the_footbed_takes_its_caps_from_the_insole_not_from_a_copy_of_its_rule(curved):
    """SYNTHETIC curved foot: its arch fill stands above the heel's 12 mm cap. The footbed eases between the
    insole's two caps where the insole itself says its heel zone is (``surface["heel_weight"]``): told the
    heel zone runs the whole length, it is capped at the heel's 12 mm everywhere."""
    assert curved.report["max_fill_mm"] > 12.5
    s = curved.surface
    heel_everywhere = replace(curved, surface={**s, "heel_weight": np.ones_like(s["heel_weight"])})
    p = fw.ShoeParams(style="stone")
    for ins, top in ((curved, curved.report["max_fill_mm"]), (heel_everywhere, 12.0)):
        bed = fw.Footbed(ins, "right")
        loft = fw._loft_for(fw.size_inside(bed.scan_length, bed.scan_width, p), p, 13.0, 0.0, 0)
        bed.place(loft.floor.polygon, loft.inside_ends()[0])
        assert bed.highest(loft.inside_widest) == pytest.approx(top, abs=0.05)


def test_the_heel_rim_stands_clear_of_the_footbed_not_only_of_the_floor(plain, block):
    """SYNTHETIC: the block foot's footbed raised 10 mm everywhere under the foot (as a deep heel cup stands
    at the back). A rim 12 mm above the floor, enough over a flat footbed, would stand 2 mm over this one and
    the opening would cut into it, so it is refused; the default rim stands at least ``HEEL_LIP_MIN_MM`` over
    it all along, and the report says how much."""
    s = block.surface
    raised = replace(block, surface={**s, "fill": np.where(s["under_foot"], s["fill"] + 10.0, 0.0)})
    with pytest.raises(fw.FootwearError, match="above the footbed"):
        fw.build("right", fw.ShoeParams(style="stone", heel_rim_mm=12.0), footbed=raised)
    r = fw.build("right", fw.ShoeParams(style="stone"), footbed=raised).report
    assert fw.HEEL_LIP_MIN_MM <= r["rim_over_footbed_mm"] <= r["heel_rim_mm"] - 10.0 + 0.1
    assert plain.report["rim_over_footbed_mm"] == pytest.approx(plain.report["heel_rim_mm"], abs=0.3)


def test_a_style_changes_the_outside_never_the_inside(plain):
    vent = fw.build("right", fw.ShoeParams(style="vent", **RULER))
    stream = fw.build("right", fw.ShoeParams(style="stream", **RULER))
    assert vent.report["inside"] == stream.report["inside"] == plain.report["inside"]
    # the walls stand in the same place: across the shoe 6 mm above the footbed (below any window), at the heel
    # and at the ball; the three soles differ in thickness, so heights are taken from each shoe's own floor
    for x in (45.0, 150.0, 200.0):
        wall = [[_hit(s.mesh, [x, 0.0, _floor(s.mesh, x, 0.0) + 6.0], [0, d, 0])[1] for d in (1.0, -1.0)]
                for s in (plain, vent, stream)]
        assert np.ptp(np.array(wall), axis=0).max() < 0.02
    # what does differ: the windows, the sole's thickness, how far it stands out at the ground
    assert plain.report["pattern"]["count"] == 0 and vent.report["pattern"]["count"] > 50
    assert stream.report["pattern"]["window_mm"][0] > 2 * stream.report["pattern"]["window_mm"][1]
    assert stream.report["sole"]["under_ball_mm"] > vent.report["sole"]["under_ball_mm"] > plain.report["sole"]["under_ball_mm"]
    assert stream.report["width_mm"] > vent.report["width_mm"] > plain.report["width_mm"]
    closed = fw.build("right", fw.ShoeParams(style="vent", openness=0.0, **RULER))
    assert closed.report["pattern"]["count"] == 0 and closed.mesh.volume > vent.mesh.volume + 1000.0


def _cut_area(mesh, origin, normal):
    """How much material a flat cut through the shoe goes through (mm2)."""
    return float(mesh.section(plane_origin=origin, plane_normal=normal).to_2D()[0].area)


def test_windows_stay_out_of_the_sole_the_toe_cap_and_the_heel():
    """The same shoe with its windows as open as they go and with none: cut across through the heel and
    through the toe cap, and level through the sole, the two are the same; only in between do they differ."""
    windowed, closed = (fw.build("right", fw.ShoeParams(style="vent", openness=o, **RULER)) for o in (0.5, 0.0))
    r = windowed.report
    assert windowed.mesh.body_count == 1 and 0.2 < r["pattern"]["openness"] <= 0.5 and r["pattern"]["count"] > 50
    L = r["inside"]["floor_length_mm"]
    cuts = [([x, 0, 0], [1, 0, 0]) for x in np.arange(2.0, fw.END_ROUND[0] * L + 6.0, 2.0)]                      # the heel
    cuts += [([x, 0, 0], [1, 0, 0]) for x in np.arange((1 - fw.END_ROUND[1]) * L, r["length_mm"] - 2.0, 2.0)]   # the toe cap
    cuts += [([0, 0, z], [0, 0, 1]) for z in np.arange(2.0, r["sole"]["under_ball_mm"], 2.0)]                   # the sole
    assert len(cuts) > 30
    for origin, normal in cuts:
        assert _cut_area(windowed.mesh, origin, normal) == pytest.approx(_cut_area(closed.mesh, origin, normal), abs=0.05), origin
    assert _cut_area(windowed.mesh, [0.7 * L, 0, 0], [1, 0, 0]) < _cut_area(closed.mesh, [0.7 * L, 0, 0], [1, 0, 0]) - 5.0
    # the sole: a level cut half way up it is one solid patch with no hole in it
    cut = windowed.mesh.section(plane_origin=[0, 0, r["sole"]["under_ball_mm"] / 2], plane_normal=[0, 0, 1]).to_2D()[0]
    assert len(cut.polygons_full) == 1 and len(cut.polygons_full[0].interiors) == 0
    with pytest.raises(fw.FootwearError, match="between 0 and 0.5"):
        fw.build("right", fw.ShoeParams(style="vent", openness=0.8, **RULER))


def test_windows_keep_clear_of_the_openings_edge():
    """Just under the opening's edge, all the way along it, the wall is whole: a ray from the middle of the
    shoe out to either side meets it where the windowless shoe's wall is."""
    p = fw.ShoeParams(style="vent", openness=0.5, **RULER)
    windowed, closed = fw.build("right", p), fw.build("right", replace(p, openness=0.0))
    st = fw.STYLES["vent"]
    loft = fw._loft_for(fw.size_inside(260.0, 97.0, p), p, st["sole_mm"], st["flare_mm"], st["grooves"])
    edge = fw._opening(loft, p)[0]
    xs = np.arange(0.12 * loft.L, p.throat * loft.L - 8.0, 1.0)
    origins = np.array([[x - loft.x0, float(loft.top_y(x)), float(edge(x)) - below] for x in xs for below in (1.5, 4.0)])
    for side in (1.0, -1.0):
        walls = []
        for shoe in (windowed, closed):
            hit, ray, _ = shoe.mesh.ray.intersects_location(origins, np.tile([0.0, side, 0.0], (len(origins), 1)), multiple_hits=False)
            assert len(hit) == len(origins)
            walls.append(hit[np.argsort(ray), 1])
        assert np.abs(walls[0] - walls[1]).max() < 0.01


def test_no_window_opens_onto_the_footbed():
    """SYNTHETIC: the block foot's fill made 1.6 times as high (17.6 mm, under the 20 mm cap), so the footbed
    stands behind the inner wall where the lowest windows would be. Those windows are left out, and a level cut
    through the footbed there is the same with windows as without."""
    import functools

    import shapely

    block = insole.from_scan(synth.block_foot(37.0, "right"), "right")
    tall = replace(block, surface={**block.surface, "fill": block.surface["fill"] * 1.6})
    p = fw.ShoeParams(style="vent")
    low, high, closed = (fw.build("right", q, footbed=f) for q, f in ((p, block), (p, tall), (replace(p, openness=0.0), tall)))
    assert high.report["footbed"]["max_fill_mm"] == pytest.approx(17.6, abs=0.1)
    assert high.report["pattern"]["count"] < low.report["pattern"]["count"]

    def cut(shoe, z):   # the material a level cut goes through, under the arch on the inner side
        loops = [shapely.Polygon(d[:, :2]) for d in shoe.mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1]).discrete]
        return functools.reduce(lambda a, b: a.symmetric_difference(b), loops).intersection(shapely.box(90.0, 0.0, 135.0, 90.0))

    top = _floor(high.mesh, 110.0, 25.0)                      # the footbed's surface under the arch
    assert top - _floor(low.mesh, 110.0, 25.0) == pytest.approx(0.6 * 11.0, abs=0.15)
    for below in (1.0, 2.5, 4.0):
        assert cut(high, top - below).area == pytest.approx(cut(closed, top - below).area, abs=0.05)


def test_the_upper_is_its_thickness_everywhere_even_where_the_roof_slopes():
    """SYNTHETIC (a generated shape): from points all over the inside's surface, the nearest the outside comes.
    Down the slope from the instep to the toes a roof raised by the thickness straight up would be thinner
    than that measured square to it."""
    import trimesh

    p = fw.ShoeParams(style="stone", **RULER)
    loft = fw._loft_for(fw.size_inside(260.0, 97.0, p), p, 13.0, 0.0, 0)

    def as_mesh(solid):
        mm = solid.to_mesh()
        return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)

    pts, _ = trimesh.sample.sample_surface(as_mesh(loft.inside()), 3000, seed=1)
    pts = pts[pts[:, 2] > loft.floor_z(pts[:, 0]) + 0.5]               # not its floor: the sole is under that
    gap = trimesh.proximity.closest_point(as_mesh(loft.outside()), pts)[1]
    assert gap.min() > 0.92 * p.upper_mm and np.median(gap) == pytest.approx(p.upper_mm, abs=0.1)


@pytest.mark.parametrize("length, width", [(180.0, 68.0), (330.0, 125.0)])
@pytest.mark.parametrize("style, toe, fit", [("vent", "round", "regular"), ("stream", "square", "roomy"), ("stone", "tapered", "snug")])
def test_every_style_builds_at_both_ends_of_adult_sizes(length, width, style, toe, fit):
    shoe = fw.build("right", fw.ShoeParams(foot_length_mm=length, foot_width_mm=width, style=style, toe=toe, fit=fit))
    assert shoe.mesh.is_watertight and shoe.mesh.body_count == 1
    assert shoe.report["inside"]["length_mm"] == pytest.approx(length + fw.FIT[fit]["toe_room_mm"], abs=0.1)
    assert shoe.report["height_mm"] < 0.4 * shoe.report["length_mm"]


def test_the_toe_shape_changes_the_front_only():
    lengths = {}
    for toe in ("tapered", "round", "square"):
        r = fw.build("right", fw.ShoeParams(style="stone", toe=toe, **RULER))
        at = r.mesh.vertices[np.abs(r.mesh.vertices[:, 0] - 0.96 * r.report["length_mm"]) < 1.0]
        lengths[toe] = np.ptp(at[:, 1])
        assert r.report["inside"]["width_mm"] == pytest.approx(99.0, abs=0.1)
    assert lengths["tapered"] + 5.0 < lengths["round"] < lengths["square"] - 5.0   # width across, just behind the tip


def test_a_shoe_too_long_for_the_bed_says_so(plain):
    assert plain.report["bed_fit"]["fits"] and "turned" in plain.report["bed_fit"]["how"]   # 278 mm: only cornerwise
    big = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=320.0, foot_width_mm=118.0)).report
    assert not big["bed_fit"]["fits"]
    assert any("bigger printer" in w for w in big["warnings"])


def test_what_isnt_a_shoe_is_refused(curved):
    for bad in (dict(style="boot"), dict(fit="tight"), dict(toe="pointed"), dict(cushion="hard"), dict(sole_mm=3.0),
                dict(drop_mm=30.0), dict(upper_mm=0.8), dict(throat=0.9), dict(heel_rim_mm=5.0), dict(sock_mm=9.0),
                dict(style="vent", openness=-0.3), dict(style="vent", openness=0.8),
                dict(foot_length_mm=26.0)):                        # centimetres
        with pytest.raises(fw.FootwearError):
            fw.build("right", fw.ShoeParams(**{**RULER, **bad}))
    with pytest.raises(fw.FootwearError, match="length and width"):
        fw.build("right", fw.ShoeParams())                         # no ruler numbers and no scan
    with pytest.raises(fw.FootwearError, match="right foot's and the shoe a left"):
        fw.build("left", fw.ShoeParams(), footbed=curved)
    with pytest.raises(fw.FootwearError, match="left.*right"):
        fw.build("both", fw.ShoeParams(**RULER))
    # a style with no pattern takes no openness, and says so rather than ignoring it
    stone = fw.build("right", fw.ShoeParams(style="stone", openness=0.3, **RULER))
    assert stone.report["pattern"]["count"] == 0 and any("has no windows" in w for w in stone.report["warnings"])


def test_a_mirrored_shoe_says_it_was_not_made_from_that_foots_scan(shod):
    left = fw.mirrored(shod)
    assert left.foot == "left" and left.report["foot"] == "left" and left.report["mirrored_from"] == "right"
    assert left.mesh.is_watertight and left.mesh.volume == pytest.approx(shod.mesh.volume, rel=1e-9)
    assert np.allclose(left.mesh.bounds[:, 1], -shod.mesh.bounds[::-1, 1])
    assert "mirror image" in left.report["warnings"][0] and "not made from a scan of the left foot" in left.report["warnings"][0]
    assert shod.report["foot"] == "right" and "mirrored_from" not in shod.report      # the original is untouched
    assert "mirror image" in fw.summary_html(left, "x")


def test_a_mirrored_flat_shoe_says_it_is_sized_from_the_other_foot_not_that_its_footbed_is(plain):
    """A shoe from ruler numbers has a flat footbed, from no scan: its mirror image is warned about the size
    (measured on the other foot), never told its footbed is the other foot's."""
    w = fw.mirrored(plain).report["warnings"][0]
    assert "mirror image" in w and "the right foot's measurements" in w and "left foot" in w
    assert "footbed" not in w and "scan" not in w


def test_the_files_carry_the_safety_rules_and_say_what_is_untested(curved, shod, tmp_path):
    files = fw.write_outputs(shod, tmp_path, "right-clog", "SYNTHETIC curved foot", synthetic=True)
    sheet = open(files["summary"], encoding="utf-8").read()
    for must in ("NOT A MEDICAL DEVICE", "not equivalent to, or a substitute for, a prescribed orthotic",
                 "not for tennis, running or any other sport", "This shoe is not for sport, whoever signs",
                 "SYNTHETIC TEST GEOMETRY", "No posting, no correction, one stiffness", "0.0&deg; (none)",
                 "standard shape in this foot's size", fw.UNTESTED, "Clinician review", "Signature",
                 "walking and casual wear", "not approved", "First wear indoors"):
        assert must in sheet, must
    # the break-in is the insole sheet's own paragraph, not a copy of it (docs/SAFETY.md, requirement 2)
    assert fw.BREAK_IN_HTML is insole.BREAK_IN_HTML
    assert fw.BREAK_IN_HTML in sheet and fw.BREAK_IN_HTML in insole.summary_html(curved, "x")
    assert "Day 1: 1 h" in fw.BREAK_IN_HTML and "Stop at once" in fw.BREAK_IN_HTML
    # a shoe made from a real scan isn't labelled synthetic
    assert "SYNTHETIC" not in fw.summary_html(shod, "a scan")

    notes = open(files["notes"], encoding="utf-8").read()
    assert "NOT A MEDICAL DEVICE" in notes and "not for sport" in notes and fw.UNTESTED in notes
    assert "100%" in notes and f"{shod.report['length_mm']} x {shod.report['width_mm']}" in notes

    back = insole.read_3mf(files["threemf"])
    assert back["unit"] == "millimeter" and len(back["faces"]) == len(shod.mesh.faces)
    assert "NOT A MEDICAL DEVICE" in back["metadata"]["Description"] and "SYNTHETIC" in back["metadata"]["Description"]
    t = np.array(back["transform"]).reshape(4, 3)
    on_bed = back["vertices"] @ t[:3] + t[3]
    assert on_bed[:, :2].min() > 0 and on_bed[:, :2].max() < shod.params.bed_mm and on_bed[:, 2].min() == pytest.approx(0, abs=1e-3)

    saved = json.loads(open(files["json"], encoding="utf-8").read())
    assert saved["synthetic"] is True and saved["foot"] == "right" and saved["params"]["style"] == "vent"
    assert saved["footbed"]["max_fill_mm"] == shod.report["footbed"]["max_fill_mm"]
    for view in fw.VIEWS:
        assert open(files[f"picture_{view}"], "rb").read(8) == b"\x89PNG\r\n\x1a\n"


def test_a_flat_shoes_sheet_says_there_is_no_footbed_from_a_scan(plain):
    assert any("no sole scan" in w for w in plain.report["warnings"]) and plain.report["footbed"] is None
    sheet = fw.summary_html(plain, "ruler only")
    assert "The footbed is flat" in sheet and "no arch fill and no shaped heel cup" in sheet


@pytest.fixture(scope="module")
def vent():
    """A shoe with windows, from ruler numbers alone."""
    return fw.build("right", fw.ShoeParams(style="vent", **RULER))


def _ring(mesh, x):
    """Is the solid closed over at x: does its slice across there go all the way round, with the foot's space
    inside it? (An open-topped slice, a U, has no hole in it.)"""
    planar, _ = mesh.section(plane_origin=[x, 0.0, 0.0], plane_normal=[1.0, 0.0, 0.0]).to_2D()
    return any(len(poly.interiors) for poly in planar.polygons_full)


def _holes(mesh):
    """How many holes go right through a closed surface (a ring has 1; each window through a wall adds 1)."""
    return (2 - mesh.euler_number) // 2


def test_trial_pieces_are_the_shoe_itself_between_flat_cuts_each_one_closed_solid(plain, vent):
    """Print-trial pieces are parts of the finished shoe, nothing changed but the cuts: each closed, in one
    piece and standing on z = 0, and what is in the toe cap is exactly what the shoe has forward of the cut
    (its volume by trimesh's own capped cut; its surface on the shoe's surface)."""
    import trimesh

    L = vent.mesh.bounds[1, 0]
    pieces, left_out = fw.trial_pieces(vent)
    assert list(pieces) == ["sole-block", "swatch", "toe-cap", "back-half"] and not left_out   # in the order to print them
    assert list(fw.trial_pieces(plain)[0]) == ["sole-block", "toe-cap", "back-half"]   # a closed upper has no pattern to try
    for p in pieces.values():
        m = p.mesh
        assert m.is_watertight and m.is_winding_consistent and m.body_count == 1
        assert m.bounds[0, 2] == pytest.approx(0.0, abs=1e-4)
        assert p.report["volume_cm3"] == pytest.approx(m.volume / 1000, abs=0.06)
        assert p.report["length_mm"] == pytest.approx(np.ptp(m.bounds[:, 0]), abs=0.06)
        assert [p.report["from_mm"], p.report["to_mm"]] == pytest.approx(m.bounds[:, 0], abs=0.06)   # where in the shoe it is from
    toe = pieces["toe-cap"].mesh
    cut = fw.TRIAL_TOE_FROM * L
    assert fw.TRIAL_TOE_FROM == 0.70 and toe.bounds[:, 0] == pytest.approx([cut, L], abs=0.01)
    assert toe.volume == pytest.approx(vent.mesh.slice_plane([cut, 0.0, 0.0], [1.0, 0.0, 0.0], cap=True).volume, rel=1e-4)
    off_the_cut = toe.vertices[toe.vertices[:, 0] > cut + 0.5]
    some = off_the_cut[np.random.default_rng(0).choice(len(off_the_cut), 300, replace=False)]
    assert trimesh.proximity.closest_point(vent.mesh, some)[1].max() < 1e-3
    # a left shoe's pieces are the right's, mirrored
    left, _ = fw.trial_pieces(fw.mirrored(vent))
    for name, p in pieces.items():
        assert left[name].mesh.volume == pytest.approx(p.mesh.volume, rel=1e-6)
        assert np.allclose(left[name].mesh.bounds[:, 1], -p.mesh.bounds[::-1, 1], atol=1e-3)


def test_the_sole_block_is_the_sole_under_the_heel_with_the_footbed_on_top_and_no_wall(plain, shod):
    L, heel = plain.mesh.bounds[1, 0], plain.report["sole"]["under_heel_mm"]
    m = fw.trial_pieces(plain)[0]["sole-block"].mesh
    assert m.bounds[:, 0] == pytest.approx([0.08 * L, 0.22 * L], abs=0.01)
    assert m.bounds[:, 1] == pytest.approx([-0.07 * L, 0.07 * L], abs=0.01)       # either side of the heel's middle line
    assert m.bounds[1, 2] == pytest.approx(heel, abs=0.02)                         # nothing stands on a flat floor
    box = 0.14 * L * 0.14 * L * heel
    assert 0.93 * box < m.volume < box                                             # a solid block, less the tread's grooves
    # with a footbed, its top is that footbed (SYNTHETIC curved foot: the heel's cup)
    L, heel = shod.mesh.bounds[1, 0], shod.report["sole"]["under_heel_mm"]
    m = fw.trial_pieces(shod)[0]["sole-block"].mesh
    for x, y in ((0.10 * L, 0.0), (0.15 * L, 10.0), (0.20 * L, -12.0)):
        assert _floor(m, x, y) == pytest.approx(_floor(shod.mesh, x, y), abs=1e-3)
    assert heel - 0.05 < m.bounds[1, 2] < heel + shod.report["footbed"]["heel_cap_mm"] + 0.05


def test_the_pattern_swatch_is_a_ring_of_the_upper_with_its_windows_on_a_thin_floor(vent):
    r = vent.report
    L, ball = vent.mesh.bounds[1, 0], r["sole"]["under_ball_mm"]
    sw = fw.trial_pieces(vent)[0]["swatch"].mesh
    x0 = fw.TRIAL_SWATCH_FROM * L
    assert sw.bounds[:, 0] == pytest.approx([x0, x0 + 40.0], abs=0.01)
    assert _holes(sw) - 1 >= 20                                    # the foot's own tunnel, and whole windows through the walls
    # its floor is the top 2 mm of the sole, set down on the bed
    assert 2.0 - 0.01 < _floor(sw, x0 + 20.0, 0.0, 30.0) < 2.5
    # the walls and the roof are the shoe's, lower by what was cut off under them
    there = vent.mesh.vertices[(vent.mesh.vertices[:, 0] >= x0) & (vent.mesh.vertices[:, 0] <= x0 + 40.0)]
    assert sw.bounds[1, 2] + (ball - 2.0) == pytest.approx(there[:, 2].max(), abs=0.3)
    assert sw.bounds[:, 1] == pytest.approx([there[:, 1].min(), there[:, 1].max()], abs=1.5)
    # long windows get a longer swatch: two and a half of them
    stream = fw.build("right", fw.ShoeParams(style="stream", **RULER))
    long = fw.trial_pieces(stream)[0]["swatch"].mesh
    assert np.ptp(long.bounds[:, 0]) == pytest.approx(2.5 * fw.STYLES["stream"]["pitch_mm"][0], abs=0.01)
    assert _holes(long) - 1 >= 6


def test_the_back_half_keeps_the_heel_cup_the_let_out_wall_and_the_rim_and_has_no_roof():
    """SYNTHETIC block foot with a 10 mm block standing out of its inner side: the back half is the shoe up to
    46% of its length, its walls cut off level 40 mm above the heel's floor. Probed like the shoe, it answers
    like the shoe: the same footbed, the same let-out inner wall, the lip behind the heel; and it is open above.
    This foot's let-out runs on past the piece's cut, and the sheet says the piece shows it only that far."""
    bulged = insole.from_scan(synth.block_foot(37.0, "right", inner_bulge=10.0), "right")
    shoe = fw.build("right", fw.ShoeParams(style="stone"), footbed=bulged)
    r = shoe.report
    L, heel = shoe.mesh.bounds[1, 0], r["sole"]["under_heel_mm"]
    assert r["footbed"]["let_out"]["inner"]["max_mm"] > 5.0
    pieces, _ = fw.trial_pieces(shoe)
    b = pieces["back-half"].mesh
    assert b.bounds[:, 0] == pytest.approx([0.0, fw.TRIAL_BACK_UNTIL * L], abs=0.01)
    assert b.bounds[1, 2] == pytest.approx(heel + fw.TRIAL_BACK_WALL_MM, abs=0.01)
    for x in (30.0, 60.0, 90.0, 110.0):
        for y in (-15.0, 0.0, 20.0):
            assert _floor(b, x, y, 300.0) == pytest.approx(_floor(shoe.mesh, x, y, heel + 30.0), abs=1e-3), (x, y)   # no roof over it
        assert _wall(b, x, heel + 20.0, 1.0) == pytest.approx(_wall(shoe.mesh, x, heel + 20.0, 1.0), abs=1e-3)       # inner wall
        assert _wall(b, x, heel + 20.0, -1.0) == pytest.approx(_wall(shoe.mesh, x, heel + 20.0, -1.0), abs=1e-3)
    assert _hit(b, [-50.0, 0.0, heel + r["heel_rim_mm"] - 4.0], [1.0, 0, 0])[0] < 1.0                               # the lip
    assert not any(_ring(b, x) for x in np.arange(10.0, b.bounds[1, 0], 6.0))                                       # no roof
    (run,) = r["footbed"]["let_out"]["inner"]["stretches"]           # one stretch, heel to past the ball
    assert run["from_mm"] < run["at_mm"] < b.bounds[1, 0] < run["to_mm"]
    notes = fw.trial_notes(shoe, pieces)
    assert (f"This shoe's inner wall is let out by up to {run['max_mm']} mm for this foot, between {run['from_mm']:.0f} "
            f"and {run['to_mm']:.0f} mm from the back. This piece ends at {b.bounds[1, 0]:.0f} mm: it shows that stretch "
            "as far as there (the most of it included), and the whole shoe the rest.") in notes
    assert "all of that is in this piece" not in notes


def test_the_trial_files_say_they_are_not_shoes_and_what_each_piece_is_for(vent, tmp_path):
    files, left_out = fw.write_trials(vent, tmp_path, "right-clog", "SYNTHETIC ruler numbers", synthetic=True)
    assert left_out == [] and all(isinstance(f, str) for f in files.values())
    notes = open(files["notes"], encoding="utf-8").read()
    for must in ("NOT A MEDICAL DEVICE", fw.TRIAL_WARNING, "Do not stand or walk in one", fw.UNTESTED, "scale 100%",
                 "SYNTHETIC TEST GEOMETRY", "15, 20 and 25%", "Sole block", "Pattern swatch", "Toe cap", "Back half",
                 "while seated", "in this order", "Press in the middle of its top", "walls the shoe doesn't have there",
                 "2 mm under the inside's floor at the ball of the foot"):
        assert must in notes, must
    assert "let out" not in notes                                   # nothing was, from ruler numbers
    # nothing the pieces are not: not ordered by size, not cut under the footbed, not the shoe at their cut faces
    for never in ("smallest first", "under the footbed", "exactly"):
        assert never not in notes, never
    assert notes.count("the cushioning's infill") == 3              # the swatch too: every piece but the block
    pieces, _ = fw.trial_pieces(vent)
    for name, p in pieces.items():
        back = insole.read_3mf(files[f"{name}_threemf"])
        said = back["metadata"]["Description"]
        assert "NOT A MEDICAL DEVICE" in said and "Do not stand or walk in one" in said and "SYNTHETIC" in said
        assert back["unit"] == "millimeter" and len(back["faces"]) == len(p.mesh.faces)
        t = np.array(back["transform"]).reshape(4, 3)
        on_bed = back["vertices"] @ t[:3] + t[3]
        assert on_bed[:, :2].min() > 0 and on_bed[:, :2].max() < vent.params.bed_mm and on_bed[:, 2].min() == pytest.approx(0, abs=1e-3)
        assert open(files[f"{name}_stl"], "rb").read(5) != b"" and f"{p.report['length_mm']} x {p.report['width_mm']}" in notes
    saved = json.loads(open(files["json"], encoding="utf-8").read())
    assert saved["synthetic"] is True and [q["piece"] for q in saved["pieces"]] == list(pieces) and saved["left_out"] == []
    assert saved["warning"] == f"NOT A MEDICAL DEVICE. {fw.TRIAL_WARNING}"
    # an STL has nowhere to carry a note and the picture is a picture: the three above are where it is said
    assert set(files) == {f"{n}_{kind}" for n in pieces for kind in ("threemf", "stl")} | {"notes", "json", "picture"}
    assert open(files["picture"], "rb").read(8) == b"\x89PNG\r\n\x1a\n"
    assert "SYNTHETIC" not in fw.trial_notes(vent, pieces)          # only what is labelled synthetic says so


def test_the_trial_cuts_follow_the_shoes_own_opening():
    """An opening that ends further back or further forward than the styles' own. The back half is cut where the
    shoe is still open above; the toe cap and the swatch start where its roof is whole. SYNTHETIC sizes; the
    first is one where a back half cut at 46% of the length whatever the opening would keep a strip of roof (a
    small shoe, a high heel and rim, the opening ending early)."""
    small = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=185.0, foot_width_mm=69.0, throat=0.35,
                                            drop_mm=12.0, heel_rim_mm=36.0))
    o = small.report["opening_ends_mm"]
    assert _ring(small.mesh, o) and not _ring(small.mesh, o - 8.0)        # the roof is whole from there on, open just behind
    back = fw.trial_pieces(small)[0]["back-half"]
    assert back.report["to_mm"] == pytest.approx(o - fw.TRIAL_OPEN_MM, abs=0.06) and fw.TRIAL_OPEN_MM == 6.0
    assert back.report["to_mm"] < fw.TRIAL_BACK_UNTIL * small.mesh.bounds[1, 0] - 20.0
    assert not any(_ring(back.mesh, x) for x in np.arange(10.0, back.report["to_mm"], 2.0))

    # the opening ending late, in a plain shoe and a patterned one of the same size
    stone, stream = (fw.build("right", fw.ShoeParams(style=style, throat=0.65, **RULER)) for style in ("stone", "stream"))
    for shoe in (stone, stream):
        L, o = shoe.mesh.bounds[1, 0], shoe.report["opening_ends_mm"]
        pieces, left_out = fw.trial_pieces(shoe)
        assert not left_out and o > fw.TRIAL_SWATCH_FROM * L
        assert pieces["back-half"].report["to_mm"] == pytest.approx(fw.TRIAL_BACK_UNTIL * L, abs=0.06)   # as for any opening
        assert pieces["toe-cap"].report["from_mm"] == pytest.approx(fw.TRIAL_TOE_FROM * L, abs=0.06) and o < fw.TRIAL_TOE_FROM * L
    assert _ring(fw.trial_pieces(stone)[0]["toe-cap"].mesh, pieces["toe-cap"].report["from_mm"] + 0.3)
    # the swatch: forward of the opening, and slid back to end a bar's width past the last window instead of running on
    # into the toe cap
    sw = pieces["swatch"]
    assert sw.report["from_mm"] == pytest.approx(o + fw.TRIAL_ROOFED_MM, abs=0.06) and fw.TRIAL_ROOFED_MM == 10.0
    assert sw.report["to_mm"] == pytest.approx(stream.report["pattern"]["ends_mm"] + fw.MIN_STRUT_MM, abs=0.06)   # not on its tip
    assert sw.report["to_mm"] - sw.report["from_mm"] < 2.5 * fw.STYLES["stream"]["pitch_mm"][0] - 5.0
    assert _holes(sw.mesh) - 1 >= 4
    # (a slice through windows is no ring, so the plain shoe is asked: the same inside, the same opening)
    assert stone.report["opening_ends_mm"] == o and _ring(stone.mesh, sw.report["from_mm"])

    # the toe cap needs no such rule: even the smallest adult shoe with the latest opening is roofed where it is cut
    least = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=180.0, foot_width_mm=67.0, throat=0.65))
    cap = fw.trial_pieces(least)[0]["toe-cap"]
    assert least.report["opening_ends_mm"] + 2.0 < cap.report["from_mm"] and _ring(cap.mesh, cap.report["from_mm"] + 0.3)

    # too little patterned roof forward of the opening for a swatch: there is none, and that is said
    short = fw.build("right", fw.ShoeParams(style="stream", foot_length_mm=185.0, foot_width_mm=69.0, throat=0.65))
    pieces, left_out = fw.trial_pieces(short)
    assert list(pieces) == ["sole-block", "toe-cap", "back-half"] and len(left_out) == 1
    assert left_out[0].startswith("Pattern swatch: left out.") and "less than a window and a half's spacing" in left_out[0]
    assert left_out[0] in fw.trial_notes(short, pieces, left_out)


def test_a_sliver_freed_where_two_cuts_meet_a_window_is_dropped_not_the_piece(monkeypatch):
    """SYNTHETIC size found by a sweep: a 245 mm foot's ``stream`` shoe with its opening ending at 0.42. The
    back half's two cuts meet the edge of a window and free a sliver of the upper far smaller than a nozzle's
    line. The sliver is dropped and the piece kept, one body; with no allowance for crumbs the piece is left
    out, as anything bigger coming loose still is."""
    shoe = fw.build("right", fw.ShoeParams(style="stream", throat=0.42, foot_length_mm=245.0, foot_width_mm=91.4))
    pieces, left_out = fw.trial_pieces(shoe)
    assert not left_out and list(pieces) == ["sole-block", "swatch", "toe-cap", "back-half"]
    back = pieces["back-half"]
    assert back.mesh.body_count == 1 and back.mesh.is_watertight
    # all of the shoe behind the cut and under the level cut, less under a thousandth of a cubic centimetre
    h0, top = back.report["to_mm"], back.mesh.bounds[1, 2]
    cut = shoe.mesh.slice_plane([h0, 0.0, 0.0], [-1.0, 0.0, 0.0], cap=True).slice_plane([0.0, 0.0, top], [0.0, 0.0, -1.0], cap=True)
    assert -1e-3 < cut.volume - back.mesh.volume < fw.TRIAL_CRUMB_MM3 and fw.TRIAL_CRUMB_MM3 == 1.0
    monkeypatch.setattr(fw, "TRIAL_CRUMB_MM3", 0.0)
    pieces, left_out = fw.trial_pieces(shoe)
    assert "back-half" not in pieces and left_out == ["Back half: left out (it didn't come out as one piece; please report the sizes used)."]


def test_the_back_half_keeps_a_high_rim_whole():
    """A rim behind the heel higher than the back half's usual level cut (40 mm above the heel's floor): the cut
    goes 8 mm above the rim instead, so the piece still has the rim it is printed to try."""
    shoe = fw.build("right", fw.ShoeParams(style="stone", heel_rim_mm=44.0, **RULER))
    heel = shoe.report["sole"]["under_heel_mm"]
    b = fw.trial_pieces(shoe)[0]["back-half"]
    assert b.mesh.bounds[1, 2] == pytest.approx(heel + 44.0 + 8.0, abs=0.01) and "level 52 mm above" in b.report["cut"]
    for z in (heel + 30.0, heel + 42.0):                               # the back of the heel, up to just under its rim
        assert _hit(b.mesh, [-50.0, 0.0, z], [1.0, 0, 0])[0] == pytest.approx(_hit(shoe.mesh, [-50.0, 0.0, z], [1.0, 0, 0])[0], abs=1e-3)
    assert _hit(b.mesh, [-50.0, 0.0, heel + 46.0], [1.0, 0, 0]) is None                 # and nothing above the rim, as on the shoe
    assert _hit(shoe.mesh, [-50.0, 0.0, heel + 46.0], [1.0, 0, 0])[0] > 20.0


def test_the_trial_sheet_speaks_of_a_let_out_wall_only_where_the_piece_has_it():
    """Made-up numbers: an inner wall let out in two places (40 to 110 mm from the back, most at 80; and 150 to
    190 mm, most at 170) with the standard shape between, an outer one by too little to speak of. Each stretch
    gets its own line and its own figures. A piece that holds all of a stretch says so; one cut part way along
    it says how far it shows and whether the most of it is in the piece; a stretch the piece has none of is
    not mentioned."""
    let = dict(inner=dict(max_mm=6.0, at=0.3, at_mm=80.0, stretches=[dict(from_mm=40.0, to_mm=110.0, max_mm=6.0, at_mm=80.0),
                                                                     dict(from_mm=150.0, to_mm=190.0, max_mm=3.0, at_mm=170.0)]),
               outer=dict(max_mm=0.6, at=0.3, at_mm=80.0, stretches=[]))
    first, = fw._let_out_lines(let, dict(from_mm=0.0, to_mm=128.0))      # the back half: the first stretch, not the second
    assert "inner wall is let out by up to 6.0 mm" in first and "between 40 and 110 mm from the back" in first
    assert "all of that is in this piece" in first
    both = fw._let_out_lines(let, dict(from_mm=0.0, to_mm=160.0))
    assert len(both) == 2 and "all of that" in both[0]
    assert "by up to 3.0 mm" in both[1] and "between 150 and 190 mm" in both[1] and "This piece ends at 160 mm" in both[1]
    assert "as far as there (not the most of it, which is at 170 mm)" in both[1]
    part, = fw._let_out_lines(let, dict(from_mm=0.0, to_mm=90.0))
    assert "This piece ends at 90 mm" in part and "(the most of it included)" in part and "all of that" not in part
    assert fw._let_out_lines(let, dict(from_mm=0.0, to_mm=35.0)) == []
    assert fw._let_out_lines(let, dict(from_mm=195.0, to_mm=278.0)) == []   # (a piece forward of both)


def test_a_wall_let_out_in_two_places_is_two_stretches_not_one_span():
    """A made-up outline from above: the standard shape's own inside with two bumps standing 6 mm out of its
    inner side, 40 to 70 and 150 to 180 mm along, and the standard shape between them. The let-out is two
    stretches, each about its bump (eased a few millimetres either way) and 6 mm at most, not one span from
    40 to 180."""
    import shapely

    p = fw.ShoeParams(style="stone", **RULER)
    st = fw.STYLES["stone"]
    loft = fw._loft_for(fw.size_inside(260.0, 97.0, p), p, st["sole_mm"], st["flare_mm"], st["grooves"])
    bumps = ((40.0, 70.0), (150.0, 180.0))

    def bump(x0, x1):
        xs = np.arange(x0, x1 + 0.5)
        _, wall = fw._across(loft.inside_widest, xs)
        return shapely.Polygon([*zip(xs, wall + 6.0), *zip(xs[::-1], wall[::-1] - 10.0)])

    fns, report, where = fw._let_out(loft, shapely.union_all([loft.inside_widest, *(bump(*b) for b in bumps)]), 0.0)
    runs = where["inner"]["stretches"]
    assert len(runs) == 2 and where["outer"]["stretches"] == [] and report["inner"]["max_mm"] == pytest.approx(6.0, abs=0.3)
    for (start, end, most, at), (x0, x1) in zip(runs, bumps):
        assert x0 - 12.0 < start <= x0 and x1 <= end < x1 + 12.0 and start < at < end
        assert most == pytest.approx(6.0, abs=0.3)
    assert runs[1][0] - runs[0][1] > 55.0                                # the standard shape between them
    assert float(fns[0](110.0)) == 0.0 and float(fns[0](55.0)) > 5.0


def test_where_a_wall_is_let_out_is_reported_from_the_back_of_the_shoe(block):
    """SYNTHETIC block foot (wider than the standard shape along most of its inner side). The report's stretch
    and its greatest point are millimetres from the back of the finished shoe, where a ruler on the print
    would find them: probed against the same shoe from ruler numbers alone (the standard shape, nothing let
    out), the inner wall stands out by the reported most at ``at_mm``, and by 1 mm where the stretch ends."""
    p = fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=90.0)
    shoe, standard = fw.build("right", p, footbed=block), fw.build("right", p)
    inner = shoe.report["footbed"]["let_out"]["inner"]
    (run,) = inner["stretches"]

    def out(x):
        return _wall(shoe.mesh, x, 38.0, 1.0) - _wall(standard.mesh, x, 38.0, 1.0)

    assert run["from_mm"] < run["at_mm"] < run["to_mm"] and run["max_mm"] > 5.0
    assert (run["max_mm"], run["at_mm"]) == (inner["max_mm"], inner["at_mm"])     # one stretch: its most is the wall's
    assert out(run["at_mm"]) == pytest.approx(run["max_mm"], abs=0.3)
    assert out(run["to_mm"] - 1.5) > 1.0 > out(run["to_mm"] + 1.5)
    # nothing left in the loft's own coordinates, in the let-out or the pattern
    assert set(inner) == {"max_mm", "at", "at_mm", "stretches"} and set(run) == {"from_mm", "to_mm", "max_mm", "at_mm"}
    assert set(shoe.report["pattern"]) == {"count", "openness"}
    assert set(fw.build("right", fw.ShoeParams(style="vent", **RULER)).report["pattern"]) == {"count", "openness", "window_mm", "rows", "ends_mm"}


def test_a_trial_piece_that_fails_is_left_out_and_said_and_the_rest_are_still_made(vent, tmp_path, monkeypatch):
    """One piece coming out broken must not cost the others. Faked here: the second piece's closed-surface step
    is made to fail. Only when no piece can be made is the whole thing an error."""
    real, calls = fw._closed_mesh, []

    def second_fails(solid, what, back_at_zero=False):
        calls.append(what)
        if len(calls) == 2:
            raise fw.FootwearError(f"{what} came out broken (not closed); please report the sizes used")
        return real(solid, what, back_at_zero)

    monkeypatch.setattr(fw, "_closed_mesh", second_fails)
    files, left_out = fw.write_trials(vent, tmp_path, "right-clog", "SYNTHETIC ruler numbers", synthetic=True)
    assert len(left_out) == 1 and left_out[0].startswith("Pattern swatch: left out (it came out broken")
    assert "swatch_threemf" not in files and not list(tmp_path.glob("*swatch*"))
    for name in ("sole-block", "toe-cap", "back-half"):
        assert (tmp_path / f"right-clog-trial-{name}.3mf").stat().st_size > 500
    notes = open(files["notes"], encoding="utf-8").read()
    assert left_out[0] in notes and "1. Sole block" in notes and "2. Toe cap" in notes and "3. Back half" in notes
    assert json.loads(open(files["json"], encoding="utf-8").read())["left_out"] == left_out

    def all_fail(solid, what, back_at_zero=False):
        raise fw.FootwearError(f"{what} came out broken (not closed); please report the sizes used")

    monkeypatch.setattr(fw, "_closed_mesh", all_fail)
    with pytest.raises(fw.FootwearError, match="no trial piece could be cut from this shoe"):
        fw.write_trials(vent, tmp_path / "none", "right-clog", "SYNTHETIC ruler numbers", synthetic=True)
    assert not (tmp_path / "none").exists()                          # nothing written, nothing removed
    assert (tmp_path / "right-clog-trial-toe-cap.3mf").exists()


def test_trial_files_of_an_earlier_shoe_are_not_left_beside_a_new_one(plain, vent, tmp_path, capsys):
    """A piece cut from an earlier shoe, left in the folder, would be printed as the new shoe's. Writing the
    trials again removes the old set first (a closed upper writes no swatch over the patterned one's). Writing
    the shoe's files leaves them alone (so trials written first are not lost), and the command removes them
    once it has written a shoe without new trials. Nothing else in the folder is touched."""
    fw.write_trials(vent, tmp_path, "right-clog", "SYNTHETIC ruler numbers", synthetic=True)
    assert (tmp_path / "right-clog-trial-swatch.3mf").exists() and (tmp_path / "right-clog-trial-swatch.stl").exists()
    mine = tmp_path / "right-clog-trial-notes-of-my-own.txt"
    mine.write_text("what I saw")
    fw.write_trials(plain, tmp_path, "right-clog", "SYNTHETIC ruler numbers", synthetic=True)
    assert not list(tmp_path.glob("right-clog-trial-swatch*")) and (tmp_path / "right-clog-trial-toe-cap.3mf").exists()
    fw.write_outputs(plain, tmp_path, "right-clog", "SYNTHETIC ruler numbers", synthetic=True)
    assert (tmp_path / "right-clog-trial-toe-cap.3mf").exists() and (tmp_path / "right-clog-trials.txt").exists()
    # the command, writing the right shoe again without --trials (here as the left's mirror image)
    assert cli.main(["footwear", "--foot", "left", "--length", "260", "--width", "97", "--style", "stone", "--pair",
                     "-o", str(tmp_path)]) == 0
    capsys.readouterr()
    assert [f.name for f in tmp_path.glob("right-clog-trial*")] == [mine.name] and mine.read_text() == "what I saw"
    assert (tmp_path / "right-clog.3mf").exists() and (tmp_path / "left-clog.3mf").exists()


def test_pictures_show_the_shoe_from_every_side(shod):
    pics = fw.pictures(shod)
    assert set(pics) == set(fw.VIEWS) | {"views"}
    side = pics["side"]
    drawn = (side < 250).any(axis=2)
    assert side.dtype == np.uint8 and 0.25 < drawn.mean() < 0.9
    # half a millimetre a pixel: the side view is as long as the shoe
    cols = np.flatnonzero(drawn.any(axis=0))
    assert (cols[-1] - cols[0] + 1) * fw.PICTURE_MM_PER_PX == pytest.approx(shod.report["length_mm"], abs=2.0)
    # no pinholes: inside the sole's band every pixel is drawn
    rows = np.flatnonzero(drawn.any(axis=1))
    band = drawn[rows[-1] - 20:rows[-1] - 4, cols[0] + 20:cols[-1] - 20]
    assert band.all()


@pytest.mark.parametrize("foot, inner", [("right", 1.0), ("left", -1.0)])
def test_the_shoe_cut_open_is_its_inner_half_closed_by_one_flat_face(foot, inner):
    """SYNTHETIC block foot, whose 11 mm arch fill is on the inner side only: the half that is kept is the one
    with the fill in it (a left shoe's is the other side), and what is kept is the shoe's own surface, unmoved."""
    block = insole.from_scan(synth.block_foot(37.0, foot), foot)
    shoe = fw.build(foot, fw.ShoeParams(style="stone"), footbed=block)
    opened, cut = fw.opened_up(shoe)
    assert opened.is_watertight and opened.is_winding_consistent and 0.3 < opened.volume / shoe.mesh.volume < 0.7
    side = inner * opened.vertices[:, 1]                           # how far toward the foot's inner side
    assert side.min() == pytest.approx(0.0, abs=1e-3)              # nothing of the outer half is left
    assert side.max() == pytest.approx((inner * shoe.mesh.vertices[:, 1]).max(), abs=1e-6)
    # the cut is one flat face on the heel's middle line, facing the half that was taken away, and it is all of
    # the material a cut there goes through
    assert cut.any() and np.abs(opened.vertices[opened.faces[cut]][:, :, 1]).max() < 1e-3
    assert np.allclose(opened.face_normals[cut], [0.0, -inner, 0.0], atol=1e-6)
    assert not np.isclose(np.abs(opened.face_normals[~cut][:, 1]), 1.0, atol=1e-9).all()
    assert opened.area_faces[cut].sum() == pytest.approx(_cut_area(shoe.mesh, [0, 0, 0], [0, 1.0, 0]), rel=1e-4)
    # the footbed under the arch is still where the whole shoe has it, fill and all
    for x in (60.0, 100.0, 125.0, 180.0):
        assert _floor(opened, x, inner * 22.0, 36.0) == pytest.approx(_floor(shoe.mesh, x, inner * 22.0, 36.0), abs=1e-4)
    assert _floor(opened, 110.0, -inner * 22.0, 36.0) is None      # and there is no floor on the other side


def test_the_3d_preview_is_the_shoe_itself_whole_and_cut_open_with_its_edges_kept(shod, tmp_path):
    """The studio's viewer rounds over any edge whose two faces share their points; the preview's points are
    split at the shoe's sharp edges, so it has more points than the shoe and the same faces."""
    from footscan.recon import viewer_data

    files = fw.write_preview(shod, tmp_path, "clog")
    assert set(files) == {"whole", "open"} and sorted(p.name for p in tmp_path.iterdir()) == [
        "clog-preview-open.bin", "clog-preview.bin"]
    whole = viewer_data.read(files["whole"])
    assert len(whole["faces"]) == len(shod.mesh.faces) and len(whole["vertices"]) > len(shod.mesh.vertices)
    assert (whole["colors"] == fw.PREVIEW_COLOUR).all()
    # the same shape, in the shoe's own frame (millimetres, heel at the back, sole on the floor)
    assert np.allclose(whole["vertices"].min(axis=0), shod.mesh.bounds[0], atol=1e-3)
    assert np.allclose(whole["vertices"].max(axis=0), shod.mesh.bounds[1], atol=1e-3)
    area = lambda d: float(np.linalg.norm(np.cross(*(d["vertices"][d["faces"][:, i]].astype(float) - d["vertices"][d["faces"][:, 0]]
                                                     for i in (1, 2))), axis=1).sum() / 2)
    assert area(whole) == pytest.approx(shod.mesh.area, rel=1e-5)

    opened, cut = fw.opened_up(shod)
    inside = viewer_data.read(files["open"])
    assert len(inside["faces"]) == len(opened.faces) and area(inside) == pytest.approx(opened.area, rel=1e-5)
    # the cut's face, and only that, is in the cut's colour
    is_cut = (inside["colors"] == fw.PREVIEW_CUT_COLOUR).all(axis=1)
    assert is_cut.any() and (inside["colors"][~is_cut] == fw.PREVIEW_COLOUR).all()
    assert np.abs(inside["vertices"][is_cut][:, 1]).max() < 1e-3
    tri = is_cut[inside["faces"]]
    assert (tri.all(axis=1) | ~tri.any(axis=1)).all()              # no face is half one colour and half the other
    assert area(dict(vertices=inside["vertices"], faces=inside["faces"][tri.all(axis=1)])) == pytest.approx(
        opened.area_faces[cut].sum(), rel=1e-5)


def test_a_shoe_that_isnt_a_closed_solid_is_not_cut_open(plain):
    import trimesh

    holed = replace(plain, mesh=trimesh.Trimesh(plain.mesh.vertices, plain.mesh.faces[:-40], process=False))
    with pytest.raises(fw.FootwearError, match="can't be cut open"):
        fw.opened_up(holed)


def test_a_sole_up_phone_scan_makes_the_shoe_the_way_the_studio_makes_the_insole():
    """SYNTHETIC sole-up scan (as the iPhone app hands one over): prepared exactly as for an insole, whose
    surface is then the footbed; the insole's own notes travel with the shoe."""
    scan = synth.sole_up_capture(synth.curved_foot("right"))
    shoe = fw.from_scan(scan, "right", fw.ShoeParams(style="stone"), kind="sole_up")
    fb = shoe.report["footbed"]
    assert fb["prep"]["kind"] == "sole_up" and fb["max_fill_mm"] == pytest.approx(synth.CURVED_ARCH_MM - 1.0, abs=0.8)
    assert shoe.report["made_for"]["length_from"] == "scan"
    assert shoe.report["made_for"]["foot_length_mm"] == pytest.approx(248.5, abs=2.5)   # curved_plan: 0 to 250
    assert "Sole up" in fw.summary_html(shoe, "x")                                       # how the foot was captured


WHOLE_SCAN = dict(completeness=dict(length_mm=244.1, width_mm=89.6, toe_end=0.23, heel_end=0.48),
                  ball_sides_above_floor_mm=dict(minus_x=0.2, plus_x=1.4), open_edges_near_floor_mm=0.0,
                  heel_back_above_floor_mm=1.3)


def test_what_makes_a_sole_scan_unfit_for_a_footbed_is_what_the_studio_refuses_on_arrival():
    """The measures are made up for the test (the whole one is close to the first real right sole scan's)."""
    assert fw.unfit_for_a_footbed(WHOLE_SCAN, "sole_up") == [] and fw.unfit_for_a_footbed(WHOLE_SCAN, "sole_hanging") == []
    for change, starts in ((dict(ball_sides_above_floor_mm=dict(minus_x=0.0, plus_x=8.6)), "THE FOREFOOT WAS ROLLED ONTO ONE EDGE"),
                           (dict(open_edges_near_floor_mm=225.0), "PART OF THE FOOT IS MISSING"),
                           (dict(heel_back_above_floor_mm=46.3), "THE HEEL IS MISSING"),
                           (dict(completeness=dict(WHOLE_SCAN["completeness"], toe_end=0.9)), "THE TOES ARE MISSING"),
                           (dict(completeness=dict(WHOLE_SCAN["completeness"], heel_end=0.9)), "THE HEEL IS CUT OFF"),
                           (dict(toes_warning="THE TOES ARE BENT UP TOO STEEPLY: made up for the test."), "THE TOES ARE BENT")):
        found = fw.unfit_for_a_footbed(dict(WHOLE_SCAN, **change), "sole_up")
        assert len(found) == 1 and found[0].startswith(starts), change
    # the ends couldn't be measured (the preparation says so in a warning): the rest still counts
    unmeasured = {k: v for k, v in WHOLE_SCAN.items() if k != "completeness"}
    assert fw.unfit_for_a_footbed(unmeasured, "sole_up") == []
    assert len(fw.unfit_for_a_footbed(dict(unmeasured, open_edges_near_floor_mm=225.0), "sole_up")) == 1
    # the kinds of scan the studio doesn't check on arrival: a foot standing on the floor, or a foam print cut
    # out of its foam, is open near the floor by design
    for kind in ("foot", "impression"):
        assert fw.unfit_for_a_footbed(dict(WHOLE_SCAN, open_edges_near_floor_mm=225.0), kind) == []


def test_a_sole_scan_with_a_rolled_forefoot_makes_no_shoe():
    """SYNTHETIC sole-up scans. Under a forefoot rolled onto one edge the fill is higher on the raised side: a
    wedge across the shoe's floor, which a first fit must not have. The insole generator warns and still writes
    its insole; a shoe's footbed can't be taken out, so there is no shoe. A roll the floor levels (5 degrees)
    makes one."""
    from test_insole import _rolled_forefoot_scan

    with pytest.raises(fw.UnfitScan) as refused:
        fw.from_scan(_rolled_forefoot_scan(15.0), "right", fw.ShoeParams(style="stone"), kind="sole_up")
    said = str(refused.value)
    assert said.startswith("no shoe is made from this sole scan: its footbed is built into the shoe")
    assert "THE FOREFOOT WAS ROLLED ONTO ONE EDGE" in said and "a wedge" in said and "Scan again" in said
    shoe = fw.from_scan(_rolled_forefoot_scan(5.0), "right", fw.ShoeParams(style="stone"), kind="sole_up")
    assert shoe.mesh.is_watertight and not any("ROLLED" in w for w in shoe.report["footbed"]["insole_warnings"])


def test_a_sole_scan_missing_its_toes_makes_no_shoe_and_the_command_writes_nothing(tmp_path, capsys):
    """SYNTHETIC sole-up scan cut off 200 mm from the heel, as the studio's arrival check is tested with."""
    scan = tmp_path / "cut.obj"
    synth.sole_up_capture(synth.cut_ends(synth.shaped_foot("right"), x_to=200.0)).export(scan)
    out = tmp_path / "out"
    assert cli.main(["footwear", "--foot", "right", "--scan", str(scan), "--kind", "sole_up", "--style", "stone",
                     "--trials", "-o", str(out)]) == 1
    said = capsys.readouterr()
    assert f"{scan}: no shoe is made from this sole scan" in said.err and "THE TOES ARE MISSING" in said.err
    assert "Traceback" not in said.err and "clog (stone)" not in said.out
    assert not out.exists() or not list(out.iterdir())


def test_the_command_writes_a_pair_from_one_scan_and_refuses_nonsense(tmp_path, capsys, monkeypatch):
    scan = tmp_path / "foot.ply"
    synth.curved_foot("right", leg=False).export(scan)
    out = tmp_path / "out"
    assert cli.main(["footwear", "--foot", "right", "--scan", str(scan), "--style", "stream", "--pair", "--trials",
                     "-o", str(out)]) == 0
    said = capsys.readouterr()
    assert "right clog (stream)" in said.out and "left clog (stream)" in said.out and "NOT A MEDICAL DEVICE" in said.out
    assert "mirror image" in said.err
    for foot in ("right", "left"):
        for end in (".3mf", ".stl", "-summary.html", "-print-notes.txt", ".json", "-views.png"):
            assert (out / f"{foot}-clog{end}").stat().st_size > 500
    assert json.loads((out / "left-clog.json").read_text())["mirrored_from"] == "right"
    # the trial pieces are the scanned foot's shoe's, not its mirror image's
    assert "right clog's trial pieces" in said.out and "Do not stand or walk in one" in said.out
    for end in ("-trials.txt", "-trials.png", "-trials.json", "-trial-sole-block.3mf", "-trial-swatch.stl",
                "-trial-toe-cap.3mf", "-trial-back-half.3mf"):
        assert (out / f"right-clog{end}").stat().st_size > 500
    assert not list(out.glob("left-clog-trial*"))

    # pieces that can't be cut are an error line, not a traceback, and the shoe's own files stand
    def refuse(shoe):
        raise fw.FootwearError("no trial piece could be cut from this shoe: made up for the test")

    monkeypatch.setattr(fw, "trial_pieces", refuse)
    assert cli.main(["footwear", "--foot", "right", "--length", "260", "--width", "97", "--style", "stone", "--trials",
                     "-o", str(tmp_path / "refused")]) == 1
    said = capsys.readouterr()
    assert "right clog's trial pieces: no trial piece could be cut" in said.err and "Traceback" not in said.err
    assert "The shoe's own files above are written" in said.err
    assert (tmp_path / "refused" / "right-clog.3mf").exists() and not list((tmp_path / "refused").glob("*trial*"))
    assert said.out.rstrip().endswith("break-in as on the summary sheet.") and "NOT A MEDICAL DEVICE" in said.out   # still the last word
    monkeypatch.undo()
    # one piece left out (faked: the second piece's closed-surface step fails) is a warning, and the rest are written
    real, cut = fw._closed_mesh, []

    def second_piece_fails(solid, what, back_at_zero=False):
        cut.append(what)
        if cut.count("it") == 2 and what == "it":
            raise fw.FootwearError("it came out broken (not closed); please report the sizes used")
        return real(solid, what, back_at_zero)

    monkeypatch.setattr(fw, "_closed_mesh", second_piece_fails)
    assert cli.main(["footwear", "--foot", "right", "--length", "260", "--width", "97", "--style", "stone", "--trials",
                     "-o", str(tmp_path / "one-short")]) == 0
    said = capsys.readouterr()
    assert "warning: Toe cap: left out (it came out broken" in said.err and "left_out" not in said.out
    assert (tmp_path / "one-short" / "right-clog-trial-back-half.3mf").exists()
    assert not list((tmp_path / "one-short").glob("*toe-cap*"))

    assert cli.main(["footwear", "--foot", "right", "--length", "26", "--width", "9.7", "-o", str(tmp_path / "bad")]) == 1
    assert "check the length, in millimetres" in capsys.readouterr().err
    assert not (tmp_path / "bad").exists()
    assert cli.main(["footwear", "--foot", "left", "-o", str(tmp_path / "bad")]) == 1   # nothing to size it by
    assert "length and width" in capsys.readouterr().err
