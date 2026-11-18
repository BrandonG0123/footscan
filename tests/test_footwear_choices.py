"""The wearer's choices for a clog, and a description read into them. No shape is made here and no network is
used: the Claude reader is given a stand-in client that answers what the test tells it to.
"""

import json
from types import SimpleNamespace

import pytest

from footscan import footwear as fw, footwear_choices as fc


# ---- the form's choices ----------------------------------------------------------------------------------
def test_the_forms_lists_and_limits_are_the_generators_own():
    o = fc.options()
    assert [s["key"] for s in o["styles"]] == list(fw.STYLES)
    assert [f["key"] for f in o["fits"]] == list(fw.FIT) and o["toes"] == list(fw.TOE_SHAPES)
    assert {c["key"]: c["infill_percent"] for c in o["cushions"]} == fw.CUSHION
    stone = next(s for s in o["styles"] if s["key"] == "stone")
    assert stone["windows"] is False and stone["sole_mm"] == fw.STYLES["stone"]["sole_mm"]
    assert o["limits"] == dict(sole_mm=list(fw.SOLE_MM), sock_mm=list(fw.SOCK_MM), openness=list(fw.OPENNESS),
                               length_mm=list(fw.FOOT_LENGTH_MM))
    d = fw.ShoeParams()
    assert o["defaults"] == dict(style=d.style, fit=d.fit, toe=d.toe, cushion=d.cushion, sock_mm=d.sock_mm)
    assert o["untested"] == fw.UNTESTED          # the page says so in the generator's own words


def test_choices_become_the_generators_settings_and_what_is_left_out_stays_its_default():
    p = fc.params_from({"style": "stone", "fit": "roomy", "toe": "square", "cushion": "firm", "sole_mm": "14",
                        "openness": 0.2, "sock_mm": 1.5, "length_mm": 260, "width_mm": "97"})   # a form's numbers are text
    assert (p.style, p.fit, p.toe, p.cushion) == ("stone", "roomy", "square", "firm")
    assert (p.sole_mm, p.openness, p.sock_mm, p.foot_length_mm, p.foot_width_mm) == (14.0, 0.2, 1.5, 260.0, 97.0)
    assert fc.params_from({}) == fw.ShoeParams()
    assert fc.params_from({"style": "", "sole_mm": " ", "length_mm": None}) == fw.ShoeParams()   # an empty field is no choice
    assert fc.checked({"style": "vent", "sole_mm": ""}) == {"style": "vent"}


@pytest.mark.parametrize("choices, says", [
    ({"style": "boot"}, "style must be one of vent, stream, stone"),
    ({"fit": "tight"}, "fit must be one of"),
    ({"toe": 3}, "toe must be one of"),
    ({"cushion": "hard"}, "cushion must be one of"),
    ({"sole_mm": fw.SOLE_MM[1] + 1}, "between 8 and 40"),
    ({"sole_mm": fw.SOLE_MM[0] - 0.5}, "between 8 and 40"),
    ({"openness": 0.6}, "between 0 and 0.5"),
    ({"sock_mm": -1}, "between 0 and 4"),
    ({"sock_mm": True}, "sock_mm must be a number"),
    ({"sole_mm": "thick"}, "sole_mm must be a number"),
    ({"openness": "nan"}, "between 0 and 0.5"),
    ({"length_mm": 26.0}, "between 180 and 330"),          # centimetres typed for millimetres
    ({"width_mm": 0}, "width_mm"),
    ([], "must be a JSON object"),
])
def test_a_choice_outside_the_generators_lists_and_limits_is_refused_in_plain_words(choices, says):
    with pytest.raises(ValueError, match=says):
        fc.checked(choices)


def test_what_is_not_a_setting_of_the_shoe_is_refused_not_ignored():
    """Nothing reaches the generator by another name: no posting, no arch height, no heel drop from the form."""
    for extra in ("posting_deg", "posting_rearfoot_deg", "arch_mm", "drop_mm", "upper_mm", "heel_rim_mm", "throat"):
        with pytest.raises(ValueError, match="not a setting of the shoe"):
            fc.checked({"style": "vent", extra: 4})


