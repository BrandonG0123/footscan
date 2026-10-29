"""Review packets: every new insole gets checked before anyone slices it.

The generator makes the geometry; nothing here changes it. When the studio
makes an insole, this module writes a *review packet* for it beside the data:

- ``review.json`` and ``packet.md``: the insole's own numbers (from its
  ``insole.json``), the shoe it has to fit (``review-spec.json``), and the
  result of each plain check below, PASS or FLAG, with the reason.
- ``top.png`` and ``side.png``: pictures of the insole drawn from its STL, so a
  reader (Brandon, or a Claude Code session in this folder) can see its shape
  without opening a slicer. ``pair.png`` when the other foot has an insole too.

The plain checks are arithmetic on the files, so they give the same answer
every time. What a picture is needed for (is the outline foot-shaped, is the
arch on the big-toe side, any spikes or holes) is left to the reader, and the
packet lists those questions. The Claude Code side is the ``review-insole``
skill in ``.claude/skills``; it writes its answer as ``claude-review.md`` in
the same folder and never edits the insole.

Packets live in ``<data>/reviews/<capture id>/<made>/``: one folder per
build, so a rebuild gets a fresh packet and the old one stays for comparison.
They hold pictures of a person's foot shape: ``data/`` is never committed.
"""

from __future__ import annotations

import json
import re
import struct
import time
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "review-spec.json"
MM_PER_PX = 0.5

DEFAULT_SPEC = dict(shoe="ASICS Gel Resolution X", size="US men's 9.5", target_length_mm=275.0,
                    target_length_source="size-chart insole length, not a ruler measurement",
                    length_tolerance_mm=1.0, pair_tolerance_mm=1.0,
                    tolerances_source="a judgment, not measured", slicer="Bambu Studio",
                    slicer_scale_percent=100, bed_mm=256.0)

# Questions only a look at the pictures can answer. The packet asks them; the reader answers in
# claude-review.md. Each says what a wrong answer would look like, so it can be checked, not felt.
LOOK_CHECKS = [
    ("outline", "Top view: is the outline foot-shaped (rounded heel at the left, wider forefoot at the right, "
                "no notches, spikes or straight cut edges)?"),
    ("handedness", "Top view: the top of the picture is the foot's left. For a RIGHT foot the big-toe side and "
                   "the arch are at the top; for a LEFT foot they are at the bottom. Does the picture agree?"),
    ("heel_cup", "Side view: is there a heel cup (the outline rises at the heel end) and no wall anywhere else?"),
    ("arch", "Top and side views: is the highest fill under the arch (between heel and ball, on the big-toe side), "
             "not under the toes or the outer edge?"),
    ("surface", "Top view: is the top surface smooth, with no holes, pits, ridges or stray islands?"),
    ("pair", "pair.png (if present): do the left and right outlines (left mirrored) lie on top of each other, "
             "give or take the feet's own difference?"),
]


def load_spec(path: Path | None = None) -> dict:
    """The shoe every insole is checked against; defaults if the file is missing."""
    p = Path(path) if path else SPEC_PATH
    spec = dict(DEFAULT_SPEC)
    if p.is_file():
        spec.update({k: v for k, v in json.loads(p.read_text()).items() if not k.startswith("_")})
    return spec


def packet_dir(data_dir: Path, capture_id: str, made: str) -> Path:
    """<data>/reviews/<capture>/<made>: one per build. ':' isn't allowed in Windows file names."""
    return Path(data_dir) / "reviews" / capture_id / re.sub(r"[^0-9A-Za-z._-]", "-", made)


def _insole_captures(data_dir: Path):
    """(folder, capture.json) for each capture whose insole can be downloaded (built, and still current)."""
    from .server import insole_downloadable, read_json

    for cj in sorted((Path(data_dir) / "captures").glob("*/capture.json")):
        try:
            meta = read_json(cj)
        except (OSError, ValueError):
            continue
        ins = meta.get("insole") or {}
        if ins.get("made") and (cj.parent / "insole" / "insole.json").is_file() and insole_downloadable(cj.parent, meta):
            yield cj.parent, meta


def pending(data_dir: Path) -> list[tuple[Path, dict]]:
    """Captures whose current insole has no review packet yet."""
    return [(f, m) for f, m in _insole_captures(data_dir)
            if not (packet_dir(data_dir, f.name, m["insole"]["made"]) / "review.json").is_file()]


