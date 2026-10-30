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

One limit the comparison found: a scan that misses the last 25 mm of the
toes compares with the whole foot to 0.02 mm (p95), but one that misses
60 mm (the toes and part of the ball) doesn't: the floor is set under the
heel and the ball, found as a share of the foot's length, and the shorter
foot puts the "ball" back toward the arch (1.2 mm p95, arch 1.3 mm lower).
Scan the toes.

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

## Toes hanging up in a sole scan (29 Oct)

Relaxed in the air, a foot's toes hang up off the line of its sole; the
left sole-up scan 89df had its toe tip 17.8 mm above the floor. The
benchmark now bends the synthetic foot's toes up (tests/synth.py
`bend_toes`, about a line across the foot 185 mm from the heel) and
compares the sole only behind the bend. SYNTHETIC, both feet alike unless
shown right / left; before is the preparation as of the start of 29 Oct,
after lays the toes flat (`_lay_toes_flat`) and places the floor's heel and
ball along the whole underside when the toes hang up:

| case | outline length, mm (before -> after) | p95 height error, mm | floor tilt, deg | arch on the inner side |
|---|---|---|---|---|
| sole up, toes bent up 20 | -4.8 / -4.9 -> -1.4 | 0.19 / 1.49 -> 0.19 | 0.14 / 1.73 -> 0.14 / 0.13 | yes -> yes |
| sole up, toes bent up 35 | -19.8 / -19.5 -> -3.9 / -4.0 | 1.15 / 1.44 -> 0.30 | 1.30 / 1.61 -> 0.16 / 0.15 | NO (false "arch on the outside") -> yes |
| sole up, toes bent up 35, speckle 0.6 | -19.4 / -20.7 -> -4.6 / -4.9 | 2.28 / 0.91 -> 0.83 / 0.80 | 2.81 / 0.83 -> 0.98 / 0.84 | yes -> yes |
| legs flat, toes bent up 35 | -19.8 / -19.6 -> -3.9 / -4.0 | 1.15 / 1.43 -> 0.29 | 1.31 / 1.60 -> 0.13 / 0.14 | NO -> yes |

The other 58 cases are unchanged to the last digit. Where toes really bend
(at the joints, inside the ball of the foot, or nearer the skin) changes
how long the laid-flat outline reads: on bends about a line 12-18 mm up it
reads 1.7-6.6 mm long (the table beside `TOES_JOINT_UP_MM` in
`foot_prep.py`). Only a ruler measurement of a scanned foot can say which.

Not fixed: toes curled *down* past the ball (SYNTHETIC, 20 degrees) tip
the floor 6 degrees heel to toe, because the hull rests on the heel and
the toe tips. A sole-up or legs-flat pose lets gravity pull the toes the
other way, so it hasn't been seen; noted here in case a real scan shows it.

On the real scans (Brandon's Mac, 29 Oct, `scripts/accuracy_eval.py` at
8dbfdee before and 25b3227 after; no ruler length yet, so none of these can
be called more accurate). All three distinct sole scans had their toes up
and were laid flat:

| scan | toes raised, deg | toe tip up, mm | outline L x W, mm | footprint length, mm |
|---|---|---|---|---|
| 2349 right, sole up | 10.8 | 9.5 -> 0.6 | 244.1 x 89.6 -> 243.7 x 89.8 | 241.5 -> 240.8 |
| 89df left, sole up | 12.8 | 17.8 -> 6.0 | 228.2 x 79.8 -> 229.7 x 79.9 | 203.8 -> 224.7 |
| 2190 left, legs flat | 21.5 | 18.1 -> 14.4 | 211.9 x 107.1 -> 219.5 x 108.2 | 199.1 -> 204.9 |

The left foot (89df) still reads 14.0 mm shorter and 9.9 mm narrower than
the right (2349), so its toes were not what made it short. 2349's floor
correction moved 3.20 -> 3.59 degrees. 2190 lost its "toes missing"
warning (its end now rounds off) but is still refused: torn near the floor,
rolled 23 mm, both feet in the scan. On SYNTHETIC feet with the front 15-40
mm cut off and the rest bent up 20 or 35 degrees, laying flat never hid the
cut (test_completeness.py); the tips of 2190's toes still curl up 14 mm,
which the one joint doesn't straighten.

Toes that curl as well (30 Oct): the benchmark also bends the tips a second
time, at 220 mm from the heel. Laying flat at up to three joints instead of
one (SYNTHETIC, outline length vs true, right / left; the sole's heights and
the floor unchanged):

| case | one joint | up to three |
|---|---|---|
| sole up, toes up 20, tips 30 more | -7.9 / -8.0 | -5.3 / -5.3 |
| sole up, toes up 30, tips 40 more | -13.2 / -13.2 | -7.7 / -7.8 |
| legs flat, toes up 20, tips 30 more | -7.9 / -7.9 | -5.3 / -5.3 |

Toes bent once read exactly as before. Not on a real scan yet.

