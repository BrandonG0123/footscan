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


def test_footscan_service_prints_only_the_file_on_stdout(capsys, tmp_path):
    assert cli.main(["service", "--system", "linux", "--data", str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("[Unit]") and "systemctl --user" in out.err
