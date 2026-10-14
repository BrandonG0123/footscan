"""First-fit insole: the shape of the bottom of the scanned foot, as a printable solid.

Not a medical device. A first-fit insole follows the scanned sole and adds
nothing else: **no posting** (no deliberate tilt of heel or forefoot), no
correction, no lattice zones. It is for checking fit and for walking-only
break-in; posting and stiffness choices wait for the Phase 0 repeatability
study and the Phase 5 material tests, and anything worn for sport needs the
clinician sign-off sheet (written next to the model, see ``summary_html``).

The bottom of the foot is the input that matters
------------------------------------------------
The insole's top surface *is* the underside of the foot, so the generator
asks one question everywhere under the foot: how high is the sole above the
floor here? It answers it by casting a ray straight up from under the floor
(every 0.5 mm) and looking at the first surface it hits:

- a **downward-facing** surface: that is the sole, seen by the scan; its
  height is the answer (under the arch, around the heel's rounded edge).
- an **upward-facing** surface: the ray went up through an opening in the
  bottom and hit the inside of the top of the foot. The sole wasn't scanned
  there, which in a standing or seated scan means it was pressed on the
  mat: height 0.
- **nothing**: a hole in the scan. Also taken as 0, and counted.

Unseen sole is never guessed upward: a missing arch gives a flat insole
there, not an invented arch. The coverage report says how much of the sole
was actually seen, and warns when the arch region wasn't.

From heights to a solid
-----------------------
1. **Fill** = the sole height minus a small *relief* (default 1 mm), so the
   insole sits at or just below the scanned sole, never above it.
   Smoothed with a 1.5 mm Gaussian to take out scan noise, but the smoothing
   may only lower the surface (or raise it by at most 0.5 mm): the result is
   ``min(smoothed, raw + 0.5)``.
2. **Caps**: fill above ``max_arch_fill_mm`` (20) or, in the heel, above the
   heel cup depth, is clipped and reported. They are safety limits on a
   first fit, not design choices.
3. **Outline**: the foot seen from above (its plan-view silhouette below
   30 mm), plus a margin (2 mm), plus a wider margin round the heel for the
   cup wall (6 mm). Corners are rounded.
4. **Heel cup wall**: outside the silhouette, around the back third of the
   foot, the top rises to the cup depth over 4 mm. The wall is entirely
   outside the scanned foot, so it holds the heel without pressing into it;
   inside, the scanned heel's own rounded underside forms the cup.
5. **Base**: a flat bottom (it prints flat on the bed), 3 mm thick under
   the foot, tapering to 2 mm at the toes.
6. **Solid**: the outline is extruded 1 mm, refined to 1.5 mm triangles,
   and every vertex's height is scaled by the top-surface height at its
   (x, y): z -> z * top(x, y). The bottom stays at 0, the top lands on the
   surface, the sides follow, and the result is a single closed solid.

Coordinates of the output: millimetres, x forward from the back of the
heel, y toward the foot's left, z up, bottom on z = 0. A left foot's insole
is a mirror image of a right foot's, as it should be.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .recon import plantar

GRID_MM = 0.5
SILHOUETTE_HEIGHT_MM = 30.0
DOWNWARD_FACING = -0.1   # cos: a hit counts as "sole" if its normal points at least this much down
SMOOTH_SIGMA_MM = 1.5
SMOOTH_MAY_RAISE_MM = 0.5


@dataclass
class InsoleParams:
    """First-fit choices. Recorded on the summary sheet; none is derived from a measurement."""
    relief_mm: float = 1.0          # top sits this far below the scanned sole
    base_mm: float = 3.0            # thickness under the foot
    toe_base_mm: float = 2.0        # tapering to this at the toes
    taper_from: float = 0.6         # fraction of length where the taper starts
    margin_mm: float = 2.0          # outline beyond the foot's silhouette
    heel_cup_depth_mm: float = 12.0
    heel_wall_margin_mm: float = 6.0
    heel_wall_ramp_mm: float = 4.0
    heel_zone: float = 0.30         # back fraction of the foot that gets the cup wall
    max_arch_fill_mm: float = 20.0
    posting_rearfoot_deg: float = 0.0   # first fit: no posting, always
    posting_forefoot_deg: float = 0.0
    bed_mm: float = 256.0           # printer bed (Bambu X1/P1/A1); for the fit check only


class InsoleError(ValueError):
    pass


@dataclass
class Insole:
    mesh: object                    # trimesh.Trimesh, output frame (mm)
    foot: str
    params: InsoleParams
    report: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# the sole
# ---------------------------------------------------------------------------
def output_frame(foot_mesh, foot: str):
    """Foot frame (x forward, y medial) -> output frame (x forward, y the foot's left)."""
    m = foot_mesh.copy()
    if foot == "left":  # medial is the foot's right: mirror y (trimesh re-winds the faces)
        m.apply_transform(np.diag([1.0, -1.0, 1.0, 1.0]))
    return m


def sole_heights(mesh, xs: np.ndarray, ys: np.ndarray, inside: np.ndarray):
    """Height of the sole above the floor at each grid point inside the outline.

    Returns (height grid, state grid) where state is 1 = sole seen, 0 = sole
    not seen (resting on the floor), -1 = no surface (hole), and nan outside.
    """
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    pts = np.c_[X[inside], Y[inside]]
    origins = np.c_[pts, np.full(len(pts), -5.0)]
    dirs = np.tile([0.0, 0.0, 1.0], (len(pts), 1))
    loc, ray_idx, tri_idx = mesh.ray.intersects_location(origins, dirs, multiple_hits=False)
    h = np.zeros(len(pts))
    state = np.full(len(pts), -1, dtype=int)
    normals_z = mesh.face_normals[tri_idx, 2]
    seen = normals_z < DOWNWARD_FACING
    h[ray_idx[seen]] = np.maximum(0.0, loc[seen, 2])
    state[ray_idx] = np.where(seen, 1, 0)
    H = np.full(X.shape, np.nan)
    S = np.full(X.shape, np.nan)
    H[inside] = h
    S[inside] = state
    return H, S


def silhouette(mesh):
    """The foot seen from above (below SILHOUETTE_HEIGHT_MM), as a polygon."""
    import shapely
    from shapely.geometry import MultiPoint

    V = np.asarray(mesh.vertices)
    low = V[V[:, 2] < SILHOUETTE_HEIGHT_MM][:, :2]
    if len(low) < 50:
        raise InsoleError("almost nothing of the foot near the floor: is this a standing or seated scan on the mat?")
    poly = shapely.concave_hull(MultiPoint(low), ratio=0.15)
    poly = poly.buffer(4.0).buffer(-4.0)  # close small gaps between scan points
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly


# ---------------------------------------------------------------------------
# the solid
# ---------------------------------------------------------------------------
def build(foot_mesh, foot: str, params: InsoleParams | None = None) -> Insole:
    """First-fit insole from a foot mesh already in the foot frame (see plantar.run)."""
    import shapely
    import trimesh
    from scipy import ndimage

    p = params or InsoleParams()
    if p.posting_rearfoot_deg or p.posting_forefoot_deg:
        raise InsoleError("a first-fit insole has no posting; posting waits for clinician review")
    if foot not in ("left", "right"):
        raise InsoleError("foot must be 'left' or 'right'")
    m = output_frame(foot_mesh, foot)
    sil = silhouette(m)
    x0, y0, x1, y1 = sil.bounds
    length = x1 - x0

    # outline: margin all round, a wider margin round the heel for the cup wall
    heel = sil.intersection(shapely.box(x0 - 50, y0 - 50, x0 + p.heel_zone * length, y1 + 50))
    outline = sil.buffer(p.margin_mm).union(heel.buffer(p.heel_wall_margin_mm))
    outline = outline.buffer(3.0).buffer(-3.0).simplify(0.2)
    if outline.geom_type != "Polygon":
        outline = max(outline.geoms, key=lambda g: g.area)

    # grid over the outline
    ox0, oy0, ox1, oy1 = outline.bounds
    xs = np.arange(ox0 - 1, ox1 + 1 + GRID_MM, GRID_MM)
    ys = np.arange(oy0 - 1, oy1 + 1 + GRID_MM, GRID_MM)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    in_sil = shapely.contains_xy(sil, X, Y)
    in_out = shapely.contains_xy(outline.buffer(1.0), X, Y)

    # 1. the sole, under the foot only
    H, S = sole_heights(m, xs, ys, in_sil)
    raw = np.where(in_sil, np.maximum(0.0, np.nan_to_num(H) - p.relief_mm), 0.0)
    smooth = ndimage.gaussian_filter(raw, SMOOTH_SIGMA_MM / GRID_MM)
    fill = np.minimum(smooth, raw + SMOOTH_MAY_RAISE_MM)
    fill[~in_sil] = 0.0

    # 2. safety caps
    w_heel = np.clip((x0 + (p.heel_zone + 0.15) * length - X) / (0.15 * length), 0, 1)  # 1 in the heel, 0 by mid-foot
    cap = np.where(w_heel >= 1, p.heel_cup_depth_mm, p.max_arch_fill_mm)
    clipped = fill > cap + 1e-6
    fill = np.minimum(fill, cap)

    # 4. heel cup wall, outside the foot only
    outside = ~in_sil
    d_out = ndimage.distance_transform_edt(outside) * GRID_MM
    ramp = np.clip(d_out / p.heel_wall_ramp_mm, 0, 1)
    ramp = ramp * ramp * (3 - 2 * ramp)  # smoothstep: a rounded rim, no sharp corner
    wall = np.where(outside, p.heel_cup_depth_mm * ramp * w_heel, 0.0)

    # 5. base, tapering toward the toes
    t = np.clip((X - (x0 + p.taper_from * length)) / ((1 - p.taper_from) * length), 0, 1)
    base = p.base_mm + (p.toe_base_mm - p.base_mm) * t
    top = base + np.maximum(fill, wall)

    # 6. the solid: extrude the outline 1 mm, refine, lift every vertex to the surface
    from scipy.interpolate import RegularGridInterpolator
    import manifold3d as m3

    interp = RegularGridInterpolator((ys, xs), top, bounds_error=False, fill_value=None)
    rings = [np.asarray(outline.exterior.coords)[:-1]]
    if outline.exterior.is_ccw is False:
        rings = [r[::-1] for r in rings]
    cs = m3.CrossSection(rings, m3.FillRule.Positive)
    solid = m3.Manifold.extrude(cs, 1.0).refine_to_length(1.5)

    def lift(v):
        v = np.array(v, dtype=float, copy=True)
        h = interp(np.c_[v[:, 1], v[:, 0]])
        v[:, 2] = v[:, 2] * h
        return v

    solid = solid.warp_batch(lift)
    mm = solid.to_mesh()
    mesh = trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=True)
    if not mesh.is_watertight or mesh.volume <= 0:
        raise InsoleError("the insole solid came out broken (not closed); please report the scan")

    # report: what the bottom of the foot gave us
    st = S[in_sil]
    seen, contact, holes = (float(np.mean(st == 1)), float(np.mean(st == 0)), float(np.mean(st == -1)))
    arch_band = in_sil & (X > x0 + 0.3 * length) & (X < x0 + 0.65 * length)
    arch_seen = float(np.mean(S[arch_band] == 1)) if arch_band.any() else 0.0
    peak = np.unravel_index(np.argmax(np.where(in_sil, fill, -1)), fill.shape)
    warnings = []
    if arch_seen < 0.05:
        warnings.append("the scan saw almost none of the sole under the arch, so the insole is flat there. "
                        "If the arch isn't actually flat on the floor, scan again with a low lap aimed under the inner arch.")
    if holes > 0.05:
        warnings.append(f"{holes:.0%} of the area under the foot is a hole in the scan (taken as flat).")
    if clipped.any():
        warnings.append(f"the fill was clipped by the safety caps over {clipped[in_sil].mean():.1%} of the foot "
                        f"(arch {p.max_arch_fill_mm} mm, heel {p.heel_cup_depth_mm} mm).")
    ext = mesh.extents
    report = dict(
        foot=foot,
        length_mm=round(float(ext[0]), 1), width_mm=round(float(ext[1]), 1), height_mm=round(float(ext[2]), 1),
        volume_cm3=round(float(mesh.volume) / 1000, 1),
        triangles=int(len(mesh.faces)),
        sole=dict(seen=round(seen, 3), resting_on_floor=round(contact, 3), holes=round(holes, 3),
                  seen_under_arch=round(arch_seen, 3)),
        max_fill_mm=round(float(fill[in_sil].max()), 2),
        max_fill_at_mm=dict(x=round(float(X[peak]), 1), y=round(float(Y[peak]), 1)),
        bed_fit=bed_fit(ext[0], ext[1], p.bed_mm),
        warnings=warnings,
        frame="mm; x forward from the back of the heel, y toward the foot's left, z up; bottom at z = 0",
    )
    return Insole(mesh=mesh, foot=foot, params=p, report=report)


