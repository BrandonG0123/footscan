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
    (as scan LIDAR_nwb_relaxed_R_20261027-151404-2349 did against a ruler, docs/insole.md) shrinks the foot's
    own outline, but not the shoe's."""
    import trimesh

    from footscan import insole, shoes

    outline, read = _shoe_outline(ball=114.0)  # a roomy shoe: both test feet fit inside it
    s = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read)
    params = insole.InsoleParams(shoe_outline=shoes.outline_param(s), shoe_name=shoes.label(s))
    foot = synth.curved_foot("right", leg=False)
    small = foot.copy()
    small.apply_transform(trimesh.transformations.scale_matrix(0.93, [0, 0, 0]))  # 7% small all round

    own = [insole.from_scan(f, "right", insole.InsoleParams(foot_outline=True)) for f in (foot, small)]
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

    assert "outline: the generic insole outline, sized from the foot (no default saved shoe" in insole()
    assert cli.main(["shoe", "add", str(scan), "--name", "Test Trainer", "--size", "9.5", "--default",
                     "--shoes", str(shoes_dir)]) == 0
    assert "saved test-trainer-9-5: Test Trainer, 9.5" in capsys.readouterr().out
    out = insole()
    assert "outline: saved shoe Test Trainer, 9.5" in out and "(the default)" in out
    assert "first-fit right insole: 27" in out  # the shoe's ~271 mm, not the foot's ~256
    assert "outline: the foot's own\n" in insole("--foot-outline")
    assert "outline: the generic insole outline, 280 mm long" in insole("--length", "280")
    assert "outline: the foot's own, lengthened to 280 mm" in insole("--length", "280", "--foot-outline")
    assert "outline: saved shoe Test Trainer, 9.5" in insole("--shoe", "test-trainer-9-5")
    assert cli.main(["shoe", "list", "--shoes", str(shoes_dir)]) == 0
    assert "* test-trainer-9-5" in capsys.readouterr().out
    assert cli.main(["shoe", "default", "none", "--shoes", str(shoes_dir)]) == 0
    assert "outline: the generic insole outline, sized from the foot (no default" in (capsys.readouterr(), insole())[1]
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "x"), "--shoes", str(shoes_dir),
                     "--shoe", "no-such-shoe"]) == 1


def test_an_unreadable_saved_shoe_is_left_out_and_never_stays_the_default(tmp_path):
    from footscan import shoes

    outline, read = _shoe_outline()
    s = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read, default=True)
    (tmp_path / "hand-edited.json").write_text("[1, 2, 3]")
    (tmp_path / "no-name.json").write_text('{"outline": [[0, 0], [1, 0], [0, 1]]}')
    assert [x["id"] for x in shoes.listed(tmp_path)] == [s["id"]]
    (tmp_path / f"{s['id']}.json").write_text('{"name": "Test Trainer"')  # cut short
    assert shoes.listed(tmp_path) == [] and shoes.default_id(tmp_path) is None


def test_a_default_that_cant_be_read_stops_an_insole_instead_of_falling_back_to_the_foot(tmp_path, capsys):
    """A chosen default whose file is broken (a merge conflict, a hand edit) or gone must not quietly cut the
    insole to the foot's own outline (the scan's size): strict reads say what's wrong."""
    from footscan import cli, shoes

    outline, read = _shoe_outline()
    s = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read, default=True)
    (tmp_path / f"{s['id']}.json").write_text("<<<<<<< HEAD\n")
    with pytest.raises(shoes.ShoeLibraryError, match="default saved shoe can't be used"):
        shoes.default_id(tmp_path, strict=True)
    foot = _foot_file(tmp_path)
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "out"),
                     "--shoes", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "default saved shoe can't be used" in err and "footscan shoe default" in err
    assert not (tmp_path / "out").exists()
    (tmp_path / f"{s['id']}.json").unlink()  # gone altogether: the same
    with pytest.raises(shoes.ShoeLibraryError, match="no saved shoe"):
        shoes.default_id(tmp_path, strict=True)
    # told to use the foot's own outline, it still can
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "out"), "--shoes", str(tmp_path),
                     "--foot-outline"]) == 0


