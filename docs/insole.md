# First-fit insole (Phase 4, part 1)

> Not a medical device. See [SAFETY.md](SAFETY.md). A first fit has **no
> posting and no correction**; it is for checking fit and walking-only
> break-in. Nothing is worn for sport until a clinician signs the summary
> sheet this step writes.

```bash
.venv/bin/footscan insole scan.ply --foot right -o reports/my-insole
```

The scan must be in the mat frame (z up, floor at z = 0), as footscan's own
reconstructions are; mm, cm or m are detected. It writes:

| File | What |
|---|---|
| `right-insole.3mf` | Open in Bambu Studio (or Orca, Prusa). Millimetres, one closed solid, already flat on the bed and centred; turned to the diagonal if it's too long to lie straight. Geometry only: you choose printer and filament settings. |
| `right-insole.stl` | The same shape, for other tools. |
| `right-insole-summary.html` | The clinician summary sheet (SAFETY.md requirement 1): device parameters (posting 0°), scan measurements, warnings, sign-off block, break-in and stop rule. Print it. |
| `print-notes.txt` | Starting points for TPU. Untested on this design (that's Phase 5). |
| `right-insole.json` | Everything above as data. |

`--length 270` lengthens the insole to a shoe's insole length (mm): only the
flat front reaches further, the shape under the heel, arch and ball stays
where the foot is, and it's never made shorter than the foot. In the studio
it's the *Shoe insole length* box on the scan's card.

`--shoe shoe-insole.obj` goes further: the insole takes the outline of the
shoe's own insole, from a scan of it lying flat on a table (the app's
*Shoe's insole* card; in the studio, *Fit to the shoe's insole* on the
scan's card). How (`src/footscan/recon/shoe.py`):

- **Reading the scan.** If the model kept the table, it's cut away (the
  lowest big level surface whose cut leaves something insole-shaped above
  it); the outline is then everything seen from above, heel (the narrower
  end) at the back. On synthetic insoles it comes out within 0.8 mm of the
  true outline everywhere, 0.3 mm outside it on average.
- **Which shoe.** A shoe's last curves in toward the big toe, so the toe
  end lies to the big-toe side of the line from the heel's middle through
  the ball's. An insole from the other shoe, or scanned upside down, is the
  mirror image of the one wanted: it's mirrored back, and the sheet says so.
  A straight shoe (toe end within 4 mm of the line) is used as scanned,
  with a warning to check.
- **Placing it.** Against the foot's outline within 10 mm of the floor,
  which is what stands on an insole (higher up, the heel bulges out over it,
  inside the shoe's counter: on the first real scan, 71 mm across near the
  floor against 86 mm at 30 mm up). The shoe's heel goes 3 mm behind the
  foot's, then it's turned (up to 10 degrees) and slid sideways (up to 8 mm)
  to where the least of the foot hangs over its edge.
- **Inside it,** the top is made exactly as without it (the same grid
  points, so the same heights to the hundredth of a millimetre). Where the
  foot is wider than the shoe's insole, the insole stops at the shoe's edge,
  and a warning says where and by how much; the heel cup wall only exists
  where the shoe's outline leaves room for it outside the heel.

Not yet tried on a real shoe's insole.

## From the iPhone app

The insole is the shape of the bottom of the foot, so the app's first
scans are the two that show it:

