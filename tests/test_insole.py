"""First-fit insole: synthetic feet with known answers. No number here is from a person.

block_foot: a 240 x 90 mm foot with a 12 mm-high arch tunnel under the inner
36 mm (x 70-150), so the insole's arch fill must come out at 12 - relief = 11 mm
there, on the inner side only, and 0 where the foot rests on the floor.
Insole coordinates: x forward from the back of the heel, y toward the foot's
left, the foot centred on y = 0 (so a right foot's inner side is y 9..45).
"""

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