def test_a_saved_shoe_is_the_one_its_file_name_says(tmp_path, capsys):
    """The id is the file's name: a file copied by hand under another name (keeping the original's id inside), or
    one with no id inside, lists under its own name and loads its own outline."""
    import json

    from footscan import cli, shoes

    outline, read = _shoe_outline()
    s = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read)
    copy = json.loads((tmp_path / f"{s['id']}.json").read_text())
    copy.update(name="Other Model", size="10")
    (tmp_path / "other-model-10.json").write_text(json.dumps(copy))
    del copy["id"]
    (tmp_path / "hand-copied-9-5.json").write_text(json.dumps(dict(copy, name="Hand Copied", size="9.5")))
    listed = {x["id"]: shoes.label(x) for x in shoes.listed(tmp_path)}
    assert listed == {"hand-copied-9-5": "Hand Copied, 9.5", "other-model-10": "Other Model, 10",
                      "test-trainer-9-5": "Test Trainer, 9.5"}
    assert shoes.load(tmp_path, "other-model-10")["id"] == "other-model-10"
    assert cli.main(["shoe", "list", "--shoes", str(tmp_path)]) == 0
    assert "hand-copied-9-5: Hand Copied, 9.5" in capsys.readouterr().out


def test_choosing_the_default_never_leaves_a_moment_with_no_default(tmp_path):
    """set_default swaps a whole file in: a reader at the same moment sees the old default or the new, never
    an empty file (which would read as no default, and an insole cut to the foot's outline)."""
    import threading

    from footscan import shoes

    outline, read = _shoe_outline()
    a = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read, default=True)
    b = shoes.save(tmp_path, outline, "Test Trainer", "10", "synthetic", read)
    stop, seen = threading.Event(), []

    def write():
        i = 0
        while not stop.is_set():
            shoes.set_default(tmp_path, (a, b)[i % 2]["id"])
            i += 1

    t = threading.Thread(target=write)
    t.start()
    try:
        for _ in range(2000):
            seen.append(shoes.default_id(tmp_path))
    finally:
        stop.set()
        t.join()
    assert set(seen) <= {a["id"], b["id"]}
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([f"{a['id']}.json", f"{b['id']}.json", "default.txt"])


def test_two_long_names_that_differ_only_at_the_end_stay_two_saved_shoes(tmp_path):
    """Nothing is cut off the name, so a 2E and a 4E of one long-named shoe never overwrite each other (and the
    default never switches to the other's outline)."""
    from footscan import shoes

    base = "ASICS Gel-Resolution X Clay Court Tennis Shoe Men's Wide "  # 57 characters, then the width
    narrow, _ = _shoe_outline(ball=105.0)
    wide, read = _shoe_outline(ball=115.0)
    a = shoes.save(tmp_path, narrow, base + "2E", "US 9.5", "synthetic", read, default=True)
    b = shoes.save(tmp_path, wide, base + "4E", "US 9.5", "synthetic", read)
    assert a["id"] != b["id"] and len(shoes.listed(tmp_path)) == 2
    assert shoes.default_id(tmp_path) == a["id"]
    assert shoes.load(tmp_path, a["id"])["width_mm"] == a["width_mm"] < b["width_mm"]
    longest = shoes.shoe_id("x" * shoes.NAME_MAX, "y" * shoes.SIZE_MAX)  # the longest name and size still make an id
    assert longest == "x" * shoes.NAME_MAX + "-" + "y" * shoes.SIZE_MAX


def test_a_mistyped_shoe_scan_is_reported_as_a_missing_file(tmp_path, capsys):
    from footscan import cli

    foot = _foot_file(tmp_path)
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "out"), "--shoes",
                     str(tmp_path / "shoes"), "--shoe", str(tmp_path / "stock-insol.obj")]) == 1
    err = capsys.readouterr().err
    assert "stock-insol.obj: no such file" in err and str(foot) not in err