- **Right / Left sole**: lie face down, bend the knee so the sole faces the
  ceiling, ankle relaxed with the ball of the foot level; someone else scans
  over the sole and down the sides, two laps. What goes wrong and how to
  avoid it: [scanning-guide.md](scanning-guide.md). Nothing presses on the foot, so the arch is as high as it is
  unloaded (the generator's 20 mm arch cap still applies). Available today,
  no equipment.
- **Right / Left sole, legs flat**: the same, but lying with both legs flat
  on the bed and the feet just past its end. The bed holds the leg, so the
  foot may hold stiller; the helper sweeps a half circle under and behind
  the foot (the bed blocks the rest), and it needs 40 photos. Which pose
  scans better is measured, not assumed: see *Comparing two scans* below.
- **Right / Left foam print**: press the foot into a foam impression box
  while seated, lift it out, scan the print from all round with the box on
  a table. Partly loaded, the way many orthotic labs take a foot's shape,
  and the print holds still for as long as the scan takes. The studio
  reports the print's depth (`print_deepest_mm`), so it can be checked with
  calipers at the heel.

*Whole right / left foot* (seated, foot on the floor) is still there for
size and shape, but it can't see the sole (see the warning below).

Scan with Footscan on the iPhone, send it to the studio,
then in the studio's **Research library** press **Make insole** on that
scan's card. It shows the size, the arch fill and any warnings, with
buttons for the 3MF, the summary sheet, the print notes and an STL.

**3D preview** (the card's *3D preview* button, `studio/insole.html`): the
insole coloured by how much it fills under the foot (light where flat, deep
teal at the 20 mm cap), with the scanned sole it was made from, which can be
lifted off to compare the two shapes. The summary sheet says how the foot
was captured (scan kind, load on the foot, scan noise, how the floor was
set) and, for a foam print, the scanned depth with a box for the calipers.

Behind the button (`src/footscan/recon/foot_prep.py`):

1. **Level**: the app's Y-up model becomes Z-up. If the scan kept the floor,
   the floor is found, levelled and cut away; if not, the lowest scanned
   points stand in for it (the arch then comes out about 0.5 mm low).
2. **Densify**: the phone's quick model is coarse (points ~5 mm apart); its
   triangles are split to 2 mm (adds points, not shape).
3. **Point the foot**: the footprint's length gives the line, the leg (or,
   without one, the taller ankle end) marks the heel.
4. **Trim the leg** above 70 mm and close the cut, so the shin can't be
   taken for foot and the cut isn't read as holes.

Two loud warnings say when not to print:
- **DOESN'T LOOK LIKE A FOOT ON THE FLOOR**: the part touching the floor
  isn't foot-sized or foot-shaped (adult: about 180-330 mm long, 0.28-0.50
  as wide as long).
- **THE SOLE MAY BE INVENTED**: the model has a surface under almost all
  of the footprint. A foot resting on the floor hides most of its sole, and
  Object Capture closes a model's bottom by itself, so that underside is
  probably guessed. The arch shape can't be trusted.

Two more, for the sole scans:
- **THE FOREFOOT WAS ROLLED ONTO ONE EDGE**: once the floor is set, one side
  of the ball of the foot sits more than 5 mm above the other. Standing,
  both rest on the floor, so the insole would fill under the raised side: a
  wedge. The first real left sole-up scan had 8.6 mm (its right pair 1.2 mm).
  A sole scan this rolled is also refused when it arrives (see below).
- A legs-flat scan with **both feet** in it keeps only the chosen foot: the
  two are cut apart down the gap between the shins, and the result says so.
  Where the feet touched, the inner side is missing, which the torn-scan
  warning reports. When they touched, that tear means the scan is refused
  on arrival (the side that lay against the other foot was never scanned);
  only feet that were apart in the scan get through to Make insole.

A sole-up scan is turned over (the phone knows which way was up), cut
below the bed and rested on its heel and ball: the floor is the face of
the scan's convex hull right under its centre, so a foot tipped by its own
relaxed ankle lands flat. Relaxed in the air, the toes hang up off the
line of the sole (gravity pulls them toward the top of the foot); standing,
they lie flat. Hung up, they look shorter from above and their tips can rise
past the 30 mm the outline is read at, so the outline comes out short
(SYNTHETIC, the 250 mm test foot with its toes bent up 35 degrees: 14.6-20.6
mm short, depending on where they bend). So a sole scan's toes are laid flat
first (`_lay_toes_flat`): from the last point past the ball still on the
floor, the toes' angle is read off the underside, and the front of the foot
is turned down by it round a 10 mm joint just behind that point (toes bend at
their joints, not at the skin; 10 mm is a judgment, to be set from a ruler
measurement). Laid flat, the same foot reads -4.1 to +6.6 mm at 35 degrees.
The table of runs is beside `TOES_JOINT_UP_MM` in `foot_prep.py`; the
decision is recorded as `toes_laid_flat` (angle, pivot, joint, length before
and after). A front rising more than 60 degrees isn't laid flat and gets a
warning. With the toes hung up, the floor's heel and ball are also placed
along the whole underside, toes included: along the contact areas alone,
which end at the ball, the "ball" was the arch and tipped the floor
(SYNTHETIC, toes bent up 20 degrees: 1.6 degrees across the left foot).
A foam print is cut out of the box (below the
foam's flat top, inside its outline, facing up), its triangles turned to
face down the way the sole did, and rested the same way; the heel is its
narrower end. Both add warnings if less than 60% of the sole was scanned,
if the arch comes out on the outer side ("is this really the right foot?")
or, for a print, if the two ends are almost the same width.

### Refused on arrival: a sole scan missing its toes or heel

A sole scan (*sole* or *legs flat*) that's missing a whole end of the foot
never gets as far as Make insole: the studio checks it the moment it arrives
(`src/footscan/recon/completeness.py`, called from the model upload, so the
iPhone app and Import 3D both go through it), keeps nothing, and answers with
what's missing and how to scan again. (A new model sent to a capture that
already had one leaves the earlier model, and what was made from it, as it
was.) The phone shows that on the scan's
page, marks the scan *Scan again*, and never sends it again (not even with
"send automatically" on). What refuses a scan:

