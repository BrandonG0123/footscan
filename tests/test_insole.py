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
    # at the outline's edge beside the heel the wall has risen to (nearly) the cup depth
    V = right.mesh.vertices
    at = V[np.abs(V[:, 0] - 50.0) < 1.0]  # where the block foot's heel is its full 90 mm wide
    lo, hi = at[:, 1].min(), at[:, 1].max()
    assert _top(right, 50.0, lo + 0.6) > p.base_mm + 0.85 * p.heel_cup_depth_mm
    # and the outline is only the 3 mm wall margin wider than the 90 mm block heel each side: slim
    # enough for a shoe's firm heel counter
    assert hi - lo == pytest.approx(90.0 + 2 * p.heel_wall_margin_mm, abs=1.0)
    # no wall beside the forefoot: base (tapering) only
    assert _top(right, 200.0, -44.0) < p.base_mm + 0.5


def test_the_heel_is_held_where_it_stands_not_where_it_bulges_higher_up():
    """A heel wider higher up than at the cup's height (as real heels are: the first real scan was 74 mm
    across at 12 mm, 86 mm at 30 mm): the outline round the heel and the cup wall follow the heel at the
    cup's height; the bulge sits over the cup, as it does inside a shoe's counter. The cup never comes
    closer than the relief to the bulge's underside."""
    import manifold3d as m3
    import trimesh

    foot = synth.curved_foot("right", leg=False)
    f = m3.Manifold(m3.Mesh(vert_properties=np.asarray(foot.vertices, dtype=np.float32),
                            tri_verts=np.asarray(foot.faces, dtype=np.uint32)))
    # a ring round the heel 8 mm wider all round, from 16 to 26 mm up (heel circle: r 32 at (32, 45))
    bulge = m3.Manifold.cylinder(10.0, 40.0, 40.0, 96).translate((32.0, 45.0, 16.0))
    mm = (f + bulge).to_mesh()
    m = trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=True)
    ins = insole.from_scan(m, "right")
    plain = insole.from_scan(foot, "right")
    p = ins.params

    def across_heel(i):  # the insole's width across the heel's widest point
        at = i.mesh.vertices[np.abs(i.mesh.vertices[:, 0] - 32.0) < 0.75]
        return at[:, 1].max() - at[:, 1].min(), at[:, 1].min()

    (width, lo), (plain_width, _) = across_heel(ins), across_heel(plain)
    assert width == pytest.approx(plain_width, abs=1.0)  # the bulge (16 mm wider) doesn't widen it
    assert width < 64.0 + 2 * p.heel_wall_margin_mm + 2.5
    # the wall stands beside the heel at the cup's height...
    assert _top(ins, 32.0, lo + 0.6) > p.base_mm + 0.85 * p.heel_cup_depth_mm
    # ...and stays the relief below the bulge's underside (16 mm up) where the two overlap
    assert _top(ins, 32.0, lo + 2.0) <= p.base_mm + 16.0 - p.relief_mm + 0.3