def bed_fit(length: float, width: float, bed: float, clearance: float = 3.0) -> dict:
    """Does it fit the bed, lying straight or along the diagonal? Picks whichever leaves more room."""
    usable = bed - 2 * clearance
    straight = usable - max(length, width)
    a = np.radians(45)
    diagonal = usable - (length * np.cos(a) + width * np.sin(a))
    if max(straight, diagonal) < 0:
        return dict(fits=False, how="too long for this bed", bed_mm=bed)
    how = "straight" if straight >= 0 else "diagonal"  # straight whenever it fits: easiest to check by eye
    return dict(fits=True, how=how, spare_mm=round(float(straight if how == "straight" else diagonal), 1), bed_mm=bed)


# ---------------------------------------------------------------------------
# from a scan
# ---------------------------------------------------------------------------
def from_scan(mesh, foot: str, params: InsoleParams | None = None) -> Insole:
    """A scan in the mat frame (mm, z up, the floor at z = 0) -> first-fit insole."""
    run = plantar.run(mesh, foot)
    insole = build(run["foot_mesh"], foot, params)
    s = run["summary"]
    insole.report["scan"] = dict(
        frame=s["method"], provisional=s["provisional"], notes=s["notes"],
        footprint_length_mm=s["footprint_length_mm"], footprint_width_mm=s["footprint_width_mm"],
        highest_medial_point=s["highest_medial_point"],
    )
    return insole


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------
THREEMF_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def write_3mf(mesh, path: Path, title: str, notes: str, bed_mm: float = 256.0) -> None:
    """A plain 3MF (core spec): one object, millimetres, placed in the middle of the bed.

    Slicers (Bambu Studio, Orca, Prusa) open this as geometry; it carries no
    printer or filament settings. If the insole is longer than the bed, it
    is turned to lie along the bed's diagonal.
    """
    import zipfile
    from xml.sax.saxutils import escape

    V = np.asarray(mesh.vertices, dtype=float)
    F = np.asarray(mesh.faces, dtype=int)
    centre = (V.min(0) + V.max(0)) / 2
    ext = V.max(0) - V.min(0)
    angle = 0.0 if bed_fit(ext[0], ext[1], bed_mm)["how"] == "straight" else 45.0
    c, s = np.cos(np.radians(angle)), np.sin(np.radians(angle))
    # build transform (3MF: 3 x 4, row vectors): rotate about z, then move to the bed's centre, bottom on z = 0
    tx = bed_mm / 2 - (c * centre[0] - s * centre[1])
    ty = bed_mm / 2 - (s * centre[0] + c * centre[1])
    tz = -V[:, 2].min()
    transform = f"{c:.6f} {s:.6f} 0 {-s:.6f} {c:.6f} 0 0 0 1 {tx:.4f} {ty:.4f} {tz:.4f}"

    verts = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in V)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{d}"/>' for a, b, d in F)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{THREEMF_CORE}">'
        f'<metadata name="Title">{escape(title)}</metadata>'
        '<metadata name="Application">footscan</metadata>'
        f'<metadata name="Description">{escape(notes)}</metadata>'
        '<resources><object id="1" type="model" name="' + escape(title) + '"><mesh>'
        f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
        "</mesh></object></resources>"
        f'<build><item objectid="1" transform="{transform}"/></build></model>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    tmp.replace(path)


