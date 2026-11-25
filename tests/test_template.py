"""The paper template (footscan/template.py): the insole at full size on paper, to check its outline before a long
TPU print. SYNTHETIC feet only (tests/synth.py)."""

import numpy as np
import pytest

import synth
from footscan import insole, template

pymupdf = pytest.importorskip("pymupdf")


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    out = tmp_path_factory.mktemp("tpl")
    ins = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    files = insole.write_outputs(ins, out, "right-insole", "synthetic curved foot", synthetic=True)
    return ins, files


def _outline_paths(page):
    """The insole's outline as drawn: the paths drawn 0.45 mm wide."""
    return [d for d in page.get_drawings() if d.get("width") and abs(d["width"] - 0.45 * template.PT_PER_MM) < 0.01]


def test_the_template_is_written_beside_the_insole_and_recorded(made):
    ins, files = made
    assert files["template"].endswith("right-insole-template.pdf")
    assert ins.report["template"] == dict(paper="letter", pages=2, square_page=1)  # 275 mm doesn't fit one letter page
    doc = pymupdf.open(files["template"])
    assert len(doc) == 2
    for page in doc:  # US Letter, in points
        assert page.rect.width == pytest.approx(612.0, abs=0.1) and page.rect.height == pytest.approx(792.0, abs=0.1)
        text = page.get_text()
        assert "NOT A MEDICAL DEVICE" in text and "Actual size" in text and "SYNTHETIC" in text
    assert "50 mm x 50 mm" in "".join(p.get_text() for p in doc)


def test_it_is_drawn_at_full_size(made):
    """The point of it: millimetres on the paper are the insole's millimetres. The outline's width across the page
    is the insole's own width; the 50 mm square and the 100 mm scale are what they say."""
    ins, files = made
    doc = pymupdf.open(files["template"])
    y0, y1 = ins.surface["outline"].bounds[1], ins.surface["outline"].bounds[3]
    widths = [p["rect"].width for page in doc for p in _outline_paths(page)]
    assert widths and max(widths) / template.PT_PER_MM == pytest.approx(y1 - y0, abs=0.2)
    squares = [d["rect"] for page in doc for d in page.get_drawings()
               if abs(d["rect"].width - 50 * template.PT_PER_MM) < 0.05 and abs(d["rect"].height - 50 * template.PT_PER_MM) < 0.05]
    assert len(squares) == 1
    rulers = [d["rect"] for page in doc for d in page.get_drawings()
              if abs(d["rect"].width - 100 * template.PT_PER_MM) < 0.05 and d["rect"].height < 0.5]
    assert len(rulers) == len(doc)


def test_the_pages_overlap_and_together_cover_the_whole_insole():
    w = template.page_windows(0.0, 280.0, 220.0)
    assert len(w) == 2 and w[0][0] == 0.0 and w[-1][1] == pytest.approx(280.0)
    assert all(a[1] - b[0] >= template.OVERLAP_MM for a, b in zip(w, w[1:]))
    w = template.page_windows(0.0, 600.0, 220.0)  # long enough for three
    assert len(w) == 3 and all(a[1] - b[0] >= template.OVERLAP_MM for a, b in zip(w, w[1:]))
    assert template.page_windows(0.0, 200.0, 220.0) == [(-10.0, 210.0)]  # one page, centred


def test_a_short_insole_fits_one_page_and_a4_works_too(tmp_path):
    foot = synth.curved_foot("right", leg=False)
    foot.apply_transform(np.diag([0.75, 0.75, 1.0, 1.0]))  # a child's size: about 190 mm
    ins = insole.from_scan(foot, "right")
    files = insole.write_outputs(ins, tmp_path, "small", "synthetic", synthetic=True, paper="a4")
    doc = pymupdf.open(files["template"])
    assert len(doc) == 1 and ins.report["template"]["pages"] == 1
    assert doc[0].rect.width == pytest.approx(210.0 * template.PT_PER_MM, abs=0.1)


