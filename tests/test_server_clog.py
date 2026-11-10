"""The studio's Make shoe: a clog for a foot capture, made to the choices sent (server.make_clog, the clog API,
the footwear API). Every foot here is ``synth.block_foot`` (SYNTHETIC), imported as the iPhone app would send it.
"""

import datetime as dt
import itertools
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from footscan import footwear as fw
from footscan import footwear_choices, footwear_fit, server
from footscan.server import WEB_DIR, StudioServer, make_handler
from test_server import (KEY, _new_sole_capture, _object_capture_foot, _sole_up_obj, body, call,
                         servers)  # noqa: F401 - servers is a fixture

OBJ = {"Content-Type": "application/octet-stream"}


def _foot_capture(op, foot="right"):
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": foot, "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot(foot), OBJ)[0] == 200
    return cid


def _listed(op, cid):
    return [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == cid][0]


def test_the_studio_makes_a_shoe_to_the_choices_sent_from_an_imported_foot(servers):
    op, phone, data = servers
    cid = _foot_capture(op, "left")
    choices = {"style": "vent", "fit": "roomy", "sole_mm": 20, "length_mm": 250, "width_mm": 95}
    assert call(f"{phone}/api/captures/{cid}/clog", "POST", choices)[0] == 403  # studio only
    st, raw, _ = call(f"{op}/api/captures/{cid}/clog", "POST", choices)
    assert st == 200, raw
    r = json.loads(raw)
    assert "error" not in r, r
    assert r["foot"] == "left" and r["style"] == "vent" and r["trials"] is None
    # what was asked for is what was made, and it is kept so the form opens as it was left
    assert r["choices"] == {"style": "vent", "fit": "roomy", "sole_mm": 20.0, "length_mm": 250.0, "width_mm": 95.0}
    made_for = r["made_for"]
    assert (made_for["foot_length_mm"], made_for["foot_width_mm"], made_for["fit"]) == (250.0, 95.0, "roomy")
    assert made_for["length_from"] == "ruler" and r["sole"]["under_ball_mm"] == 20.0
    # the footbed is this capture's sole (the block foot's 11 mm arch fill), not a flat floor
    assert r["footbed"]["scan_length_mm"] == pytest.approx(240.0, abs=0.6)
    assert r["footbed"]["max_fill_mm"] == pytest.approx(11.0, abs=0.6)
    assert r["untested"] == fw.UNTESTED
    folder = data / "captures" / cid / "clog"
    assert {p.name for p in folder.iterdir()} == set(r["files"])  # nothing written that the studio can't hand out
    for name in ("clog.3mf", "clog.stl", "summary.html", "print-notes.txt", "clog.json", "clog-views.png"):
        st, got, h = call(f"{op}/api/captures/{cid}/clog/{name}")
        assert st == 200 and len(got) > 100, name
        shown = name.endswith((".html", ".png"))
        assert ("attachment" in (h.get("Content-Disposition") or "")) is not shown, name
        assert call(f"{phone}/api/captures/{cid}/clog/{name}")[0] == 403, name
    sheet = call(f"{op}/api/captures/{cid}/clog/summary.html")[1].decode()
    assert "NOT A MEDICAL DEVICE" in sheet and "walking and casual wear only" in sheet.lower()
    for name in ("clog-preview.bin", "clog-preview-open.bin"):  # the studio's 3-D preview, whole and cut open
        st, got, _ = call(f"{op}/api/captures/{cid}/clog/{name}")
        assert st == 200 and got[:4] == b"FSV1", name
    assert call(f"{op}/api/captures/{cid}/clog/../capture.json")[0] == 404
    assert call(f"{op}/api/captures/{cid}/clog/clog-trial-swatch.3mf")[0] == 404  # none were asked for
    listed = _listed(op, cid)
    assert listed["clog"]["length_mm"] == r["length_mm"] and "stale" not in listed["clog"]
    assert "insole" not in listed and not (data / "captures" / cid / "insole").exists()  # a shoe is not an insole


