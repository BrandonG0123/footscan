"""The studio's Make shoe: a clog for a foot capture, made to the choices sent (server.make_clog, the clog API,
the footwear API). Every foot here is ``synth.block_foot`` (SYNTHETIC), imported as the iPhone app would send it.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from footscan import footwear as fw
from footscan import footwear_choices, server
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
