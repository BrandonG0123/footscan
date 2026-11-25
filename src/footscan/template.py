"""A paper template of the insole, printed at full size: a check of its outline before a long TPU print.

Not a medical device. A paper template checks size and shape only; it says nothing about support or comfort.

What it is for. A TPU insole takes hours to print, and the outline (a shoe's, or the generic insole outline at the
shoe's length) is only right if it goes into the shoe. On paper, at full size, the outline can be checked first:

- lay the shoe's stock insole on it (or it on the stock insole): the two outlines should match, give or take the
  stock insole's own heel cup and the edge it curls up into the shoe's sides;
- put it into the shoe: it should lie flat, heel against the back, without buckling at the sides or the toe;
- stand on it (in the sock the insole will be worn with): the scanned foot's outline near the floor is drawn
  dashed, so where the real foot's toes and sides land against it shows how far a scan reads short or narrow.

What's drawn, all at full size (millimetres on the paper are millimetres of the insole):

- the insole's outline (solid; cut along it), as seen from above, toes toward the top of the page;
- the scanned foot near the floor (dashed): the outline the insole was placed round (``recon/shoe.py``,
  ``FIT_HEIGHT_MM``);
- where the top rises above the base (thin lines every ``CONTOUR_STEP_MM``): the arch fill and the heel cup's
  wall, read from the generator's own heights, so the arch support can be seen where the foot stands;
- trim lines ``TRIM_LINES_MM`` in from the toe end (dotted): a full-length insole is often trimmed to a shoe;
  the lines show what a little trimming leaves, before cutting anything;
- a 50 mm square and a 100 mm scale with millimetre ticks: measure them. If they aren't exactly that, the
  printer scaled the page, and the template is no check of anything: print again at "Actual size" (100%).

An insole longer than one page goes onto several, overlapping by ``OVERLAP_MM``: the same line, marked with the
same letter, crosses the overlap on both pages; lay one page over the other so the line and the outline meet,
and tape.

The PDF is written by hand (a few dozen lines of PDF operators, Helvetica only), so nothing beyond numpy and
shapely is needed on the studio's computer. Paper sizes are US Letter and A4.
"""

from __future__ import annotations

import zlib

import numpy as np

PT_PER_MM = 72.0 / 25.4
PAPER_MM = {"letter": (215.9, 279.4), "a4": (210.0, 297.0)}
MARGIN_MM = 12.7          # half an inch all round: inside what home printers leave unprinted
HEADER_MM = 30.0          # top of each page: what the template is, how to check its scale, the legend
FOOTER_MM = 8.0           # bottom: page number, scan
OVERLAP_MM = 20.0         # pages overlap this much along the length, so they can be lined up
CONTOUR_STEP_MM = 3.0     # a line where the top is 3, 6, 9 ... mm above the base
TRIM_LINES_MM = (5.0, 10.0)
SCALE_SQUARE_MM = 50.0


# ---------------------------------------------------------------------------
# the drawing, in the insole's own millimetres
# ---------------------------------------------------------------------------
def contour_segments(xs: np.ndarray, ys: np.ndarray, Z: np.ndarray, level: float) -> np.ndarray:
    """Where the grid ``Z`` (rows along ``ys``, columns along ``xs``) crosses ``level``, as line segments
    (n x 2 x 2, mm): marching squares, the crossing on each cell edge found by straight-line interpolation
    between its two corners. NaN counts as below the level (outside the insole: no rise there)."""
    Z = np.nan_to_num(np.asarray(Z, float), nan=-np.inf)
    a, b = Z[:-1, :-1], Z[:-1, 1:]   # corners of each cell: a (x0, y0), b (x1, y0), c (x1, y1), d (x0, y1)
    c, d = Z[1:, 1:], Z[1:, :-1]
    case = (a > level) * 1 + (b > level) * 2 + (c > level) * 4 + (d > level) * 8
    X0, Y0 = np.meshgrid(xs[:-1], ys[:-1])
    dx, dy = xs[1] - xs[0], ys[1] - ys[0]

    def t(p, q):  # where along an edge from p to q the level is crossed
        with np.errstate(invalid="ignore", divide="ignore"):
            r = (level - p) / (q - p)
        return np.clip(np.nan_to_num(r, nan=0.5, posinf=0.5, neginf=0.5), 0.0, 1.0)

    # the crossing point on each edge: bottom (a-b), right (b-c), top (d-c), left (a-d)
    edge = {
        "B": (X0 + t(a, b) * dx, Y0),
        "R": (X0 + dx, Y0 + t(b, c) * dy),
        "T": (X0 + t(d, c) * dx, Y0 + dy),
        "L": (X0, Y0 + t(a, d) * dy),
    }
    # which edges each case joins (the two saddle cases, 5 and 10, are joined one way, as either is right)
    table = {1: ["BL"], 2: ["BR"], 3: ["LR"], 4: ["RT"], 5: ["BR", "LT"], 6: ["BT"], 7: ["LT"], 8: ["LT"],
             9: ["BT"], 10: ["BL", "RT"], 11: ["RT"], 12: ["LR"], 13: ["BR"], 14: ["BL"]}
    out = []
    for k, pairs in table.items():
        sel = case == k
        if not sel.any():
            continue
        for e1, e2 in pairs:
            p1 = np.c_[edge[e1][0][sel], edge[e1][1][sel]]
            p2 = np.c_[edge[e2][0][sel], edge[e2][1][sel]]
            out.append(np.stack([p1, p2], axis=1))
    return np.concatenate(out) if out else np.zeros((0, 2, 2))