def test_trial_pieces_are_cut_when_asked_for_and_gone_when_the_shoe_is_made_again_without(servers):
    op, _, data = servers
    cid = _foot_capture(op)
    r = body(call(f"{op}/api/captures/{cid}/clog", "POST", {"style": "vent", "trials": True}))
    assert "error" not in r, r
    assert "trials" not in r["choices"]  # how it is made, not a setting of the shoe
    cut = r["trials"]
    assert [p["piece"] for p in cut["pieces"]] == list(server.CLOG_TRIAL_PIECES) and cut["left_out"] == []
    assert all(p["title"] for p in cut["pieces"])
    assert cut["warning"] == fw.TRIAL_WARNING
    folder = data / "captures" / cid / "clog"
    assert {p.name for p in folder.iterdir()} == set(r["files"]) <= set(server.CLOG_FILES)
    for piece in server.CLOG_TRIAL_PIECES:
        assert call(f"{op}/api/captures/{cid}/clog/clog-trial-{piece}.3mf")[0] == 200, piece
    assert fw.TRIAL_WARNING.encode() in call(f"{op}/api/captures/{cid}/clog/clog-trials.txt")[1]

    again = body(call(f"{op}/api/captures/{cid}/clog", "POST", {"style": "vent"}))
    assert again["trials"] is None and not [n for n in again["files"] if "trial" in n]
    assert not [p.name for p in folder.iterdir() if "trial" in p.name]  # an earlier shoe's pieces don't linger
    assert call(f"{op}/api/captures/{cid}/clog/clog-trial-swatch.3mf")[0] == 404


def test_the_studios_list_of_shoe_files_is_the_generators():
    """The server names the files it will hand out; these are the generator's own pieces and pictures."""
    assert server.CLOG_TRIAL_PIECES == tuple(fw._TRIALS)
    assert server.CLOG_VIEWS == ("views", *fw.VIEWS)


@pytest.mark.parametrize("sent, says", [
    ({"style": "boot"}, "style"),
    ({"fit": "tight"}, "fit"),
    ({"sole_mm": 100}, "sole"),
    ({"openness": 0.9}, "0.5"),
    ({"posting_deg": 4}, "not a setting of the shoe"),      # no posting or correction: there is no such setting
    ({"arch_support": "high"}, "not a setting of the shoe"),
    ({"length_mm": "long"}, "length"),
    ({"trials": "yes"}, "trials must be true or false"),
    ([], "expected a JSON object"),
    (b"{style", "expected a JSON object"),
])
def test_what_isnt_a_setting_of_the_shoe_is_refused_and_nothing_is_made(servers, sent, says):
    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    st, raw, _ = call(f"{op}/api/captures/{cid}/clog", "POST", json.dumps(sent).encode() if isinstance(sent, list) else sent)
    assert st == 400 and says in json.loads(raw)["error"], raw
    assert "clog" not in json.loads((data / "captures" / cid / "capture.json").read_text())
    assert not (data / "captures" / cid / "clog").exists()


def test_a_shoe_needs_a_foot_and_a_model(servers):
    op, _, data = servers
    thing = body(call(f"{op}/api/captures", "POST", {"condition": "object", "session": "L1", "method": "imported_mesh"}))["id"]
    st, raw, _ = call(f"{op}/api/captures/{thing}/clog", "POST", {})
    assert st == 400 and "foot capture" in json.loads(raw)["error"]
    # a foot with no 3D model yet: said, and nothing to download
    foot = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                     "load_kg": 30, "method": "imported_mesh"}))["id"]
    assert "no 3D model yet" in body(call(f"{op}/api/captures/{foot}/clog", "POST", {}))["error"]
    assert call(f"{op}/api/captures/{foot}/clog/clog.3mf")[0] == 409
    assert not (data / "captures" / foot / "clog").exists()


def test_choices_the_generator_wont_make_a_shoe_to_leave_the_shoe_already_made_standing(servers):
    """A ruler length too far from the scan's is the generator's refusal, not a failed build: the model hasn't
    changed, so the earlier shoe still matches it. With no earlier shoe the refusal is what the capture shows."""
    op, _, data = servers
    cid = _foot_capture(op)
    too_long = {"length_mm": 300}           # the SYNTHETIC block foot's scan reads 240 mm: more than 15% apart
    r = body(call(f"{op}/api/captures/{cid}/clog", "POST", too_long))
    assert "error" in r and "refused" not in r and "300" in r["error"]
    assert _listed(op, cid)["clog"] == r and call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 409
    assert not (data / "captures" / cid / "clog").exists()

    made = body(call(f"{op}/api/captures/{cid}/clog", "POST", {"style": "stone", "length_mm": 250}))
    assert "error" not in made
    st, raw, _ = call(f"{op}/api/captures/{cid}/clog", "POST", too_long)
    assert st == 400 and json.loads(raw)["error"] == r["error"]
    assert _listed(op, cid)["clog"] == made                      # its report and its choices, untouched
    assert call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 200
    assert json.loads((data / "captures" / cid / "clog" / "clog.json").read_text())["style"] == "stone"