def test_a_heel_cup_outline_inside_the_foot_raises_nothing_under_the_foot(monkeypatch):
    """Codex's case: a scan missing the heel's lower sides can give a cup-height outline well inside the foot.
    Wherever the scan saw no sole the insole stays flat, so no wall may rise there, under the foot: here a
    foot whose sole the scan never saw (a box with no bottom), with the cup outline forced 15 mm inside."""
    import shapely
    import trimesh

    real = insole.silhouette

    def shrunk(mesh, notes=None, height=insole.SILHOUETTE_HEIGHT_MM):
        sil = real(mesh, notes, height)
        return sil.buffer(-15.0) if height < insole.SILHOUETTE_HEIGHT_MM else sil

    monkeypatch.setattr(insole, "silhouette", shrunk)
    box = trimesh.creation.box([240.0, 90.0, 25.0])
    box.apply_translation([120.0, 45.0, 12.5])
    box = box.subdivide_to_size(3.0)
    box.update_faces(box.triangles_center[:, 2] > 0.1)  # no bottom: the scan saw no sole
    box.remove_unreferenced_vertices()
    ins = insole.from_scan(box, "right")
    p = ins.params
    inside = real(ins.sole).buffer(-1.5)
    pts = [(x, y) for x in np.arange(5.0, 75.0, 5.0) for y in np.arange(-60.0, 61.0, 2.5)
           if inside.contains(shapely.Point(x, y))]
    pts = [(x, y, t) for x, y in pts if (t := _top(ins, x, y)) is not None]  # (the heel's outline shrinks too)
    assert len(pts) > 200
    tops = np.array([t for _, _, t in pts])
    assert np.abs(tops - p.base_mm).max() < 0.4, pts[int(np.argmax(np.abs(tops - p.base_mm)))]


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
def test_toes_hanging_up_in_a_sole_scan_are_laid_flat_so_the_outline_keeps_its_length(foot, monkeypatch):
    """Relaxed in the air the toes bend up off the sole; standing they lie flat. Bent up 35 degrees, their
    tips rise past the outline's height and the 250 mm foot's outline reads about 20 mm short as scanned;
    laid flat, within a few mm (TOES_JOINT_UP_MM lists the measured error). Behind the joint nothing moves."""
    from footscan.recon import completeness, foot_prep

    scan = synth.sole_up_capture(synth.bend_toes(synth.refined(synth.curved_foot(foot)), 35.0))
    placed, info = foot_prep.prepare_sole_up(scan, foot=foot)
    laid = info["toes_laid_flat"]
    assert laid["raised_deg"] == pytest.approx(35.0, abs=4.0)
    assert laid["pivot_from_heel_mm"] == pytest.approx(185.0, abs=12.0)
    assert completeness.measure(placed)["length_mm"] == pytest.approx(250.0, abs=7.0)
    # laid on the floor, not folded under it: nothing below the floor, and the toes' underside down on it
    V = placed.vertices
    assert V[:, 2].min() > -0.3
    front = V[V[:, 1] > V[:, 1].max() - 40.0]
    assert front[:, 2].min() < 2.0
    # bent, not torn: the top of the foot over the joint stretches, it doesn't open up into long triangles
    long_edges = lambda m: int((m.edges_unique_length > 6.0).sum())

    monkeypatch.setattr(foot_prep, "LAY_TOES_FLAT", False)
    as_scanned, info2 = foot_prep.prepare_sole_up(scan, foot=foot)
    assert "toes_laid_flat" not in info2
    assert completeness.measure(as_scanned)["length_mm"] < 235.0
    assert long_edges(placed) <= long_edges(as_scanned)
    # the heel, the arch and the ball (everything behind the joint) are where they were: the whole foot is
    # only centred on the mat afresh (a slide, recorded in to_mat), the longer outline's centre being further on
    from scipy.spatial import cKDTree

    slide = np.array(info["to_mat"]) @ np.linalg.inv(np.array(info2["to_mat"]))
    assert np.allclose(slide[:3, :3], np.eye(3))
    V = as_scanned.vertices
    behind = V[(V[:, 1] < V[:, 1].min() + laid["joint_from_heel_mm"] - 1.0) & (V[:, 2] < foot_prep.LEG_TRIM_MM - 1.0)]
    assert cKDTree(placed.vertices).query(behind + slide[:3, 3])[0].max() < 1e-6


@pytest.mark.parametrize("foot", ["right", "left"])
def test_toes_hanging_up_dont_tip_the_floor_set_under_the_heel_and_ball(foot):
    """Toes bent up 20 degrees hang out of the floor's contact band, which then ends at the ball: the ball
    is looked for along the whole underside instead, toes included, not 55-80% of the way to the ball
    (that's the arch, which tipped the left foot's floor 1.6 degrees). The floor stays where the foot
    stands: both sides of the ball on it, the heel too."""
    from footscan.recon import foot_prep

    scan = synth.sole_up_capture(synth.bend_toes(synth.refined(synth.curved_foot(foot)), 20.0))
    _, info = foot_prep.prepare_sole_up(scan, foot=foot)
    sides = info["ball_sides_above_floor_mm"]
    assert abs(sides["minus_x"]) < 0.5 and abs(sides["plus_x"]) < 0.5
    assert abs(info["heel_back_above_floor_mm"]) < 0.5
    assert info.get("floor_corrected_deg", 0.0) < 0.5


def test_a_front_too_steep_for_toes_hanging_up_is_left_as_scanned_and_refused_on_arrival():
    """A front rising 65 degrees past the ball isn't toes hanging up: it's left as scanned, Make insole warns
    the insole may be short, and the arrival check refuses the scan for it."""
    from footscan.recon import completeness, foot_prep

    scan = synth.sole_up_capture(synth.bend_toes(synth.refined(synth.curved_foot("right")), 65.0))
    ins, _ = foot_prep.insole_from_object_capture(scan, "right", kind="sole_up")
    info = ins.report["prep"]
    assert "toes_laid_flat" not in info
    assert any(w.startswith("THE FRONT OF THE FOOT RISES") for w in ins.report["warnings"])
    assert any(w.startswith("THE FRONT OF THE FOOT RISES") for w in completeness.from_prep(info))


