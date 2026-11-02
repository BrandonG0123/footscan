"""How the studio's server handles connections: HTTPS handshakes and keep-alive.

The phone loads the capture page (15 files: the page, its scripts and its stylesheet) over Wi-Fi before the
camera opens. These tests pin the two things that decide how long that takes: a connection is set up in its own
thread (so one slow or stuck phone connection doesn't hold up the others), and a connection is reused for
the next request instead of being closed after each one.
"""

import http.client
import socket
import ssl
import threading

import pytest

from footscan.server import WEB_DIR, StudioServer, ensure_cert, make_handler

KEY = "test-studio-key"


@pytest.fixture
def https_server(tmp_path):
    cert, key = ensure_cert(tmp_path / "certs")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    httpd = StudioServer(("127.0.0.1", 0), make_handler(WEB_DIR, tmp_path / "data"), ssl_context=ctx)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def http_server(tmp_path):
    httpd = StudioServer(("127.0.0.1", 0), make_handler(WEB_DIR, tmp_path / "data", studio_key=KEY))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def trusting_client() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the studio's own self-signed certificate
    return ctx


def test_a_connection_that_never_finishes_its_handshake_does_not_block_other_visitors(https_server):
    # A phone that opens a connection and goes quiet (asleep, or out of Wi-Fi range mid-way).
    stuck = socket.create_connection(("127.0.0.1", https_server))
    try:
        conn = http.client.HTTPSConnection("127.0.0.1", https_server, timeout=3, context=trusting_client())
        conn.request("GET", "/studio/capture.html")
        resp = conn.getresponse()
        assert resp.status == 200
        assert b"Open camera" in resp.read()
        conn.close()
    finally:
        stuck.close()


def test_page_files_are_fetched_over_one_reused_https_connection(https_server):
    conn = http.client.HTTPSConnection("127.0.0.1", https_server, timeout=3, context=trusting_client())
    conn.connect()
    first_socket = conn.sock
    for path in ("/studio/capture.html", "/assets/scanner.js", "/assets/style.css", "/mat/footscan-mat-a4.json"):
        conn.request("GET", path)
        resp = conn.getresponse()
        assert resp.status == 200, path
        resp.read()
        assert resp.getheader("Connection", "").lower() != "close"
    assert conn.sock is first_socket  # http.client opens a new socket if the server closed the old one
    conn.close()


def test_a_request_refused_before_its_body_was_read_closes_the_connection(http_server):
    # Leftover body bytes would otherwise be read as the start of the next request.
    for path, headers, status in [
        ("/index.html", {}, 405),  # not something that takes a POST: send_error
        ("/api/submissions", {"Origin": "https://elsewhere.example"}, 403),  # another site's request: send_json
    ]:
        conn = http.client.HTTPConnection("127.0.0.1", http_server, timeout=3)
        conn.request("POST", path, body=b"x" * 5000, headers={"Content-Type": "application/json", **headers})
        resp = conn.getresponse()
        assert resp.status == status, path
        assert resp.getheader("Connection", "").lower() == "close", path
        resp.read()
        conn.close()


def test_a_json_post_that_was_read_keeps_the_connection_open(http_server):
    conn = http.client.HTTPConnection("127.0.0.1", http_server, timeout=3)
    conn.connect()
    first_socket = conn.sock
    conn.request("POST", "/api/submissions", body=b"[1, 2]", headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 400  # not a JSON object: refused, but only after reading the whole body
    resp.read()
    assert resp.getheader("Connection", "").lower() != "close"
    conn.request("GET", "/robots.txt")
    again = conn.getresponse()
    assert again.status == 200
    assert b"User-agent" in again.read()
    assert conn.sock is first_socket
    conn.close()


def test_an_upload_that_asks_to_continue_gets_a_bare_go_ahead_then_its_answer(http_server):
    # curl sends "Expect: 100-continue" before a large upload and waits for the go-ahead.
    body = b"[1, 2]"
    with socket.create_connection(("127.0.0.1", http_server), timeout=3) as s:
        s.sendall(b"POST /api/submissions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                  b"Expect: 100-continue\r\nContent-Length: %d\r\n\r\n" % len(body))
        go_ahead = b""
        while b"\r\n\r\n" not in go_ahead:
            go_ahead += s.recv(1)
        assert go_ahead == b"HTTP/1.1 100 Continue\r\n\r\n"
        s.sendall(body)
        resp = http.client.HTTPResponse(s)
        resp.begin()
        assert resp.status == 400  # read, then refused: not a JSON object
        assert resp.getheader("Connection", "").lower() != "close"
        resp.read()


def test_the_studio_key_cookie_goes_only_on_the_answer_to_the_link_that_carried_the_key(http_server):
    # One connection, two requests: the second must not be handed the first one's Set-Cookie.
    conn = http.client.HTTPConnection("127.0.0.1", http_server, timeout=3)
    conn.request("GET", f"/studio/?key={KEY}")
    first = conn.getresponse()
    first.read()
    assert first.status == 200
    assert KEY in (first.getheader("Set-Cookie") or "")
    for path in ("/studio/capture.html", "/index.html", "/assets/scanner.js"):
        conn.request("GET", path)
        resp = conn.getresponse()
        resp.read()
        assert resp.getheader("Set-Cookie") is None, path
    conn.close()


@pytest.mark.parametrize("framing", [
    b"Transfer-Encoding: chunked\r\nContent-Length: 6\r\n",  # framed two ways
    b"Transfer-Encoding: chunked\r\n",
    b"Content-Length: -5\r\n",
])
def test_a_body_with_unusable_framing_is_refused_and_ends_the_connection(http_server, framing):
    with socket.create_connection(("127.0.0.1", http_server), timeout=3) as s:
        s.sendall(b"POST /api/submissions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                  + framing + b"\r\n6\r\n[1, 2]\r\n0\r\n\r\nGET /robots.txt HTTP/1.1\r\nHost: x\r\n\r\n")
        resp = http.client.HTTPResponse(s)
        resp.begin()
        assert resp.status in (400, 501)
        assert resp.getheader("Connection", "").lower() == "close"
        resp.read()
        assert s.recv(100) == b""  # nothing more: the bytes after it weren't taken as another request