def test_a_saved_shoe_serves_both_feet_without_a_false_scan_warning(tmp_path):
    """One saved outline (from the right shoe's insole) is mirrored for the left foot. That's how a saved shoe
    works, so the left insole's sheet mustn't say the shoe's scan was upside down; a one-off scan of the wrong
    shoe still gets the warning."""
    from footscan import insole, shoes

    outline, read = _shoe_outline(ball=114.0, foot="right")
    s = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read)
    saved = insole.InsoleParams(shoe_outline=shoes.outline_param(s), shoe_name=shoes.label(s), shoe_saved=True)
    one_off = insole.InsoleParams(shoe_outline=shoes.outline_param(s))
    left = synth.curved_foot("left", leg=False)
    ins = insole.from_scan(left, "left", saved)
    assert ins.report["shoe_fit"]["mirrored"]
    assert not any("upside down" in w for w in ins.report["warnings"])
    assert "upside down" not in insole.summary_html(ins, "test")
    assert any("upside down" in w for w in insole.from_scan(left, "left", one_off).report["warnings"])


def test_two_sizes_of_a_shoe_with_a_long_name_stay_two_saved_shoes():
    from footscan import shoes

    name = "A Very Long Shoe Model Name That Goes On And On For Ever"  # 57 characters
    assert shoes.shoe_id(name, "US men's 9.5") != shoes.shoe_id(name, "US men's 10")
    assert shoes.shoe_id(name, "US men's 10").endswith("-us-men-s-10")


def test_saving_the_same_shoe_from_many_requests_at_once_leaves_one_readable_file(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from footscan import shoes

    outline, read = _shoe_outline()
    with ThreadPoolExecutor(8) as pool:
        saved = list(pool.map(lambda i: shoes.save(tmp_path, outline, "Test Trainer", "9.5", f"scan {i}", read),
                              range(32)))
    assert {s["id"] for s in saved} == {"test-trainer-9-5"}
    assert shoes.load(tmp_path, "test-trainer-9-5")["read_from"].startswith("scan ")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["test-trainer-9-5.json"]  # no part files left behind


def test_the_insole_command_cuts_the_other_foot_to_a_saved_shoe_without_a_false_scan_warning(tmp_path, capsys):
    """The command line's saved shoe is a saved shoe too: mirrored for the other foot with no "scanned upside
    down" warning on that insole's sheet (the studio already did this; the command line didn't)."""
    from footscan import cli

    shoes_dir = tmp_path / "shoes"
    scan = tmp_path / "right-stock-insole.obj"
    scan.write_bytes(synth.shoe_insole(ball=114.0, foot="right").export(file_type="obj").encode())
    left = tmp_path / "left-foot.ply"
    synth.curved_foot("left", leg=False).export(left)
    assert cli.main(["shoe", "add", str(scan), "--name", "Test Trainer", "--size", "9.5", "--default",
                     "--shoes", str(shoes_dir)]) == 0
    capsys.readouterr()
    assert cli.main(["insole", str(left), "--foot", "left", "-o", str(tmp_path / "out"),
                     "--shoes", str(shoes_dir)]) == 0
    out = capsys.readouterr()
    assert "outline: saved shoe Test Trainer, 9.5" in out.out
    assert "upside down" not in out.err
    assert "upside down" not in (tmp_path / "out" / "left-insole-summary.html").read_text(encoding="utf-8")


def test_the_insole_command_takes_one_way_to_set_the_outline(tmp_path, capsys):
    """A shoe's outline sets the length, so --shoe with --length (or --foot-outline) is refused before the foot
    is read, and said as the command's problem, not the foot scan's."""
    from footscan import cli, shoes

    outline, read = _shoe_outline()
    s = shoes.save(tmp_path / "shoes", outline, "Test Trainer", "9.5", "synthetic", read)
    foot = _foot_file(tmp_path)
    for extra in (["--length", "275"], ["--foot-outline"]):
        assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "out"),
                         "--shoes", str(tmp_path / "shoes"), "--shoe", s["id"], *extra]) == 1
        err = capsys.readouterr().err
        assert err.startswith("footscan insole: give --shoe or") and str(foot) not in err