def test_toes_raised_steeply_from_further_forward_are_still_judged_not_skipped_as_too_short():
    """Steep toes cover little floor: 50 mm of toes bent up 65 degrees from 200 mm reach only about 21 mm across
    it. They were skipped as too short to be toes, so neither laid flat nor warned about, and the outline read
    214 mm of 250 with nothing said (found by a Codex review, 29 Oct). Their reach is measured along the
    underside now: the 65-degree front is refused, and toes bent up 50 degrees from 215 mm are laid flat."""
    from footscan.recon import completeness, foot_prep

    steep, info = foot_prep.prepare_sole_up(
        synth.sole_up_capture(synth.bend_toes(synth.curved_foot("right"), 65.0, x_from=200.0)), foot="right")
    assert any(w.startswith("THE FRONT OF THE FOOT RISES") for w in completeness.from_prep(info))
    placed, info = foot_prep.prepare_sole_up(
        synth.sole_up_capture(synth.bend_toes(synth.curved_foot("right"), 50.0, x_from=215.0)), foot="right")
    assert info["toes_laid_flat"]["raised_deg"] == pytest.approx(50.0, abs=4.0)
    assert completeness.measure(placed)["length_mm"] > 240.0  # 235.1 when skipped


def test_toes_that_curl_as_well_as_bend_are_laid_flat_at_a_second_joint():
    """Toes bent up 20 degrees at 185 mm and their tips 30 more at 220 mm (as the real legs-flat scan 2190's toe
    tips still rose 14 mm after one joint, 29 Oct): with one joint the tips stayed 10.7 mm up and the outline
    read 7.9 mm short (SYNTHETIC); a second joint, from where the first left the toes on the floor, lays them."""
    from footscan.recon import completeness, foot_prep

    mesh = synth.bend_toes(synth.bend_toes(synth.curved_foot("right"), 30.0, x_from=220.0), 20.0, x_from=185.0)
    placed, info = foot_prep.prepare_sole_up(synth.sole_up_capture(mesh), foot="right")
    joints = info["toes_laid_flat"]["joints"]
    assert len(joints) == 2 and joints[1]["pivot_from_heel_mm"] > joints[0]["pivot_from_heel_mm"] + 20.0
    m = completeness.measure(placed)
    assert m["toe_tip_above_floor_mm"] < 4.0
    assert m["length_mm"] > 250.0 - 6.5
    assert placed.vertices[:, 2].min() > -0.3


