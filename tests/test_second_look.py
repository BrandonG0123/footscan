"""Claude's look at a sole scan on arrival (second_look.py). No network is used: Claude is a stand-in client that
answers what the test tells it to. The scans are SYNTHETIC (tests/synth.py)."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from footscan import second_look as sl
from footscan.recon import completeness


class StandIn:
    """Answers each request with ``answer`` (JSON-encoded unless a string), or raises ``error``; keeps the
    requests it was sent."""

    def __init__(self, answer=None, stop_reason="end_turn", error=None):
        self.answer, self.stop_reason, self.error, self.sent = answer, stop_reason, error, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.sent.append(request)
        if self.error:
            raise self.error
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="thinking", thinking=""),
                                                                      SimpleNamespace(type="text", text=text)])


VIEWS = [("a test picture", np.full((6, 8, 3), 200, np.uint8)), ("another", np.zeros((4, 4, 3), np.uint8))]
MEASURES = dict(length_mm=250.5, width_mm=100.4, toe_end=0.33, heel_end=0.47)
INFO = dict(kind="sole_up", to_mat=[[1, 0, 0, 0]] * 4, heel_back_above_floor_mm=0.0)


def ask(answer, **kw):
    client = StandIn(answer, **kw)
    return sl.ask(VIEWS, MEASURES, INFO, "sole_up", client=client), client


# ---- the question --------------------------------------------------------------------------------------------
def test_each_picture_is_sent_after_a_line_saying_what_it_is_then_the_measures_without_the_matrix():
    _, client = ask(dict(verdict="keep", problems=[], looked_at="A whole foot."))
    req = client.sent[0]
    assert req["model"] == sl.MODEL and req["fallbacks"] == "default" and req["thinking"] == {"type": "adaptive"}
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": sl.schema()}
    content = req["messages"][0]["content"]
    assert [c["type"] for c in content] == ["text", "image", "text", "image", "text"]
    assert content[0]["text"] == "Picture 1: a test picture." and content[1]["source"]["media_type"] == "image/png"
    measured = json.loads(content[-1]["text"].split("\n", 1)[1])
    assert measured["measures"] == MEASURES and "to_mat" not in measured["preparation"]


def test_the_prompt_asks_about_the_scan_never_the_foot():
    p = sl.prompt("sole_up")
    assert "Don't comment on the foot's shape, its arch, its health or any condition" in p
    assert "When you are unsure, keep" in p and "sole to the ceiling" in p
    for code in sl.CODES:
        assert f"- {code}: " in p


def test_keep_is_kept_and_any_problems_with_it_are_dropped():
    answer, _ = ask(dict(verdict="keep", problems=[dict(code="torn", seen="A small dent.")], looked_at="Fine"))
    assert answer == dict(verdict="keep", problems=[], looked_at="Fine.", model=sl.MODEL)
    assert sl.refusals(answer) == []


def test_scan_again_keeps_only_problems_from_the_list_once_each():
    answer, _ = ask(dict(verdict="scan_again", looked_at="The heel is a smooth dome.", problems=[
        dict(code="heel_missing", seen="In picture 1 the heel is a smooth dome"),
        dict(code="heel_missing", seen="Again"),
        dict(code="flat_feet", seen="The arch is low.")]))           # not a code it may use: dropped
    assert answer["verdict"] == "scan_again"
    assert answer["problems"] == [dict(code="heel_missing", seen="In picture 1 the heel is a smooth dome.")]


def test_scan_again_naming_nothing_it_may_name_is_no_answer():
    with pytest.raises(sl.Unavailable, match="without naming a problem"):
        ask(dict(verdict="scan_again", looked_at="", problems=[dict(code="flat_feet", seen="Low arch.")]))


@pytest.mark.parametrize("answer, kw, why", [
    (dict(verdict="keep", problems=[], looked_at=""), dict(stop_reason="refusal"), "declined"),
    ("not json", {}, "wasn't the form"),
    (dict(verdict="maybe", problems=[], looked_at=""), {}, "wasn't the form"),
    (None, dict(error=TypeError("Could not resolve authentication method")), "no API key"),
])
def test_no_usable_answer_says_why(answer, kw, why):
    with pytest.raises(sl.Unavailable, match=why):
        ask(answer, **kw)


def test_what_claude_saw_is_one_line_cut_at_a_word():
    long = "The front of the scan " + "is a smooth rounded lump " * 20
    answer, _ = ask(dict(verdict="scan_again", looked_at="x", problems=[dict(code="toes_missing", seen=long)]))
    seen = answer["problems"][0]["seen"]
    assert len(seen) <= sl.MAX_SEEN + 1 and seen.endswith("…") and "\n" not in seen
    assert long.startswith(seen[:-1])


def test_every_problem_claude_may_name_gets_the_studios_own_steps():
    """Each refusal line starts with a headline in completeness.RETAKE_STEPS, so the phone shows that entry's
    title and steps (the same as for the studio's own refusals), never steps of Claude's own."""
    answer = dict(verdict="scan_again", problems=[dict(code=c, seen="") for c in sl.CODES])
    lines = sl.refusals(answer)
    assert [completeness.retake_advice(line)["code"] for line in lines] == list(sl.CODES)
    for line in lines:
        assert "Claude looked at pictures of the scan and saw this: " in line and line.endswith("following the steps.")
        assert ":  " not in line          # nothing seen: what the problem means is said instead


def test_trouble_on_the_way_keeps_the_scan_and_says_why():
    import synth

    foot = synth.shaped_foot("right")
    out = sl.look(foot, foot, MEASURES, INFO, "sole_up", client=StandIn(error=RuntimeError("down")))
    assert out == dict(error="Claude couldn't look at this scan: RuntimeError. It was kept.")
    assert sl.refusals(out) == []


# ---- the pictures --------------------------------------------------------------------------------------------
def test_the_pictures_show_the_prepared_foot_from_six_sides_and_the_model_as_it_arrived():
    import synth
    from footscan.recon import foot_prep

    scan = synth.sole_up_capture(synth.shaped_foot("right"))
    scan.vertices *= 1000.0                                   # as the studio keeps it: mm, Y up
    placed, _ = foot_prep.prepare_sole_up(scan, "y", foot="right")
    views = sl.pictures(placed, scan)
    assert [n for n, _ in views][:6] == [n for n, _, _ in sl.PREPARED_VIEWS] and len(views) == 8
    assert all(img.dtype == np.uint8 and max(img.shape[:2]) <= sl.PICTURE_PX + 60 for _, img in views)
    # from below, toes at the top: the foot spans the picture's height at 0.5 mm a pixel, and its front
    # (the top rows) is narrower than its ball
    sole = views[0][1]
    drawn = (sole < 250).any(axis=2)
    rows = np.flatnonzero(drawn.any(axis=1))
    assert (rows[-1] - rows[0] + 1) * sl.MM_PER_PX_MOST == pytest.approx(np.ptp(placed.vertices[:, 1]), abs=3.0)
    widths = drawn.sum(axis=1)[rows]
    assert widths[: len(widths) // 10].mean() < widths.max() * 0.8