def test_contours_follow_the_rise_of_the_top():
    """Marching squares on a cone: the 10 mm line is a circle of radius 10."""
    xs = ys = np.arange(-20.0, 20.01, 0.5)
    X, Y = np.meshgrid(xs, ys)
    Z = 30.0 - np.hypot(X, Y)          # 10 mm above where r = 20, 20 above where r = 10
    segs = template.contour_segments(xs, ys, Z, 20.0)
    r = np.hypot(segs[..., 0], segs[..., 1])
    assert len(segs) > 50 and np.allclose(r, 10.0, atol=0.05)
    # outside the insole (nan) counts as no rise: nothing drawn there
    Z[:, :40] = np.nan
    segs = template.contour_segments(xs, ys, Z, 20.0)
    assert np.all(segs[..., 0] >= -0.6)


def test_the_arch_contours_lie_inside_the_outline_and_the_trim_lines_inside_the_toe(made):
    import shapely

    ins, _ = made
    outline = ins.surface["outline"]
    xs, ys, rise = template.rise_above_base(ins)
    segs = template.contour_segments(xs, ys, rise, template.CONTOUR_STEP_MM)
    assert len(segs)
    pts = segs.reshape(-1, 2)
    assert shapely.contains_xy(outline.buffer(0.6), pts[:, 0], pts[:, 1]).all()
    trims = template.trim_lines(outline)
    assert sorted({mm for mm, _ in trims}) == [5.0, 10.0]
    x0, _, x1, _ = outline.bounds
    for mm, pts in trims:
        d = np.asarray(shapely.distance(outline.exterior, shapely.points(pts)))
        assert np.allclose(d, mm, atol=0.3) and pts[:, 0].min() >= x0 + 0.8 * (x1 - x0) - 0.01


def test_the_template_of_a_left_insole_is_the_mirror_of_the_right():
    """Seen from above, a left insole's arch is on the page's right: the template is drawn looking down on it."""
    left = insole.from_scan(synth.curved_foot("left", leg=False), "left", insole.InsoleParams(target_length_mm=275.0))
    right = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    pages = {}
    for name, ins in (("left", left), ("right", right)):
        doc = pymupdf.open(stream=template.template_pdf(ins, "synthetic", synthetic=True), filetype="pdf")
        page = doc[0]
        peak = [b for b in page.get_text("blocks") if "highest fill" in b[4]]
        outline = max(_outline_paths(page), key=lambda d: d["rect"].width)["rect"]
        pages[name] = (peak[0][0] - (outline.x0 + outline.x1) / 2)  # the arch's mark, right of the middle: > 0
    assert pages["right"] < 0 < pages["left"]


def test_the_template_marks_the_arch_support_where_it_is_not_the_highest_fill():
    """On a flat foot the highest fill can be the heel's rounded back: the arch support as printed gets its own ring
    and label, on the arch's side of the page (a right insole's arch on the page's left), unless it is the same
    point."""
    right = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    r = right.report
    r["max_fill_at_mm"] = dict(x=r["arch_fill"]["x"] - 100.0, y=0.0)  # as on a flat foot: the heel's back
    doc = pymupdf.open(stream=template.template_pdf(right, "synthetic", synthetic=True), filetype="pdf")
    labels = [(i, b) for i, page in enumerate(doc) for b in page.get_text("blocks") if "arch support" in b[4]]
    assert labels  # on each page whose stretch it falls in (the pages overlap)
    for i, b in labels:
        assert f"arch support {r['arch_fill']['max_mm']} mm" in b[4]
        outline = max(_outline_paths(doc[i]), key=lambda d: d["rect"].width)["rect"]
        assert b[0] < (outline.x0 + outline.x1) / 2
    r["max_fill_at_mm"] = dict(x=r["arch_fill"]["x"], y=r["arch_fill"]["y"])  # the same point: one label
    doc = pymupdf.open(stream=template.template_pdf(right, "synthetic", synthetic=True), filetype="pdf")
    assert not any("arch support" in b[4] for page in doc for b in page.get_text("blocks"))