Still short, with no warning (SYNTHETIC, curved_foot, right, sole up,
outline vs 250 mm): a curl that starts within about 25 mm of the tip
(60 degrees from 225 mm: 14.9 mm short; from 230 mm: 12.0; 50 degrees from
235 mm after 20 at 185: 10.4), too short past its bend to be told from a
toe's rounded end, and a curl much steeper than the toes' first bend (20 at
185 then 70 more at 215: 19.4 short; 15 at 180, 15 at 200, 70 at 222:
23.4). Neither the tip's height nor how far the foot reaches above the
outline's 30 mm tells these apart from toes laid flat: the curled tips stay
below 30 mm and their lowest point is near the floor. What catches them is
the length against the other foot's scan (12 mm, on arrival) and a ruler
length.

The floor on a different test shape: `synth.shaped_foot` (a flat-bottomed
block with a box-shaped arch tunnel, not used by the benchmark) with its
toes bent up 30-45 degrees has the right foot's floor tipped 4-6 degrees,
the heel 9-11 mm below it; the left foot is right. The realistic
`curved_foot` stays within 0.2 degrees up to 50 degrees (1.5 at 55, left).
Before the 29 Oct change that runs the floor's length on to the toe tips,
the block read about 2 mm low at 30-35 degrees. Not changed: the block's
square edges and tunnel are unlike a sole; noted in case a real scan shows
it.

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

### Rebuilding the phone's scan on the Mac: tried, worse

The phone builds Object Capture's "reduced" detail. The same scan's 46
photos (and, separately, its Checkpoint folder: the phone's own session
data) were copied off the phone and rebuilt on the Mac with
`ios/tools/reconstruct-mac.swift` (22 Oct 2026, right sole-up scan of
21 Oct, in a sock). Width of the foot below 30 mm, at 10 / 20 / 40 / 60 /
80% of its length from the heel, after the same preparation as Make insole:

| model | vertices | widths, mm | length, mm |
|---|---|---|---|
| phone (reduced, on the phone) | 4,626 | 75 / 86 / 90 / 88 / 80 | 244.3 |
| Mac, full | 12,233 | 9 / 45 / 77 / 80 / 70 | 243.3 |
| Mac, raw | 11,785 | 19 / 42 / 58 / 75 / 67 | 242.7 |
| Mac, reduced, with the phone's checkpoint | 11,551 | 22 / 49 / 52 / 59 / 51 | 246.9 |
| Mac, full, with the phone's checkpoint | 11,482 | 9 / 44 / 56 / 74 / 72 | 232.1 |
| Mac, full, object masking off | 11,270 | 18 / 28 / 34 / 43 / 52 | 215.2 |

Every Mac rebuild came out narrower (ball 73-80 mm against 88), and the
widths near the back above are misleading: re-measured (24 Oct) on the
full and raw rebuilds, the back tenth of each scan sits 23-57 mm above the
floor, against under 5 mm on the phone's. The underside of the heel wasn't
rebuilt, so the furthest-back part left is the ankle, off the floor, and
the preparation rested the rest tipped 10-13 degrees. Either way the
phone's own model is the most complete of the six, and stays the one
insoles are made from. Make insole now catches this case: if the back 5%
of a prepared scan is more than 15 mm above the floor it warns THE HEEL MAY
BE MISSING (phone: 1.2 mm, no warning; the two Mac rebuilds: 46.3 and
48.4 mm, warned; none of the 58 synthetic benchmark cases). Whether the
phone's model is the right *size* is a separate question: measure the foot
(see below).

### Catching an incomplete scan (24 Oct)

`scripts/second_look_eval.py` takes the first real sole scan as it is, the
same scan with a known part cut out (the last 15% of the toes, the heel's
underside, one side below 25 mm, a patch under the arch), and the two Mac
rebuilds that lost the heel's underside, runs each through Make insole's
preparation, and scores footscan's own warnings against what each case is
known to be. Before this round they caught 5 of 7: a hole under the arch
read as sole resting on the floor (the arch silently flat), and the cut-off
toes passed. Two checks since, for the sole scans (knee bent, legs flat):

- **OF THE SOLE IS A HOLE**: where a ray up from the floor finds the inside
  of the foot more than 3 mm up instead of the sole, the sole is missing;
  over 5% of the footprint, a warning (a foot standing on the floor has no
  sole in its scan by design, so not for that kind).
- **THE SCAN IS TORN NEAR THE FLOOR**: Object Capture's models are closed,
  so open edges within 40 mm of the floor are a missing part. The real scan
  has none (its only opening is the leg's cut, higher up); the damaged ones
  190-593 mm; warning over 50 mm.

Now 7 of 7, no warning on the real scan, and in the 58 synthetic benchmark
cases only the two with holes cut in them warn. The limit: Object Capture
usually closes a gap itself with guessed surface, which no open-edge or
hole check can see; the heel check caught the one such case so far.

The same script can also ask Claude (`claude-opus-5-5`) to look at four
rendered views of each case and say only whether the scan looks complete,
to see whether an advisory "second look" would catch anything these checks
don't. Not run yet: it needs an API key or `ant auth login`. Footscan's own
checks already get every case it has, so it would have to find a kind of
flaw nobody has thought to check for to be worth adding.

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
