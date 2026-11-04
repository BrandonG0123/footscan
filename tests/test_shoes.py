"""Saved shoes: one fixed insole outline per shoe model and size (footscan/shoes.py, cli shoe and insole)."""

import pytest

import synth


def _shoe_outline(**kw):
    from footscan.recon import shoe

    return shoe.outline_from_scan(synth.shoe_insole(**kw))


def _outline_area(ins) -> float:
    """The printed insole's outline seen from above, mm2 (its section just above the bed)."""
    section = ins.mesh.section(plane_origin=[0, 0, 0.3], plane_normal=[0, 0, 1])
    planar, _ = section.to_2D()
    return float(planar.area)


def test_a_saved_shoe_is_kept_by_name_and_size_and_read_back_unchanged(tmp_path):
    from footscan import shoes

    outline, read = _shoe_outline()
    s = shoes.save(tmp_path, outline, "ASICS Gel Resolution X", "US men's 9.5", "LIDAR_shoe_1", read, default=True)
    assert s["id"] == "asics-gel-resolution-x-us-men-s-9-5" and s["shoe"] == "right"
    assert s["length_mm"] == pytest.approx(271, abs=1.5)
    back = shoes.load(tmp_path, s["id"])
    assert back["outline"] == s["outline"] and shoes.default_id(tmp_path) == s["id"]
    assert [x["id"] for x in shoes.listed(tmp_path)] == [s["id"]] and "outline" not in shoes.listed(tmp_path)[0]
    # the same name and size again replaces it; another size is another shoe
    shoes.save(tmp_path, outline, "ASICS Gel Resolution X", "US men's 10", "LIDAR_shoe_2", read)
    assert len(shoes.listed(tmp_path)) == 2 and shoes.default_id(tmp_path) == s["id"]


def test_a_saved_shoe_needs_a_name_and_size_and_ids_cant_reach_outside_the_folder(tmp_path):
    from footscan import shoes

    outline, read = _shoe_outline()
    with pytest.raises(shoes.ShoeLibraryError, match="name"):
        shoes.save(tmp_path, outline, "", "US men's 9.5", "x", read)
    for bad in ("../secrets", "Upper", "", "a/b"):
        with pytest.raises(shoes.ShoeLibraryError):
            shoes.load(tmp_path, bad)
    with pytest.raises(shoes.ShoeLibraryError, match="no saved shoe"):
        shoes.set_default(tmp_path, "not-saved")
    assert shoes.default_id(tmp_path) is None


def test_feet_of_different_sizes_in_the_same_saved_shoe_get_the_same_outline(tmp_path):
    """The rule: the shoe sets the insole's outline, the foot only the top inside it. A scan that reads 7% small
    (as the first real right-foot scan did against a ruler) shrinks the foot's own outline, but not the shoe's."""
    import trimesh

    from footscan import insole, shoes

    outline, read = _shoe_outline(ball=114.0)  # a roomy shoe: both test feet fit inside it
    s = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read)
    params = insole.InsoleParams(shoe_outline=shoes.outline_param(s), shoe_name=shoes.label(s))
    foot = synth.curved_foot("right", leg=False)
    small = foot.copy()
    small.apply_transform(trimesh.transformations.scale_matrix(0.93, [0, 0, 0]))  # 7% small all round

    own = [insole.from_scan(f, "right") for f in (foot, small)]
    fitted = [insole.from_scan(f, "right", params) for f in (foot, small)]
    # the foot's own outline follows the scan's size...
    assert _outline_area(own[1]) < 0.9 * _outline_area(own[0])
    # ...the saved shoe's doesn't: the same outline (placed round each foot, so compared by size, not position)
    assert _outline_area(fitted[1]) == pytest.approx(_outline_area(fitted[0]), rel=0.01)
    for f in fitted:
        assert f.report["length_mm"] == pytest.approx(s["length_mm"], abs=1.5)  # as placed (turned a little)
        assert f.report["outline_from"] == "shoe" and f.report["shoe_name"] == "Test Trainer, 9.5"
    assert own[0].report["outline_from"] == "foot"
    # the top under the foot is still the foot's
    assert fitted[0].report["max_fill_mm"] == own[0].report["max_fill_mm"]
    assert "Test Trainer, 9.5" in insole.summary_html(fitted[0], "test")
    assert "the foot's own (no shoe chosen)" in insole.summary_html(own[0], "test")


def _foot_file(tmp_path):
    path = tmp_path / "foot.ply"
    synth.curved_foot("right", leg=False).export(path)
    return path


def test_the_insole_command_takes_the_default_saved_shoes_outline_unless_told_otherwise(tmp_path, capsys):
    from footscan import cli

    shoes_dir = tmp_path / "shoes"
    scan = tmp_path / "stock-insole.obj"
    scan.write_bytes(synth.shoe_insole(ball=114.0).export(file_type="obj").encode())
    foot = _foot_file(tmp_path)

    def insole(*extra):
        assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "out"),
                         "--shoes", str(shoes_dir), *extra]) == 0
        return capsys.readouterr().out

    assert "outline: the foot's own (no default saved shoe" in insole()
    assert cli.main(["shoe", "add", str(scan), "--name", "Test Trainer", "--size", "9.5", "--default",
                     "--shoes", str(shoes_dir)]) == 0
    assert "saved test-trainer-9-5: Test Trainer, 9.5" in capsys.readouterr().out
    out = insole()
    assert "outline: saved shoe Test Trainer, 9.5" in out and "(the default)" in out
    assert "first-fit right insole: 27" in out  # the shoe's ~271 mm, not the foot's ~256
    assert "outline: the foot's own\n" in insole("--foot-outline")
    assert "outline: the foot's own, lengthened to 280 mm" in insole("--length", "280")
    assert "outline: saved shoe Test Trainer, 9.5" in insole("--shoe", "test-trainer-9-5")
    assert cli.main(["shoe", "list", "--shoes", str(shoes_dir)]) == 0
    assert "* test-trainer-9-5" in capsys.readouterr().out
    assert cli.main(["shoe", "default", "none", "--shoes", str(shoes_dir)]) == 0
    assert "outline: the foot's own (no default" in (capsys.readouterr(), insole())[1]
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "x"), "--shoes", str(shoes_dir),
                     "--shoe", "no-such-shoe"]) == 1