- **The toes are missing**: seen from above (the insole outline), a foot
  rounds off to its toes. 5 mm in from the front, the outline is only a third
  as wide as the ball of the foot on the synthetic test feet (0.33); cut off
  25-50 mm short, it's square, 0.62-0.84 (15 mm short, 0.54: left to the
  length check below). Over 0.6 is refused.
- **The heel is cut off**: the same at the back, against the heel's own
  width (0.47 whole on the test feet, 0.66-0.80 cut 8-30 mm short). Over 0.65
  is refused.
- **The heel is missing** or **the scan is torn near the floor**: the two
  older checks below (the back of the scan far above the floor; open edges
  near the floor), which only warned before.
- **The forefoot was rolled onto one edge** (more than 5 mm between the two
  sides of the ball once the floor is set): the insole would put a wedge
  under the raised side, and a first fit has no posting.
- **Much shorter than another scan**: more than 12 mm shorter than the
  newest kept sole scan of the other foot, or of the same foot. Object
  Capture closes a gap it never saw with a guessed surface, and an end that
  curled or was cut off only a little doesn't look square, but it does make
  the foot short. The case that started this: the left sole-up scan
  `LIDAR_nwb_relaxed_L_20261027-151404-89df` made a 227.0 x 86.3 mm
  outline against 246.4 x 102.3 mm for the right foot's scan that afternoon,
  and passed every check before this one.
- **Not one whole foot**: the outline's length or width/length is outside an
  adult foot's (180-330 mm, 0.28-0.50), e.g. both feet caught together.
- **The studio couldn't prepare it at all** (no foot found on the floor).

The end-shape thresholds were set on SYNTHETIC scans (tests/synth.py's
`shaped_foot` and `curved_foot` with an end cut off and closed over, as
sole-up scans in metres, Y up), not on real feet; the numbers above are from
those runs.

First run on real scans (`scripts/check_completeness.py` on the studio's
captures, 2026-10-28): the right sole-up scan
`LIDAR_nwb_relaxed_R_20261027-151404-2349` is kept (244.1 x 89.6 mm, toe end
0.23, heel end 0.48). The left sole-up scan 89df and its duplicate 537f
(228.2 x 79.8 mm, toe end 0.46, heel end 0.59, toe tip 17.8 mm up) are
refused, by the length check: 16 mm shorter than 2349. Their ends weren't
square enough for the shape checks. The legs-flat scan
`LIDAR_nwb_relaxed_L_20261027-151815-2190`, which caught both feet merged,
read 264.9 x 254.3 mm and was kept by that first version; the *not one whole
foot* check was added for it. Four real scans: the thresholds aren't proven
by them.
Those lengths predate laying hung-up toes flat (29 Oct): 89df's toe tip was
17.8 mm up, so it may read longer now; not yet rerun. Saved measures from
before are measured again before a length comparison, and a sole scan's
insole made before then shows as out of date until it's made again
(`foot_prep.prep_version(kind)`, one per scan kind: changed again on 30 Oct
for both sole kinds, and legs-flat scans also for how one leg is read).

A standing foot and a foam print aren't checked. Make insole on a
scan kept before this check still lists the same problems as warnings. To see
what the check makes of the scans already in the studio, without changing
them: `.venv/bin/python scripts/check_completeness.py`.

Before either is rested, scan noise is measured and, if there is any, blurred
out (over about 4 mm), and on a noisy scan the floor is set from smooth fits
under the heel and both sides of the ball of the foot rather than from the
noise's lowest specks. How well all this reads a sole, clean and noisy, and
how that compares with published foot scanners: [benchmark.md](benchmark.md).

