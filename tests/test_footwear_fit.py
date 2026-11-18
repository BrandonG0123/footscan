"""What a clog's print-trial pieces showed, and what that suggests for the shoe's choices (footwear_fit.py).
No shape is made here; every answer below is made up for the test (nothing has been printed).
"""

import pytest

from footscan import footwear as fw, footwear_choices as fc, footwear_fit as ff

NO_HURT = {"hurt": "no"}


def _changes(answers, choices=None):
    return {c["setting"]: (c["was"], c["to"]) for c in ff.suggest({**NO_HURT, **answers}, choices)["changes"]}


# ---- the questions ---------------------------------------------------------------------------------------
def test_the_questions_are_about_the_generators_own_trial_pieces_and_cushionings():
    asked = ff.questions()
    assert {q["piece"] for q in asked} == {*fw._TRIALS, None}          # every piece is asked about, and nothing else
    assert [q["key"] for q in asked if q["piece"] is None] == ["hurt"]  # what hurt belongs to no piece
    cushion = next(q for q in asked if q["key"] == "cushion")
    assert [a["key"] for a in cushion["answers"]] == [*fw.CUSHION, "none"]
    assert cushion["piece_title"] == "Sole block"
    assert all(set(a) == {"key", "label"} for q in asked for a in q["answers"])   # the page gets no rule, only the words


def test_a_shoe_with_no_pattern_swatch_is_not_asked_about_one_but_always_whether_anything_hurt():
    keys = [q["key"] for q in ff.questions(["sole-block", "toe-cap", "back-half"])]   # (Stone has no windows)
    assert "windows" not in keys and "swatch_roof" not in keys
    assert "cushion" in keys and "walls" in keys and keys[-1] == "hurt"


# ---- what a person recorded, checked -----------------------------------------------------------------------
def test_a_record_keeps_the_answers_given_in_the_questions_order_and_the_note_as_written():
    got = ff.checked({"answers": {"walls": "press", "hurt": "no", "cushion": "firm"}, "note": "  the soft one bottomed out \n"})
    assert list(got["answers"].items()) == [("cushion", "firm"), ("walls", "press"), ("hurt", "no")]
    assert got["note"] == "the soft one bottomed out"
    assert ff.checked({"answers": {"hurt": "no"}}) == dict(answers={"hurt": "no"}, note="")   # nothing printed yet is a record too


@pytest.mark.parametrize("findings, says", [
    ([], "must be a JSON object"),
    ({"answers": {"hurt": "no"}, "fit": "roomy"}, "not part of a trial record: fit"),        # a choice can't be slipped in
    ({"answers": ["hurt"]}, "answers must be a JSON object"),
    ({"answers": {"walls": "press"}}, "say whether anything hurt"),                           # asked of every record
    ({"answers": {}}, "say whether anything hurt"),
    ({"answers": {"hurt": "no", "walls": "tight"}}, "walls must be one of touch, press, stand_off"),
    ({"answers": {"hurt": "no", "walls": 1}}, "walls must be one of"),
    ({"answers": {"hurt": "no", "arch_height": "lower"}}, "not a question about the trial pieces: arch_height"),
    ({"answers": {"hurt": "no"}, "note": 5}, "the note must be text"),
    ({"answers": {"hurt": "no"}, "note": "x" * 501}, "the note is 501 characters; keep it to 500"),
])
def test_a_record_that_is_not_answers_to_these_questions_is_refused_in_plain_words(findings, says):
    with pytest.raises(ValueError, match=says):
        ff.checked(findings)


def test_an_answer_about_a_piece_the_shoe_has_none_of_is_refused():
    with pytest.raises(ValueError, match="this shoe has no pattern swatch among its trial pieces"):
        ff.checked({"answers": {"hurt": "no", "windows": "bars"}}, pieces=["sole-block", "toe-cap", "back-half"])
    assert ff.checked({"answers": {"hurt": "no", "windows": "bars"}}, pieces=list(fw._TRIALS))["answers"]["windows"] == "bars"


