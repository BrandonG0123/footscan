"""What a clog's print-trial pieces showed, and what that says about the shoe's choices.

The trial pieces (``footwear.trial_pieces``) are small parts of one shoe, printed before a whole one, and
their sheet asks the same things of every shoe's pieces. This file holds those questions with fixed answers
(``QUESTIONS``), checks what a person answered against them (``checked``), and turns the answers into
suggested changes to the wearer's choices (``suggest``): the form's settings in ``footwear_choices``, nothing
else. No shape is made here.

It suggests and changes nothing. The studio shows each suggestion beside the answers it came from, and the
person moves it into the form or doesn't.

A record is about one shoe: the one its pieces were cut from, which the person names when recording (the
studio keeps the shoes whose pieces it cut, ``shoe_of``), because pieces take hours to print and the shoe may
have been made again meanwhile. Pieces are recorded one at a time as they are printed, so a shoe's suggestion
is made from everything recorded about it together (``merged``), never from one record alone.

Two settings are ever suggested, each by a rule that needs no number of this file's own:

- cushion: the sole block the person picked is the cushioning (``footwear.CUSHION``).
- fit: one step along the generator's own three fits (``footwear.FIT``): roomier where the toe cap or the
  back half pressed on the foot, snugger where the back half's walls stood off it. Answers that point both
  ways change nothing and say so, because a fit moves the room across the ball, over the toes and past them
  together. For the same reason toes that touched the end hold a snugger fit back, though they ask for no
  roomier one (a toe cap can't measure length).

Everything else is kept and answered in this file's fixed words, because it is not a choice to make here:

- The footbed. The heel cup and the rise under the arch are the first-fit insole's surface, from the sole
  scan. Nothing here raises, lowers or tilts it to how it felt: that would be correcting a foot by feel
  (docs/SAFETY.md: no posting or correction in a first fit).
- Anything that hurt. The answer is the stop rule (docs/SAFETY.md, requirement 2), and from then on NOTHING
  is suggested for any shoe of that capture, the cushioning included: a shoe is not adjusted round a pain by
  this program, and its fixed rules can't know what a later, painless piece has to do with an earlier pain.
  Not for the record that said so alone, nor for that shoe alone: a later record about another piece, or the
  shoe made again, would bring the suggestions back. Nothing here lifts it (the rule is "until reviewed", and
  this program can't know of a review). The answers are kept, and the form is still the person's to change.
  Don't narrow that.
- How a piece printed (a top that didn't close, strands across a window, a roof that sagged). Those are slicer
  settings. Only broken bars point at a setting, the pattern's openness, and no number is suggested for it.
- Room past the toes. A toe cap has no heel to stand the foot against, so it can't measure length.

All of it is a JUDGMENT made before any piece was printed: which answers move the fit, and that they move it
one step. docs/footwear.md says so.
"""

from __future__ import annotations

from . import footwear as fw

MAX_NOTE = 500      # characters of the person's own note: kept and shown, never read into anything
KEPT = 20           # records kept with a capture, the newest last (the older ones are dropped)
SHOES_KEPT = 10     # shoes whose trial pieces were cut, kept with a capture so a record can say which it is about

YES_NO = (dict(key="yes", label="Yes"), dict(key="no", label="No"))


def _and(parts) -> str:
    parts = list(parts)
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


FOOTBED_NOTE = ("is part of the footbed, which is the first-fit insole's surface made from the sole scan. No choice on "
                "the form changes it, and it is not reshaped to how it felt (no posting or correction: docs/SAFETY.md). "
                "It is kept here for the fit log.")
SLICER_NOTE = ("is how the piece printed, a slicer setting and not the shoe's shape. The print notes' settings are "
               "untested starting points; nothing about the shoe is suggested for it.")