def test_toes_already_flat_are_left_exactly_as_scanned(monkeypatch):
    """A sole scan whose toes lie along the sole: nothing is laid flat, and the prepared foot is the same,
    point for point, as with laying toes flat turned off."""
    from footscan.recon import foot_prep

    scan = synth.sole_up_capture(synth.curved_foot("right"))
    placed, info = foot_prep.prepare_sole_up(scan, foot="right")
    assert "toes_laid_flat" not in info and "toes_warning" not in info
    monkeypatch.setattr(foot_prep, "LAY_TOES_FLAT", False)
    as_scanned, _ = foot_prep.prepare_sole_up(scan, foot="right")
    assert np.array_equal(placed.vertices, as_scanned.vertices)


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
    assert r["length_mm"] == pytest.approx(255.0, abs=1.0)  # 250 mm foot + 2 mm at the toe + the 3 mm heel-cup wall
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

    ins, _ = foot_prep.insole_from_object_capture(_as_object_capture(synth.foam_print("right", shape="curved")),
                                                  "right", kind="impression")
    files = insole.write_outputs(ins, tmp_path, "insole", "test print", synthetic=True)
    pv = viewer_data.read(files["preview_insole"])
    sole = viewer_data.read(files["preview_sole"])
    assert pv["colors"] is not None and len(pv["faces"]) == len(ins.mesh.faces)
    assert len(sole["faces"]) > 1000
    # deepest colour where the fill is highest (the arch), lightest where there's none
    z = pv["vertices"][:, 2]
    assert pv["colors"][np.argmax(z)].sum() < pv["colors"][np.argmin(z)].sum()
    # at no lift the sole sits the relief above the insole's top: straight down from the sole's underside to
    # the insole's top, at points well inside the foot (away from walls and edges)
    import trimesh

    top_mesh = trimesh.Trimesh(pv["vertices"], pv["faces"], process=False)
    sole_mesh = trimesh.Trimesh(sole["vertices"], sole["faces"], process=False)
    import shapely

    # the whole sole from the end of the heel cup to the toes, 8 mm in from the sole's own outline (the
    # arch, where the insole rises, is out on the inner side)
    X, Y = np.meshgrid(np.arange(40.0, 200.0, 6.0), np.arange(-60.0, 61.0, 6.0))
    sole_outline = shapely.MultiPoint(sole["vertices"][:, :2]).convex_hull.buffer(-8.0)
    P = np.c_[X.ravel(), Y.ravel()][shapely.contains_xy(sole_outline, X.ravel(), Y.ravel())]
    down, i_d, _ = top_mesh.ray.intersects_location(np.c_[P, np.full(len(P), 100.0)], np.tile([0, 0, -1.0], (len(P), 1)),
                                                    multiple_hits=False)
    up, i_u, _ = sole_mesh.ray.intersects_location(np.c_[P, np.full(len(P), -50.0)], np.tile([0, 0, 1.0], (len(P), 1)),
                                                   multiple_hits=False)
    top_z = dict(zip(i_d.tolist(), down[:, 2]))
    pairs = [(top_z[k], z - top_z[k]) for k, z in zip(i_u.tolist(), up[:, 2]) if k in top_z]
    assert len(pairs) > 50
    gaps = np.array([g for _, g in pairs])
    # (a smooth, foot-like sole: a sharp step, which no foot has, the smoothing rounds off on purpose)
    # never more than the relief above it, never into it
    assert gaps.max() < ins.params.relief_mm + 0.4
    assert gaps.min() > -0.3
    # ...and exactly the relief wherever the insole rises to meet the sole (where it rests on the floor,
    # the insole can't go below its base, so there the sole sits right on it)
    rising = np.array([g for top, g in pairs if top > ins.params.base_mm + 2.0])
    assert len(rising) > 5 and np.median(rising) == pytest.approx(ins.params.relief_mm, abs=0.3)
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


def test_the_forefoot_edge_is_bevelled_for_a_shoes_toe_box(right):
    """Beyond the heel the base thins to edge_mm at the outline over edge_bevel_mm: a square 2-3 mm edge
    would dig into the curve where a shoe's footbed meets its sides. Inside that band, the full base."""
    import shapely

    p = right.params
    V = right.mesh.vertices
    edge_y = V[np.abs(V[:, 0] - 170.0) < 1.0][:, 1].min()  # the outer edge of the outline at x = 170
    assert _top(right, 170.0, edge_y + 0.4) < p.edge_mm + 0.6
    assert _top(right, 170.0, edge_y + p.edge_bevel_mm + 1.5) == pytest.approx(p.base_mm, abs=0.35)


def _legs_flat_scan(foot="right", bed=True, yaw=63.0, standing=None):
    """SYNTHETIC legs-flat scan: the curved foot (or ``standing``, in the same frame), face down, legs straight
    along the bed (toward -x), the foot just past the bed's end, sole facing back (+x); the bed under the shin;
    as the app hands it over."""
    import trimesh

    m = synth.curved_foot(foot) if standing is None else standing
    W = np.eye(4)
    W[:3, :3] = np.c_[[0, 0, -1.0], [0, -1.0, 0], [-1.0, 0, 0]]  # standing -> lying: up -> -x, front -> down
    m.apply_transform(W)
    parts = [m]
    if bed:
        V = m.vertices
        shin = V[V[:, 0] < -80]  # the leg, well up from the sole
        top = shin[:, 2].min()
        edge = V[:, 0][V[:, 0] < -60].max() - 20  # the bed ends a little short of the ankle
        b = trimesh.creation.box(extents=[700, 600, 40])
        b.apply_translation([edge - 350, shin[:, 1].mean(), top - 20 - 0.5])
        parts.append(b)
    return _as_object_capture(trimesh.util.concatenate(parts), yaw_deg=yaw)


