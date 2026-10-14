"""Local web server: the scan site, the operator studio, and on-disk storage.

Standard library only. It runs on your own machine (and your own Wi-Fi, so a
phone can reach it). It is not hardened for the open internet.

Two audiences
-------------
**The person being fitted** uses ``/`` on their phone: acknowledge the safety
terms, scan each foot, send. They can create a submission and upload to it
with the one-time upload token they were given, and nothing else. They cannot
list or view anyone's scans, including their own after sending.

**The operator** uses ``/studio/``. Studio pages and every API that reads
scans answer only requests from this machine (loopback) or from a browser
holding the studio key, so someone on the same Wi-Fi cannot browse other
people's foot photos. To use the studio from your own phone, open the
``/studio/?key=...`` address printed at startup once; it sets a cookie.

Customer API
------------
GET  /api/survey                                        question schema
POST /api/survey/evaluate                               {feet, survey} -> {blocked, flags, plan}; stores nothing
POST /api/submissions                                   {name, feet, acknowledgments, survey}
                                                        -> {id, upload_token, plan, flags}; 422 if screened out
POST /api/submissions/<id>/scans/<key>/start            clear a scan before (re)scanning; key e.g. right-swb
PUT  /api/submissions/<id>/scans/<key>/frames/<n>       one JPEG, header X-Upload-Token
POST /api/submissions/<id>/scans/<key>/complete         per-frame quality data
POST /api/submissions/<id>/submit                       closes uploads

Operator API (this machine, or a browser holding the studio key)
--------------------------------
GET  /api/submissions                                   list
GET  /api/submissions/<id>                              detail
GET  /api/submissions/<id>/scans/<foot>/frames/<n>.jpg
POST /api/submissions/<id>/status                       {status, note}
GET/POST/PUT /api/captures...                           research captures (Phase 0)
POST /api/captures/<id>/recon                           build the 3D model (Phase 2), in the background
GET  /api/captures/<id>/recon                           its progress and results
GET  /api/captures/<id>/recon/<file>                    mesh.ply, report.json, ... (download)
PUT  /api/captures/<id>/calipers                        caliper readings of the calibration object
POST/GET /api/submissions/<id>/scans/<key>/recon[/<file>]   the same for a customer's scan
GET  /api/captures/<id>/viewer.bin                      the 3-D model for the landmark viewer
GET  /api/captures/<id>/picks                           landmark spec + saved picks (Phase 3)
PUT  /api/captures/<id>/picks/<n>                       save pick n {landmarks: {name: [x, y, z]}} -> measurements
DELETE /api/captures/<id>/picks/<n>
(the same three under /api/submissions/<id>/scans/<key>/)
GET  /api/measurements.csv                              every research capture's picks, for the repeatability study

The server itself needs only the standard library; saving a pick loads
numpy and trimesh to compute the measurements.
GET  /api/studio                                        scan address to share

Phones only allow camera and motion-sensor access on secure origins, so
``--https`` generates a self-signed certificate.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import http.cookies
import json
import mimetypes
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import mat as mat_mod
from . import recon_jobs
from . import survey as survey_mod

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"

# "object" is a scanner test: any object, no mat, no foot. It can't be scaled
# to millimetres, so it never counts as foot measurement data.
# "calibration" is the printed calibration object on the mat (Phase 2
# accuracy study): scaled, but not a foot either.
CONDITIONS = {"nwb", "nwb_relaxed", "swb", "fwb", "object", "calibration"}
UNSCALED_CONDITIONS = {"object"}
NON_FOOT_CONDITIONS = {"object", "calibration"}
METHODS = {"bare_skin", "speckle_sock", "marker_dots", "foam_impression", "imported_mesh"}
FEET = ("left", "right")
REQUIRED_ACKS = ("not_medical_device", "clinician_review", "break_in", "photo_consent")
OPERATOR_STATUSES = {"received", "needs_rescan", "archived"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
# A 1920x1080 JPEG from the scanner is ~0.3-1 MB and a scan keeps ~60 frames.
# These caps leave generous headroom while stopping one visitor filling the disk.
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_FRAMES = 200
MAX_MESH_BYTES = 150 * 1024 * 1024
MESH_TYPES = {"obj", "ply", "stl", "glb", "gltf", "off"}
# New submissions per client per hour. Stops a script flooding the disk; a
# real person makes one or two.
SUBMISSIONS_PER_HOUR = 20
LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
# Headers a reverse proxy or tunnel adds. If any is present the request came
# from somewhere else, whatever the socket address says.
PROXY_HEADERS = ("X-Forwarded-For", "Forwarded", "CF-Connecting-IP", "X-Real-IP", "True-Client-IP")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",  # studio keys and rescan tokens travel in URLs
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self), accelerometer=(self), gyroscope=(self), magnetometer=(self)",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
    ),
}


class BadRequest(Exception):
    pass


class Forbidden(Exception):
    pass


STUDIO_LOCKED_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Studio locked</title>
<link rel="stylesheet" href="/assets/style.css"></head><body>
<main class="wrap" style="max-width:520px">
<h1 style="margin-top:12vh">Studio locked</h1>
<p class="muted">This is the private side of footscan. To open it on this device, paste the studio key.
It is printed in the terminal when footscan starts, and stored in the file <span class="mono">.studio_key</span>.</p>
<form class="card" method="get" style="display:grid;gap:14px">
  <div class="field"><label for="key">Studio key</label>
    <input id="key" name="key" type="text" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"></div>
  <button class="btn" type="submit">Open the studio</button>
</form>
<p class="hint">Tip: open the full link with <span class="mono">?key=...</span> once and this device remembers it.
If you are looking for the scan page, it is <a href="/">here</a>.</p>
</main></body></html>"""


class ScreenedOut(Exception):
    def __init__(self, blocked: dict):
        super().__init__(blocked["message"])
        self.blocked = blocked


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(path)


# ---- validation ------------------------------------------------------------