# The trial sheet's questions (footwear._TRIALS says what to look at), in the order the pieces are printed.
# An answer may carry: ``fit`` (+1 a roomier fit, -1 a snugger one) with ``says``, the words the suggestion gives
# as its reason; ``holds``, the words for why it stands against a snugger fit without asking for a roomier one;
# ``note``, the fixed answer for something that is not a choice.
QUESTIONS = (
    dict(key="cushion", piece="sole-block", ask="Which of the three sole blocks should the sole be?",
         answers=(*(dict(key=k, label=f"The {k} one ({v}% infill)") for k, v in fw.CUSHION.items()),
                  dict(key="none", label="None of them",
                       note=f"None of the three sole blocks was right. {_and(fw.CUSHION).capitalize()} are the only "
                            "cushionings there are to choose, so none is suggested: say what was wrong in the note."))),
    dict(key="sole_top", piece="sole-block", ask="Is the block's top closed and smooth?",
         answers=(YES_NO[0], dict(YES_NO[1], note=f"A top that isn't closed and smooth {SLICER_NOTE}"))),
    dict(key="tread", piece="sole-block", ask="Did the tread underneath print cleanly?",
         answers=(YES_NO[0], dict(YES_NO[1], note="Tread that didn't print cleanly is kept here. The form has no "
                                                  "setting for the tread, so nothing is suggested for it."))),
    dict(key="windows", piece="swatch", ask="Are the windows' edges clean and the bars between them whole?",
         answers=(dict(key="clean", label="Clean edges, whole bars"),
                  dict(key="strands", label="Strands droop across the windows",
                       note=f"Strands across the windows: that {SLICER_NOTE}"),
                  dict(key="bars", label="Bars are broken or missing",
                       note="Bars that broke or are missing: a less open pattern leaves wider bars (Pattern open, % on "
                            "the form), and Stone has no windows at all. No number is suggested, because none has "
                            "been tried."))),
    dict(key="swatch_roof", piece="swatch",
         ask="Did the roof print without sagging, and did the supports come out without tearing it?",
         answers=(YES_NO[0], dict(YES_NO[1], note=f"A roof that sagged or tore with its supports {SLICER_NOTE}"))),
    dict(key="toe_supports", piece="toe-cap", ask="Did the supports under the roof come out, leaving the inside smooth?",
         answers=(YES_NO[0], dict(YES_NO[1], note="Supports that didn't come out cleanly from under the toe cap's "
                                                  f"roof: that {SLICER_NOTE}"))),
    dict(key="toe_over", piece="toe-cap", ask="Seated, sock on, the front of the foot slid in: is there room over the toes?",
         answers=(dict(key="room", label="Yes"),
                  dict(key="presses", label="No: the roof presses on them", fit=+1,
                       says="the toe cap's roof pressed on the toes"))),
    dict(key="toe_sides", piece="toe-cap", ask="Does the toe cap press on the sides of the toes?",
         answers=(dict(key="no", label="No"),
                  dict(key="yes", label="Yes", fit=+1, says="the toe cap pressed on the sides of the toes"))),
    dict(key="toe_past", piece="toe-cap", ask="Do the toes touch the end?",
         answers=(dict(key="no", label="No"),
                  dict(key="touch", label="Yes", holds="the toes touched the end of the toe cap",
                       note="Toes touching the end of the toe cap is not a measure of the shoe's length: the piece has "
                            "no heel to stand the foot against. Check the ruler's length (heel to the longest toe, "
                            "standing) before a whole shoe is made."))),
    dict(key="heel_cup", piece="back-half", ask="Seated, sock on, the heel set down: does it sit down into the cup?",
         answers=(dict(key="sits", label="Yes"),
                  dict(key="edge", label="No: it rests on the cup's edge", note=f"The heel cup {FOOTBED_NOTE}"))),
    dict(key="arch", piece="back-half", ask="What does the raised part under the arch feel like?",
         answers=(dict(key="support", label="Like support"),
                  dict(key="ridge", label="Like a ridge", note=f"The rise under the arch {FOOTBED_NOTE}"),
                  dict(key="nothing", label="I can't feel it", note=f"The rise under the arch {FOOTBED_NOTE}"))),
    dict(key="walls", piece="back-half", ask="What do the walls do?",
         answers=(dict(key="touch", label="Touch the foot lightly"),
                  dict(key="press", label="Press on it", fit=+1, says="the back half's walls pressed on the foot"),
                  dict(key="stand_off", label="Stand off it", fit=-1, says="the back half's walls stood off the foot"))),
    dict(key="rim", piece="back-half", ask="How is the rim behind the heel?",
         answers=(dict(key="right", label="About right"),
                  dict(key="high", label="Too high", note="The rim behind the heel was too high. Its height is not a "
                                                           "choice on the form yet, so nothing is suggested for it."),
                  dict(key="low", label="Too low", note="The rim behind the heel was too low. Its height is not a "
                                                         "choice on the form yet, so nothing is suggested for it."))),
    dict(key="hurt", piece=None, ask="Did anything hurt, rub, or leave a mark on the skin?", answers=(YES_NO[1], YES_NO[0])),
)