# ---- what the answers suggest ---------------------------------------------------------------------------------
def test_the_sole_block_picked_is_the_cushioning_suggested_and_the_one_the_shoe_already_has_is_no_change():
    assert _changes({"cushion": "firm"}) == {"cushion": ("medium", "firm")}       # (medium is the generator's default)
    assert _changes({"cushion": "soft"}, {"cushion": "firm"}) == {"cushion": ("firm", "soft")}
    assert _changes({"cushion": "medium"}) == {}
    said = ff.suggest({**NO_HURT, "cushion": "none"})
    assert said["changes"] == [] and "Soft, medium and firm are the only cushionings" in said["notes"][0]


@pytest.mark.parametrize("answers", [{"toe_over": "presses"}, {"toe_sides": "yes"}, {"walls": "press"}])
def test_a_piece_that_pressed_on_the_foot_suggests_one_fit_roomier(answers):
    assert _changes(answers, {"fit": "snug"}) == {"fit": ("snug", "regular")}
    assert _changes(answers) == {"fit": ("regular", "roomy")}                     # (regular is the generator's default)


def test_walls_that_stood_off_the_foot_suggest_one_fit_snugger():
    assert _changes({"walls": "stand_off"}, {"fit": "roomy"}) == {"fit": ("roomy", "regular")}
    assert _changes({"walls": "stand_off"}) == {"fit": ("regular", "snug")}


def test_several_answers_one_way_move_the_fit_one_step_and_each_is_given_as_the_reason():
    said = ff.suggest({**NO_HURT, "toe_over": "presses", "toe_sides": "yes", "walls": "press"}, {"fit": "snug"})
    (change,) = said["changes"]
    assert (change["was"], change["to"]) == ("snug", "regular")                   # one step, not three
    assert change["because"] == ["the toe cap's roof pressed on the toes", "the toe cap pressed on the sides of the toes",
                                 "the back half's walls pressed on the foot"]


def test_answers_that_point_both_ways_change_no_fit_and_say_so():
    said = ff.suggest({**NO_HURT, "toe_over": "presses", "walls": "stand_off"})
    assert said["changes"] == []
    (note,) = said["notes"]
    assert "point both ways" in note and "the toe cap's roof pressed on the toes" in note \
        and "the back half's walls stood off the foot" in note


def test_there_is_no_fit_past_the_roomiest_or_the_snuggest_and_that_is_said():
    said = ff.suggest({**NO_HURT, "walls": "press"}, {"fit": "roomy"})
    assert said["changes"] == [] and "Roomy is already the roomiest of the three fits" in said["notes"][0] \
        and "Thicker sock" in said["notes"][0]
    said = ff.suggest({**NO_HURT, "walls": "stand_off"}, {"fit": "snug"})
    assert said["changes"] == [] and "Snug is already the snuggest" in said["notes"][0] and "sock" not in said["notes"][0]


def test_the_fits_are_stepped_through_in_the_generators_own_order_of_room():
    assert ff.FITS == sorted(fw.FIT, key=lambda k: fw.FIT[k]["toe_room_mm"]) == ["snug", "regular", "roomy"]


def test_every_suggestion_is_a_choice_the_generator_takes():
    """Whatever is answered, a suggested change is a setting of the form with one of the generator's own values."""
    for q in ff.QUESTIONS:
        for a in q["answers"]:
            for choices in ({}, {"fit": "snug", "cushion": "soft"}, {"fit": "roomy", "cushion": "firm"}):
                for c in ff.suggest({**NO_HURT, q["key"]: a["key"]}, choices)["changes"]:
                    assert c["setting"] in ("cushion", "fit")
                    assert fc.checked({**choices, c["setting"]: c["to"]})[c["setting"]] == c["to"] != c["was"]