def test_the_limits_the_form_shows_are_the_ones_the_generator_refuses_at():
    for kwargs, limit in ((dict(sole_mm=fw.SOLE_MM[1] + 0.5), "the sole is between"), (dict(sock_mm=fw.SOCK_MM[1] + 0.5), "sock_mm"),
                          (dict(openness=fw.OPENNESS[1] + 0.05), "openness")):
        with pytest.raises(fw.FootwearError, match=limit):
            fw.build("right", fw.ShoeParams(foot_length_mm=260.0, foot_width_mm=97.0, **kwargs))


# ---- a description, read by looking for known words --------------------------------------------------------
@pytest.mark.parametrize("text, settings", [
    ("Something airy and roomy", dict(style="vent", fit="roomy")),
    ("A smooth closed clog, snug and firm", dict(style="stone", fit="snug", cushion="firm")),
    ("long windows down the side, a square toe, soft", dict(style="stream", toe="square", cushion="soft")),
    ("Stone style with a pointed front", dict(style="stone", toe="tapered")),
    ("BREATHABLE!  Loose.", dict(style="vent", fit="roomy")),                   # case and punctuation don't matter
    ("hello there", {}),
])
def test_known_words_are_read_into_the_settings_they_mean(text, settings):
    r = fc.from_keywords(text)
    assert r["settings"] == settings and r["read_by"] == "keywords"
    assert {u["setting"]: u["value"] for u in r["understood"]} == settings


def test_each_choice_says_which_words_it_was_read_from():
    r = fc.from_keywords("A smooth, plain clog with no holes")
    assert r["understood"] == [dict(setting="style", value="stone", words=["smooth", "plain", "no holes"], judgment=None)]
    # every style is a closed-toe shoe: "closed toe" picks none of them
    assert fc.from_keywords("a closed toe clog")["settings"] == {}


def test_a_word_said_not_to_be_wanted_does_not_count_and_a_not_stops_at_its_own_clause():
    assert fc.from_keywords("not too tight")["settings"] == {}
    assert fc.from_keywords("no holes please")["settings"] == {"style": "stone"}        # the phrase itself says no
    assert fc.from_keywords("no slots or stripes")["settings"] == {}                    # within three words of the "no"
    # "not" reaches "tight" and no further: the comma ends its clause, so soft and the square toe are asked for
    assert fc.from_keywords("not too tight, soft, square toe")["settings"] == {"cushion": "soft", "toe": "square"}
    assert fc.from_keywords("not tight but soft")["settings"] == {"cushion": "soft"}


def test_two_values_for_one_setting_keep_the_one_most_words_point_to_and_say_so():
    r = fc.from_keywords("smooth and plain, a bit sleek")
    assert r["settings"] == {"style": "stone"}
    assert any("more than one way for style" in n and "sleek" in n and "stone was kept" in n for n in r["notes"])
    later = fc.from_keywords("snug, or maybe roomy")           # one word each: the later mention
    assert later["settings"] == {"fit": "roomy"}


def test_a_word_for_an_amount_becomes_this_readers_own_number_and_says_it_is_a_judgment():
    r = fc.from_keywords("a thick sole, very open, for thick socks")
    assert r["settings"] == dict(sole_mm=fc.THICK_SOLE_MM, openness=fc.MORE_OPEN, sock_mm=fc.THICK_SOCK_MM)
    assert all(u["judgment"] and "this reader's own number" in u["judgment"] for u in r["understood"])
    assert fc.from_keywords("thin sole, fewer holes")["settings"] == dict(sole_mm=fc.THIN_SOLE_MM, openness=fc.LESS_OPEN)
    # every such number is one the generator accepts
    assert fw.SOLE_MM[0] <= fc.THIN_SOLE_MM < fc.THICK_SOLE_MM <= fw.SOLE_MM[1]
    assert fw.OPENNESS[0] <= fc.LESS_OPEN < fc.MORE_OPEN <= fw.OPENNESS[1] and fw.SOCK_MM[0] < fc.THICK_SOCK_MM <= fw.SOCK_MM[1]
    for _, _, phrases in fc.WORDS:
        fc.checked({s: v for s, v, p in fc.WORDS if p is phrases})          # and every listed value is a real one