def test_the_shoes_footbed_is_the_insole_the_studio_makes_from_the_same_capture(servers):
    """A SYNTHETIC sole-up phone scan: Make shoe picks and prepares the model the way Make insole does (the
    scan's kind, its up axis), so the footbed in the shoe is that insole's, and both go stale together."""
    op, _, _ = servers
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"), OBJ)[0] == 200
    insole = body(call(f"{op}/api/captures/{cid}/insole", "POST", {}))
    clog = body(call(f"{op}/api/captures/{cid}/clog", "POST", {}))
    assert "error" not in insole and "error" not in clog, (insole, clog)
    assert clog["footbed"]["max_fill_mm"] == insole["max_fill_mm"] > 5.0
    assert (clog["source"], clog["prep"]) == (insole["source"], insole["prep"])
    assert b"sole-up" in call(f"{op}/api/captures/{cid}/clog/summary.html")[1].lower().replace(b" ", b"-")


def test_a_saved_bought_shoe_changes_insoles_and_never_a_printed_shoe(servers):
    """A saved shoe (shoes.py) is a bought shoe whose outline new insoles are cut to. A clog has its own
    outline, so saving one as the default must leave a printed shoe exactly as it was, and not stale."""
    import synth

    op, _, _ = servers
    cid = _foot_capture(op)
    before = body(call(f"{op}/api/captures/{cid}/clog", "POST", {"style": "stone"}))
    bought = body(call(f"{op}/api/captures", "POST", {"condition": "shoe_insole", "session": "LIDAR",
                                                      "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{bought}/mesh?ext=obj&up=y", "PUT", synth.shoe_insole().export(file_type="obj").encode(),
                OBJ)[0] == 200
    assert call(f"{op}/api/shoes", "POST", {"capture": bought, "name": "Test Trainer", "size": "US men's 9.5",
                                            "default": True})[0] == 201
    assert body(call(f"{op}/api/captures/{cid}/insole", "POST", {}))["outline"] == "saved"   # the insole follows it
    assert "stale" not in _listed(op, cid)["clog"] and call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 200
    after = body(call(f"{op}/api/captures/{cid}/clog", "POST", {"style": "stone"}))
    same = ("length_mm", "width_mm", "height_mm", "volume_cm3", "inside", "footbed", "warnings")
    assert {k: after[k] for k in same} == {k: before[k] for k in same}


def test_a_shoe_goes_stale_when_its_model_changes_and_is_removed_when_the_model_is_replaced(servers):
    """Its footbed is that model's: never offer a shoe made from a model that has since been replaced or rebuilt."""
    op, _, data = servers
    cid = _foot_capture(op)
    assert "error" not in body(call(f"{op}/api/captures/{cid}/clog", "POST", {}))
    assert call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 200

    # the model file changes underneath (e.g. rebuilt): marked stale, downloads refused
    mesh = data / "captures" / cid / "mesh.ply"
    later = time.time() + 5
    os.utime(mesh, (later, later))
    assert _listed(op, cid)["clog"].get("stale") is True
    st, raw, _ = call(f"{op}/api/captures/{cid}/clog/clog.3mf")
    assert st == 409 and "make the shoe again" in json.loads(raw)["error"]
    assert call(f"{op}/api/captures/{cid}/clog/clog-preview.bin")[0] == 409

    # a new import removes the old shoe altogether
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"), OBJ)[0] == 200
    assert "clog" not in _listed(op, cid) and not (data / "captures" / cid / "clog").exists()


def test_a_failed_shoe_rebuild_leaves_nothing_downloadable(servers):
    op, _, data = servers
    cid = _foot_capture(op)
    assert "error" not in body(call(f"{op}/api/captures/{cid}/clog", "POST", {}))
    # the model file is replaced by one that can't be read (e.g. a rebuild that died half-written)
    (data / "captures" / cid / "mesh.ply").write_bytes(b"ply\nformat ascii 1.0\nelement vertex 3\nend_header\n")
    r = body(call(f"{op}/api/captures/{cid}/clog", "POST", {}))
    assert "error" in r
    assert call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 409
    assert not (data / "captures" / cid / "clog").exists()
    assert "stale" not in _listed(op, cid)["clog"]  # a failed attempt is shown as that, not as an old shoe


@pytest.mark.parametrize("step, error, says", [
    ("write_outputs", OSError(28, "No space left on device"), "couldn't save the shoe's files ([Errno 28] No space left"),
    ("write_preview", RuntimeError("no preview"), "couldn't write the shoe's files"),
])
def test_a_shoe_whose_files_cant_be_written_counts_as_a_failed_build(servers, monkeypatch, step, error, says):
    """If writing the files fails (disk full, or the preview can't be made), an earlier shoe must not stay on
    offer as if it were this one."""
    op, _, data = servers
    cid = _foot_capture(op)
    assert "error" not in body(call(f"{op}/api/captures/{cid}/clog", "POST", {}))

    def fails(*a, **k):
        raise error
    monkeypatch.setattr(fw, step, fails)
    r = body(call(f"{op}/api/captures/{cid}/clog", "POST", {}))
    assert says in r["error"]
    assert call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 409
    assert not [p for p in (data / "captures" / cid).iterdir() if p.name.startswith("clog")]


def test_trial_pieces_that_cant_be_cut_are_said_and_the_shoe_still_stands(servers, monkeypatch):
    op, _, _ = servers
    cid = _foot_capture(op)

    def no_pieces(*a, **k):
        raise fw.FootwearError("no piece could be cut from this shoe")
    monkeypatch.setattr(fw, "write_trials", no_pieces)
    r = body(call(f"{op}/api/captures/{cid}/clog", "POST", {"trials": True}))
    assert "error" not in r and r["trials"] == {"error": "no piece could be cut from this shoe"}
    assert call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 200


def test_two_shoe_builds_at_once_both_succeed_and_leave_one_clean_result(servers):
    """Two studio tabs pressing Make shoe together: no half-written or lost files."""
    op, _, data = servers
    cid = _foot_capture(op)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda style: call(f"{op}/api/captures/{cid}/clog", "POST", {"style": style}),
                                ("stone", "stream")))
    assert [r[0] for r in results] == [200, 200]
    assert all("error" not in json.loads(r[1]) for r in results)
    folder = data / "captures" / cid
    assert sorted(p.name for p in folder.iterdir() if p.name.startswith("clog")) == ["clog"]  # no leftovers
    # the files are one build's, whole, and the listing describes that same build
    kept = json.loads((folder / "capture.json").read_text())["clog"]
    assert json.loads((folder / "clog" / "clog.json").read_text())["style"] == kept["style"]
    assert {p.name for p in (folder / "clog").iterdir()} == set(kept["files"])


