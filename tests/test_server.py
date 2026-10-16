import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from footscan.server import WEB_DIR, make_handler

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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(WEB_DIR, tmp_path, local_check=is_loopback, studio_key=KEY))
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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(WEB_DIR, tmp_path, local_check=lambda h: False,
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


def test_runner_one_build_at_a_time_and_notices_a_dead_process(tmp_path):
    from footscan import recon_jobs

    fake = tmp_path / "fake-python"
    fake.write_text("#!/bin/sh\nsleep 2\n")
    fake.chmod(0o755)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    runner = recon_jobs.ReconRunner(python=str(fake))
    runner.start(a, calibration_object=False)
    assert recon_jobs.summary(a, runner)["state"] == "running"
    with pytest.raises(recon_jobs.Busy):
        runner.start(b, calibration_object=False)
    runner.proc.wait()
    # it exited without writing "done": that's a failure, not "still running"
    s = recon_jobs.summary(a, runner)
    assert s["state"] == "failed" and "unexpectedly" in s["error"]


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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert call(f"{url}/api/studio/pairing")[0] == 403
        p = body(call(f"{url}/api/studio/pairing", headers={"X-Studio-Key": KEY, "Host": "footscan.example.dev"}))
        assert p == {"available": True, "url": "https://footscan.example.dev", "key": KEY, "fingerprint": None}
    finally:
        httpd.shutdown()


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
    st, raw, _ = call(f"{op}/api/captures/{cid}/insole", "POST", {})
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
    assert r["max_fill_mm"] == pytest.approx(11.0, abs=0.1) and r["warnings"] == []
    assert b"foam print" in call(f"{op}/api/captures/{cid}/insole/summary.html")[1]
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