def validate_setup(body: dict) -> dict:
    """Research capture setup (Phase 0 studio)."""
    foot = body.get("foot")
    cond = body.get("condition")
    session = str(body.get("session", "")).strip()
    method = body.get("method", "bare_skin")
    if cond not in CONDITIONS:
        raise BadRequest(f"condition must be one of {sorted(CONDITIONS)}")
    is_object = cond in NON_FOOT_CONDITIONS
    if is_object:
        foot = foot if foot in FEET else None
    elif foot not in FEET:
        raise BadRequest("foot must be left or right")
    if not SESSION_RE.match(session):
        raise BadRequest("session: 1-20 letters, digits, - or _")
    if method not in METHODS:
        raise BadRequest(f"method must be one of {sorted(METHODS)}")
    load = parse_load(body.get("load_kg"))
    if cond in ("swb", "fwb") and load is None:
        raise BadRequest("weight-bearing captures need the scale reading (load_kg)")
    return dict(
        foot=foot, condition=cond, session=session, method=method, load_kg=load,
        measurable=not is_object,
        notes=str(body.get("notes", ""))[:2000], device=str(body.get("device", ""))[:300],
    )


def parse_load(value) -> float | None:
    if value in ("", None):
        return None
    load = float(value)
    if not 0 < load < 400:
        raise BadRequest("load_kg out of range")
    return load


def validate_feet(feet) -> list[str]:
    if not isinstance(feet, list) or not feet or len(set(feet)) != len(feet) or not set(feet) <= set(FEET):
        raise BadRequest("feet: choose left, right, or both")
    return [f for f in FEET if f in feet]


def evaluate_survey(body: dict) -> tuple[list[str], dict, dict]:
    """-> (feet, cleaned survey, evaluation). Raises BadRequest on invalid answers."""
    feet = validate_feet(body.get("feet"))
    answers = survey_mod.validate(body.get("survey"))
    return feet, answers, survey_mod.evaluate(answers, feet)


def validate_submission(body: dict) -> dict:
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 80:
        raise BadRequest("name: 1-80 characters")
    acks = body.get("acknowledgments") or {}
    missing = [k for k in REQUIRED_ACKS if acks.get(k) is not True]
    if missing:
        raise BadRequest(f"all acknowledgments are required (missing {missing})")
    mat_check = validate_mat_check(body)
    feet, answers, evaluation = evaluate_survey(body)
    if evaluation["blocked"]:
        # Screened out: refuse, and store nothing about this person.
        raise ScreenedOut(evaluation["blocked"])
    return dict(
        name=name, feet=feet, survey=answers, flags=evaluation["flags"], plan=evaluation["plan"],
        mat_check=mat_check, mat_check_mm=mat_check["mm"],
        acknowledgments={k: True for k in REQUIRED_ACKS}, device=str(body.get("device", ""))[:300],
    )


def validate_mat_check(body: dict) -> dict:
    """The measured check bar, in whichever unit the person's ruler uses."""
    unit = body.get("mat_check_unit", "cm")
    bar = next((b for b in mat_mod.CHECK_BARS if b["unit"] == unit), None)
    if bar is None:
        raise BadRequest(f"mat_check_unit must be one of {[b['unit'] for b in mat_mod.CHECK_BARS]}")
    try:
        value = float(body.get("mat_check_value"))
    except (TypeError, ValueError):
        raise BadRequest(f"mat_check_value: measure the {bar['label']} bar on the printed scan mat") from None
    measured_mm = value * (bar["length_mm"] / bar["value"])
    # Fit-to-page scaling is out by 3-6 %; a ruler reads to about half a millimetre.
    if abs(measured_mm - bar["length_mm"]) > mat_mod.CHECK_TOLERANCE_MM:
        raise BadRequest("mat_check_value: the scan mat was printed at the wrong size; print at 100% / actual size")
    return dict(value=value, unit=unit, mm=round(measured_mm, 2), expected_mm=bar["length_mm"])


def new_id(prefix: str, data_dir: Path) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    while True:
        cid = f"{prefix}{stamp}-{secrets.token_hex(2)}"
        if not (data_dir / cid).exists():
            return cid


# ---- handler ---------------------------------------------------------------

def is_loopback(handler) -> bool:
    """True only for a request made directly on this computer.

    A tunnel or reverse proxy running on this machine connects from loopback
    too, so any proxy header means the real client is elsewhere.
    """
    if any(handler.headers.get(h) for h in PROXY_HEADERS):
        return False
    return handler.client_address[0] in LOOPBACK


def never_local(handler) -> bool:
    return False


class RateLimiter:
    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self.hits: dict[str, list[float]] = {}

    def allow(self, client: str) -> bool:
        import time

        now = time.monotonic()
        recent = [t for t in self.hits.get(client, []) if now - t < 3600]
        if len(recent) >= self.per_hour:
            self.hits[client] = recent
            return False
        recent.append(now)
        self.hits[client] = recent
        return True


def load_studio_key(path: Path) -> str:
    """A persistent random key, so a phone stays signed in across restarts."""
    if path.exists() and (key := path.read_text().strip()):
        return key
    key = secrets.token_urlsafe(18)
    path.write_text(key)
    path.chmod(0o600)
    return key


