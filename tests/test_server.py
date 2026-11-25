import io
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from footscan.server import PUBLIC_PAIRING_NOTE, STALE_MESSAGES, WEB_DIR, StudioServer, make_handler

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
KEY = "test-studio-key"
ACKS = {"not_medical_device": True, "clinician_review": True, "break_in": True, "photo_consent": True}
SURVEY = {
    "adult": "yes", "conditions": ["none"], "pain": "none", "arch": "flat", "tiptoe": "appears", "arch_change": "no",
    "use": "sport", "sport": "tennis", "sport_level": "competitive", "shoe_type": "court",
    "removable_insole": "yes", "current_insoles": "none", "goals": ["support", "stability"],
}
PERSON = {"name": "Test Person", "feet": ["right", "left"], "acknowledgments": ACKS, "survey": SURVEY,
          "mat_check_value": 10, "mat_check_unit": "cm"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def start(tmp_path, local: bool):
    handler = make_handler(WEB_DIR, tmp_path, local_check=lambda h: local, studio_key=KEY)
    httpd = StudioServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture
def servers(tmp_path):
    """Same data dir, two views: the operator's machine and a phone on the Wi-Fi."""
    op, op_url = start(tmp_path, local=True)
    ph, ph_url = start(tmp_path, local=False)
    yield op_url, ph_url, tmp_path
    op.shutdown()
    ph.shutdown()


def call(url, method="GET", body=None, headers=None, opener=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with (opener or urllib.request.build_opener()).open(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def body(resp):
    return json.loads(resp[1])


def test_customer_flow_end_to_end(servers):
    op, phone, data = servers
    status, raw, _ = call(f"{phone}/api/submissions", "POST", PERSON)
    assert status == 201
    sub = json.loads(raw)
    tok = {"X-Upload-Token": sub["upload_token"]}
    keys = [p["key"] for p in sub["plan"]]
    assert keys == ["right-swb", "left-swb", "right-fwb", "left-fwb"]  # flat foot -> standing scans too

    # can't send before every planned scan is done
    assert call(f"{phone}/api/submissions/{sub['id']}/submit", "POST", {}, tok)[0] == 400

    for key in keys:
        base = f"{phone}/api/submissions/{sub['id']}/scans/{key}"
        assert call(f"{base}/start", "POST", {}, tok)[0] == 200
        for n in (1, 2, 3):
            assert call(f"{base}/frames/{n}", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})[0] == 200
        assert call(f"{base}/complete", "POST", {"frames": [], "summary": {"frames_kept": 3}, "load_kg": "9.5"}, tok)[0] == 200

    assert call(f"{phone}/api/submissions/{sub['id']}/submit", "POST", {}, tok)[0] == 200
    # upload token is closed after sending
    assert call(f"{phone}/api/submissions/{sub['id']}/scans/right-swb/start", "POST", {}, tok)[0] == 403
    # scans outside the plan don't exist
    assert call(f"{phone}/api/submissions/{sub['id']}/scans/right-nwb/start", "POST", {}, tok)[0] == 404

    listing = body(call(f"{op}/api/submissions"))
    assert listing[0]["id"] == sub["id"] and listing[0]["status"] == "received"
    assert "upload_token" not in listing[0]
    detail = body(call(f"{op}/api/submissions/{sub['id']}"))
    assert detail["scans"]["right-swb"]["frame_files"] == ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"]
    assert detail["scans"]["left-fwb"]["load_kg"] == 9.5 and detail["scans"]["left-fwb"]["condition"] == "fwb"
    assert detail["survey"]["sport"] == "tennis"
    assert [f["code"] for f in detail["flags"]] == ["tiptoe_arch"]
    status, img, _ = call(f"{op}/api/submissions/{sub['id']}/scans/left-swb/frames/2.jpg")
    assert status == 200 and img == JPEG

    updated = body(call(f"{op}/api/submissions/{sub['id']}/status", "POST", {"status": "needs_rescan", "note": "blurry heel"}))
    assert updated["status"] == "needs_rescan" and updated["history"][-1]["note"] == "blurry heel"


def test_restarting_a_foot_clears_old_frames(servers):
    _, phone, data = servers
    sub = body(call(f"{phone}/api/submissions", "POST", {**PERSON, "feet": ["right"]}))
    tok = {"X-Upload-Token": sub["upload_token"]}
    base = f"{phone}/api/submissions/{sub['id']}/scans/right-swb"
    call(f"{base}/start", "POST", {}, tok)
    for n in (1, 2, 3):
        call(f"{base}/frames/{n}", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})
    call(f"{base}/start", "POST", {}, tok)
    call(f"{base}/frames/1", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})
    assert body(call(f"{base}/complete", "POST", {"frames": []}, tok))["frames_on_disk"] == 1


@pytest.mark.parametrize("patch,msg", [
    ({"acknowledgments": {**ACKS, "clinician_review": False}}, "acknowledgments"),
    ({"acknowledgments": {}}, "acknowledgments"),
    ({"name": "  "}, "name"),
    ({"feet": []}, "feet"),
    ({"feet": ["right", "right"]}, "feet"),
    ({"feet": ["middle"]}, "feet"),
    ({"mat_check_value": None}, "mat_check_value"),
    ({"mat_check_value": 9.6}, "wrong size"),                      # cm bar, fit-to-page
    ({"mat_check_value": 4}, "wrong size"),                        # an inch reading against the cm bar
    ({"mat_check_value": 3.7, "mat_check_unit": "in"}, "wrong size"),
    ({"mat_check_value": 10, "mat_check_unit": "furlong"}, "mat_check_unit"),
])
def test_submission_validation(servers, patch, msg):
    _, phone, _ = servers
    status, raw, _ = call(f"{phone}/api/submissions", "POST", {**PERSON, **patch})
    assert status == 400 and msg in json.loads(raw)["error"]


def test_phone_cannot_see_studio_or_other_scans(servers):
    op, phone, _ = servers
    sub = body(call(f"{phone}/api/submissions", "POST", PERSON))
    assert call(f"{phone}/api/submissions")[0] == 403
    assert call(f"{phone}/api/submissions/{sub['id']}")[0] == 403
    assert call(f"{phone}/api/submissions/{sub['id']}/status", "POST", {"status": "archived"})[0] == 403
    assert call(f"{phone}/api/captures")[0] == 403
    assert call(f"{phone}/api/studio")[0] == 403
    assert call(f"{phone}/studio/")[0] == 403
    assert call(f"{phone}/studio/submission.html")[0] == 403
    # wrong or missing upload token
    assert call(f"{phone}/api/submissions/{sub['id']}/scans/right-swb/start", "POST", {}, {"X-Upload-Token": "nope"})[0] == 403
    assert call(f"{phone}/api/submissions/{sub['id']}/scans/right-swb/start", "POST", {})[0] == 403
    # the customer pages themselves are public
    assert call(f"{phone}/")[0] == 200
    assert call(f"{phone}/care.html")[0] == 200


def test_survey_endpoints_and_screening(servers):
    _, phone, data = servers
    schema = body(call(f"{phone}/api/survey"))
    assert [s["id"] for s in schema["sections"]] == ["safety", "feet", "use"]

    plan = body(call(f"{phone}/api/survey/evaluate", "POST", {"feet": ["left"], "survey": SURVEY}))
    assert [p["key"] for p in plan["plan"]] == ["left-swb", "left-fwb"]
    assert not (data / "submissions").exists()  # evaluating stores nothing

    status, raw, _ = call(f"{phone}/api/survey/evaluate", "POST", {"feet": ["left"], "survey": {**SURVEY, "use": "sport", "sport": ""}})
    assert status == 400 and "sport" in json.loads(raw)["fields"]

    screened = {**PERSON, "survey": {**SURVEY, "conditions": ["diabetes"]}}
    status, raw, _ = call(f"{phone}/api/submissions", "POST", screened)
    assert status == 422 and "podiatrist" in json.loads(raw)["blocked"]["message"]
    assert not any((data / "submissions").glob("*")) if (data / "submissions").exists() else True


def test_studio_key_opens_the_studio_from_any_device(servers):
    """The key alone must always work: cookies can be blocked, cleared, or
    refused behind a self-signed certificate."""
    _, phone, _ = servers
    # no key: a readable page, not a raw error
    status, page, headers = call(f"{phone}/studio/")
    assert status == 403 and headers["Content-Type"].startswith("text/html")
    assert b"Studio locked" in page and b'name="key"' in page
    assert call(f"{phone}/studio/?key=wrong")[0] == 403

    # key in the URL serves the page and offers a cookie for next time
    status, _, headers = call(f"{phone}/studio/?key={KEY}")
    assert status == 200
    cookie = headers["Set-Cookie"].split(";")[0]
    assert "HttpOnly" in headers["Set-Cookie"]

    # afterwards any of the three work, on pages and on the API
    assert call(f"{phone}/studio/capture.html", headers={"Cookie": cookie})[0] == 200
    assert call(f"{phone}/studio/capture.html?key={KEY}")[0] == 200
    assert call(f"{phone}/api/submissions", headers={"Cookie": cookie})[0] == 200
    assert call(f"{phone}/api/submissions", headers={"X-Studio-Key": KEY})[0] == 200
    assert call(f"{phone}/api/submissions?key={KEY}")[0] == 200
    assert call(f"{phone}/api/submissions", headers={"X-Studio-Key": "wrong"})[0] == 403
    assert call(f"{phone}/api/submissions", headers={"Cookie": "footscan_studio=wrong"})[0] == 403


def test_research_capture_roundtrip(servers):
    op, _, data = servers
    setup = {"foot": "right", "condition": "fwb", "session": "S1", "load_kg": 38.5, "method": "bare_skin"}
    status, raw, _ = call(f"{op}/api/captures", "POST", setup)
    assert status == 201
    cid = json.loads(raw)["id"]
    assert call(f"{op}/api/captures/{cid}/frames/1", "PUT", JPEG, {"Content-Type": "image/jpeg"})[0] == 200
    assert call(f"{op}/api/captures/{cid}/frames/2", "PUT", b"not a jpeg", {"Content-Type": "image/jpeg"})[0] == 400
    assert call(f"{op}/api/captures/{cid}/complete", "POST", {"frames": []})[0] == 200
    meta = json.loads((data / "captures" / cid / "capture.json").read_text())
    assert meta["status"] == "complete" and meta["frame_files"] == ["frame_0001.jpg"]
    assert call(f"{op}/api/captures", "POST", {**setup, "load_kg": None})[0] == 400


def test_check_bar_accepts_either_ruler(servers):
    """A 10 cm bar and a 4 inch bar are the same print; both readings pass."""
    op, phone, _ = servers
    bars = body(call(f"{phone}/api/mat"))["check_bars"]
    assert {b["unit"] for b in bars} == {"cm", "in"}
    created = {}
    for reading, unit in [(10, "cm"), (10.1, "cm"), (4, "in"), (3.97, "in")]:
        status, raw, _ = call(f"{phone}/api/submissions", "POST",
                              {**PERSON, "mat_check_value": reading, "mat_check_unit": unit})
        assert status == 201, raw
        created[(reading, unit)] = json.loads(raw)["id"]
    detail = body(call(f"{op}/api/submissions/{created[(3.97, 'in')]}"))
    assert detail["mat_check"]["unit"] == "in"
    assert detail["mat_check"]["mm"] == pytest.approx(100.8, abs=0.1)  # stored in mm whatever the ruler


def test_pdf_download_header(servers):
    op, _, _ = servers
    status, data, headers = call(f"{op}/mat/footscan-mat-letter.pdf")
    assert status == 200 and data[:4] == b"%PDF" and headers["Content-Type"] == "application/pdf"
    assert "Content-Disposition" not in headers  # opens in the browser by default
    _, _, headers = call(f"{op}/mat/footscan-mat-letter.pdf?download=1")
    assert headers["Content-Disposition"].startswith("attachment")


def test_object_capture_needs_no_foot_mat_or_load(servers):
    """Scanner test captures: any object, no mat, marked unmeasurable."""
    op, _, data = servers
    status, raw, _ = call(f"{op}/api/captures", "POST",
                          {"condition": "object", "session": "MATTEST", "notes": "shoe on a desk"})
    assert status == 201
    cid = json.loads(raw)["id"]
    meta = json.loads((data / "captures" / cid / "capture.json").read_text())
    assert meta["foot"] is None and meta["measurable"] is False and meta["load_kg"] is None
    # foot conditions still demand a foot, and weight-bearing still demands the scale reading
    assert call(f"{op}/api/captures", "POST", {"condition": "swb", "session": "S1", "load_kg": 9})[0] == 400
    assert call(f"{op}/api/captures", "POST", {"condition": "fwb", "session": "S1", "foot": "right"})[0] == 400
    assert json.loads(call(f"{op}/api/captures", "POST", {"condition": "object", "session": "S1", "foot": "right"})[1])["id"]


def test_static_traversal_blocked(servers):
    op, _, _ = servers
    assert call(f"{op}/../pyproject.toml")[0] == 404
    assert call(f"{op}/assets/%2e%2e/%2e%2e/pyproject.toml")[0] == 404
    assert call(f"{op}/api/submissions/..%2F..%2Fx")[0] in (400, 404)


# ---- hosting safety -------------------------------------------------------

def test_proxy_headers_are_never_treated_as_local(tmp_path):
    """A tunnel on this machine connects from loopback; it must not unlock the studio."""
    from footscan.server import is_loopback

    class Fake:
        def __init__(self, headers):
            self.client_address = ("127.0.0.1", 5000)
            self.headers = headers

    assert is_loopback(Fake({})) is True
    for h in ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded", "X-Real-IP", "True-Client-IP"):
        assert is_loopback(Fake({h: "203.0.113.9"})) is False, h


def test_tunnelled_request_cannot_open_studio(tmp_path):
    from footscan.server import is_loopback

    httpd = StudioServer(("127.0.0.1", 0), make_handler(WEB_DIR, tmp_path, local_check=is_loopback, studio_key=KEY))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert call(f"{url}/api/submissions")[0] == 200  # genuinely local
        assert call(f"{url}/api/submissions", headers={"CF-Connecting-IP": "198.51.100.7"})[0] == 403
        assert call(f"{url}/studio/", headers={"X-Forwarded-For": "198.51.100.7"})[0] == 403
        # ...but the studio key still works through the tunnel
        assert call(f"{url}/api/submissions", headers={"X-Forwarded-For": "198.51.100.7",
                                                       "Cookie": f"footscan_studio={KEY}"})[0] == 200
    finally:
        httpd.shutdown()


def test_security_headers_on_every_response(servers):
    op, phone, _ = servers
    for url in (f"{phone}/", f"{phone}/api/survey", f"{phone}/api/submissions"):
        _, _, headers = call(url)
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_submission_creation_is_rate_limited(tmp_path):
    httpd = StudioServer(("127.0.0.1", 0), make_handler(WEB_DIR, tmp_path, local_check=lambda h: False,
                                                               studio_key=KEY, submissions_per_hour=2))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        codes = [call(f"{url}/api/submissions", "POST", PERSON)[0] for _ in range(3)]
        assert codes == [201, 201, 429]
    finally:
        httpd.shutdown()


# ---- rescan ------------------------------------------------------------------

def finish_scan(phone, sid, key, tok, n=2):
    base = f"{phone}/api/submissions/{sid}/scans/{key}"
    assert call(f"{base}/start", "POST", {}, tok)[0] == 200
    for i in range(1, n + 1):
        assert call(f"{base}/frames/{i}", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})[0] == 200
    assert call(f"{base}/complete", "POST", {"frames": []}, tok)[0] == 200