def test_making_an_insole_and_a_shoe_from_one_capture_keeps_both(servers):
    op, _, data = servers
    cid = _foot_capture(op)
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    assert "error" not in body(call(f"{op}/api/captures/{cid}/clog", "POST", {}))
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    listed = _listed(op, cid)
    assert "stale" not in listed["insole"] and "stale" not in listed["clog"]
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 200
    assert call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 200


# ---- what a shoe can be set to, and a description read into those settings ------------------------------------

def test_what_the_trial_pieces_showed_is_kept_about_the_shoe_they_were_cut_from_and_changes_no_choice(servers, monkeypatch):
    op, phone, data = servers
    # a clock that moves on a second every time it is read: two stamps taken in one build would differ
    seconds = itertools.count()
    monkeypatch.setattr(server, "now_iso", lambda: (dt.datetime(2026, 11, 10, 22, 0) + dt.timedelta(seconds=next(seconds)))
                        .isoformat(timespec="seconds"))
    cid = _foot_capture(op)
    meta = lambda: json.loads((data / "captures" / cid / "capture.json").read_text())  # noqa: E731
    clog, url = f"{op}/api/captures/{cid}/clog", f"{op}/api/captures/{cid}/clog/fit"
    # before there is a shoe there are no pieces to have printed
    assert body(call(url)) == dict(shoes=[], stop=None, max_note=footwear_fit.MAX_NOTE)
    st, raw, _ = call(url, "POST", {"made": "never", "answers": {"hurt": "no"}})
    assert st == 400 and "say which shoe these trial pieces were cut from" in json.loads(raw)["error"]
    # ... and a shoe made without its trial pieces has none to record about either
    plain = body(call(clog, "POST", {"style": "stone", "fit": "snug"}))
    assert "error" not in plain and plain["trials"] is None
    assert body(call(url))["shoes"] == [] and "clog_trial_shoes" not in meta()
    assert call(url, "POST", {"made": plain["made"], "answers": {"hurt": "no"}})[0] == 400

    shoe = body(call(clog, "POST", {"style": "stone", "fit": "snug", "trials": True}))
    assert "error" not in shoe, shoe
    pieces = [p["piece"] for p in shoe["trials"]["pieces"]]
    (first,) = body(call(url))["shoes"]
    assert first == dict(made=shoe["made"], style="stone", choices=shoe["choices"], pieces=pieces, recordable=True,
                         name=fw.made_name("stone", "snug", "medium", shoe["made"]),
                         questions=footwear_fit.questions(pieces), records=[], suggestion=None)
    # the pieces' own sheet and data file name the shoe they were cut from, in the words the page lists it by
    sheet = lambda: call(f"{op}/api/captures/{cid}/clog/clog-trials.txt")[1].decode()  # noqa: E731
    assert f"These pieces were cut from the {first['name']}." in sheet()
    assert body(call(f"{op}/api/captures/{cid}/clog/clog-trials.json"))["cut_from"] == dict(
        made=shoe["made"], name=first["name"], style="stone", fit="snug", cushion="medium")
    assert "windows" not in [q["key"] for q in first["questions"]]   # Stone has no windows, so no swatch was cut
    assert call(f"{phone}/api/captures/{cid}/clog/fit")[0] == 403                      # studio only, like the shoe
    assert call(f"{phone}/api/captures/{cid}/clog/fit", "POST", {"made": shoe["made"], "answers": {"hurt": "no"}})[0] == 403

    for sent, says in (({"made": shoe["made"], "answers": {"hurt": "no", "walls": "tight"}}, "walls must be one of"),
                       ({"made": shoe["made"], "answers": {"walls": "press"}}, "say whether anything hurt"),
                       ({"made": shoe["made"], "answers": {"hurt": "no", "windows": "bars"}}, "this shoe has no pattern swatch"),
                       ({"made": shoe["made"], "answers": {"hurt": "no"}, "fit": "roomy"}, "not part of a trial record"),
                       ({"answers": {"hurt": "no"}}, "say which shoe these trial pieces were cut from")):
        st, raw, _ = call(url, "POST", sent)
        assert st == 400 and says in json.loads(raw)["error"], raw
    assert "clog_fit" not in meta()

    said = body(call(url, "POST", {"made": shoe["made"], "answers": {"hurt": "no", "cushion": "firm"}, "note": "tight at the heel"}))
    (about,) = said["shoes"]
    assert [(c["setting"], c["was"], c["to"]) for c in about["suggestion"]["changes"]] == [("cushion", "medium", "firm")]
    # a suggestion is only that: the shoe, its choices and its files are as they were
    assert meta()["clog"] == {k: v for k, v in _listed(op, cid)["clog"].items() if k != "stale"} == shoe
    (kept,) = meta()["clog_fit"]                                                       # the answers are what is kept
    assert kept["about"] == dict(made=shoe["made"], style="stone", choices=shoe["choices"], pieces=pieces)
    assert kept["answers"] == {"cushion": "firm", "hurt": "no"} and kept["note"] == "tight at the heel"
    assert about["records"] == [dict(recorded=kept["recorded"], note="tight at the heel", said=footwear_fit.in_words(kept["answers"]))]
    assert body(call(url)) == said

    # The shoe made again to the cushioning suggested, before its other pieces were tried. Its back half, tried
    # afterwards, is recorded about the shoe it was cut from, and read with that shoe's first record.
    again = body(call(clog, "POST", {"style": "stone", "fit": "snug", "cushion": "firm", "trials": True}))
    assert [s["made"] for s in meta()["clog_trial_shoes"]] == [shoe["made"], again["made"]] and again["made"] != shoe["made"]
    assert fw.made_name("stone", "snug", "firm", again["made"]) in sheet() and first["name"] not in sheet()
    said = body(call(url, "POST", {"made": shoe["made"], "answers": {"hurt": "no", "walls": "press"}}))
    newest, first = said["shoes"]
    assert newest["made"] == again["made"] and newest["records"] == [] and newest["suggestion"] is None
    assert [(c["setting"], c["was"], c["to"]) for c in first["suggestion"]["changes"]] == \
        [("cushion", "medium", "firm"), ("fit", "snug", "regular")]
    assert len(first["records"]) == 2 and all(r["about"]["made"] == shoe["made"] for r in meta()["clog_fit"])

    # a piece of the new shoe hurt: the stop rule, and nothing suggested for either shoe from then on
    said = body(call(url, "POST", {"made": again["made"], "answers": {"hurt": "yes", "walls": "press"}}))
    assert said["stop"]["words"] == footwear_fit.STOP and said["stop"]["nothing"] == footwear_fit.NOTHING_FOR_HURT
    assert all(s["suggestion"]["changes"] == [] and s["suggestion"]["stop"] == footwear_fit.STOP for s in said["shoes"])
    assert meta()["clog_fit_stop"] == dict(recorded=said["stop"]["recorded"], made=again["made"])
    said = body(call(url, "POST", {"made": shoe["made"], "answers": {"hurt": "no", "toe_over": "presses"}}))   # later, painless
    assert said["stop"]["made"] == again["made"] and all(s["suggestion"]["changes"] == [] for s in said["shoes"])
    said = body(call(url, "POST", {"made": shoe["made"], "answers": {"hurt": "yes"}}))
    assert meta()["clog_fit_stop"]["made"] == again["made"]                            # the first that hurt is what is kept
    # the model replaced: the shoe goes; what was printed and tried is still on record, and can still be added to
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"), OBJ)[0] == 200
    assert "clog" not in meta() and len(meta()["clog_fit"]) == 5
    got = body(call(url))
    assert [len(s["records"]) for s in got["shoes"]] == [1, 4] and got["stop"]["made"] == again["made"]
    assert call(url, "POST", {"made": again["made"], "answers": {"hurt": "no"}})[0] == 200


