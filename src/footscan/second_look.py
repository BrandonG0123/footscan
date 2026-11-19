"""Claude's look at a sole scan as it arrives: pictures of the model and the studio's own measures, then keep it
or scan again.

Why: the scans have to be consistent before anything else can be (Brandon, 2026-11-19), and the studio's own
checks (recon/completeness.py) only catch what someone thought to measure: an end cut square, a torn edge, a
rolled forefoot. Object Capture usually closes a gap with a smooth guessed surface instead, which no measurement
here sees; a person looking at pictures of the model might. So once a sole scan has passed those checks, and only
where the studio was started with ``footscan serve --check-scans-with-claude``, it is drawn from six sides and
the pictures, with the measures, go to Claude, who answers keep or scan again.

What it can do, and what it can't:

- It can only refuse a scan, the same way the studio's own checks refuse one (server.IncompleteScan): the phone
  shows *Scan again* with the steps for each problem. It never changes the shape, gives no number and makes no
  insole: Make insole still makes the insole, with the generator, from the scan as it is.
- Its answer is held to fixed lists (``LOOKS_FOR``): a verdict from two, each problem from this file's list,
  and each problem's steps are the studio's own (completeness.RETAKE_STEPS). The only words of its own shown to
  the person are one short sentence per problem on what it saw in the pictures (``seen``, cut to
  ``MAX_SEEN`` characters).
- It is told to judge the scan, never the foot (its shape, arch or health): not a medical device
  (docs/SAFETY.md).
- If Claude can't be reached, declines, or answers in another form, the scan is kept, and why is saved with it:
  this studio's own trouble never blocks a scan.

What is sent to Anthropic's API: the eight pictures (grey renderings of the 3-D model, no photographs) and the
measures. Not the capture's name, the person's name, the phone, or the model file.

NOT TRIED ON A REAL SCAN YET (2026-11-19): no API key has been used with it. ``scripts/second_look_eval.py``
asks the same question of a real scan with known damage cut into it; run that, and send scans known good and
bad, before trusting a refusal from it.
"""

from __future__ import annotations

import base64
import json
import re

import numpy as np

MODEL = "claude-opus-5-5"
# The phone waits for the answer (its upload allows 180 s of silence): one try, then the scan is kept.
TIMEOUT_S = 90.0
MAX_SEEN = 240            # characters of Claude's own words shown per problem
MM_PER_PX_MOST = 0.5      # the pictures are drawn at 0.5 mm a pixel, or coarser for a big model...
PICTURE_PX = 640          # ...so that none is wider or taller than about this

# What Claude may answer is wrong with a scan: (code, the refusal's headline, what it means, for Claude). The
# headlines are completeness.RETAKE_STEPS', so each refusal gets that entry's title and steps on the phone.
LOOKS_FOR = (
    ("toes_missing", "THE TOES ARE MISSING",
     "the toes are cut off, or the front ends blunt or square where toes should round off"),
    ("toes_curled", "THE FRONT OF THE FOOT RISES",
     "the toes are curled up or pulled back, standing well off the line of the sole"),
    ("heel_cut_off", "THE HEEL IS CUT OFF", "the back of the heel is cut off flat"),
    ("heel_missing", "THE HEEL IS MISSING", "the underside of the heel is missing, flattened or looks made up"),
    ("forefoot_rolled", "THE FOREFOOT WAS ROLLED ONTO ONE EDGE",
     "the ball of the foot is clearly tilted onto one edge: one side well below the other"),
    ("torn", "PART OF THE FOOT IS MISSING", "a hole, a tear, or a side of the foot missing"),
    ("not_one_foot", "THIS ISN'T ONE WHOLE FOOT",
     "more than one foot, or the foot merged with the bed, a hand, a sock fold or another object"),
    ("guessed_surface", "PARTS OF THE SOLE LOOK GUESSED",
     "large parts of the sole are smooth blobs, bulges, lumps or doubled surfaces with none of a foot's shape: "
     "the scanner never saw them and made them up"),
    ("not_a_sole", "THIS DOESN'T LOOK LIKE A SOLE SCAN",
     "it is not the sole of a foot at all (a shoe, an object, the floor, a leg without a foot)"),
)
CODES = tuple(c for c, _, _ in LOOKS_FOR)
HEADLINE = {c: h for c, h, _ in LOOKS_FOR}


class Unavailable(RuntimeError):
    """No usable answer from Claude: no key, no network, declined, or not the form it was asked for."""


# ---------------------------------------------------------------------------
# pictures
# ---------------------------------------------------------------------------
X, Y, Z = np.eye(3)
# The prepared foot (foot_prep: mm, the floor at z = 0, toes toward +y): (what the picture is, toward the
# camera, the picture's width). Toes are up the page from below and above, to the right or left from the sides.
PREPARED_VIEWS = (
    ("the sole, from below (toes at the top)", -Z, -X),
    ("from above (toes at the top)", Z, X),
    ("from one side (toes to the right)", X, Y),
    ("from the other side (toes to the left)", -X, -Y),
    ("from behind the heel", -Y, X),
    ("from in front of the toes", Y, -X),
)