def test_rescan_round_trip(servers):
    op, phone, data = servers
    sub = body(call(f"{phone}/api/submissions", "POST", {**PERSON, "feet": ["right"]}))
    tok = {"X-Upload-Token": sub["upload_token"]}
    for p in sub["plan"]:
        finish_scan(phone, sub["id"], p["key"], tok)
    assert call(f"{phone}/api/submissions/{sub['id']}/submit", "POST", {}, tok)[0] == 200

    # the phone can't ask for a rescan, and bad scan keys are refused
    assert call(f"{phone}/api/submissions/{sub['id']}/rescan", "POST", {"scans": ["right-swb"]})[0] == 403
    assert call(f"{op}/api/submissions/{sub['id']}/rescan", "POST", {"scans": ["left-swb"]})[0] == 400

    link = body(call(f"{op}/api/submissions/{sub['id']}/rescan", "POST",
                     {"scans": ["right-swb"], "note": "heel was blurry"}))
    assert link["path"].startswith(f"/?rescan={sub['id']}&t=")
    new_tok = {"X-Upload-Token": link["path"].split("&t=")[1]}
    # the old photos are kept, not deleted
    assert any((data / "submissions" / sub["id"] / "_previous").glob("right-swb-*"))

    info = body(call(f"{phone}/api/submissions/{sub['id']}/rescan", headers=new_tok))
    assert info["note"] == "heel was blurry" and [p["key"] for p in info["plan"]] == ["right-swb"]
    assert call(f"{phone}/api/submissions/{sub['id']}/rescan", headers=tok)[0] == 403  # old token is dead

    # can't send until the redone scan is complete, and a rescan needs a fresh mat check
    assert call(f"{phone}/api/submissions/{sub['id']}/submit", "POST", {}, new_tok)[0] == 400
    finish_scan(phone, sub["id"], "right-swb", new_tok, n=3)
    assert call(f"{phone}/api/submissions/{sub['id']}/submit", "POST", {}, new_tok)[0] == 400
    ok = call(f"{phone}/api/submissions/{sub['id']}/submit", "POST",
              {"mat_check_value": 4, "mat_check_unit": "in"}, new_tok)
    assert ok[0] == 200

    detail = body(call(f"{op}/api/submissions/{sub['id']}"))
    assert detail["status"] == "received" and "rescan" not in detail
    assert detail["rescans"][0]["mat_check"]["unit"] == "in"
    assert len(detail["scans"]["right-swb"]["frame_files"]) == 3
    assert call(f"{phone}/api/submissions/{sub['id']}/rescan", headers=new_tok)[0] == 403  # link closed


def test_operator_can_delete_a_submission(servers):
    op, phone, data = servers
    sub = body(call(f"{phone}/api/submissions", "POST", PERSON))
    assert call(f"{phone}/api/submissions/{sub['id']}", "DELETE")[0] == 403
    assert call(f"{op}/api/submissions/{sub['id']}", "DELETE")[0] == 200
    assert not (data / "submissions" / sub["id"]).exists()


# ---- imported 3D models ------------------------------------------------------------

@pytest.mark.parametrize("scale,units", [(0.001, "m"), (1.0, "mm")])
def test_mesh_import_detects_units(servers, tmp_path, scale, units):
    import trimesh

    op, _, data = servers
    foot_ish = trimesh.creation.box(extents=[260 * scale, 100 * scale, 70 * scale])
    obj = foot_ish.export(file_type="obj").encode()
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "fwb", "foot": "right", "session": "L1",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    status, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj", "PUT", obj, {"Content-Type": "application/octet-stream"})
    assert status == 200, raw
    mesh = json.loads(raw)["mesh"]
    assert mesh["units_detected"] == units
    assert mesh["extents_mm"] == pytest.approx([260, 100, 70], abs=0.5)
    assert (data / "captures" / cid / "mesh.ply").exists()


def test_mesh_import_rejects_bad_files(servers):
    op, _, _ = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "object", "session": "L1"}))["id"]
    assert call(f"{op}/api/captures/{cid}/mesh?ext=usdz", "PUT", b"x", {"Content-Type": "application/octet-stream"})[0] == 400
    status, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj", "PUT", b"not a mesh",
                          {"Content-Type": "application/octet-stream"})
    assert status == 400 and "couldn't read" in json.loads(raw)["error"]


def test_imported_calibration_object_is_scored_and_rescored_with_calipers(servers):
    """A model from the iPhone test app (metres, Y up) gets the accuracy study on import."""
    from test_imported import _as_exported

    op, _, data = servers
    obj = _as_exported(table=False, tilt_deg=0.0).export(file_type="obj").encode()
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "calibration", "session": "LIDAR",
                                                    "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=x", "PUT", obj,
                {"Content-Type": "application/octet-stream"})[0] == 400
    status, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", obj,
                          {"Content-Type": "application/octet-stream"})
    assert status == 200, raw
    acc = json.loads(raw)["accuracy"]
    assert acc["median_mm"] < 0.01 and abs(acc["length_mm"]) < 0.06 and acc["reference"] == "model"
    assert (data / "captures" / cid / "accuracy.json").exists()
    assert call(f"{op}/api/captures/{cid}/accuracy")[0] == 200

    # caliper readings of the print become the reference, straight away
    st, raw, _ = call(f"{op}/api/captures/{cid}/calipers", "PUT", {"length": 149.8})
    assert st == 200, raw
    acc = json.loads(raw)["accuracy"]
    assert acc["reference"] == "calipers" and acc["length_mm"] == pytest.approx(0.2, abs=0.06)


def test_importing_something_else_as_the_calibration_object_is_reported_not_crashed(servers):
    import trimesh

    op, _, _ = servers
    shoe_ish = trimesh.creation.box(extents=[2.6, 1.0, 1.2])  # metres, and far too big: no real scale
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "calibration", "session": "LIDAR",
                                                    "method": "imported_mesh"}))["id"]
    status, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj", "PUT", shoe_ish.export(file_type="obj").encode(),
                          {"Content-Type": "application/octet-stream"})
    assert status == 200, raw
    assert "calibration object is 150 mm" in json.loads(raw)["accuracy"]["error"]
    assert call(f"{op}/api/captures/{cid}/accuracy")[0] == 404


# --------------------------------------------------------------------------
# Phase 2: 3D models from the studio
# --------------------------------------------------------------------------
def make_capture(op, condition="calibration", foot=None, frames=2):
    st, raw, _ = call(f"{op}/api/captures", "POST", {"condition": condition, "foot": foot, "session": "S1"})
    assert st == 201, raw
    cid = json.loads(raw)["id"]
    for n in range(1, frames + 1):
        call(f"{op}/api/captures/{cid}/frames/{n}", "PUT", JPEG, {"Content-Type": "image/jpeg"})
    call(f"{op}/api/captures/{cid}/complete", "POST", {"frames": []})
    return cid


def test_calibration_capture_is_not_foot_data(servers):
    op, _, data = servers
    cid = make_capture(op)
    meta = json.loads((data / "captures" / cid / "capture.json").read_text())
    assert meta["foot"] is None and meta["measurable"] is False and meta["condition"] == "calibration"


def test_recon_status_before_any_build(servers):
    op, _, _ = servers
    cid = make_capture(op)
    assert body(call(f"{op}/api/captures/{cid}/recon")) == {"state": "none"}


def test_recon_needs_photos(servers):
    op, _, _ = servers
    cid = make_capture(op, frames=0)
    assert call(f"{op}/api/captures/{cid}/recon", "POST", {})[0] == 400


def test_recon_is_operator_only(servers):
    op, phone, _ = servers
    cid = make_capture(op)
    assert call(f"{phone}/api/captures/{cid}/recon")[0] == 403
    assert call(f"{phone}/api/captures/{cid}/recon", "POST", {})[0] == 403


def test_recon_files_are_whitelisted(servers):
    op, _, data = servers
    cid = make_capture(op)
    out = data / "captures" / cid / "recon"
    out.mkdir()
    (out / "mesh.ply").write_bytes(b"ply\n")
    st, raw, h = call(f"{op}/api/captures/{cid}/recon/mesh.ply")
    assert st == 200 and raw == b"ply\n" and "attachment" in h["Content-Disposition"]
    assert call(f"{op}/api/captures/{cid}/recon/log.txt")[0] == 404
    assert call(f"{op}/api/captures/{cid}/recon/..%2Fcapture.json")[0] == 404
    assert call(f"{op}/api/captures/{cid}/recon/report.json")[0] == 404  # not there yet


def test_calipers_saved_and_validated(servers):
    op, _, data = servers
    cid = make_capture(op)
    assert call(f"{op}/api/captures/{cid}/calipers", "PUT", {"length": "abc"})[0] == 400
    assert call(f"{op}/api/captures/{cid}/calipers", "PUT", {"length": 9999})[0] == 400
    st, raw, _ = call(f"{op}/api/captures/{cid}/calipers", "PUT", {"length": "149.82", "width": "", "base": 10.04})
    assert st == 200
    saved = json.loads((data / "captures" / cid / "calipers.json").read_text())
    assert saved == {"length": 149.82, "base": 10.04}
    assert body(call(f"{op}/api/captures/{cid}/recon")) == {"state": "none"}  # readings alone don't build


def test_runner_one_build_at_a_time_and_notices_a_dead_process(tmp_path, monkeypatch):
    from footscan import recon_jobs

    # A stand-in `footscan.cli` that sleeps and exits without writing "done". It's put first on PYTHONPATH and
    # run by this same Python, so the test runs on Windows too (a `#!/bin/sh` fake can't be started there).
    fake = tmp_path / "fake" / "footscan"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("", encoding="utf-8")
    (fake / "cli.py").write_text(
        "import sys, time\nprint(f'utf8_mode={sys.flags.utf8_mode}', flush=True)\ntime.sleep(2)\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(fake.parent))
    monkeypatch.setenv("PYTHONUTF8", "0")  # as on Windows; a C locale would otherwise turn UTF-8 mode on by itself
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    runner = recon_jobs.ReconRunner(python=sys.executable)
    runner.start(a, calibration_object=False)
    assert recon_jobs.summary(a, runner)["state"] == "running"
    with pytest.raises(recon_jobs.Busy):
        runner.start(b, calibration_object=False)
    runner.proc.wait()
    # it exited without writing "done": that's a failure, not "still running"
    s = recon_jobs.summary(a, runner)
    assert s["state"] == "failed" and "unexpectedly" in s["error"]
    # the build runs in UTF-8 mode, so its log and files are UTF-8 on Windows as well
    assert "utf8_mode=1" in (a / "recon" / "log.txt").read_text(encoding="utf-8")


def test_customer_scan_recon_writes_what_the_pipeline_needs(servers):
    op, phone, data = servers
    sub = body(call(f"{phone}/api/submissions", "POST", PERSON))
    tok = {"X-Upload-Token": sub["upload_token"]}
    key = sub["plan"][0]["key"]
    base = f"{phone}/api/submissions/{sub['id']}/scans/{key}"
    call(f"{base}/start", "POST", {}, tok)
    call(f"{base}/frames/1", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})
    call(f"{base}/complete", "POST", {"frames": [], "summary": {"mat_paper": "a4"}}, tok)
    # the phone can't start a build
    assert call(f"{phone}/api/submissions/{sub['id']}/scans/{key}/recon", "POST", {})[0] == 403
    st, raw, _ = call(f"{op}/api/submissions/{sub['id']}/scans/{key}/recon", "POST", {})
    assert st == 202, raw
    meta = json.loads((data / "submissions" / sub["id"] / key / "capture.json").read_text())
    assert meta["foot"] == key.split("-")[0] and meta["condition"] == key.split("-")[1]
    assert meta["mat_paper"] == "a4" and meta["frames"] == [{"file": "frame_0001.jpg"}]


# --------------------------------------------------------------------------
# Phase 3: landmarks
# --------------------------------------------------------------------------
def test_landmark_endpoints(servers):
    import synth
    from footscan.recon import viewer_data
    from test_landmarks import placed

    op, phone, data = servers
    st, raw, _ = call(f"{op}/api/captures", "POST", {"condition": "fwb", "foot": "right", "session": "S1", "load_kg": 40})
    cid = json.loads(raw)["id"]
    base = f"{op}/api/captures/{cid}"
    info = body(call(f"{base}/picks"))
    assert info["has_model"] is False and info["picks"] == []
    assert call(f"{base}/viewer.bin")[0] == 404
    assert call(f"{base}/picks/1", "PUT", {"landmarks": {}})[0] == 400  # no model yet

    recon = data / "captures" / cid / "recon"
    recon.mkdir()
    m = synth.block_foot(0.0)
    m.export(recon / "mesh.ply")
    viewer_data.write(m, recon / "viewer.bin")
    info = body(call(f"{base}/picks"))
    assert info["has_model"] and info["in_mat_frame"] and "navicular_tuberosity" in [s["key"] for s in info["spec"]]
    st, raw, _ = call(f"{base}/viewer.bin")
    assert st == 200 and raw[:4] == b"FSV1"

    assert call(f"{phone}/api/captures/{cid}/picks/1", "PUT", {"landmarks": placed(0.0)})[0] == 403
    st, raw, _ = call(f"{base}/picks/1", "PUT", {"landmarks": placed(0.0)})
    assert st == 200, raw
    assert json.loads(raw)["measures"]["navicular_height_mm"] == 18.0
    assert call(f"{base}/picks/1", "PUT", {"landmarks": {"elbow": [0, 0, 0]}})[0] == 400

    st, raw, h = call(f"{op}/api/measurements.csv")
    assert st == 200 and "attachment" in h["Content-Disposition"]
    lines = raw.decode().strip().splitlines()
    assert lines[0].startswith("foot,condition,source") and any(",navicular_height_mm,18.0," in ln for ln in lines)
    assert call(f"{phone}/api/measurements.csv")[0] == 403

    assert body(call(f"{base}/picks/1", "DELETE"))["ok"]
    assert body(call(f"{base}/picks"))["picks"] == []


def test_landmarks_are_only_for_feet(servers):
    op, _, _ = servers
    cid = make_capture(op, condition="calibration")
    assert call(f"{op}/api/captures/{cid}/picks")[0] == 400


# --------------------------------------------------------------------------
# Other web sites can't act as the operator
# --------------------------------------------------------------------------
def test_dns_rebinding_host_is_not_the_operator(servers):
    op, _, _ = servers  # this server treats the socket as local...
    # ...but a page on evil.example rebinding its name to 127.0.0.1 sends its own Host
    assert call(f"{op}/api/submissions", headers={"Host": "evil.example:8765"})[0] == 403
    st, raw, _ = call(f"{op}/studio/index.html", headers={"Host": "evil.example"})
    assert b"Studio locked" in raw
    assert call(f"{op}/api/submissions", headers={"Host": "localhost"})[0] == 200


def test_cross_site_changes_are_refused(servers):
    op, _, data = servers
    cid = make_capture(op)
    host = op.split("//")[1]
    assert call(f"{op}/api/captures/{cid}/calipers", "PUT", {"length": 150},
                headers={"Origin": "https://evil.example"})[0] == 403
    assert call(f"{op}/api/captures/{cid}/calipers", "PUT", {"length": 150},
                headers={"Origin": f"http://{host}"})[0] == 200


def test_studio_pages_locked_however_spelt(servers):
    _, phone, _ = servers
    for path in ("/STUDIO/index.html", "/Studio/", "/assets/../studio/index.html"):
        st, raw, _ = call(f"{phone}{path}")
        assert b"Studio locked" in raw or st == 404, path