def test_a_thickness_given_in_millimetres_is_taken_as_given_inside_the_limits_and_said_outside_them():
    r = fc.from_keywords("a thick sole, 12.5 mm sole really, and 2mm thicker socks")
    assert r["settings"] == dict(sole_mm=12.5, sock_mm=2.0)                  # the number wins over the word
    assert [u for u in r["understood"] if u["setting"] == "sole_mm"] == [
        dict(setting="sole_mm", value=12.5, words=["12.5 mm sole"], judgment=None)]
    out = fc.from_keywords("sole of 55 mm")
    assert out["settings"] == {} and any("'sole of 55 mm' is outside what the generator makes (8 to 40 mm)" in n for n in out["notes"])
    # a number said not to be wanted is not set, like a word
    assert fc.from_keywords("roomy, but not a 30 mm sole")["settings"] == {"fit": "roomy"}


@pytest.mark.parametrize("text, answer", [
    ("in red please", "Colour is the spool"),
    ("something to play tennis in", "walking and casual wear only, not for sport"),
    ("good for running", "not for sport"),
    ("I have flat feet", "Not a medical device"),
    ("more arch support", "Not a medical device"),
    ("something supportive", "Not a medical device"),
    ("I have high arches", "Not a medical device"),
    ("my podiatrist said to", "Not a medical device"),
    ("my heel hurts", "see a podiatrist"),
    ("for hiking socks", "not for sport"),                    # hiking is a sport here, whatever the socks
    ("snug and firm for badminton", "not for sport"),
    ("something for the gym and for training", "not for sport"),
    ("firm, so my feet don't hurt", "Not a medical device"),  # a pain said not to be wanted is still a wish to treat it
    ("with laces", "Only the slip-on clog exists"),
    ("a high heel", "The heel is low (it sits 6 mm above the ball of the foot)"),
    ("waterproof and grippy", "untested on this design"),
    ("US 9.5", "Size comes from the foot's own measurements"),
    ("size 44", "not from a shoe size"),
])
def test_what_is_asked_for_that_no_setting_gives_gets_its_fixed_answer(text, answer):
    r = fc.from_keywords(text)
    assert r["settings"] == {} and any(answer in n for n in r["notes"])


def test_the_medical_and_sport_answers_are_the_safety_rules_unsoftened():
    """docs/SAFETY.md: not a medical device, never sport. These two answers are requirements, not copy."""
    answers = {key: answer for key, _, answer in fc.NOT_SETTINGS}
    assert answers["medical"].startswith("Not a medical device: no setting supports, corrects or treats anything")
    assert "no posting" in answers["medical"] and "see a podiatrist or another clinician" in answers["medical"]
    assert answers["sport"] == "This shoe is for walking and casual wear only, not for sport: nothing was set for that."


@pytest.mark.parametrize("text, answer", [
    ("I need a firm sole and a snug fit for my flat feet", "Not a medical device"),
    ("Airy and roomy. I have flat feet.", "Not a medical device"),                 # another sentence of the same wish
    ("For my flat feet:\n- firm sole\n- snug fit", "Not a medical device"),        # a wish written as a list
    ("I have plantar fasciitis; a firm thick sole", "Not a medical device"),
    ("Make it firm so my feet don't hurt", "Not a medical device"),
    ("A soft sole so there is no pain", "Not a medical device"),
    ("snug and firm to play tennis in; smooth, with a thick sole", "not for sport"),
    ("Snug, 12 mm sole.\nFor volleyball", "not for sport"),
])
def test_a_description_that_says_the_shoe_is_for_a_foot_condition_or_for_sport_is_not_read_at_all(text, answer):
    """A firmer sole "for my flat feet" would be a setting chosen to treat a foot: the fixed answer says none
    was, and no rule about sentences can tell which other lines belong to the wish. So nothing is read."""
    r = fc.from_keywords(text)
    assert r["settings"] == {} and r["understood"] == [] and r["read_by"] == "keywords" and r["not_read"] is True
    assert answer in r["notes"][-2] and r["notes"][-1] == fc.NOT_READ
    assert fc.NOTHING_FOUND not in r["notes"]


def test_a_sport_said_not_to_be_wanted_is_no_purpose_and_the_description_is_read():
    r = fc.from_keywords("A casual clog, airy, not for sport. Soft, and never for running")
    assert r["settings"] == dict(style="vent", cushion="soft") and r["notes"] == [] and "not_read" not in r
    assert fc.wanted_for("airy, not for sport") == [] and fc.wanted_for("airy, for sport") == ["sport"]
    assert fc.wanted_for("for tennis, with my flat feet") == ["medical", "sport"]