# ---- what is never suggested ---------------------------------------------------------------------------------
@pytest.mark.parametrize("answers, says", [
    ({"heel_cup": "edge"}, "The heel cup is part of the footbed"),
    ({"arch": "ridge"}, "The rise under the arch is part of the footbed"),
    ({"arch": "nothing"}, "The rise under the arch is part of the footbed"),
])
def test_the_footbed_is_never_changed_to_how_it_felt(answers, says):
    said = ff.suggest({**NO_HURT, **answers}, {"fit": "regular"})
    assert said["changes"] == [] and said["stop"] is None
    (note,) = said["notes"]
    assert says in note and "not reshaped to how it felt (no posting or correction: docs/SAFETY.md)" in note


@pytest.mark.parametrize("answers, says", [
    ({"sole_top": "no"}, "a slicer setting and not the shoe's shape"),
    ({"tread": "no"}, "no setting for the tread"),
    ({"windows": "strands"}, "a slicer setting and not the shoe's shape"),
    ({"windows": "bars"}, "No number is suggested, because none has been tried"),
    ({"swatch_roof": "no"}, "a slicer setting and not the shoe's shape"),
    ({"toe_supports": "no"}, "a slicer setting and not the shoe's shape"),
    ({"toe_past": "touch"}, "not a measure of the shoe's length: the piece has no heel"),
    ({"rim": "high"}, "not a choice on the form yet"),
    ({"rim": "low"}, "not a choice on the form yet"),
])
def test_what_is_not_a_choice_gets_its_fixed_answer_and_no_change(answers, says):
    said = ff.suggest({**NO_HURT, **answers})
    assert said["changes"] == [] and said["stop"] is None
    assert len(said["notes"]) == 1 and says in said["notes"][0]


def test_answers_that_change_nothing_say_so():
    fine = {"cushion": "medium", "sole_top": "yes", "tread": "yes", "windows": "clean", "swatch_roof": "yes",
            "toe_supports": "yes", "toe_over": "room", "toe_sides": "no", "toe_past": "no", "heel_cup": "sits",
            "arch": "support", "walls": "touch", "rim": "right"}
    assert set(fine) | {"hurt"} == {q["key"] for q in ff.QUESTIONS}
    assert ff.suggest({**NO_HURT, **fine}) == dict(changes=[], notes=[ff.NOTHING], stop=None)


def test_pieces_that_hurt_get_the_stop_rule_and_no_suggestion_at_all():
    """Not a medical device: a shoe is not adjusted round a pain. Answers that would otherwise move the fit and
    the cushioning suggest nothing once something hurt; the stop rule is docs/SAFETY.md's, unsoftened."""
    answers = {"hurt": "yes", "cushion": "soft", "walls": "press", "toe_over": "presses", "arch": "ridge"}
    assert ff.suggest({**answers, "hurt": "no"}, {"fit": "snug"})["changes"]      # (they do, when nothing hurt)
    said = ff.suggest(answers, {"fit": "snug"})
    assert said["changes"] == []
    stop = said["stop"]
    for words in ("Stop trying these pieces", "do not go on until it has been reviewed", "any new pain",
                  "numbness, tingling or burning", "an existing pain that gets worse",
                  "a mark on the skin that has not gone by the next day", "docs/SAFETY.md", "not a medical device"):
        assert words in stop, words
    assert said["notes"][0] == ff.NOTHING_FOR_HURT and "does not adjust a shoe round a pain" in said["notes"][0]
    assert any("not reshaped to how it felt" in n for n in said["notes"][1:])     # the other fixed answers still stand
    assert ff.suggest({"hurt": "no"})["stop"] is None


