"""Finding the mat's markers in each photo, to sub-pixel precision.

The phone already finds markers live (js-aruco2, to steer the person). Here
we find them again, offline, with OpenCV, on the saved full-size photos:
there's no time pressure, so we can afford the careful version.

What a detection is
-------------------
Each marker is a 30 mm black square with a unique 6x6 pattern inside. The
pattern says *which* marker it is; the board file says where that marker is
printed on the sheet. So each detected marker gives four correspondences:
"this pixel is the image of that exact millimetre position on the paper".
Those correspondences are what turn the reconstruction into millimetres
(see scale.py).

Corner precision
----------------
A corner found to the nearest pixel is off by up to half a pixel; at a
typical phone distance one pixel is about a quarter of a millimetre on the
mat. Sub-pixel refinement fits the corner to the image gradients around it
(the intensity edges of the black square cross at the corner), which brings
the error to a small fraction of a pixel. The tests measure that error on
rendered images, where the true corner position is known exactly.

Pixel conventions
-----------------
OpenCV puts pixel *centres* at integer coordinates (the first pixel covers
-0.5..0.5). COLMAP puts pixel *corners* at integers (the first pixel covers
0..1). Mixing them silently shifts every point by half a pixel. Corners are
stored here in OpenCV's convention; ``to_colmap`` converts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

MAT_DIR = Path(__file__).resolve().parents[3] / "web" / "mat"

# ARUCO_MIP_36h12 codes differ from each other in at least 12 of 36 bits.
# Correcting up to 3 flipped bits keeps detections robust to glare or a
# smudge while leaving a margin of 9 bits before one marker could be read as
# another. A wrong ID would put four corners in the wrong place, which is
# far worse than missing a marker, so this errs on the strict side.
MAX_CORRECTED_BITS = 3
# A marker seen this small (or this edge-on) is a few pixels per millimetre;
# its corners are too imprecise to help and, at grazing angles, biased.
MIN_SIDE_PX = 22.0


@dataclass
class Detection:
    image: str
    marker_id: int
    sheet: int                 # 0 = heel sheet, 1 = toe sheet
    corners_px: np.ndarray     # 4x2, OpenCV pixel convention, TL TR BR BL as printed
    corners_mm: np.ndarray     # 4x2, position on that sheet (sheet coordinates)


@lru_cache(maxsize=4)
def load_board(paper: str) -> dict:
    board = json.loads((MAT_DIR / f"footscan-mat-{paper}.json").read_text(encoding="utf-8"))
    board["lookup"] = {
        int(mid): (i, np.asarray(corners, float))
        for i, sheet in enumerate(board["sheets"])
        for mid, corners in sheet["markers"].items()
    }
    return board


def make_detector():
    import cv2

    aruco = cv2.aruco
    params = aruco.DetectorParameters()
    params.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
    params.cornerRefinementWinSize = 5
    params.cornerRefinementMaxIterations = 60
    params.cornerRefinementMinAccuracy = 0.005
    # errorCorrectionRate scales the dictionary's maximum correctable bits
    # ((12 - 1) // 2 = 5); 0.6 * 5 = 3 bits.
    params.errorCorrectionRate = MAX_CORRECTED_BITS / 5
    return aruco.ArucoDetector(aruco.getPredefinedDictionary(aruco.DICT_ARUCO_MIP_36h12), params)


def detect(gray: np.ndarray, paper: str, image: str = "", detector=None) -> list[Detection]:
    """Markers of this mat found in one grayscale image."""
    board = load_board(paper)
    detector = detector or make_detector()
    corners, ids, _ = detector.detectMarkers(gray)
    out = []
    for c, mid in zip(corners, [] if ids is None else ids.ravel()):
        hit = board["lookup"].get(int(mid))
        if hit is None:  # a marker from the other paper size, or not ours at all
            continue
        sheet, mm = hit
        quad = c.reshape(4, 2).astype(float)
        if _apparent_side(quad) < MIN_SIDE_PX:
            continue
        out.append(Detection(image, int(mid), sheet, quad, mm))
    return out


def _apparent_side(quad: np.ndarray) -> float:
    """Square root of the quad's area: its side length if it were square-on."""
    x, y = quad[:, 0], quad[:, 1]
    return float(np.sqrt(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2))


def detect_images(image_dir: Path, names: list[str], paper: str) -> dict[str, list[Detection]]:
    import cv2

    det = make_detector()
    out = {}
    for name in names:
        gray = cv2.imread(str(Path(image_dir) / name), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise FileNotFoundError(name)
        out[name] = detect(gray, paper, name, det)
    return out


def guess_paper(image_dir: Path, names: list[str], sample: int = 8) -> str | None:
    """Which mat size is in the photos, if the capture didn't record it.

    Letter and A4 sheets use different marker IDs (0-99 vs 100-199), so
    the IDs seen settle it.
    """
    import cv2

    det = make_detector()
    votes = {"letter": 0, "a4": 0}
    step = max(1, len(names) // sample)
    for name in names[::step]:
        gray = cv2.imread(str(Path(image_dir) / name), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        for paper in votes:
            votes[paper] += len(detect(gray, paper, name, det))
    best = max(votes, key=votes.get)
    return best if votes[best] > 0 else None


def to_colmap(px: np.ndarray) -> np.ndarray:
    """OpenCV pixel coordinates -> COLMAP pixel coordinates (+0.5 px)."""
    return np.asarray(px, float) + 0.5