def test_wrong_shaped_input_gets_an_answer(servers):
    op, _, _ = servers
    cid = make_capture(op)
    st, raw, _ = call(f"{op}/api/captures/{cid}/calipers", "PUT", {"length": [1, 2]})
    assert st == 400 and b"invalid input" in raw


def test_public_server_hides_from_search_engines(tmp_path):
    handler = make_handler(WEB_DIR, tmp_path, local_check=lambda h: False, studio_key=KEY, allow_indexing=False)
    httpd = StudioServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        st, raw, h = call(f"{url}/robots.txt")
        assert st == 200 and b"Disallow: /\n" in raw
        st, _, h = call(f"{url}/")
        assert h["X-Robots-Tag"] == "noindex, nofollow"
    finally:
        httpd.shutdown()


def test_studio_path_check_is_part_based(servers):
    """Compare whole path parts: /studio-old/ is not inside /studio/ (and Windows paths use backslashes)."""
    _, phone, _ = servers
    st, raw, _ = call(f"{phone}/studio-old/x.html")
    assert st == 404 and b"Studio locked" not in raw


# ---- pairing the iPhone app ----------------------------------------------------

def test_pairing_code_is_studio_only_and_explains_when_phones_cant_connect(servers):
    op, phone, _ = servers
    assert call(f"{phone}/api/studio/pairing")[0] == 403          # a phone without the key gets nothing
    p = body(call(f"{op}/api/studio/pairing"))                     # this test server: http on 127.0.0.1
    assert p["available"] is False and "--host 0.0.0.0 --https" in p["reason"]
    assert "key" not in p


def test_pairing_through_the_public_address_uses_it_and_needs_no_fingerprint(tmp_path):
    handler = make_handler(WEB_DIR, tmp_path, local_check=lambda h: False, studio_key=KEY, public=True)
    httpd = StudioServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert call(f"{url}/api/studio/pairing")[0] == 403
        p = body(call(f"{url}/api/studio/pairing", headers={"X-Studio-Key": KEY, "Host": "footscan.example.dev"}))
        assert p == {"available": True, "url": "https://footscan.example.dev", "key": KEY, "fingerprint": None,
                     "note": PUBLIC_PAIRING_NOTE}  # the App Store build won't take it: said where the code is shown
    finally:
        httpd.shutdown()


def test_the_studio_knows_the_apps_own_network_rule():
    """The same rule as the app's StudioStore.isOwnNetwork, so the studio can say when the App Store build
    will refuse the code it shows (a computer given a public address, on a campus network say)."""
    from footscan.server import own_network

    for own in ("192.168.11.233", "10.0.0.5", "172.20.1.1", "169.254.3.4", "100.113.53.83", "mac-mini.local",
                "mac.local.", "[fd7a:115c:a1e0::1]", "fe90::1", "::ffff:192.168.1.5"):
        assert own_network(own), own
    for other in ("172.32.0.1", "100.128.0.1", "128.32.10.1", "footscan.example.dev", "mac.tail1234.ts.net",
                  "2001:db8::1", "fe7f::1", "fd::1"):  # fd::1 is 00fd::1, not unique-local
        assert not own_network(other), other


def test_a_lan_pairing_code_at_an_address_the_app_store_build_refuses_says_so(tmp_path, monkeypatch):
    from footscan import server

    handler = make_handler(WEB_DIR, tmp_path, studio_key=KEY, cert_fingerprint="ab" * 32)
    monkeypatch.setattr(handler, "other_addresses", lambda self, url: [])
    monkeypatch.setattr(handler, "studio_info", lambda self: {"phones_can_connect": True,
                                                              "scan_url": "https://128.32.10.1:8766/"})
    p = handler.pairing(object.__new__(handler))
    assert p["url"] == "https://128.32.10.1:8766" and p["note"] == server.OWN_NETWORK_NOTE
    monkeypatch.setattr(handler, "studio_info", lambda self: {"phones_can_connect": True,
                                                              "scan_url": "https://192.168.11.233:8766/"})
    assert "note" not in handler.pairing(object.__new__(handler))


def _phone_ready_studio(tmp_path, monkeypatch, tailnet):
    """A studio as the tank runs it (every address, HTTPS, a pinned certificate), on a home network."""
    import footscan.server as srv

    monkeypatch.setattr(srv, "lan_ip", lambda: "192.168.11.233")
    monkeypatch.setattr(srv, "tailnet_ip", lambda: tailnet)
    handler = make_handler(WEB_DIR, tmp_path, local_check=lambda h: False, studio_key=KEY, secure_cookie=True,
                           cert_fingerprint="ab" * 32)
    httpd = StudioServer(("127.0.0.1", 0), handler)  # listening on this computer only, while the tests run
    port = httpd.server_address[1]
    httpd.server_address = ("0.0.0.0", port)  # but answering as a studio bound to every address, as tank's is
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}"


def test_pairing_offers_the_tailscale_address_too_so_the_phone_reaches_the_studio_away_from_home(tmp_path, monkeypatch):
    httpd, url = _phone_ready_studio(tmp_path, monkeypatch, tailnet="100.101.102.103")
    port = httpd.server_address[1]
    try:
        p = body(call(f"{url}/api/studio/pairing", headers={"X-Studio-Key": KEY}))
        assert p["available"] is True and p["fingerprint"] == "ab" * 32
        assert p["url"] == f"https://192.168.11.233:{port}"                 # home Wi-Fi first, as before
        assert p["alt_urls"] == [f"https://100.101.102.103:{port}"]         # same port, same pinned certificate
    finally:
        httpd.shutdown()


def test_pairing_without_tailscale_offers_only_the_home_network_address(tmp_path, monkeypatch):
    httpd, url = _phone_ready_studio(tmp_path, monkeypatch, tailnet=None)
    try:
        p = body(call(f"{url}/api/studio/pairing", headers={"X-Studio-Key": KEY}))
        assert p["available"] is True and p["alt_urls"] == []
    finally:
        httpd.shutdown()


def test_pairing_with_no_wifi_address_offers_the_tailscale_one_instead_of_failing(tmp_path, monkeypatch):
    """Reachable only over Tailscale (no Wi-Fi address): the connect code names the Tailscale address. With
    neither, the page says so, instead of answering 500."""
    import footscan.server as srv

    httpd, url = _phone_ready_studio(tmp_path, monkeypatch, tailnet="100.101.102.103")
    monkeypatch.setattr(srv, "lan_ip", lambda: None)
    port = httpd.server_address[1]
    try:
        p = body(call(f"{url}/api/studio/pairing", headers={"X-Studio-Key": KEY}))
        assert p["available"] is True and p["url"] == f"https://100.101.102.103:{port}" and p["alt_urls"] == []
    finally:
        httpd.shutdown()
    httpd, url = _phone_ready_studio(tmp_path, monkeypatch, tailnet=None)
    monkeypatch.setattr(srv, "lan_ip", lambda: None)
    try:
        st, raw, _ = call(f"{url}/api/studio/pairing", headers={"X-Studio-Key": KEY})
        assert st == 200 and json.loads(raw)["available"] is False and "no network address" in json.loads(raw)["reason"]
    finally:
        httpd.shutdown()


def test_the_tailscale_address_is_asked_for_at_most_once_a_minute(tmp_path, monkeypatch):
    """Each Show the connect code asks for it; a stuck tailscaled costs 3 s a try."""
    import footscan.server as srv

    asked = []
    httpd, url = _phone_ready_studio(tmp_path, monkeypatch, tailnet=None)
    monkeypatch.setattr(srv, "tailnet_ip", lambda: asked.append(1) or "100.101.102.103")
    try:
        for _ in range(3):
            assert body(call(f"{url}/api/studio/pairing", headers={"X-Studio-Key": KEY}))["alt_urls"]
    finally:
        httpd.shutdown()
    assert len(asked) == 1


def test_tailnet_address_is_read_from_the_tailscale_command(monkeypatch, tmp_path):
    import subprocess

    import footscan.server as srv

    exe = tmp_path / "tailscale"
    exe.write_text("")
    monkeypatch.setattr(srv.shutil, "which", lambda name: str(exe))
    monkeypatch.setattr(srv.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "100.88.1.2\n", ""))
    assert srv.tailnet_ip() == "100.88.1.2"


def test_tailnet_address_is_found_through_the_mac_app_when_the_command_isnt_on_path(monkeypatch):
    import subprocess

    import footscan.server as srv

    mac_cli = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    ran = []
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    monkeypatch.setattr(srv.Path, "is_file", lambda self: self == Path(mac_cli))  # Path, not str: works on Windows

    def run(cmd, **kw):
        ran.append(cmd[0])
        return subprocess.CompletedProcess(cmd, 0, "100.88.1.2\n", "")

    monkeypatch.setattr(srv.subprocess, "run", run)
    assert srv.tailnet_ip() == "100.88.1.2" and ran == [mac_cli]


def test_a_stopped_tailscale_means_no_tailnet_address(monkeypatch, tmp_path):
    """Tailscale stopped: its command runs and gives no address, and that is the answer. (The computer's own
    addresses aren't looked at: a 100.64.0.0/10 one then is someone else's, such as Cloudflare WARP's. On
    Windows, neither is Tailscale's adapter, below.)"""
    import subprocess

    import footscan.server as srv

    monkeypatch.setattr(srv, "ON_WINDOWS", True)

    exe = tmp_path / "tailscale"
    exe.write_text("")
    monkeypatch.setattr(srv.shutil, "which", lambda name: str(exe))
    monkeypatch.setattr(srv.Path, "is_file", lambda self: self == exe)  # not this computer's own Tailscale
    ran = []
    monkeypatch.setattr(srv.subprocess, "run", lambda cmd, **k: ran.append(cmd[0]) or subprocess.CompletedProcess(
        cmd, 1, "", "Tailscale is stopped.\n"))
    assert srv.tailnet_ip() is None and ran == [str(exe)]  # it said so: the adapter isn't read
    monkeypatch.setattr(srv.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 0, "" if cmd[0] == str(exe) else "100.88.1.2", "Logged out.\n" if cmd[0] == str(exe) else ""))
    assert srv.tailnet_ip() is None
    # with no tailscale command anywhere (WARP on, Tailscale not installed), still none
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    monkeypatch.setattr(srv.Path, "is_file", lambda self: False)
    assert srv.tailnet_ip() is None


def test_the_windows_service_finds_its_tailscale_address_on_tailscales_adapter(monkeypatch):
    """On tank the studio runs as Local Service, and `tailscale ip -4` gave that account no address (6 Nov 2026,
    "Run unattended" on too), so the connect code had only the home address. The "Tailscale" adapter has it."""
    import ntpath
    import subprocess

    import footscan.server as srv

    win = r"C:\Program Files\Tailscale\tailscale.exe"
    ran = []
    monkeypatch.setattr(srv, "ON_WINDOWS", True)
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    monkeypatch.setattr(srv.Path, "is_file", lambda self: self == Path(win))

    def run(cmd, **kw):
        ran.append("tailscale" if cmd[0] == win else ntpath.basename(cmd[0]))
        if cmd[0] == win:  # what the service got: no address
            return subprocess.CompletedProcess(cmd, 1, "", "")
        assert cmd[-1] == srv.WINDOWS_TAILSCALE_ADAPTER
        # only Tailscale's own adapter, and only while it is up (a 100.x address elsewhere isn't Tailscale's)
        assert "-Name Tailscale " in cmd[-1] and "$a.Status -eq 'Up'" in cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, "100.113.53.83\r\n", "")

    monkeypatch.setattr(srv.subprocess, "run", run)
    assert srv.tailnet_ip() == "100.113.53.83" and ran == ["tailscale", "powershell.exe"]


def test_the_tailscale_adapter_is_read_only_on_windows_with_tailscale_installed(monkeypatch, tmp_path):
    """Without Tailscale (Cloudflare WARP's 100.64/10 address, say) nothing is read, and an answer outside
    Tailscale's range from the adapter doesn't count."""
    import subprocess

    import footscan.server as srv

    ran = []
    monkeypatch.setattr(srv.subprocess, "run",
                        lambda cmd, **k: ran.append(cmd[0]) or subprocess.CompletedProcess(cmd, 0, "100.64.0.9\n", ""))
    monkeypatch.setattr(srv, "ON_WINDOWS", True)
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    monkeypatch.setattr(srv.Path, "is_file", lambda self: False)
    assert srv.tailnet_ip() is None and ran == []  # not installed: PowerShell never runs

    exe = tmp_path / "tailscale"
    exe.write_text("")
    monkeypatch.setattr(srv.shutil, "which", lambda name: str(exe))
    monkeypatch.setattr(srv.Path, "is_file", lambda self: self == exe)
    monkeypatch.setattr(srv.subprocess, "run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "" if cmd[0] == str(exe) else "169.254.3.4", ""))
    assert srv.tailnet_ip() is None
    monkeypatch.setattr(srv, "ON_WINDOWS", False)  # the Mac and Linux: only the command's answer
    monkeypatch.setattr(srv.subprocess, "run", lambda cmd, **k: ran.append(cmd[0]) or subprocess.CompletedProcess(cmd, 1, "", ""))
    assert srv.tailnet_ip() is None and ran == [str(exe)]


def test_a_stuck_tailscaled_on_windows_still_leaves_the_adapter_to_read(monkeypatch):
    """Reading the adapter doesn't ask tailscaled, so a command that times out (the service's own access to it
    stalling, say) doesn't cost the connect code its Tailscale address."""
    import subprocess

    import footscan.server as srv

    win = r"C:\Program Files\Tailscale\tailscale.exe"
    monkeypatch.setattr(srv, "ON_WINDOWS", True)
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    monkeypatch.setattr(srv.Path, "is_file", lambda self: self == Path(win))

    def run(cmd, **kw):
        if cmd[0] == win:
            raise subprocess.TimeoutExpired(cmd, 3)
        return subprocess.CompletedProcess(cmd, 0, "100.113.53.83\n", "")

    monkeypatch.setattr(srv.subprocess, "run", run)
    assert srv.tailnet_ip() == "100.113.53.83"


def test_powershell_is_never_run_from_a_relative_path(monkeypatch):
    """An empty or relative SystemRoot in the service's environment would run powershell.exe from the service's
    own folder, which its owner can change."""
    import subprocess

    import footscan.server as srv

    ran = []
    monkeypatch.setattr(srv.subprocess, "run", lambda cmd, **k: ran.append(cmd[0]) or subprocess.CompletedProcess(
        cmd, 0, "100.88.1.2", ""))
    for root in ("", "Windows", r"\Users\Public", "C:", r"D:\Win"):
        monkeypatch.setenv("SystemRoot", root)
        assert srv.windows_tailscale_adapter_ip() == "100.88.1.2"
    assert ran == [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"] * 4 + [
        r"D:\Win\System32\WindowsPowerShell\v1.0\powershell.exe"]


def test_the_tailscale_command_runs_once_when_path_finds_an_install_location(monkeypatch):
    """which() on tank finds C:\\Program Files\\Tailscale\\tailscale.exe, which is also on the fixed list: a stuck
    tailscaled would cost 3 s twice on every pairing request if it ran twice."""
    import subprocess

    import footscan.server as srv

    win = r"C:\Program Files\Tailscale\tailscale.exe"
    monkeypatch.setattr(srv, "ON_WINDOWS", False)  # the command only (Windows reads the adapter after)
    ran = []
    monkeypatch.setattr(srv.shutil, "which", lambda name: win)
    monkeypatch.setattr(srv.Path, "is_file", lambda self: self == Path(win))

    def run(cmd, **kw):
        ran.append(cmd[0])
        raise subprocess.TimeoutExpired(cmd, 3)

    monkeypatch.setattr(srv.subprocess, "run", run)
    assert srv.tailnet_ip() is None and ran == [win]


def test_a_stuck_tailscaled_is_waited_on_once_not_once_per_program(monkeypatch):
    """The Mac's command-line tailscale is a script, not a link to the app's program, so both are on the list;
    when the first times out, the second would only wait on the same stuck tailscaled."""
    import subprocess

    import footscan.server as srv

    mac_cli, wrapper = "/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/usr/local/bin/tailscale"
    monkeypatch.setattr(srv, "ON_WINDOWS", False)  # the command only (Windows reads the adapter after)
    ran = []
    monkeypatch.setattr(srv.shutil, "which", lambda name: wrapper)
    monkeypatch.setattr(srv.Path, "is_file", lambda self: self in (Path(mac_cli), Path(wrapper)))

    def run(cmd, **kw):
        ran.append(cmd[0])
        raise subprocess.TimeoutExpired(cmd, 3)

    monkeypatch.setattr(srv.subprocess, "run", run)
    assert srv.tailnet_ip() is None and ran == [wrapper]


def test_a_tailscale_exit_node_doesnt_hide_the_home_network_address(monkeypatch):
    """With an exit node (or a subnet route over 10/8) the route toward a private address goes through
    Tailscale, so the connect code's home address would be the Tailscale one and the phone at home without
    Tailscale couldn't reach the studio. The computer's own private address is used instead."""
    import socket

    import footscan.server as srv

    class Routed:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def connect(self, addr):
            pass

        def getsockname(self):
            return ("100.113.53.83", 50000)

    monkeypatch.setattr(srv.socket, "socket", Routed)
    monkeypatch.setattr(srv.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, 0, 0, "", ("100.113.53.83", 0)), (socket.AF_INET, 0, 0, "", ("127.0.0.1", 0)),
        (socket.AF_INET, 0, 0, "", ("192.168.11.233", 0))])
    assert srv.lan_ip() == "192.168.11.233"
    monkeypatch.setattr(srv.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", ("100.113.53.83", 0))])
    assert srv.lan_ip() is None  # only the Tailscale address: no home address to offer


def test_no_tailscale_address_is_asked_again_after_ten_seconds_not_a_minute(monkeypatch):
    """A service started at boot may ask before Tailscale is up; that "none" mustn't stand for a minute."""
    import time

    import footscan.server as srv

    answers = iter([None, "100.88.1.2"])
    monkeypatch.setattr(srv, "tailnet_ip", lambda: next(answers))
    cached = srv.make_handler().tailnet_cached
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now)
    assert cached() is None
    monkeypatch.setattr(time, "monotonic", lambda: now + srv.TAILNET_RETRY_S + 1)
    assert cached() == "100.88.1.2"