def test_only_the_newest_trial_records_and_shoes_are_kept_and_a_stop_outlives_its_record(servers, monkeypatch):
    op, _, data = servers
    cid = _foot_capture(op)
    made = iter(f"2026-11-1{i}T10:00:00" for i in range(1, 9))
    monkeypatch.setattr(server, "make_clog", lambda d, meta, choices, trials=False: dict(
        made=next(made), style="stone", choices=choices, trials=dict(pieces=[dict(piece="sole-block")])))
    monkeypatch.setattr(footwear_fit, "KEPT", 3)
    monkeypatch.setattr(footwear_fit, "SHOES_KEPT", 2)
    clog, url = f"{op}/api/captures/{cid}/clog", f"{op}/api/captures/{cid}/clog/fit"
    shoes = [body(call(clog, "POST", {}))["made"] for _ in range(3)]
    assert [s["made"] for s in body(call(url))["shoes"]] == [shoes[2], shoes[1]]       # the two newest, the newest first
    assert call(url, "POST", {"made": shoes[0], "answers": {"hurt": "no"}})[0] == 400  # the oldest is no longer known here
    said = body(call(url, "POST", {"made": shoes[1], "answers": {"hurt": "yes"}, "note": "try 0"}))
    for i in range(1, 5):
        said = body(call(url, "POST", {"made": shoes[2], "answers": {"hurt": "no", "cushion": "firm"}, "note": f"try {i}"}))
    assert [r["note"] for s in said["shoes"] for r in s["records"]] == ["try 4", "try 3", "try 2"]
    # the record that said something hurt has gone with the oldest; that it was said has not
    assert said["stop"]["made"] == shoes[1] and said["shoes"][0]["suggestion"]["changes"] == []
    assert said["shoes"][0]["suggestion"]["stop"] == footwear_fit.STOP