def _draw(mesh, views) -> list[tuple[str, np.ndarray]]:
    """Each view of ``mesh`` (pictures.shaded_view), at one scale for all, fine enough for the detail and
    coarse enough that the biggest is about ``PICTURE_PX`` across."""
    from .pictures import shaded_view, surface_points

    mm_per_px = max(MM_PER_PX_MOST, float(np.max(mesh.extents)) / PICTURE_PX)
    # about 4 points to a pixel's area, so that nearly every pixel of the near surface gets one
    P, N = surface_points(mesh, per_mm2=4.0 / mm_per_px ** 2, least=20_000, most=2_000_000)
    return [(name, shaded_view(P, N, toward, right, mm_per_px)) for name, toward, right in views]


def pictures(placed, scanned) -> list[tuple[str, np.ndarray]]:
    """What Claude is shown: the prepared foot (``placed``, what the insole is made from) from six sides, and
    the model as it arrived (``scanned``: mm, Y up, as Object Capture made it), from above and from the side,
    so that whatever the preparation cut away (the leg, the other foot, the bed) can be seen too."""
    out = _draw(placed, PREPARED_VIEWS)
    V = np.asarray(scanned.vertices)
    zup = scanned.copy()
    zup.vertices = np.c_[V[:, 0], -V[:, 2], V[:, 1]]        # Y up -> Z up, the same way round
    level = np.array([1.0, -1.0, 0.0]) / np.sqrt(2)
    out += [(f"the whole model as it arrived, before the studio prepared it, {name}", img) for name, img in _draw(
        zup, (("from above", Z, X), ("from the side", level, np.cross(Z, level))))]
    return out


# ---------------------------------------------------------------------------
# the question
# ---------------------------------------------------------------------------
def schema() -> dict:
    """The one answer Claude may give: keep or scan_again, each problem from ``CODES`` with a sentence on what
    was seen, and what the pictures show, in a sentence or two (saved with the scan, for the studio's owner)."""
    problem = {"type": "object", "additionalProperties": False, "required": ["code", "seen"],
               "properties": {"code": {"type": "string", "enum": list(CODES)}, "seen": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["verdict", "problems", "looked_at"],
            "properties": {"verdict": {"type": "string", "enum": ["keep", "scan_again"]},
                           "problems": {"type": "array", "items": problem},
                           "looked_at": {"type": "string"}}}


def prompt(kind: str) -> str:
    """What Claude is told: what the pictures are, what the studio has already checked, and how to answer."""
    from .recon import completeness, foot_prep

    how = {"sole_up": "lying face down with the knee bent and the sole to the ceiling",
           "sole_hanging": "sitting with the legs out flat and the heel resting on the bed"}.get(kind, "")
    problems = "\n".join(f"- {code}: {what}" for code, _, what in LOOKS_FOR)
    return f"""You are checking one 3D scan of the sole of a person's foot, made with an iPhone (Apple Object Capture), \
before a program makes a 3D-printed insole from it. The person scanned it {how}. An insole made from a bad scan is \
the wrong shape, so a bad scan should be scanned again now, while the person is still there. Your answer decides \
only that: keep this scan, or ask for it to be scanned again. You never change the shape, and the program makes \
the insole from the scan as it is.

The pictures are grey renderings of the 3D model, drawn from far off with no perspective, all at the same scale \
within each set. The first six show the model after the program prepared it: turned so the sole faces down onto a \
flat floor, the leg cut off on purpose about {foot_prep.LEG_TRIM_MM:.0f} mm above the floor (the cut is closed flat), \
and anything that isn't this foot taken away. The last two show the model as it arrived, before any of that.

The program has already measured this scan, and it passed every check it has. The measures are in the JSON \
below: length_mm and width_mm of the outline seen from above (a foot is \
{foot_prep.FOOT_LENGTH_MM[0]:.0f}-{foot_prep.FOOT_LENGTH_MM[1]:.0f} mm long); toe_end and heel_end, how square each end \
is (over {completeness.TOE_END_SQUARE} at the toes or {completeness.HEEL_END_SQUARE} at the heel is refused); \
how high each side of the ball of the foot sits; open edges near the floor. Those checks cannot see a part the \
scanner never saw and made up as a smooth, rounded surface, which is what it usually does. That is what you are \
looking for, along with anything else plainly wrong with the scan.

Problems you may name (use these codes only):
{problems}

How to answer:
- Judge only the scan: whether it captured the whole sole, toes and heel included, as a real foot looks. Don't \
comment on the foot's shape, its arch, its health or any condition, and don't estimate sizes. A foot's arch \
leaving the floor, toes that hang up a little, a sock's texture and a rough or bumpy surface are normal.
- Answer scan_again only for a problem you can point to in the pictures, and one that would make the insole the \
wrong shape. For each, give its code and, in seen, one short plain sentence saying where in which picture, for \
the person who scanned. If the scan looks usable, answer keep with no problems. When you are unsure, keep: the \
program's own checks have passed, and asking for a needless rescan costs the person time.
- In looked_at, say in one or two sentences what the pictures show, for the studio's owner."""


def _image(rgb: np.ndarray) -> dict:
    from .pictures import png_bytes

    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(png_bytes(rgb)).decode()}}