def read_3mf(path: Path):
    """Read back a 3MF written by write_3mf (vertices, faces, unit, build transform). For checking."""
    import xml.etree.ElementTree as ET
    import zipfile

    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = {"m": THREEMF_CORE}
    V = np.array([[float(v.get(k)) for k in "xyz"] for v in root.iterfind(".//m:vertex", ns)])
    F = np.array([[int(t.get(k)) for k in ("v1", "v2", "v3")] for t in root.iterfind(".//m:triangle", ns)])
    item = root.find(".//m:build/m:item", ns)
    return dict(names=names, unit=root.get("unit"), vertices=V, faces=F,
                transform=[float(x) for x in item.get("transform").split()],
                metadata={m.get("name"): m.text for m in root.iterfind("m:metadata", ns)})


PRINT_NOTES = """Footscan first-fit insole: print notes
NOT A MEDICAL DEVICE. Walking-only break-in; no sport until a clinician has signed the summary sheet.

Starting points only. None of these settings has been tested on this design yet (that is Phase 5).
- Material: TPU (95A is the usual starting point for insoles).
- Bottom face down on the bed, as the file is placed.
- Walls / top / bottom layers: enough that the top surface is closed and smooth (try 3 walls, 4 top layers).
- Infill: one density for the whole insole (first fit has no zones). Gyroid is a common choice for TPU.
- Print slowly, as TPU needs; dry the filament first.
After printing: compare it with your shoe's own insole, trim the toe end if needed, and start the break-in.
"""