def test_the_studio_says_what_a_shoe_can_be_set_to(servers):
    op, phone, _ = servers
    assert call(f"{phone}/api/footwear/options")[0] == 403
    opts = body(call(f"{op}/api/footwear/options"))
    assert opts == dict(footwear_choices.options(), described_by="keywords")
    assert opts["untested"] == fw.UNTESTED
    assert call(f"{op}/api/footwear/options", "POST", {})[0] == 404
    assert call(f"{op}/api/footwear/nothing")[0] == 404


def test_a_description_is_read_on_this_computer_unless_the_studio_was_started_to_ask_claude(servers, monkeypatch):
    op, phone, _ = servers

    def never(*a, **k):
        raise AssertionError("a description left this computer without --describe-with-claude")
    monkeypatch.setattr(footwear_choices, "from_claude", never)
    words = {"text": "A roomy one with lots of holes, in blue, for my flat feet."}
    assert call(f"{phone}/api/footwear/describe", "POST", words)[0] == 403
    r = body(call(f"{op}/api/footwear/describe", "POST", words))
    assert r["read_by"] == "keywords" and r["settings"] == {}  # nothing is set from a sentence about a foot condition
    assert any("Not a medical device" in n for n in r["notes"]) and footwear_choices.NOT_READ in r["notes"]
    r = body(call(f"{op}/api/footwear/describe", "POST", {"text": "roomy, with slots, in blue"}))
    assert r["settings"] == {"fit": "roomy", "style": "stream"}
    assert any("spool" in n for n in r["notes"])
    for nothing in ({"text": "  "}, {}, {"text": "x" * (footwear_choices.MAX_DESCRIPTION + 1)}):
        assert call(f"{op}/api/footwear/describe", "POST", nothing)[0] == 400, nothing