def test_only_addresses_in_tailscales_range_count_as_tailnet():
    from footscan.server import first_tailnet_ip

    assert first_tailnet_ip(["192.168.11.233", "100.63.255.255", "100.128.0.1", "fd7a:115c:a1e0::1"]) is None
    assert first_tailnet_ip(["192.168.11.233", "not an ip", "100.64.0.1", "100.100.1.1"]) == "100.64.0.1"


def test_certificate_fingerprint_is_the_sha256_of_the_certificate(tmp_path):
    import hashlib
    import ssl

    from footscan.server import cert_fingerprint, ensure_cert

    cert, _ = ensure_cert(tmp_path)
    fp = cert_fingerprint(cert)
    assert fp == hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest() and len(fp) == 64


# ---- first-fit insole from the studio ------------------------------------------

def _object_capture_foot(foot="right"):
    """A synthetic foot (with leg) as the iPhone app would export it: metres, Y up, turned."""
    import numpy as np
    import trimesh

    import synth
    from footscan.recon import imported

    m = synth.block_foot(0.0, foot, origin=(0, 0))
    T = np.eye(4)
    c, s = np.cos(np.radians(63)), np.sin(np.radians(63))
    T[:2, :2] = [[c, -s], [s, c]]
    m.apply_transform(T)
    m.apply_transform(np.block([[imported.UP["y"].T, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.apply_scale(0.001)
    return m.export(file_type="obj").encode()


def test_studio_makes_a_first_fit_insole_from_an_imported_foot(servers):
    op, phone, _ = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "left", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("left"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    assert call(f"{phone}/api/captures/{cid}/insole", "POST", {})[0] == 403  # studio only
    # the block foot is a rectangle, square toes and all: the foot's own outline, so the whole sole is on it
    st, raw, _ = call(f"{op}/api/captures/{cid}/insole", "POST", {"foot_outline": True})
    assert st == 200, raw
    r = json.loads(raw)
    assert r["foot"] == "left" and r["max_fill_mm"] == pytest.approx(11.0, abs=0.6) and r["warnings"] == []
    for name in ("insole.3mf", "summary.html", "print-notes.txt", "insole.stl"):
        st, data, h = call(f"{op}/api/captures/{cid}/insole/{name}")
        assert st == 200 and len(data) > 100, name
    assert b"NOT A MEDICAL DEVICE" in call(f"{op}/api/captures/{cid}/insole/summary.html")[1]
    assert call(f"{op}/api/captures/{cid}/insole/../capture.json")[0] == 404
    listed = [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == cid][0]
    assert listed["insole"]["max_fill_mm"] == r["max_fill_mm"]


def test_studio_makes_an_insole_from_a_foam_print_without_a_scale_reading(servers):
    """The app sends a foam print as condition swb, scan_kind impression, no load: Make insole reads it as a print."""
    import numpy as np

    import synth
    from footscan.recon import imported

    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "method": "imported_mesh", "scan_kind": "impression"}))["id"]
    assert json.loads((data / "captures" / cid / "capture.json").read_text())["scan_kind"] == "impression"
    m = synth.foam_print("right")
    m.apply_transform(np.block([[imported.UP["y"].T, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.apply_scale(0.001)
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", m.export(file_type="obj").encode(),
                {"Content-Type": "application/octet-stream"})[0] == 200
    st, raw, _ = call(f"{op}/api/captures/{cid}/insole", "POST", {})
    assert st == 200, raw
    r = json.loads(raw)
    assert r["max_fill_mm"] == pytest.approx(11.0, abs=0.1) and r["outline_shape"] == "generic"
    assert [w for w in r["warnings"] if "wider than the generic insole outline" not in w] == []
    assert b"foam print" in call(f"{op}/api/captures/{cid}/insole/summary.html")[1]
    for name in ("insole-preview.bin", "insole-preview-sole.bin"):  # the studio's 3-D preview
        st, data, _ = call(f"{op}/api/captures/{cid}/insole/{name}")
        assert st == 200 and data[:4] == b"FSV1", name
    # a standing foot still needs the scale reading; kinds are checked
    assert call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "S1",
                                               "scan_kind": "foot"})[0] == 400
    assert call(f"{op}/api/captures", "POST", {"condition": "nwb_relaxed", "foot": "right", "session": "S1",
                                               "scan_kind": "sideways"})[0] == 400
    assert call(f"{op}/api/captures", "POST", {"condition": "object", "session": "S1",
                                               "scan_kind": "sole_up"})[0] == 400


def test_studio_insole_needs_a_foot(servers):
    op, _, _ = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "object", "session": "L1", "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 400


def test_two_insole_builds_at_once_both_succeed_and_leave_one_clean_result(servers):
    """Two studio tabs pressing Make insole together: no half-written or lost files."""
    from concurrent.futures import ThreadPoolExecutor

    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
         {"Content-Type": "application/octet-stream"})
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: call(f"{op}/api/captures/{cid}/insole", "POST", {}), range(2)))
    assert [r[0] for r in results] == [200, 200]
    assert all("error" not in json.loads(r[1]) for r in results)
    folder = data / "captures" / cid
    assert sorted(p.name for p in folder.iterdir() if p.name.startswith("insole")) == ["insole"]  # no leftovers
    assert {p.name for p in (folder / "insole").iterdir()} >= {"insole.3mf", "summary.html", "print-notes.txt"}


def test_an_insole_goes_stale_when_its_model_changes(servers, tmp_path):
    """Never offer an insole made from a model that has since been replaced or rebuilt."""
    import os
    import time

    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    put = lambda: call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
                       {"Content-Type": "application/octet-stream"})
    put()
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 200

    # the model file changes underneath (e.g. rebuilt): marked stale, downloads refused
    mesh = data / "captures" / cid / "mesh.ply"
    later = time.time() + 5
    os.utime(mesh, (later, later))
    listed = [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == cid][0]
    assert listed["insole"].get("stale") is True
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 409

    # making it again clears that
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 200

    # a new import removes the old insole altogether
    put()
    listed = [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == cid][0]
    assert "insole" not in listed and not (data / "captures" / cid / "insole").exists()


def test_a_failed_insole_rebuild_leaves_nothing_downloadable(servers):
    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
         {"Content-Type": "application/octet-stream"})
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    # the model file is replaced by one that can't be read (e.g. a rebuild that died half-written)
    (data / "captures" / cid / "mesh.ply").write_bytes(b"ply\nformat ascii 1.0\nelement vertex 3\nend_header\n")
    r = body(call(f"{op}/api/captures/{cid}/insole", "POST", {}))
    assert "error" in r
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 409
    assert not (data / "captures" / cid / "insole").exists()


def test_a_failed_save_counts_as_a_failed_build(servers, monkeypatch):
    """If writing the files fails (disk full), the old insole must not stay on offer as if current."""
    from footscan import insole as insole_mod

    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
         {"Content-Type": "application/octet-stream"})
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200

    def full_disk(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(insole_mod, "write_outputs", full_disk)
    r = body(call(f"{op}/api/captures/{cid}/insole", "POST", {}))
    assert "No space left" in r["error"]
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 409
    assert not [p for p in (data / "captures" / cid).iterdir() if p.name.startswith("insole")]


def test_make_insole_can_lengthen_to_a_shoe(servers):
    """POST {length_mm}: the generic insole outline at the shoe's length (scaled as a whole); with
    {foot_outline: true} too, the foot's own outline lengthened at the front; nonsense lengths are refused."""
    op, _, _ = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    st, raw, _ = call(f"{op}/api/captures/{cid}/insole", "POST", {"length_mm": 275})
    assert st == 200, raw
    r = json.loads(raw)
    # a length alone: the generic outline at that length, recorded as no outline chosen (a default saved later
    # takes over); asked for by name, recorded as chosen
    assert r["shoe_length_mm"] == 275 and r["outline"] == "default" and r["outline_shape"] == "generic"
    assert r["generic"]["length_mm"] == pytest.approx(275, abs=0.1) and r["shoe"] is None
    assert r["length_mm"] == pytest.approx(275, abs=6)  # along the foot: the outline may be turned a few degrees
    assert not any("lengthened to" in w for w in r["warnings"])
    named = body(call(f"{op}/api/captures/{cid}/insole", "POST", {"length_mm": 275, "generic": True}))
    assert named["outline"] == "generic" and named["generic"]["length_mm"] == r["generic"]["length_mm"]
    own = body(call(f"{op}/api/captures/{cid}/insole", "POST", {"length_mm": 275, "foot_outline": True}))
    assert own["length_mm"] == pytest.approx(275, abs=0.6) and own["outline"] == "foot" and own["generic"] is None
    assert any("lengthened to 275 mm" in w for w in own["warnings"])
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {"length_mm": 9})[0] == 400
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {"length_mm": "nine"})[0] == 400


def test_make_insole_can_fit_to_a_scanned_shoes_insole(servers):
    """POST {shoe}: the insole takes that shoe's-insole capture's outline; a shoe and a length together, or a
    capture that isn't a shoe's insole, are refused; a changed shoe scan makes the insole stale."""
    import os
    import time

    import synth

    op, _, data = servers
    foot = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                     "load_kg": 30, "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{foot}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    st, raw, _ = call(f"{op}/api/captures", "POST", {"condition": "shoe_insole", "session": "LIDAR",
                                                     "method": "imported_mesh", "notes": "trainers"})
    assert st in (200, 201), raw
    shoe = json.loads(raw)["id"]
    assert call(f"{op}/api/captures/{shoe}/mesh?ext=obj&up=y", "PUT",
                synth.shoe_insole().export(file_type="obj").encode(), {"Content-Type": "application/octet-stream"})[0] == 200

    st, raw, _ = call(f"{op}/api/captures/{foot}/insole", "POST", {"shoe": shoe})
    assert st == 200, raw
    r = json.loads(raw)
    assert "error" not in r, r
    assert r["length_mm"] == pytest.approx(271, abs=2) and r["shoe"]["capture"] == shoe
    assert r["shoe"]["fit"]["shoe_length_mm"] == pytest.approx(271, abs=2)
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"shoe": shoe, "length_mm": 280})[0] == 400
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"shoe": foot})[0] == 400  # not a shoe's insole
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"shoe": "../x"})[0] == 400

    # the shoe's scan changes underneath: the insole fitted to it is stale, downloads refused
    assert call(f"{op}/api/captures/{foot}/insole/insole.3mf")[0] == 200
    mesh = data / "captures" / shoe / "mesh.ply"
    later = time.time() + 5
    os.utime(mesh, (later, later))
    listed = [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == foot][0]
    assert listed["insole"].get("stale") is True
    assert call(f"{op}/api/captures/{foot}/insole/insole.3mf")[0] == 409


def test_a_default_the_studio_cant_write_answers_with_why(servers, monkeypatch):
    """data/shoes not writable or the disk full: a JSON answer naming the folder, as a failed save gets."""
    from footscan import shoes

    op, _phone, _data = servers

    def full(folder, sid):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shoes, "set_default", full)
    st, raw, _ = call(f"{op}/api/shoes/default", "POST", {"id": None})
    assert st == 500 and "couldn't choose the default" in json.loads(raw)["error"]