# ---- a record, as kept ---------------------------------------------------------------------------------------
def test_a_records_answers_are_shown_in_the_questions_own_words():
    assert ff.in_words({"cushion": "firm", "walls": "stand_off", "hurt": "no"}) == [
        dict(piece_title="Sole block", ask="Which of the three sole blocks should the sole be?", answer="The firm one (25% infill)"),
        dict(piece_title="Back half", ask="What do the walls do?", answer="Stand off it"),
        dict(piece_title=None, ask="Did anything hurt, rub, or leave a mark on the skin?", answer="No")]


def test_an_answer_an_older_record_holds_that_is_no_longer_asked_is_passed_over_not_a_crash():
    old = {"hurt": "no", "walls": "press", "lace_holes": "torn", "rim": "sharp"}
    assert [w["ask"] for w in ff.in_words(old)] == ["Did anything hurt, rub, or leave a mark on the skin?", "What do the walls do?"]
    assert [c["setting"] for c in ff.suggest(old, {"fit": "snug"})["changes"]] == ["fit"]
    # ... nor is a shoe made to a fit the generator no longer has: there is no step to take from it
    assert ff.suggest({"hurt": "no", "walls": "press"}, {"fit": "wide"}) == dict(changes=[], notes=[ff.NOTHING], stop=None)


def test_a_record_says_which_shoes_pieces_it_is_about():
    shoe = dict(made="2026-11-10T19:40:25", style="vent", choices={"style": "vent", "fit": "snug"},
                pieces=["sole-block", "toe-cap"], length_mm=280.0)
    kept = ff.record({"hurt": "no", "walls": "press"}, "tight at the little toe", shoe, "2026-11-12T08:00:00")
    assert kept == dict(recorded="2026-11-12T08:00:00",
                        about=dict(made="2026-11-10T19:40:25", style="vent", choices={"style": "vent", "fit": "snug"},
                                   pieces=["sole-block", "toe-cap"]),
                        answers={"hurt": "no", "walls": "press"}, note="tight at the little toe")
    shoe["choices"]["fit"] = "roomy"                       # the shoe made again to other choices
    assert kept["about"]["choices"]["fit"] == "snug"       # ... the record is still about the one whose pieces were tried


# ---- which shoe a record is about, and everything recorded about it read together -------------------------------
def _report(made, style="vent", pieces=("sole-block", "swatch", "toe-cap", "back-half"), **choices):
    """The studio's report of a shoe, as far as this file reads it."""
    return dict(made=made, style=style, choices=dict(style=style, **choices),
                trials=dict(pieces=[dict(piece=p, title=p) for p in pieces]) if pieces else None)


A = ff.shoe_of(_report("2026-11-10T10:00:00", fit="regular"))
B = ff.shoe_of(_report("2026-11-11T10:00:00", "stone", ("sole-block", "toe-cap", "back-half"), fit="roomy"))


def _rec(shoe, when, **answers):
    return ff.record({"hurt": "no", **answers}, "", shoe, when)


def test_only_a_shoe_whose_trial_pieces_were_cut_can_be_recorded_about():
    report = _report("2026-11-10T10:00:00", fit="regular")
    kept = ff.shoe_of(report)
    assert kept == A == dict(made="2026-11-10T10:00:00", style="vent", choices={"style": "vent", "fit": "regular"},
                             pieces=["sole-block", "swatch", "toe-cap", "back-half"])
    report["choices"]["fit"] = "snug"
    assert kept["choices"]["fit"] == "regular"             # kept as it was made, not as the report goes on
    assert ff.shoe_of(_report("x", pieces=())) is None     # made without its trial pieces
    assert ff.shoe_of(dict(made="x", style="vent", choices={}, trials=dict(error="no piece could be cut"))) is None
    assert ff.pieces_cut(None) == [] and ff.pieces_cut({}) == []