Checked on synthetic feet with a 12 mm arch (tests/test_insole.py): sole
up, tipped 25 degrees, with a bed in the scan, and a print pressed 30 mm
into a foam block on a table with the box 1.5 degrees off level, each in
metres, Y up, turned. Both give 11.0 mm of fill (12 minus the 1 mm relief)
on the inner side for each foot, the tip and tilt are recovered (25.0 and
1.5 degrees) and the print's depth reads 30.0 mm. Not yet checked on a
real scan of either kind.

Checked on the phone's real shoe scan: both warnings fire (its floor
contact is 165 x 48 mm, and its whole underside is closed), as they should
for something that isn't a foot.

## Comparing two scans

```bash
.venv/bin/footscan compare scan-1.obj scan-2.obj --foot right --kind sole_up --kind-b sole_hanging
```

(or *Compare scans* in the research library). Each scan is prepared exactly
as Make insole prepares it; the two soles' height maps are lined up flat on
the table (turn and slide only, heights and tilts left as they are) and
compared at every point both scans saw, more than 6 mm in from the edge:
typical and 95% height difference, bias, arch top and outline gap, in mm.
Two scans of the same foot in the same pose that agree closely mean the
foot held still; it's how to choose between the knee-bent and legs-flat
poses, and the same repeat-scan measure foot-scanner makers publish
([benchmark.md](benchmark.md)).

## How the shape is made

The bottom of the foot is the input that matters: the insole's top surface
*is* the scanned underside of the foot, set 1 mm below it. The generator
looks straight up from under the floor every 0.5 mm. Where the scan saw the
sole (a downward-facing surface), its height is used; where it didn't (the
sole was pressed on the mat, or a hole), the insole is flat. **Unseen sole is
never guessed upward**, and the report says how much of the sole, and of the
arch, the scan actually saw. If it saw almost none of the arch, it warns:
scan again with a low lap aimed under the inner arch.

Then: light smoothing that may only lower the surface; safety caps (20 mm
arch fill, 12 mm heel); the outline (the foot's silhouette + 2 mm; round
the heel, the heel as it is at the cup's 12 mm height + 3 mm, kept small
because a shoe's heel counter is firm); a heel cup wall *outside* the
scanned heel, rising over 2.5 mm, so it holds without pressing in. The heel
is measured at the cup's height because heels bulge out higher up: on the
first real scan, 74 mm across at 12 mm and 86 mm at 30 mm. Measured at
30 mm, that insole's heel came out 92.6 mm wide with its cup wall standing
about 6 mm off the heel each side; measured at 12 mm, 80.2 mm, the wall
against the heel; a flat 3 mm base tapering to 2 mm at the toes. For a sole-up or
legs-flat scan, no fill under the toes from 78% of the length on (a relaxed
unloaded foot curls its toes; standing, they lie flat).

To slide into a shoe: beyond the heel, the base thins toward the outline's
edge to 1.2 mm over the last 4 mm (a smooth S-curve, the distance from the
edge measured at every grid point), so the edge tucks under a shoe's
curving sides instead of riding up them. The heel keeps its full base.

On the bed: the outline is turned in 0.5 degree steps to find the angle
where it fits the 256 mm bed with the most room to spare, and the 3MF is
placed at that angle. Full detail in `src/footscan/insole.py`.

## What's been checked

- Synthetic feet only (`tests/test_insole.py`): on a test foot with a 12 mm
  arch, the insole's arch comes out at exactly 11 mm (12 minus the 1 mm
  relief), on the inner side only; flat where the foot rests; the heel wall
  only outside the heel; left is the mirror of right; a foot whose arch the
  scan can't see gives a flat insole and a warning; posting is refused; the
  3MF is millimetres, one closed object, on the bed. Validated with the
  official 3MF library (lib3mf) in strict mode: no warnings, manifold.
- **From a real foot: one so far** (a right sole-up scan, 21 Oct 2026). Made,
  opened in Bambu Studio, not yet printed or worn. Its accuracy against the
  real foot hasn't been measured (see benchmark.md, *Measuring it end to
  end*).
- Bambu Studio's command-line mode crashed on every file tried, including a
  plain cube, so the open-in-Bambu check is by hand: open the 3MF.