def test_a_saved_shoe_is_the_default_outline_for_every_new_insole(servers):
    """POST /api/shoes saves a shoe's-insole capture as a saved shoe (one outline per shoe and size); made the
    default, POST insole {} takes its outline; {foot_outline: true} opts out; saving it again makes the insole
    stale; the phone can't reach any of it."""
    import time

    import synth

    op, phone, data = servers
    foot = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                     "load_kg": 30, "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{foot}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    shoe = body(call(f"{op}/api/captures", "POST", {"condition": "shoe_insole", "session": "LIDAR",
                                                    "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{shoe}/mesh?ext=obj&up=y", "PUT",
                synth.shoe_insole().export(file_type="obj").encode(), {"Content-Type": "application/octet-stream"})[0] == 200

    assert body(call(f"{op}/api/shoes")) == {"shoes": [], "default": None, "default_problem": None}
    plain = body(call(f"{op}/api/captures/{foot}/insole", "POST", {}))  # no saved shoe yet: the generic outline
    # recorded as "the default" (there was none), not as a choice of the foot's outline: once a default is
    # saved, this card's menu and Remake follow it instead of cutting the foot's outline again
    assert plain["shoe"] is None and plain["length_mm"] < 265 and plain["outline"] == "default"
    assert plain["outline_shape"] == "generic" and plain["generic"]["length_mm"] < 265  # sized from the foot

    new = {"capture": shoe, "name": "Test Trainer", "size": "US men's 9.5", "default": True}
    st, raw, _ = call(f"{op}/api/shoes", "POST", new)
    assert st == 201, raw
    s = json.loads(raw)
    assert s["id"] == "test-trainer-us-men-s-9-5" and s["length_mm"] == pytest.approx(271, abs=2) and "outline" not in s
    listed = body(call(f"{op}/api/shoes"))
    assert listed["default"] == s["id"] and [x["id"] for x in listed["shoes"]] == [s["id"]]
    assert call(f"{op}/api/shoes", "POST", {**new, "capture": foot})[0] == 400  # not a shoe's insole
    assert call(f"{op}/api/shoes", "POST", {**new, "name": " "})[0] == 400
    assert call(f"{phone}/api/shoes")[0] == 403

    r = body(call(f"{op}/api/captures/{foot}/insole", "POST", {}))  # nothing chosen: the default saved shoe
    assert r["shoe"]["saved"] == s["id"] and r["shoe"]["name"] == "Test Trainer, US men's 9.5"
    assert r["outline"] == "saved"
    assert r["length_mm"] == pytest.approx(271, abs=2)
    assert "Test Trainer" in call(f"{op}/api/captures/{foot}/insole/summary.html")[1].decode()
    generic = body(call(f"{op}/api/captures/{foot}/insole", "POST", {"generic": True}))  # chosen over the default
    assert generic["shoe"] is None and generic["outline"] == "generic" and generic["length_mm"] == plain["length_mm"]
    # a length alone passes the default saved shoe over for the generic outline at that length: recorded as that,
    # not as "default", or the menu would show the saved shoe and Remake would cut to it
    at_len = body(call(f"{op}/api/captures/{foot}/insole", "POST", {"length_mm": 275}))
    assert at_len["shoe"] is None and at_len["outline"] == "generic"
    assert at_len["generic"]["length_mm"] == pytest.approx(275, abs=0.5)
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"generic": True, "saved_shoe": s["id"]})[0] == 400
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"generic": True, "foot_outline": True})[0] == 400
    own = body(call(f"{op}/api/captures/{foot}/insole", "POST", {"foot_outline": True}))
    assert own["shoe"] is None and own["generic"] is None and own["outline"] == "foot" and own["outline_shape"] == "foot"
    # recorded, so the studio's menu shows "the foot's own" for this card after a reload, not the default shoe
    mine = [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == foot][0]
    assert mine["insole"]["outline"] == "foot"
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"saved_shoe": s["id"], "length_mm": 280})[0] == 400
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"saved_shoe": s["id"], "foot_outline": True})[0] == 400
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"saved_shoe": "no-such-shoe"})[0] == 400
    assert call(f"{op}/api/captures/{foot}/insole", "POST", {"saved_shoe": "../x"})[0] == 400

    # saved again (a better scan of the same shoe): an insole made from the old outline is stale
    assert body(call(f"{op}/api/captures/{foot}/insole", "POST", {"saved_shoe": s["id"]}))["shoe"]["saved"] == s["id"]
    time.sleep(0.01)
    assert call(f"{op}/api/shoes", "POST", new)[0] == 201
    listed = [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == foot][0]
    assert listed["insole"].get("stale") is True and listed["insole"]["stale_reason"] == "shoe"
    assert listed["insole"]["stale_message"] == STALE_MESSAGES["shoe"]  # the card's words, from one place
    st, raw, _ = call(f"{op}/api/captures/{foot}/insole/insole.3mf")
    assert st == 409 and "shoe" in json.loads(raw)["error"] and "3D model" not in json.loads(raw)["error"]

    # a capture.json naming something that isn't a saved shoe's id (edited by hand): that insole is stale, and
    # the studio's list still loads (it used to answer 500, an empty studio)
    cj = data / "captures" / foot / "capture.json"
    kept = cj.read_bytes()
    m = json.loads(kept)
    m["insole"]["shoe"]["saved"] = "../Not An Id"
    cj.write_text(json.dumps(m))
    st, raw, _ = call(f"{op}/api/captures")
    assert st == 200
    assert [c for c in json.loads(raw) if c["capture_id"] == foot][0]["insole"]["stale_reason"] == "shoe"
    cj.write_bytes(kept)

    # the default's file broken by hand: Make insole says so, rather than cutting to the foot's own outline
    good = (data / "shoes" / f"{s['id']}.json").read_bytes()
    (data / "shoes" / f"{s['id']}.json").write_text("<<<<<<< HEAD\n")
    st, raw, _ = call(f"{op}/api/captures/{foot}/insole", "POST", {})
    assert st == 400 and "default saved shoe can't be used" in json.loads(raw)["error"]
    assert "can't be used" in body(call(f"{op}/api/shoes"))["default_problem"]
    (data / "shoes" / f"{s['id']}.json").write_bytes(good)

    assert body(call(f"{op}/api/shoes/default", "POST", {"id": None})) == {"default": None}
    assert call(f"{op}/api/shoes/default", "POST", {"id": "no-such-shoe"})[0] == 400
    assert body(call(f"{op}/api/captures/{foot}/insole", "POST", {}))["shoe"] is None  # no default: the foot's
    (data / "captures" / shoe / "mesh.ply").write_bytes(b"ply\nnot a model")  # broken: an answer, not a dropped line
    st, raw, _ = call(f"{op}/api/shoes", "POST", new)
    assert st == 400 and "couldn't read" in json.loads(raw)["error"]


def test_saving_a_shoe_into_a_folder_that_cant_be_written_is_the_studios_fault_not_the_scans(servers, monkeypatch):
    """A save that fails on the studio's own disk (not writable, full) answers 500 naming the folder, not a 400
    that sends the user off to scan a good insole again."""
    import synth

    from footscan import shoes

    op, _, _ = servers
    shoe = body(call(f"{op}/api/captures", "POST", {"condition": "shoe_insole", "session": "LIDAR",
                                                    "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{shoe}/mesh?ext=obj&up=y", "PUT",
                synth.shoe_insole().export(file_type="obj").encode(), {"Content-Type": "application/octet-stream"})[0] == 200

    def refuse(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(shoes, "save", refuse)
    st, raw, _ = call(f"{op}/api/shoes", "POST", {"capture": shoe, "name": "Test Trainer", "size": "9.5"})
    assert st == 500
    err = json.loads(raw)["error"]
    assert "couldn't save the shoe" in err and "Permission denied" in err and "read the shoe's insole" not in err


def test_the_studio_compares_two_scans_of_the_same_foot(servers):
    """POST /api/compare {a, b}: two imports of the same synthetic foot agree closely; studio only."""
    op, phone, _ = servers
    ids = []
    for _ in range(2):
        cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "left", "session": "LIDAR",
                                                        "load_kg": 30, "method": "imported_mesh"}))["id"]
        assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("left"),
                    {"Content-Type": "application/octet-stream"})[0] == 200
        ids.append(cid)
    assert call(f"{phone}/api/compare", "POST", {"a": ids[0], "b": ids[1]})[0] == 403
    st, raw, _ = call(f"{op}/api/compare", "POST", {"a": ids[0], "b": ids[1]})
    assert st == 200, raw
    r = json.loads(raw)
    assert r["typical_mm"] < 0.1 and "agree within" in r["verdict"]
    assert call(f"{op}/api/compare", "POST", {"a": ids[0], "b": ids[0]})[0] == 400


# ---- a sole scan missing part of the foot is refused on arrival -----------------

def _sole_up_obj(foot="right", **cut):
    """A SYNTHETIC sole-up scan as the iPhone app exports it; ``cut`` (x_from, x_to) takes off an end."""
    import synth

    mesh = synth.shaped_foot(foot)
    if cut:
        mesh = synth.cut_ends(mesh, **cut)
    return synth.sole_up_capture(mesh).export(file_type="obj").encode()


def _new_sole_capture(op, foot):
    return body(call(f"{op}/api/captures", "POST", {"condition": "nwb_relaxed", "foot": foot, "session": "LIDAR",
                                                    "method": "imported_mesh", "scan_kind": "sole_up"}))["id"]


def test_a_sole_scan_without_its_toes_is_refused_and_not_kept(servers):
    op, phone, data = servers
    cid = _new_sole_capture(op, "left")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("left", x_to=200.0),
                      {"Content-Type": "application/octet-stream"})
    assert st == 422, raw
    r = json.loads(raw)
    assert r["incomplete"] and r["incomplete"][0].startswith("THE TOES ARE MISSING")
    assert r["error"].startswith("The studio didn't keep this scan") and "Scan again" in r["error"]
    # and what to change next time, one entry per line found, for the phone to show before the retake
    assert [a["code"] for a in r["retake"]] == ["toes_missing"] and r["retake"][0]["steps"]
    assert not (data / "captures" / cid).exists()
    assert cid not in [c["capture_id"] for c in body(call(f"{op}/api/captures"))]


def test_a_whole_sole_scan_is_kept_with_its_measures(servers):
    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                      {"Content-Type": "application/octet-stream"})
    assert st == 200, raw
    c = json.loads((data / "captures" / cid / "capture.json").read_text())["completeness"]
    assert c["problems"] == [] and c["measures"]["length_mm"] == pytest.approx(250.0, abs=3.0)


def test_a_refusal_gives_one_set_of_steps_per_kind_of_problem():
    """Shorter than both feet's scans is two lines but one thing to change: the phone shows its steps once."""
    from footscan.server import IncompleteScan

    lines = ["THIS FOOT IS 20 MM SHORTER than an earlier scan of the same foot (L1): ...",
             "THIS FOOT IS 18 MM SHORTER than your right foot's scan (R1): ...",
             "THE TOES ARE MISSING: ...", "SOMETHING NEW: a. Scan again.", "SOMETHING ELSE: b. Scan again."]
    e = IncompleteScan(lines)
    assert e.problems == lines
    assert [a["code"] for a in e.advice] == ["shorter_than_other", "toes_missing", "other", "other"]


def test_a_sole_scan_much_shorter_than_the_other_foot_is_refused(servers):
    """Both ends there, but 25 mm of the forefoot gone short of the toes' tip: only the other foot's scan shows it."""
    op, _, data = servers
    right = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{right}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    import synth

    # the left foot made 25 mm shorter by squeezing it, not cutting it: its ends keep their round shape
    short = synth.shaped_foot("left")
    short.apply_scale([225.0 / 250.0, 1.0, 1.0])
    left = _new_sole_capture(op, "left")
    st, raw, _ = call(f"{op}/api/captures/{left}/mesh?ext=obj&up=y", "PUT",
                      synth.sole_up_capture(short).export(file_type="obj").encode(),
                      {"Content-Type": "application/octet-stream"})
    assert st == 422, raw
    found = json.loads(raw)["incomplete"]
    assert len(found) == 1 and "SHORTER than your right foot's scan" in found[0] and right in found[0]


def test_a_scan_kept_before_the_check_is_measured_when_compared_and_an_incomplete_one_is_passed_over(servers):
    """Scans already in the studio have no measures: measured (and saved) the first time they're compared with.
    One that turns out incomplete itself isn't compared with."""
    op, _, data = servers
    old = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{old}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    meta_file = data / "captures" / old / "capture.json"
    meta = json.loads(meta_file.read_text())
    meta.pop("completeness")  # as if kept before this check existed
    meta_file.write_text(json.dumps(meta))
    from footscan import server

    found = server.other_scans(data / "captures", dict(capture_id="new", foot="left"))
    assert [o["capture_id"] for o in found] == [old] and not found[0]["same_foot"]
    assert json.loads(meta_file.read_text())["completeness"]["problems"] == []
    # the same scan, its saved check now saying it's incomplete: passed over
    meta = json.loads(meta_file.read_text())
    meta["completeness"]["problems"] = ["THE TOES ARE MISSING: ..."]
    meta_file.write_text(json.dumps(meta))
    assert server.other_scans(data / "captures", dict(capture_id="new", foot="left")) == []


def test_a_refused_model_sent_to_a_capture_that_had_one_leaves_the_earlier_model_and_its_insole(servers):
    """Replacing a kept scan's model with one missing its toes is refused, and only the new model is dropped:
    the capture, its model and the insole made from it are as they were (a new capture is still removed)."""
    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    folder = data / "captures" / cid
    model = ("mesh.ply", "original.obj", "viewer.bin")  # viewer.bin: what the landmark viewer draws
    before = {f: (folder / f).read_bytes() for f in model}
    meta_before = json.loads((folder / "capture.json").read_text())
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right", x_to=200.0),
                      {"Content-Type": "application/octet-stream"})
    assert st == 422 and json.loads(raw)["incomplete"], raw
    assert {f: (folder / f).read_bytes() for f in model} == before
    assert not [f for f in folder.iterdir() if f.name.startswith(".upload-")]
    assert json.loads((folder / "capture.json").read_text()) == meta_before
    assert (folder / "insole").is_dir() and meta_before.get("insole")


def test_a_refused_model_sent_to_a_capture_with_photos_but_no_model_keeps_the_capture(servers):
    """Only a capture made just for the upload (nothing in it but its capture.json) is removed when the model
    is refused: one holding photos, picks or a reconstruction keeps them."""
    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    folder = data / "captures" / cid
    (folder / "frame_0001.jpg").write_bytes(b"photo")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right", x_to=200.0),
                      {"Content-Type": "application/octet-stream"})
    assert st == 422, raw
    assert (folder / "frame_0001.jpg").read_bytes() == b"photo" and not (folder / "mesh.ply").exists()


def test_a_replacement_whose_check_breaks_leaves_the_earlier_model(servers, monkeypatch):
    """Anything going wrong while the new model is checked (here the check itself raising) leaves the earlier
    model where it was: the new one is only moved in once it's kept."""
    from footscan import server

    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    folder = data / "captures" / cid
    before = {f: (folder / f).read_bytes() for f in ("mesh.ply", "original.obj", "viewer.bin", "capture.json")}

    def broken(*a, **k):
        raise ValueError("the check broke")

    monkeypatch.setattr(server, "check_completeness", broken)
    st, _, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("left"),
                    {"Content-Type": "application/octet-stream"})
    assert st == 400
    assert {f: (folder / f).read_bytes() for f in before} == before
    assert not [f for f in folder.iterdir() if f.name.startswith(".upload-")]


def test_a_leftover_upload_folder_doesnt_stop_a_refused_new_capture_being_removed(servers):
    """A side folder left by an upload that died midway is cleared by the next upload, so a capture made just
    for a refused model is still removed (and the leftover copy of a foot's shape doesn't stay on disk)."""
    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    folder = data / "captures" / cid
    (folder / ".upload-dead0000").mkdir()
    (folder / ".upload-dead0000" / "mesh.ply").write_bytes(b"left over")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right", x_to=200.0),
                      {"Content-Type": "application/octet-stream"})
    assert st == 422, raw
    assert not folder.exists()


def test_what_another_request_saves_in_capture_json_during_an_upload_is_kept(servers, monkeypatch):
    """The upload re-reads capture.json before writing it, so calipers (or frames) saved while the new model
    was being checked aren't overwritten."""
    from footscan import server

    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    meta_file = data / "captures" / cid / "capture.json"
    check = server.check_completeness

    def meanwhile(*a, **k):
        m = json.loads(meta_file.read_text())
        m["calipers"] = {"note": "saved during the upload"}
        meta_file.write_text(json.dumps(m))
        return check(*a, **k)

    monkeypatch.setattr(server, "check_completeness", meanwhile)
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    saved = json.loads(meta_file.read_text())
    assert saved["calipers"] == {"note": "saved during the upload"} and saved["completeness"]["problems"] == []


def test_measures_of_a_model_replaced_while_it_was_measured_are_not_saved(servers, monkeypatch):
    """other_scans measures another capture without its lock: if a new model comes in meanwhile, what it
    measured belongs to the old one, so it isn't saved over the new model's."""
    from footscan import server

    op, _, data = servers
    old = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{old}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    folder = data / "captures" / old
    meta = json.loads((folder / "capture.json").read_text())
    meta.pop("completeness")
    (folder / "capture.json").write_text(json.dumps(meta))
    measure = server.scan_measures

    def replaced_meanwhile(f, m):
        out = measure(f, m)
        (f / "mesh.ply").write_bytes((f / "mesh.ply").read_bytes() + b"\n")  # a new model arrives
        return out

    monkeypatch.setattr(server, "scan_measures", replaced_meanwhile)
    server.other_scans(data / "captures", dict(capture_id="new", foot="left"))
    assert "completeness" not in json.loads((folder / "capture.json").read_text())


