"""First-fit insole: synthetic feet with known answers. No number here is from a person.

block_foot: a 240 x 90 mm foot with a 12 mm-high arch tunnel under the inner
36 mm (x 70-150), so the insole's arch fill must come out at 12 - relief = 11 mm
there, on the inner side only, and 0 where the foot rests on the floor.
Insole coordinates: x forward from the back of the heel, y toward the foot's
left, the foot centred on y = 0 (so a right foot's inner side is y 9..45).
"""

from pathlib import Path

import numpy as np
import pytest

import synth
from footscan import insole


@pytest.fixture(scope="module")
def right():
    return insole.from_scan(synth.block_foot(37.0, "right"), "right")


def _top(ins, x, y):
    """Height of the insole's top surface at (x, y), by a ray from above."""
    hit, _, _ = ins.mesh.ray.intersects_location([[x, y, 100.0]], [[0, 0, -1.0]], multiple_hits=False)
    return float(hit[0, 2]) if len(hit) else None


def test_the_solid_is_printable(right):
    m = right.mesh
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    assert m.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-6)  # flat on the bed
    assert m.extents[0] == pytest.approx(240 + 2 * 2.0 + 4, abs=6)   # foot + margins (heel wall adds at the back)


def test_the_arch_fill_follows_the_scanned_sole(right):
    p = right.params
    # under the arch tunnel, inner side: base + (12 - relief); in the middle of the tunnel, away from smoothing
    assert _top(right, 110.0, 27.0) == pytest.approx(p.base_mm + 12 - p.relief_mm, abs=0.3)
    # outer side at the same place: the foot rests on the floor, so just the base
    assert _top(right, 110.0, -20.0) == pytest.approx(p.base_mm, abs=0.3)
    assert right.report["max_fill_mm"] == pytest.approx(11.0, abs=0.05)


def test_the_heel_cup_wall_is_outside_the_foot(right):
    p = right.params
    # under the heel (it rests flat): base only
    assert _top(right, 30.0, -30.0) == pytest.approx(p.base_mm, abs=0.4)
    # just outside the heel (its edge is at |y| = 42.4 here): the wall rises to the cup depth
    assert _top(right, 30.0, -45.5) == pytest.approx(p.base_mm + p.heel_cup_depth_mm, abs=0.5)
    # no wall beside the forefoot: base (tapering) only
    assert _top(right, 200.0, -44.0) < p.base_mm + 0.5


def test_left_is_the_mirror_of_right(right):
    left = insole.from_scan(synth.block_foot(37.0, "left"), "left")
    assert left.mesh.volume == pytest.approx(right.mesh.volume, rel=0.01)
    # the arch is on the other side: a left foot's inner side is its right (-y)
    p = left.params
    assert _top(left, 110.0, -27.0) == pytest.approx(p.base_mm + 12 - p.relief_mm, abs=0.3)
    assert _top(left, 110.0, 27.0) == pytest.approx(p.base_mm, abs=0.3)


def test_an_unseen_sole_is_never_guessed_upward():
    """A foot with no arch visible to the scan gives a flat insole, and says so."""
    import manifold3d as m3
    import trimesh

    body = m3.Manifold.cube((240.0, 90.0, 25.0))
    mm = body.to_mesh()
    m = trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts))
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=2.0)
    m = trimesh.Trimesh(v, f)
    m.update_faces(~((m.face_normals[:, 2] < -0.99) & (m.triangles_center[:, 2] < 0.01)))
    m.apply_transform(synth.foot_pose(0.0))
    ins = insole.from_scan(m, "right")
    assert ins.report["max_fill_mm"] == 0.0
    assert any("under the arch" in w for w in ins.report["warnings"])


def test_posting_is_refused_on_a_first_fit():
    with pytest.raises(insole.InsoleError):
        insole.from_scan(synth.block_foot(0.0), "right", insole.InsoleParams(posting_rearfoot_deg=4.0))