def test_a_shoe_is_shown_by_the_name_its_trial_pieces_sheet_carries():
    """The person picks the shoe their pieces were cut from by reading the pieces' sheet: the page lists each
    shoe in the sheet's own words (footwear.made_name), to the second, with the fit and cushioning it was made to."""
    newest, older = ff.shown([], [A, B])["shoes"]
    assert older["name"] == "Vent shoe made 2026-11-10 10:00:00, regular fit, medium cushioning"
    assert newest["name"] == "Stone shoe made 2026-11-11 10:00:00, roomy fit, medium cushioning"
    firm = ff.shoe_of(_report("2026-11-10T10:00:07", fit="regular", cushion="firm"))   # seven seconds after A
    assert ff.shown([], [firm])["shoes"][0]["name"] == "Vent shoe made 2026-11-10 10:00:07, regular fit, firm cushioning"
    bare = ff.shoe_of(_report("2026-11-12T10:00:00"))                                 # nothing chosen: the generator's own
    assert ff.shown([], [bare])["shoes"][0]["name"] == fw.made_name("vent", fw.ShoeParams().fit, fw.ShoeParams().cushion,
                                                                    "2026-11-12T10:00:00")
    # a shoe the studio no longer keeps is still named, from what its records say they are about
    (gone,) = ff.shown([_rec(A, "t1")], [])["shoes"]
    assert gone["name"] == older["name"] and gone["recordable"] is False


def test_everything_recorded_about_one_shoe_is_read_together():
    """Pieces are recorded one at a time as they are printed: a shoe's suggestion is made from all of them."""
    # the block picked in one record and a wall that pressed in the next: both stand
    both = ff.suggest(ff.merged([_rec(A, "t1", cushion="firm"), _rec(A, "t2", walls="press")]), A["choices"])
    assert {c["setting"]: c["to"] for c in both["changes"]} == {"cushion": "firm", "fit": "roomy"}
    # a toe cap that pressed and, later, walls that stood off point both ways across the two records
    two_ways = ff.suggest(ff.merged([_rec(A, "t1", toe_over="presses"), _rec(A, "t2", walls="stand_off")]), A["choices"])
    assert two_ways["changes"] == [] and "point both ways" in two_ways["notes"][0]
    # the newest answer to a question stands (the piece printed and tried again)
    again = ff.merged([_rec(A, "t1", walls="press"), _rec(A, "t2", walls="touch")])
    assert again["walls"] == "touch" and ff.suggest(again, A["choices"])["changes"] == []
    # ... but not for whether anything hurt: said once, it stays said
    assert ff.merged([ff.record({"hurt": "yes"}, "", A, "t1"), _rec(A, "t2", walls="press")])["hurt"] == "yes"
    assert ff.merged([]) == {}


def test_toes_that_touched_the_end_hold_a_snugger_fit_back_and_ask_for_no_roomier_one():
    """A snugger fit takes room from past the toes too (footwear.FIT), so walls that stood off don't suggest
    one where the toes already reached the end of the toe cap. Touching the end alone still changes nothing."""
    assert _changes({"walls": "stand_off"}, {"fit": "regular"}) == {"fit": ("regular", "snug")}
    held = ff.suggest({"hurt": "no", "toe_past": "touch", "walls": "stand_off"}, {"fit": "regular"})
    assert held["changes"] == []
    assert ff.SNUGGER_HELD.format(snugger="the back half's walls stood off the foot",
                                  held="the toes touched the end of the toe cap") in held["notes"]
    assert "takes room from over the toes and past them" in ff.SNUGGER_HELD
    assert _changes({"toe_past": "touch"}, {"fit": "regular"}) == {}
    assert _changes({"toe_past": "touch", "walls": "press"}, {"fit": "regular"}) == {"fit": ("regular", "roomy")}