# docs/SAFETY.md, requirement 2 (the stop rule), said for a trial piece. A safety requirement: not softened.
STOP = ("Something hurt, rubbed or left a mark. Stop trying these pieces, and do not go on until it has been "
        "reviewed. The stop rule for everything made by this project (docs/SAFETY.md): stop on any new pain, on "
        "numbness, tingling or burning, on an existing pain that gets worse, and on a mark on the skin that has not "
        "gone by the next day. This is not a medical device.")
NOTHING_FOR_HURT = ("Nothing is suggested for this foot's shoes once a piece has hurt, the cushioning included: this "
                    "program does not adjust a shoe round a pain. Every answer is kept, and the choices are still "
                    "yours to change in the form.")
BOTH_WAYS = ("The answers point both ways for the fit ({roomier}; but {snugger}). A fit moves the room across the "
             "ball, over the toes and past them together, so no fit is suggested: check the ruler's length and width.")
SNUGGER_HELD = ("A snugger fit is not suggested ({snugger}; but {held}): a snugger fit also takes room from over the "
                "toes and past them. Check the ruler's length and width, standing.")
NO_FURTHER = ("{fit} is already the {end} of the three fits, so there is none further to suggest ({why}). Check the "
              "ruler's length and width, standing{sock}.")
NOTHING = "Nothing in these answers changes a choice."

_BY_KEY = {q["key"]: q for q in QUESTIONS}
FITS = sorted(fw.FIT, key=lambda k: fw.FIT[k]["width_mm"])       # snuggest first, by the generator's own table


def pieces_cut(shoe: dict | None) -> list:
    """The trial pieces that were cut from a shoe, from the studio's report of it. None for a shoe made without
    them, or whose pieces couldn't be cut: there is nothing to print from it, so nothing to record about."""
    cut = (shoe or {}).get("trials") or {}
    return [p["piece"] for p in cut.get("pieces") or []]


def shoe_of(shoe: dict) -> dict | None:
    """What is kept of a shoe so that a record can be about it: when it was made, its style, the choices it was
    made to, and the trial pieces cut from it. ``shoe``: the studio's report. None where no piece was cut."""
    pieces = pieces_cut(shoe)
    if not pieces:
        return None
    return dict(made=shoe.get("made"), style=shoe.get("style"), choices=dict(shoe.get("choices") or {}), pieces=pieces)


def questions(pieces=None) -> list:
    """The questions for a shoe's trial pieces, as the page shows them: key, piece, piece's name, the question
    and its answers. ``pieces``: the pieces that were cut from this shoe (Stone has no pattern swatch); None for
    all of them. The question about anything hurting belongs to no piece and is always asked."""
    return [dict(key=q["key"], piece=q["piece"], piece_title=fw._TRIALS[q["piece"]][0] if q["piece"] else None,
                 ask=q["ask"], answers=[dict(key=a["key"], label=a["label"]) for a in q["answers"]])
            for q in QUESTIONS if q["piece"] is None or pieces is None or q["piece"] in pieces]


