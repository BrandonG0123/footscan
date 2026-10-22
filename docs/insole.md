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
  ceiling, foot relaxed; someone else scans over the sole and down the
  sides. Nothing presses on the foot, so the arch is as high as it is
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

A sole-up scan is turned over (the phone knows which way was up), cut
below the bed and rested on its heel and ball: the floor is the face of
the scan's convex hull right under its centre, so a foot tipped by its own
relaxed ankle lands flat. A foam print is cut out of the box (below the
foam's flat top, inside its outline, facing up), its triangles turned to
face down the way the sole did, and rested the same way; the heel is its
narrower end. Both add warnings if less than 60% of the sole was scanned,
if the arch comes out on the outer side ("is this really the right foot?")
or, for a print, if the two ends are almost the same width.

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
