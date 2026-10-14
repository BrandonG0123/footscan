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