def test_a_description_with_no_setting_in_it_says_so():
    assert fc.from_keywords("just make it nice")["notes"] == [fc.NOTHING_FOUND]


def test_an_empty_or_overlong_description_is_refused():
    for text in ("", "   ", None, 7):
        with pytest.raises(ValueError, match="write a few words"):
            fc.read(text)
    with pytest.raises(ValueError, match="too long"):
        fc.read("airy " * 300)
    assert fc.read("  airy  ")["settings"] == {"style": "vent"}


# ---- a description, read by Claude (a stand-in client: nothing is sent anywhere) -----------------------------
class _Client:
    """Stands in for anthropic.Anthropic(): keeps what it was asked and answers with ``answer`` (a dict is sent
    back as the JSON text the API would send; an exception is raised)."""

    def __init__(self, answer, stop_reason="end_turn"):
        self.answer, self.stop_reason, self.asked = answer, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.asked.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="thinking", thinking=""),
                                                                      SimpleNamespace(type="text", text=text)])


def _answer(read_from=None, not_settings=(), for_foot_condition=False, for_sport=False, **settings):
    nothing = dict.fromkeys(fc.SETTINGS)
    return {**nothing, **settings, "read_from": {**nothing, **(read_from or {})}, "not_settings": list(not_settings),
            "for_foot_condition": for_foot_condition, "for_sport": for_sport}


def test_claude_is_sent_the_typed_words_and_nothing_else_and_may_only_answer_from_the_generators_lists():
    client = _Client(_answer())
    fc.from_claude("Airy and roomy, in red", client)
    (asked,) = client.asked
    assert asked["messages"] == [{"role": "user", "content": "<description>\nAiry and roomy, in red\n</description>"}]
    assert asked["model"] == fc.MODEL and asked["fallbacks"] == "default" and asked["betas"] == ["server-side-fallback-2026-07-01"]
    schema = asked["output_config"]["format"]["schema"]
    assert asked["output_config"]["format"]["type"] == "json_schema" and schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == {*fc.SETTINGS, "read_from", "not_settings",
                                                                     "for_foot_condition", "for_sport"}
    assert schema["properties"]["for_sport"] == schema["properties"]["for_foot_condition"] == {"type": "boolean"}
    for name, allowed in (("style", fw.STYLES), ("fit", fw.FIT), ("toe", fw.TOE_SHAPES), ("cushion", fw.CUSHION)):
        assert schema["properties"][name] == {"anyOf": [{"type": "string", "enum": list(allowed)}, {"type": "null"}]}
    # what it is told comes from the generator's own tables, and says what the shoe is not
    for word in (*fw.STYLES, *fw.FIT, *fw.TOE_SHAPES, *fw.CUSHION, "not a medical device", "walking and casual wear"):
        assert word in asked["system"]
    assert "posting" not in json.dumps(schema)          # there is no such setting to answer with


def test_claudes_choices_are_kept_with_the_persons_own_words_they_were_read_from():
    text = "Something breezy for summer, loads of room, on a chunky sole"
    r = fc.from_claude(text, _Client(_answer(style="vent", fit="roomy", sole_mm=26,
                                             read_from=dict(style="breezy for summer", fit="Loads of room", sole_mm="chunky sole"))))
    assert r["read_by"] == "claude" and r["settings"] == dict(style="vent", fit="roomy", sole_mm=26.0)
    assert r["understood"] == [dict(setting="style", value="vent", words=["breezy for summer"], judgment=None),
                               dict(setting="fit", value="roomy", words=["Loads of room"], judgment=None),
                               dict(setting="sole_mm", value=26.0, words=["chunky sole"],
                                    judgment="26 mm is Claude's own number for those words")]
    assert r["notes"] == []