@pytest.mark.parametrize("foot,bed", [("right", True), ("left", True), ("right", False)])
def test_a_legs_flat_scan_is_stood_up_from_the_leg_and_reads_the_arch(foot, bed):
    """Face down, legs straight, the foot past the end of the bed (sole facing back, not up): the bed is
    taken away, the leg's direction stands the foot up, and the sole reads as it does from a sole-up scan
    of the same foot, the arch on the inner side, the heel found under the leg."""
    from footscan.recon import foot_prep

    ins, placed = foot_prep.insole_from_object_capture(_legs_flat_scan(foot, bed), foot, kind="sole_hanging")
    r = ins.report
    p = r["prep"]
    assert p.get("bed_found", False) == bed
    assert p["heel_from"] == "the leg stands over it"
    # the same foot as a sole-up scan reads the same sole
    import trimesh

    up = synth.curved_foot(foot)
    up.apply_transform(trimesh.transformations.rotation_matrix(np.radians(25), [0, 1, 0], [0, 45, 0]))
    up.apply_transform(np.diag([1.0, -1, -1, 1]))
    ref, _ = foot_prep.insole_from_object_capture(_as_object_capture(up), foot, kind="sole_up")
    assert r["max_fill_mm"] == pytest.approx(ref.report["max_fill_mm"], abs=0.3)
    assert (r["max_fill_at_mm"]["y"] > 0) == (foot == "right")
    assert placed.vertices[:, 2].max() <= foot_prep.LEG_TRIM_MM + 1.5  # cut by triangle centres: corners poke a little above
    assert not [w for w in r["warnings"] if "ARCH IS ON THE OUTSIDE" in w or "DOESN'T LOOK" in w]


def _both_feet(gap_mm: float, leg_mm: float = 400.0):
    """SYNTHETIC both feet standing side by side (foot coordinates: x forward, y toward the person's left):
    the right foot as synth.curved_foot, the left one ``gap_mm`` to its left at the ball (negative: they
    overlap, joined into one solid, as Object Capture joins feet that touch). Each has its leg, ``leg_mm``
    of it: at 400 mm the scan's long axis runs along the legs, as with real legs on a bed; a box drawn to a
    hand's width of leg holds 100-150 mm."""
    import manifold3d as m3
    import trimesh

    right, left = synth.curved_foot("right"), synth.curved_foot("left")
    left.apply_translation([0.0, 100.0 + gap_mm, 0.0])  # each foot is 100 mm wide at the ball

    def solid(t):
        return m3.Manifold(m3.Mesh(np.asarray(t.vertices, dtype=np.float32), np.asarray(t.faces, dtype=np.uint32)))

    legs = [m3.Manifold.cylinder(leg_mm, 28.0, 28.0, 64).translate((45.0, y, 40.0)) for y in (45.0, 145.0 + gap_mm)]
    both = (solid(right) + solid(left) + legs[0] + legs[1]).to_mesh()
    return trimesh.Trimesh(np.asarray(both.vert_properties)[:, :3], np.asarray(both.tri_verts), process=True)


@pytest.mark.parametrize("foot", ["right", "left"])
@pytest.mark.parametrize("gap_mm", [-4.0, 15.0])
def test_a_legs_flat_scan_with_both_feet_in_it_keeps_the_asked_for_foot(foot, gap_mm):
    """Both legs lie on the bed, so a loose box takes in both feet (as in the first real legs-flat scan,
    LIDAR_nwb_relaxed_L_20261027-151815-2190: 221 x 217 mm on the floor). Touching (joined into one piece)
    or apart, the feet are cut apart between the shins and the asked-for one is kept: its arch on its
    inner side, a foot-shaped footprint, and a note saying both feet were there."""
    from footscan.recon import foot_prep

    ins, placed = foot_prep.insole_from_object_capture(_legs_flat_scan(standing=_both_feet(gap_mm)), foot,
                                                       kind="sole_hanging")
    r = ins.report
    assert r["prep"]["two_feet"]["kept"] == foot
    assert (r["max_fill_at_mm"]["y"] > 0) == (foot == "right")  # inner side
    assert r["prep"]["footprint_mm"]["width"] < 110
    assert not [w for w in r["warnings"] if "ARCH IS ON THE OUTSIDE" in w or "DOESN'T LOOK" in w]
    assert any(w.startswith("both feet were in the scan") for w in r["warnings"])