def test_two_refused_replacements_at_once_still_leave_the_earlier_model(servers, monkeypatch):
    """Two models sent to the same capture at the same moment, both refused: they take turns, so neither sets
    aside the other's copy of the earlier model, and the earlier model is there afterwards."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    from footscan import server

    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    folder = data / "captures" / cid
    mesh_before = (folder / "mesh.ply").read_bytes()
    check = server.check_completeness

    def slow_check(*a, **k):  # hold each upload between setting the old model aside and putting it back
        time.sleep(1.0)
        return check(*a, **k)

    monkeypatch.setattr(server, "check_completeness", slow_check)
    cut = _sole_up_obj("right", x_to=200.0)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", cut,
                                               {"Content-Type": "application/octet-stream"}), range(2)))
    assert [r[0] for r in results] == [422, 422], results
    assert (folder / "mesh.ply").read_bytes() == mesh_before


def test_a_kept_scan_that_cant_be_measured_is_tried_once_not_on_every_upload(servers, monkeypatch):
    """A kept sole scan whose measuring fails is left out of the comparison, and the failure is saved, so the
    next upload doesn't prepare it all over again inside the request."""
    op, _, data = servers
    old = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{old}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    meta_file = data / "captures" / old / "capture.json"
    meta = json.loads(meta_file.read_text())
    meta.pop("completeness")  # as if kept before this check existed
    meta_file.write_text(json.dumps(meta))
    from footscan import server

    tries = []

    def broken(folder, m):
        tries.append(folder)
        raise ValueError("no outline")

    monkeypatch.setattr(server, "scan_measures", broken)
    for _ in range(3):
        assert server.other_scans(data / "captures", dict(capture_id="new", foot="left")) == []
    assert len(tries) == 1
    assert "couldn't be measured" in json.loads(meta_file.read_text())["completeness"]["error"]


def test_a_scan_measured_the_old_way_is_measured_again_before_its_length_is_compared(servers):
    """Measures saved before the way of measuring changed (sole scans' toes now laid flat first) aren't
    compared with a new scan's: the scan is measured again and the new measures saved."""
    op, _, data = servers
    old = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{old}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    meta_file = data / "captures" / old / "capture.json"
    meta = json.loads(meta_file.read_text())
    fresh = meta["completeness"]["measures"]["length_mm"]
    meta["completeness"]["measures"]["length_mm"] = fresh - 20.0  # as an earlier version of the check read it
    del meta["completeness"]["measures"]["measured_as"]
    meta_file.write_text(json.dumps(meta))
    from footscan import server
    from footscan.recon import foot_prep

    found = server.other_scans(data / "captures", dict(capture_id="new", foot="left"))
    assert [o["length_mm"] for o in found] == [fresh]
    saved = json.loads(meta_file.read_text())["completeness"]["measures"]
    assert saved["measured_as"] == foot_prep.prep_version() and saved["length_mm"] == fresh


def test_a_sole_scans_insole_made_by_an_earlier_preparation_is_stale_until_made_again(servers):
    """A sole scan's insole made before the preparation changed (toes now laid flat: before, hung-up toes made
    the outline short) is marked stale and not offered for download; making it again clears that."""
    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 200

    meta_file = data / "captures" / cid / "capture.json"
    meta = json.loads(meta_file.read_text())
    del meta["insole"]["prep"]  # as an insole made before the preparation said how it was made
    meta_file.write_text(json.dumps(meta))
    listed = [c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == cid][0]
    assert listed["insole"].get("stale") is True
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 409

    assert call(f"{op}/api/captures/{cid}/insole", "POST", {})[0] == 200
    assert call(f"{op}/api/captures/{cid}/insole/insole.3mf")[0] == 200


def test_kinds_the_check_doesnt_read_are_kept_as_before(servers):
    """A foot standing on the floor (not a sole scan) isn't judged by the completeness check."""
    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": "right", "session": "LIDAR",
                                                    "load_kg": 30, "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    assert "completeness" not in json.loads((data / "captures" / cid / "capture.json").read_text())


# ---- Claude's look on arrival (second_look.py; Claude is a stand-in here) ---------------------------------------

@pytest.fixture
def looked_at(tmp_path):
    """A studio started with --check-scans-with-claude, whose Claude says what ``answer`` holds and notes each
    scan it was shown: (studio address, data dir, answer, what it was shown)."""
    answer = {"verdict": "keep", "problems": [], "looked_at": "A whole foot.", "model": "stand-in"}
    shown = []

    def look(placed, scanned, measures, info, kind):
        shown.append(dict(length_mm=measures["length_mm"], kind=kind, faces=len(placed.faces)))
        return dict(answer)

    handler = make_handler(WEB_DIR, tmp_path, local_check=lambda h: True, studio_key=KEY, second_look=look)
    httpd = StudioServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path, answer, shown
    httpd.shutdown()


def test_a_sole_scan_claude_keeps_is_kept_with_its_answer(looked_at):
    op, data, _, shown = looked_at
    cid = _new_sole_capture(op, "right")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                      {"Content-Type": "application/octet-stream"})
    assert st == 200, raw
    assert json.loads(raw)["second_look"]["verdict"] == "keep"          # the phone gets the answer too
    c = json.loads((data / "captures" / cid / "capture.json").read_text())["completeness"]
    assert c["problems"] == [] and c["second_look"]["looked_at"] == "A whole foot." and c["second_look"]["checked"]
    assert shown == [dict(length_mm=c["measures"]["length_mm"], kind="sole_up", faces=shown[0]["faces"])]
    logged = [json.loads(x) for x in (data / "second-looks.jsonl").read_text().splitlines()]
    assert [(x["capture_id"], x["refused"], x["second_look"]["verdict"]) for x in logged] == [(cid, False, "keep")]


def test_a_sole_scan_claude_asks_for_again_is_refused_with_the_studios_steps(looked_at):
    op, data, answer, _ = looked_at
    answer.update(verdict="scan_again", problems=[{"code": "guessed_surface",
                                                    "seen": "In picture 1 the heel is a smooth dome."}])
    cid = _new_sole_capture(op, "right")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                      {"Content-Type": "application/octet-stream"})
    assert st == 422, raw
    r = json.loads(raw)
    assert r["error"].startswith("The studio didn't keep this scan: Claude looked at pictures of it")
    assert r["incomplete"] == ["PARTS OF THE SOLE LOOK GUESSED: Claude looked at pictures of the scan and saw this: "
                               "In picture 1 the heel is a smooth dome. Scan again, following the steps."]
    assert [a["code"] for a in r["retake"]] == ["guessed_surface"] and r["retake"][0]["steps"]
    assert not (data / "captures" / cid).exists()                       # refused like the studio's own refusals
    logged = json.loads((data / "second-looks.jsonl").read_text().splitlines()[-1])
    assert logged["capture_id"] == cid and logged["refused"] is True     # kept in the log, to check later


def test_claude_is_not_asked_about_a_scan_the_studio_refuses_itself(looked_at):
    op, data, _, shown = looked_at
    cid = _new_sole_capture(op, "left")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("left", x_to=200.0),
                      {"Content-Type": "application/octet-stream"})
    assert st == 422 and json.loads(raw)["incomplete"][0].startswith("THE TOES ARE MISSING")
    assert shown == [] and not (data / "second-looks.jsonl").exists()


def test_no_answer_from_claude_keeps_the_scan_and_says_why(looked_at):
    op, data, answer, _ = looked_at
    answer.clear()
    answer["error"] = "Claude couldn't look at this scan: the studio's computer couldn't reach the API. It was kept."
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    c = json.loads((data / "captures" / cid / "capture.json").read_text())["completeness"]
    assert c["problems"] == [] and "couldn't reach the API" in c["second_look"]["error"]


def test_a_scan_sent_with_z_up_reaches_claude_y_up_like_one_sent_with_y_up(tmp_path):
    """second_look.pictures draws the model as it arrived assuming Y up: a Z-up file is turned to Y up first."""
    import trimesh

    shown = []

    def look(placed, scanned, measures, info, kind):
        shown.append(np.asarray(scanned.bounds))
        return {"verdict": "keep", "problems": [], "looked_at": "", "model": "stand-in"}

    handler = make_handler(WEB_DIR, tmp_path, local_check=lambda h: True, studio_key=KEY, second_look=look)
    httpd = StudioServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    op = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        y_up = trimesh.load(io.BytesIO(_sole_up_obj("right")), file_type="obj", process=False)
        z_up = y_up.copy()
        V = np.asarray(y_up.vertices)
        z_up.vertices = np.c_[V[:, 0], -V[:, 2], V[:, 1]]           # the same scan, written Z up
        for mesh, up in ((y_up, "y"), (z_up, "z")):
            cid = _new_sole_capture(op, "right")
            st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up={up}", "PUT",
                              mesh.export(file_type="obj").encode(), {"Content-Type": "application/octet-stream"})
            assert st == 200, raw
    finally:
        httpd.shutdown()
    assert len(shown) == 2 and np.allclose(shown[0], shown[1], atol=1e-3)