def content(views: list[tuple[str, np.ndarray]], measures: dict, info: dict) -> list[dict]:
    """The message: each picture after a line saying what it is, then the measures and the preparation's notes
    (its own words and numbers; the to_mat matrix left out), as JSON."""
    out = []
    for i, (name, rgb) in enumerate(views, 1):
        out += [{"type": "text", "text": f"Picture {i}: {name}."}, _image(rgb)]
    notes = {k: v for k, v in info.items() if k != "to_mat"}
    out.append({"type": "text", "text": "The program's measures of this scan:\n" + json.dumps(
        dict(measures=measures, preparation=notes), indent=1, default=str)})
    return out


def _client():
    try:
        import anthropic
    except ImportError:
        raise Unavailable("the anthropic package isn't installed on the studio's computer") from None
    return anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=0)


def _said(text) -> str:
    """Claude's sentence on what it saw, as shown to the person: one line, at most ``MAX_SEEN`` characters
    (cut at a word), ending in a full stop."""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if len(s) > MAX_SEEN:
        s = s[:MAX_SEEN].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return s if not s or s[-1] in ".!?…" else s + "."


def ask(views, measures: dict, info: dict, kind: str, client=None) -> dict:
    """Claude's answer: {"verdict": "keep"|"scan_again", "problems": [{"code", "seen"}], "looked_at"}, held to
    ``schema`` (a problem with a code not on the list is dropped; scan_again with none left is no answer).
    Raises ``Unavailable`` where there's no usable answer."""
    from .footwear_choices import _why

    client = client or _client()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            system=prompt(kind),
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema()}},
            messages=[{"role": "user", "content": content(views, measures, info)}],
        )
    except Unavailable:
        raise
    except Exception as err:  # noqa: BLE001 - whatever went wrong on the way, the scan is kept
        raise Unavailable(_why(err)) from None
    if response.stop_reason == "refusal":
        raise Unavailable("it declined to look at this scan")
    try:
        answer = json.loads(next(b.text for b in response.content if b.type == "text"))
    except (StopIteration, json.JSONDecodeError):
        raise Unavailable("its answer wasn't the form it was asked for") from None
    if not isinstance(answer, dict) or answer.get("verdict") not in ("keep", "scan_again"):
        raise Unavailable("its answer wasn't the form it was asked for")
    found, codes = [], set()
    for p in answer.get("problems") if isinstance(answer.get("problems"), list) else []:
        if isinstance(p, dict) and p.get("code") in HEADLINE and p["code"] not in codes:
            codes.add(p["code"])
            found.append(dict(code=p["code"], seen=_said(p.get("seen", ""))))
    if answer["verdict"] == "scan_again" and not found:
        raise Unavailable("it asked for the scan again without naming a problem it may name")
    return dict(verdict=answer["verdict"], problems=found if answer["verdict"] == "scan_again" else [],
                looked_at=_said(answer.get("looked_at", "")), model=MODEL)


def look(placed, scanned, measures: dict, info: dict, kind: str, client=None) -> dict:
    """Claude's look at one sole scan that passed the studio's own checks: ``ask``'s answer, or {"error": why}
    (the scan is then kept). ``placed``: the prepared foot; ``scanned``: the model as it arrived, in mm."""
    try:
        return ask(pictures(placed, scanned), measures, info, kind, client=client)
    except Unavailable as e:
        return dict(error=f"Claude couldn't look at this scan: {e}. It was kept.")
    except Exception as e:  # noqa: BLE001 - the pictures couldn't be drawn: our own trouble never blocks a scan
        return dict(error=f"the pictures for Claude couldn't be drawn ({type(e).__name__}: {e}). It was kept.")


def refusals(answer: dict) -> list[str]:
    """Claude's scan_again as the studio's refusal lines: each starts with its problem's headline (so the phone
    gets completeness.RETAKE_STEPS' title and steps for it), then what Claude saw. Nothing for keep or an error."""
    if answer.get("verdict") != "scan_again":
        return []
    what = {c: w for c, _, w in LOOKS_FOR}
    return [f"{HEADLINE[p['code']]}: Claude looked at pictures of the scan and saw this: "
            f"{p['seen'] or _said(what[p['code']].capitalize())} Scan again, following the steps."
            for p in answer["problems"]]