@pytest.mark.parametrize("foot", ["right", "left"])
def test_a_legs_flat_scan_of_both_feet_apart_with_little_leg_is_stood_up_along_the_leg(foot):
    """Two feet 30 mm apart are two pieces. With only 100 mm of each leg in the box, the pair is wider than
    it is long, so the leg's direction is read from one piece: read from both, it ran across the legs and
    the foot was stood up on its side (SYNTHETIC, this case: a 233 x 157 mm footprint)."""
    from footscan.recon import foot_prep

    ins, placed = foot_prep.insole_from_object_capture(_legs_flat_scan(standing=_both_feet(30.0, leg_mm=100.0)),
                                                       foot, kind="sole_hanging")
    r = ins.report
    fp = r["prep"]["footprint_mm"]
    assert 230.0 < fp["length"] < 265.0 and fp["width"] < 115.0, fp
    assert (r["max_fill_at_mm"]["y"] > 0) == (foot == "right")
    assert not [w for w in r["warnings"] if "DOESN'T LOOK" in w or "HEEL MAY BE MISSING" in w]


def test_an_insole_is_still_made_when_the_missing_toes_check_breaks(monkeypatch):
    """The arrival check keeps a scan its measure breaks on, so Make insole mustn't fail on it either:
    the insole is made, with a warning to look at the outline's ends."""
    from footscan.recon import completeness, foot_prep

    def broken(placed, kind=None):
        raise ValueError("empty heel band")

    monkeypatch.setattr(completeness, "measure", broken)
    ins, _ = foot_prep.insole_from_object_capture(_sole_up_scan("right"), "right", kind="sole_up")
    assert any("couldn't run (ValueError: empty heel band)" in w for w in ins.report["warnings"])


def test_a_legs_flat_scan_of_one_foot_with_a_coarse_shin_is_not_cut():
    """A simplified model's shin can be a few big triangles (here an 8-sided cylinder): their centres leave
    strips across the one leg with no centre in them, which must not be read as the gap between two shins.
    Read that way, this foot was cut in half (SYNTHETIC, this case: 48 mm wide; the bug Codex found in review)."""
    import manifold3d as m3
    import trimesh

    from footscan.recon import foot_prep

    right = synth.curved_foot("right", leg=False)
    foot = m3.Manifold(m3.Mesh(np.asarray(right.vertices, dtype=np.float32), np.asarray(right.faces, dtype=np.uint32)))
    one = (foot + m3.Manifold.cylinder(150.0, 28.0, 28.0, 8).translate((45.0, 45.0, 40.0))).to_mesh()
    standing = trimesh.Trimesh(np.asarray(one.vert_properties)[:, :3], np.asarray(one.tri_verts), process=True)
    ins, _ = foot_prep.insole_from_object_capture(_legs_flat_scan(standing=standing), "right", kind="sole_hanging")
    assert "two_feet" not in ins.report["prep"]
    assert ins.report["prep"]["footprint_mm"]["width"] > 85.0


@pytest.mark.parametrize("gap_mm", [-4.0, 15.0])
def test_a_legs_flat_scan_of_both_feet_says_whether_they_touched(gap_mm):
    """Joined into one piece, the cut between them went through surface (that side of the foot was never
    scanned); apart, it went through none."""
    from footscan.recon import foot_prep

    _, info = foot_prep.prepare_sole_hanging(_legs_flat_scan(standing=_both_feet(gap_mm)), foot="right")
    assert info["two_feet"]["touching"] == (gap_mm < 0)


def test_a_legs_flat_scan_of_one_foot_is_not_cut():
    from footscan.recon import foot_prep

    _, info = foot_prep.prepare_sole_hanging(_legs_flat_scan("left"), foot="left")
    assert "two_feet" not in info


def _rolled_forefoot_scan(deg: float):
    """SYNTHETIC sole-up scan of a right foot whose forefoot is rolled onto its outer edge (inner side up) by
    ``deg``, about that edge (y = -5), the roll building across the midfoot (x 110-140) and holding under the
    ball and toes."""
    import trimesh

    m = synth.refined(synth.shaped_foot("right", leg=True))
    V = m.vertices.copy()
    a = np.radians(deg) * np.clip((V[:, 0] - 110.0) / 30.0, 0, 1)
    dy, dz = V[:, 1] + 5.0, V[:, 2]
    V[:, 1], V[:, 2] = -5.0 + dy * np.cos(a) - dz * np.sin(a), dy * np.sin(a) + dz * np.cos(a)
    m = trimesh.Trimesh(V, m.faces, process=False)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(25), [0, 1, 0], [0, 45, 0]))
    m.apply_transform(np.diag([1.0, -1, -1, 1]))
    return _as_object_capture(m)