def make_handler(web_dir: Path = WEB_DIR, data_dir: Path = DATA_DIR, local_check=is_loopback,
                 studio_key: str | None = None, secure_cookie: bool = False,
                 submissions_per_hour: int = SUBMISSIONS_PER_HOUR, allow_indexing: bool = True,
                 public: bool = False, cert_fingerprint: str | None = None):
    runner = recon_jobs.ReconRunner()
    insole_locks: dict[str, threading.Lock] = {}
    captures_dir = data_dir / "captures"
    submissions_dir = data_dir / "submissions"
    limiter = RateLimiter(submissions_per_hour)

    class Handler(BaseHTTPRequestHandler):
        server_version = "footscan"

        def log_message(self, fmt, *args):  # skip static asset noise
            if args and "/api/" in str(args[0]):
                super().log_message(fmt, *args)

        def end_headers(self):
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            if not allow_indexing:
                # Keep search engines out (every page, every file) until the
                # operator decides otherwise: see serve --allow-indexing.
                self.send_header("X-Robots-Tag", "noindex, nofollow")
            super().end_headers()

        def client_id(self) -> str:
            for h in ("CF-Connecting-IP", "X-Real-IP"):
                if v := self.headers.get(h):
                    return v.strip()
            if v := self.headers.get("X-Forwarded-For"):
                return v.split(",")[0].strip()
            return self.client_address[0]

        # -- helpers --------------------------------------------------------
        def send_json(self, obj, status=HTTPStatus.OK):
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path: Path, ctype: str, cache: str = "no-cache", headers: dict | None = None):
            headers = {**getattr(self, "_extra_headers", {}), **(headers or {})}
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def read_body(self, limit: int) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                raise BadRequest("empty body")
            if length > limit:
                raise BadRequest("body too large")
            return self.rfile.read(length)

        def json_body(self) -> dict:
            body = json.loads(self.read_body(MAX_JSON_BYTES))
            if not isinstance(body, dict):
                raise BadRequest("expected a JSON object")
            return body

        def has_studio_cookie(self) -> bool:
            if not studio_key:
                return False
            jar = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            got = jar.get("footscan_studio")
            return bool(got) and hmac.compare_digest(got.value, studio_key)

        def has_studio_key(self) -> bool:
            """Key in a header or in ?key=. Cookies can be blocked or cleared
            (a self-signed certificate, private browsing, a link opened without
            the key), so the key alone must always be enough."""
            if not studio_key:
                return False
            header = self.headers.get("X-Studio-Key", "")
            if header and hmac.compare_digest(header, studio_key):
                return True
            given = query_param(self.path, "key")
            return bool(given) and hmac.compare_digest(given, studio_key)

        def host_is_loopback_name(self) -> bool:
            """The address the browser typed is this computer's own name.

            Without this, any web page could "rebind" its own domain name to
            127.0.0.1 and read the studio as if it were on this computer (DNS
            rebinding). The browser still sends that page's domain as the Host,
            so only localhost / 127.0.0.1 / [::1] count.
            """
            from urllib.parse import urlsplit

            host = urlsplit("//" + (self.headers.get("Host") or "")).hostname or ""
            return host in ("localhost", "127.0.0.1", "::1")

        def is_operator(self) -> bool:
            return (local_check(self) and self.host_is_loopback_name()) or self.has_studio_cookie() or self.has_studio_key()

        def cross_site(self) -> bool:
            """A change requested by some other web site (its Origin isn't this server).

            Browsers attach an Origin header to every cross-site POST/PUT/DELETE,
            so a page elsewhere can't use the operator's browser to delete
            submissions or start builds here (cross-site request forgery).
            """
            from urllib.parse import urlsplit

            origin = self.headers.get("Origin")
            return bool(origin) and urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower()

        def require_local(self):
            if not self.is_operator():
                raise Forbidden("studio is only available to the operator")

        def remember_studio_key(self):
            """Set the cookie for next time. The page is served either way, so a
            browser that refuses the cookie still works via the key."""
            flags = "; Secure" if secure_cookie else ""
            self._extra_headers = {
                "Set-Cookie": f"footscan_studio={studio_key}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000{flags}",
            }

        def studio_locked(self, path: str):
            body = STUDIO_LOCKED_HTML.encode()
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def save_jpeg(self, path: Path, n: int):
            if not 1 <= n <= MAX_FRAMES:
                raise BadRequest("frame number out of range")
            body = self.read_body(MAX_FRAME_BYTES)
            if body[:3] != b"\xff\xd8\xff":
                raise BadRequest("frame must be a JPEG")
            path.write_bytes(body)

        def route(self, method: str):
            path, _, query = self.path.partition("?")
            try:
                if method != "GET" and self.cross_site():
                    raise Forbidden("request from another web site refused")
                if path.startswith("/api/"):
                    return self.api(method, path.strip("/").split("/")[1:])
                if method != "GET":
                    return self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                if path == "/robots.txt":
                    body = b"User-agent: *\nDisallow: /\n" if not allow_indexing else b"User-agent: *\nDisallow: /studio/\nDisallow: /api/\n"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    return self.wfile.write(body)
                if self.is_studio_path(path):
                    if not self.is_operator():
                        return self.studio_locked(path)
                    if self.has_studio_key() and not self.has_studio_cookie():
                        self.remember_studio_key()  # so later pages work without the key in the URL
                return self.static(path, query)
            except BadRequest as e:
                self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            except Forbidden as e:
                self.send_json({"error": str(e)}, HTTPStatus.FORBIDDEN)
            except survey_mod.SurveyError as e:
                self.send_json({"error": "survey incomplete or invalid", "fields": e.errors}, HTTPStatus.BAD_REQUEST)
            except ScreenedOut as e:
                self.send_json({"error": str(e), "blocked": e.blocked}, HTTPStatus.UNPROCESSABLE_ENTITY)
            except (ValueError, json.JSONDecodeError) as e:
                self.send_json({"error": f"invalid input: {e}"}, HTTPStatus.BAD_REQUEST)
            except FileNotFoundError:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (TypeError, OverflowError, AttributeError) as e:
                # Input of the wrong shape (a list where a number was expected, ...):
                # answer, rather than dropping the connection.
                self.send_json({"error": f"invalid input: {e}"}, HTTPStatus.BAD_REQUEST)

        def is_studio_path(self, path: str) -> bool:
            """Anything that ends up inside web/studio, however it was spelt.

            The Mac's disk ignores letter case (/STUDIO/ is /studio/) and a raw
            client can send /assets/../studio/; resolve the path first, then ask.
            """
            target = Path(str((web_dir / path.lstrip("/")).resolve()).casefold())
            studio = Path(str((web_dir / "studio").resolve()).casefold())
            # Path.is_relative_to compares whole path parts, with the right
            # separator for the operating system (\ on Windows, / elsewhere).
            return target == studio or target.is_relative_to(studio)

        def static(self, path: str, query: str = ""):
            rel = path.lstrip("/") or "index.html"
            target = (web_dir / rel).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.is_relative_to(web_dir.resolve()) or not target.is_file():
                return self.send_error(HTTPStatus.NOT_FOUND)
            ctype = "text/javascript" if target.suffix == ".js" else (
                mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            # ?download=1 asks the browser to save the file instead of showing it.
            extra = {"Content-Disposition": f'attachment; filename="{target.name}"'} if "download=1" in query else {}
            self.send_file(target, ctype, headers=extra)

        def api(self, method: str, parts: list[str]):
            if parts[:1] == ["submissions"]:
                return self.api_submissions(method, parts[1:])
            if parts == ["mat"] and method == "GET":
                return self.send_json({"check_bars": mat_mod.CHECK_BARS, "tolerance_mm": mat_mod.CHECK_TOLERANCE_MM})
            if parts == ["survey"] and method == "GET":
                return self.send_json({"sections": survey_mod.SECTIONS})
            if parts == ["survey", "evaluate"] and method == "POST":
                _, _, evaluation = evaluate_survey(self.json_body())
                return self.send_json(evaluation)
            if parts[:1] == ["captures"]:
                self.require_local()
                return self.api_captures(method, parts[1:])
            if parts == ["measurements.csv"] and method == "GET":
                self.require_local()
                return self.measurements_csv()
            if parts == ["studio"] and method == "GET":
                self.require_local()
                return self.send_json(self.studio_info())
            if parts == ["studio", "pairing"] and method == "GET":
                self.require_local()
                return self.send_json(self.pairing())
            raise FileNotFoundError

        def pairing(self) -> dict:
            """What the iPhone app needs to send scans straight to this studio.

            Shown as a QR code in the studio (so only someone already in the
            studio can see it): the address the phone should use, the studio
            key, and, for this computer's own self-signed HTTPS, the SHA-256
            fingerprint of its certificate, so the app trusts exactly this
            computer and nothing pretending to be it.
            """
            if public:
                host = self.headers.get("Host", "")
                if not host:
                    return dict(available=False, reason="Open the studio through its public address to pair.")
                return dict(available=True, url=f"https://{host}", key=studio_key, fingerprint=None)
            info = self.studio_info()
            if not info["phones_can_connect"] or not cert_fingerprint:
                return dict(available=False,
                            reason="Phones can't reach this studio yet. Restart footscan with "
                                   "--host 0.0.0.0 --https, then open this page again.")
            return dict(available=True, url=info["scan_url"].rstrip("/"), key=studio_key, fingerprint=cert_fingerprint)

        def insole_api(self, method: str, d: Path, rest: list[str]):
            """First-fit insole from a foot capture: POST makes it, GET <file> downloads it."""
            out = d / "insole"
            if method == "GET" and len(rest) == 1:
                name = rest[0]
                if name not in INSOLE_FILES:
                    raise FileNotFoundError
                if not insole_downloadable(d, read_json(d / "capture.json")):
                    return self.send_json({"error": "this insole doesn't match the scan's current 3D model "
                                                    "(it changed, or the last attempt failed): make the insole again"},
                                          HTTPStatus.CONFLICT)
                f = out / name
                if not f.is_file():
                    raise FileNotFoundError
                return self.send_file(f, INSOLE_FILES[name], headers={
                    "Content-Disposition": f'attachment; filename="{d.name}-{name}"'} if not name.endswith(".html") else None)
            if method == "POST" and not rest:
                # One build per capture at a time (two studio tabs): the second waits for the first.
                with insole_locks.setdefault(d.name, threading.Lock()):
                    meta = read_json(d / "capture.json")
                    foot = meta.get("foot")
                    if foot not in FEET:
                        raise BadRequest("an insole needs a foot capture (left or right)")
                    result = make_insole(d, meta)
                    if "error" in result:  # a failed attempt leaves nothing printable behind
                        shutil.rmtree(d / "insole", ignore_errors=True)
                    meta = read_json(d / "capture.json")  # re-read: don't undo other changes made meanwhile
                    meta["insole"] = result
                    write_json(d / "capture.json", meta)
                return self.send_json(result)
            raise FileNotFoundError

        def studio_info(self) -> dict:
            host, port = self.server.server_address[:2]
            scheme = "https" if secure_cookie else "http"
            reachable = host not in ("127.0.0.1", "localhost", "::1")
            ip = lan_ip() if host in ("0.0.0.0", "::") else host
            return dict(
                scan_url=f"{scheme}://{ip}:{port}/" if reachable and ip else None,
                https=secure_cookie,
                phones_can_connect=reachable and secure_cookie,
            )

        # -- customer submissions ------------------------------------------
        def submission(self, sid: str) -> tuple[Path, dict]:
            if not ID_RE.match(sid):
                raise BadRequest("bad submission id")
            d = submissions_dir / sid
            if not (d / "submission.json").exists():
                raise FileNotFoundError
            return d, read_json(d / "submission.json")

        def require_token(self, meta: dict):
            token = self.headers.get("X-Upload-Token", "")
            expected = meta.get("upload_token")
            if not expected or not hmac.compare_digest(token, expected):
                raise Forbidden("upload closed or invalid upload token")

        def api_submissions(self, method: str, p: list[str]):
            if not p:
                if method == "POST":
                    info = validate_submission(self.json_body())
                    if not limiter.allow(self.client_id()):
                        return self.send_json({"error": "too many new scans from here; try again later"},
                                              HTTPStatus.TOO_MANY_REQUESTS)
                    submissions_dir.mkdir(parents=True, exist_ok=True)
                    sid = new_id("sub-", submissions_dir)
                    (submissions_dir / sid).mkdir()
                    token = secrets.token_urlsafe(24)
                    meta = dict(
                        id=sid, created=now_iso(), status="uploading",
                        history=[dict(at=now_iso(), status="uploading", note="submission started")],
                        acknowledged_at=now_iso(), upload_token=token,
                        scans={p["key"]: dict(foot=p["foot"], condition=p["condition"], label=p["label"], status="pending")
                               for p in info["plan"]},
                        **info,
                    )
                    write_json(submissions_dir / sid / "submission.json", meta)
                    return self.send_json({"id": sid, "upload_token": token, "plan": info["plan"], "flags": info["flags"]},
                                          HTTPStatus.CREATED)
                if method == "GET":
                    self.require_local()
                    return self.send_json(list_submissions(submissions_dir))
                raise FileNotFoundError

            d, meta = self.submission(p[0])
            rest = p[1:]

            if rest == [] and method == "GET":
                self.require_local()
                return self.send_json(public_meta(meta))

            if rest == [] and method == "DELETE":
                # Privacy: the person can ask for their photos to be removed.
                self.require_local()
                shutil.rmtree(d)
                return self.send_json({"ok": True, "deleted": meta["id"]})

            if rest == ["rescan"] and method == "POST":
                self.require_local()
                body = self.json_body()
                keys = body.get("scans")
                if not isinstance(keys, list) or not keys or not set(keys) <= set(meta["scans"]):
                    raise BadRequest("scans: choose which of this submission's scans to redo")
                token = secrets.token_urlsafe(24)
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                for key in keys:
                    # Keep the old photos for comparison rather than deleting them.
                    if (d / key).exists():
                        (d / "_previous").mkdir(exist_ok=True)
                        (d / key).rename(d / "_previous" / f"{key}-{stamp}")
                    ident = {k: meta["scans"][key][k] for k in ("foot", "condition", "label")}
                    meta["scans"][key] = dict(**ident, status="pending", rescan_requested=now_iso())
                note = str(body.get("note", "")).strip()[:500]
                meta.update(status="needs_rescan", upload_token=token,
                            rescan=dict(scans=keys, note=note, requested_at=now_iso()))
                meta["history"].append(dict(at=now_iso(), status="needs_rescan",
                                            note=f"rescan requested: {', '.join(keys)}" + (f" · {note}" if note else "")))
                write_json(d / "submission.json", meta)
                return self.send_json({"ok": True, "path": f"/?rescan={meta['id']}&t={token}", "scans": keys})

            if rest == ["rescan"] and method == "GET":
                # The person following a rescan link: only what they need to redo it.
                self.require_token(meta)
                if not meta.get("rescan"):
                    raise FileNotFoundError
                plan = [dict(key=k, **{f: meta["scans"][k][f] for f in ("foot", "condition", "label")},
                             why="We need new photos for this one.") for k in meta["rescan"]["scans"]]
                return self.send_json(dict(name=meta["name"], note=meta["rescan"]["note"], plan=plan))

            if rest == ["status"] and method == "POST":
                self.require_local()
                body = self.json_body()
                status = body.get("status")
                if status not in OPERATOR_STATUSES:
                    raise BadRequest(f"status must be one of {sorted(OPERATOR_STATUSES)}")
                meta["status"] = status
                meta["history"].append(dict(at=now_iso(), status=status, note=str(body.get("note", ""))[:1000]))
                write_json(d / "submission.json", meta)
                return self.send_json(public_meta(meta))

            if rest == ["submit"] and method == "POST":
                self.require_token(meta)
                incomplete = [f for f, s in meta["scans"].items() if s.get("status") != "complete"]
                if incomplete:
                    raise BadRequest(f"scan not finished for: {', '.join(incomplete)}")
                note = "sent by customer"
                if meta.get("rescan"):
                    # The mat may have been reprinted since: check it again.
                    body = json.loads(self.read_body(MAX_JSON_BYTES)) if int(self.headers.get("Content-Length") or 0) else {}
                    done = dict(meta.pop("rescan"), mat_check=validate_mat_check(body), sent=now_iso())
                    meta.setdefault("rescans", []).append(done)
                    note = f"rescan sent: {', '.join(done['scans'])}"
                meta.update(status="received", submitted=now_iso(), upload_token=None)
                meta["history"].append(dict(at=now_iso(), status="received", note=note))
                write_json(d / "submission.json", meta)
                return self.send_json({"ok": True})

            if len(rest) >= 3 and rest[0] == "scans":
                key = rest[1]
                if key not in meta["scans"]:
                    raise FileNotFoundError
                scan_dir = d / key
                ident = {k: meta["scans"][key][k] for k in ("foot", "condition", "label")}
                if rest[2] == "start" and len(rest) == 3 and method == "POST":
                    self.require_token(meta)
                    shutil.rmtree(scan_dir, ignore_errors=True)
                    scan_dir.mkdir()
                    meta["scans"][key] = dict(**ident, status="scanning", started=now_iso())
                    write_json(d / "submission.json", meta)
                    return self.send_json({"ok": True})
                if rest[2] == "frames" and len(rest) == 4:
                    if method == "PUT":
                        self.require_token(meta)
                        if not scan_dir.is_dir():
                            raise BadRequest("call start before uploading frames")
                        n = int(rest[3])
                        self.save_jpeg(scan_dir / f"frame_{n:04d}.jpg", n)
                        return self.send_json({"ok": True})
                    if method == "GET" and rest[3].endswith(".jpg"):
                        self.require_local()
                        f = scan_dir / f"frame_{int(rest[3][:-4]):04d}.jpg"
                        if not f.is_file():
                            raise FileNotFoundError
                        return self.send_file(f, "image/jpeg")
                if rest[2] in ("picks", "viewer.bin"):
                    self.require_local()
                    scan = meta["scans"][key]
                    return self.picks_api(method, scan_dir, rest[2:], dict(
                        foot=scan["foot"], condition=scan["condition"], session=meta["id"],
                        capture_id=f"{meta['id']}-{key}", load_kg=scan.get("load_kg")))
                if rest[2] == "recon":
                    self.require_local()
                    scan = meta["scans"][key]
                    if rest[3:] == [] and method == "POST":
                        if scan.get("status") != "complete":
                            raise BadRequest("this scan isn't finished")
                        # What the reconstruction needs to know, next to the photos.
                        write_json(scan_dir / "capture.json", dict(
                            capture_id=f"{meta['id']}/{key}", foot=scan["foot"], condition=scan["condition"],
                            mat_paper=(scan.get("summary") or {}).get("mat_paper"),
                            frames=[{"file": f} for f in scan.get("frame_files", [])]))
                    return self.recon_api(method, scan_dir, rest[3:], calibration_object=False)
                if rest[2] == "complete" and len(rest) == 3 and method == "POST":
                    self.require_token(meta)
                    body = self.json_body()
                    frames = body.get("frames", [])
                    if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
                        raise BadRequest("frames must be a list")
                    files = sorted(x.name for x in scan_dir.glob("frame_*.jpg"))
                    if not files:
                        raise BadRequest("no frames uploaded")
                    meta["scans"][key] = dict(
                        **ident, status="complete", completed=now_iso(), frame_files=files, frames=frames,
                        summary=body.get("summary", {}), load_kg=parse_load(body.get("load_kg")),
                    )
                    write_json(d / "submission.json", meta)
                    return self.send_json({"ok": True, "frames_on_disk": len(files)})
            raise FileNotFoundError

        # -- 3D models (Phase 2, operator only) ----------------------------
        def recon_api(self, method: str, folder: Path, rest: list[str], calibration_object: bool):
            """rest is what follows .../recon: [] or [file name]."""
            if rest == [] and method == "GET":
                return self.send_json(recon_jobs.summary(folder, runner))
            if rest == [] and method == "POST":
                if not any(folder.glob("frame_*.jpg")):
                    raise BadRequest("this capture has no photos to build a model from")
                try:
                    runner.start(folder, calibration_object)
                except recon_jobs.Busy as e:
                    return self.send_json({"error": str(e)}, HTTPStatus.CONFLICT)
                return self.send_json(recon_jobs.summary(folder, runner), HTTPStatus.ACCEPTED)
            if len(rest) == 1 and method == "GET" and rest[0] in recon_jobs.RECON_FILES:
                f = folder / "recon" / rest[0]
                if not f.is_file():
                    raise FileNotFoundError
                download = f"{folder.name}-{rest[0]}"
                return self.send_file(f, recon_jobs.RECON_FILES[rest[0]],
                                      headers={"Content-Disposition": f'attachment; filename="{download}"'})
            raise FileNotFoundError

        # -- landmarks (Phase 3, operator only) -----------------------------
        def picks_api(self, method: str, folder: Path, rest: list[str], ident: dict):
            from . import landmarks as lm_mod

            if ident.get("foot") not in FEET:
                raise BadRequest("landmarks are for foot scans")
            if rest == ["viewer.bin"] and method == "GET":
                f = lm_mod.viewer_path(folder)
                if f is None:
                    raise FileNotFoundError
                return self.send_file(f, "application/octet-stream")
            if rest == ["picks"] and method == "GET":
                mat = lm_mod.in_mat_frame(folder)
                frame = None
                if (folder / "recon" / "plantar.json").exists():  # the reconstruction's provisional foot frame
                    frame = read_json(folder / "recon" / "plantar.json").get("frame")
                return self.send_json(dict(
                    foot=ident["foot"], condition=ident["condition"], in_mat_frame=mat, provisional_frame=frame,
                    has_model=lm_mod.viewer_path(folder) is not None,
                    # the model's fingerprint: saves send it back, so clicks on a model
                    # that was rebuilt meanwhile are refused instead of mislabelled
                    mesh_sha256=lm_mod.sha256(lm_mod.mesh_path(folder)) if lm_mod.mesh_path(folder) else None,
                    spec=lm_mod.spec(ident["condition"], mat), picks=lm_mod.list_picks(folder)))
            if len(rest) == 2 and rest[0] == "picks" and rest[1].isdigit():
                n = int(rest[1])
                if method == "PUT":
                    try:
                        return self.send_json(lm_mod.save_pick(folder, n, self.json_body(), ident))
                    except lm_mod.LandmarkError as e:
                        raise BadRequest(str(e)) from None
                if method == "DELETE":
                    (folder / "landmarks" / f"pick-{n}.json").unlink(missing_ok=True)
                    return self.send_json({"ok": True})
            raise FileNotFoundError

        def measurements_csv(self):
            import csv
            import io

            from . import landmarks as lm_mod
            from .cli import FIELDS

            folders = sorted(f.parent for f in captures_dir.glob("*/capture.json")) if captures_dir.exists() else []
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(lm_mod.export_rows(folders))
            data = buf.getvalue().encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="scan_measurements.csv"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # -- research captures (operator only) -----------------------------
        def api_captures(self, method: str, p: list[str]):
            if not p and method == "GET":
                return self.send_json(list_captures(captures_dir))
            if not p and method == "POST":
                setup = validate_setup(self.json_body())
                captures_dir.mkdir(parents=True, exist_ok=True)
                tag = setup["foot"][0].upper() if setup["foot"] else "X"
                cid = new_id(f"{setup['session']}_{setup['condition']}_{tag}_", captures_dir)
                (captures_dir / cid).mkdir()
                write_json(captures_dir / cid / "capture.json",
                           dict(capture_id=cid, created=now_iso(), status="uploading", frames=[], **setup))
                return self.send_json({"id": cid}, HTTPStatus.CREATED)
            if not p or not ID_RE.match(p[0]):
                raise BadRequest("bad capture id")
            d = captures_dir / p[0]
            if not (d / "capture.json").exists():
                raise FileNotFoundError
            if len(p) == 3 and p[1] == "frames":
                if method == "PUT":
                    n = int(p[2])
                    self.save_jpeg(d / f"frame_{n:04d}.jpg", n)
                    return self.send_json({"ok": True})
                if method == "GET" and p[2].endswith(".jpg"):
                    f = d / f"frame_{int(p[2][:-4]):04d}.jpg"
                    if not f.is_file():
                        raise FileNotFoundError
                    return self.send_file(f, "image/jpeg")
            if p[1:2] in (["picks"], ["viewer.bin"]):
                meta = read_json(d / "capture.json")
                return self.picks_api(method, d, p[1:], dict(
                    foot=meta.get("foot"), condition=meta.get("condition"), session=meta.get("session"),
                    capture_id=meta.get("capture_id", p[0]), load_kg=meta.get("load_kg")))
            if p[1:2] == ["recon"]:
                meta = read_json(d / "capture.json")
                return self.recon_api(method, d, p[2:], meta.get("condition") == "calibration")
            if p[1:] == ["calipers"] and method == "PUT":
                calipers = recon_jobs.validate_calipers(self.json_body())
                write_json(d / "calipers.json", calipers)
                # A built model only needs its comparison redone, not a rebuild.
                updating = False
                meta = read_json(d / "capture.json")
                if meta.get("condition") == "calibration" and meta.get("method") == "imported_mesh" and meta.get("mesh"):
                    # An imported model: re-scoring takes seconds, so do it now.
                    meta["accuracy"] = score_imported(d, meta["mesh"].get("up", "y"))
                    write_json(d / "capture.json", meta)
                    return self.send_json({"ok": True, "calipers": calipers, "updating": False,
                                           "accuracy": meta["accuracy"]})
                built = recon_jobs.summary(d, runner).get("state") == "done"
                if meta.get("condition") == "calibration" and built and (d / "recon" / "mesh.ply").exists():
                    try:
                        runner.start(d, calibration_object=True, accuracy_only=True)
                        updating = True
                    except recon_jobs.Busy:
                        pass
                return self.send_json({"ok": True, "calipers": calipers, "updating": updating})
            if p[1:] == ["mesh"] and method == "PUT":
                ext = (query_param(self.path, "ext") or "").lower()
                if ext not in MESH_TYPES:
                    raise BadRequest(f"3D file must be one of {sorted(MESH_TYPES)} (export from your scanning app)")
                up = (query_param(self.path, "up") or "y").lower()
                if up not in UP_AXES:
                    raise BadRequest(f"up must be one of {sorted(UP_AXES)}")
                raw = d / f"original.{ext}"
                raw.write_bytes(self.read_body(MAX_MESH_BYTES))
                try:
                    stats = import_mesh(raw, d / "mesh.ply")
                except Exception as e:  # noqa: BLE001 - any parse failure is the file's fault
                    raw.unlink(missing_ok=True)
                    raise BadRequest(f"couldn't read that 3D file: {e}") from None
                stats["up"] = up
                meta = read_json(d / "capture.json")
                meta.update(status="complete", mesh=stats, frame_files=[])
                # an insole made from the old model no longer matches: remove it
                meta.pop("insole", None)
                shutil.rmtree(d / "insole", ignore_errors=True)
                # The calibration object made by another app (e.g. the iPhone
                # test app): score it now, against the object's true shape.
                if meta.get("condition") == "calibration":
                    meta["accuracy"] = score_imported(d, up)
                write_json(d / "capture.json", meta)
                return self.send_json({"ok": True, "mesh": stats, "accuracy": meta.get("accuracy")})
            if p[1:] == ["accuracy"] and method == "GET":
                f = d / "accuracy.json"
                if not f.is_file():
                    raise FileNotFoundError
                return self.send_file(f, "application/json")
            if p[1:2] == ["insole"]:
                return self.insole_api(method, d, p[2:])
            if p[1:] == ["complete"] and method == "POST":
                body = self.json_body()
                frames = body.get("frames", [])
                if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
                    raise BadRequest("frames must be a list")
                meta = read_json(d / "capture.json")
                files = sorted(x.name for x in d.glob("frame_*.jpg"))
                meta.update(status="complete", frames=frames, frame_files=files, summary=body.get("summary", {}))
                write_json(d / "capture.json", meta)
                return self.send_json({"ok": True, "frames_on_disk": len(files)})
            raise FileNotFoundError

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_PUT(self):
            self.route("PUT")

        def do_DELETE(self):
            self.route("DELETE")

    return Handler


def query_param(path: str, name: str) -> str | None:
    from urllib.parse import parse_qs, urlsplit

    return (parse_qs(urlsplit(path).query).get(name) or [None])[0]


def import_mesh(src: Path, dst: Path) -> dict:
    """Load a 3D scan exported from a phone app and save it as PLY in millimetres.

    LiDAR apps (Polycam, Scaniverse, 3d Scanner App) export in metres; other
    tools use millimetres. A foot is roughly 0.2-0.35 m long, so the largest
    dimension tells the units apart unambiguously.
    """
    from .recon import viewer_data
    from .recon.imported import load_geometry, to_millimetres

    mesh, units, factor = to_millimetres(load_geometry(src))
    mesh.export(dst)
    viewer_data.write(mesh, dst.parent / "viewer.bin")
    ext = [round(float(v), 1) for v in sorted(mesh.extents, reverse=True)]
    return dict(
        source_file=src.name, vertices=int(len(mesh.vertices)), faces=int(len(mesh.faces)),
        units_detected=units, scale_to_mm=factor, extents_mm=ext, watertight=bool(mesh.is_watertight),
        file="mesh.ply",
    )


UP_AXES = ("y", "z")
INSOLE_FILES = {"insole.3mf": "model/3mf", "insole.stl": "model/stl",
                "summary.html": "text/html; charset=utf-8", "print-notes.txt": "text/plain; charset=utf-8",
                "insole.json": "application/json"}


def insole_source(folder: Path, meta: dict) -> Path | None:
    """The model an insole is made from: the imported model, else footscan's reconstruction."""
    if meta.get("method") == "imported_mesh" and (folder / "mesh.ply").is_file():
        return folder / "mesh.ply"
    if (folder / "recon" / "mesh.ply").is_file():
        return folder / "recon" / "mesh.ply"
    return None


def source_stamp(path: Path | None) -> str | None:
    """Cheap fingerprint of a model file (size and modification time): changes when it's replaced or rebuilt."""
    if path is None or not path.is_file():
        return None
    st = path.stat()
    return f"{path.name}:{st.st_size}:{st.st_mtime_ns}"


def insole_is_stale(folder: Path, meta: dict) -> bool:
    """Was this capture's model replaced or rebuilt after its insole was made?"""
    ins = meta.get("insole") or {}
    return bool(ins) and "error" not in ins and ins.get("source") != source_stamp(insole_source(folder, meta))


def insole_downloadable(folder: Path, meta: dict) -> bool:
    """Only an insole from a successful build whose source model is still the current one."""
    ins = meta.get("insole") or {}
    current = source_stamp(insole_source(folder, meta))
    return bool(ins) and "error" not in ins and current is not None and ins.get("source") == current


def make_insole(folder: Path, meta: dict) -> dict:
    """First-fit insole for a foot capture: an imported model (iPhone app) or a footscan reconstruction.

    Files go to <capture>/insole/. Returns a short report (or {"error": ...}).
    """
    import shutil

    from . import insole as insole_mod
    from .recon import foot_prep
    from .recon.imported import load_geometry

    foot = meta["foot"]
    stamp = source_stamp(insole_source(folder, meta))
    try:
        if meta.get("method") == "imported_mesh" and (folder / "mesh.ply").is_file():
            up = (meta.get("mesh") or {}).get("up", "y")
            ins, _ = foot_prep.insole_from_object_capture(load_geometry(folder / "mesh.ply"), foot, up=up)
            source = f"imported model ({(meta.get('notes') or 'scanning app')[:80]})"
        elif (folder / "recon" / "mesh.ply").is_file():
            ins = insole_mod.from_scan(load_geometry(folder / "recon" / "mesh.ply"), foot)
            source = "footscan photo reconstruction"
        else:
            return dict(error="this capture has no 3D model yet: build it (3D model) or import one first")
    except (ValueError, insole_mod.InsoleError) as e:
        return dict(error=str(e))
    except Exception as e:  # noqa: BLE001 - an unreadable or broken model is reported, never a crash
        return dict(error=f"couldn't make an insole from this model ({type(e).__name__}: {e})")
    out = folder / "insole"
    tmp = folder / f"insole.part-{secrets.token_hex(4)}"  # this request's own: never shared with another
    try:
        insole_mod.write_outputs(ins, tmp, "insole", f"{meta.get('capture_id', folder.name)}, {source}")
        (tmp / "insole-summary.html").rename(tmp / "summary.html")  # fixed names, so the studio can link them
        old = folder / f"insole.old-{secrets.token_hex(4)}"
        if out.exists():
            out.rename(old)
        tmp.rename(out)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    r = ins.report
    return dict(made=now_iso(), foot=foot, length_mm=r["length_mm"], width_mm=r["width_mm"], height_mm=r["height_mm"],
                max_fill_mm=r["max_fill_mm"], sole=r["sole"], bed=r["bed_fit"], warnings=r["warnings"],
                files=sorted(INSOLE_FILES), source=stamp)


def score_imported(folder: Path, up: str) -> dict:
    """Accuracy study of an imported calibration-object model (see recon/imported.py)."""
    from .recon.imported import score_capture

    try:
        return score_capture(folder, up)
    except Exception as e:  # noqa: BLE001 - a model the study can't use is reported, not a crash
        return dict(error=f"the accuracy study couldn't run on this model: {e}")


def public_meta(meta: dict) -> dict:
    """Submission as the studio sees it: never includes the upload token."""
    out = {k: v for k, v in meta.items() if k != "upload_token"}
    out["scans"] = {f: {k: v for k, v in s.items() if k != "frames"} for f, s in meta.get("scans", {}).items()}
    return out


def list_submissions(submissions_dir: Path) -> list[dict]:
    out = []
    for f in submissions_dir.glob("*/submission.json") if submissions_dir.exists() else []:
        try:
            out.append(public_meta(read_json(f)))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda m: m.get("created", ""), reverse=True)