def test_the_3mf_is_millimetres_one_closed_object_on_the_bed(right, tmp_path):
    files = insole.write_outputs(right, tmp_path, "right-insole", "synthetic block foot", synthetic=True)
    t = insole.read_3mf(files["threemf"])
    assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= t["names"]
    assert t["unit"] == "millimeter"
    assert len(t["faces"]) == len(right.mesh.faces)
    assert "SYNTHETIC" in t["metadata"]["Title"] and "NOT A MEDICAL DEVICE" in t["metadata"]["Description"]
    # placed on the bed: transform it and check it lies within 0..256 and sits on z = 0
    a = np.array(t["transform"]).reshape(4, 3)
    placed = t["vertices"] @ a[:3] + a[3]
    assert placed[:, 2].min() == pytest.approx(0.0, abs=1e-3)
    assert placed[:, :2].min() >= 0 and placed[:, :2].max() <= 256
    sheet = open(files["summary"]).read()
    for must in ("NOT A MEDICAL DEVICE", "Rearfoot posting", "Approved for", "Stop at once", "SYNTHETIC TEST GEOMETRY"):
        assert must in sheet


@pytest.mark.parametrize("length,width,fits,how", [(200, 80, True, "straight"), (248, 102, True, "straight"), (260, 60, True, "diagonal"), (253, 102, False, None), (320, 120, False, None)])
def test_bed_fit(length, width, fits, how):
    r = insole.bed_fit(length, width, 256)
    assert r["fits"] == fits and (how is None or r["how"] == how)


def test_an_external_scan_in_any_orientation_lands_on_the_mat_and_checks_out(tmp_path):
    """scripts/external_foot.py: a closed foot (sole visible, as when scanned off the ground),
    in metres, turned and moved anywhere, comes out flat on the mat with sensible checks."""
    import sys
    from pathlib import Path

    import trimesh

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import external_foot as ef

    m = synth.block_foot(0.0, "right", origin=(0, 0), floor_cut=False)
    m.update_faces(m.triangles_center[:, 2] < 60)  # an ankle stub, not a whole leg
    m.remove_unreferenced_vertices()
    m.apply_transform(trimesh.transformations.euler_matrix(1.1, -0.4, 2.3))
    m.apply_scale(0.001)
    path = tmp_path / "foot.obj"
    m.export(path)

    assert ef.main([str(path), "--foot", "right", "-o", str(tmp_path / "out")]) == 0  # every check ok
    assert ef.main([str(path), "--foot", "left", "-o", str(tmp_path / "out2")]) == 2  # wrong foot is noticed