def unreviewed(data_dir: Path) -> list[Path]:
    """Packets that Claude (or Brandon) hasn't answered yet: no claude-review.md beside review.json."""
    return sorted(p.parent for p in (Path(data_dir) / "reviews").glob("*/*/review.json")
                  if not (p.parent / "claude-review.md").is_file())


def _other_foot(data_dir: Path, folder: Path, meta: dict) -> tuple[Path, dict] | None:
    """The most recently made insole of the other foot, if any."""
    other = {"left": "right", "right": "left"}.get(meta.get("foot"))
    best = None
    for f, m in _insole_captures(data_dir):
        if f != folder and m.get("foot") == other and (best is None or m["insole"]["made"] > best[1]["insole"]["made"]):
            best = (f, m)
    return best


# ---------------------------------------------------------------------------
# the plain checks
# ---------------------------------------------------------------------------
def checks(ins_dir: Path, meta: dict, report: dict, spec: dict, other: dict | None) -> list[dict]:
    """Arithmetic on the insole's files. Each: name, ok (True/False), and what was found."""
    from .insole import read_3mf

    out = []

    def add(name, ok, found):
        out.append(dict(name=name, ok=bool(ok), found=found))

    target, tol = float(spec["target_length_mm"]), float(spec["length_tolerance_mm"])
    length = float(report["length_mm"])
    add("length", abs(length - target) <= tol,
        f"{length:.1f} mm long; the shoe's insole is {target:.1f} mm ({spec['target_length_source']}); "
        f"allowed ±{tol:g} mm")

    add("foot", report.get("foot") == meta.get("foot"),
        f"insole made for the {report.get('foot')} foot; the capture is a {meta.get('foot')} foot")

    posting = [k for k in ("posting_rearfoot_deg", "posting_forefoot_deg") if (report["params"].get(k) or 0) != 0]
    add("no_posting", not posting, "no posting" if not posting else f"posting set: {', '.join(posting)}")

    cap = float(report["params"]["max_arch_fill_mm"])
    add("fill_cap", float(report["max_fill_mm"]) <= cap + 0.01,
        f"highest fill {report['max_fill_mm']} mm (cap {cap:g} mm)")

    bed = report.get("bed_fit") or {}
    add("bed", bed.get("fits", False), f"{bed.get('how', 'unknown')} on a {bed.get('bed_mm', '?')} mm bed")

    # The 3MF is what Bambu Studio opens: millimetres, no scale in its placement, and the same
    # length as the STL and insole.json. A file that passes this prints at the right size at 100%.
    m = read_3mf(ins_dir / "insole.3mf")
    t = m["transform"]
    scale = float(np.hypot(t[0], t[1]))
    tm_len = float(np.ptp(m["vertices"][:, 0])) if len(m["vertices"]) else 0.0
    add("3mf_size", m["unit"] == "millimeter" and abs(scale - 1) < 1e-4 and abs(tm_len - length) <= 0.15,
        f"3MF in {m['unit']}, placement scale {scale:.4f}, {tm_len:.1f} mm long (insole.json says {length:.1f})")

    summary = (ins_dir / "summary.html").read_text(errors="replace") if (ins_dir / "summary.html").is_file() else ""
    add("summary_sheet", "NOT A MEDICAL DEVICE" in summary.upper() and "sign" in summary.lower(),
        "clinician summary sheet present, with the not-a-medical-device notice and a signature line"
        if summary else "summary.html is missing")

    if report.get("synthetic"):
        add("real_scan", False, "SYNTHETIC test geometry, not a foot: never print or wear it")

    if other is not None:
        diff = length - float(other["length_mm"])
        add("pair_length", abs(diff) <= float(spec["pair_tolerance_mm"]),
            f"{other['foot']} insole ({other['capture']}) is {other['length_mm']:.1f} mm; difference {diff:+.1f} mm")
    return out