def trim_lines(outline, distances=TRIM_LINES_MM) -> list[tuple[float, np.ndarray]]:
    """Lines ``distances`` mm in from the toe end (the front fifth of the outline, followed round its curve): what a
    little trimming at the toe would leave. -> [(mm, points), ...]."""
    import shapely

    x0, y0, x1, y1 = outline.bounds
    out = []
    for mm in distances:
        inner = outline.buffer(-mm)
        if inner.is_empty:
            continue
        if inner.geom_type != "Polygon":
            inner = max(inner.geoms, key=lambda g: g.area)
        front = shapely.box(x0 + 0.8 * (x1 - x0), y0 - 1, x1 + 1, y1 + 1)
        line = inner.exterior.intersection(front)
        parts = getattr(line, "geoms", [line])
        for part in parts:
            if part.geom_type == "LineString" and part.length > 5.0:
                out.append((mm, np.asarray(part.coords)))
    return out


def rise_above_base(insole) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """(xs, ys, rise) on the generator's own grid: how far the printed top stands above the base at each point
    inside the outline (NaN outside), as built (the arch fill and the heel cup's wall, with the edge rounded)."""
    s = insole.surface or {}
    if "rise" not in s:
        return None
    return s["xs"], s["ys"], s["rise"]


# ---------------------------------------------------------------------------
# a tiny PDF writer: lines, dashes, text, clipping
# ---------------------------------------------------------------------------
def _pdf_text(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


class _Page:
    def __init__(self):
        self.ops: list[str] = []

    def add(self, op: str):
        self.ops.append(op)

    def text(self, x_mm: float, y_mm: float, s: str, size: float = 9.0, bold: bool = False):
        font = "F2" if bold else "F1"
        self.add(f"BT /{font} {size:g} Tf {x_mm * PT_PER_MM:.2f} {y_mm * PT_PER_MM:.2f} Td {_pdf_text(s)} Tj ET")

    def polyline(self, pts, width_mm: float, dash_mm=None, close=False, mm=True):
        """Points in the current coordinates (mm under the page's transform, or page mm)."""
        k = 1.0 if mm else PT_PER_MM
        P = np.asarray(pts, float) * k
        if len(P) < 2:
            return
        d = f"[{' '.join(f'{v * k:.3f}' for v in dash_mm)}] 0 d" if dash_mm else "[] 0 d"
        path = f"{P[0, 0]:.3f} {P[0, 1]:.3f} m " + " ".join(f"{x:.3f} {y:.3f} l" for x, y in P[1:])
        self.add(f"{width_mm * k:.3f} w {d} {path} {'h ' if close else ''}S")

    def segments(self, segs, width_mm: float):
        if not len(segs):
            return
        body = " ".join(f"{s[0, 0]:.2f} {s[0, 1]:.2f} m {s[1, 0]:.2f} {s[1, 1]:.2f} l" for s in segs)
        self.add(f"{width_mm:.3f} w [] 0 d {body} S")


def _pdf(pages: list[_Page], paper_mm: tuple[float, float], title: str) -> bytes:
    w, h = (v * PT_PER_MM for v in paper_mm)
    objs: list[bytes] = []

    def obj(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font1 = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2 = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1 + 2 * len(pages)  # after every page and its content
    kids = []
    for pg in pages:
        data = zlib.compress("\n".join(pg.ops).encode("latin-1"))
        content = obj(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(obj((f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {w:.2f} {h:.2f}] "
                         f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
                         f"/Contents {content} 0 R >>").encode()))
    assert obj(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()) == pages_id
    # print at actual size: the viewer's print dialog starts with no scaling
    catalog = obj(f"<< /Type /Catalog /Pages {pages_id} 0 R /ViewerPreferences << /PrintScaling /None >> >>".encode())
    info = obj(f"<< /Title {_pdf_text(title)} /Producer (footscan) >>".encode("latin-1"))

    out = bytearray(b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# ---------------------------------------------------------------------------
# the template
# ---------------------------------------------------------------------------
def page_windows(x0: float, x1: float, usable_mm: float, overlap_mm: float = OVERLAP_MM) -> list[tuple[float, float]]:
    """Stretches of the insole's length (mm, from x0 to x1) that go on each page, ``usable_mm`` long each,
    overlapping by ``overlap_mm``; the last one ends at x1. One page if it fits."""
    length = x1 - x0
    if length <= usable_mm:
        mid = (x0 + x1) / 2
        return [(mid - usable_mm / 2, mid + usable_mm / 2)]
    n = int(np.ceil((length - overlap_mm) / (usable_mm - overlap_mm)))
    step = (length - usable_mm) / (n - 1)  # spread the pages evenly: every overlap is at least overlap_mm
    return [(x0 + i * step, x0 + i * step + usable_mm) for i in range(n)]


def template_pdf(insole, scan_label: str, paper: str = "letter", synthetic: bool = False) -> bytes:
    """The paper template (see the module docstring) of ``insole`` (insole.build's), as PDF bytes."""
    return make(insole, scan_label, paper, synthetic)[0]


def make(insole, scan_label: str, paper: str = "letter", synthetic: bool = False) -> tuple[bytes, dict]:
    """The paper template as PDF bytes, and what it holds: ``pages`` (how many) and ``square_page`` (which one,
    from 1, carries the 50 mm scale square)."""
    from .recon import shoe as shoe_mod

    if paper not in PAPER_MM:
        raise ValueError(f"paper must be one of {', '.join(PAPER_MM)}")
    pw, ph = PAPER_MM[paper]
    s = insole.surface or {}
    outline = s.get("outline")
    if outline is None:
        raise ValueError("this insole has no outline recorded (made by an older footscan): make it again")
    standing = s.get("standing")
    if standing is None and insole.sole is not None:  # the foot's own outline: the foot near the floor all the same
        from .insole import silhouette

        standing = silhouette(insole.sole, height=shoe_mod.FIT_HEIGHT_MM)
    r = insole.report
    x0, y0, x1, y1 = outline.bounds
    ymid = (y0 + y1) / 2
    usable_w = pw - 2 * MARGIN_MM
    usable_h = ph - 2 * MARGIN_MM - HEADER_MM - FOOTER_MM
    if y1 - y0 > usable_w - 4:
        raise ValueError(f"the insole is {y1 - y0:.0f} mm wide: wider than the {paper} page")
    windows = page_windows(x0 - 2.0, x1 + 2.0, usable_h)
    rise = rise_above_base(insole)
    levels = []
    if rise is not None:
        top = np.nanmax(rise[2]) if np.isfinite(rise[2]).any() else 0.0
        levels = list(np.arange(CONTOUR_STEP_MM, top, CONTOUR_STEP_MM))
        segs = {lv: contour_segments(rise[0], rise[1], rise[2], lv) for lv in levels}
    trims = trim_lines(outline)
    ring = np.asarray(outline.exterior.coords)
    foot_ring = np.asarray(standing.exterior.coords) if standing is not None else None
    peak = r.get("max_fill_at_mm")
    arch = r.get("arch_fill")  # the arch support as printed (the highest fill is the heel's back on a flat foot)
    if arch and peak and abs(arch["x"] - peak["x"]) < 1.0 and abs(arch["y"] - peak["y"]) < 1.0:
        arch = None  # the same point: one ring, one label
    letters = "ABCDEFGH"
    joins = [((windows[i][1] + windows[i + 1][0]) / 2, letters[i]) for i in range(len(windows) - 1)]

    bottom, cx = MARGIN_MM + FOOTER_MM, pw / 2
    square_page, square_at = _square_place(ring, windows, cx, ymid, bottom, pw, usable_h)
    pages = []
    for i, (wx0, wx1) in enumerate(windows):
        pg = _Page()
        # the insole's frame -> the page's (pt): toes up the page, the foot's left to the page's left
        # (looking down on it): page x = cx - (y - ymid), page y = bottom + (x - wx0)
        k = PT_PER_MM
        pg.add("q")
        pg.add(f"0 {k:.6f} {-k:.6f} 0 {k * (cx + ymid):.4f} {k * (bottom - wx0):.4f} cm")
        pg.add(f"{wx0:.3f} {ymid - usable_w / 2:.3f} {wx1 - wx0:.3f} {usable_w:.3f} re W n")
        pg.add("0 0 0 RG")
        pg.polyline(ring, 0.45, close=True)
        if foot_ring is not None:
            pg.add("0.25 0.25 0.25 RG")
            pg.polyline(foot_ring, 0.3, dash_mm=(2.0, 1.5), close=True)
        if levels:
            pg.add("0.05 0.45 0.42 RG")
            for lv in levels:
                pg.segments(segs[lv], 0.15 if lv % (2 * CONTOUR_STEP_MM) else 0.25)
        pg.add("0.45 0.45 0.45 RG")
        for _, pts in trims:
            pg.polyline(pts, 0.2, dash_mm=(0.6, 1.2))
        pg.add("0 0 0 RG")
        th = np.linspace(0, 2 * np.pi, 25)
        for at in (peak, arch):  # the highest printed fill, and the arch support's: a small ring each
            if at:
                pg.polyline(np.c_[at["x"] + 2.0 * np.cos(th), at["y"] + 2.0 * np.sin(th)], 0.25)
        for jx, letter in joins:  # the join line, on both pages it crosses
            if wx0 < jx < wx1:
                pg.polyline([(jx, ymid - usable_w / 2 + 2), (jx, ymid + usable_w / 2 - 2)], 0.2, dash_mm=(4.0, 2.0))
                for yy in (ymid - usable_w / 2 + 6, ymid + usable_w / 2 - 6):  # a cross at each end
                    pg.polyline([(jx - 3, yy), (jx + 3, yy)], 0.25)
                    pg.polyline([(jx, yy - 3), (jx, yy + 3)], 0.25)
        pg.add("Q")
        # labels on the drawing, in page mm (text isn't turned)
        for jx, letter in joins:
            if wx0 < jx < wx1:
                py = bottom + (jx - wx0)
                if jx > (wx0 + wx1) / 2:  # near this page's top: the next page is laid on it
                    pg.text(MARGIN_MM + 1, py + 1, f"{letter}: lay page {i + 2}'s cut edge along this line", 7)
                else:                      # near its bottom: this page is cut here and laid on the one before
                    pg.text(MARGIN_MM + 1, py + 1, f"{letter}: cut along this line, lay it on line {letter} of page "
                            f"{i}, tape", 7)
        for mm, pts in trims:
            far = pts[np.argmax(pts[:, 0])]
            if wx0 <= far[0] <= wx1:
                pg.text(cx - (far[1] - ymid) + 1.5, bottom + (far[0] - wx0) - 1.0, f"trim {mm:g}", 6)
        if peak and wx0 <= peak["x"] <= wx1:
            pg.text(cx - (peak["y"] - ymid) + 3, bottom + (peak["x"] - wx0) - 1, f"highest fill {r['max_fill_mm']} mm", 6)
        if arch and wx0 <= arch["x"] <= wx1:
            pg.text(cx - (arch["y"] - ymid) + 3, bottom + (arch["x"] - wx0) - 1, f"arch support {arch['max_mm']} mm", 6)
        for x_at, word in ((x0, "HEEL"), (x1, "TOE")):
            if wx0 <= x_at <= wx1:
                pg.text(cx + (y1 - ymid) + 4, bottom + (x_at - wx0) - 1.2, word, 7, bold=True)

        # header: what it is, the scale check, the legend
        top = ph - MARGIN_MM
        pg.text(MARGIN_MM, top - 5, f"Footscan paper template: {insole.foot} insole, {r['length_mm']} x "
                f"{r['width_mm']} mm. Page {i + 1} of {len(windows)}", 11, bold=True)
        pg.text(MARGIN_MM, top - 10, "NOT A MEDICAL DEVICE. A full-size paper check of the outline before printing; "
                "it says nothing about support or comfort.", 7)
        pg.text(MARGIN_MM, top - 14, "Print at Actual size (100%, no fit to page). The square on page "
                f"{square_page + 1} must measure 50 mm each way, and the ruler 100 mm; if not, the page was scaled.", 7)
        pg.text(MARGIN_MM, top - 18, "Solid: the insole (cut along it). Dashed: the scanned foot near the floor. "
                f"Thin lines: the top {CONTOUR_STEP_MM:g}, {2 * CONTOUR_STEP_MM:g}, "
                f"{3 * CONTOUR_STEP_MM:g} ... mm above the base (arch, heel cup).", 7)
        pg.text(MARGIN_MM, top - 22, "Dotted: 5 and 10 mm in from the toe. Lay the stock insole on it, put it in the "
                "shoe, or stand on it in your sock.", 7)
        if synthetic:
            pg.add("0.69 0.15 0.12 rg")
            pg.text(MARGIN_MM, top - 27, "SYNTHETIC TEST GEOMETRY: a computer-made shape, not a person's foot.", 8, bold=True)
            pg.add("0 0 0 rg")
        # the scale check: a 50 mm square on one page only (the first page with a corner the insole leaves clear;
        # one is enough, and the header names its page) and a 100 mm ruler along the foot of every page
        if i == square_page:
            sx, sy = square_at
            pg.polyline([(sx, sy), (sx + SCALE_SQUARE_MM, sy), (sx + SCALE_SQUARE_MM, sy + SCALE_SQUARE_MM),
                         (sx, sy + SCALE_SQUARE_MM)], 0.3, close=True, mm=False)
            pg.text(sx + 2, sy + SCALE_SQUARE_MM / 2, "50 mm x 50 mm", 7)
        rx, ry = MARGIN_MM, MARGIN_MM + 4
        pg.polyline([(rx, ry), (rx + 100, ry)], 0.25, mm=False)
        for t in range(0, 101):
            h = 3.0 if t % 10 == 0 else 2.0 if t % 5 == 0 else 1.2
            pg.polyline([(rx + t, ry), (rx + t, ry + h)], 0.12, mm=False)
        pg.text(rx + 102, ry, "100 mm", 7)
        pg.text(MARGIN_MM, MARGIN_MM, f"Scan: {scan_label}"[:110], 6)
        pages.append(pg)
    pdf = _pdf(pages, PAPER_MM[paper], f"Footscan paper template: {insole.foot} insole")
    return pdf, dict(pages=len(windows), square_page=square_page + 1)


def _square_place(ring, windows, cx, ymid, bottom, pw, usable_h):
    """Where the 50 mm square goes: (page index, (x, y) page mm of its lower left corner), the first corner of a
    page's drawing area that the insole leaves clear (it's beside the rounded heel or toe, usually), else the first
    page's top right corner, over the insole: measuring it is what matters."""
    import shapely

    sq, gap = SCALE_SQUARE_MM, 3.0
    corners = [(pw - MARGIN_MM - sq, bottom + usable_h - sq), (MARGIN_MM, bottom + usable_h - sq),
               (pw - MARGIN_MM - sq, bottom), (MARGIN_MM, bottom)]
    for i, (wx0, _) in enumerate(windows):
        shape = _page_shape(ring, cx, ymid, bottom, wx0).buffer(gap)
        for sx, sy in corners:
            if not shapely.box(sx, sy, sx + sq, sy + sq).intersects(shape):
                return i, (sx, sy)
    return 0, corners[0]


def _page_shape(ring, cx, ymid, bottom, wx0):
    """The insole's outline in page mm (as the page's transform draws it), for keeping the square clear of it."""
    import shapely

    return shapely.Polygon(np.c_[cx - (ring[:, 1] - ymid), bottom + (ring[:, 0] - wx0)])