@pytest.mark.parametrize("foot,floor", [("right", True), ("left", True), ("right", False)])
def test_object_capture_foot_is_levelled_trimmed_and_makes_the_right_insole(foot, floor):
    """iPhone app output (metres, Y up, turned, leg included, with or without floor) -> correct insole."""
    import trimesh

    from footscan.recon import foot_prep, imported

    parts = [synth.block_foot(0.0, foot, origin=(0, 0))]
    if floor:
        top = trimesh.Trimesh([[-80, -80, 0], [330, -80, 0], [330, 170, 0], [-80, 170, 0]], [[0, 1, 2], [0, 2, 3]])
        parts.append(top.subdivide().subdivide().subdivide())
    m = trimesh.util.concatenate(parts)
    T = np.eye(4)
    c, s = np.cos(np.radians(63)), np.sin(np.radians(63))
    T[:2, :2] = [[c, -s], [s, c]]
    T[:3, 3] = [40, -25, 7]
    m.apply_transform(T)
    m.apply_transform(np.block([[imported.UP["y"].T, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.apply_scale(0.001)

    ins, placed = foot_prep.insole_from_object_capture(m, foot)
    prep = ins.report["prep"]
    assert prep["heel_from"] == "the leg stands over it"
    assert placed.vertices[:, 2].max() <= foot_prep.LEG_TRIM_MM + 0.5  # leg trimmed
    assert ins.report["sole"]["holes"] < 0.01                             # the cut is lidded, not read as holes
    # without a floor in the scan the lowest points stand in for it, a fraction of a mm high
    assert ins.report["max_fill_mm"] == pytest.approx(11.0, abs=0.1 if floor else 0.6)
    inner = ins.report["max_fill_at_mm"]["y"] > 0 if foot == "right" else ins.report["max_fill_at_mm"]["y"] < 0
    assert inner and ins.report["warnings"] == []


def test_a_closed_underside_is_flagged_as_possibly_invented():
    """Object Capture closes a model's bottom; a 'foot' whose whole sole is a surface gets a loud warning."""
    from footscan.recon import foot_prep

    closed = synth.block_foot(0.0, "right", origin=(0, 0), floor_cut=False)
    ins, _ = foot_prep.insole_from_object_capture(closed, "right", up="z")
    assert any("MAY BE INVENTED" in w for w in ins.report["warnings"])


def test_something_that_isnt_a_foot_is_flagged():
    """A shoe-sized box with a narrow footprint isn't a foot on the floor."""
    import trimesh

    from footscan.recon import foot_prep

    box = trimesh.creation.box(extents=[160.0, 45.0, 40.0])
    box.apply_translation([0, 0, 20.0])
    v, f = trimesh.remesh.subdivide_to_size(box.vertices, box.faces, max_edge=2.0)
    box = trimesh.Trimesh(v, f)
    box.update_faces(~(box.face_normals[:, 2] < -0.99))
    ins, _ = foot_prep.insole_from_object_capture(box, "right", up="z")
    assert any("DOESN'T LOOK LIKE A FOOT" in w for w in ins.report["warnings"])


def _as_object_capture(m, yaw_deg=63.0, tilt_deg=0.0):
    """Mat-frame mm -> how the iPhone app hands it over: turned, maybe not quite level, Y up, metres."""
    import trimesh

    from footscan.recon import imported

    T = trimesh.transformations.rotation_matrix(np.radians(yaw_deg), [0, 0, 1])
    T[:3, 3] = [40, -25, 7]
    m.apply_transform(T)
    if tilt_deg:
        m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(tilt_deg), [1, 0.3, 0]))
    m.apply_transform(np.block([[imported.UP["y"].T, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.apply_scale(0.001)
    return m


@pytest.mark.parametrize("foot", ["right", "left"])
def test_a_sole_up_scan_is_turned_over_rested_and_makes_the_right_insole(foot):
    """Lying face down, knee bent, sole to the ceiling, foot relaxed (tipped 25 degrees), a bed below:
    turned over, rested on heel and ball, leg trimmed, the 12 mm arch gives 11 mm of fill on the inner side."""
    import trimesh

    from footscan.recon import foot_prep

    m = synth.shaped_foot(foot)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(25), [0, 1, 0], [0, 45, 0]))
    m.apply_transform(np.diag([1.0, -1, -1, 1]))  # sole up, leg hanging down
    bed = trimesh.creation.box(extents=[600, 400, 20])
    bed.apply_translation([100, 45, -420])
    m = _as_object_capture(trimesh.util.concatenate([m, bed]))

    ins, placed = foot_prep.insole_from_object_capture(m, foot, kind="sole_up")
    r = ins.report
    assert r["prep"]["tipped_to_rest_deg"] == pytest.approx(25.0, abs=0.2)
    assert r["prep"]["heel_from"] == "the leg stands over it"
    assert placed.vertices[:, 2].max() <= foot_prep.LEG_TRIM_MM + 0.5
    assert r["sole"]["seen_under_arch"] > 0.95 and r["sole"]["holes"] < 0.01
    assert r["max_fill_mm"] == pytest.approx(11.0, abs=0.1)
    assert (r["max_fill_at_mm"]["y"] > 0) == (foot == "right")  # inner side
    assert r["warnings"] == []


@pytest.mark.parametrize("foot", ["right", "left"])
def test_a_foam_print_is_found_flipped_rested_and_makes_the_right_insole(foot):
    """A foot pressed 30 mm into a foam block on a table, scanned with the box 1.5 degrees off level:
    the print is cut out of box and table, the heel found by width, 11 mm of fill on the inner side."""
    from footscan.recon import foot_prep

    m = _as_object_capture(synth.foam_print(foot, depth=30.0), tilt_deg=1.5)
    ins, placed = foot_prep.insole_from_object_capture(m, foot, kind="impression")
    r = ins.report
    assert r["prep"]["print_deepest_mm"] == pytest.approx(30.0, abs=0.2)
    assert r["prep"]["foam_top_tilt_deg"] == pytest.approx(1.5, abs=0.1)
    assert r["prep"]["heel_from"].startswith("the narrower end")
    assert r["sole"]["seen"] > 0.95 and r["sole"]["holes"] < 0.01
    assert r["max_fill_mm"] == pytest.approx(11.0, abs=0.1)
    assert (r["max_fill_at_mm"]["y"] > 0) == (foot == "right")
    assert r["length_mm"] == pytest.approx(258.0, abs=1.0)  # 250 mm foot + 2 mm at the toe + the 6 mm heel-cup wall
    assert r["warnings"] == []


def test_a_print_of_the_other_foot_is_noticed():
    from footscan.recon import foot_prep

    ins, _ = foot_prep.insole_from_object_capture(synth.foam_print("right"), "left", up="z", kind="impression")
    assert any("ARCH IS ON THE OUTSIDE" in w for w in ins.report["warnings"])


def test_a_foam_box_with_no_print_is_refused():
    import trimesh

    from footscan.recon import foot_prep

    block = trimesh.creation.box(extents=[330.0, 130.0, 70.0])
    block.apply_translation([0, 0, 35.0])
    with pytest.raises(foot_prep.FootPrepError):
        foot_prep.prepare_impression(block, up="z")


@pytest.mark.parametrize("tilt", [5.0, 8.0])
def test_a_densely_meshed_foam_print_on_a_tilted_table_reads_the_same(tilt):
    """The foam's top is found as a whole plane, however finely it's meshed, with the box a few degrees off level."""
    from footscan.recon import foot_prep

    m = synth.foam_print("right", depth=30.0).subdivide().subdivide().subdivide()
    m = _as_object_capture(m, tilt_deg=tilt)
    ins, _ = foot_prep.insole_from_object_capture(m, "right", kind="impression")
    r = ins.report
    assert r["prep"]["foam_top_tilt_deg"] == pytest.approx(tilt, abs=0.1)
    assert r["prep"]["print_deepest_mm"] == pytest.approx(30.0, abs=0.2)
    assert r["max_fill_mm"] == pytest.approx(11.0, abs=0.1) and r["warnings"] == []


def _sole_up_scan(foot, noise_mm=0.0, wavy=False):
    import trimesh

    m = synth.refined(synth.shaped_foot(foot))
    if noise_mm:
        m = synth.bumps(m, noise_mm, waves=(20.0, 40.0)) if wavy else synth.speckle(m, noise_mm)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(25), [0, 1, 0], [0, 45, 0]))
    m.apply_transform(np.diag([1.0, -1, -1, 1]))
    return _as_object_capture(m)


def test_a_clean_scan_is_left_exactly_as_it_is():
    from footscan.recon import foot_prep

    ins, _ = foot_prep.insole_from_object_capture(_sole_up_scan("right"), "right", kind="sole_up")
    p = ins.report["prep"]
    assert p["surface_noise_mm"] <= foot_prep.NOISY_SCAN_MM and p["denoised"].startswith("no")
    assert ins.report["max_fill_mm"] == pytest.approx(11.0, abs=0.1)


@pytest.mark.parametrize("kind", ["sole_up", "impression"])
def test_scan_speckle_is_measured_smoothed_out_and_does_not_lift_the_arch(kind):
    """0.3 mm of speckle (bumps ~2 mm across): read as roughly that, blurred away, the floor set from
    the heel and the ball of the foot rather than the noise's lowest specks, so the 12 mm arch still
    gives about 11 mm of fill, on the inner side, with no rough-scan warning."""
    from footscan.recon import foot_prep

    m = (_sole_up_scan("right", 0.3) if kind == "sole_up"
         else _as_object_capture(synth.speckle(synth.refined(synth.foam_print("right"), 3.0), 0.3)))
    ins, _ = foot_prep.insole_from_object_capture(m, "right", kind=kind)
    r = ins.report
    assert 0.15 < r["prep"]["surface_noise_mm"] < 0.5
    assert r["prep"]["denoised"].startswith("blurred")
    assert r["max_fill_mm"] == pytest.approx(11.0, abs=0.7)
    assert r["max_fill_at_mm"]["y"] > 0
    assert not any("rough" in w for w in r["warnings"])


def test_a_rough_scan_says_so():
    from footscan.recon import foot_prep

    ins, _ = foot_prep.insole_from_object_capture(_sole_up_scan("left", 1.5), "left", kind="sole_up")
    r = ins.report
    assert r["prep"]["surface_noise_mm"] > foot_prep.ROUGH_SCAN_MM
    assert any("surface is rough" in w for w in r["warnings"])
    assert r["max_fill_at_mm"]["y"] < 0  # still the inner side


def test_long_gentle_undulations_are_shape_not_noise():
    """Waves 20-40 mm across are the size of the foot's own shapes: they mustn't be read as noise."""
    from footscan.recon import foot_prep

    ins, _ = foot_prep.insole_from_object_capture(_sole_up_scan("right", 0.7, wavy=True), "right", kind="sole_up")
    assert ins.report["prep"]["surface_noise_mm"] <= foot_prep.NOISY_SCAN_MM


@pytest.mark.parametrize("foot", ["right", "left"])
def test_two_foam_blocks_side_by_side_give_the_right_print_not_a_box(foot):
    """A box with a block for each foot, scanned together (a gap between the blocks): each block
    is outlined on its own, so the walls and bottoms between them are never taken for a print,
    and the print that looks like the chosen foot is used."""
    import trimesh

    from footscan.recon import foot_prep

    right = synth.refined(synth.foam_print("right"), 3.0)
    left = synth.refined(synth.foam_print("left"), 3.0)
    left.apply_translation([0, 160, 0])
    m = _as_object_capture(trimesh.util.concatenate([right, left]))
    ins, _ = foot_prep.insole_from_object_capture(m, foot, kind="impression")
    r = ins.report
    assert r["prep"]["print_deepest_mm"] == pytest.approx(30.0, abs=0.3)
    assert r["prep"]["footprint_mm"]["length"] == pytest.approx(250.0, abs=3.0)
    assert (r["max_fill_at_mm"]["y"] > 0) == (foot == "right")
    assert "used the one that looks like" in r["prep"].get("pieces_note", "")


@pytest.mark.parametrize("kind", ["foot", "sole_up", "impression"])
def test_the_recorded_transform_maps_the_scan_as_handed_over_onto_the_prepared_one(kind):
    """prep.to_mat (scan as the app hands it over -> mat frame) must be the whole turn and move,
    for every kind: a point of the input, moved by it, lands where that point is in the result."""
    import trimesh

    from footscan.recon import foot_prep

    if kind == "foot":
        m = _as_object_capture(synth.block_foot(0.0, "right", origin=(0, 0)))
    elif kind == "sole_up":
        m = _sole_up_scan("right")
    else:
        m = _as_object_capture(synth.foam_print("right"))
    ins, placed = foot_prep.insole_from_object_capture(m, "right", kind=kind)
    T = np.array(ins.report["prep"]["to_mat"])
    moved = m.copy()
    moved.apply_transform(T)
    # every prepared point lies (to within smoothing) on the moved input's surface; the
    # preparation splits triangles, so its points needn't be the input's own corners
    sample = placed.vertices[placed.vertices[:, 2] < 60][::50]
    _, d, _ = trimesh.proximity.closest_point(moved, sample)
    assert np.median(d) < 0.5


def test_if_the_exact_outline_fails_the_insole_still_covers_the_whole_foot(monkeypatch):
    """GEOS has thrown on some dense scans; the fallback must be a filled outline, never a fragment."""
    import shapely

    def boom(*a, **k):
        raise shapely.errors.GEOSException("forced")

    monkeypatch.setattr(shapely, "concave_hull", boom)
    ins = insole.from_scan(synth.block_foot(37.0, "right"), "right")
    assert ins.report["length_mm"] > 240 and ins.report["width_mm"] > 90
    assert any("convex outline" in w for w in ins.report["warnings"])


@pytest.mark.parametrize("depth", [12.0, 30.0, 45.0])
def test_a_coarse_print_of_any_depth_is_found(depth):
    """A coarse model (a phone's quick one): wall triangles span the whole depth, their centres far
    below the foam's top, yet the print opens at the top and must be found."""
    from footscan.recon import foot_prep

    placed, info = foot_prep.prepare_impression(synth.foam_print("right", depth=depth), up="z", foot="right")
    assert info["print_deepest_mm"] == pytest.approx(depth, abs=0.3)
    assert ("shallow_warning" in info) == (depth < foot_prep.PRINT_SHALLOW_MM)


@pytest.mark.parametrize("bed_below_sole", [200.0, 250.0, 420.0])
def test_a_bed_close_under_a_sole_up_scan_is_not_taken_for_the_foot(bed_below_sole):
    """Lying face down with a short leg, a knee bent past a right angle or a pillow under the shin,
    the bed can be 200-300 mm from the sole: found and cut away, never mistaken for the scan."""
    import trimesh

    from footscan.recon import foot_prep

    m = synth.refined(synth.shaped_foot("right"))
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(25), [0, 1, 0], [0, 45, 0]))
    m.apply_transform(np.diag([1.0, -1, -1, 1]))  # sole up; its top surface is now at about z = -25 ... 0
    bed = trimesh.creation.box(extents=[700, 500, 30])
    bed.apply_translation([100, 45, m.vertices[:, 2].max() - bed_below_sole - 15])
    ins, _ = foot_prep.insole_from_object_capture(_as_object_capture(trimesh.util.concatenate([m, bed])), "right",
                                                  kind="sole_up")
    fp = ins.report["prep"]["footprint_mm"]
    assert fp["length"] == pytest.approx(250, abs=5) and fp["width"] == pytest.approx(100, abs=5)
    assert ins.report["max_fill_mm"] == pytest.approx(11.0, abs=0.3)