def test_a_forefoot_rolled_further_than_the_floor_can_level_is_flagged():
    """Relaxed, the left foot of the first real sole-up pair rolled onto its outer edge: after the floor was
    set, one side of its ball sat 8.6 mm above the other (the right foot: 1.2 mm), and the insole would have
    filled under it, a wedge. A forefoot turned 15 degrees is flagged; 5 degrees, which the tripod floor
    levels, isn't."""
    from footscan.recon import foot_prep

    rolled, _ = foot_prep.insole_from_object_capture(_rolled_forefoot_scan(15.0), "right", kind="sole_up")
    sides = rolled.report["prep"]["ball_sides_above_floor_mm"]
    assert abs(sides["plus_x"] - sides["minus_x"]) > foot_prep.BALL_ROLL_WARN_MM
    assert any(w.startswith("THE FOREFOOT WAS ROLLED") for w in rolled.report["warnings"])

    slight, _ = foot_prep.insole_from_object_capture(_rolled_forefoot_scan(5.0), "right", kind="sole_up")
    sides = slight.report["prep"]["ball_sides_above_floor_mm"]
    assert abs(sides["plus_x"] - sides["minus_x"]) < 1.0
    assert not any(w.startswith("THE FOREFOOT WAS ROLLED") for w in slight.report["warnings"])


def test_a_scan_whose_heel_is_off_the_floor_is_flagged():
    """A heel rests on the floor. When the back of a prepared scan is far above it, the heel's underside is
    missing (as in two Mac rebuilds of the first real sole scan: 46.3 and 48.4 mm; the phone's own: 1.2 mm)."""
    from footscan.recon import foot_prep

    report = dict(sole=dict(seen=0.95), max_fill_mm=10.0, max_fill_at_mm=dict(x=100.0, y=20.0))
    info = dict(kind="sole_up", footprint_mm=dict(length=245.0, width=95.0))
    assert not foot_prep.plausibility(dict(info, heel_back_above_floor_mm=1.2), report, "right")
    warned = foot_prep.plausibility(dict(info, heel_back_above_floor_mm=46.3), report, "right")
    assert len(warned) == 1 and warned[0].startswith("THE HEEL MAY BE MISSING") and "46 mm" in warned[0]


def test_a_hole_under_the_arch_is_a_hole_not_a_flat_arch():
    """Looking up through a hole in the sole, the first surface is the inside of the foot's top, facing up,
    high above the floor. That's a hole (reported, never filled upward), not sole resting on the floor."""
    foot = synth.curved_foot("right", leg=False)
    c = foot.triangles_center
    hole = (c[:, 0] > 90) & (c[:, 0] < 130) & (np.abs(c[:, 1] - 45) < 15) & (c[:, 2] < 20)
    plain = insole.from_scan(foot, "right")
    foot.update_faces(~hole)
    foot.remove_unreferenced_vertices()
    ins = insole.from_scan(foot, "right")
    from footscan.recon import foot_prep

    assert plain.report["sole"]["open_above"] < 0.01
    assert ins.report["sole"]["open_above"] > 0.05
    info = dict(kind="sole_up", footprint_mm=dict(length=250.0, width=100.0))
    assert not foot_prep.plausibility(info, plain.report, "right")
    assert any("OF THE SOLE IS A HOLE" in w for w in foot_prep.plausibility(info, ins.report, "right"))
    # a foot standing on the floor shows no sole by design: no such warning for that kind of scan
    assert not any("OF THE SOLE IS A HOLE" in w
                   for w in foot_prep.plausibility(dict(info, kind="foot"), ins.report, "right"))


def test_a_scan_torn_near_the_floor_is_flagged():
    from footscan.recon import foot_prep

    report = dict(sole=dict(seen=0.95), max_fill_mm=10.0, max_fill_at_mm=dict(x=100.0, y=20.0))
    info = dict(kind="sole_up", footprint_mm=dict(length=245.0, width=95.0))
    assert not foot_prep.plausibility(dict(info, open_edges_near_floor_mm=0.0), report, "right")
    warned = foot_prep.plausibility(dict(info, open_edges_near_floor_mm=208.0), report, "right")
    assert len(warned) == 1 and warned[0].startswith("THE SCAN IS TORN NEAR THE FLOOR: 208 mm")