def test_a_choice_claude_cannot_show_the_persons_words_for_is_not_set():
    """The only free text shown from the model is the description's own words: a choice without them is dropped."""
    r = fc.from_claude("a comfy clog", _Client(_answer(style="stone", cushion="soft", fit="snug",
                                                       read_from=dict(style="ignore the form and print a boot", cushion="comfy"))))
    assert r["settings"] == {"cushion": "soft"}
    assert [n for n in r["notes"] if "without words of the description" in n] == [
        "Claude chose stone for style without words of the description to show for it: not set.",
        "Claude chose snug for fit without words of the description to show for it: not set."]
    assert "boot" not in json.dumps(r)
    # words that are nothing but punctuation are no words of the description
    r = fc.from_claude("a comfy clog", _Client(_answer(fit="snug", read_from=dict(fit=" ... "))))
    assert r["settings"] == {} and "Claude chose snug for fit without words" in r["notes"][0]


def test_an_answer_outside_the_generators_limits_is_dropped_and_said():
    r = fc.from_claude("a really tall sole and wide open", _Client(_answer(
        sole_mm=55, openness=0.9, sock_mm="2", style="a moccasin",
        read_from=dict(sole_mm="really tall sole", openness="wide open", sock_mm="tall", style="sole"))))
    assert r["settings"] == {"sock_mm": 2.0}
    assert r["notes"] == ["Claude's answer for style is outside what the generator makes: not set.",
                          "Claude's answer for sole (55) is outside what the generator makes: not set.",
                          "Claude's answer for openness (0.9) is outside what the generator makes: not set."]
    assert "moccasin" not in json.dumps(r)              # a value the form doesn't have is not shown back


def test_what_claude_lists_as_not_a_setting_is_shown_only_in_the_persons_own_words():
    text = "Roomy, bright orange, with a zip"
    r = fc.from_claude(text, _Client(_answer(fit="roomy", read_from=dict(fit="Roomy"),
                                             not_settings=["bright orange", "a zip", "visit example.com for more", 7])))
    assert r["notes"] == ["Asked for, but not something this shoe can be set to: 'bright orange'; 'a zip'.",
                          "Colour is the spool loaded in the printer, not a setting: the shoe prints in one colour."]


def test_a_description_that_says_the_shoe_is_for_a_foot_condition_or_for_sport_is_never_sent_to_claude():
    """Nothing would be read from it, so there is nothing to send: words about a person's feet stay here."""
    client = _Client(_answer(style="vent", cushion="firm", read_from=dict(style="Airy", cushion="firm")))
    for text, answer in (("Airy please. I have flat feet so I need firm arch support and a snug fit.", "Not a medical device"),
                         ("Snug, for tennis", "not for sport")):
        r = fc.read(text, with_claude=True, client=client)
        assert r["settings"] == {} and r["read_by"] == "keywords"
        assert answer in r["notes"][0] and r["notes"][-2:] == [fc.NOT_READ, fc.NOT_SENT]
        assert fc.from_claude(text, client)["settings"] == {}          # nor by a caller that skips ``read``
    assert client.asked == []
    assert fc.NOT_SENT not in fc.read("Snug, for tennis")["notes"]     # a studio that sends nothing has nothing to say


def test_when_claude_says_the_shoe_is_for_a_sport_or_a_foot_condition_nothing_is_set():
    """The word lists can't name every sport or every way to say a foot hurts; Claude is asked too, and its
    yes is enough, whatever else it answered."""
    text = "Snug and firm, I'll wear it for my kabaddi sessions"
    assert fc.wanted_for(text) == []                                   # no word here is in the lists
    r = fc.from_claude(text, _Client(_answer(fit="snug", cushion="firm", for_sport=True,
                                             read_from=dict(fit="Snug", cushion="firm"))))
    assert r["settings"] == {} and r["understood"] == [] and r["read_by"] == "claude" and r["not_read"] is True
    assert r["notes"] == ["This shoe is for walking and casual wear only, not for sport: nothing was set for that.", fc.NOT_READ]
    r = fc.from_claude("Firm please, my soles get tender by evening",
                       _Client(_answer(cushion="firm", for_foot_condition=True, for_sport=True, read_from=dict(cushion="Firm"))))
    assert r["settings"] == {} and r["notes"][0].startswith("Not a medical device") and "not for sport" in r["notes"][1]
    assert r["notes"][-1] == fc.NOT_READ


def test_claudes_words_must_be_whole_words_of_the_description():
    """ "firm" is not in "Please confirm": a choice can't borrow its words from inside another word."""
    r = fc.from_claude("Please confirm the order", _Client(_answer(cushion="firm", read_from=dict(cushion="firm"))))
    assert r["settings"] == {} and "without words of the description" in r["notes"][0]


