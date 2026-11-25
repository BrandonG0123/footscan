"""The arch trial (insole.arch_trial, footscan insole --trial): the insole's midfoot on its own, cut out with two flat
cuts and nothing else changed, to print before the whole insole. SYNTHETIC feet only (tests/synth.py)."""

import json

import numpy as np
import pytest

import synth
from footscan import cli, insole


@pytest.fixture(scope="module")
def right():
    return insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))


def _top(mesh, P):
    hit, idx, _ = mesh.ray.intersects_location(np.c_[P, np.full(len(P), 100.0)], np.tile([0, 0, -1.0], (len(P), 1)),
                                               multiple_hits=False)
    z = np.full(len(P), np.nan)
    z[idx] = hit[:, 2]
    return z


def test_the_arch_trial_is_one_closed_piece_cut_across_the_arch_supports_highest_point(right):
    piece, rep = insole.arch_trial(right)
    a_x = right.report["arch_fill"]["x"]
    a, b = a_x - insole.ARCH_TRIAL_MM / 2, a_x + insole.ARCH_TRIAL_MM / 2
    assert piece.is_watertight and piece.body_count == 1
    assert piece.bounds[0, 0] == pytest.approx(a, abs=0.01) and piece.bounds[1, 0] == pytest.approx(b, abs=0.01)
    assert piece.bounds[0, 2] == pytest.approx(0.0, abs=1e-6)  # on the bed as the insole is
    assert rep["from_mm"] == round(a, 1) and rep["to_mm"] == round(b, 1)
    assert 0.1 < rep["share_of_insole"] < 0.4  # a fraction of the print
    assert rep["arch_fill_mm"] == right.report["arch_fill"]["max_mm"]
    assert rep["bed_fit"]["fits"]


def test_the_arch_trial_stays_inside_the_insole():
    """An arch support read near an end (a short foot, a long shoe) still gets a whole piece ARCH_TRIAL_MM long, cut
    inside the insole: never a cut past its end, which would leave a piece shorter than said."""
    ins = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    ins.report["arch_fill"] = dict(ins.report["arch_fill"], x=float(ins.mesh.bounds[0, 0]) + 0.5)
    piece, rep = insole.arch_trial(ins)
    assert piece.bounds[0, 0] >= ins.mesh.bounds[0, 0] + 0.99
    assert rep["length_mm"] == pytest.approx(insole.ARCH_TRIAL_MM, abs=0.1)
    assert rep["arch_fill_mm"] is None  # moved off the arch's top: it doesn't claim to hold it


def test_the_arch_trial_is_the_insole_there_unchanged(right):
    """Nothing but the cuts: the top surface over the piece is exactly the insole's (to the ray casts' precision),
    so what it shows in TPU is what the insole will."""
    piece, rep = insole.arch_trial(right)
    y0, y1 = piece.bounds[0, 1] + 6.0, piece.bounds[1, 1] - 6.0
    X, Y = np.meshgrid(np.linspace(rep["from_mm"] + 2, rep["to_mm"] - 2, 25), np.linspace(y0, y1, 15))
    P = np.c_[X.ravel(), Y.ravel()]
    a, b = _top(piece, P), _top(right.mesh, P)
    ok = ~np.isnan(a) & ~np.isnan(b)
    assert ok.mean() > 0.8
    assert np.abs(a[ok] - b[ok]).max() < 0.02
    assert piece.bounds[1, 2] == pytest.approx(rep["height_mm"], abs=0.06)


def test_the_mirror_images_arch_trial_is_the_mirror_of_the_pieces(right):
    piece, rep = insole.arch_trial(right)
    left_piece, left_rep = insole.arch_trial(insole.mirrored(right))
    assert left_rep["length_mm"] == rep["length_mm"] and left_rep["width_mm"] == rep["width_mm"]
    assert left_piece.volume == pytest.approx(piece.volume, rel=1e-4)
    assert left_piece.bounds[0, 1] == pytest.approx(-piece.bounds[1, 1], abs=0.01)


def test_footscan_insole_trial_writes_the_piece_and_says_never_to_stand_on_it(tmp_path, capsys):
    foot, out = tmp_path / "foot.stl", tmp_path / "out"
    synth.curved_foot("right", leg=False).export(foot)
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(out), "--length", "275", "--trial"]) == 0
    said = capsys.readouterr().out
    assert "arch trial:" in said and "print it first, the same way, at 100%" in said
    for end in (".3mf", ".stl", ".txt"):
        assert (out / f"right-insole-arch-trial{end}").is_file()
    notes = (out / "right-insole-arch-trial.txt").read_text()
    assert "NOT A MEDICAL DEVICE" in notes and "Never stand or walk on it" in notes and "100% scale" in notes
    rep = json.loads((out / "right-insole.json").read_text())["arch_trial"]
    m = insole.read_3mf(out / "right-insole-arch-trial.3mf")
    assert m["unit"] == "millimeter" and "not an insole" in m["metadata"]["Description"]
    assert np.ptp(m["vertices"][:, 0]) == pytest.approx(rep["length_mm"], abs=0.1)
    # without --trial, no piece
    out2 = tmp_path / "out2"
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(out2), "--length", "275"]) == 0
    assert not (out2 / "right-insole-arch-trial.3mf").exists()


def test_the_arch_trial_is_placed_on_the_bed_at_the_insoles_angle(tmp_path):
    """A 275 mm insole is turned to fit the 256 mm bed; its trial is turned the same, so the walls and infill run
    the same way across the arch as on the insole (the firmness it shows depends on them)."""
    ins = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    assert ins.report["bed_fit"]["angle_deg"] != 0
    insole.write_outputs(ins, tmp_path, "right-insole", "synthetic", synthetic=True)
    insole.write_arch_trial(ins, tmp_path, "right-insole", synthetic=True)
    t_insole = insole.read_3mf(tmp_path / "right-insole.3mf")["transform"]
    t_trial = insole.read_3mf(tmp_path / "right-insole-arch-trial.3mf")["transform"]
    assert t_trial[:2] == pytest.approx(t_insole[:2], abs=1e-6)


def test_a_trial_that_cant_be_cut_costs_the_insole_nothing_and_no_old_trial_is_left(tmp_path, capsys, monkeypatch):
    foot, out = tmp_path / "foot.stl", tmp_path / "out"
    synth.curved_foot("right", leg=False).export(foot)
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(out), "--length", "275", "--trial"]) == 0
    assert (out / "right-insole-arch-trial.3mf").is_file()

    def broken(_):
        raise RuntimeError("cut failed")

    monkeypatch.setattr(insole, "arch_trial", broken)
    (out / "right-insole.3mf").unlink()
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(out), "--length", "275", "--trial"]) == 0
    assert "arch trial: not made (RuntimeError: cut failed)" in capsys.readouterr().err
    assert (out / "right-insole.3mf").is_file() and (out / "right-insole-summary.html").is_file()
    assert not any((out / f"right-insole-arch-trial{end}").exists() for end in (".3mf", ".stl", ".txt"))