def test_a_gap_in_the_scanned_foam_top_doesnt_cut_the_print():
    """Missing scan data splits the foam's top into two patches; they're one block, and the whole
    250 mm print is kept (not half of it, not 'two prints')."""
    from footscan.recon import foot_prep

    m = synth.refined(synth.foam_print("right"), 3.0)
    gap = (m.triangles_center[:, 2] > 66) & (np.abs(m.triangles_center[:, 0] - 125) < 4)
    m.update_faces(~gap)
    m.remove_unreferenced_vertices()
    placed, info = foot_prep.prepare_impression(m, up="z", foot="right")
    assert info["footprint_mm"]["length"] == pytest.approx(250, abs=3)
    assert "pieces_note" not in info and "pieces_warning" not in info


def test_two_blocks_close_together_still_give_the_print():
    """Blocks 15 mm apart are outlined as one; the walls and the table between them still never
    beat the print, which faces up out of the foam."""
    import trimesh

    from footscan.recon import foot_prep

    right = synth.refined(synth.foam_print("right"), 3.0)
    left = synth.refined(synth.foam_print("left"), 3.0)
    left.apply_translation([0, 145, 0])  # blocks 130 wide: a 15 mm gap
    placed, info = foot_prep.prepare_impression(trimesh.util.concatenate([right, left]), up="z", foot="left")
    assert info["print_deepest_mm"] == pytest.approx(30.0, abs=0.3)
    assert info["footprint_mm"]["length"] == pytest.approx(250, abs=3)
    assert foot_prep._looks_like(placed) == "left"