def test_a_scan_measured_again_keeps_what_claude_said_of_it(looked_at):
    op, data, _, _ = looked_at
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    f = data / "captures" / cid / "capture.json"
    meta = json.loads(f.read_text())
    meta["completeness"]["measures"]["measured_as"] = "an older preparation"   # measured again on the next upload
    f.write_text(json.dumps(meta))
    other = _new_sole_capture(op, "left")
    assert call(f"{op}/api/captures/{other}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("left"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    c = json.loads(f.read_text())["completeness"]
    assert c["measures"]["measured_as"] != "an older preparation"
    assert c["second_look"]["looked_at"] == "A whole foot."


def test_a_scan_measured_again_keeps_the_answer_saved_with_its_model_now_not_the_one_read_before(looked_at,
                                                                                                    monkeypatch):
    """The list of captures is read without the lock: what Claude said is taken from capture.json as it is under
    the lock, where it goes with the model just measured, never from that earlier read."""
    from footscan import server

    op, data, _, _ = looked_at
    cid = _new_sole_capture(op, "right")
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    f = data / "captures" / cid / "capture.json"
    meta = json.loads(f.read_text())
    meta["completeness"]["measures"]["measured_as"] = "an older preparation"
    f.write_text(json.dumps(meta))
    measure = server.scan_measures

    def meanwhile(folder, m):     # while it's measured, capture.json gets another answer (with its model)
        if folder.name == cid:
            saved = json.loads(f.read_text())
            saved["completeness"]["second_look"] = {"verdict": "keep", "problems": [], "looked_at": "Said later."}
            f.write_text(json.dumps(saved))
        return measure(folder, m)

    monkeypatch.setattr(server, "scan_measures", meanwhile)
    other = _new_sole_capture(op, "left")
    assert call(f"{op}/api/captures/{other}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("left"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    assert json.loads(f.read_text())["completeness"]["second_look"]["looked_at"] == "Said later."


def test_without_the_flag_no_scan_is_shown_to_claude(servers):
    op, _, data = servers
    cid = _new_sole_capture(op, "right")
    st, raw, _ = call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _sole_up_obj("right"),
                      {"Content-Type": "application/octet-stream"})
    assert st == 200 and json.loads(raw)["second_look"] is None
    assert "second_look" not in json.loads((data / "captures" / cid / "capture.json").read_text())["completeness"]
    assert not (data / "second-looks.jsonl").exists()


def test_a_refused_upload_still_gets_its_answer_when_the_body_is_large(servers):
    """A request refused before its body is read (here: too large) is answered and then the connection closes.
    Closing with the body still arriving makes the computer reset the connection, which can throw away the
    answer before the phone reads it (seen on Windows, test_imported_calibration_object_... under load);
    the server reads and drops what is still coming, within a limit, before it closes."""
    import socket

    op, _phone, _data = servers
    host, port = op.removeprefix("http://").split(":")
    body = b"x" * (6 * 1024 * 1024)  # over the 2 MB JSON limit, and more than the socket buffers hold
    sock = socket.create_connection((host, int(port)), timeout=10)
    head = (f"POST /api/captures HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode()
    errors = []

    def send():
        try:
            sock.sendall(head + body)
        except OSError as e:  # the server closed while the body was still coming: a reset
            errors.append(e)

    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    got = b""
    try:
        while chunk := sock.recv(65536):
            got += chunk
    finally:
        sender.join(10)
        sock.close()
    assert got.startswith(b"HTTP/1.1 400"), got[:200]
    assert b"body too large: " in got and b"MB, and this takes at most " in got  # how big, and the limit
    assert errors == []  # the whole body was taken in before the connection closed, so nothing was reset


def test_a_refused_chunked_upload_still_gets_its_answer(servers):
    """A chunked upload (Transfer-Encoding) is refused with 501 before its body is read; like any refused body,
    what's still coming is read and dropped before the connection closes, so the sender isn't reset and the
    answer isn't lost."""
    import socket

    op, _phone, _data = servers
    host, port = op.removeprefix("http://").split(":")
    piece = b"x" * 65536
    chunks = b"".join(b"%x\r\n%s\r\n" % (len(piece), piece) for _ in range(96)) + b"0\r\n\r\n"  # 6 MB
    sock = socket.create_connection((host, int(port)), timeout=10)
    head = (f"PUT /api/captures/x/mesh?ext=ply HTTP/1.1\r\nHost: {host}\r\n"
            "Transfer-Encoding: chunked\r\n\r\n").encode()
    errors = []

    def send():
        try:
            sock.sendall(head + chunks)
        except OSError as e:
            errors.append(e)

    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    got = b""
    try:
        while chunk := sock.recv(65536):
            got += chunk
    finally:
        sender.join(10)
        sock.close()
    assert got.startswith(b"HTTP/1.1 501"), got[:200]
    assert errors == []


def test_a_capture_removed_while_the_list_is_read_is_left_out(tmp_path, monkeypatch):
    """A refused phone upload removes its just-made capture; if that happens between the list's glob and its read,
    the list leaves it out instead of answering 404 for the whole list."""
    from footscan import server

    caps = tmp_path / "captures"
    for cid in ("kept", "gone"):
        (caps / cid).mkdir(parents=True)
        server.write_json(caps / cid / "capture.json", {"capture_id": cid, "created": "2026-11-05"})
    real = server.read_json

    def read(path):
        if path.parent.name == "gone":
            raise FileNotFoundError(path)
        return real(path)

    monkeypatch.setattr(server, "read_json", read)
    assert [m["capture_id"] for m in server.list_captures(caps)] == ["kept"]
    subs = tmp_path / "submissions"
    (subs / "gone").mkdir(parents=True)
    server.write_json(subs / "gone" / "submission.json", {"id": "gone"})
    assert server.list_submissions(subs) == []


def test_a_json_file_is_swapped_in_even_while_a_reader_briefly_holds_the_old_one(tmp_path, monkeypatch):
    """On Windows, replacing a file someone has open fails with PermissionError for as long as they hold it (the
    model page reads a build's status every 2 s). The swap is tried again for a moment instead of failing the
    write (and with it the build); a file held for good still fails, after the wait."""
    import os

    from footscan import atomic, server
    from footscan.recon import pipeline

    real, refusals = os.replace, []

    def held_for_a_moment(src, dst):
        if len(refusals) < 3:
            refusals.append(dst)
            raise PermissionError(13, "Access is denied", str(dst))
        return real(src, dst)

    monkeypatch.setattr(atomic.os, "replace", held_for_a_moment)
    monkeypatch.setattr(atomic, "RETRIES", True)  # as on Windows, wherever the test runs
    server.write_json(tmp_path / "capture.json", {"a": 1})
    assert server.read_json(tmp_path / "capture.json") == {"a": 1} and len(refusals) == 3
    refusals.clear()
    pipeline.write_json_atomic(tmp_path / "status.json", {"stage": "done"})
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8")) == {"stage": "done"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["capture.json", "status.json"]  # no temporary files left

    def held_for_good(src, dst):
        raise PermissionError(13, "Access is denied", str(dst))

    monkeypatch.setattr(atomic.os, "replace", held_for_good)
    monkeypatch.setattr(atomic, "RETRY_FOR_S", 0.05)
    with pytest.raises(PermissionError):
        atomic.replace(tmp_path / "x.tmp", tmp_path / "capture.json", retry_for_s=0.05)
    with pytest.raises(PermissionError):
        server.write_json(tmp_path / "capture.json", {"a": 2})
    assert server.read_json(tmp_path / "capture.json") == {"a": 1}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["capture.json", "status.json"]


def test_a_capture_whose_insole_cant_be_checked_is_listed_as_stale_not_left_out(tmp_path, monkeypatch):
    """Only a capture.json that can't be read is left out of the studio list. If what the insole was made from
    can't be read (a shoe's capture.json garbled, a model mid-rebuild), the capture is still listed, its insole
    marked stale."""
    from footscan import server

    d = tmp_path / "captures" / "A"
    d.mkdir(parents=True)
    server.write_json(d / "capture.json", {"capture_id": "A", "created": "1", "insole": {"made": "x"}})

    def unreadable(folder, meta):
        raise ValueError("not UTF-8")

    monkeypatch.setattr(server, "insole_source", unreadable)
    [c] = server.list_captures(tmp_path / "captures")
    assert c["capture_id"] == "A" and c["insole"]["stale"] is True


def test_an_insole_whose_source_cant_be_read_is_not_downloadable_and_the_review_loop_carries_on(tmp_path, monkeypatch):
    """The same unreadable source answers "not current" wherever it's asked (the download, the review
    loop), instead of an error that stops the review of every other capture."""
    from footscan import review, server

    for cid in ("A", "B"):
        d = tmp_path / "captures" / cid
        (d / "insole").mkdir(parents=True)
        (d / "insole" / "insole.json").write_text("{}", encoding="utf-8")
        server.write_json(d / "capture.json", {"capture_id": cid, "insole": {"made": "x", "source": "m",
                                                                             "outline_shape": "generic"}})

    def source(folder, meta):
        if folder.name == "A":
            raise OSError("removed mid-rebuild")
        return folder / "mesh.ply"

    monkeypatch.setattr(server, "insole_source", source)
    monkeypatch.setattr(server, "source_stamp", lambda path: "m")
    assert server.insole_downloadable(tmp_path / "captures" / "A", {"insole": {"made": "x", "source": "m"}}) is False
    assert server.insole_is_stale(tmp_path / "captures" / "A", {"insole": {"made": "x", "source": "m"}}) is True
    assert [f.name for f, _m in review.pending(tmp_path)] == ["B"]


def test_a_list_of_submissions_still_shows_a_bug_in_reading_one(tmp_path, monkeypatch):
    """Only a submission.json that can't be read is left out; a ValueError from turning it into the studio's
    view is a bug, and is raised, not hidden by leaving that submission out."""
    from footscan import server

    (tmp_path / "S1").mkdir()
    server.write_json(tmp_path / "S1" / "submission.json", {"created": "1", "scans": {}})

    def broken(meta):
        raise ValueError("a bug")

    monkeypatch.setattr(server, "public_meta", broken)
    with pytest.raises(ValueError, match="a bug"):
        server.list_submissions(tmp_path)


def test_a_build_from_before_the_computer_last_started_has_stopped(monkeypatch):
    """After a restart or a power cut, the number in a build's status.json may belong to another account's
    process now, which can't be asked (access denied) and would look alive for good. A status written
    before the computer started is from a process that has stopped."""
    import os

    from footscan import recon_jobs

    monkeypatch.setattr(recon_jobs, "booted_at", lambda: 1000.0)
    early = 1000.0 - recon_jobs.CLOCK_SLACK_S
    assert recon_jobs.pid_alive(os.getpid(), since=early - 1) is False
    # just before the start as the clock now reads: the clock may have been set forward since (NTP)
    assert recon_jobs.pid_alive(os.getpid(), since=999.0) is True
    assert recon_jobs.pid_alive(os.getpid(), since=1001.0) is True
    assert recon_jobs.pid_alive(os.getpid()) is True  # no time written: asked as before


def test_a_build_page_reads_a_bom_calipers_file_and_skips_a_garbled_plantar_file(tmp_path):
    """calipers.json saved by Notepad starts with a byte-order mark, which --calipers accepts; the status
    must too. A plantar.json cut short (being rewritten, or removed by a rebuild) leaves its profile out
    instead of failing the whole status."""
    import json

    from footscan import recon_jobs

    out = tmp_path / "recon"
    out.mkdir()
    (out / "status.json").write_text(json.dumps({"state": "done", "stage": "done"}), encoding="utf-8")
    (out / "plantar.json").write_bytes(b'{"medial_prof')
    (tmp_path / "calipers.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"length": 50.0}).encode())
    s = recon_jobs.summary(tmp_path)
    assert s["state"] == "done" and s["medial_profile"] is None and s["calipers"] == {"length": 50.0}


@pytest.mark.parametrize("failure", ["permission", "openssl"])
def test_a_studio_that_cant_write_its_certificate_says_how_to_make_it(monkeypatch, failure):
    """Under Local Service the checkout is read-only, so a missing .certs (first start, or deleted to make
    a new certificate) can't be made there: say to start it once as yourself, not a traceback."""
    import subprocess

    from footscan import server

    def refused(cert_dir):
        if failure == "permission":
            raise PermissionError(13, "Access is denied", str(cert_dir))
        raise subprocess.CalledProcessError(1, ["openssl"], stderr=b"req: Can't open key.pem for writing")

    monkeypatch.setattr(server, "load_studio_key", lambda path: "k")
    monkeypatch.setattr(server, "ensure_cert", refused)
    # openssl can fail for other reasons too (a broken openssl.cnf on a Mac): what it said comes first
    said = "Start footscan serve --https once as yourself" if failure == "permission" else "Can't open key.pem for writing"
    with pytest.raises(SystemExit, match=said):
        server.serve(https=True)


def test_a_temporary_file_left_by_a_killed_write_is_known_as_one(tmp_path):
    """A write killed between writing its temporary file and the swap leaves that file behind. It isn't
    something anyone made, so a refused upload's capture with only that beside capture.json is still
    removed."""
    from footscan import atomic

    assert atomic.is_temporary(atomic.temporary_name(tmp_path / "capture.json"))
    assert not atomic.is_temporary(tmp_path / "capture.json")
    assert not atomic.is_temporary(tmp_path / "mesh.ply")


def test_a_request_refused_for_two_lengths_still_gets_its_answer(servers):
    """Content-Length 0 then 5 MB is refused (one length, please) before its body is read. The 5 MB is still
    coming, so it's taken in before the close like any refused body, and the 400 isn't lost to a reset."""
    import socket

    op, _phone, _data = servers
    host, port = op.removeprefix("http://").split(":")
    body = b"x" * (6 * 1024 * 1024)
    sock = socket.create_connection((host, int(port)), timeout=10)
    head = (f"POST /api/captures HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
            f"Content-Length: 0\r\nContent-Length: {len(body)}\r\n\r\n").encode()
    errors = []

    def send():
        try:
            sock.sendall(head + body)
        except OSError as e:
            errors.append(e)

    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    got = b""
    try:
        while chunk := sock.recv(65536):
            got += chunk
    except OSError as e:
        errors.append(e)
    finally:
        sender.join(10)
        sock.close()
    assert got.startswith(b"HTTP/1.1 400"), got[:200]
    assert errors == []


def test_a_folder_that_cant_be_written_fails_at_once_off_windows(tmp_path, monkeypatch):
    """Only Windows refuses to replace an open file; elsewhere PermissionError means the folder can't be written,
    and waiting 2 s on every write (holding the request and its capture lock) changes nothing."""
    import time

    from footscan import atomic

    def refused(src, dst):
        raise PermissionError(13, "Permission denied", str(dst))

    monkeypatch.setattr(atomic.os, "replace", refused)
    monkeypatch.setattr(atomic, "RETRIES", False)
    t0 = time.monotonic()
    with pytest.raises(PermissionError):
        atomic.write_utf8(tmp_path / "capture.json", "{}")
    assert time.monotonic() - t0 < 0.5
    assert list(tmp_path.iterdir()) == []  # no temporary file left behind


def test_a_build_another_account_started_counts_as_running_on_windows():
    """The Local Service studio can't open a build the owner started from their own PowerShell (access
    denied). That build exists, so it's running: the studio mustn't call it failed and start a second one."""
    from footscan import recon_jobs

    class NoOpen:
        def OpenProcess(self, *a):
            return 0

    assert recon_jobs._windows_pid_alive(1234, NoOpen(), lambda: recon_jobs.ERROR_ACCESS_DENIED) is True
    assert recon_jobs._windows_pid_alive(1234, NoOpen(), lambda: 87) is False  # ERROR_INVALID_PARAMETER: gone


def test_a_build_silent_for_longer_than_any_build_takes_has_stopped_even_if_its_number_cant_be_asked():
    """Crashed, and its number given to another account's process in the same boot: access denied, but a build
    writes its status at every stage, so one unheard of for SILENT_BUILD_S is not that build."""
    from footscan import recon_jobs

    class NoOpen:
        def OpenProcess(self, *a):
            return 0

    denied = lambda: recon_jobs.ERROR_ACCESS_DENIED  # noqa: E731
    assert recon_jobs._windows_pid_alive(1234, NoOpen(), denied, unheard_for_s=60.0) is True
    assert recon_jobs._windows_pid_alive(1234, NoOpen(), denied, unheard_for_s=recon_jobs.SILENT_BUILD_S + 1) is False


def test_a_read_refused_while_a_write_swaps_the_file_is_tried_again(tmp_path, monkeypatch):
    """Windows refuses an open in the instant another thread replaces the file (a sharing violation)."""
    from pathlib import Path as P

    from footscan import atomic

    f = tmp_path / "capture.json"
    f.write_text("{}", encoding="utf-8")
    real, calls = P.read_text, []

    def busy_once(self, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(13, "sharing violation", str(self))
        return real(self, *a, **k)

    monkeypatch.setattr(atomic, "RETRIES", True)
    monkeypatch.setattr(P, "read_text", busy_once)
    assert atomic.read_utf8(f) == "{}" and len(calls) == 2


def test_a_file_kept_open_past_the_retries_gets_an_answer_not_a_dropped_connection(servers, monkeypatch):
    from footscan import server

    op, _phone, _data = servers

    def busy(path):
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(server, "list_captures", busy)
    st, raw, _ = call(f"{op}/api/captures")
    assert st == 503 and "in use by another program" in json.loads(raw)["error"]


def test_a_temporary_file_another_request_is_writing_now_still_counts(tmp_path):
    """Only one left behind (older than a minute) is ignored when a refused upload's capture is removed; one
    being written right now (a calipers save) keeps the folder."""
    import os
    import time

    from footscan import atomic

    t = atomic.temporary_name(tmp_path / "calipers.json")
    t.write_text("{}", encoding="utf-8")
    assert not atomic.is_temporary(t, left_behind=True)
    old = time.time() - atomic.LEFT_BEHIND_AFTER_S - 5
    os.utime(t, (old, old))
    assert atomic.is_temporary(t, left_behind=True)


def test_a_studio_that_cant_write_its_key_says_how_to_make_it(monkeypatch):
    from footscan import server

    def read_only(path):
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(server, "load_studio_key", read_only)
    with pytest.raises(SystemExit, match="Start footscan serve once as yourself"):
        server.serve()


# ---- what the customer's scan page sends, and who it is from --------------------------------------------------

def test_a_customers_scan_summary_keeps_only_numbers_and_short_words(servers):
    """The scan page sends its summary without the studio key, and the studio page shows it: markup sent in it
    (here, a script tag in a number's place) is not kept, while what scanner.js really sends is."""
    op, phone, _ = servers
    sub = body(call(f"{phone}/api/submissions", "POST", PERSON))
    tok = {"X-Upload-Token": sub["upload_token"]}
    key = sub["plan"][0]["key"]
    base = f"{phone}/api/submissions/{sub['id']}/scans/{key}"
    assert call(f"{base}/start", "POST", {}, tok)[0] == 200
    assert call(f"{base}/frames/1", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})[0] == 200
    bad = "<img src=x onerror=alert(1)>" + "x" * 40
    summary = {"frames_kept": 1, "duration_s": bad, "rejected_blur": 0, "mat_paper": "a4",
               "view_sources": {"sensor": 1}, "focal_px_median": None, "orientation_source": {"no": [bad]},
               "short_tag": "<b onclick=x>", "quoted": 'a"b', "papers": ["a4", "<i>"],
               bad: 1, "coverage_completeness": 0.5}
    assert call(f"{base}/complete", "POST", {"frames": [], "summary": summary}, tok)[0] == 200
    kept = body(call(f"{op}/api/submissions/{sub['id']}"))["scans"][key]["summary"]
    assert kept == {"frames_kept": 1, "rejected_blur": 0, "mat_paper": "a4", "view_sources": {"sensor": 1},
                    "focal_px_median": None, "coverage_completeness": 0.5}


def test_the_submission_page_escapes_every_scan_summary_figure():
    """Summaries saved before the server cleaned them are still shown: the page itself escapes each one."""
    import re

    page = (WEB_DIR / "studio" / "submission.html").read_text(encoding="utf-8")
    raw = re.findall(r"\$\{\s*\(?\s*(?:sum\.|scan\.load_kg|s\.feet)", page)
    assert raw == []


def test_rate_limit_counts_a_direct_request_by_its_own_address_whatever_header_it_sends():
    from footscan.server import client_of

    spoof = {"CF-Connecting-IP": "203.0.113.5", "X-Forwarded-For": "203.0.113.6"}
    assert client_of("100.70.1.2", spoof) == "100.70.1.2"       # straight from Tailscale or the Wi-Fi
    assert client_of("127.0.0.1", spoof) == "203.0.113.5"       # the tunnel on this computer names the client
    assert client_of("127.0.0.1", {"X-Forwarded-For": "198.51.100.1, 10.0.0.1"}) == "198.51.100.1"
    assert client_of("127.0.0.1", {}) == "127.0.0.1"


def test_rate_limiter_forgets_clients_with_nothing_in_the_last_hour(monkeypatch):
    import time

    from footscan import server

    monkeypatch.setattr(server, "RATE_LIMIT_CLIENTS_KEPT", 3)
    limiter = server.RateLimiter(per_hour=1)
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    for c in ("a", "b", "c", "d"):
        assert limiter.allow(c)
    now[0] += 3601
    assert limiter.allow("e") and set(limiter.hits) == {"e"}
    assert not limiter.allow("e")  # the limit itself still holds


def test_an_insole_cut_to_the_foots_outline_by_default_is_stale_now_that_the_default_is_the_generic_outline():
    """Made before the generic insole outline was the default: cut to the foot's own outline without asking (or
    lengthened at the front for a shoe's length), it can be the long thin shape the generic outline replaces."""
    from footscan.server import STALE_MESSAGES, _old_default_outline

    assert _old_default_outline({"made": "x"})                                  # before outlines were recorded
    assert _old_default_outline({"outline": "default"})                         # nothing asked, no saved shoe
    assert _old_default_outline({"outline": "foot", "shoe_length_mm": 275.0})   # the foot's, lengthened
    assert not _old_default_outline({"outline": "foot", "shoe_length_mm": None})  # the foot's own, chosen
    assert not _old_default_outline({"outline": "saved", "shoe": {"saved": "x"}})
    assert not _old_default_outline({"outline": "default", "outline_shape": "generic"})
    assert "generic insole outline" in STALE_MESSAGES["outline"]


# ---- uploads that end early, a full disk, the log, and two requests at once (Codex review, 2026-11-17) -----

def _raw_request(url: str, head: str, body: bytes, close_early: bool = False):
    """Send a request by hand (for a body shorter than it says) -> the answer's status code."""
    import socket
    from urllib.parse import urlsplit

    u = urlsplit(url)
    s = socket.create_connection((u.hostname, u.port))
    s.sendall(head.encode() + body)
    if close_early:
        s.shutdown(socket.SHUT_WR)
    answer = s.recv(65536).decode("latin-1")
    s.close()
    return int(answer.split()[1])


def _new_scan(phone):
    sub = body(call(f"{phone}/api/submissions", "POST", PERSON))
    tok = {"X-Upload-Token": sub["upload_token"]}
    key = sub["plan"][0]["key"]
    base = f"{phone}/api/submissions/{sub['id']}/scans/{key}"
    assert call(f"{base}/start", "POST", {}, tok)[0] == 200
    return sub, tok, key, base


def test_a_photo_upload_that_ends_early_is_refused_and_keeps_the_photo_that_was_there(servers):
    _, phone, data = servers
    sub, tok, key, base = _new_scan(phone)
    good = JPEG + b"good"
    assert call(f"{base}/frames/1", "PUT", good, {**tok, "Content-Type": "image/jpeg"})[0] == 200
    path = urlsplit_path(f"{base}/frames/1")
    head = (f"PUT {path} HTTP/1.1\r\nHost: x\r\nX-Upload-Token: {sub['upload_token']}\r\n"
            f"Content-Type: image/jpeg\r\nContent-Length: 1000\r\n\r\n")
    assert _raw_request(base, head, JPEG[:10], close_early=True) == 400
    frame = data / "submissions" / sub["id"] / key / "frame_0001.jpg"
    assert frame.read_bytes() == good
    assert [f.name for f in frame.parent.iterdir()] == ["frame_0001.jpg"]  # no part-file left behind


def urlsplit_path(url):
    from urllib.parse import urlsplit

    return urlsplit(url).path


def test_a_submission_takes_no_more_photos_than_its_quota(servers, monkeypatch):
    from footscan import server

    _, phone, data = servers
    sub, tok, key, base = _new_scan(phone)
    room = server.folder_bytes(data / "submissions" / sub["id"]) + 2 * len(JPEG)  # its submission.json + 2 photos
    monkeypatch.setattr(server, "MAX_SUBMISSION_BYTES", room)
    for n in (1, 2):
        assert call(f"{base}/frames/{n}", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})[0] == 200
    status, raw, _ = call(f"{base}/frames/3", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})
    assert status == 400 and b"as many photos" in raw


def test_no_photo_is_kept_when_the_disk_is_nearly_full(servers, monkeypatch):
    from footscan import server

    _, phone, data = servers
    sub, tok, key, base = _new_scan(phone)
    monkeypatch.setattr(server, "MIN_FREE_BYTES", 10 ** 18)
    assert call(f"{base}/frames/1", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})[0] == 507
    assert not (data / "submissions" / sub["id"] / key / "frame_0001.jpg").exists()