# ---------------------------------------------------------------------------
# pictures (plain numpy + zlib: no plotting library needed on the server)
# ---------------------------------------------------------------------------
def write_png(path: Path, rgb: np.ndarray) -> None:
    """An 8-bit RGB PNG, written by hand (each row: filter byte 0, then the pixels)."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[r].astype(np.uint8).tobytes() for r in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _points(mesh, per_mm2: float = 40.0) -> np.ndarray:
    """Points spread over the surface, about 10 per 0.5 mm pixel of the top, so that no pixel of it is
    missed (a missed one would show the bottom face through it, a false pit)."""
    import trimesh

    n = int(min(max(mesh.area * per_mm2, 20_000), 4_000_000))
    pts, _ = trimesh.sample.sample_surface(mesh, n, seed=0)
    return np.vstack([pts, mesh.vertices])


def _raster(u: np.ndarray, v: np.ndarray, val: np.ndarray, lo, hi, pad: int = 20):
    """Highest ``val`` per pixel of the (u, v) plane (u right, v up), 0.5 mm per pixel; NaN where empty."""
    w = int(np.ceil((hi[0] - lo[0]) / MM_PER_PX)) + 2 * pad
    h = int(np.ceil((hi[1] - lo[1]) / MM_PER_PX)) + 2 * pad
    c = np.clip(((u - lo[0]) / MM_PER_PX).astype(int) + pad, 0, w - 1)
    r = np.clip(h - 1 - (((v - lo[1]) / MM_PER_PX).astype(int) + pad), 0, h - 1)
    img = np.full(h * w, -np.inf)
    np.maximum.at(img, r * w + c, val)
    img = img.reshape(h, w)
    # close pinholes between samples: an empty pixel with at least 3 of its 4 neighbours filled takes
    # their highest. The outline's own edge (at most 2 filled neighbours) doesn't grow.
    near = np.stack([np.roll(img, 1, 0), np.roll(img, -1, 0), np.roll(img, 1, 1), np.roll(img, -1, 1)])
    hole = ~np.isfinite(img) & (np.isfinite(near).sum(0) >= 3)
    img[hole] = near.max(0)[hole]
    return np.where(np.isfinite(img), img, np.nan)


def _shade(height: np.ndarray, colour=(0.85, 0.55, 0.30)) -> np.ndarray:
    """Height map -> RGB: lit from the top left (slopes show as light and dark), white background."""
    z = np.nan_to_num(height, nan=0.0)
    gy, gx = np.gradient(z, MM_PER_PX)
    n = np.dstack([-gx, gy, np.ones_like(z)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    light = np.array([-0.5, 0.5, 0.7]) / np.linalg.norm([-0.5, 0.5, 0.7])
    lam = np.clip(n @ light, 0, 1)
    hz = (z - np.nanmin(height)) / max(np.nanmax(height) - np.nanmin(height), 1e-6)  # higher = brighter
    base = (0.35 + 0.65 * lam)[..., None] * (0.55 + 0.45 * hz)[..., None] * np.array(colour)
    rgb = np.where(np.isnan(height)[..., None], 1.0, base)
    return (rgb * 255).astype(np.uint8)


def _scale_bar(rgb: np.ndarray, mm: float = 50.0) -> np.ndarray:
    """A black bar ``mm`` long in the bottom left corner, with 10 mm ticks."""
    h = rgb.shape[0]
    n = int(mm / MM_PER_PX)
    rgb[h - 8:h - 5, 10:10 + n] = 0
    for k in range(0, n + 1, int(10 / MM_PER_PX)):
        rgb[h - 14:h - 5, 10 + min(k, n - 1)] = 0
    return rgb


def top_view(mesh) -> np.ndarray:
    """Looking down: heel at the left, toes at the right, the foot's left at the top. 0.5 mm per pixel."""
    # Only faces that can be seen from above (not the bottom): a pixel the samples happen to miss is
    # then empty, and filled from its neighbours, instead of showing the bottom face as a false pit.
    seen = mesh.submesh([np.flatnonzero(mesh.face_normals[:, 2] > -0.05)], append=True)
    p = _points(seen)
    lo, hi = mesh.bounds[0, :2], mesh.bounds[1, :2]
    return _scale_bar(_shade(_raster(p[:, 0], p[:, 1], p[:, 2], lo, hi)))


SIDE_STRETCH = 2.0


def side_view(mesh) -> np.ndarray:
    """From the foot's left: heel at the left, the bed along the bottom. Heights are drawn
    ``SIDE_STRETCH`` times taller than lengths, so a few millimetres of heel cup or arch show."""
    p = _points(mesh)
    lo, hi = mesh.bounds[0, [0, 2]] * [1, SIDE_STRETCH], mesh.bounds[1, [0, 2]] * [1, SIDE_STRETCH]
    h = _raster(p[:, 0], p[:, 2] * SIDE_STRETCH, p[:, 1], lo, hi)  # nearest the viewer (largest y) wins
    rgb = np.where(np.isnan(h)[..., None], 255, np.array([110, 110, 120])).astype(np.uint8)
    return _scale_bar(rgb)