def test_a_print_scanned_without_the_table_keeps_its_sole():
    """Object Capture often leaves the table out. A deep print's flat bottom must not be taken for
    the table (which would cut the sole away)."""
    from footscan.recon import foot_prep

    m = synth.foam_print("right")
    m.update_faces(m.triangles_center[:, 2] > 0.5)  # no table
    m.remove_unreferenced_vertices()
    placed, info = foot_prep.prepare_impression(m, up="z", foot="right")
    assert info["print_deepest_mm"] == pytest.approx(30.0, abs=0.3)
    assert info["footprint_mm"]["length"] == pytest.approx(250, abs=3)


def test_a_clean_curved_surface_is_not_mistaken_for_a_noisy_one():
    """Smoothing pulls a curved surface inward; that mustn't read as noise (it did, and a clean dome
    was then blurred, lifting its floor edge by about 2 mm)."""
    from footscan.recon import foot_prep

    dome = synth.refined(synth.dome_foot(), 2.0)
    info = {}
    out = foot_prep._denoise(dome, info)
    assert info["surface_noise_mm"] <= 0.02
    assert np.array_equal(out.vertices, dome.vertices)  # left exactly as it is


def test_the_insole_comes_with_a_3d_preview_and_the_sheet_says_how_the_foot_was_captured(tmp_path):
    """preview-insole.bin (coloured by fill) and preview-sole.bin next to the 3MF; the summary sheet
    says what kind of scan it was, the load on the foot and, for a foam print, has a box for the
    calipers' reading of the print's depth."""
    from footscan.recon import foot_prep, viewer_data

    ins, _ = foot_prep.insole_from_object_capture(_as_object_capture(synth.foam_print("right")), "right",
                                                  kind="impression")
    files = insole.write_outputs(ins, tmp_path, "insole", "test print", synthetic=True)
    pv = viewer_data.read(files["preview_insole"])
    sole = viewer_data.read(files["preview_sole"])
    assert pv["colors"] is not None and len(pv["faces"]) == len(ins.mesh.faces)
    assert len(sole["faces"]) > 1000
    # deepest colour where the fill is highest (the arch), lightest where there's none
    z = pv["vertices"][:, 2]
    assert pv["colors"][np.argmax(z)].sum() < pv["colors"][np.argmin(z)].sum()
    # at no lift the sole sits the relief above the insole's top, where the insole follows it
    from scipy.spatial import cKDTree

    top = pv["vertices"][pv["vertices"][:, 2] > 3.5]
    under = sole["vertices"][sole["vertices"][:, 2] < 25]
    d, i = cKDTree(top[:, :2]).query(under[:, :2], distance_upper_bound=0.8)
    ok = np.isfinite(d)
    gap = under[ok, 2] - top[i[ok], 2]
    assert np.median(gap) == pytest.approx(ins.params.relief_mm, abs=0.3)
    assert Path(files["preview_insole"]).name == "insole-preview.bin"
    sheet = Path(files["summary"]).read_text()
    assert "How the foot was captured" in sheet and "semi-weight-bearing" in sheet
    assert "Print depth, calipers" in sheet and "NOT A MEDICAL DEVICE" in sheet