def checked(findings, pieces=None) -> dict:
    """What a person recorded, checked against the questions: -> dict(answers={question: answer}, note=str).

    ``findings``: {"answers": {question key: answer key}, "note": the person's own words (optional)}. A question
    left out wasn't answered (a piece not printed yet), except whether anything hurt: that is asked of every
    record, so a suggestion is never made without it. Raises ValueError, in words for the person, for a question
    or an answer that isn't one of these, for a question about a piece this shoe has none of (``pieces``), for
    a record that doesn't say whether anything hurt, and for a note over ``MAX_NOTE`` characters.
    """
    if not isinstance(findings, dict):
        raise ValueError("what the trial pieces showed must be a JSON object")
    unknown = sorted(set(findings) - {"answers", "note"})
    if unknown:
        raise ValueError(f"not part of a trial record: {', '.join(unknown)}")
    answers = findings.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("answers must be a JSON object: a question's key and the answer picked")
    if "hurt" not in answers:
        raise ValueError("say whether anything hurt, rubbed or left a mark (hurt: yes or no): every record has that answer")
    out = {}
    for q in QUESTIONS:     # (kept in the questions' own order)
        if q["key"] not in answers:
            continue
        value = answers[q["key"]]
        allowed = [a["key"] for a in q["answers"]]
        if not isinstance(value, str) or value not in allowed:
            raise ValueError(f"{q['key']} must be one of {', '.join(allowed)}")
        if q["piece"] is not None and pieces is not None and q["piece"] not in pieces:
            raise ValueError(f"this shoe has no {fw._TRIALS[q['piece']][0].lower()} among its trial pieces, so there is "
                             f"nothing to answer about one ({q['key']})")
        out[q["key"]] = value
    stray = sorted(set(answers) - set(_BY_KEY))
    if stray:
        raise ValueError(f"not a question about the trial pieces: {', '.join(str(k) for k in stray)}")
    note = findings.get("note")
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise ValueError("the note must be text")
    note = note.strip()
    if len(note) > MAX_NOTE:
        raise ValueError(f"the note is {len(note)} characters; keep it to {MAX_NOTE}")
    return dict(answers=out, note=note)


def _picked(answers: dict) -> list:
    """(question, the answer picked) for each answer of a record, in the record's order. An answer this table no
    longer has (a record kept by an earlier version of it) is passed over: it suggests nothing."""
    out = []
    for key, value in answers.items():
        q = _BY_KEY.get(key)
        a = next((a for a in q["answers"] if a["key"] == value), None) if q else None
        if a:
            out.append((q, a))
    return out


def in_words(answers: dict) -> list:
    """A record's answers as the page shows them: the piece's name, the question and the answer picked."""
    return [dict(piece_title=fw._TRIALS[q["piece"]][0] if q["piece"] else None, ask=q["ask"], answer=a["label"])
            for q, a in _picked(answers)]


def merged(records: list) -> dict:
    """The answers of several records about one shoe as one set, the oldest laid down first, so the newest
    answer to each question stands (a piece printed and tried again). Whether anything hurt is not a newest
    answer: once any of them says so, it stays said."""
    out: dict = {}
    for r in records:
        out.update(r["answers"])
    if any(r["answers"].get("hurt") == "yes" for r in records):
        out["hurt"] = "yes"
    return out


