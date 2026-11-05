"""The whole foot must be in a sole scan: toes and heel there, not much shorter than the person's other scans.

All shapes here are SYNTHETIC (tests/synth.py). The cut ones are closed over, as Object Capture closes a part
of the foot it never saw, so nothing is torn and the older checks don't see them.
"""

import pytest

import synth
from footscan.recon import completeness, foot_prep


def _measured(mesh):
    placed, info = foot_prep.prepare_sole_up(synth.sole_up_capture(mesh))
    return completeness.measure(placed), info


@pytest.mark.parametrize("foot", ["right", "left"])
@pytest.mark.parametrize("shape", ["shaped", "curved"])
def test_a_whole_foot_passes(foot, shape):
    mesh = synth.shaped_foot(foot) if shape == "shaped" else synth.curved_foot(foot)
    m, info = _measured(mesh)
    assert m["length_mm"] == pytest.approx(250.0, abs=3.0)
    assert m["toe_end"] < completeness.TOE_END_SQUARE and m["heel_end"] < completeness.HEEL_END_SQUARE
    assert completeness.problems(m) == [] and completeness.from_prep(info) == []


@pytest.mark.parametrize("foot", ["right", "left"])
@pytest.mark.parametrize("shape", ["shaped", "curved"])
def test_a_scan_without_its_toes_is_caught(foot, shape):
    """The front 50 mm gone (the toes and the end of the forefoot), the cut closed over."""
    mesh = synth.shaped_foot(foot) if shape == "shaped" else synth.curved_foot(foot)
    m, info = _measured(synth.cut_ends(mesh, x_to=200.0))
    found = completeness.problems(m)
    assert len(found) == 1 and found[0].startswith("THE TOES ARE MISSING") and "Scan again" in found[0]


@pytest.mark.parametrize("deg", [20, 35])
@pytest.mark.parametrize("shape", ["shaped", "curved"])
def test_toes_cut_off_are_still_caught_after_the_front_is_laid_flat(shape, deg):
    """The front 25 mm gone and what's left of the toes hanging up: laying them flat must not round the end off.
    (The real legs-flat scan 2190 lost its "toes missing" warning when its toes were laid flat, 29 Oct.)"""
    mesh = synth.shaped_foot("right") if shape == "shaped" else synth.curved_foot("right")
    m, info = _measured(synth.bend_toes(synth.cut_ends(mesh, x_to=225.0), deg))
    assert "toes_laid_flat" in info
    assert any(p.startswith("THE TOES ARE MISSING") for p in completeness.problems(m))


@pytest.mark.parametrize("foot", ["right", "left"])
def test_a_scan_with_the_heel_cut_off_is_caught(foot):
    """The back 30 mm of the heel gone, the cut closed over."""
    m, info = _measured(synth.cut_ends(synth.shaped_foot(foot), x_from=30.0))
    found = completeness.problems(m) + completeness.from_prep(info)
    assert any(p.startswith("THE HEEL IS CUT OFF") for p in found)
    assert not any(p.startswith("THE TOES") for p in found)


def test_a_scan_much_shorter_than_the_other_foot_is_caught_and_a_close_one_is_not():
    """The left sole-up scan 89df against the right foot's 2349 (real insole outlines, 227.0 and 246.4 mm)."""
    m = dict(length_mm=227.0)
    right = dict(foot="right", same_foot=False, capture_id="LIDAR_nwb_relaxed_R_x", length_mm=246.4)
    found = completeness.against_others(m, [right])
    assert len(found) == 1 and found[0].startswith("THIS FOOT IS 19 MM SHORTER than your right foot's scan")
    assert completeness.against_others(dict(length_mm=240.0), [right]) == []
    # longer than the other is not this scan's fault
    assert completeness.against_others(dict(length_mm=265.0), [right]) == []
    earlier = dict(right, foot="left", same_foot=True, capture_id="LIDAR_nwb_relaxed_L_y")
    assert "an earlier scan of the same foot" in completeness.against_others(m, [earlier])[0]


def test_make_insole_warns_about_missing_toes_too():
    """Scans kept from before the check (or imported some other way) still say so when an insole is made."""
    ins, _ = foot_prep.insole_from_object_capture(synth.sole_up_capture(synth.cut_ends(synth.shaped_foot("right"),
                                                                                       x_to=200.0)),
                                                  "right", kind="sole_up")
    assert any(w.startswith("THE TOES ARE MISSING") for w in ins.report["warnings"])
    whole, _ = foot_prep.insole_from_object_capture(synth.sole_up_capture(synth.shaped_foot("right")), "right",
                                                    kind="sole_up")
    assert not any("MISSING" in w or "CUT OFF" in w for w in whole.report["warnings"])


def test_a_scan_that_isnt_one_foot_is_caught_when_its_ends_look_whole():
    """The legs-flat scan 2190 caught both feet merged: its outline read 264.9 x 254.3 mm (real check, Oct 28).
    A real kept right sole scan, 2349, read 244.1 x 89.6 mm."""
    both = dict(length_mm=264.9, width_mm=254.3, toe_end=0.24, heel_end=0.28)
    found = completeness.problems(both)
    assert len(found) == 1 and found[0].startswith("THIS ISN'T ONE WHOLE FOOT: seen from above the scan is 265 x 254 mm")
    assert completeness.problems(dict(length_mm=244.1, width_mm=89.6, toe_end=0.23, heel_end=0.48)) == []
    # far too short to be an adult foot
    assert completeness.problems(dict(length_mm=150.0, width_mm=60.0, toe_end=0.3, heel_end=0.4))[0].startswith(
        "THIS ISN'T ONE WHOLE FOOT")


