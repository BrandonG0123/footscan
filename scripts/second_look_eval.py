"""Would a Claude "second look" at a scan catch problems footscan's own checks miss? An evaluation.

Each case is a real scan, or a real scan with a known kind of damage, run through the same
preparation as Make insole. For each: what footscan's own checks say (its warnings), and, unless
--dry-run, what Claude says when shown four views of the prepared model and asked only whether the
SCAN looks complete (never about the foot's shape or health). The answers are scored against what
each case is known to be. Claude never changes the shape or gives a number; this decides only
whether an advisory "second look" is worth building.

  .venv/bin/python scripts/second_look_eval.py SCAN.obj [--mac-rebuild NAME=PATH ...] [--dry-run] [-o DIR]

SCAN is a sole-up scan as the iPhone app hands it over (metres, Y up). The damage is cut out of the
raw scan where the prepared model says (heel, toes, a side, under the arch), so it goes through the
whole preparation like a real flaw. Needs `pip install anthropic` and a key (ANTHROPIC_API_KEY, or an
`ant auth login` profile) unless --dry-run. Sends the four rendered views of each case (pictures of
the model, no photos of the person) to the Claude API. Roughly 8 requests.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from footscan.recon import foot_prep  # noqa: E402
from footscan.recon.imported import load_geometry  # noqa: E402

MODEL = "claude-opus-5-5"
VIEW_PX = 400
PROMPT = """These four pictures are views of one 3D scan of a person's bare or socked foot, made with a phone,
after it was turned so the sole faces down onto a flat floor (a footscan insole is made from the sole).
Top left: from below (the sole). Top right: from the heel's side, looking forward along the foot.
Bottom left and bottom right: from each side. Toes point up in the first picture.
The leg was cut off on purpose about 70 mm above the floor, and the cut was closed with a flat lid.