def suggest(answers: dict, choices: dict | None = None, hurt: bool = False) -> dict:
    """What the answers say about the choices the pieces' shoe was made to.

    ``answers``: everything recorded about that one shoe (``merged``). ``choices``: that shoe's, as the studio
    keeps them; a choice left out was the generator's default. ``hurt``: something hurt in a record kept with
    this capture, whichever shoe it was about (``hurt_in``).
    -> dict(changes=[dict(setting, was, to, because=[...])], notes=[...], stop=None or the stop rule's words).
    Nothing is changed by this: each change is for the person to take or leave. Once something hurt there are
    no changes at all (this file's docstring says why).
    """
    choices = choices or {}
    picked = [a for _, a in _picked(answers)]
    notes = [a["note"] for a in picked if "note" in a]
    if hurt or answers.get("hurt") == "yes":
        return dict(changes=[], notes=[NOTHING_FOR_HURT, *notes], stop=STOP)
    defaults = fw.ShoeParams()
    changes = []
    block = answers.get("cushion")
    was = choices.get("cushion") or defaults.cushion
    if block in fw.CUSHION and block != was:
        changes.append(dict(setting="cushion", was=was, to=block, because=[f"the {block} sole block was the one picked"]))
    roomier = [a["says"] for a in picked if a.get("fit") == +1]
    snugger = [a["says"] for a in picked if a.get("fit") == -1]
    held = [a["holds"] for a in picked if "holds" in a]
    fit = choices.get("fit") or defaults.fit
    if roomier and snugger:
        notes.append(BOTH_WAYS.format(roomier=_and(roomier), snugger=_and(snugger)))
    elif snugger and held:
        notes.append(SNUGGER_HELD.format(snugger=_and(snugger), held=_and(held)))
    elif (roomier or snugger) and fit in FITS:      # (a fit the generator no longer has: nothing to step from)
        at = FITS.index(fit) + (1 if roomier else -1)
        why = roomier or snugger
        if 0 <= at < len(FITS):
            changes.append(dict(setting="fit", was=fit, to=FITS[at], because=why))
        else:
            notes.append(NO_FURTHER.format(
                fit=fit.capitalize(), end="roomiest" if roomier else "snuggest", why=_and(why),
                sock="; a thicker sock's allowance (Thicker sock, mm) adds room all round" if roomier else ""))
    if not changes and not notes:
        notes.append(NOTHING)
    return dict(changes=changes, notes=notes, stop=None)


def record(answers: dict, note: str, shoe: dict, when: str) -> dict:
    """One entry of a capture's trial record: the answers, the person's note, and which shoe's pieces they are
    about (``shoe``: that shoe as ``shoe_of`` keeps it: when it was made, to which choices, with which pieces)."""
    about = dict(made=shoe.get("made"), style=shoe.get("style"), choices=dict(shoe.get("choices") or {}),
                 pieces=list(shoe.get("pieces") or []))
    return dict(recorded=when, about=about, answers=dict(answers), note=note)


def hurt_in(records: list) -> dict | None:
    """The first record that says something hurt: dict(recorded, made), or None. The studio keeps this when
    such a record arrives (the records themselves are only the newest ``KEPT``), and never takes it away."""
    for r in records:
        if r["answers"].get("hurt") == "yes":
            return dict(recorded=r["recorded"], made=r["about"].get("made"))
    return None


def shown(records: list, shoes: list, stopped: dict | None = None) -> dict:
    """A capture's whole trial record as the page shows it, shoe by shoe.

    ``records``: the records kept, oldest first. ``shoes``: the shoes whose trial pieces were cut (``shoe_of``),
    oldest first: a record can be added about any of them. ``stopped``: what the studio kept when a record said
    something hurt (``hurt_in``), or None.
    -> dict(shoes=[...], stop=None or dict(recorded, made, words, nothing)). Each shoe, the newest first: made,
    style, choices, pieces, ``recordable`` (its pieces are still known here) with its ``questions``, its
    ``records`` (newest first, each with ``said``: its answers in words), and ``suggestion``: what everything
    recorded about it says for its choices (``suggest``), None where nothing is recorded. A shoe whose records
    outlived the studio's memory of it is shown with them, and can't be added to.
    """
    stopped = stopped or hurt_in(records)
    known = {s["made"]: dict(s, recordable=True) for s in shoes}
    for r in records:
        known.setdefault(r["about"].get("made"), dict(r["about"], recordable=False))
    out = []
    for made, shoe in known.items():
        mine = [r for r in records if r["about"].get("made") == made]
        out.append(dict(
            shoe, questions=questions(shoe.get("pieces") or []) if shoe["recordable"] else [],
            records=[dict(recorded=r["recorded"], note=r["note"], said=in_words(r["answers"])) for r in reversed(mine)],
            suggestion=suggest(merged(mine), shoe.get("choices"), hurt=bool(stopped)) if mine else None))
    out.sort(key=lambda s: str(s.get("made") or ""), reverse=True)
    stop = dict(stopped, words=STOP, nothing=NOTHING_FOR_HURT) if stopped else None
    return dict(shoes=out, stop=stop)