def test_lengthening_for_a_shoe_keeps_the_foot_shaped_part_and_extends_only_the_front():
    """A shoe's insole is longer than the foot: the heel, arch and ball stay where the foot is; only the
    flat front reaches further. Never shorter than the foot."""
    base = insole.from_scan(synth.block_foot(37.0, "right"), "right")
    long = insole.from_scan(synth.block_foot(37.0, "right"), "right", insole.InsoleParams(target_length_mm=275.0))
    assert long.report["length_mm"] == pytest.approx(275.0, abs=0.6)
    assert long.report["max_fill_mm"] == base.report["max_fill_mm"]
    for x, y in [(30, 0), (110, 25), (150, 0)]:  # heel, arch, ball: the same height
        assert _top(long, x, y) == pytest.approx(_top(base, x, y), abs=0.05)
    assert any("lengthened to 275 mm" in w for w in long.report["warnings"])
    with pytest.raises(insole.InsoleError):
        insole.from_scan(synth.block_foot(37.0, "right"), "right", insole.InsoleParams(target_length_mm=200.0))


def test_the_bed_check_uses_the_insoles_own_outline():
    """A foot-shaped outline narrow at both ends fits a square bed's diagonal far better than a rectangle
    of the same length: an oval 270 x 106 mm fits a 256 mm bed turned about 45 degrees; a 270 x 250
    slab doesn't fit at all."""
    t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
    oval = np.c_[135 * np.cos(t), 53 * np.sin(t)]
    fit = insole.bed_fit_shape(oval, 256.0)
    assert fit["fits"] and 40 <= fit["angle_deg"] <= 50
    assert insole.bed_fit_shape(np.c_[[0, 270, 270, 0], [0, 0, 250, 250]], 256.0)["fits"] is False
    small = insole.bed_fit_shape(oval * 0.5, 256.0)
    assert small["how"] == "straight" and small["angle_deg"] == 0.0