def test_a_shoes_folder_that_cant_be_written_is_a_message_not_a_traceback(tmp_path, capsys):
    from footscan import cli

    scan = tmp_path / "stock-insole.obj"
    scan.write_bytes(synth.shoe_insole(ball=114.0).export(file_type="obj").encode())
    not_a_folder = tmp_path / "shoes"
    not_a_folder.write_text("a file where the shoes folder should be")
    assert cli.main(["shoe", "add", str(scan), "--name", "X", "--size", "9", "--shoes", str(not_a_folder)]) == 1
    assert capsys.readouterr().err.startswith("footscan shoe: ")


def test_two_different_shoes_that_get_the_same_id_never_replace_each_other(tmp_path):
    """The id is the name and size with only a-z and 0-9 kept, so a split between name and size that moves, or
    letters outside a-z, can give two shoes one id. The second is refused instead of silently replacing the
    first (whose insoles would go stale, or the default switch shoe). The same shoe saved again, written a
    little differently, still replaces it."""
    from footscan import shoes

    outline, read = _shoe_outline()
    for first, second in ((("Nike Pegasus 40", "US 9"), ("Nike Pegasus", "40 US 9")),
                          (("Große", "EU 42"), ("Größe", "EU 42"))):
        folder = tmp_path / first[0].replace(" ", "")
        a = shoes.save(folder, outline, *first, "synthetic", read, default=True)
        assert shoes.shoe_id(*second) == a["id"]
        with pytest.raises(shoes.ShoeLibraryError, match="a different saved shoe already has the id"):
            shoes.save(folder, outline, *second, "synthetic", read)
        assert shoes.load(folder, a["id"])["name"] == first[0] and shoes.default_id(folder) == a["id"]
    again = shoes.save(tmp_path / "NikePegasus40", outline, "nike  pegasus-40", "us 9", "a better scan", read)
    assert again["name"] == "nike  pegasus-40"


def test_a_foot_far_shorter_than_its_saved_shoe_is_warned_about_on_the_sheet(tmp_path):
    """A saved shoe's outline hides a scan that reads small: the insole fits the shoe, but the arch support sits
    where the scan puts the arch. With much more room past the toes than a shoe usually leaves, the sheet says
    to measure the foot. SYNTHETIC foot scaled to 90%."""
    from footscan import insole, shoes

    outline, read = _shoe_outline(ball=114.0)
    s = shoes.save(tmp_path, outline, "Test Trainer", "9.5", "synthetic", read)
    params = insole.InsoleParams(shoe_outline=shoes.outline_param(s), shoe_name=shoes.label(s), shoe_saved=True)
    small = synth.curved_foot("right", leg=False)
    small.apply_scale(0.9)
    ins = insole.from_scan(small, "right", params)
    assert ins.report["shoe_fit"]["room_past_toes_mm"] > 20
    assert any("the scan may read small" in w for w in ins.report["warnings"])
    fits = insole.from_scan(synth.curved_foot("right", leg=False), "right", params)
    assert fits.report["shoe_fit"]["room_past_toes_mm"] <= 20
    assert not any("the scan may read small" in w for w in fits.report["warnings"])


def test_the_sheet_says_a_lengthened_outline_was_lengthened(tmp_path):
    from footscan import cli

    foot = _foot_file(tmp_path)
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "out"),
                     "--shoes", str(tmp_path / "shoes"), "--length", "280", "--foot-outline"]) == 0
    sheet = (tmp_path / "out" / "right-insole-summary.html").read_text(encoding="utf-8")
    assert "lengthened to the shoe&#x27;s 280 mm" in sheet or "lengthened to the shoe's 280 mm" in sheet
    assert "no shoe chosen" not in sheet


def test_the_sheet_says_a_generic_outline_was_made_at_the_shoes_length(tmp_path):
    from footscan import cli

    foot = _foot_file(tmp_path)
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(tmp_path / "out"),
                     "--shoes", str(tmp_path / "shoes"), "--length", "280"]) == 0
    sheet = (tmp_path / "out" / "right-insole-summary.html").read_text(encoding="utf-8")
    assert "the generic insole outline, the same shape for every foot, 280.0 mm long" in sheet
    assert "the shoe&#x27;s length, 280 mm" in sheet or "the shoe's length, 280 mm" in sheet
    assert "lengthened" not in sheet and "no shoe chosen" not in sheet