Judge only whether the SCAN is complete and usable: missing parts (heel, toes, a side), holes,
torn or doubled surfaces, things that aren't foot. Don't comment on the foot's shape, arch or health,
and don't estimate any sizes. If it looks like a complete foot, answer ok with no problems."""
SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "rescan"]},
        "problems": {"type": "array", "items": {
            "type": "object",
            "properties": {"part": {"type": "string", "enum": ["heel", "toes", "inner side", "outer side",
                                                                 "sole", "top", "other"]},
                           "what": {"type": "string"}},
            "required": ["part", "what"], "additionalProperties": False}},
    },
    "required": ["verdict", "problems"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- pictures
def _png(rgb: np.ndarray) -> bytes:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _view(mesh, right: np.ndarray, up: np.ndarray, px: int = VIEW_PX) -> np.ndarray:
    """Orthographic, shaded grey, z-buffered: the camera looks along right x up."""
    look = np.cross(right, up)
    V = np.asarray(mesh.vertices)
    P = np.c_[V @ right, V @ up, V @ look]
    lo, hi = P[:, :2].min(0), P[:, :2].max(0)
    s = (px - 20) / float((hi - lo).max())
    xy = (P[:, :2] - lo) * s + 10 + ((px - 20) - (hi - lo) * s) / 2
    img = np.full((px, px), 255.0)
    depth = np.full((px, px), np.inf)
    n = np.asarray(mesh.face_normals) @ look  # facing the camera: n < 0
    shade = 60 + 180 * np.clip(-n, 0, 1)
    for f, tri in enumerate(np.asarray(mesh.faces)):
        a, b, c = xy[tri]
        x0, y0 = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        x1, y1 = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        if x1 < 0 or y1 < 0 or x0 >= px or y0 >= px:
            continue
        X, Y = np.meshgrid(np.arange(max(x0, 0), min(x1, px - 1) + 1), np.arange(max(y0, 0), min(y1, px - 1) + 1))
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-12:
            continue
        w0 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / det
        w1 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / det
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        z = w0 * P[tri[0], 2] + w1 * P[tri[1], 2] + w2 * P[tri[2], 2]
        X, Y, z = X[inside], Y[inside], z[inside]
        nearer = z < depth[Y, X]
        depth[Y[nearer], X[nearer]] = z[nearer]
        img[Y[nearer], X[nearer]] = shade[f]
    return np.flipud(img)


def picture(placed) -> bytes:
    """Four views of a prepared model (mm, z up, toes +y): below, from the heel, both sides."""
    X, Y, Z = np.eye(3)
    # the camera looks along right x up and keeps the nearest surface: (-X, Z) looks along +y, from the heel
    views = [_view(placed, X, Y, VIEW_PX), _view(placed, -X, Z, VIEW_PX),
             _view(placed, Y, Z, VIEW_PX), _view(placed, -Y, Z, VIEW_PX)]
    grid = np.vstack([np.hstack(views[:2]), np.hstack(views[2:])])
    grid[VIEW_PX - 1:VIEW_PX + 1, :] = 0
    grid[:, VIEW_PX - 1:VIEW_PX + 1] = 0
    return _png(np.repeat(grid[:, :, None], 3, axis=2))


# --------------------------------------------------------------------------- cases
def damaged(scan, cut) -> object:
    """``scan`` without the faces whose prepared (mat-frame) position ``cut(x, y, z, length)`` selects."""
    # the cut maps the scan with to_mat, which holds everywhere only for a rigid preparation: toes as scanned
    lay, foot_prep.LAY_TOES_FLAT = foot_prep.LAY_TOES_FLAT, False
    try:
        placed, info = foot_prep.prepare_sole_up(scan, "y")
    finally:
        foot_prep.LAY_TOES_FLAT = lay
    T = np.asarray(info["to_mat"])
    C = np.c_[scan.triangles_center, np.ones(len(scan.faces))] @ T.T
    V = placed.vertices
    y0, length = V[:, 1].min(), np.ptp(V[:, 1])
    gone = cut(C[:, 0] - V[:, 0].mean(), (C[:, 1] - y0) / length, C[:, 2], length)
    out = scan.copy()
    out.update_faces(~gone)
    out.remove_unreferenced_vertices()
    return out


DAMAGE = {  # name: (cut in the prepared frame: x across from the middle (mm), y share from the heel, z mm)
    "toes missing (last 15%)": lambda x, y, z, L: y > 0.85,
    "heel underside missing": lambda x, y, z, L: (y < 0.25) & (z < 15),
    "one side missing (below 25 mm)": lambda x, y, z, L: (x > 15) & (z < 25),
    "hole under the arch": lambda x, y, z, L: (y > 0.35) & (y < 0.6) & (z < 25) & (np.abs(x) < 20),
}


def footscan_checks(scan) -> list[str]:
    ins, _ = foot_prep.insole_from_object_capture(scan, "right", kind="sole_up")
    return ins.report["warnings"]


def ask_claude(png: bytes) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(png).decode()}},
            {"type": "text", "text": PROMPT}]}],
    )
    if response.stop_reason == "refusal":
        return dict(verdict="declined", problems=[], usage=response.usage.to_dict())
    text = next(b.text for b in response.content if b.type == "text")
    return dict(json.loads(text), usage=response.usage.to_dict())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan")
    ap.add_argument("--mac-rebuild", action="append", default=[], metavar="NAME=PATH",
                    help="a rebuild of the same scan known to have lost the heel's underside")
    ap.add_argument("--dry-run", action="store_true", help="pictures and footscan's checks only; no API call")
    ap.add_argument("-o", "--out", default="reports/second-look", help="folder for the pictures and results")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    scan = load_geometry(a.scan)
    cases = [("real scan, as it is", scan, False)]
    cases += [(f"real scan, {k}", damaged(scan, cut), True) for k, cut in DAMAGE.items()]
    cases += [(f"{name} (heel underside lost)", load_geometry(path), True)
              for name, path in (m.split("=", 1) for m in a.mac_rebuild)]

    rows = []
    for name, mesh, faulty in cases:
        warnings = footscan_checks(mesh)
        placed, _ = foot_prep.prepare_sole_up(mesh, "y")
        png = picture(placed)
        slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        (out / f"{slug}.png").write_bytes(png)
        # any warning about the scan counts; the routine note that the safety caps clipped some fill doesn't
        about_scan = [w for w in warnings if not w.startswith("the fill was clipped by the safety caps")]
        row = dict(case=name, faulty=faulty, footscan_flagged=bool(about_scan),
                   footscan_warnings=warnings, picture=f"{slug}.png")
        if not a.dry_run:
            row["claude"] = ask_claude(png)
            row["claude_flagged"] = row["claude"]["verdict"] == "rescan"
        rows.append(row)
        print(f"{name:48s} faulty={faulty!s:5s} footscan={row['footscan_flagged']!s:5s}"
              + ("" if a.dry_run else f" claude={row['claude']['verdict']}"), flush=True)
    (out / "results.json").write_text(json.dumps(rows, indent=2, default=str))

    def score(key):
        ok = [r for r in rows if key in r]
        return sum(r[key] == r["faulty"] for r in ok), len(ok)

    print("\nright calls: footscan's checks %d/%d" % score("footscan_flagged")
          + ("" if a.dry_run else ", Claude %d/%d" % score("claude_flagged")))
    print(f"pictures and results in {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