def list_captures(captures_dir: Path) -> list[dict]:
    out = []
    for f in captures_dir.glob("*/capture.json") if captures_dir.exists() else []:
        try:
            meta = read_json(f)
        except json.JSONDecodeError:
            continue
        meta.pop("frames", None)
        if meta.get("insole") and insole_is_stale(f.parent, meta):
            meta["insole"] = {**meta["insole"], "stale": True}
        out.append(meta)
    return sorted(out, key=lambda m: m.get("created", ""), reverse=True)


def ensure_cert(cert_dir: Path) -> tuple[Path, Path]:
    cert, key = cert_dir / "cert.pem", cert_dir / "key.pem"
    if not cert.exists():
        cert_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "825",
             "-keyout", str(key), "-out", str(cert), "-subj", "/CN=footscan-local"],
            check=True, capture_output=True,
        )
    return cert, key


def cert_fingerprint(cert_path: Path) -> str:
    """SHA-256 of the certificate (DER), hex: what the iPhone app pins."""
    der = ssl.PEM_cert_to_DER_cert(cert_path.read_text())
    return hashlib.sha256(der).hexdigest()


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def serve(host: str = "127.0.0.1", port: int = 8765, https: bool = False, public: bool = False,
          data_dir: Path | None = None, allow_indexing: bool | None = None) -> None:
    """Run the site. ``public``: reachable from the internet through a tunnel or
    proxy, so nothing is trusted for being "local" and only the studio key
    opens the studio."""
    studio_key = load_studio_key(ROOT / ".studio_key")
    if allow_indexing is None:
        allow_indexing = not public  # on the internet, hidden from search engines unless asked otherwise
    cert_fp = None
    if https:
        cert_path, key_path = ensure_cert(ROOT / ".certs")
        cert_fp = cert_fingerprint(cert_path)
    handler = make_handler(data_dir=(data_dir or DATA_DIR).resolve(), studio_key=studio_key,
                           secure_cookie=https or public, local_check=never_local if public else is_loopback,
                           allow_indexing=allow_indexing, public=public, cert_fingerprint=cert_fp)
    httpd = ThreadingHTTPServer((host, port), handler)
    scheme = "http"
    if https:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    print("footscan - NOT a medical device", flush=True)
    if public:
        print("PUBLIC MODE: the studio opens only with the studio key, even on this computer.")
        print(f"studio link (keep private): <your public address>/studio/?key={studio_key}")
    print(f"studio on this computer: {scheme}://localhost:{port}/studio/" + (f"?key={studio_key}" if public else ""))
    if host == "0.0.0.0" and (ip := lan_ip()):
        print(f"scan page for phones on this Wi-Fi: {scheme}://{ip}:{port}/")
        print(f"studio on YOUR phone (keep this private): {scheme}://{ip}:{port}/studio/?key={studio_key}")
    else:
        print(f"scan page: {scheme}://localhost:{port}/")
    print("", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
