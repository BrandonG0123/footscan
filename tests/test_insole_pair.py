"""A matched pair from one foot's scan: the other foot's insole as its mirror image (insole.mirrored, footscan insole
--pair). SYNTHETIC feet only (tests/synth.py)."""

import numpy as np
import pytest

import synth
from footscan import cli, insole


@pytest.fixture(scope="module")
def pair():
    right = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    return right, insole.mirrored(right)


def test_the_mirror_image_is_the_other_foots_insole_exactly_mirrored(pair):
    right, left = pair
    assert left.foot == "left" and left.report["foot"] == "left" and left.report["mirrored_from"] == "right"
    assert left.mesh.is_watertight and left.mesh.volume == pytest.approx(right.mesh.volume, rel=1e-6)
    V = np.array(right.mesh.vertices)
    V[:, 1] *= -1
    assert np.allclose(np.sort(left.mesh.vertices, axis=0), np.sort(V, axis=0))
    assert left.report["max_fill_mm"] == right.report["max_fill_mm"]
    assert left.report["max_fill_at_mm"]["y"] == -right.report["max_fill_at_mm"]["y"]
    assert left.report["edge_beyond_heel"]["side"] == right.report["edge_beyond_heel"]["side"] == "inner"
    assert left.report["length_mm"] == right.report["length_mm"]


def test_its_sheet_and_warnings_say_first_that_it_is_not_that_foots_own_shape(pair):
    right, left = pair
    first = left.report["warnings"][0]
    assert "mirror image" in first and "not made from a scan of the left foot" in first
    assert not any("mirror image" in w for w in right.report["warnings"])  # the source is untouched
    sheet = insole.summary_html(left, "test", synthetic=True)
    assert "First-fit insole: left foot (the right insole's mirror image)" in sheet
    assert "not made from a scan of the left foot" in sheet


def test_the_mirror_images_paper_template_has_its_arch_on_the_pages_right(pair, tmp_path):
    """Seen from above, a left insole's arch is on the right: its surface was mirrored with it."""
    pymupdf = pytest.importorskip("pymupdf")
    right, left = pair
    files = insole.write_outputs(left, tmp_path, "left-insole", "test", synthetic=True)
    page = pymupdf.open(files["template"])[0]
    peak = [b for b in page.get_text("blocks") if "highest fill" in b[4]][0]
    outline = max((d for d in page.get_drawings() if d.get("width") and abs(d["width"] - 0.45 * 72 / 25.4) < 0.01),
                  key=lambda d: d["rect"].width)["rect"]
    assert peak[0] > (outline.x0 + outline.x1) / 2


def test_footscan_insole_pair_writes_both_feet(tmp_path):
    foot = tmp_path / "foot.ply"
    synth.curved_foot("right", leg=False).export(foot)
    out = tmp_path / "out"
    assert cli.main(["insole", str(foot), "--foot", "right", "-o", str(out), "--length", "275", "--pair",
                     "--shoes", str(tmp_path / "no-shoes")]) == 0
    for side in ("right", "left"):
        for suffix in (".3mf", ".stl", "-summary.html", ".json", "-template.pdf"):
            assert (out / f"{side}-insole{suffix}").is_file()
    import json

    left = json.loads((out / "left-insole.json").read_text())
    assert left["mirrored_from"] == "right" and left["length_mm"] == json.loads((out / "right-insole.json").read_text())["length_mm"]


@pytest.mark.parametrize("kw, source_says", [(dict(), False), (dict(foot="left"), True)],
                         ids=["right shoe's insole", "left shoe's insole"])
def test_the_mirror_images_fit_warnings_are_its_own(kw, source_says):
    """Whether the shoe's outline had to be mirrored is the other way round for the other foot: a right foot cut to
    a right shoe's insole needs no mirroring, its mirror image (a left insole from that right shoe's outline) does,
    and the other way for a left shoe's. Each says so for itself, once; the source is untouched."""
    from footscan.recon import shoe

    outline, _ = shoe.outline_from_scan(synth.shoe_insole(**kw))
    right = insole.from_scan(synth.curved_foot("right", leg=False), "right",
                             insole.InsoleParams(shoe_outline=shoe.as_param(outline)))
    left = insole.mirrored(right)
    says = [w for w in left.report["warnings"] if "mirrored for this foot" in w]
    assert any("mirrored for this foot" in w for w in right.report["warnings"]) is source_says
    assert len(says) == (0 if source_says else 1)
    assert left.report["shoe_fit"]["mirrored"] is not source_says
    if says:
        assert "is a right shoe's as scanned" in says[0]
