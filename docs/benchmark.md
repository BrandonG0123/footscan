# How accurate is it? The benchmark so far, and the bar to clear

Not a medical device. These numbers say how well the software reads a
sole; they are not a claim about any device's clinical performance, and
never a comparison with a prescribed orthotic.

## The bar: what the best foot-scanning tools report

The figures below are as published, with who measured them. They are
end-to-end: a real foot, scanned with a real phone or scanner, compared
with calipers or a reference scanner.

| Tool | What was measured | Result | Who measured |
|---|---|---|---|
| Volumental mobile (phone) scanning | foot length, ball width, barefoot adults, against Volumental's in-store scanner | median absolute error 1.1 mm (length), 1.3 mm (ball width); repeat scans within 1.1 mm (length) | the vendor; sample size not stated ([Volumental](https://volumental.com/volumental-mobile-scanning)) |
| Smartphone with a depth camera | foot shape against a 3D scanner | shape error about 1.13 mm; arch measures 0.95 and 0.52 mm | peer-reviewed conference paper ([ResearchGate](https://www.researchgate.net/publication/328316594_A_Simple_3D_Scanning_System_of_the_Human_Foot_Using_a_Smartphone_with_a_Depth_Camera)) |
| OptiFit (phone app) | 19 silicone foot models against manual measurement | about 95% (length), 97% (width), 89% (arch height) accuracy | peer-reviewed, Sensors 2022 ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9739363/)) |
| Kinect-based plantar scanner, weight-bearing (Rogati et al. 2019) | the plantar surface against a high-resolution laser scanner, 14 healthy adults | RMSE under 3 mm over the whole plantar surface, under 1.6 mm over the arch; repeat sessions 1.2 +/- 0.4 mm | peer-reviewed, J Foot Ankle Res ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6720393/)) |
| Foam box vs 3D scanning for orthoses | systematic review of the evidence | no clear winner; reliability varies by method; arch height the weak spot | systematic review, J Foot Ankle Res 2020 ([Springer](https://link.springer.com/article/10.1186/s13047-020-00442-8)) |

So the bar is about **1 mm** for length, width and overall shape, end to
end; for the plantar surface itself, the one study that measures it point
by point (the Kinect scanner) reports under 1.6 mm over the arch and under
3 mm overall. Arch height is the hardest measure for everyone.

## What footscan's processing adds (synthetic feet)

`scripts/benchmark_prep.py` (report: `reports/benchmark-prep.md`). Every
number below is from a run of it, on SYNTHETIC scans: a computer-made foot
whose true shape is known exactly (250 x 100 mm, heel pad and ball of the
foot on the floor, a smooth 14 mm arch on the inner side, rounded edges),
handed over the way the iPhone app hands over a scan (metres, Y up, turned,
maybe tilted), damaged the way phone scans are, then run through the same
preparation as Make insole. Heights are measured above each floor (the one
the processing found, and the true one), at every point of the sole more
than 8 mm in from its edge, both feet: sole-up scans with the knee bent,
sole-up scans lying with the legs flat (feet past the end of the bed), and
foam prints.

| | clean scans (any tip, roll, phone level off, holes, stray bits, shallow or deep print, tilted box) | noisy scans (speckle 0.3-1.0 mm, coarse speckle, jitter) |
|---|---|---|
| cases | 32 | 26 |
| average height error (bias) | 0.01 mm or less | 0.12 mm or less |
| RMS height error | 0.01 mm or less | 0.46 mm or less |
| 95% of points within | 0.03 mm | 0.97 mm |
| arch top | within 0.05 mm | within 0.98 mm |
| floor tilt | 0.03 degrees or less | 0.91 degrees or less |
| outline length | +0.4 to +0.5 mm | +0.3 to +1.8 mm |
| arch on the inner side | every case | every case |

Scans rougher than 0.5 mm (as the processing reads them) get a warning to
scan again.

**What this does and doesn't show.** It shows the software reading the sole
adds next to nothing on a clean scan, and well under a millimetre on a
noisy one: it isn't the weak link. It does **not** show how accurate a real
phone scan of a real foot is: that's the capture (Apple's Object Capture,
the light, how still the foot is), and it can only be measured on real
objects. The published figures above are end to end; these are the
processing alone. They are not comparable until the end-to-end
measurement below is done.

## Knee bent or legs flat?

Lying face down, a foot held up with the knee bent has to be held still by
the leg's own muscles; with the legs flat on the bed and the feet just past
its end, the bed holds the leg and the foot can relax. That should move
less, so it may well scan better. The cost: the helper can't go all the
way round (the bed is in the way), so the scan is a half circle under and
behind the foot, and the processing has to find the foot's direction from
the leg lying along the bed instead of the leg pointing up.

What the synthetic benchmark says, on the same damage, in mm (p95 of the
height error, right / left foot):

| | knee bent | legs flat |
|---|---|---|
| clean, phone level off 4 degrees, no bed in the scan | 0.00 / 0.00 | 0.00 / 0.00 |
| speckle 0.6 | 0.45 / 0.68 | 0.45 / 0.68 |
| jitter 0.5 | 0.36 / 0.24 | 0.32 / 0.24 |

So the processing reads either pose equally well. This can't say which pose
gives the better *scan*: a computer-made foot doesn't twitch. That is
measured with two real scans of the same foot in the same pose, compared
with `footscan compare` (or Compare scans in the research library): each
scan is prepared exactly as Make insole prepares it, the two sole height
maps are lined up flat (turn and slide only; heights and tilts are left
as they are), and it reports how far apart they are at every point of the
sole seen in both: typical and 95% difference, bias, arch top, outline.
That is the same "repeat scans within ... mm" that foot-scanner makers
publish (Volumental: 1.1 mm).

The test, when there's time for four scans:

1. Right foot, knee bent, twice (two separate scans, getting up between).
2. Right foot, legs flat, twice.
3. Compare each pair. The pose whose two scans agree more closely is the
   one the foot holds still in; it becomes the first choice in the app.

Until those numbers exist, both poses stay in the app, knee bent first.

## What got fixed along the way

The benchmark found real problems before any real foot did:

- A foot tipped 45 degrees by its relaxed ankle (toes lowest, heel about
  180 mm up) lost its leg to the "keep the bottom 180 mm" step, and the
  fallback guessed the heel wrong: an insole turned back to front, caught
  only by the arch-on-the-outside warning. Now 300 mm is kept, the leg is
  found by surface area, and without one the narrower end is the heel.
- The "shape-keeping" smoothing from trimesh shrinks (with the usual
  settings both of its passes pull inward), which would lift a real
  rounded heel. Replaced, then replaced again: true Taubin smoothing keeps
  shape but barely touches scan speckle a few mm across. Now a measured
  Gaussian blur, only on scans that need it, sized in millimetres.
- On a noisy scan the foot rested on the noise's lowest specks: every
  height read high (by about 1.5 x the noise) and the floor tilted by up
  to a degree. Now the floor is set from smooth fits under the heel and
  both sides of the ball of the foot.
- The noise estimate read a fifth of the true noise, and (Codex found)
  counted a clean curved surface's smoothing shrinkage as noise. Now it's
  what's left over from smooth curved patches fitted 4 mm round: 0.00 mm
  on clean curved shapes, about 0.7 x the true noise for fine speckle,
  0.5 x for coarse (bumps 4 mm across), 1.0 x for point jitter.

Codex reviews of those fixes found more, each now fixed and tested:

- A bed 200-300 mm under a sole-up scan (a short leg, a knee bent past a
  right angle) survived the taller cut and, being bigger, was taken for
  the foot. The bed is now found (the nearest big level surface well above
  the turned-over sole) and cut short of.
- Two foam blocks scanned together: one outline round both let their
  walls and bottoms outrank the prints. Now each block is outlined on its
  own (patches of foam top within 20 mm count as one block, so a gap in
  the scan doesn't cut a print in half), the table is looked for only
  outside the blocks (a deep print's flat bottom looked like a table when
  the scan left the table out), and candidates are ranked by
  upward-facing area, which a print's bottom has and walls don't.
- Legs flat, jittery scan: specks of foot happened to be level enough to
  count as bed, and the "bed" outline then reached under the foot and cut
  part of it away (length out by 160 mm). The bed is now only the largest
  single connected level patch.
- If the exact outline can't be made, the fallback is the filled convex
  outline (it was able to collapse to a fragment), and the sheet says so.

## The part not measured yet: the capture

The processing is not the weak link; the capture may be. The closest
published check of Apple's Object Capture itself (Photocatch, on a Mac,
from a DSLR camera on a turntable, 11 stone hand axes, against calipers;
PLOS ONE 2024, [link](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0314560))
found the size depends on what sets the scale: 1.9 mm out in length when
scaled from a 2.8 mm stamp on the object, 0.23 mm (length) and 0.47 mm
(width) when scaled from the object's whole length. No surface deviation
was reported, and it wasn't a phone. With the app, the scale comes from the
iPhone's LiDAR; how right that is for a foot-sized object is exactly what
the calibration object measures.

## Measuring it end to end (needs real objects)

To compare with the table at the top on equal terms:

1. **Calibration object** (Phase 2): print it, measure it with calipers,
   scan it with the app. Its surface error is the capture's own accuracy.
2. **Real foot, the same measures as the published ones**: foot length and
   ball width with calipers (or a Brannock device), arch height with the
   calipers' depth rod on a foam print; then sole-up or foam-print scans,
   three times each. Report the median absolute error and the repeat-scan
   spread, as Volumental does, so the numbers line up.
3. **Foam print depth**: the studio reports `print_deepest_mm`; measure the
   heel print's depth with the depth rod and compare.
