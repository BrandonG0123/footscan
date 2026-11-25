"""The studio library's server side: one capture as listed, and the picture of each 3-D model (thumbnails.py)."""

from test_server import _object_capture_foot, body, call, servers  # noqa: F401 - servers is a fixture

PNG = b"\x89PNG\r\n\x1a\n"


def _imported(op, foot="right"):
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "swb", "foot": foot, "session": "LIDAR", "load_kg": 30,
                                                    "method": "imported_mesh"}))["id"]
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot(foot),
                {"Content-Type": "application/octet-stream"})[0] == 200
    return cid


def test_a_capture_with_a_model_has_a_picture_drawn_once_and_kept(servers):
    op, phone, data = servers
    cid = _imported(op)
    status, png, h = call(f"{op}/api/captures/{cid}/thumb.png")
    assert status == 200 and png.startswith(PNG) and h["Content-Type"] == "image/png"
    kept = list((data / "captures" / cid).glob("thumb-*.png"))
    assert len(kept) == 1 and kept[0].read_bytes() == png
    mtime = kept[0].stat().st_mtime_ns
    assert call(f"{op}/api/captures/{cid}/thumb.png")[1] == png
    assert kept[0].stat().st_mtime_ns == mtime  # not drawn again
    assert call(f"{phone}/api/captures/{cid}/thumb.png")[0] == 403  # a picture of a foot: the studio's only


def test_a_replaced_model_gets_a_new_picture_and_the_old_one_goes(servers):
    op, _, data = servers
    cid = _imported(op)
    call(f"{op}/api/captures/{cid}/thumb.png")
    first = list((data / "captures" / cid).glob("thumb-*.png"))
    assert call(f"{op}/api/captures/{cid}/mesh?ext=obj&up=y", "PUT", _object_capture_foot("left"),
                {"Content-Type": "application/octet-stream"})[0] == 200
    assert call(f"{op}/api/captures/{cid}/thumb.png")[0] == 200
    now = list((data / "captures" / cid).glob("thumb-*.png"))
    assert len(now) == 1 and now != first


def test_a_capture_without_a_model_has_no_picture(servers):
    op, _, _ = servers
    cid = body(call(f"{op}/api/captures", "POST", {"condition": "object", "session": "S1"}))["id"]
    assert call(f"{op}/api/captures/{cid}/thumb.png")[0] == 404


def test_a_model_that_cant_be_drawn_is_answered_not_dropped(servers, monkeypatch):
    from footscan import thumbnails

    op, _, _ = servers
    cid = _imported(op)

    def broken(model, up="y"):
        raise ValueError("no faces")

    monkeypatch.setattr(thumbnails, "draw", broken)
    status, raw, _ = call(f"{op}/api/captures/{cid}/thumb.png")
    assert status == 422 and "couldn't draw" in body((status, raw))["error"]


def test_one_capture_is_answered_as_the_library_lists_it(servers):
    op, phone, _ = servers
    cid = _imported(op)
    one = body(call(f"{op}/api/captures/{cid}"))
    listed = next(c for c in body(call(f"{op}/api/captures")) if c["capture_id"] == cid)
    assert one == listed and "frames" not in one
    assert call(f"{op}/api/captures/nope")[0] == 404
    assert call(f"{phone}/api/captures/{cid}")[0] == 403