def test_the_studio_key_and_upload_tokens_in_a_url_never_reach_the_log(servers, capfd):
    op, _, _ = servers
    call(f"{op}/api/studio?key={KEY}")
    call(f"{op}/api/submissions/sub-x/rescan?t=secret-token")
    err = capfd.readouterr().err
    assert "/api/studio?key=…" in err and KEY not in err and "secret-token" not in err


def test_a_slow_request_doesnt_undo_another_scans_finishing(servers):
    """Two scans of one submission finished at once, the first one's body arriving slowly: both stay
    finished (the slow one reads submission.json only once its body is in, under the submission's lock)."""
    import socket
    import time
    from urllib.parse import urlsplit

    _, phone, data = servers
    sub = body(call(f"{phone}/api/submissions", "POST", PERSON))
    tok = {"X-Upload-Token": sub["upload_token"]}
    keys = [p["key"] for p in sub["plan"]][:2]
    for key in keys:
        base = f"{phone}/api/submissions/{sub['id']}/scans/{key}"
        assert call(f"{base}/start", "POST", {}, tok)[0] == 200
        assert call(f"{base}/frames/1", "PUT", JPEG, {**tok, "Content-Type": "image/jpeg"})[0] == 200
    slow = json.dumps({"frames": []}).encode()
    u = urlsplit(phone)
    s = socket.create_connection((u.hostname, u.port))
    s.sendall((f"POST /api/submissions/{sub['id']}/scans/{keys[0]}/complete HTTP/1.1\r\nHost: x\r\n"
               f"X-Upload-Token: {sub['upload_token']}\r\nContent-Type: application/json\r\n"
               f"Content-Length: {len(slow)}\r\n\r\n").encode() + slow[:3])
    time.sleep(0.5)  # the slow request has started
    assert call(f"{phone}/api/submissions/{sub['id']}/scans/{keys[1]}/complete", "POST", {"frames": []}, tok)[0] == 200
    s.sendall(slow[3:])
    assert int(s.recv(65536).decode().split()[1]) == 200
    s.close()
    scans = json.loads((data / "submissions" / sub["id"] / "submission.json").read_text())["scans"]
    assert [scans[k]["status"] for k in keys] == ["complete", "complete"]


def test_rate_limit_counts_an_ipv6_client_by_its_slash_64():
    from footscan.server import RateLimiter

    limiter = RateLimiter(per_hour=2)
    assert limiter.allow("2001:db8:1:2::1") and limiter.allow("2001:db8:1:2::abcd")
    assert not limiter.allow("2001:db8:1:2:ffff::9")      # a new address in the same /64
    assert limiter.allow("2001:db8:1:3::1")                # another network
    assert limiter.allow("::ffff:198.51.100.7") and limiter.allow("198.51.100.7")
    assert not limiter.allow("198.51.100.7")               # the same IPv4 client, written either way


def test_rate_limiter_is_safe_to_use_from_many_threads_while_it_forgets(monkeypatch):
    import threading

    from footscan import server

    monkeypatch.setattr(server, "RATE_LIMIT_CLIENTS_KEPT", 5)
    limiter = server.RateLimiter(per_hour=1000)
    errors = []

    def hammer(k):
        try:
            for i in range(3000):
                limiter.allow(f"10.{k}.{i // 250}.{i % 250}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=hammer, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# ---- files: revalidation (ETag) and gzip ----------------------------------------------------------------------

def test_a_file_the_browser_already_has_is_answered_not_modified_with_no_body(servers):
    _, phone, _ = servers
    status, raw, h = call(f"{phone}/assets/style.css")
    assert status == 200 and raw == (WEB_DIR / "assets" / "style.css").read_bytes() and h["ETag"]
    status, raw, h2 = call(f"{phone}/assets/style.css", headers={"If-None-Match": h["ETag"]})
    assert status == 304 and raw == b"" and h2["ETag"] == h["ETag"]
    # weak or listed among others, it still matches; another version's tag doesn't
    assert call(f"{phone}/assets/style.css", headers={"If-None-Match": f'"x", W/{h["ETag"]}'})[0] == 304
    assert call(f"{phone}/assets/style.css", headers={"If-None-Match": '"1-2"'})[0] == 200


def test_a_file_that_changed_gets_a_new_etag(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    f = web / "assets" / "a.js"
    f.write_text("let a = 1;\n" * 10)
    httpd = StudioServer(("127.0.0.1", 0), make_handler(web, tmp_path, local_check=lambda h: False, studio_key=KEY))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/assets/a.js"
    try:
        tag = call(url)[2]["ETag"]
        f.write_text("let a = 2;\n" * 11)
        status, raw, h = call(url, headers={"If-None-Match": tag})
        assert status == 200 and raw == f.read_bytes() and h["ETag"] != tag
    finally:
        httpd.shutdown()


def test_text_and_previews_are_gzipped_only_for_a_browser_that_takes_it(servers):
    import gzip

    _, phone, _ = servers
    js = (WEB_DIR / "assets" / "app.js").read_bytes()
    status, raw, h = call(f"{phone}/assets/app.js", headers={"Accept-Encoding": "gzip, deflate, br"})
    assert status == 200 and h["Content-Encoding"] == "gzip" and gzip.decompress(raw) == js
    assert int(h["Content-Length"]) == len(raw) < len(js) and "Accept-Encoding" in h["Vary"]
    # its own tag: a cache never mixes the compressed and plain copies
    _, plain, hp = call(f"{phone}/assets/app.js")
    assert plain == js and "Content-Encoding" not in hp and hp["ETag"] != h["ETag"]
    assert "Content-Encoding" not in call(f"{phone}/assets/app.js", headers={"Accept-Encoding": "gzip;q=0"})[2]
    # a 304 for the compressed copy, by its own tag
    assert call(f"{phone}/assets/app.js", headers={"Accept-Encoding": "gzip", "If-None-Match": h["ETag"]})[0] == 304


def test_photos_are_never_gzipped(servers):
    op, _, data = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "object", "session": "S1"}))["id"]
    big = JPEG + b"\x00" * 4096
    assert call(f"{op}/api/captures/{cid}/frames/1", "PUT", big, {"Content-Type": "image/jpeg"})[0] == 200
    status, raw, h = call(f"{op}/api/captures/{cid}/frames/1.jpg", headers={"Accept-Encoding": "gzip"})
    assert status == 200 and raw == big and "Content-Encoding" not in h


def test_a_head_request_gets_the_gets_headers_and_no_body_and_the_connection_carries_on(servers):
    import http.client
    import urllib.parse

    op, phone, _ = servers
    css = (WEB_DIR / "assets" / "style.css").read_bytes()
    u = urllib.parse.urlsplit(phone)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    try:
        conn.request("HEAD", "/assets/style.css")
        r = conn.getresponse()
        assert r.status == 200 and int(r.headers["Content-Length"]) == len(css) and r.headers["ETag"]
        assert r.read() == b""
        conn.request("HEAD", "/assets/no-such-file.js")
        r = conn.getresponse()
        assert r.status == 404 and r.read() == b""
        # the same connection: had a HEAD's body gone out, it would be read here as the start of this answer
        conn.request("GET", "/assets/style.css")
        r = conn.getresponse()
        assert r.status == 200 and r.read() == css
    finally:
        conn.close()
    # an API answer too, the same length its GET sends
    u = urllib.parse.urlsplit(op)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    try:
        conn.request("GET", "/api/captures")
        r = conn.getresponse()
        got = r.read()
        conn.request("HEAD", "/api/captures")
        r = conn.getresponse()
        assert r.status == 200 and int(r.headers["Content-Length"]) == len(got) and r.read() == b""
        assert r.headers["Content-Type"] == "application/json"
    finally:
        conn.close()


def test_a_304_does_not_read_the_file(servers, monkeypatch):
    import builtins

    _, phone, _ = servers
    tag = call(f"{phone}/assets/style.css")[2]["ETag"]
    reads = []
    real_open = builtins.open

    class Counting:
        def __init__(self, f):
            self._f = f

        def read(self, *a):
            reads.append(1)
            return self._f.read(*a)

        def __getattr__(self, k):
            return getattr(self._f, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._f.__exit__(*a)

    def counting_open(file, mode="r", *a, **k):
        f = real_open(file, mode, *a, **k)
        return Counting(f) if str(file).endswith("style.css") and "b" in mode else f

    monkeypatch.setattr(builtins, "open", counting_open)
    assert call(f"{phone}/assets/style.css", headers={"If-None-Match": tag})[0] == 304
    assert reads == []
    assert call(f"{phone}/assets/style.css")[0] == 200 and reads


@pytest.mark.parametrize("header,takes", [("gzip", True), ("deflate, gzip;q=0.8", True), ("GZIP", True),
                                          ("gzip;q=0", False), ("gzip; q=0.0", False), ("br, deflate", False),
                                          ("", False), ("x-gzip;q=0, gzip", True), ("*", True),
                                          ("gzip;q=0, *", False), ("br, *;q=0.1", True), ("gzip;q=x", False)])
def test_accept_encoding_is_read_with_its_q_values(header, takes):
    from footscan.server import accepts_gzip

    assert accepts_gzip(header) is takes


def test_no_script_written_into_a_page_runs_only_the_sites_own_files():
    """The CSP forbids inline script, so no page may carry one: each page's script is a file under /assets."""
    import re

    from footscan.server import SECURITY_HEADERS

    csp = dict(p.strip().split(" ", 1) for p in SECURITY_HEADERS["Content-Security-Policy"].split(";") if p.strip())
    assert csp["script-src"] == "'self'"
    assert csp["base-uri"] == csp["form-action"] == "'self'" and csp["object-src"] == "'none'"
    for page in [*WEB_DIR.glob("*.html"), *WEB_DIR.glob("studio/*.html")]:
        html = page.read_text(encoding="utf-8")
        inline = [m for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S) if m.group(2).strip()]
        assert not inline, f"{page.name}: a script inside the page won't run; move it to a file under web/assets"
        assert not re.search(r"\son[a-z]+\s*=", html), f"{page.name}: an onclick= (or the like) won't run"


def test_a_wrong_studio_key_is_said_so_and_the_page_asked_for_keeps_its_settings(servers):
    _, phone, _ = servers
    st, page, _ = call(f"{phone}/studio/insole.html?capture=ABC_1&key=not-the-key")
    assert st == 403 and b"doesn't match" in page
    assert b'<input type="hidden" name="capture" value="ABC_1">' in page and b'value="not-the-key"' not in page
    st, page, _ = call(f"{phone}/studio/?key=&capture=x")  # the box left empty: asked for, not "doesn't match"
    assert st == 403 and b"doesn't match" not in page
    st, page, _ = call(f"{phone}/studio/?capture=%22%3E%3Cscript%3E")
    assert b"doesn't match" not in page and b"<script>" not in page  # no key given; a setting is escaped


def test_an_unexpected_error_is_answered_500_in_words_and_logged_not_a_dropped_connection(servers, monkeypatch, capsys):
    from footscan import server

    op, _, _ = servers

    def broken(*a, **k):
        raise RuntimeError("something inside broke")

    monkeypatch.setattr(server, "list_captures", broken)
    status, raw, _ = call(f"{op}/api/captures?key={KEY}")
    assert status == 500 and "didn't expect (RuntimeError)" in json.loads(raw)["error"]
    assert b"something inside broke" not in raw  # the details are the log's, not the answer's
    err = capsys.readouterr().err
    assert "something inside broke" in err and "GET /api/captures?key=…" in err and KEY not in err
    # and the Status page lists it, newest first, without the key
    monkeypatch.undo()
    listed = json.loads(call(f"{op}/api/studio/status")[1])["recent_errors"]
    assert len(listed) == 1 and listed[0]["request"] == "GET /api/captures"
    assert listed[0]["error"] == "RuntimeError: something inside broke" and listed[0]["code"].startswith("test_server.py:")