def test_a_studio_started_to_ask_claude_says_so_and_sends_the_description_there(tmp_path, monkeypatch):
    handler = make_handler(WEB_DIR, tmp_path, local_check=lambda h: True, studio_key=KEY, describe_with_claude=True)
    httpd = StudioServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    op = f"http://127.0.0.1:{httpd.server_address[1]}"
    sent = []

    def stand_in(text, client=None):
        sent.append(text)
        return dict(settings={"toe": "square"}, understood=[], notes=[], read_by="claude")
    monkeypatch.setattr(footwear_choices, "from_claude", stand_in)
    try:
        assert body(call(f"{op}/api/footwear/options"))["described_by"] == "claude"
        r = body(call(f"{op}/api/footwear/describe", "POST", {"text": "boxy at the front"}))
        assert sent == ["boxy at the front"] and r["read_by"] == "claude" and r["settings"] == {"toe": "square"}
    finally:
        httpd.shutdown()


def test_a_sole_scan_the_studio_would_refuse_today_makes_no_shoe_and_keeps_none(servers, monkeypatch):
    """A SYNTHETIC sole-up scan with its forefoot rolled onto one edge, in the library as scans were kept before
    the studio checked them on arrival. Its footbed would carry a wedge across the shoe's floor, so no shoe is
    made; and a shoe made from this same model before the rule (faked: the rule switched off) isn't kept, where
    choices the generator refuses leave an earlier shoe standing."""
    from test_insole import _rolled_forefoot_scan

    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    rolled = _rolled_forefoot_scan(15.0).export(file_type="obj").encode()
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", rolled, OBJ)[0] == 422   # today: not kept
    cid = _new_sole_capture(op, "right")
    monkeypatch.setattr(server, "check_completeness", lambda *a, **k: None)                   # before it checked
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", rolled, OBJ)[0] == 200
    monkeypatch.undo()
    monkeypatch.setattr(fw, "unfit_for_a_footbed", lambda prep, kind: [])                     # before this rule
    made = body(call(f"{op}/api/captures/{cid}/clog", "POST", {"style": "stone"}))
    assert "error" not in made and call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 200
    monkeypatch.undo()

    st, raw, _ = call(f"{op}/api/captures/{cid}/clog", "POST", {"style": "stone"})
    r = json.loads(raw)
    assert st == 200 and set(r) == {"error"}, raw
    assert r["error"].startswith("no shoe is made from this sole scan") and "THE FOREFOOT WAS ROLLED" in r["error"]
    assert "Scan again" in r["error"]
    assert not (data / "captures" / cid / "clog").exists()
    assert call(f"{op}/api/captures/{cid}/clog/clog.3mf")[0] == 409
    assert _listed(op, cid)["clog"] == r
    # and it can still make an insole, with the warning the insole generator has always given
    st, raw, _ = call(f"{op}/api/captures/{cid}/insole", "POST", {})
    assert st == 200 and any(w.startswith("THE FOREFOOT WAS ROLLED") for w in json.loads(raw)["warnings"]), raw