def _ball_wedge(placed, foot="right"):
    """Inner minus outer sole height (mm) across the ball of the foot, as the generator reads the sole."""
    import shapely

    from footscan.recon import plantar

    fm = insole.output_frame(plantar.run(placed, foot)["foot_mesh"], foot)
    sil = insole.silhouette(fm)
    x0, y0, x1, y1 = sil.bounds
    xs, ys = np.arange(x0, x1, 1.0), np.arange(y0, y1, 1.0)
    X, Y = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(sil.buffer(-8), X, Y)
    H, S = insole.sole_heights(fm, xs, ys, inside)
    ball = inside & (X > x0 + 0.62 * (x1 - x0)) & (X < x0 + 0.72 * (x1 - x0)) & (S == 1)
    mid = np.median(Y[ball])
    return float(np.median(H[ball & (Y > mid)]) - np.median(H[ball & (Y <= mid)]))


def test_an_unloaded_foot_with_its_forefoot_turned_in_gets_no_wedge(monkeypatch):
    """Relaxed with no weight on it, the forefoot turns in (its inner side up), so the scan's lowest
    points are the outer heel and the outer ball: resting it there builds a wedge (posting) into the
    insole. The floor goes through the standing tripod (the heel and both sides of the ball): the
    wedge goes; the toes, hanging up in the air, get no fill."""
    import trimesh

    from footscan.recon import foot_prep

    m = synth.refined(synth.shaped_foot("right", leg=True))
    # turn the forefoot in as one block (forefoot varus): the turn builds across the midfoot
    # (x 110-140) and holds at 5 degrees under the ball and the toes, its inner side (+y) up
    V = m.vertices.copy()
    a = np.radians(5.0) * np.clip((V[:, 0] - 110.0) / 30.0, 0, 1)
    dy, dz = V[:, 1] - 45.0, V[:, 2]
    V[:, 1], V[:, 2] = 45.0 + dy * np.cos(a) - dz * np.sin(a), dy * np.sin(a) + dz * np.cos(a)
    m = trimesh.Trimesh(V, m.faces, process=False)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(25), [0, 1, 0], [0, 45, 0]))
    m.apply_transform(np.diag([1.0, -1, -1, 1]))
    scan = _as_object_capture(m)

    ins, placed = foot_prep.insole_from_object_capture(scan, "right", kind="sole_up")
    p = ins.report["prep"]
    assert p["floor_from"].startswith("standing tripod") and p["floor_corrected_deg"] > 1.0
    assert ins.params.toes_flat_from == foot_prep.SOLE_UP_TOES_FLAT_FROM
    with_tripod = _ball_wedge(placed)

    monkeypatch.setattr(foot_prep, "_settle_floor", lambda placed, info, unloaded=False: np.eye(4))
    _, resting = foot_prep.insole_from_object_capture(scan, "right", kind="sole_up")
    on_lowest_points = _ball_wedge(resting)
    assert on_lowest_points > 0.6        # resting on its lowest points: a wedge across the ball
    assert abs(with_tripod) < 0.3        # standing on heel and both sides of the ball: level