def pair_view(this_mesh, this_foot: str, other_mesh) -> np.ndarray:
    """Both outlines from above, the left foot's mirrored so a matched pair lies on top of itself.
    This foot's in orange, the other's in blue, where they overlap dark grey."""
    def foot_xy(m, foot):
        p = _points(m, 12.0)[:, :2]
        if foot == "left":
            p = p * [1, -1]
        return p - [p[:, 0].min(), 0]  # both heels at x = 0

    other_foot = "left" if this_foot == "right" else "right"
    a, b = foot_xy(this_mesh, this_foot), foot_xy(other_mesh, other_foot)
    allp = np.vstack([a, b])
    lo, hi = allp.min(0), allp.max(0)
    ra = np.isfinite(_raster(a[:, 0], a[:, 1], np.ones(len(a)), lo, hi))
    rb = np.isfinite(_raster(b[:, 0], b[:, 1], np.ones(len(b)), lo, hi))
    rgb = np.full(ra.shape + (3,), 255, np.uint8)
    rgb[ra & ~rb] = (230, 140, 60)
    rgb[rb & ~ra] = (70, 120, 220)
    rgb[ra & rb] = (90, 90, 90)
    return _scale_bar(rgb)


# ---------------------------------------------------------------------------
# the packet
# ---------------------------------------------------------------------------
def build_packet(data_dir: Path, folder: Path, meta: dict, spec: dict | None = None) -> Path:
    """Write the review packet for one capture's current insole; returns its folder."""
    import trimesh

    spec = spec or load_spec()
    ins_dir = folder / "insole"
    report = json.loads((ins_dir / "insole.json").read_text())
    made = meta["insole"]["made"]
    out = packet_dir(data_dir, folder.name, made)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pair.png").unlink(missing_ok=True)  # left from an earlier, unfinished attempt: drawn afresh below

    other = _other_foot(data_dir, folder, meta)
    other_info = None
    if other is not None:
        orep = json.loads((other[0] / "insole" / "insole.json").read_text())
        other_info = dict(capture=other[0].name, foot=other[1]["foot"], length_mm=orep["length_mm"],
                          width_mm=orep["width_mm"], made=other[1]["insole"]["made"])

    mesh = trimesh.load(ins_dir / "insole.stl", force="mesh")
    write_png(out / "top.png", top_view(mesh))
    write_png(out / "side.png", side_view(mesh))
    pair_note = None
    if other is not None:
        try:
            write_png(out / "pair.png", pair_view(mesh, meta["foot"],
                                                  trimesh.load(other[0] / "insole" / "insole.stl", force="mesh")))
        except Exception as e:  # noqa: BLE001 - the other foot's broken file mustn't stop this foot's packet
            pair_note = f"couldn't draw pair.png: the other foot's insole.stl didn't load ({type(e).__name__})"

    results = checks(ins_dir, meta, report, spec, other_info)
    packet = dict(
        capture=folder.name, foot=meta.get("foot"), scan_kind=meta.get("scan_kind"), made=made,
        synthetic=bool(report.get("synthetic")), spec=spec,
        insole=dict(length_mm=report["length_mm"], width_mm=report["width_mm"], height_mm=report["height_mm"],
                    volume_cm3=report.get("volume_cm3"), max_fill_mm=report["max_fill_mm"],
                    max_fill_at_mm=report.get("max_fill_at_mm"), sole=report.get("sole"),
                    bed_fit=report.get("bed_fit"), shoe_fit=report.get("shoe_fit"),
                    warnings=report.get("warnings", []), frame=report.get("frame")),
        other_foot=other_info, checks=results, flags=[c["name"] for c in results if not c["ok"]],
        look_checks=[dict(name=n, question=q) for n, q in LOOK_CHECKS
                     if n != "pair" or (out / "pair.png").is_file()],
        pair_note=pair_note,
        files=dict(insole=str(ins_dir), stl=str(ins_dir / "insole.stl"), threemf=str(ins_dir / "insole.3mf"),
                   summary=str(ins_dir / "summary.html"), insole_json=str(ins_dir / "insole.json"),
                   top=str(out / "top.png"), side=str(out / "side.png"),
                   pair=str(out / "pair.png") if (out / "pair.png").is_file() else None),
        written=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    (out / "packet.md").write_text(packet_markdown(packet))
    (out / "review.json").write_text(json.dumps(packet, indent=2))  # last: its presence means the packet is whole
    return out


def packet_markdown(p: dict) -> str:
    """The packet as a page a person or Claude reads top to bottom."""
    s, i = p["spec"], p["insole"]
    lines = [f"# Insole review: {p['foot']} foot, capture {p['capture']}", ""]
    if p["synthetic"]:
        lines += ["**SYNTHETIC test geometry, not a foot. Never print or wear it.**", ""]
    lines += ["NOT A MEDICAL DEVICE. This review decides whether the file is ready to slice. It does not clear "
              "anyone to wear it for sport: that needs a clinician's signature on the summary sheet "
              "(docs/SAFETY.md), and the break-in protocol still applies.", "",
              f"Made {p['made']}. Packet written {p['written']}.", "",
              "## The shoe", "",
              f"- {s['shoe']}, {s['size']}: insole length {s['target_length_mm']:g} mm "
              f"({s['target_length_source']}).",
              f"- Slice in {s['slicer']} at **{s['slicer_scale_percent']}% scale**. Never rescale the model in the "
              "slicer: if the size is wrong, rebuild the insole with the right length instead.", "",
              "## The insole (from insole.json)", "",
              f"- {i['length_mm']} x {i['width_mm']} x {i['height_mm']} mm, {i['volume_cm3']} cm3.",
              f"- Highest fill {i['max_fill_mm']} mm at x {i['max_fill_at_mm']['x']}, y {i['max_fill_at_mm']['y']} mm "
              f"({i['frame']}).",
              f"- Sole seen by the scan: {i['sole']['seen']:.0%} of the footprint, "
              f"{i['sole']['seen_under_arch']:.0%} under the arch." if i.get("sole") else "- Sole coverage: not recorded.",
              f"- Bed: {i['bed_fit'].get('how')}." if i.get("bed_fit") else "- Bed: not recorded."]
    if p["other_foot"]:
        o = p["other_foot"]
        lines.append(f"- Other foot: {o['foot']} insole from capture {o['capture']}, "
                     f"{o['length_mm']} x {o['width_mm']} mm, made {o['made']}.")
    if p.get("pair_note"):
        lines.append(f"- {p['pair_note']}")
    lines += ["", "## Generator warnings", ""]
    lines += [f"- {w}" for w in i["warnings"]] or ["- none"]
    lines += ["", "## Plain checks (arithmetic on the files)", "", "| check | result | found |", "|---|---|---|"]
    lines += [f"| {c['name']} | {'PASS' if c['ok'] else '**FLAG**'} | {c['found']} |" for c in p["checks"]]
    lines += ["", "## Look at the pictures", "",
              "top.png and side.png are drawn from insole.stl at 0.5 mm per pixel (side.png's heights drawn "
              f"{SIDE_STRETCH:g} times taller, so they show); the bar at the bottom left is 50 mm with 10 mm ticks. "
              "Read sizes from the numbers above, not from the pictures.", ""]
    lines += [f"- [ ] **{c['name']}**: {c['question']}" for c in p["look_checks"]]
    lines += ["", "## Files", ""] + [f"- {k}: `{v}`" for k, v in p["files"].items() if v]
    return "\n".join(lines) + "\n"


def run_once(data_dir: Path, spec: dict | None = None, log=print) -> list[Path]:
    """Write a packet for every insole that lacks one. A broken insole is logged and skipped, never fatal."""
    made = []
    for folder, meta in pending(data_dir):
        try:
            made.append(build_packet(data_dir, folder, meta, spec))
            log(f"review packet: {made[-1]}")
        except Exception as e:  # noqa: BLE001 - one bad file mustn't stop the others (or the server)
            log(f"review packet for {folder.name} failed: {type(e).__name__}: {e}")
    return made


def watch(data_dir: Path, interval_s: float = 20.0, spec_path: Path | None = None, on_new=None,
          stop=None, log=print) -> None:
    """Poll for new insoles every ``interval_s`` and write their packets; ``on_new(packet_dir)`` after each.
    ``stop``: a threading.Event that ends the loop (the server sets it on shutdown)."""
    while stop is None or not stop.is_set():
        for out in run_once(data_dir, load_spec(spec_path), log=log):
            if on_new is not None:
                try:
                    on_new(out)
                except Exception as e:  # noqa: BLE001
                    log(f"after-packet command failed for {out}: {type(e).__name__}: {e}")
        if stop is not None:
            stop.wait(interval_s)
        else:
            time.sleep(interval_s)
