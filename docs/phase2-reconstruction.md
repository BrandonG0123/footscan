# Phase 2 — Reconstruction and accuracy

> Not a medical device. See [SAFETY.md](SAFETY.md). Phase 2 turns photos into
> a surface in millimetres and measures how far that surface is from the
> truth. It designs and prints nothing.

## What it does

```
photos on the mat
  │  COLMAP (structure from motion): where each photo was taken, and the lens
  │  the mat's markers: COLMAP's unitless model → millimetres, with error checks
  │  plane-sweep stereo: a depth for every pixel, kept only where photos agree
  │  Poisson surface → cut at the floor → trim → fill small holes → Taubin smoothing → decimate
  ▼
mesh.ply (mm, mat frame)
  ├─ calibration object → accuracy.json  (scan vs. the printed object's model and your calipers)
  └─ standing foot       → mesh_foot.ply, plantar.ply, plantar.json  (provisional foot frame)
```

Run it from the studio (*Research library* → *3D model* → *Build*, or the
*3D model* button on a customer's scan) or from the command line:

```bash
.venv/bin/footscan reconstruct data/captures/<id>
.venv/bin/footscan reconstruct data/captures/<id> --calibration-object --calipers calipers.json
```

Everything is written to `<capture>/recon/`: the meshes, the point cloud and
`report.json`. The report holds every number, every setting, the software
versions and a SHA-256 of every input photo, so a result can be traced back
to exactly what produced it.

## The geometry, step by step

Each module's docstring explains its operations in plain terms; this is the
map.

| Step | Module | Operation |
|---|---|---|
| Camera poses + lens | `recon/sfm.py` | SIFT features, pairwise matching with RANSAC geometric checks, incremental reconstruction, bundle adjustment (COLMAP 4.2) |
| Mat corners | `recon/markers.py` | ArUco detection with sub-pixel corner refinement; pixel conventions (OpenCV vs COLMAP: half a pixel) |
| Millimetres | `recon/scale.py` | per-photo homography check per sheet; corner triangulation (DLT + Gauss–Newton); similarity fit (Umeyama) per sheet; floor plane from both sheets, position from the heel sheet |
| Depth | `recon/dense.py` | plane-sweep stereo: homography warps, normalised cross-correlation, best-of-k sources, sub-plane parabola, edge-band removal, cross-view geometric consistency, voxel merging |
| Surface | `recon/mesh.py` | statistical outlier removal, connected pieces, PCA normals, screened Poisson, floor cut, distance trim, hole filling, Taubin smoothing, quadric decimation |
| Accuracy | `recon/accuracy.py` | point-to-plane ICP (rigid only, never scaling), signed surface distance, completeness, caliper-style dimensions from plane and sphere fits |
| Foot frame | `recon/plantar.py` | floor = mat plane; long axis = the line the footprint's filled convex hull is spread along most (its principal axis of area; until 2026-11-25 the narrowest-width direction, which ran along one side); heel/toe from the leg; underside selection; medial arch profile |

**Why not COLMAP's own dense step?** COLMAP's PatchMatch stereo only runs on
an NVIDIA or AMD GPU; on a Mac it refuses to start. `dense.py` does the same
job on the CPU. Everything around it (poses, lens model, undistortion) is
COLMAP's. On a machine with an NVIDIA GPU, COLMAP's PatchMatch could be
swapped in.

**Reproducibility.** The COLMAP settings are fixed in `SfmConfig` (seed,
one thread). Running COLMAP twice on the same photos gives bit-identical
camera poses; a slow test checks this.

## Scale: what the error numbers mean

| Report field | Meaning |
|---|---|
| `residual_rms_mm` | How far each mat corner's 3-D position lands from where it is printed, after the fit. Mostly per-corner noise, which averages out of the scale. |
| `sheet_scale_disagreement_pct` | The two sheets are fitted separately; their scales should agree. This is an **independent** check on the scale (never used in either fit). Also given as millimetres over a 250 mm foot. |
| `scale_se_pct` (per sheet) | Bootstrap standard error: how much the scale changes with a different subset of markers. |
| `mat_flatness_rms_mm` | Height of the corners above the fitted floor: how flat the paper lay. |
| `seam_offset` | Where the toe sheet really is relative to its nominal place (tape is never perfect). It doesn't affect the scale. |

## The accuracy study (the real number)

1. **Print** `web/studio/files/footscan-calibration-object.stl` (or
   `footscan calib-object`): base-down, 100 %, no supports, matte light
   filament. 150 × 70 × 35 mm, with a dome, a ramp and two terraces.
2. **Measure** it with calipers: length, width, base thickness, dome top
   height, both terrace heights. Enter them on the model page. The
   dimensions are then compared with the print, not the model, so printer
   error isn't counted as scan error. If the print differs from the model by
   more than 0.4 mm anywhere, the report warns that the surface numbers
   include print error.
3. **Scan** it standing on the mat: *Research capture* → *Calibration object*.
   Once as printed, once dotted all over with a fine marker pen. Say which
   in the notes. Plain plastic is closer to skin; the dotted run shows what
   texture is worth.
4. **Build** the model. The page shows:
   - surface deviation: median, 95th percentile, max and signed mean
     (+ = scan too big);
   - completeness: share of the object's surface with scan within 1 mm and 2 mm;
   - each caliper dimension, scan minus reference;
   - the same surface numbers before smoothing, so smoothing's effect is
     measured rather than assumed.

The surface statistics come after lining the scan up with the model
(rotation and shift only), which flatters them slightly. The dimensions
don't depend on the alignment.

## Results so far

**No real scan has been reconstructed yet.** The only real capture on disk is
an object scan without the mat, which can't be put in millimetres. The real
accuracy number comes from step 3 above, and nothing in this section stands
in for it.

What exists is a check of the code on **synthetic** photos: 31 images of the
calibration object on the mat, rendered at 540 × 960 by `tests/synth.py`
with a known lens, known camera positions and sensor noise. Run on the M3
MacBook on 2026-10-01, from the studio's *Rebuild* button (`footscan serve
--data .demo-data`):

| Check (synthetic) | Result |
|---|---|
| Photos placed by COLMAP | 31 / 31, reprojection error 0.37 px |
| Scale vs. truth (distances between cameras) | 0.004 % off |
| Sheets' scale disagreement | 0.05 % (0.12 mm over 250 mm) |
| Camera positions vs. truth | median 0.27 mm, worst 2.1 mm |
| Surface deviation, final mesh | median 0.15 mm, 95th percentile 0.99 mm, signed mean +0.12 mm |
| Surface deviation, before smoothing | median 0.15 mm, 95th percentile 0.92 mm |
| Completeness within 1 mm | 98.7 % |
| Length / width | +0.31 / +0.27 mm |
| Heights (base, terraces, dome top) | +0.03 to +0.06 mm |
| Dome radius (sphere fit) | +0.08 mm |
| Time | 336 s (cameras 46 s, depth 170 s, surface 88 s, accuracy the rest) |

These say the pieces fit together and recover a known shape and size. They
are **not** a phone's accuracy: the rendered photos have perfect focus, a
fixed exposure, a flat mat and an evenly speckled object.

What the synthetic run already shows:

- **Walls come out slightly fat (+0.15 mm).** Matching windows that straddle
  an edge pick up the nearer surface. Removing a band around depth jumps
  cut the 95th percentile from 1.05 to 0.76 mm on the raw points, but didn't
  remove the bias. Feet have no sharp edges, but they do have outlines
  against the floor.
- **Taubin smoothing made this object slightly worse.** The object's edges
  are sharp; a foot's surface isn't. Keep it under review with real scans:
  the report always carries both numbers.
- **Run time:** under 6 minutes for 31 small photos. Real scans have more
  and larger photos, so expect longer; reconstructions run one at a time.

## Skin, texture and smoothing (synthetic experiment)

Skin has far less texture than a dotted calibration object. To see what
that costs, a smooth foot-sized dome (half-ellipsoid, 240 x 92 x 58 mm) was
rendered twice, 31 photos each at 540 x 960, once dotted like pen speckle
and once with a faint skin-like mottling (a guess at skin: a few percent of
brightness variation at 0.8, 3 and 9 mm scales), and reconstructed.
Surface error is measured against the true dome in the mat frame (no
alignment at all). Run 2026-10-05:

| | median | 95th pct | signed mean | surface within 1 mm |
|---|---|---|---|---|
| dotted, no smoothing | 0.104 mm | 0.375 mm | +0.047 mm | 99.98 % |
| dotted, Taubin 10 steps (default) | 0.098 mm | 0.348 mm | +0.048 mm | 99.97 % |
| skin-like, no smoothing | 0.107 mm | 0.313 mm | +0.075 mm | 71.4 % |
| skin-like, Taubin 10 steps (default) | 0.105 mm | 0.307 mm | +0.075 mm | 70.9 % |

What it says:

- **Plain skin costs coverage, not accuracy.** Where the surface is found
  it is as accurate; but almost 30 % of it wasn't found at all, and COLMAP
  found only 10 points on the plain dome, so the pipeline had to fall back
  to searching the whole mat area (now with a quick low-resolution pass to
  find the subject first: 135 s instead of more than 15 minutes).
  **Dot the foot with a washable marker, or wear a speckled sock** (both are
  choices on the capture page): that is the difference between 71 % and
  100 % of the surface.
- **Smoothing helps on smooth shapes** (95th percentile 0.375 -> 0.348 mm)
  where it slightly hurt on the sharp-edged calibration object. Feet are
  smooth, so the default (10 Taubin steps) stays.

Synthetic, so: the right *direction* and rough size of each effect, not a
phone's accuracy.

## First contact with real photos

The one real capture so far (114 iPhone frames of a shoe on a black desk,
no mat, 2026-09-25) was run through the camera-solving step on 2026-10-05.
It found three real problems, now fixed, that the rendered scenes had not:

| Problem | Effect on the real capture | Fix |
|---|---|---|
| Lens distortion solved from the first two photos | distortion came out k1 = 0.7, k2 = -2.0 (a phone's video is nearly distortion-free); only 2 of 114 photos placed | hold distortion and lens centre fixed while placing photos, solve them in a final adjustment: 40 placed, k1 = 0.02, k2 = -0.04 |
| One photo taken with the phone sideways | silently dropped (one camera = one image size) | turned upright before solving; listed in the report |
| Big jumps between kept photos | the capture kept one photo per 0.6 s; when the phone swung 25-47 degrees between two, nothing linked them and the photos split into 4 unconnected groups (40, 39, 23, 13) | capture now keeps a "bridging" photo whenever the view has turned 8 degrees since the last, and says "slow down" when turning faster than 35 degrees a second; the report says when photos split into groups |

The split shoe capture is still split (its photos were taken with the old
rule); a new capture is needed to see the bridging work. A foot scan also
has the printed mat in every photo, which gives far more to link photos
than a plain black desk.

## Not done / known limits

- **Real photos.** Everything above needs repeating on real captures:
  marker detection on real paper, skin texture, motion blur, auto-exposure.
- **Capture resolution.** The phone records 1920 × 1080 video frames. If the
  real accuracy is limited by resolution, the capture page can ask for 4K.
- **Non-weight-bearing scans** have no floor under the foot, so their foot
  frame waits for Phase 3 landmarks.
- **The foot frame is provisional.** It is built from the mat and the
  footprint outline; Phase 3 replaces it with landmarks you click.
- **No 3-D viewer yet.** Download the PLY and open it in MeshLab or Blender.
  The landmark viewer (Phase 3) adds one.
- **LiDAR comparison.** Imported LiDAR meshes aren't yet run through the
  accuracy study. `accuracy.evaluate` accepts any mesh in mat coordinates, so
  the missing piece is aligning the LiDAR mesh to the mat.

## Tests

```bash
.venv/bin/python -m pytest -q             # fast: geometry, scale, mesh, accuracy, plantar, server
.venv/bin/python -m pytest -m slow -q     # end-to-end on a rendered scene (~5 min)
```

Every test scene is synthetic and labelled as such. The fast tests check
exact answers: the calibration object against its formula, triangulation,
similarity fits, the mat frame with a crooked seam, the exact-distance
index against brute force, and the accuracy study on a perfect copy and on
a copy 1 % too big. That last one must report 1 % too big, not be "lined up"
away.
