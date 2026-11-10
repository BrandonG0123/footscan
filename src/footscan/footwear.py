"""A printed shoe made for one foot: a slip-on clog with the foot's own footbed built into its floor.

Not a medical device, and not sports equipment. The shoe is for walking and
casual wear only. Its footbed is the first-fit insole's surface (``insole.py``):
it follows the scanned sole, with no posting and no correction, and everything
in docs/SAFETY.md applies to it exactly as it does to an insole (break-in, stop
on any new pain, clinician sign-off before sport). ``summary_html`` writes the
sheet that says so next to every model.

What comes from the foot, and what doesn't
------------------------------------------
- **Size and fit come from the foot**: its length and its width across the
  ball (a ruler measurement when given, else the sole scan's own outline),
  plus the room the chosen fit adds (``FIT``).
- **The footbed comes from the sole scan**: the same height map the insole
  generator makes (arch fill, the heel's rounded cup), printed as part of the
  shoe's floor. One print per shoe; there is no separate insole.
- **The upper is a standard shape in that size**, like a bought shoe's. No
  scan of the top of the foot is asked for: the roof heights are a table of
  shares of the length (``ROOF``), a judgment, not a measurement of this foot.
- **Room at the sides comes from the sole scan's own edges**: it shows the
  foot's sides for the first 30 mm up. Where the foot is wider there than the
  standard shape (a flat foot's inner side stands out over its own
  footprint), the inside is let out to it, behind the toe box only
  (``_let_out``). It is never made narrower than the standard shape.
- **The look comes from the style** (``STYLES``) and the preferences: the
  pattern cut into the upper, how open it is, the sole's thickness, the toe's
  shape. A style never changes the inside.

Proportions stay a shoe's whatever the foot: the standard shape's width is
held between ``BALL_SHARE`` of its length (a long, narrow foot gets a normal
shoe in its length, never a long thin one, and the result says so). Only
where the sole scan shows the foot wider than that shape is it let out, so
a shoe is never tighter than the scanned foot for the sake of its looks;
the sheet says where.

How the shape is made
---------------------
Everything is built for a right shoe, inner side toward +y, and mirrored at
the end for a left one.

1. **The floor outline** (``FloorOutline``): the plan shape of the inside at
   floor level, drawn from ``LAST_STATIONS`` (half-widths at shares of the
   length) and stretched to this foot's length and width. Rounded at the heel
   and the toe; the toe end sits toward the big toe.
2. **The inside (the "last")** (``_Loft``): a closed surface over that outline,
   drawn as slices across the shoe, one every millimetre or so. Each slice
   starts at the floor outline's two edges, leans outward a few millimetres
   on the way up (a foot is widest a little above the floor, and a heel
   bulges out over its own footprint), then rounds inward to the roof like
   a squashed circle (a superellipse). Toward the two ends every slice gets
   lower as well as narrower, along a rounded curve, so the heel and the toe
   cap close like the end of an egg rather than a box. The floor slopes
   gently from the heel down to the ball (the heel sits ``drop_mm`` higher).
3. **The outside** is made the same way, ``upper_mm`` further out, and solid
   down to the ground: that lower part is the sole. The sole's side stands
   out a little at the ground (the style's ``flare_mm``) and leans in to a
   waist at the footbed's level; from there the upper leans back out with
   the foot. The lines round the sole's side are drawn into the same slices.
4. **Standing the foot in the shoe** (``Footbed.place``): what of the foot
   is within 10 mm of the floor is what stands on it. The floor's outline is
   placed round that, turned and slid a little so the least of it hangs over
   (``recon/shoe.py``'s placing), the back of the whole heel against the
   back of the inside.
5. **Letting out** (``_let_out``): where everything the scan shows of the
   foot is wider than the standard shape's widest point, that side's wall
   leans out further, by what the foot needs plus the fit's ease (at most
   ``LET_OUT_MAX_MM``), and the outside and the sole move out with it. The
   toe box stays the standard shape.
6. **The footbed** (``Footbed``, ``_under_the_foot``): the insole generator's
   height map, laid on the floor where the foot stands, scaled in plan to a
   ruler's length when one is given and the scan reads differently. From
   just inside the foot's edge it carries on level to the wall, so there is
   no groove there. It never rises above what the insole generator allows
   (its relief and caps), and is lower where those two caps would leave a
   step. Without a sole scan it is the flat floor.
7. **Hollowing**: the inside, down to the footbed's surface and no further,
   is subtracted from the outside. What is left is the sole with the footbed
   as its top, and a shell of even thickness over the foot.
8. **The opening**: everything above a curve that starts low behind the heel
   (``heel_rim_mm`` above the floor) and climbs to the top of the instep is
   cut away. That leaves a low lip round the heel and a closed front: a
   clog. The curve stays at least ``HEEL_LIP_MIN_MM`` above the footbed all
   along, or the shoe is refused.
9. **The pattern**: diamond-shaped windows are cut through the upper, each
   pointing straight out of the surface, in rows that follow the shoe's own
   curves. Diamonds, so that on the upright sides a window narrows to a
   point at its top instead of ending in a flat lintel the printer has to
   bridge (whether they print cleanly is untested, the long shallow ones of
   the ``stream`` style least certain). None in the toe cap, round the heel,
   in the sole, within a few millimetres of the opening's edge, or where the
   footbed stands behind the wall.
10. **Tread**: shallow grooves across the bottom, inside a solid rim.
11. **Tidying** (``_weld``): points of the finished surface a hair apart are
    joined, so the file stays one closed surface when its numbers are rounded.

Coordinates of the output: millimetres, x forward from the back of the shoe,
y toward the foot's left, z up, the bottom on z = 0.

Nothing here has been printed or worn yet. Every thickness, height and
allowance below is a starting judgment, marked as one where it is set.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import insole as insole_mod

# The inside's plan shape at floor level, for a right shoe: (distance from the back of the heel, half-width to the
# inner side, half-width to the outer side), all as shares of the outline's length. A JUDGMENT, not measured from
# any last: the proportions of a men's running shoe's sock liner (the same table the generic insole outline is
# drawn from, where that exists), heel about 0.76 as wide as the ball, the inner side nearly straight from heel to
# ball (a flat foot's arch reaches the floor there), the toe end toward the big toe. Its width is then stretched to
# the foot's, so only the proportions between heel, ball and toe come from here.
LAST_STATIONS = (
    (0.02, 0.0836, 0.0836), (0.05, 0.1182, 0.1182), (0.10, 0.1364, 0.1364), (0.16, 0.1418, 0.1418),
    (0.25, 0.1418, 0.1436), (0.35, 0.1418, 0.1473), (0.45, 0.1455, 0.1564), (0.55, 0.1564, 0.1745),
    (0.65, 0.1709, 0.1909), (0.72, 0.1800, 0.1945), (0.80, 0.1818, 0.1800), (0.88, 0.1691, 0.1491),
    (0.94, 0.1418, 0.1036), (0.98, 0.0964, 0.0564),
)
LAST_TOE_TIP = 0.04   # the very front sits this share of the length to the inner side (the big toe's end)

# The toe's shape: what the front stations' half-widths are multiplied by (from 0.88 of the length on).
# Round is the table as drawn. Judgments.
TOE_SHAPES = {
    "round": {0.88: 1.0, 0.94: 1.0, 0.98: 1.0},
    "square": {0.88: 1.04, 0.94: 1.15, 0.98: 1.35},
    "tapered": {0.88: 0.96, 0.94: 0.86, 0.98: 0.72},
}

# The inside's roof: height above the floor along the top of the shoe, as shares of the inside length, at shares
# of the floor outline's length from the heel. A JUDGMENT (no scan of the top of the foot is taken): for a 272 mm
# inside, 65 mm over the instep where the opening ends, 41 mm over the ball, 35 mm over the toes (a clog's roomy
# toe box). The fit's ``roof_mm`` is added over the instep, ball and toes.
ROOF = ((0.0, 0.262), (0.15, 0.262), (0.30, 0.265), (0.45, 0.255), (0.52, 0.240), (0.62, 0.195), (0.72, 0.152),
        (0.80, 0.136), (0.88, 0.130), (1.0, 0.130))
ROOF_POWER = 2.4      # the roof's roundness across the shoe: 2 is an ellipse, higher is boxier (more room at the sides)

# How far the inside leans out above the floor before it rounds over, and how high its widest point is (mm, for a
# 272 mm inside; scaled with the length), at shares of the length. The heel's numbers follow the one real foot
# measured so far (docs/insole.md: 71 mm across near the floor, 74 mm at 12 mm up, 86 mm at 30 mm up); the ball's
# and the toes' are judgments.
BULGE = ((0.0, 6.0, 30.0), (0.20, 6.0, 30.0), (0.55, 2.5, 13.0), (0.80, 2.5, 12.0), (1.0, 1.5, 10.0))
REFERENCE_LENGTH_MM = 272.0

# The two ends: over this share of the inside's length from the heel's end and from the toe's, every slice gets
# lower, along a rounded curve (``END_POWER``: 2 would be a quarter ellipse; higher is fuller, so less of the
# length is lost to the rounding at the heights where the heel and the toes actually reach). Judgments.
END_ROUND = (0.10, 0.10)
END_POWER = 2.6

# What a fit adds to the foot (mm). JUDGMENTS, untested on a printed shoe: the usual shoe-fitting advice is about a
# thumb's width past the longest toe; TPU doesn't give the way a knitted upper does, so nothing is taken off the
# width even for "snug".
FIT = {
    "snug": dict(toe_room_mm=8.0, width_mm=0.0, roof_mm=-2.0),
    "regular": dict(toe_room_mm=12.0, width_mm=2.0, roof_mm=0.0),
    "roomy": dict(toe_room_mm=15.0, width_mm=5.0, roof_mm=3.0),
}

# The inside's width across the ball stays between these shares of its length, whatever the foot (a shoe's
# proportions; the same band the generic insole outline is held to).
BALL_SHARE = (0.33, 0.42)
FOOT_LENGTH_MM = (180.0, 330.0)   # an adult foot, as foot_prep's plausibility check has it
SCAN_VS_RULER_REFUSE = 0.15       # a scan this far from the ruler isn't this foot (or isn't in millimetres)
SCAN_VS_RULER_WARN = 0.02
SCAN_WIDTH_NOTE = 0.06            # a standing foot spreads wider than one scanned resting in the air: a few percent
                                  # between the scan's width and the ruler's is expected, more than this is said

# Where the foot itself is wider than the standard shape, the inside is let out to it (``_let_out``): up to this
# far on either side, everywhere behind the toe box (fully up to the first share of the length, fading to nothing
# by the second: the toe box stays the standard shape). What the scan shows of the foot's sides is everything
# under ``insole.SILHOUETTE_HEIGHT_MM``. The first real foot (right sole scan 2349, a flat foot, sized by ruler)
# stands up to 15.9 mm wider than the standard shape along its inner side, more than 5 mm wider from 10% to
# 57% of the length, and nowhere wider on its outer side. The limit is a JUDGMENT.
LET_OUT_MAX_MM = 20.0
LET_OUT_UNTIL = (0.75, 0.88)

# The outermost ring of the scanned sole is not read reliably: the sole turns up into the foot's side there, and
# the insole generator's smoothing blends the edge with the bare floor beside it (on scan 2349 the fill within
# 1 mm of the foot's edge has a median of 2.5 mm under the ball where it is 5.7 mm the next millimetre in; on
# the SYNTHETIC block foot, whose true fill is a level 11 mm right to the edge, the insole's surface is 6.2 mm
# at the edge, 10.3 mm 2 mm in and 10.8 mm 3 mm in). The shoe's footbed takes the insole's surface up to this
# far inside the foot's edge, twice that smoothing's width, and carries it on level from there to the wall.
FOOTBED_EDGE_MM = 2 * insole_mod.SMOOTH_SIGMA_MM

# Cushioning is a print setting, not a shape: the sole's infill. Starting points only, untested (the same three
# densities the insole print notes suggest trying as cubes first).
CUSHION = {"soft": 15, "medium": 20, "firm": 25}

# Styles: what the outside looks like. None changes the inside. ``pattern`` is the window shape (width along the
# shoe : height up the wall), ``pitch_mm`` the spacing of windows, ``openness`` the share of the patterned area
# that is window, ``sole_mm`` the thickness under the ball of the foot, ``flare_mm`` how far the sole stands out
# at the ground past the upper's widest, ``grooves`` the lines round the sole's side.
STYLES = {
    "vent": dict(label="Vent", about="rows of small diamond windows over the forefoot and sides, a mid-height sole with two lines",
                 pattern=(1.0, 1.0), pitch_mm=(11.0, 10.0), openness=0.28, sole_mm=16.0, flare_mm=1.5, grooves=2),
    "stream": dict(label="Stream", about="long slim windows running the length of the shoe, a thick flared sole with three lines",
                   pattern=(3.2, 1.0), pitch_mm=(24.0, 9.0), openness=0.30, sole_mm=22.0, flare_mm=4.0, grooves=3),
    "stone": dict(label="Stone", about="a smooth closed upper with no windows, a slim plain sole",
                  pattern=None, pitch_mm=None, openness=0.0, sole_mm=13.0, flare_mm=0.0, grooves=0),
}

MIN_STRUT_MM = 2.6        # the least material left between two windows (a judgment: about six 0.4 mm lines)
WINDOW_EDGE_MM = 5.0      # no window closer than this to the opening's edge
# The least the opening's edge stands above the footbed anywhere along it (mm). A JUDGMENT, the same 12 mm the
# rim has always had to stand over a flat floor: lower, a clog's back holds too little of the heel. With the
# insole's 12 mm heel cap and the default 26 mm rim it is at least 14 mm.
HEEL_LIP_MIN_MM = 12.0
GROOVE_DEPTH_MM = 0.9     # the lines round the sole's side
TREAD_DEPTH_MM = 1.6
TREAD_WIDTH_MM = 2.4
TREAD_PITCH_MM = 8.0
TREAD_RIM_MM = 6.0        # the bottom's outer rim stays solid
WELD_MM = 0.002           # points of the finished surface closer together than this become one point


@dataclass
class ShoeParams:
    """What the shoe is made to. The foot's two measurements, then the wearer's preferences."""
    foot_length_mm: float | None = None   # heel to longest toe, standing, by ruler. None: the sole scan's own length
    foot_width_mm: float | None = None    # across the ball, standing, by ruler. None: the sole scan's own width
    fit: str = "regular"                  # snug | regular | roomy (FIT)
    sock_mm: float = 0.0                  # room for a sock thicker than the one the foot was measured in
    toe: str = "round"                    # round | square | tapered (TOE_SHAPES)
    style: str = "vent"                   # STYLES
    openness: float | None = None         # share of the patterned area cut away; None: the style's own
    sole_mm: float | None = None          # thickness under the ball of the foot; None: the style's own
    drop_mm: float = 6.0                  # the heel sits this much higher than the ball (front to back only: no
                                          # sideways tilt, which would be posting)
    cushion: str = "medium"               # soft | medium | firm: the sole's infill when printed (CUSHION)
    heel_rim_mm: float = 26.0             # the rim behind the heel, above the inside's floor (the footbed's heel
                                          # cup stands in it: the rim must clear that by HEEL_LIP_MIN_MM)
    throat: float = 0.50                  # the opening ends this share of the length from the heel
    upper_mm: float = 2.4                 # the upper's thickness (six 0.4 mm lines). A judgment for TPU 95A
    tread: bool = True
    bed_mm: float = 256.0                 # printer bed (Bambu X1/P1/A1); for the fit check and the 3MF's placing


class FootwearError(ValueError):
    pass


@dataclass
class Shoe:
    mesh: object                    # trimesh.Trimesh, output frame (mm)
    foot: str
    params: ShoeParams
    report: dict = field(default_factory=dict)


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _table(rows, col: int = 1):
    """A smooth curve through one column of a table of (share of length, value, ...) rows."""
    from scipy.interpolate import PchipInterpolator

    return PchipInterpolator([r[0] for r in rows], [r[col] for r in rows], extrapolate=True)


def _ends_round(x, x0: float, x1: float, r0: float, r1: float):
    """1 along the middle of [x0, x1], falling to 0 at each end over the distances r0 and r1 along a rounded
    curve (a quarter superellipse, ``END_POWER``): upright where it reaches 0, level where it reaches 1."""
    x = np.asarray(x, float)
    a = np.clip((x - x0) / r0, 0.0, 1.0)
    b = np.clip((x1 - x) / r1, 0.0, 1.0)
    return ((1 - (1 - a) ** END_POWER) * (1 - (1 - b) ** END_POWER)) ** (1 / END_POWER)


def _over(y_widest, z_widest, y_top, z_top, phi):
    """The rounding over the top of a slice: a quarter superellipse from its widest point (phi = 0) to its top
    point (phi = 90 degrees). Upright at the widest point, level at the top."""
    phi = np.clip(np.asarray(phi, float), 0.0, np.pi / 2)
    e = 2.0 / ROOF_POWER
    y = y_top + (y_widest - y_top) * np.clip(np.cos(phi), 0.0, 1.0) ** e
    z = z_widest + (z_top - z_widest) * np.clip(np.sin(phi), 0.0, 1.0) ** e
    return y, z


def _outline_polygon(x, y_inner, y_outer):
    """A plan outline from its two edges (functions of x), which meet at the first and the last x."""
    import shapely

    return shapely.Polygon(np.r_[np.c_[x, y_inner(x)], np.c_[x[-2:0:-1], y_outer(x[-2:0:-1])]])


def _edges(polygon):
    """A plan outline -> its inner (+y) and outer edges, each as a function of x."""
    ring = np.asarray(polygon.exterior.coords)[:-1]
    ring = np.roll(ring, -int(ring[:, 0].argmin()), axis=0)       # start at the back...
    j = int(ring[:, 0].argmax())                                  # ...and split at the front
    a, b = ring[:j + 1], np.r_[ring[j:], ring[:1]][::-1]
    if a[:, 1].mean() < b[:, 1].mean():
        a, b = b, a
    fa, fb = (lambda x, c=c: np.interp(x, np.maximum.accumulate(c[:, 0]), c[:, 1]) for c in (a, b))
    return fa, fb


def _tube(rings: np.ndarray):
    """Slices -> a closed solid. ``rings`` is (slices, points, 3): each slice's points in order from its inner
    bottom corner, up the inner side, over the top (one point), and down the outer side to its outer bottom
    corner; the bottom is the straight line that closes it. Skin joins each slice to the next, and the first and
    the last slice (both tiny) are closed flat."""
    import manifold3d as m3

    N, M, _ = rings.shape
    idx = np.arange(N * M).reshape(N, M)
    a, b = idx[:-1], np.roll(idx[:-1], -1, axis=1)
    c, d = np.roll(idx[1:], -1, axis=1), idx[1:]
    F = [np.c_[a.ravel(), b.ravel(), c.ravel()], np.c_[a.ravel(), c.ravel(), d.ravel()]]
    top = (M - 1) // 2
    for ring, flip in ((idx[0], True), (idx[-1], False)):   # the end caps: strips across, bottom to top
        cap = []
        for m in range(top):
            A, B, B2, A2 = ring[m], ring[m + 1], ring[M - 2 - m], ring[M - 1 - m]
            cap += [(A, B, A2)] if B == B2 else [(A, B, B2), (A, B2, A2)]
        cap = np.array(cap)
        F.append(cap[:, ::-1] if flip else cap)
    F = np.vstack(F)
    solid = m3.Manifold(m3.Mesh(vert_properties=rings.reshape(-1, 3).astype(np.float32), tri_verts=F.astype(np.uint32)))
    if solid.status() != m3.Error.NoError or solid.volume() <= 0:
        raise FootwearError(f"the shoe's surface came out broken ({solid.status()}); please report the sizes used")
    return solid


# ---------------------------------------------------------------------------
# sizing: the foot -> the inside
# ---------------------------------------------------------------------------
TIGHT_AT_BALL = "It may be tight across the ball: check before wearing."


def size_inside(foot_length_mm: float, foot_width_mm: float, p: ShoeParams, scanned: bool = False) -> dict:
    """The standard shape's inside length and width (mm) for a foot, the fit's room added, and any note about
    its proportions.

    The length is the foot's plus the fit's room past the toes; the width is the foot's plus the fit's ease. The
    width is then held between ``BALL_SHARE`` of the length: a foot much narrower or wider than a shoe's
    proportions gets the nearest normal shoe in its length, and a note saying how far off its own width that is.
    ``scanned``: a sole scan comes with the foot, so where it shows the foot wider than that the walls will be
    let out (``_let_out``), and whether a wide foot still has too little room is only known after that: the
    note for it is left to ``build`` (``narrower_mm`` says by how much the standard shape is narrower).
    """
    if p.fit not in FIT:
        raise FootwearError(f"fit must be one of {sorted(FIT)}")
    if not FOOT_LENGTH_MM[0] <= foot_length_mm <= FOOT_LENGTH_MM[1]:
        raise FootwearError(f"a foot {foot_length_mm:.0f} mm long is outside an adult foot's "
                            f"({FOOT_LENGTH_MM[0]:.0f}-{FOOT_LENGTH_MM[1]:.0f} mm): check the length, in millimetres")
    if foot_width_mm <= 0:
        raise FootwearError("the foot's width must be more than 0 mm")
    if not 0.0 <= p.sock_mm <= 4.0:
        raise FootwearError("sock_mm is the extra thickness of the sock to be worn: between 0 and 4 mm")
    f = FIT[p.fit]
    length = foot_length_mm + f["toe_room_mm"] + p.sock_mm
    wanted = foot_width_mm + f["width_mm"] + 2 * p.sock_mm
    width = float(np.clip(wanted, BALL_SHARE[0] * length, BALL_SHARE[1] * length))
    notes = []
    if width > wanted + 0.05:
        notes.append(f"this foot is narrow for its length ({foot_width_mm:.0f} mm across the ball, {foot_length_mm:.0f} mm "
                     f"long): the shoe keeps a normal shoe's proportions, so its inside is {width - wanted:.0f} mm wider "
                     "than the fit alone would make it. Expect room at the sides.")
    elif width < wanted - 0.05 and not scanned:
        notes.append(f"this foot is wide for its length ({foot_width_mm:.0f} mm across the ball, {foot_length_mm:.0f} mm "
                     f"long): the shoe keeps a normal shoe's proportions, so its inside is {wanted - width:.0f} mm narrower "
                     f"than the fit alone would make it. {TIGHT_AT_BALL}")
    return dict(length_mm=round(length, 1), width_mm=round(width, 1), toe_room_mm=f["toe_room_mm"] + p.sock_mm,
                width_ease_mm=round(width - foot_width_mm, 1), roof_ease_mm=f["roof_mm"] + p.sock_mm, notes=notes,
                narrower_mm=round(max(0.0, wanted - width), 1) if width < wanted - 0.05 else 0.0)


def _wide_note(length: float, width: float, narrower: float, let_out, loft, over: dict) -> str:
    """The note for a scanned foot wide for its length, once the walls have been let out for it: whether they
    were let out across the ball (and the shoe is wider there than a normal one's proportions), whether the
    scan's outline fits across the ball anyway, or whether it still may not (then ``over`` says where)."""
    head = (f"this foot is wide for its length ({width:.0f} mm across the ball, {length:.0f} mm long): a normal shoe's "
            f"proportions make the standard shape {narrower:.0f} mm narrower than the fit alone would. ")
    if over["where"] and "ball" in over["where"]:
        return head + TIGHT_AT_BALL
    if let_out is not None and max(float(f(0.72 * loft.L)) for f in let_out) >= 0.5:
        return head + ("The sole scan shows the foot wider than that across the ball, so the walls are let out for it "
                       "there: the shoe is wider than a normal shoe's proportions where this foot needs it.")
    return head + "The sole scan's outline fits inside it across the ball."


# ---------------------------------------------------------------------------
# the floor outline
# ---------------------------------------------------------------------------
class FloorOutline:
    """The inside's plan shape at floor level: heel at x = 0, toes along +x, inner side toward +y (a right shoe).

    ``y_inner(x)`` and ``y_outer(x)`` give its two edges; ``polygon`` is the same shape as a closed outline.
    Made by drawing a smooth curve through the squares of ``LAST_STATIONS``' half-widths, which is what rounds
    the two ends: a width whose square falls to zero in a straight line closes like a circle does.
    """

    def __init__(self, length_mm: float, width_mm: float, toe: str = "round"):
        from scipy.interpolate import PchipInterpolator

        if toe not in TOE_SHAPES:
            raise FootwearError(f"toe must be one of {sorted(TOE_SHAPES)}")
        k = TOE_SHAPES[toe]
        S = [(s, a * k.get(s, 1.0), b * k.get(s, 1.0)) for s, a, b in LAST_STATIONS]
        s = np.array([0.0, *[r[0] for r in S], 1.0])
        half = np.array([0.0, *[(a + b) / 2 for _, a, b in S], 0.0])
        mid = np.array([0.0, *[(a - b) / 2 for _, a, b in S], LAST_TOE_TIP * (0.5 if toe == "tapered" else 1.0)])
        self._half2 = PchipInterpolator(s, half ** 2)
        self._mid = PchipInterpolator(s, mid)
        self.length = float(length_mm)
        # stretch across, so the ball is exactly as wide as asked: measured the way a foot's width is, between two
        # straight edges along the shoe (the inner side is widest further forward than the outer side)
        u = np.linspace(0.5, 0.9, 401)
        widest = (self._mid(u) + np.sqrt(self._half2(u))).max() - (self._mid(u) - np.sqrt(self._half2(u))).min()
        self._ky = width_mm / (widest * self.length)
        self.width = float(width_mm)
        x = self.length * (1 - np.cos(np.linspace(0, np.pi, 361))) / 2   # closer together toward the two ends
        self.polygon = _outline_polygon(x, self.y_inner, self.y_outer)

    def half(self, x):
        return self.length * self._ky * np.sqrt(np.clip(self._half2(np.clip(np.asarray(x, float) / self.length, 0, 1)), 0, None))

    def middle(self, x):
        return self.length * self._ky * self._mid(np.clip(np.asarray(x, float) / self.length, 0, 1))

    def y_inner(self, x):
        return self.middle(x) + self.half(x)

    def y_outer(self, x):
        return self.middle(x) - self.half(x)


# ---------------------------------------------------------------------------
# the inside and the outside: one closed surface each
# ---------------------------------------------------------------------------
class _Loft:
    """The inside's shape and the outside's, as slices across the shoe.

    A slice of the inside at x: from the floor outline's two edges (at the floor's height there), leaning out
    by ``lean(x)`` to the widest point ``widest_at(x)`` up, then over to the top point at ``roof(x)`` above the
    floor. The top point sits toward the inner side over the instep (a foot is highest along its inner side) and
    in the middle over the toes. Within ``END_ROUND`` of each end the heights (and the lean) shrink toward
    nothing, which rounds the heel and the toe cap.

    A slice of the outside is the same shape ``upper`` further out, carried on down to the ground: in to a
    waist at the footbed's level, then out to ``flare`` past the widest at the ground, with the sole's lines
    dipped into that stretch. ``inside()`` and ``outside()`` make the two solids; ``outside_point`` gives any
    point of the outside above its widest, with the surface's own directions there, for placing the windows.

    ``let_out``: how much further each side's widest point stands out than the standard shape's, as two
    functions of x (inner side, outer side; mm, before the two ends' rounding), for a foot that is wider than
    the standard shape above the floor (``_let_out``). The floor outline stays where it is, so that side's
    wall leans out more; the outside moves out with it from the ground up (the waist keeps its standard
    depth), so the sole stands under the let-out wall and what is under the footbed there is solid.
    """

    def __init__(self, floor: FloorOutline, roof_ease: float, sole: float, drop: float, upper: float,
                 flare: float = 0.0, grooves: int = 0, slices: int = 280, let_out=None):
        import shapely

        self._made_with = dict(floor=floor, roof_ease=roof_ease, sole=sole, drop=drop, upper=upper, flare=flare,
                               grooves=grooves, slices=slices)
        self.floor, self.upper, self.flare, self.grooves = floor, upper, flare, grooves
        L = self.L = floor.length
        k = L / REFERENCE_LENGTH_MM
        roof, lean, widest_at = _table(ROOF), _table(BULGE, 1), _table(BULGE, 2)

        def share(x):
            return np.clip(np.asarray(x, float) / L, 0.0, 1.0)

        self._round = (END_ROUND[0] * L, END_ROUND[1] * L)
        # the floor: the heel `drop` higher than the ball, level under each, a smooth ramp between
        self.floor_z = lambda x: sole + drop * (1 - _smoothstep((share(x) - 0.22) / 0.40))
        self.roof = lambda x: L * roof(share(x)) + roof_ease * _smoothstep((share(x) - 0.25) / 0.2) * _smoothstep((0.95 - share(x)) / 0.15)
        self.ends = lambda x: _ends_round(x, 0.0, L, *self._round)
        self.lean = lambda x: k * lean(share(x)) * self.ends(x)                 # the standard shape's, both sides
        let = let_out or (lambda x: 0.0 * np.asarray(x, float),) * 2
        self.lean_of = lambda side, x: self.lean(x) + let[side](x) * self.ends(x)   # this shoe's: 0 inner, 1 outer
        self.widest_at = lambda x: k * widest_at(share(x))
        self.top_y = lambda x: floor.middle(x) + (0.22 - 0.17 * _smoothstep((share(x) - 0.50) / 0.35)) * floor.half(x)
        # the upper's thickness is measured square to its surface: where the roof slopes (down from the instep
        # to the toes), the outside stands that much further above the inside
        top = lambda x: self.floor_z(x) + self.roof(x)  # noqa: E731
        self.upper_up = lambda x: upper * np.sqrt(1 + (top(np.asarray(x, float) + 0.5) - top(np.asarray(x, float) - 0.5)) ** 2)

        u = np.linspace(0.004, np.pi - 0.004, slices)     # closer together toward the two ends, where it curves most
        self.xi = L * (1 - np.cos(u)) / 2
        self.inside_widest = _outline_polygon(np.r_[0.0, self.xi, L], lambda x: floor.y_inner(x) + self.lean_of(0, x),
                                              lambda x: floor.y_outer(x) - self.lean_of(1, x))
        self.outside_widest = self.inside_widest.buffer(upper, quad_segs=32)
        self._wide = _edges(self.outside_widest)
        self.x0, _, self.x1, _ = self.outside_widest.bounds
        self.xo = self.x0 + (self.x1 - self.x0) * (1 - np.cos(u)) / 2
        xg = np.r_[self.x0, self.xo, self.x1]
        g = self._outside_at(xg)["yg"]                    # the shoe's outline on the ground
        self.ground = shapely.Polygon(np.r_[np.c_[xg, g[0]], np.c_[xg[-2:0:-1], g[1][-2:0:-1]]])

    def let_out_by(self, let_out) -> "_Loft":
        """The same shoe with its two sides let out (see the class's own words on ``let_out``)."""
        return _Loft(**self._made_with, let_out=let_out)

    # -- one slice ------------------------------------------------------------
    def _inside_at(self, x) -> dict:
        x = np.asarray(x, float)
        zf, n = self.floor_z(x), self.ends(x)
        yi, yo = self.floor.y_inner(x), self.floor.y_outer(x)
        return dict(yf=(yi, yo), yw=(yi + self.lean_of(0, x), yo - self.lean_of(1, x)), zf=zf,
                    zw=zf + self.widest_at(x) * n, yc=self.top_y(x), zc=zf + self.roof(x) * n)

    def _outside_at(self, x) -> dict:
        x = np.asarray(x, float)
        t = self.upper
        xc = np.clip(x, 0.0, self.L)
        yi, yo = self._wide[0](x), self._wide[1](x)
        w = np.maximum(yi - yo, 0.0)
        cap = _ends_round(x, self.x0, self.x1, self._round[0] + t, self._round[1] + t)
        # the waist is as deep as the standard lean (a let-out side's waist moves out with it), easing in over
        # the first and last 12 mm so the sole's side has no crease where the inside's two ends begin
        e = np.minimum(self.lean(xc), 0.35 * w) * _smoothstep(x / 12.0) * _smoothstep((self.L - x) / 12.0)
        fl = self.flare * _ends_round(x, self.x0, self.x1, *self._round)
        zf = self.floor_z(xc)
        return dict(yg=(yi + fl, yo - fl),       # at the ground
                    ya=(yi - e, yo + e),         # the waist, at the footbed's level
                    yw=(yi, yo),                 # the widest
                    zf=zf, zw=zf + self.widest_at(xc) * cap,
                    yc=np.clip(self.top_y(xc), yo + 0.2 * w, yi - 0.2 * w), zc=zf + (self.roof(xc) + self.upper_up(xc)) * cap,
                    thin=np.clip(w / 8.0, 0.0, 1.0))   # 0 at the very ends: where the sole's lines fade out

    # -- the solids -----------------------------------------------------------
    @staticmethod
    def _stack(x, sides, top):
        """Each side's points (slices x steps, y and z) and the top points -> rings for ``_tube``."""
        rings = []
        for y, z in sides:
            rings.append(np.stack([np.broadcast_to(x[:, None], y.shape), y, z], axis=2))
        return np.concatenate([rings[0], top[:, None, :], rings[1][:, ::-1]], axis=1)

    def inside(self, lower: int = 8, over: int = 36, below: float = 0.0):
        """The inside ("last") as a solid: what the shoe is hollowed by. ``below`` starts every slice that far
        under the floor (for cutting it off at the footbed's surface, which is never under the floor)."""
        x = self.xi
        s = self._inside_at(x)
        t = np.linspace(0, 1, lower + 1)[None, :]
        phi = np.linspace(0, np.pi / 2, over + 1)[None, 1:-1]
        sides = []
        for k in (0, 1):
            yf, yw, zf, zw = s["yf"][k][:, None], s["yw"][k][:, None], s["zf"][:, None], s["zw"][:, None]
            y_top, z_top = _over(yw, zw, s["yc"][:, None], s["zc"][:, None], phi)
            # out by the lean over the lower steps (a quarter sine: upright where it's widest), then over the top
            z_low = zf + (zw - zf) * t
            z_low[:, 0] -= below
            sides.append((np.c_[yf + (yw - yf) * np.sin(np.pi * t / 2), y_top], np.c_[z_low, z_top]))
        return _tube(self._stack(x, sides, np.c_[x, s["yc"], s["zc"]]))

    def outside(self, side_steps: int = 48, lower: int = 8, over: int = 36):
        """The outside as a solid, down to the ground (its lower part is the sole)."""
        x = self.xo
        o = self._outside_at(x)
        f = np.linspace(0, 1, side_steps + 1)[None, :]
        t = np.linspace(0, 1, lower + 1)[None, 1:]
        phi = np.linspace(0, np.pi / 2, over + 1)[None, 1:-1]
        dips = np.zeros_like(f)
        for i in range(self.grooves):   # the sole's lines: shallow dips at even heights up its side
            dips = dips + np.exp(-0.5 * ((f - (i + 1) / (self.grooves + 1)) / 0.035) ** 2)
        sides = []
        for k in (0, 1):
            inward = -1.0 if k == 0 else 1.0
            yg, ya, yw = o["yg"][k][:, None], o["ya"][k][:, None], o["yw"][k][:, None]
            zf, zw = o["zf"][:, None], o["zw"][:, None]
            y_sole = ya + (yg - ya) * (1 - _smoothstep(f)) + inward * GROOVE_DEPTH_MM * dips * o["thin"][:, None]
            y_top, z_top = _over(yw, zw, o["yc"][:, None], o["zc"][:, None], phi)
            sides.append((np.c_[y_sole, ya + (yw - ya) * np.sin(np.pi * t / 2), y_top],
                          np.c_[zf * f, zf + (zw - zf) * t, z_top]))
        return _tube(self._stack(x, sides, np.c_[x, o["yc"], o["zc"]]))

    def outside_point(self, x, side, phi):
        """Points of the outside above its widest: at ``x``, on the inner (``side`` 0) or outer (1) side, at
        angle ``phi`` over the top (0 at the widest point, 90 degrees at the top). -> the points and the
        surface's own directions there: along the shoe, up the slice, and straight out."""
        x, side, phi = np.asarray(x, float), np.asarray(side), np.asarray(phi, float)

        def at(xx, ph):
            o = self._outside_at(xx)
            y, z = _over(np.where(side == 0, o["yw"][0], o["yw"][1]), o["zw"], o["yc"], o["zc"], ph)
            return np.c_[xx, y, z], o

        p, o = at(x, phi)
        up = at(x, phi + 0.02)[0] - at(x, phi - 0.02)[0]
        along = at(x + 0.5, phi)[0] - at(x - 0.5, phi)[0]
        up /= np.linalg.norm(up, axis=1, keepdims=True)
        out = np.cross(along, up)
        out /= np.linalg.norm(out, axis=1, keepdims=True)
        away = np.einsum("ij,ij->i", out, p - np.c_[x, o["yc"], o["zw"]])
        out *= np.where(away < 0, -1.0, 1.0)[:, None]     # pointing away from the inside
        along = np.cross(up, out)
        return p, along, up, out

    def inside_ends(self) -> tuple[float, float]:
        """Where a foot's two ends can reach inside the shoe (x of each, mm), along the top of the shoe: where
        the inside first stands as high as a heel reaches back furthest, and where it last stands as high as
        the toes reach forward furthest (the heights where the inside is widest at each end, ``BULGE``). The
        two ends round over, so these are a little inside the floor outline's own ends."""
        L = self.L
        back = np.linspace(0.0, 1.5 * self._round[0], 3000)
        front = L - np.linspace(0.0, 1.5 * self._round[1], 3000)
        return (float(np.interp(float(self.widest_at(0.0)), self.roof(back) * self.ends(back), back)),
                float(np.interp(float(self.widest_at(L)), self.roof(front) * self.ends(front), front)))

    def inside_size(self) -> tuple[float, float]:
        """The inside's length and width as a foot uses them (mm). Length: between ``inside_ends``. Width:
        across the ball where the standard shape is widest, between two straight edges along the shoe, as a
        foot's width is measured (what a side is let out for one foot is not counted: ``_let_out`` reports it)."""
        x_heel, x_toe = self.inside_ends()
        ball = self.L * np.linspace(0.5, 0.9, 401)
        width = float((self.floor.y_inner(ball) + self.lean(ball)).max() - (self.floor.y_outer(ball) - self.lean(ball)).min())
        return x_toe - x_heel, width


def _loft_for(size: dict, p: ShoeParams, sole: float, flare: float, grooves: int) -> _Loft:
    """The loft whose inside measures ``size`` (``_Loft.inside_size``): the floor outline is drawn a little
    longer and narrower than that, by what the rounded ends take off the length and the lean adds to the width,
    then corrected by what the built shape actually measures."""
    k = size["length_mm"] / REFERENCE_LENGTH_MM
    L, W = size["length_mm"], size["width_mm"] - 2 * k * float(_table(BULGE, 1)(0.72))
    for _ in range(5):
        loft = _Loft(FloorOutline(L, W, p.toe), size["roof_ease_mm"], sole, p.drop_mm, p.upper_mm, flare, grooves)
        length, width = loft.inside_size()
        if abs(length - size["length_mm"]) < 0.02 and abs(width - size["width_mm"]) < 0.02:
            break
        L += size["length_mm"] - length
        W += size["width_mm"] - width
    return loft


# ---------------------------------------------------------------------------
# the footbed: the insole generator's surface, laid on the shoe's floor
# ---------------------------------------------------------------------------
class Footbed:
    """The first-fit insole's fill (``Insole.surface``) as heights above the shoe's floor.

    The insole generator has already done everything that makes it a first fit: read the sole, set the surface
    ``relief_mm`` below it, smoothed it downward only, capped it, left unseen sole flat. Nothing is added here;
    the heights are only moved to where the foot stands in the shoe:

    - turned to a right foot's layout (inner side toward +y) for a left foot, as the shoe is built;
    - made the ruler's size, when a ruler's length is given and the scan reads differently (``size_to``: the
      same scale along and across, heights not scaled);
    - carried on level from ``FOOTBED_EDGE_MM`` inside the foot's own edge outward (each point past there takes
      the height of the nearest point further in), so the footbed meets the shoe's wall instead of leaving a
      groove beside the foot, and the scan's unreliable edge is not built in;
    - lowered where the insole's two caps meet. The insole's fill is capped at one height round the heel and
      another under the arch, and steps from one to the other on a line across the foot (on scan 2349, from
      12 to 20 mm along the foot's inner side). In a shoe that step is a ledge inside the wall, so here the
      cap climbs from the heel's to the arch's over the same 15% of the length the insole's heel zone fades
      over. That only ever lowers the surface.

    Two outlines of the foot come with it, both seen from above: ``outline``, everything the scan shows of the
    foot (under ``insole.SILHOUETTE_HEIGHT_MM``: what the shoe's walls have to hold), and ``standing``, the
    foot within ``recon.shoe.FIT_HEIGHT_MM`` of the floor (what stands on the footbed; a heel and a flat foot's
    inner side bulge out above it).
    """

    def __init__(self, ins, foot: str):
        import shapely
        from scipy import ndimage

        from .recon import shoe as shoe_mod

        s = ins.surface
        if s is None:
            raise FootwearError("this insole carries no height map (made by an older footscan?): make the insole again")
        xs, ys, fill, under, outline = s["xs"], s["ys"], s["fill"], s["under_foot"], s["foot_outline"]
        standing = outline
        if ins.sole is not None:
            try:
                near = insole_mod.silhouette(ins.sole, height=shoe_mod.FIT_HEIGHT_MM).intersection(outline)
                if near.geom_type != "Polygon":
                    near = max(near.geoms, key=lambda g: g.area)
                if near.area > 0.3 * outline.area:   # (less: almost nothing of this scan is near the floor)
                    standing = near
            except (insole_mod.InsoleError, shapely.errors.GEOSException, ValueError, AttributeError):
                pass
        q = ins.params   # the heel's cap easing into the arch's, over the insole's own heel zone (1 in the heel, 0 past it)
        w_heel = s["heel_weight"]
        fill = np.minimum(fill, (q.max_arch_fill_mm + (q.heel_cup_depth_mm - q.max_arch_fill_mm) * _smoothstep(w_heel))[None, :])
        if foot == "left":   # the insole's frame has y toward the foot's left: a left foot's inner side is -y there
            ys, fill, under = -ys[::-1], fill[::-1], under[::-1]
            outline, standing = (shapely.transform(g, lambda c: c * [1.0, -1.0]) for g in (outline, standing))
        firm = ndimage.distance_transform_edt(under) * float(xs[1] - xs[0]) > FOOTBED_EDGE_MM
        if not firm.any():
            firm = under
        idx = ndimage.distance_transform_edt(~firm, return_distances=False, return_indices=True)
        self._xs, self._ys = xs, ys
        self._fill = fill[tuple(idx)]          # carried on level from just inside the foot's edge
        self.outline = outline                 # (insole frame, inner side +y)
        self.standing = standing
        x0, y0, x1, y1 = outline.bounds
        self.heel_x = x0
        self.scan_length = float(x1 - x0)
        # the width a ruler measures across the ball: between two straight edges along the foot, over the part
        # the ball is in (a flat foot's inner side can stand out further behind it than the ball itself does)
        front = outline.intersection(shapely.box(x0 + 0.58 * self.scan_length, y0 - 1, x0 + 0.88 * self.scan_length, y1 + 1))
        self.scan_width = float(front.bounds[3] - front.bounds[1])
        self.scale = 1.0
        self._to_foot = self._to_shoe = None

    def size_to(self, length_mm: float | None, width_mm: float | None) -> list[str]:
        """Make the scanned foot the ruler's length (None: left as scanned). -> notes for the summary sheet.

        A scan that reads the foot shorter or longer than a ruler does has its size wrong, so its footbed is
        scaled by the two lengths' ratio, the same along and across; heights are not scaled (the fill is never
        made higher than the insole generator made it). The ruler's width is not scaled to: it sets the shoe's
        width, and is only compared with the scan's. More than ``SCAN_VS_RULER_REFUSE`` apart either way is
        refused."""
        notes = []
        k = length_mm / self.scan_length if length_mm else 1.0
        if abs(k - 1) > SCAN_VS_RULER_REFUSE:
            raise FootwearError(f"the scan reads the foot {self.scan_length:.0f} mm long and the ruler {length_mm:.0f} mm: too "
                                "far apart to be the same foot in millimetres. Check the measurement and the scan.")
        if abs(k - 1) > SCAN_VS_RULER_WARN:
            notes.append(f"the scan reads the foot {self.scan_length:.1f} mm long, the ruler {length_mm:.1f} mm: the shoe is "
                         f"sized by the ruler, and the footbed was scaled {100 * (k - 1):+.1f}% along and across to match "
                         "(its heights unchanged). Until the scan's size is settled, the arch may sit a few millimetres off.")
        if width_mm:
            scanned = self.scan_width * k
            off = width_mm / scanned - 1
            if abs(off) > SCAN_VS_RULER_REFUSE:
                raise FootwearError(f"the scan reads the foot {scanned:.0f} mm across the ball and the ruler {width_mm:.0f} mm: "
                                    "too far apart to be the same foot in millimetres. Check the measurement and the scan.")
            if abs(off) > SCAN_WIDTH_NOTE:
                notes.append(f"the scan reads the foot {scanned:.1f} mm across the ball, the ruler {width_mm:.1f} mm: the "
                             "shoe's width is the ruler's. A standing foot spreads a little wider than one scanned "
                             "resting; this much is worth measuring again.")
        self.scale = float(k)
        return notes

    def _sized(self, g):
        import shapely

        return shapely.transform(g, lambda c: (c - [self.heel_x, 0.0]) * self.scale + [self.heel_x, 0.0])

    def place(self, floor, heel_reach_mm: float) -> dict:
        """Stand the (sized) foot in the shoe: the floor's outline is placed round what of the foot stands on
        it, the way a shoe's insole outline is (``recon/shoe.py``: turned and slid to where the least of the
        foot hangs over). What stands on it is the standing outline with its hollows bridged straight across
        (a rubber band round it, kept inside the foot's whole outline): under a high arch nothing is near the
        floor, and the floor's own inner edge runs straight from heel to ball there, so the hollow says nothing
        about where the foot belongs. The back of the whole heel, which reaches further back above the floor
        than on it, goes ``heel_reach_mm`` from the back of the floor's outline (as far back as the inside lets
        a heel reach). -> that fit's report. After this ``height`` and ``in_shoe`` answer in shoe coordinates."""
        from .recon import shoe as shoe_mod

        whole = self._sized(self.outline)
        standing = self._sized(self.standing).convex_hull.intersection(whole)
        if standing.geom_type != "Polygon":
            standing = max(standing.geoms, key=lambda g: g.area)
        ring = np.asarray(floor.exterior.coords)[:-1]
        placed, fit = shoe_mod.fit_to_foot(floor, standing, "right", heel_reach_mm + standing.bounds[0] - whole.bounds[0])
        if fit["mirrored"]:   # the floor is drawn as a right shoe's, so this would be a bug here, not a scan's fault
            raise FootwearError("the shoe's own outline read as the other foot's; please report the sizes used")
        to = np.asarray(placed.exterior.coords)[:-1]
        # the move it found (a turn and a slide), read back off where the outline's own points went
        self._to_foot = np.linalg.lstsq(np.c_[ring, np.ones(len(ring))], to, rcond=None)[0]
        self._to_shoe = np.linalg.inv(np.c_[self._to_foot, [0.0, 0.0, 1.0]])[:, :2]
        return fit

    def in_shoe(self, which: str = "outline"):
        """The foot's ``outline`` (or its ``standing`` one), sized, where it stands in the shoe."""
        import shapely

        if self._to_shoe is None:
            raise FootwearError("place() the footbed first")
        return shapely.transform(self._sized(getattr(self, which)), lambda c: np.c_[c, np.ones(len(c))] @ self._to_shoe)

    def height(self, x, y):
        """Fill (mm above the floor) at shoe coordinates x, y."""
        from scipy.interpolate import RegularGridInterpolator

        if self._to_foot is None:
            raise FootwearError("place() the footbed first")
        f = np.c_[np.asarray(x, float).ravel(), np.asarray(y, float).ravel(), np.ones(np.size(x))] @ self._to_foot
        fx = np.clip((f[:, 0] - self.heel_x) / self.scale + self.heel_x, self._xs[0], self._xs[-1])
        fy = np.clip(f[:, 1] / self.scale, self._ys[0], self._ys[-1])
        return RegularGridInterpolator((self._ys, self._xs), self._fill)(np.c_[fy, fx]).reshape(np.shape(x))

    def highest(self, inside) -> float:
        """The highest the footbed stands anywhere inside the shoe (``inside``: its outline from above), mm."""
        import shapely

        x0, y0, x1, y1 = inside.bounds
        X, Y = np.meshgrid(np.arange(x0, x1, 0.5), np.arange(y0, y1, 0.5))
        return float(self.height(X, Y)[shapely.contains_xy(inside, X, Y)].max())


def _across(outline, x: np.ndarray):
    """An outline's two edges at each x: (its lowest y, its highest y), nan where it isn't."""
    import shapely

    lo, hi = np.full(len(x), np.nan), np.full(len(x), np.nan)
    _, y0, _, y1 = outline.bounds
    for i, xx in enumerate(x):
        b = outline.intersection(shapely.LineString([(xx, y0 - 1.0), (xx, y1 + 1.0)])).bounds
        if len(b) == 4 and np.isfinite(b[1]):
            lo[i], hi[i] = b[1], b[3]
    return lo, hi


def _let_out(loft: _Loft, foot, ease: float):
    """How far each side of the inside has to be let out for this foot. -> (the two functions ``_Loft`` takes,
    or None when neither side needs any; what was let out, for the report).

    ``foot`` is everything the scan shows of the foot, from above, where it stands in the shoe. Every
    millimetre along, each side's need is how far the foot's edge, plus ``ease``, stands outside the standard
    shape's widest point there. It is never negative (the shoe is never made narrower than the standard shape),
    never more than ``LET_OUT_MAX_MM``, faded to nothing through the toe box (``LET_OUT_UNTIL``), and smoothed
    along the shoe (the most within 4 mm either way, then blurred), so the wall stays a fair curve."""
    from scipy import ndimage

    L = loft.L
    x = np.arange(0.0, L + 1.0, 1.0)
    lo, hi = _across(foot, x)
    ends = np.maximum(loft.ends(x), 0.3)     # the lean is rounded off toward the two ends: ask for more there
    fade = 1.0 - _smoothstep((x / L - LET_OUT_UNTIL[0]) / (LET_OUT_UNTIL[1] - LET_OUT_UNTIL[0]))
    wider = (hi - (loft.floor.y_inner(x) + loft.lean(x)), (loft.floor.y_outer(x) - loft.lean(x)) - lo)
    fns, report = [], {}
    for side, w in zip(("inner", "outer"), wider):
        w = np.where(np.isnan(w), -np.inf, w)       # (no foot at this x: nothing to hold)
        n = np.clip((w + ease) / ends, 0.0, LET_OUT_MAX_MM) * fade
        n = ndimage.gaussian_filter1d(ndimage.maximum_filter1d(n, 9), 4.0)
        n[np.abs(n) < 0.05] = 0.0
        fns.append(lambda q, n=n: np.interp(np.asarray(q, float), x, n))
        out = n * loft.ends(x)
        i = int(np.argmax(out))
        report[side] = dict(max_mm=round(float(out[i]), 1), at=round(float(x[i] / L), 2))
    if max(r["max_mm"] for r in report.values()) < 0.5:
        return None, None
    return tuple(fns), report


def _hangs_over(loft: _Loft, foot) -> dict:
    """Where the foot is still wider than the shoe's inside at its widest, and by how much, reported the way
    ``recon.shoe.fit_to_foot`` reports it for an insole's outline (the same helper)."""
    from .recon import shoe as shoe_mod

    return shoe_mod.overhang_of(loft.inside_widest, foot, 0.0, loft.L, lambda px, py: py > float(loft.floor.middle(px)))


def _prism(polygon, z0: float, z1: float):
    """A shapely polygon (holes and all, or several) pushed straight up from z0 to z1, as a solid."""
    import manifold3d as m3
    from shapely.geometry.polygon import orient

    rings = []
    for g in getattr(polygon, "geoms", [polygon]):
        if g.is_empty or g.geom_type != "Polygon":
            continue
        g = orient(g, 1.0)
        rings.append(np.asarray(g.exterior.coords)[:-1])
        rings += [np.asarray(h.coords)[:-1] for h in g.interiors]
    if not rings:
        return m3.Manifold()
    return m3.Manifold.extrude(m3.CrossSection(rings, m3.FillRule.EvenOdd), z1 - z0).translate((0.0, 0.0, z0))


def _under_the_foot(loft: _Loft, bed: Footbed | None):
    """Everything under the footbed's surface, as a solid a little wider than the inside: from 4 mm under the
    floor up to the floor plus the fill (the flat floor itself without a footbed). Made the way the insole's
    own solid is: a 1 mm slab cut into small triangles, every point then moved to its height."""
    slab = _prism(loft.inside_widest.buffer(3.0), 0.0, 1.0).refine_to_length(1.5)

    def lift(v):
        v = np.array(v, dtype=float, copy=True)
        fill = bed.height(v[:, 0], v[:, 1]) if bed is not None else 0.0
        v[:, 2] = loft.floor_z(v[:, 0]) - 4.0 + v[:, 2] * (4.0 + fill)
        return v

    return slab.warp_batch(lift)


# ---------------------------------------------------------------------------
# the opening, the windows, the tread
# ---------------------------------------------------------------------------
def _opening(loft: _Loft, p: ShoeParams, bed: Footbed | None = None):
    """The opening's edge as a height at each x (``edge(x)``), the solid above it that is cut away, where the
    edge ends, and the least it stands above the footbed (mm).

    The edge starts ``heel_rim_mm`` above the inside's floor behind the heel and climbs, slowly then faster, to
    just over the roof where the opening ends (``throat``); past that it is above the shoe, so the front stays
    closed. The footbed stands on that floor (its heel cup up to the insole's heel cap behind the heel), so the
    edge is checked against the footbed's highest point across the shoe all along the opening: anywhere less
    than ``HEEL_LIP_MIN_MM`` above it the rim would hold too little of the heel, and below it the cut would take
    the top off the footbed. That is refused.
    """
    import manifold3d as m3

    if not 0.35 <= p.throat <= 0.65:
        raise FootwearError("the opening ends between 0.35 and 0.65 of the length from the heel")
    if p.heel_rim_mm < HEEL_LIP_MIN_MM:
        raise FootwearError(f"the heel's rim is at least {HEEL_LIP_MIN_MM:.0f} mm above the floor of the inside")
    back = loft.x0 - 1.0
    xt = p.throat * loft.L
    z_rim = float(loft.floor_z(0.0)) + p.heel_rim_mm
    z_top = float(loft.floor_z(xt) + loft.roof(xt)) + loft.upper + 1.0
    if z_top <= z_rim + 5.0:
        raise FootwearError("the heel's rim is as high as the roof: lower heel_rim_mm")

    def edge(x):
        u = np.clip((np.asarray(x, float) - back) / (xt - back), 0.0, None)
        return z_rim + (z_top - z_rim) * u ** 2.2

    # the footbed's highest point across the inside, every 2 mm from the heel's end to where the opening ends
    xs = np.arange(loft.x0 + 0.5, xt, 2.0)
    lo, hi = _across(loft.inside_widest, xs)
    ok = np.isfinite(lo)
    xs, lo, hi = xs[ok], lo[ok], hi[ok]
    top = loft.floor_z(xs)
    if bed is not None:
        t = np.linspace(0.0, 1.0, 41)[None, :]
        top = top + bed.height(np.repeat(xs[:, None], 41, axis=1), lo[:, None] + t * (hi - lo)[:, None]).max(axis=1)
    lip = edge(xs) - top
    i = int(np.argmin(lip))
    if lip[i] < HEEL_LIP_MIN_MM - 0.05:
        raise FootwearError(f"the opening's edge would stand only {lip[i]:.1f} mm above the footbed {xs[i]:.0f} mm from the "
                            f"back (at least {HEEL_LIP_MIN_MM:.0f} mm, so the rim holds the heel and the cut stays clear of "
                            f"the footbed): raise heel_rim_mm by {HEEL_LIP_MIN_MM - lip[i]:.1f} mm or more")

    x = np.linspace(back, back + 1.35 * (xt - back), 80)
    ring = np.r_[[(back - 40.0, z_rim)], np.c_[x, edge(x)], [(x[-1], 600.0), (back - 40.0, 600.0)]]
    wide = 2 * loft.floor.width + 80.0
    cut = m3.Manifold.extrude(m3.CrossSection([ring], m3.FillRule.Positive), wide)   # drawn in x and height...
    cut = cut.rotate((90.0, 0.0, 0.0)).translate((0.0, wide / 2, 0.0))              # ...then stood up across the shoe
    return edge, cut, float(x[-1]), round(float(lip[i]), 1)


def _windows(loft: _Loft, p: ShoeParams, edge, edge_ends: float, bed: Footbed | None):
    """The pattern: diamond windows through the upper. -> (the solids to cut away, what was made).

    Rows run the length of the shoe on both sides, each a fixed share of the way over the top, so they follow
    the roof's own curve; every other row is shifted half a step, like brickwork. Each window is a diamond-sided
    peg pushed through the upper along the surface's own outward direction. Left out: the toe cap and the heel
    (``END_ROUND``), anything within ``WINDOW_EDGE_MM`` of the opening's edge, and anything that would open
    onto the footbed.
    """
    import manifold3d as m3

    st = STYLES[p.style]
    openness = st["openness"] if p.openness is None else p.openness
    if not 0 <= openness <= 0.5:
        raise FootwearError("openness is the share of the patterned area cut away: between 0 and 0.5")
    if st["pattern"] is None or openness == 0:
        return [], dict(count=0, openness=0.0)
    (rw, rh), (px, pg) = st["pattern"], st["pitch_mm"]
    h = np.sqrt(2 * openness * px * pg * rh / rw)          # a diamond w x h has area w * h / 2
    w = h * rw / rh
    w, h = min(w, px - MIN_STRUT_MM), min(h, pg - MIN_STRUT_MM)

    L = loft.L
    phis = np.linspace(0, np.pi / 2, 181)                   # the rows are spaced on a slice over the ball
    pts = loft.outside_point(np.full(len(phis), 0.70 * L), np.zeros(len(phis), int), phis)[0]
    arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    rows = int(arc[-1] // pg)
    row_phi = np.interp((np.arange(rows) + 0.5) * pg, arc, phis)
    x_from, x_to = END_ROUND[0] * L + 4.0 + w / 2, (1 - END_ROUND[1]) * L - 4.0 - w / 2
    xs, sides, ph = [], [], []
    for r, phi in enumerate(row_phi):
        row = np.arange(x_from + (px / 2 if r % 2 else 0.0), x_to, px)
        for side in (0, 1):
            xs.append(row)
            sides.append(np.full(len(row), side))
            ph.append(np.full(len(row), phi))
    if not xs or not sum(len(r) for r in xs):
        return [], dict(count=0, openness=0.0)
    xs, sides, ph = np.concatenate(xs), np.concatenate(sides), np.concatenate(ph)
    c, along, up, out = loft.outside_point(xs, sides, ph)
    top = c[:, 2] + 0.5 * h * np.abs(up[:, 2])
    # clear of the opening's edge, which climbs toward the front: judged at the window's back end
    keep = (c[:, 0] > edge_ends) | (top + WINDOW_EDGE_MM < edge(c[:, 0] - 0.5 * w - WINDOW_EDGE_MM))
    inner = c - out * (loft.upper + 1.0)
    floor = loft.floor_z(inner[:, 0]) + (bed.height(inner[:, 0], inner[:, 1]) if bed is not None else 0.0)
    keep &= (c[:, 2] - 0.5 * h) > floor + 3.0               # not where the footbed stands behind the wall
    peg = m3.Manifold.extrude(m3.CrossSection([np.array([(-0.5, 0.0), (0.0, -0.5), (0.5, 0.0), (0.0, 0.5)])],
                                              m3.FillRule.Positive), 1.0).translate((0.0, 0.0, -0.5))
    depth = loft.upper + 3.0
    pegs = []
    for q, a, u, o in zip(c[keep], along[keep], up[keep], out[keep]):
        centre = q - o * (loft.upper / 2)
        pegs.append(peg.transform(np.c_[a * w, u * h, o * depth, centre].astype(np.float32)))
    return pegs, dict(count=len(pegs), openness=round(float(w * h / 2 / (px * pg)), 3),
                      window_mm=(round(float(w), 1), round(float(h), 1)), rows=int(rows))


def _tread(plan):
    """Shallow V-shaped grooves across the bottom, inside a solid rim: grip, and somewhere for the sole to bend."""
    import shapely

    x0, y0, x1, y1 = plan.bounds
    ym = (y0 + y1) / 2
    lines = [shapely.LineString([(x - 14.0, y0 - 5.0), (x, ym), (x - 14.0, y1 + 5.0)])
             for x in np.arange(x0 + 10.0, x1 + 14.0, TREAD_PITCH_MM)]
    grooves = shapely.union_all([ln.buffer(TREAD_WIDTH_MM / 2, cap_style="flat", join_style="mitre") for ln in lines])
    return _prism(grooves.intersection(plan.buffer(-TREAD_RIM_MM)), -1.0, TREAD_DEPTH_MM)


def _weld(V: np.ndarray, F: np.ndarray, tol: float = WELD_MM):
    """Join points of a closed surface that are closer together than ``tol``, and drop the triangles that
    shrink to nothing when they are. -> points, triangles.

    Cutting one solid with another leaves hair-length edges (a few millionths of a millimetre) where the two
    surfaces cross; written to a file, the two ends of such an edge can round to the same point, and a slicer
    then sees a pinched surface. Joining by distance alone can make a pinch of its own, where a third point sits
    just past ``tol`` from two that were joined (an edge then has four triangles on it, not two). Those edges,
    when they are themselves hair-length, are closed up the same way, until every edge has its two triangles.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    def join(V, F, pairs):
        n = len(V)
        groups, label = connected_components(coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n)),
                                             directed=False)
        W = np.zeros((groups, 3))
        np.add.at(W, label, V)                       # each group of points becomes their middle
        W /= np.bincount(label, minlength=groups)[:, None]
        G = label[F]
        G = G[(G[:, 0] != G[:, 1]) & (G[:, 1] != G[:, 2]) & (G[:, 0] != G[:, 2])]
        # two triangles left on the same three points are a flap squeezed flat: both go
        _, which, count = np.unique(np.sort(G, axis=1), axis=0, return_inverse=True, return_counts=True)
        return W, G[count[which.ravel()] == 1]

    pairs = cKDTree(V).query_pairs(tol, output_type="ndarray")
    if len(pairs):
        V, F = join(V, F, pairs)
    for _ in range(8):
        edges, count = np.unique(np.sort(F[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1), axis=0, return_counts=True)
        pinched = edges[count != 2]
        pinched = pinched[np.linalg.norm(V[pinched[:, 0]] - V[pinched[:, 1]], axis=1) < 25 * tol]
        if not len(pinched):
            break
        V, F = join(V, F, pinched)
    return V, F


# ---------------------------------------------------------------------------
# the shoe
# ---------------------------------------------------------------------------
def build(foot: str, params: ShoeParams | None = None, footbed=None) -> Shoe:
    """A clog for one foot. ``footbed`` is that foot's first-fit insole (``insole.Insole``, from the sole scan):
    its surface becomes the shoe's floor, and its outline gives the foot's length and width where the params
    don't. Without one the floor is flat, and the params must give both measurements."""
    import manifold3d as m3
    import trimesh

    p = params or ShoeParams()
    if foot not in ("left", "right"):
        raise FootwearError("foot must be 'left' or 'right'")
    if p.style not in STYLES:
        raise FootwearError(f"style must be one of {sorted(STYLES)}")
    if p.cushion not in CUSHION:
        raise FootwearError(f"cushion must be one of {sorted(CUSHION)}")
    st = STYLES[p.style]
    sole = st["sole_mm"] if p.sole_mm is None else p.sole_mm
    if not 8.0 <= sole <= 40.0:
        raise FootwearError("the sole is between 8 and 40 mm thick under the ball of the foot")
    if not 0.0 <= p.drop_mm <= 12.0:
        raise FootwearError("the heel sits between 0 and 12 mm higher than the ball of the foot")
    if not 1.6 <= p.upper_mm <= 5.0:
        raise FootwearError("the upper is between 1.6 and 5 mm thick")

    warnings: list[str] = []
    bed = None
    if footbed is not None:
        if footbed.foot != foot:
            raise FootwearError(f"the footbed is a {footbed.foot} foot's and the shoe a {foot} one")
        bed = Footbed(footbed, foot)
    scan_notes = bed.size_to(p.foot_length_mm, p.foot_width_mm) if bed is not None else []
    length = p.foot_length_mm or (bed.scan_length if bed else None)
    # without a ruler's width, the scan's own, scaled to the ruler's length with the rest of the footbed (the
    # foot the shoe holds is that size)
    width = p.foot_width_mm or (bed.scan_width * bed.scale if bed else None)
    if length is None or width is None:
        raise FootwearError("give the foot's length and width in mm, or a sole scan to read them from")
    size = size_inside(length, width, p, scanned=bed is not None)
    warnings += size["notes"] + scan_notes

    loft = _loft_for(size, p, sole, st["flare_mm"], st["grooves"])
    fit = let = over = room = None
    if bed is not None:
        fit = bed.place(loft.floor.polygon, loft.inside_ends()[0])   # the heel as far back as it can reach
        whole = bed.in_shoe("outline")
        let_out, let = _let_out(loft, whole, FIT[p.fit]["width_mm"] / 2 + p.sock_mm)
        if let_out is not None:
            loft = loft.let_out_by(let_out)
            for side in ("inner", "outer"):
                if let[side]["max_mm"] >= 1.0:
                    warnings.append(f"this foot is wider above the floor than the standard shape on its {side} side: the "
                                    f"inside is let out there by up to {let[side]['max_mm']} mm ({let[side]['at']:.0%} of the "
                                    "way along), so the shoe is fuller on that side than its style's standard shape.")
        over = _hangs_over(loft, whole)
        if size["narrower_mm"]:
            warnings.append(_wide_note(length, width, size["narrower_mm"], let_out, loft, over))
        if over["max_mm"] > 1.0:
            warnings.append(f"the scanned foot is wider than the shoe's inside at the {over['where']}, by up to {over['max_mm']} mm. "
                            "It may press there: check before wearing, or choose a roomier fit.")
        room = round(float(loft.inside_ends()[1] - whole.bounds[2]), 1)
        if room < 5.0:
            warnings.append(f"only {room} mm of room past the scanned toes: the shoe may be short.")

    # hollow the outside by the inside, down to the footbed's surface (the inside's slices start under the
    # floor, so that surface always cuts cleanly through their sides)
    shoe = loft.outside() - (loft.inside(below=1.5) - _under_the_foot(loft, bed))
    edge, cut, edge_ends, rim_over_footbed = _opening(loft, p, bed)
    shoe -= cut
    pegs, pattern = _windows(loft, p, edge, edge_ends, bed)
    if pegs:
        shoe -= m3.Manifold.batch_boolean(pegs, m3.OpType.Add)
    if p.openness and st["pattern"] is None:
        warnings.append(f"the {p.style} style has no windows, so the openness asked for ({p.openness:g}) changes nothing.")
    if p.tread:
        shoe -= _tread(loft.ground)
    if foot == "left":
        shoe = shoe.mirror((0.0, 1.0, 0.0))

    pieces = shoe.decompose()
    if len(pieces) != 1:
        raise FootwearError(f"the shoe came out in {len(pieces)} pieces: the pattern cut something free. "
                            "Lower the openness, and please report the sizes used.")
    mm = shoe.to_mesh()
    V, F = _weld(np.asarray(mm.vert_properties)[:, :3].astype(float), np.asarray(mm.tri_verts))
    V[:, 0] -= V[:, 0].min()                                     # the back of the shoe at x = 0
    mesh = trimesh.Trimesh(V, F, process=False)
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
        raise FootwearError("the shoe's solid came out broken (not closed); please report the sizes used")

    in_length, in_width = loft.inside_size()
    ext = mesh.extents
    report = dict(
        foot=foot,
        style=p.style,
        made_for=dict(foot_length_mm=round(float(length), 1), foot_width_mm=round(float(width), 1),
                      length_from="ruler" if p.foot_length_mm else "scan", width_from="ruler" if p.foot_width_mm else "scan",
                      fit=p.fit, sock_mm=p.sock_mm),
        inside=dict(length_mm=round(in_length, 1), width_mm=round(in_width, 1), floor_length_mm=round(loft.L, 1),
                    room_past_toes_mm=size["toe_room_mm"], width_ease_mm=size["width_ease_mm"],
                    roof_over_ball_mm=round(float(loft.roof(0.72 * loft.L)), 1),
                    roof_over_instep_mm=round(float(loft.roof(p.throat * loft.L)), 1)),
        length_mm=round(float(ext[0]), 1), width_mm=round(float(ext[1]), 1), height_mm=round(float(ext[2]), 1),
        volume_cm3=round(float(mesh.volume) / 1000, 1),
        triangles=int(len(mesh.faces)),
        sole=dict(under_ball_mm=round(float(sole), 1), under_heel_mm=round(float(sole + p.drop_mm), 1),
                  infill_percent=CUSHION[p.cushion], cushion=p.cushion),
        upper_mm=p.upper_mm,
        heel_rim_mm=p.heel_rim_mm,
        rim_over_footbed_mm=rim_over_footbed,
        pattern=pattern,
        footbed=None if bed is None else dict(
            max_fill_mm=round(bed.highest(loft.inside_widest), 2), scan_length_mm=round(bed.scan_length, 1),
            scan_width_mm=round(bed.scan_width, 1), scaled_percent=round(100 * (bed.scale - 1), 1),
            turned_deg=fit["turned_deg"], slid_mm=fit["slid_mm"], room_past_scanned_toes_mm=room,
            let_out=let, overhang=over, relief_mm=footbed.params.relief_mm, arch_cap_mm=footbed.params.max_arch_fill_mm,
            heel_cap_mm=footbed.params.heel_cup_depth_mm,
            posting_deg=dict(rearfoot=footbed.params.posting_rearfoot_deg, forefoot=footbed.params.posting_forefoot_deg),
            sole_seen=footbed.report.get("sole"), scan=footbed.report.get("scan"), prep=footbed.report.get("prep"),
            insole_warnings=list(footbed.report.get("warnings", []))),
        bed_fit=insole_mod.bed_fit_shape(np.asarray(mesh.vertices)[:, :2], p.bed_mm),
        warnings=warnings,
        frame="mm; x forward from the back of the shoe, y toward the foot's left, z up; bottom at z = 0",
    )
    if bed is None:
        report["warnings"].append("no sole scan: the footbed is flat (no arch fill, no heel cup shaped to the foot).")
    if not report["bed_fit"]["fits"]:
        report["warnings"].append(f"too long for a {p.bed_mm:.0f} mm bed even turned (by {report['bed_fit']['short_by_mm']} mm): "
                                  "it needs a bigger printer.")
    return Shoe(mesh=mesh, foot=foot, params=p, report=report)


# ---------------------------------------------------------------------------
# pictures
# ---------------------------------------------------------------------------
PICTURE_MM_PER_PX = 0.5
PICTURE_COLOUR = (0.80, 0.84, 0.86)
VIEWS = {   # name: (turn about the upright axis, tilt of the camera above level), degrees, for a right shoe
    "side": (0.0, 0.0),        # from the outer side, level: toes to the right
    "quarter": (-38.0, 28.0),  # from the front and outer side, looking down a little
    "top": (0.0, 90.0),        # straight down: toes to the right
    "bottom": (-20.0, -55.0),  # up at the sole, from the outer side and a little in front
    "back": (-90.0, 12.0),     # from behind the heel, into the opening
    "front": (90.0, 12.0),     # from in front of the toes
}


def _surface_points(mesh):
    """Points spread evenly over the surface (about 16 per square millimetre), each with its face's outward
    direction, about the middle of the shoe."""
    import trimesh

    n = int(min(max(mesh.area * 16.0, 50_000), 6_000_000))
    pts, face = trimesh.sample.sample_surface(mesh, n, seed=0)
    return pts - mesh.bounds.mean(0), mesh.face_normals[face]


def picture(mesh, view: str, foot: str = "right", points=None) -> np.ndarray:
    """One shaded picture of the shoe (RGB, 0.5 mm per pixel), as ``VIEWS`` names them.

    Drawn without a 3-D library: points are spread densely over the surface, the camera's view of each is
    worked out, and each pixel keeps the nearest point that faces the camera. Its brightness is how squarely
    that point's surface faces a lamp up and to the left (Lambert's cosine law), plus some light from
    everywhere. A pixel no point of the near surface happened to land in (so it is empty, or shows something
    several millimetres behind), with nearer drawn pixels nearly all round it, takes their average, which
    closes the pinholes. A left shoe is drawn from its own outer side, so the pair's pictures mirror each other.
    """
    P, N = _surface_points(mesh) if points is None else points
    turn, tilt = np.radians(VIEWS[view])
    if foot == "left":
        turn = np.pi - turn if view != "top" else turn
    # camera axes in the shoe's own frame: `right` and `upward` span the picture, `toward` points at the camera
    toward = np.array([np.sin(turn) * np.cos(tilt), -np.cos(turn) * np.cos(tilt), np.sin(tilt)])
    right = np.array([np.cos(turn), np.sin(turn), 0.0])
    upward = np.cross(toward, right)
    keep = N @ toward > 0.02
    u, v, depth = P[keep] @ right, P[keep] @ upward, P[keep] @ toward
    Nk = N[keep]
    pad = 24
    lo_u, lo_v = (P @ right).min(), (P @ upward).min()
    w = int(np.ceil(((P @ right).max() - lo_u) / PICTURE_MM_PER_PX)) + 2 * pad
    h = int(np.ceil(((P @ upward).max() - lo_v) / PICTURE_MM_PER_PX)) + 2 * pad
    col = np.clip(((u - lo_u) / PICTURE_MM_PER_PX).astype(int) + pad, 0, w - 1)
    row = np.clip(h - 1 - (((v - lo_v) / PICTURE_MM_PER_PX).astype(int) + pad), 0, h - 1)
    order = np.argsort(depth)                      # nearest last, so it is the one a pixel ends up with
    nearest = np.full(h * w, -1)
    nearest[(row * w + col)[order]] = order
    nearest = nearest.reshape(h, w)
    lamp = -0.45 * right + 0.55 * upward + 0.70 * toward
    lamp /= np.linalg.norm(lamp)
    lit = np.clip(Nk @ lamp, 0.0, 1.0)
    d = (depth - depth.min()) / max(np.ptp(depth), 1e-6)       # a little darker further away, to tell front from back
    shade = (0.30 + 0.70 * lit) * (0.72 + 0.28 * d)
    hit = nearest >= 0
    grey = np.where(hit, shade[np.clip(nearest, 0, None)], 0.0)
    deep = np.where(hit, depth[np.clip(nearest, 0, None)], -np.inf)
    for _ in range(2):                             # pinholes
        pg, pd = np.pad(grey, 1), np.pad(deep, 1, constant_values=-np.inf)
        nearer = [(pd[1 + a:h + 1 + a, 1 + b:w + 1 + b] > deep + 2.0, pg[1 + a:h + 1 + a, 1 + b:w + 1 + b],
                   pd[1 + a:h + 1 + a, 1 + b:w + 1 + b]) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
        around = sum(n.astype(int) for n, _, _ in nearer)
        fill = around >= 6
        grey = np.where(fill, sum(np.where(n, g, 0.0) for n, g, _ in nearer) / np.maximum(around, 1), grey)
        deep = np.where(fill, sum(np.where(n, d, 0.0) for n, _, d in nearer) / np.maximum(around, 1), deep)
        hit = hit | fill
    img = np.ones((h, w, 3))
    img[hit] = grey[hit][:, None] * np.array(PICTURE_COLOUR)
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def pictures(shoe: Shoe) -> dict:
    """Every view in ``VIEWS``, and one sheet with all of them."""
    points = _surface_points(shoe.mesh)
    out = {v: picture(shoe.mesh, v, shoe.foot, points) for v in VIEWS}
    w = max(im.shape[1] for im in out.values())
    rows = []
    for a, b in (("side", "quarter"), ("top", "bottom"), ("back", "front")):
        hh = max(out[a].shape[0], out[b].shape[0])
        row = np.full((hh, 2 * w, 3), 255, np.uint8)
        for k, name in enumerate((a, b)):
            im = out[name]
            r0, c0 = (hh - im.shape[0]) // 2, k * w + (w - im.shape[1]) // 2
            row[r0:r0 + im.shape[0], c0:c0 + im.shape[1]] = im
        rows.append(row)
    out["views"] = np.vstack(rows)
    return out


# ---------------------------------------------------------------------------
# a pair from one foot, and a shoe straight from a scan
# ---------------------------------------------------------------------------
def mirrored(shoe: Shoe) -> Shoe:
    """The same shoe for the other foot: its mirror image. NOT made from the other foot's scan, and its sheet
    says so: two feet are not mirror images of each other (their arches differ), so this is for trying a pair
    on before the other foot has a scan of its own."""
    import trimesh

    other = "left" if shoe.foot == "right" else "right"
    V = np.array(shoe.mesh.vertices, dtype=float)
    V[:, 1] *= -1.0
    mesh = trimesh.Trimesh(V, np.asarray(shoe.mesh.faces)[:, ::-1], process=False)   # turned inside out, so turn each face back
    report = json.loads(json.dumps(shoe.report))
    report["foot"] = other
    report["mirrored_from"] = shoe.foot
    if report.get("footbed"):
        first = (f"this {other} shoe is the {shoe.foot} shoe's mirror image: its footbed is the {shoe.foot} foot's, not "
                 f"made from a scan of the {other} foot. Two feet differ; make it again from the {other} foot's own sole "
                 "scan before relying on it.")
    else:   # a flat floor from ruler numbers: what came from the other foot is only its size
        first = (f"this {other} shoe is the {shoe.foot} shoe's mirror image, sized from the {shoe.foot} foot's measurements, "
                 f"not the {other} foot's. Two feet differ in length and width; measure the {other} foot and make it "
                 "again before relying on it.")
    report["warnings"] = [first] + report["warnings"]
    report["bed_fit"] = insole_mod.bed_fit_shape(V[:, :2], shoe.params.bed_mm)
    return Shoe(mesh=mesh, foot=other, params=shoe.params, report=report)


def from_scan(mesh, foot: str, params: ShoeParams | None = None, kind: str = "mat", up: str = "y", insole_params=None) -> Shoe:
    """A sole scan -> the foot's first-fit insole surface -> the shoe with that as its footbed.

    ``kind`` "mat": a scan already in the mat frame (mm, z up, the floor at z = 0), as ``footscan insole``
    takes. Any other kind is an iPhone Object Capture model as the studio imports them (``foot_prep.PREPARE``:
    sole_up, sole_hanging, impression, foot), with ``up`` its up axis. The insole is made exactly as the studio
    makes it, warnings and all; the shoe's report carries them.
    """
    if kind == "mat":
        ins = insole_mod.from_scan(mesh, foot, insole_params)
    else:
        from .recon import foot_prep

        ins, _ = foot_prep.insole_from_object_capture(mesh, foot, up=up, params=insole_params, kind=kind)
    return build(foot, params, footbed=ins)


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------
# Until a shoe from this generator has been printed and worn, every sheet and every set of print notes says so.
# Change this (and docs/footwear.md) when the print trials have results; don't delete it before then.
UNTESTED = ("No shoe from this design has been printed or worn yet. Its thicknesses, heights and allowances are "
            "starting judgments, and its grip, wear and strength are unknown.")

# The break-in, the insole's summary sheet's own paragraph (docs/SAFETY.md, requirement 2): one text for both.
BREAK_IN_HTML = insole_mod.BREAK_IN_HTML


def print_notes(shoe: Shoe) -> str:
    r = shoe.report
    return f"""Footscan clog ({shoe.foot} foot): print notes
NOT A MEDICAL DEVICE. For walking and casual wear only, not for sport. Break-in as on the summary sheet.

{UNTESTED}
Starting points only: none of these settings has been tried on this design.
- Check the size first: the slicer should show {r['length_mm']} x {r['width_mm']} x {r['height_mm']} mm. Keep the scale at 100%.
- Material: TPU 95A, dried first. One piece; the colour is the spool that is loaded.
- Sole down on the bed, as the file is placed ({r['bed_fit']['how'] if r['bed_fit']['fits'] else 'it does NOT fit this bed'}).
- Supports: the roof over the toes and the instep hangs over empty space. Expect to need supports inside
  (tree supports standing on the footbed), pulled out through the opening afterwards. Whether a smaller
  piece of the roof prints cleanly is the first thing to try, before a whole shoe.
- Walls: 3. The upper is {r['upper_mm']} mm thick, so it should come out solid, with no infill inside it.
- Infill: gyroid, {r['sole']['infill_percent']}% for {r['sole']['cushion']} cushioning (this is the sole and the footbed). A guess
  until small blocks at 15, 20 and 25% have been squeezed by hand.
- Top layers: enough that the footbed is closed and smooth (try 4). Print slowly, as TPU needs.
After printing: check the inside for strings and support stubs before a foot goes in, then start the break-in:
indoors first, on a dry, level floor.
"""


def _footbed_rows(fb: dict | None) -> str:
    if fb is None:
        return '<tr><th>Footbed</th><td colspan="3">flat: no sole scan was given, so there is no arch fill and no shaped heel cup</td></tr>'
    o, let = fb["overhang"], fb["let_out"] or {}
    stretch = ("as scanned" if not fb["scaled_percent"] else
               f"scaled {fb['scaled_percent']:+.1f}% along and across to the ruler's length (heights unchanged)")
    let_out = "; ".join(f"{side} side by up to {v['max_mm']} mm ({v['at']:.0%} of the way along)"
                        for side, v in let.items() if v["max_mm"] >= 1.0) or "nowhere: the standard shape holds this foot"
    over = (f"the scanned foot is wider than the inside at the {o['where']} by up to {o['max_mm']} mm" if o["max_mm"] > 1.0
            else "the scanned foot is inside the shoe all round")
    seen = fb.get("sole_seen") or {}
    seen_row = (f"<tr><th>Sole seen by the scan</th><td>{seen['seen']:.0%} of the footprint</td><th>Under the arch</th>"
                f"<td>{seen['seen_under_arch']:.0%}</td></tr>") if seen else ""
    return f"""<tr><th>Rearfoot posting</th><td>{fb['posting_deg']['rearfoot']}&deg; (none)</td><th>Forefoot posting</th><td>{fb['posting_deg']['forefoot']}&deg; (none)</td></tr>
<tr><th>Arch fill</th><td>scanned sole &minus; {fb['relief_mm']} mm, capped at {fb['arch_cap_mm']} mm ({fb['heel_cap_mm']} mm round the heel)</td><th>Highest fill</th><td>{fb['max_fill_mm']} mm</td></tr>
<tr><th>Foot as scanned</th><td>{fb['scan_length_mm']} &times; {fb['scan_width_mm']} mm</td><th>Used</th><td>{stretch}</td></tr>
<tr><th>Stood in the shoe</th><td colspan="3">heel against the back, turned {fb['turned_deg']}&deg; and slid {fb['slid_mm']} mm sideways for its sole to stand on the floor;
{fb['room_past_scanned_toes_mm']} mm past the scanned toes; {over}</td></tr>
<tr><th>Let out for this foot</th><td colspan="3">{let_out}</td></tr>
{seen_row}"""


def summary_html(shoe: Shoe, label: str, synthetic: bool = False) -> str:
    """The summary sheet for a shoe (docs/SAFETY.md, requirement 1): what it was made to and what is a judgment,
    the footbed's first-fit parameters, the sign-off block and the break-in."""
    from html import escape

    r = shoe.report
    mf, ins, sole, pat, fb = r["made_for"], r["inside"], r["sole"], r["pattern"], r["footbed"]
    st = STYLES[r["style"]]
    warn = "".join(f"<li>{escape(w)}</li>" for w in r["warnings"] + ((fb or {}).get("insole_warnings") or [])) or "<li>None.</li>"
    synth = ('<p class="synthetic">SYNTHETIC TEST GEOMETRY. This sheet was made from a computer-generated '
             'shape, not a person\'s foot. It is an example of the sheet, not a shoe to wear.</p>') if synthetic else ""
    capture = insole_mod.capture_html((fb or {}).get("prep"))
    pattern = (f"{pat['count']} windows of {pat['window_mm'][0]} &times; {pat['window_mm'][1]} mm in {pat['rows']} rows a side "
               f"({pat['openness']:.0%} of the patterned area open)") if pat["count"] else "none (a closed upper)"
    footbed_is = (f"<b>The footbed is a first fit</b>, built into the floor: it follows the scanned underside of the foot, set "
                  f"{fb['relief_mm']} mm below it. <b>No posting, no correction, one stiffness.</b>" if fb else
                  "<b>The footbed is flat</b>: no sole scan was given. No posting, no correction, one stiffness.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Footscan clog summary: {escape(label)}</title>
<style>
 body{{font:14px/1.45 -apple-system,Segoe UI,sans-serif;max-width:760px;margin:24px auto;color:#15201f}}
 h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:22px 0 6px;border-bottom:1px solid #ccc}}
 .safety{{background:#15201f;color:#fff;padding:10px 12px;border-radius:6px}} .safety b{{color:#d6ee3c}}
 .synthetic{{border:2px solid #b0271f;color:#b0271f;padding:8px;font-weight:700}}
 table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}
 .sign td{{height:34px}} .box{{display:inline-block;width:12px;height:12px;border:1px solid #333;margin:0 6px 0 14px}}
 @media print{{body{{margin:0}}}}
</style></head><body>
<div class="safety"><b>NOT A MEDICAL DEVICE.</b> A homemade shoe from a phone scan and a ruler. It does not diagnose or treat
anything, and its footbed is not equivalent to, or a substitute for, a prescribed orthotic.
<b>For walking and casual wear only: not for tennis, running or any other sport.</b></div>
{synth}
<h1>Clog: {escape(shoe.foot)} foot{f" (the {escape(r['mirrored_from'])} shoe's mirror image)" if r.get('mirrored_from') else ""}</h1>
<p>Made from: {escape(label)}</p>

<h2>What this shoe is</h2>
<p>A one-piece slip-on clog printed in flexible plastic (TPU). {footbed_is}
<b>The upper is a standard shape in this foot's size</b>: no scan of the top of the foot was taken, so how it sits over
the instep and the toes is not measured from this foot.</p>
<p><b>Untested.</b> {escape(UNTESTED)}</p>

<h2>Made for</h2>
<table>
<tr><th>Foot length</th><td>{mf['foot_length_mm']} mm (from the {mf['length_from']})</td><th>Foot width</th><td>{mf['foot_width_mm']} mm (from the {mf['width_from']})</td></tr>
<tr><th>Fit</th><td>{escape(mf['fit'])}{f", {mf['sock_mm']} mm more for a thicker sock" if mf['sock_mm'] else ""}</td><th>Room past the toes</th><td>{ins['room_past_toes_mm']} mm</td></tr>
<tr><th>Inside length</th><td>{ins['length_mm']} mm</td><th>Inside width at the ball</th><td>{ins['width_mm']} mm ({ins['width_ease_mm']:+.1f} mm on the foot)</td></tr>
<tr><th>Roof over the ball</th><td>{ins['roof_over_ball_mm']} mm (standard shape)</td><th>Roof where the opening ends</th><td>{ins['roof_over_instep_mm']} mm (standard shape)</td></tr>
</table>

<h2>The shoe</h2>
<table>
<tr><th>Style</th><td colspan="3">{escape(st['label'])}: {escape(st['about'])}</td></tr>
<tr><th>Size</th><td>{r['length_mm']} &times; {r['width_mm']} mm, {r['height_mm']} mm tall</td><th>Volume</th><td>{r['volume_cm3']} cm&sup3; if printed solid (less with infill)</td></tr>
<tr><th>Sole</th><td>{sole['under_ball_mm']} mm under the ball, {sole['under_heel_mm']} mm under the heel</td><th>Heel above the ball</th><td>{round(sole['under_heel_mm'] - sole['under_ball_mm'], 1)} mm, front to back only (no sideways tilt)</td></tr>
<tr><th>Upper</th><td>{r['upper_mm']} mm thick; rim behind the heel {r['heel_rim_mm']} mm above the floor, at least {r['rim_over_footbed_mm']} mm above the footbed</td><th>Cushioning</th><td>{escape(sole['cushion'])}: {sole['infill_percent']}% infill suggested (untested)</td></tr>
<tr><th>Pattern</th><td colspan="3">{pattern}</td></tr>
<tr><th>Printer bed</th><td colspan="3">{escape(r['bed_fit']['how']) if r['bed_fit']['fits'] else 'does not fit a ' + format(r['bed_fit']['bed_mm'], '.0f') + ' mm bed'}</td></tr>
</table>

<h2>Footbed</h2>
<table>
{_footbed_rows(fb)}
</table>
{capture}
<p><b>Repeatability:</b> not yet measured (Phase 0 study pending). Treat every number from the scan as unverified.</p>
<h2>Warnings</h2><ul>{warn}</ul>

<h2>As printed (fill in)</h2>
<table class="sign"><tr><th>Material</th><td></td><th>Infill</th><td></td></tr><tr><th>Date printed</th><td></td><th>Printer</th><td></td></tr></table>

<h2>Clinician review</h2>
<p>Reviewed by a podiatrist, sports-medicine physician, physical therapist or certified athletic trainer.
Walking under the break-in below does not wait for a signature. <b>This shoe is not for sport, whoever signs.</b></p>
<table class="sign">
<tr><th>Name</th><td></td><th>Credential</th><td></td></tr>
<tr><th>Signature</th><td></td><th>Date</th><td></td></tr>
</table>
<p>Approved for:<span class="box"></span>walking and casual wear<span class="box"></span>not approved</p>
<p>Notes:</p><div style="border:1px solid #ccc;height:90px"></div>

<h2>Break-in (walking only)</h2>
{BREAK_IN_HTML}
<p>First wear indoors, on a dry, level floor: this sole's grip has not been tested.</p>
</body></html>"""


def write_outputs(shoe: Shoe, out_dir: Path, name: str, label: str, synthetic: bool = False) -> dict:
    """<name>.3mf, <name>.stl, <name>-summary.html, <name>-print-notes.txt, <name>.json and the pictures
    (<name>-views.png with every view, and one file per view) in out_dir."""
    from .review import write_png

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = "SYNTHETIC TEST GEOMETRY, not a foot. " if synthetic else ""
    notes = (f"{tag}Footscan clog ({shoe.foot} foot). NOT A MEDICAL DEVICE. Walking and casual wear only, not sport. "
             "Break-in as on the summary sheet.")
    files = dict(threemf=out / f"{name}.3mf", stl=out / f"{name}.stl", summary=out / f"{name}-summary.html",
                 notes=out / f"{name}-print-notes.txt", json=out / f"{name}.json")
    insole_mod.write_3mf(shoe.mesh, files["threemf"], title=f"{tag}{name}", notes=notes, bed_mm=shoe.params.bed_mm)
    shoe.mesh.export(files["stl"])
    files["summary"].write_text(summary_html(shoe, label, synthetic), encoding="utf-8")
    files["notes"].write_text(print_notes(shoe), encoding="utf-8")
    files["json"].write_text(json.dumps(dict(synthetic=synthetic, made_from=label, params=asdict(shoe.params), **shoe.report),
                                        indent=2), encoding="utf-8")
    for view, img in pictures(shoe).items():
        files[f"picture_{view}"] = out / f"{name}-{view}.png"
        write_png(files[f"picture_{view}"], img)
    return {k: str(v) for k, v in files.items()}