def test_a_forefoot_rolled_onto_one_edge_is_refused_on_arrival():
    """The insole would fill under the raised side of the ball: a wedge, which a first fit must not have.
    Over 5 mm between the two sides is refused; the 1.2 mm of the first real right sole-up scan is not."""
    assert completeness.from_prep(dict(ball_sides_above_floor_mm=dict(minus_x=0.2, plus_x=1.4))) == []
    found = completeness.from_prep(dict(ball_sides_above_floor_mm=dict(minus_x=0.0, plus_x=8.6)))
    assert len(found) == 1 and found[0].startswith("THE FOREFOOT WAS ROLLED") and "9 mm" in found[0]


def test_a_scan_torn_where_two_touching_feet_were_cut_apart_says_to_keep_the_other_foot_out():
    found = completeness.from_prep(dict(open_edges_near_floor_mm=153.0, two_feet=dict(touching=True)))
    assert len(found) == 1 and "other foot out of the box" in found[0]


def test_a_torn_scan_of_two_feet_that_were_apart_gets_the_usual_retake_advice():
    """Apart, the cut between them went through no surface: a tear is something else missing (toes, heel)."""
    found = completeness.from_prep(dict(open_edges_near_floor_mm=153.0, two_feet=dict(touching=False),
                                        two_feet_note="both feet were in the scan: the right one was kept"))
    assert len(found) == 1 and "covering the whole foot" in found[0] and "other foot" not in found[0]


def _every_refusal():
    """One line of each kind of refusal a sole scan can get on arrival, from the checks themselves (fed the
    measures and decisions that set each one off), with the code its steps should come under."""
    import inspect

    from footscan import server

    whole = dict(length_mm=250.0, width_mm=100.0, toe_end=0.3, heel_end=0.4)
    out = [
        (completeness.problems({**whole, "toe_end": 0.8})[0], "toes_missing"),
        (completeness.problems({**whole, "heel_end": 0.8})[0], "heel_cut_off"),
        (completeness.problems({**whole, "width_mm": 250.0})[0], "not_one_foot"),
        (completeness.against_others(whole, [dict(foot="right", same_foot=False, capture_id="R1",
                                                  length_mm=270.0)])[0], "shorter_than_other"),
        (completeness.from_prep(dict(heel_back_above_floor_mm=40.0))[0], "heel_missing"),
        (completeness.from_prep(dict(open_edges_near_floor_mm=153.0, two_feet=dict(touching=True)))[0],
         "feet_touching"),
        (completeness.from_prep(dict(open_edges_near_floor_mm=153.0))[0], "torn"),
        (completeness.from_prep(dict(ball_sides_above_floor_mm=dict(minus_x=0.0, plus_x=8.6)))[0],
         "forefoot_rolled"),
    ]
    # two come from elsewhere as text: the preparation's too-steep toes, and a preparation that failed outright
    assert 'info["toes_warning"] = (f"THE FRONT OF THE FOOT RISES' in inspect.getsource(foot_prep)
    out.append((completeness.from_prep(dict(toes_warning="THE FRONT OF THE FOOT RISES 70 DEGREES past the ball"))[0],
                "toes_curled"))
    assert "THE STUDIO COULDN'T FIND THE WHOLE FOOT: {e}" in inspect.getsource(server.check_completeness)
    out.append(("THE STUDIO COULDN'T FIND THE WHOLE FOOT: no floor. Scan again.", "foot_not_found"))
    return out


def test_every_refusal_comes_with_its_own_steps_for_the_next_scan():
    """The phone shows these before the retake: each kind of refusal gets its own title and steps, not the
    fallback."""
    for line, code in _every_refusal():
        advice = completeness.retake_advice(line)
        assert advice["code"] == code, line
        assert advice["title"] and advice["steps"] and all(s.endswith(".") for s in advice["steps"])
    codes = [c for _, c, _, _ in completeness.RETAKE_STEPS]
    assert len(set(codes)) == len(codes)


def test_a_rolled_forefoot_is_fixed_by_checking_the_ball_is_level_not_by_turning_one_way():
    """Which side of the ball looks higher depends on whether you look at the scan (sole down) or the foot
    (sole up), so the steps don't name a side: a book across the ball touches both sides or it doesn't."""
    line = completeness.from_prep(dict(ball_sides_above_floor_mm=dict(minus_x=0.0, plus_x=8.6)))[0]
    assert "book" in line
    steps = " ".join(completeness.retake_advice(line)["steps"])
    assert "book" in steps and "big-toe side and the little-toe side" in steps


def test_a_refusal_without_steps_of_its_own_keeps_its_own_words():
    advice = completeness.retake_advice("THE SOLE IS GREEN: it shouldn't be. Scan again in daylight.")
    assert advice == dict(code="other", title="The sole is green", steps=["Scan again in daylight."])
    assert completeness.retake_advice("odd")["steps"] == ["Scan again."]


@pytest.mark.parametrize("kind", ["sole_up", "sole_hanging"])
def test_the_preparation_version_is_one_not_used_before(kind):
    """Earlier preparations stamped these; reusing one would make what they made look current. (The 29 Oct
    string was kept through fc4982c's change to steep toes, so it names two different preparations.)"""
    used = {"2026-10-29: toes laid flat", "2026-10-29: toes as scanned",
            "2026-10-30: toes laid flat", "2026-10-30: toes as scanned"}
    assert foot_prep.prep_version(kind) not in used
    assert foot_prep.prep_version("sole_up") != foot_prep.prep_version("sole_hanging")