def test_once_anything_hurt_nothing_is_suggested_for_any_shoe_of_the_capture():
    """Not for the record that said so alone, nor for that shoe alone: a later record about another piece, or
    the shoe made again, would bring the suggestions back. (docs/SAFETY.md: stop, and do not resume until
    reviewed. This program can't know of a review, so nothing here lifts it.)"""
    hurt = ff.record({"hurt": "yes", "toe_over": "presses"}, "rubbed the little toe", A, "2026-11-12T08:00:00")
    records = [_rec(A, "2026-11-11T08:00:00", cushion="firm"), hurt,
               _rec(A, "2026-11-13T08:00:00", walls="press"),              # the same shoe's next piece, nothing hurt
               _rec(B, "2026-11-14T08:00:00", cushion="soft", walls="press")]   # the shoe made again, nothing hurt
    assert ff.shown(records[:1], [A, B])["shoes"][-1]["suggestion"]["changes"]          # (before it: suggestions)
    got = ff.shown(records, [A, B])
    assert got["stop"] == dict(recorded="2026-11-12T08:00:00", made=A["made"], words=ff.STOP, nothing=ff.NOTHING_FOR_HURT)
    assert [s["made"] for s in got["shoes"]] == [B["made"], A["made"]]
    for shoe in got["shoes"]:
        assert shoe["suggestion"]["changes"] == [] and shoe["suggestion"]["stop"] == ff.STOP, shoe["made"]
        assert shoe["suggestion"]["notes"][0] == ff.NOTHING_FOR_HURT
    assert "for this foot's shoes once a piece has hurt, the cushioning included" in ff.NOTHING_FOR_HURT
    # the record that said so is one of the oldest and has been dropped: what the studio kept of it still stops
    kept = ff.hurt_in(records)
    assert kept == dict(recorded="2026-11-12T08:00:00", made=A["made"]) and ff.hurt_in(records[:1]) is None
    later = ff.shown(records[3:], [A, B], stopped=kept)
    assert later["stop"]["recorded"] == "2026-11-12T08:00:00"
    assert later["shoes"][0]["suggestion"]["changes"] == [] and later["shoes"][0]["suggestion"]["stop"] == ff.STOP
    assert ff.shown(records[3:], [A, B])["shoes"][0]["suggestion"]["changes"]            # (without it: suggestions)


def test_the_record_is_shown_shoe_by_shoe_with_the_questions_for_each_shoes_own_pieces():
    gone = ff.shoe_of(_report("2026-11-01T10:00:00", fit="snug"))         # a shoe the studio no longer keeps
    records = [_rec(gone, "2026-11-02T08:00:00", walls="press"),
               _rec(A, "2026-11-11T08:00:00", cushion="firm"), _rec(A, "2026-11-12T08:00:00", walls="press")]
    got = ff.shown(records, [A, B])
    assert got["stop"] is None
    newest, middle, oldest = got["shoes"]
    assert (newest["made"], middle["made"], oldest["made"]) == (B["made"], A["made"], gone["made"])
    # B (Stone) has no swatch and nothing recorded yet: it is asked about its own pieces, and suggests nothing
    assert newest["recordable"] and newest["records"] == [] and newest["suggestion"] is None
    assert [q["key"] for q in newest["questions"]] == [q["key"] for q in ff.questions(["sole-block", "toe-cap", "back-half"])]
    assert "windows" in [q["key"] for q in middle["questions"]]
    # A's two records, the newest first, each in the questions' words; one suggestion from the two together
    assert [r["recorded"] for r in middle["records"]] == ["2026-11-12T08:00:00", "2026-11-11T08:00:00"]
    assert middle["records"][0]["said"] == ff.in_words({"hurt": "no", "walls": "press"})
    assert {c["setting"] for c in middle["suggestion"]["changes"]} == {"cushion", "fit"}
    # a shoe whose records outlived the studio's memory of it is shown with them and can't be added to
    assert not oldest["recordable"] and oldest["questions"] == [] and len(oldest["records"]) == 1
    assert oldest["suggestion"]["changes"][0]["to"] == "regular" and oldest["choices"] == {"style": "vent", "fit": "snug"}
    assert ff.shown([], []) == dict(shoes=[], stop=None)