def summary_html(insole: Insole, scan_label: str, synthetic: bool = False) -> str:
    """The clinician summary sheet (docs/SAFETY.md, requirement 1), for this first-fit device."""
    from html import escape

    r, p = insole.report, insole.params
    scan = r.get("scan", {})
    hm = scan.get("highest_medial_point")
    warn = "".join(f"<li>{escape(w)}</li>" for w in r["warnings"]) or "<li>None.</li>"
    synth = ('<p class="synthetic">SYNTHETIC TEST GEOMETRY. This sheet was made from a computer-generated '
             'shape, not a person\'s foot. It is an example of the sheet, not a device to wear.</p>') if synthetic else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Footscan insole summary: {escape(scan_label)}</title>
<style>
 body{{font:14px/1.45 -apple-system,Segoe UI,sans-serif;max-width:760px;margin:24px auto;color:#15201f}}
 h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:22px 0 6px;border-bottom:1px solid #ccc}}
 .safety{{background:#15201f;color:#fff;padding:10px 12px;border-radius:6px}} .safety b{{color:#d6ee3c}}
 .synthetic{{border:2px solid #b0271f;color:#b0271f;padding:8px;font-weight:700}}
 table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}
 .sign td{{height:34px}} .box{{display:inline-block;width:12px;height:12px;border:1px solid #333;margin:0 6px 0 14px}}
 @media print{{body{{margin:0}}}}
</style></head><body>
<div class="safety"><b>NOT A MEDICAL DEVICE.</b> A homemade insole from a phone scan. It does not diagnose or treat
anything and is not equivalent to, or a substitute for, a prescribed orthotic. Not for sport until signed below.</div>
{synth}
<h1>First-fit insole: {escape(insole.foot)} foot</h1>
<p>Scan: {escape(scan_label)}</p>

<h2>What this device is</h2>
<p>A <b>first fit</b>: the top follows the scanned underside of the foot, set {p.relief_mm} mm below it.
<b>No posting, no correction, one uniform stiffness.</b> Its purpose is to check fit and comfort while walking.</p>

<h2>Device parameters</h2>
<table>
<tr><th>Rearfoot posting</th><td>{p.posting_rearfoot_deg}&deg; (none)</td><th>Forefoot posting</th><td>{p.posting_forefoot_deg}&deg; (none)</td></tr>
<tr><th>Arch fill</th><td>scanned sole &minus; {p.relief_mm} mm, capped at {p.max_arch_fill_mm} mm</td><th>Highest fill</th><td>{r['max_fill_mm']} mm</td></tr>
<tr><th>Heel cup depth</th><td>{p.heel_cup_depth_mm} mm (wall outside the scanned heel)</td><th>Base thickness</th><td>{p.base_mm} mm, {p.toe_base_mm} mm at toes</td></tr>
<tr><th>Stiffness</th><td colspan="3">Uniform (no lattice zones). Material and infill as printed: record below.</td></tr>
<tr><th>Size</th><td colspan="3">{r['length_mm']} &times; {r['width_mm']} mm, {r['height_mm']} mm tall</td></tr>
</table>

<h2>Measurements from the scan</h2>
<table>
<tr><th>Footprint length</th><td>{scan.get('footprint_length_mm', '&mdash;')} mm</td><th>Footprint width</th><td>{scan.get('footprint_width_mm', '&mdash;')} mm</td></tr>
<tr><th>Highest point under the inner arch</th><td colspan="3">{f"{hm['height_mm']} mm, {hm['x_mm']} mm from the heel" if hm else '&mdash;'}</td></tr>
<tr><th>Sole seen by the scan</th><td>{r['sole']['seen']:.0%} of the footprint</td><th>Under the arch</th><td>{r['sole']['seen_under_arch']:.0%}</td></tr>
</table>
<p><b>Repeatability:</b> not yet measured (Phase 0 study pending). Treat every number above as unverified.
The foot frame is {"provisional (from the scan alone)" if scan.get('provisional', True) else "from landmarks"}.</p>
<h2>Warnings</h2><ul>{warn}</ul>

<h2>As printed (fill in)</h2>
<table class="sign"><tr><th>Material</th><td></td><th>Infill</th><td></td></tr><tr><th>Date printed</th><td></td><th>Shoe</th><td></td></tr></table>

<h2>Clinician review</h2>
<p>Reviewed by a podiatrist, sports-medicine physician, physical therapist or certified athletic trainer.</p>
<table class="sign">
<tr><th>Name</th><td></td><th>Credential</th><td></td></tr>
<tr><th>Signature</th><td></td><th>Date</th><td></td></tr>
</table>
<p>Approved for:<span class="box"></span>walking only<span class="box"></span>training<span class="box"></span>match play<span class="box"></span>not approved</p>
<p>Notes:</p><div style="border:1px solid #ccc;height:90px"></div>

<h2>Break-in (walking only until signed above)</h2>
<p>Day 1: 1 h &middot; days 2&ndash;3: 2 h &middot; days 4&ndash;5: 3 h &middot; days 6&ndash;7: 4 h &middot; days 8&ndash;10: 6 h &middot;
days 11&ndash;14: all day. Check both feet after every session.
<b>Stop at once</b> and don't resume until reviewed if anything new hurts (foot, ankle, shin, knee, hip or back),
a skin mark is still there the next day, a foot feels numb, tingly or burning, or an existing pain gets worse.</p>
</body></html>"""


def write_outputs(insole: Insole, out_dir: Path, name: str, scan_label: str, synthetic: bool = False) -> dict:
    """insole.3mf, insole.stl, summary.html, print-notes.txt and insole.json in out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = "SYNTHETIC TEST GEOMETRY, not a foot. " if synthetic else ""
    notes = (f"{tag}Footscan first-fit insole ({insole.foot} foot). NOT A MEDICAL DEVICE. No posting. "
             "Walking-only break-in; no sport until a clinician has signed the summary sheet.")
    files = dict(threemf=out / f"{name}.3mf", stl=out / f"{name}.stl", summary=out / f"{name}-summary.html",
                 notes=out / "print-notes.txt", json=out / f"{name}.json")
    write_3mf(insole.mesh, files["threemf"], title=f"{tag}{name}", notes=notes, bed_mm=insole.params.bed_mm)
    insole.mesh.export(files["stl"])
    files["summary"].write_text(summary_html(insole, scan_label, synthetic))
    files["notes"].write_text(PRINT_NOTES)
    files["json"].write_text(json.dumps(dict(synthetic=synthetic, params=asdict(insole.params), **insole.report), indent=2))
    return {k: str(v) for k, v in files.items()}