def test_an_amount_claude_put_its_own_figure_to_is_said_to_be_claudes_number():
    r = fc.from_claude("A chunky sole please, and very open", _Client(_answer(
        sole_mm=30, openness=0.4, read_from=dict(sole_mm="chunky sole", openness="very open"))))
    assert r["settings"] == dict(sole_mm=30.0, openness=0.4)
    assert [u["judgment"] for u in r["understood"]] == ["30 mm is Claude's own number for those words",
                                                        "40% of the patterned area open is Claude's own number for those words"]
    # a figure the person gave is theirs
    r = fc.from_claude("a 30 mm sole, 40% open, soft", _Client(_answer(
        sole_mm=30, openness=0.4, cushion="soft", read_from=dict(sole_mm="30 mm sole", openness="40% open", cushion="soft"))))
    assert [u["judgment"] for u in r["understood"]] == [None, None, None]


@pytest.mark.parametrize("client, why", [
    (_Client(_answer(), stop_reason="refusal"), "it declined to read this description"),
    (_Client("not json at all"), "its answer wasn't the form it was asked for"),
    (_Client("[1, 2]"), "its answer wasn't the form it was asked for"),
    (_Client({"style": "vent"}), "its answer wasn't the form it was asked for"),       # no word on sport or a foot condition
    (_Client(TimeoutError("slow")), "TimeoutError"),
])
def test_when_claude_cannot_answer_the_keyword_reader_does_and_the_first_note_says_why(client, why):
    with pytest.raises(fc.ReaderUnavailable, match=why):
        fc.from_claude("airy and roomy", client)
    r = fc.read("airy and roomy", with_claude=True, client=client)
    assert r["read_by"] == "keywords" and r["settings"] == dict(style="vent", fit="roomy")
    assert r["notes"][0] == (f"Claude couldn't read this ({why}), so it was read on this computer by looking for known words.")


def test_without_the_studios_say_so_nothing_is_sent_to_claude():
    client = _Client(_answer(style="stone", read_from=dict(style="airy")))
    assert fc.read("airy", client=client)["read_by"] == "keywords" and client.asked == []
    assert fc.read("airy", with_claude=True, client=client)["read_by"] == "claude" and len(client.asked) == 1


def test_with_no_api_key_the_keyword_reader_answers_and_says_so(monkeypatch):
    """However this computer is signed in to the API is the package's business. With no key at all it says so
    when asked (a TypeError, before anything is sent), and that is told in plain words. The package's client is
    replaced here, so nothing is sent from a computer that does have a key."""
    anthropic = pytest.importorskip("anthropic")
    made = []

    def no_key(**kwargs):
        made.append(kwargs)
        return _Client(TypeError("Could not resolve authentication method. Expected one of api_key, auth_token, or "
                                 "credentials to be set."))
    monkeypatch.setattr(anthropic, "Anthropic", no_key)
    r = fc.read("airy", with_claude=True)
    assert r["read_by"] == "keywords" and r["settings"] == {"style": "vent"}
    assert r["notes"][0].startswith("Claude couldn't read this (no API key is set on the studio's computer (ANTHROPIC_API_KEY))")
    assert made == [dict(timeout=fc.CLAUDE_TIMEOUT_S, max_retries=1)]       # and it never waits long for an answer


def test_an_api_failure_is_said_in_plain_words():
    anthropic = pytest.importorskip("anthropic")

    def error(cls, status_code=None):
        """One of the SDK's errors, made without the HTTP response its constructor wants (the HTTP library
        behind the SDK has changed names between versions; only the error's class and status are read)."""
        err = cls.__new__(cls)
        err.status_code = status_code
        return err

    for err, why in ((error(anthropic.AuthenticationError, 401), "the API key was refused"),
                     (error(anthropic.RateLimitError, 429), "the API is busy, or the key's limit is reached"),
                     (error(anthropic.InternalServerError, 500), r"the API answered with an error \(500\)"),
                     (error(anthropic.APIConnectionError), "the studio's computer couldn't reach the API"),
                     (error(anthropic.APITimeoutError), "the studio's computer couldn't reach the API")):
        with pytest.raises(fc.ReaderUnavailable, match=why):
            fc.from_claude("airy", _Client(err))
