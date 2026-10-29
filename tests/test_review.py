"""Review packets for new insoles, and the always-on start-up files.

All insoles here are built from SYNTHETIC block feet (tests/synth.py), through the studio's own
make_insole, so the packets read exactly what the studio writes.
"""

import json
import plistlib
import shutil
import zipfile

import numpy as np
import pytest

import synth
from footscan import cli, review, server, service
from footscan.recon import imported

SPEC = dict(review.DEFAULT_SPEC, target_length_mm=275.0, length_tolerance_mm=1.0, pair_tolerance_mm=1.0)


def _capture(data, cid, foot, length):
    """A foot capture as the iPhone app imports it (metres, Y up), with an insole made by the studio."""
    d = data / "captures" / cid
    d.mkdir(parents=True)
    m = synth.block_foot(0.0, foot, origin=(0, 0))
    m.apply_transform(np.block([[imported.UP["y"].T, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.apply_scale(0.001)
    m.export(d / "mesh.ply")
    meta = dict(capture_id=cid, foot=foot, method="imported_mesh", condition="swb", scan_kind="foot",
                mesh=dict(up="y"))
    meta["insole"] = server.make_insole(d, meta, length_mm=length)
    assert "error" not in meta["insole"], meta["insole"]
    server.write_json(d / "capture.json", meta)
    return d


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("built")
    _capture(data, "R275", "right", 275.0)   # right foot, built to the shoe's length
    _capture(data, "Lfoot", "left", None)    # left foot, built to the foot's own length
    return data


@pytest.fixture
def data(built, tmp_path):
    """A fresh copy per test (copy2 keeps the model's modification time, so the insoles stay current)."""
    shutil.copytree(built, tmp_path / "data")
    return tmp_path / "data"


def _only(data, cid):
    """Just one capture (drop the others), so no other foot is in play."""
    for d in (data / "captures").iterdir():
        if d.name != cid:
            shutil.rmtree(d)
    return data


def _check(packet_dir, name):
    return next(c for c in json.loads((packet_dir / "review.json").read_text())["checks"] if c["name"] == name)


def test_an_insole_built_to_the_shoe_length_passes_the_size_checks(data):
    _only(data, "R275")
    [p] = review.run_once(data, SPEC)
    assert _check(p, "length")["ok"] and _check(p, "3mf_size")["ok"] and _check(p, "summary_sheet")["ok"]
    assert _check(p, "foot")["ok"] and _check(p, "no_posting")["ok"] and _check(p, "bed")["ok"]
    assert json.loads((p / "review.json").read_text())["flags"] == []
    md = (p / "packet.md").read_text()
    assert "NOT A MEDICAL DEVICE" in md and "100% scale" in md and "ASICS Gel Resolution X" in md


def test_an_insole_not_built_to_the_shoe_length_is_flagged(data):
    _only(data, "Lfoot")
    [p] = review.run_once(data, SPEC)
    c = _check(p, "length")
    assert not c["ok"] and "275.0 mm" in c["found"]
    assert "length" in json.loads((p / "review.json").read_text())["flags"]


def test_a_left_and_right_of_different_lengths_are_flagged_and_drawn_together(data):
    made = review.run_once(data, SPEC)
    assert len(made) == 2
    for p in made:
        assert not _check(p, "pair_length")["ok"]  # 275 mm against the foot's own length
        assert (p / "pair.png").read_bytes().startswith(b"\x89PNG")


def test_pictures_are_real_pngs_at_half_a_millimetre_per_pixel(data):
    _only(data, "R275")
    [p] = review.run_once(data, SPEC)
    for name in ("top.png", "side.png"):
        raw = (p / name).read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        width = int.from_bytes(raw[16:20], "big")
        # 275 mm long at 0.5 mm per pixel (give or take the last pixel), plus 20 pixels of margin each side
        assert abs(width - (275.0 / review.MM_PER_PX + 40)) <= 1


def test_the_top_view_has_no_false_pits():
    """A flat-topped slab drawn from above: every pixel inside it shows the top (no bottom face showing through)."""
    import trimesh

    slab = trimesh.creation.box(extents=(200, 80, 5))
    slab.apply_translation(-slab.bounds[0])
    rgb = review.top_view(slab)
    inside = rgb[25:-25, 25:-25].reshape(-1, 3)  # away from the edges and the scale bar
    assert len(np.unique(inside, axis=0)) == 1


def test_a_packet_is_written_once_per_build_and_waits_until_answered(data):
    _only(data, "R275")
    [p] = review.run_once(data, SPEC)
    assert review.run_once(data, SPEC) == []  # nothing new
    assert review.unreviewed(data) == [p]
    (p / "claude-review.md").write_text("Verdict: READY TO SLICE\n")
    assert review.unreviewed(data) == []


def test_no_packet_for_an_insole_whose_model_has_since_changed(data):
    _only(data, "R275")
    mesh = data / "captures" / "R275" / "mesh.ply"
    mesh.write_bytes(mesh.read_bytes() + b"\n")  # replaced: the insole no longer matches the scan
    assert review.pending(data) == [] and review.run_once(data, SPEC) == []


def test_a_3mf_that_would_print_at_the_wrong_size_is_flagged(data):
    _only(data, "R275")
    f = data / "captures" / "R275" / "insole" / "insole.3mf"
    with zipfile.ZipFile(f) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["3D/3dmodel.model"] = parts["3D/3dmodel.model"].replace(b'unit="millimeter"', b'unit="inch"')
    with zipfile.ZipFile(f, "w") as z:
        for n, b in parts.items():
            z.writestr(n, b)
    [p] = review.run_once(data, SPEC)
    assert not _check(p, "3mf_size")["ok"]


def test_posting_in_an_insole_is_flagged(data):
    _only(data, "R275")
    j = data / "captures" / "R275" / "insole" / "insole.json"
    rep = json.loads(j.read_text())
    rep["params"]["posting_rearfoot_deg"] = 4.0
    j.write_text(json.dumps(rep))
    [p] = review.run_once(data, SPEC)
    assert not _check(p, "no_posting")["ok"]


def test_a_broken_insole_is_logged_and_the_others_still_get_packets(data):
    (data / "captures" / "Lfoot" / "insole" / "insole.stl").write_bytes(b"not an stl")
    logs = []
    made = review.run_once(data, SPEC, log=logs.append)
    assert [p.parent.name for p in made] == ["R275"]
    assert any("Lfoot" in m and "failed" in m for m in logs)


def test_a_packet_never_mixes_two_builds(data):
    """The studio swaps in a rebuilt insole a moment before it records the build in capture.json:
    a packet started for the old build is dropped, and nothing half-written is left behind."""
    _only(data, "R275")
    [(folder, meta)] = review.pending(data)
    j = folder / "insole" / "insole.json"
    rep = json.loads(j.read_text())
    j.write_text(json.dumps(dict(rep, length_mm=rep["length_mm"] + 5)))  # new files, capture.json not yet updated
    with pytest.raises(review.Superseded):
        review.build_packet(data, folder, meta, SPEC)
    assert not review.packet_dir(data, "R275", meta["insole"]["made"]).exists()
    j.write_text(json.dumps(rep))
    server.write_json(folder / "capture.json", dict(meta, insole=dict(meta["insole"], made="2099-01-01T00:00:00")))
    with pytest.raises(review.Superseded):  # capture.json already names a newer build
        review.build_packet(data, folder, meta, SPEC)


def test_a_rebuild_swapped_in_while_copying_drops_the_packet(data, monkeypatch):
    """The studio renames a whole new insole/ folder into place: if that happens between copying
    insole.json and the STL, the packet would mix two builds, so it is dropped instead."""
    _only(data, "R275")
    [(folder, meta)] = review.pending(data)
    ins, real_copy, done = folder / "insole", shutil.copy2, []

    def copy_then_swap(src, dst, **kw):
        out = real_copy(src, dst, **kw)
        if not done:  # after the first file: a rebuild lands (same numbers, new files)
            done.append(1)
            shutil.copytree(ins, folder / "insole.new")
            ins.rename(folder / "insole.old")
            (folder / "insole.new").rename(ins)
        return out

    monkeypatch.setattr(shutil, "copy2", copy_then_swap)
    with pytest.raises(review.Superseded):
        review.build_packet(data, folder, meta, SPEC)
    assert not list((data / "reviews" / "R275").iterdir())  # no packet, no half-written folder


def test_a_second_writer_never_deletes_a_finished_packet_or_its_review(data):
    """The server's watcher and a footscan review run at once: the packet that finished first stays."""
    _only(data, "R275")
    [(folder, meta)] = review.pending(data)
    p = review.build_packet(data, folder, meta, SPEC)
    (p / "claude-review.md").write_text("Verdict: READY TO SLICE\n")
    assert review.build_packet(data, folder, meta, SPEC) == p
    assert (p / "claude-review.md").read_text() == "Verdict: READY TO SLICE\n"
    assert [q.name for q in p.parent.iterdir()] == [p.name]  # no temporary folders left


def test_the_reviewer_is_handed_packets_someone_else_wrote(data):
    """The service writes the packet; a watcher started later with --exec still hands it to Claude, once."""
    import threading

    _only(data, "R275")
    [p] = review.run_once(data, SPEC)  # as the server would
    stop, handed = threading.Event(), []

    def on_new(packet):
        handed.append(packet)
        if len(handed) == 1:
            threading.Timer(0.3, stop.set).start()  # a few more rounds, to see it isn't handed twice

    t = threading.Thread(target=review.watch, args=(data, 0.05, None),
                         kwargs=dict(on_new=on_new, stop=stop, log=lambda m: None))
    t.start()
    t.join(60)
    stop.set()
    assert handed == [p]


def test_a_packet_reads_its_own_copies_of_the_files(data):
    _only(data, "R275")
    [p] = review.run_once(data, SPEC)
    files = json.loads((p / "review.json").read_text())["files"]
    for name in ("insole.json", "insole.stl", "insole.3mf", "summary.html"):
        assert files[name] == str(p / "files" / name) and (p / "files" / name).is_file()


def test_a_packet_for_a_build_that_has_since_changed_is_no_longer_listed(data):
    _only(data, "R275")
    [p] = review.run_once(data, SPEC)
    assert review.unreviewed(data) == [p]
    mesh = data / "captures" / "R275" / "mesh.ply"
    mesh.write_bytes(mesh.read_bytes() + b"\n")  # the scan's model replaced: that insole is stale
    assert review.unreviewed(data) == []


def test_the_watcher_keeps_going_after_a_bad_round(data, tmp_path):
    """A mistyped review-spec.json is logged, and once it's fixed the next round writes the packet."""
    import threading

    _only(data, "R275")
    spec = tmp_path / "spec.json"
    spec.write_text("{ not json")
    stop, logs = threading.Event(), []

    def log(m):
        logs.append(m)
        if "this round failed" in m:
            spec.write_text(json.dumps(SPEC))
        if m.startswith("review packet: ") and "trying" not in m:
            stop.set()

    t = threading.Thread(target=review.watch, args=(data, 0.05, spec), kwargs=dict(stop=stop, log=log))
    t.start()
    t.join(120)
    assert not t.is_alive() and any("this round failed" in m for m in logs) and review.unreviewed(data)


def test_the_bed_is_checked_against_the_printer_in_the_spec(data):
    _only(data, "R275")
    [p] = review.run_once(data, dict(SPEC, bed_mm=150.0))
    assert not _check(p, "bed")["ok"] and "150 mm bed" in _check(p, "bed")["found"]


def test_a_3mf_placed_with_a_stretch_is_flagged(data):
    """A 10% stretch across the insole (the transform's second row) would print 10% too wide at 100%."""
    _only(data, "R275")
    f = data / "captures" / "R275" / "insole" / "insole.3mf"
    with zipfile.ZipFile(f) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    model = parts["3D/3dmodel.model"].decode()
    i = model.index('transform="') + len('transform="')
    t = model[i:model.index('"', i)].split()
    t[3:6] = [str(float(v) * 1.1) for v in t[3:6]]
    parts["3D/3dmodel.model"] = (model[:i] + " ".join(t) + model[model.index('"', i):]).encode()
    with zipfile.ZipFile(f, "w") as z:
        for n, b in parts.items():
            z.writestr(n, b)
    [p] = review.run_once(data, SPEC)
    assert not _check(p, "3mf_size")["ok"]


def test_a_summary_sheet_without_its_signature_line_is_flagged(data):
    _only(data, "R275")
    f = data / "captures" / "R275" / "insole" / "summary.html"
    f.write_text(f.read_text().replace("<th>Signature</th>", "<th></th>"))
    [p] = review.run_once(data, SPEC)
    c = _check(p, "summary_sheet")
    assert not c["ok"] and "signature" in c["found"]


def test_packet_folders_have_no_colons_so_they_work_on_windows(tmp_path):
    p = review.packet_dir(tmp_path, "cap", "2026-10-29T17:49:04")
    assert p.name == "2026-10-29T17-49-04"


def test_the_spec_file_in_the_repo_is_the_shoe_being_fitted():
    spec = review.load_spec()
    assert spec["shoe"] == "ASICS Gel Resolution X" and spec["target_length_mm"] == 275.0
    assert spec["slicer_scale_percent"] == 100


def test_review_list_names_each_waiting_packet(data, capsys):
    _only(data, "R275")
    [p] = review.run_once(data, SPEC)
    capsys.readouterr()
    assert cli.main(["review", "--list", "--data", str(data)]) == 0
    assert str(p / "packet.md") in capsys.readouterr().out


# ---- the always-on start-up files ---------------------------------------------------------------

@pytest.mark.parametrize("system", service.SYSTEMS)
def test_every_service_serves_on_the_wifi_with_https_and_review_and_never_public(system, tmp_path):
    r = service.render(system, tmp_path / "footscan", tmp_path / "data")
    for arg in ("--host 0.0.0.0", "--https", "--review", "--port 8765"):
        assert arg in r["content"].replace("</string>\n    <string>", " ")
    assert "--public" not in r["content"]  # the internet is a separate step, with the owner's go-ahead


def test_the_macos_service_is_a_valid_launch_agent_that_restarts(tmp_path):
    r = service.render("macos", tmp_path / "foot scan", tmp_path / "data")
    plist = plistlib.loads(r["content"].encode())
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert plist["ProgramArguments"][0] == str(tmp_path / "foot scan" / ".venv" / "bin" / "footscan")
    assert plist["WorkingDirectory"] == str(tmp_path / "foot scan")


def test_the_linux_service_restarts_and_quotes_paths_with_spaces(tmp_path):
    r = service.render("linux", tmp_path / "foot scan", tmp_path / "data")
    assert "Restart=always" in r["content"]
    assert f'ExecStart="{tmp_path / "foot scan" / ".venv" / "bin" / "footscan"}" serve' in r["content"]


def test_the_windows_service_opens_the_port_on_private_networks_only(tmp_path):
    r = service.render("windows", tmp_path / "footscan", tmp_path / "data")
    assert "nssm install Footscan" in r["content"] and "Scripts/footscan.exe" in r["content"].replace("\\", "/")
    assert "-Profile Private" in r["content"]


def test_the_windows_service_refuses_a_data_folder_with_spaces(tmp_path):
    with pytest.raises(ValueError, match="without spaces"):
        service.render("windows", tmp_path / "footscan", tmp_path / "my data")


def test_the_macos_steps_make_the_folders_launchd_needs(tmp_path):
    r = service.render("macos", tmp_path / "footscan", tmp_path / "feet")
    assert r["steps"][0] == f'mkdir -p ~/Library/LaunchAgents "{tmp_path / "feet"}"'


def test_the_save_step_repeats_the_choices_made(tmp_path):
    r = service.render("linux", tmp_path / "footscan", tmp_path / "feet", port=9000, review=False)
    assert "--port 9000" in r["steps"][1] and "--no-review" in r["steps"][1] and str(tmp_path / "feet") in r["steps"][1]


def test_footscan_service_prints_only_the_file_on_stdout(capsys, tmp_path):
    assert cli.main(["service", "--system", "linux", "--data", str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("[Unit]") and "systemctl --user" in out.err
