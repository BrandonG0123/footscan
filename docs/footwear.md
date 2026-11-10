# A printed clog with the footbed built in

> Not a medical device, and not sports equipment. See [SAFETY.md](SAFETY.md):
> everything there applies to a shoe exactly as it does to an insole. The
> footbed is a **first fit** (no posting, no correction). The shoe is for
> **walking and casual wear only**: not tennis, not running, not any sport,
> whoever signs the sheet. Break-in and the stop rule are the insole's.
>
> **Untested.** No shoe from this design has been printed or worn yet. Every
> thickness, height and allowance below is a starting judgment, and its
> grip, wear and strength are unknown.

A slip-on clog, one print per shoe, made for one foot:

```bash
# sized by a ruler, with the foot's own footbed from its sole scan
.venv/bin/footscan footwear --foot right --scan sole.ply --length 260 --width 97 -o reports/my-clog
# ruler numbers alone: the same shoe with a flat footbed
.venv/bin/footscan footwear --foot right --length 260 --width 97 -o reports/my-clog
```

`--scan` takes a scan in the mat frame, as `footscan insole` does. For a
model from the iPhone app say what it is, as the studio does:
`--kind sole_up` (or `sole_hanging`, `impression`, `foot`), and `--up z` if
its up axis isn't y. `--pair` also writes the other foot's shoe as this
one's mirror image (see *A pair from one foot*). It writes, per shoe:

| File | What |
|---|---|
| `right-clog.3mf` | Open in Bambu Studio (or Orca, Prusa). Millimetres, one closed solid, sole down on the bed, turned to the angle that fits. Geometry only: you choose printer and filament settings. |
| `right-clog.stl` | The same shape, for other tools. |
| `right-clog-summary.html` | The summary sheet: what the shoe was made to, which numbers are a standard shape rather than this foot, the footbed's first-fit parameters (posting 0°), warnings, the clinician's sign-off block, break-in and stop rule. Print it. |
| `right-clog-print-notes.txt` | Starting points for TPU 95A. Untested. |
| `right-clog.json` | Everything above as data. |
| `right-clog-views.png` | Six pictures on one sheet (side, three-quarter, top, sole, back, front), and one file per view. |

## What comes from the foot, and what doesn't

| | Comes from | Notes |
|---|---|---|
| Length and width | A ruler (`--length`, `--width`: heel to longest toe and across the ball, standing), else the sole scan's own outline | The ruler wins. Until the scans' size is settled (they have read a few percent short: see benchmark.md), give the ruler numbers. |
| The footbed | The sole scan, through the insole generator | The same fill a first-fit insole has (the scanned sole less the relief, capped), as the shoe's floor. No separate insole. Without a scan the floor is flat. |
| The upper | A standard shape in that size | Like a bought shoe's. No scan of the top of the foot is asked for, so the roof heights are a table (`ROOF`), not this foot. The sheet says so. |
| Room at the sides | The sole scan's own edges | A sole scan also shows the foot's sides for the first 30 mm up. Where the foot is wider there than the standard shape (a flat foot's inner side stands out over its own footprint), the inside is let out to it, behind the toe box only, by 20 mm at most. Never made narrower. Without a scan: the standard shape. |
| The look | The style and the preferences | Never changes the inside. |

**Proportions stay a shoe's.** The inside is the foot's length plus the
fit's room past the toes, and the foot's width plus the fit's ease, but its
width is held between 0.33 and 0.42 of its length (`BALL_SHARE`). A long,
narrow foot gets a normal shoe in its length, not a long thin one, and the
sheet says how much wider than the foot that is. A foot wider than the band:
with a sole scan, the walls are let out where the scan shows the foot needs
it (across the ball too) and the sheet says so, because a shoe is never made
tighter than the foot for the sake of its looks; from ruler numbers alone it
is told the shoe may be tight.

**When the ruler and the scan disagree** about the length, the shoe is sized
by the ruler and the scan is taken to have its size wrong: the footbed is
scaled by the two lengths' ratio, the same along and across (its heights are
left alone: the fill is never made higher than the insole generator made
it), with a note of how much. More than 15% apart is refused: that isn't the
same foot in millimetres. This is a stopgap while the scans' size is being
settled, and it means the arch may sit a few millimetres off.

The ruler's width sets the shoe's width and nothing else. It is compared
with the scan's width across the ball: a standing foot spreads wider than
one scanned resting in the air, so up to 6% between them is not mentioned,
more is noted, and more than 15% is refused. Without a ruler's width the
scan's own is used, scaled with the footbed: a scan 5% short, given only a
ruler's length, is sized for a foot 5% wider than it reads too.

## Preferences

| | Choices | What it changes |
|---|---|---|
| `--style` | `vent`: rows of small diamond windows, a mid-height sole with two lines. `stream`: long slim windows, a thick flared sole with three lines. `stone`: a closed upper, a slim plain sole. | The outside only: windows, sole thickness, how far the sole stands out, its lines. |
| `--fit` | `snug` (8 mm past the toes, no ease), `regular` (12 mm, 2 mm wider), `roomy` (15 mm, 5 mm wider, 3 mm more roof) | The inside's size. |
| `--sock` | mm | Room for a sock thicker than the one the foot was measured in: that much longer and higher, twice that wider. |
| `--toe` | `round`, `square`, `tapered` | The front of the outline, from 88% of the length on. |
| `--sole` | mm under the ball (8 to 40) | Overrides the style's. The heel sits 6 mm higher, front to back only. |
| `--openness` | 0 to 0.5 | Share of the patterned area cut away. 0 closes the upper. |
| `--cushion` | `soft`, `medium`, `firm` | Nothing in the shape: the infill the print notes suggest for the sole (15, 20, 25%). |

Colour is the spool that's loaded.

## A pair from one foot

`--pair` (or `footwear.mirrored`) writes the other foot's shoe as the mirror
image of this one. Its footbed is then the *first* foot's: two feet are not
mirror images of each other, and their arches differ. Its sheet and its
warnings say so first. It is for trying a pair on before the other foot has
a scan of its own, not instead of that scan.

## How the shape is made

Everything is built for a right shoe (inner side toward +y) and mirrored at
the end for a left one. In plain words (`src/footscan/footwear.py` has the
same steps with the numbers):

1. **The floor outline.** The plan shape of the inside at floor level, from
   a table of half-widths at shares of the length (heel about 0.76 as wide
   as the ball, the inner side nearly straight, the toe end toward the big
   toe), stretched to this foot's length and width. The curve is drawn
   through the *squares* of the half-widths, which is what rounds the two
   ends: a width whose square falls to zero in a straight line closes like
   a circle.
2. **The inside.** Slices across the shoe, one every millimetre or so. Each
   starts at the floor outline's two edges, leans out a few millimetres on
   the way up (a foot is widest a little above the floor; a heel bulges out
   over its own footprint), then rounds over to the roof like a squashed
   circle. Toward the two ends each slice gets lower as well as narrower,
   which rounds the heel and the toe cap. The floor slopes gently from heel
   to ball.
3. **The outside.** The same slices, the upper's thickness further out, and
   solid down to the ground: that part is the sole. Its side stands out a
   little at the ground and leans in to a waist at the footbed's level; the
   upper leans back out from there. The sole's lines are shallow dips drawn
   into the same slices. Where the roof slopes (down from the instep to the
   toes) the outside is raised a little more, so the upper is its thickness
   measured square to its surface.
4. **Standing the foot in the shoe.** What stands on the floor is the foot
   within 10 mm of it (a heel, and a flat foot's inner side, bulge out
   higher up), with the hollow under the arch bridged straight across. The
   floor's outline is placed round that exactly as a shoe's insole outline
   is placed round a foot (`recon/shoe.py`): turned (up to 10 degrees) and
   slid sideways (up to 8 mm) to where the least of it hangs over. The back
   of the whole heel, which reaches further back above the floor than on
   it, goes against the back of the inside.
5. **Letting out.** Every millimetre along, on each side: how far does
   everything the scan shows of the foot (up to 30 mm above the floor) stand
   outside the standard shape's widest point there, plus the fit's ease?
   That side's wall leans out that much more, up to 20 mm, smoothed along
   the shoe so it stays a fair curve, and fading to nothing through the toe
   box (from 75% to 88% of the length), which stays the standard shape. The
   floor's outline doesn't move. The outside moves out with the wall from
   the ground up, so the sole stands under it and what is under the footbed
   there is solid. Where the foot is not wider, nothing changes: the shoe is
   never narrower than the standard shape. What couldn't be let out (past
   the limit, or in the toe box) is a warning on the sheet.
6. **The footbed.** The insole generator's height map, laid on the floor
   where the foot stands. Three things are done to it, none of which adds
   height under the foot:
   - From 3 mm inside the foot's edge outward, the surface carries on level
     to the wall, so there is no groove beside the foot. The insole's own
     surface dips in those last millimetres (its smoothing blends in the
     bare floor beside the foot), and that dip is not built in.
   - Where the insole's two caps meet (12 mm round the heel, 20 mm under the
     arch) its surface can step. In a shoe that step is a ledge inside the
     wall, so the cap climbs from one to the other over the next 15% of the
     length. That only lowers the surface.
   - For a ruler's length, scaled in plan (see above).

   The relief, the caps and "never guess unseen sole upward" are all the
   insole generator's.
7. **Hollowing.** The inside, down to the footbed's surface and no further,
   is subtracted from the outside.
8. **The opening.** Everything above a curve is cut away: it starts 26 mm
   above the floor behind the heel and climbs, slowly then faster, to the
   top of the instep half way along. A low lip round the heel, a closed
   front. The footbed's heel cup stands up to 12 mm inside that, so the
   curve is checked against the footbed all along: less than 12 mm above
   it anywhere (a lower rim, or a deeper heel cup) is refused, since the
   rim would hold too little of the heel and the cut would take the top
   off the footbed. The sheet gives the least height over the footbed.
9. **The pattern.** Diamond windows through the upper, each pushed straight
   out of the surface, in rows that follow the roof's curve, every other row
   shifted half a step. None in the toe cap, round the heel, in the sole,
   near the opening's edge (5 mm), or where the footbed stands behind the
   wall. At least 2.6 mm of material between windows.
10. **Tread.** Shallow V-shaped grooves across the bottom inside a solid rim.
11. **Tidying.** Cutting solids with each other leaves edges a few millionths
    of a millimetre long; points closer than 0.002 mm are joined, so the file
    is still one closed surface after a slicer rounds its numbers.

The inside's length is measured where a foot uses it: between where the
back wall stands as high as a heel reaches back furthest and where the front
wall stands as high as the toes reach forward furthest. The floor outline is
drawn about 1.5 mm longer than that, for what the rounded ends take off.

## What is a judgment

None of these is measured from a last, a worn shoe or a printed trial:

- The outline's proportions (`LAST_STATIONS`: the generic insole outline's
  table) and the three toe shapes.
- The roof (`ROOF`): for a 272 mm inside, 65 mm over the instep where the
  opening ends, 41 mm over the ball, 35 mm over the toes.
- The lean and the height of the widest point (`BULGE`). The heel's numbers
  follow the one real foot measured (insole.md: 74 mm across at 12 mm up,
  86 mm at 30 mm up); the ball's and the toes' are judgments.
- The fits (`FIT`), the sole thicknesses, the 6 mm heel-to-ball drop, the
  2.4 mm upper, the 26 mm heel rim and the 12 mm it must stand over the
  footbed (`HEEL_LIP_MIN_MM`), where the opening ends.
- How far a side may be let out (`LET_OUT_MAX_MM`, 20 mm), where the toe
  box begins (`LET_OUT_UNTIL`), and how the sole follows a let-out wall.
- How far inside the foot's edge the footbed stops following the insole's
  surface (`FOOTBED_EDGE_MM`, 3 mm: twice the insole's smoothing width).
- The window sizes and the 2.6 mm between them.
- Every print setting.

## Printing

Starting points only (`<name>-print-notes.txt` has them per shoe): TPU 95A,
dried; sole down, scale 100%; 3 walls; gyroid infill at the cushioning's
percentage; slow.

- **Supports.** The roof over the toes and the instep hangs over empty
  space, so it will very likely need supports inside, pulled out through the
  opening. Whether a piece of the roof prints cleanly is the first thing to
  try, before a whole shoe.
- **The bed.** A 256 mm bed takes a shoe up to about 300 mm long, turned
  cornerwise. On SYNTHETIC generated shapes (regular fit, width 0.375 of
  the length), the shoe for a 285 mm foot fits (`vent`, `stone`; 280 mm for `stream`) and
  the one for a 290 mm foot doesn't; the report and the sheet say when it
  doesn't.
- **Before a whole shoe:** trial pieces (a toe cap, a swatch of the pattern,
  a block of the sole at each infill). Not generated yet.

## What's been checked

Everything in this list is SYNTHETIC: generated shapes and synthetic feet
(`tests/test_footwear.py`) with known answers. The one real sole scan put
through the generator has its own section below. Nothing here is from a
printer or a worn shoe.

- One closed solid, flat on its sole, in one piece; no two points of the
  surface closer than the weld; an STL of it reads back closed.
- The inside is the foot plus the fit's room, in the report and probed in
  the solid itself (rays from inside to the walls): within 1 mm in length
  and width for all three fits of a 260 x 97 mm foot.
- On the SYNTHETIC block foot (a 12 mm arch tunnel under the inner side),
  the shoe's floor stands 11.0 mm above a flat one under the tunnel (12 less
  the 1 mm relief), within 0.1 mm, and within 0.05 mm of flat under the
  heel, the ball, the toes and the whole outer side. Never above the
  insole's own fill.
- The same block with a 10 mm block standing out of its inner side above
  the floor: it is stood in the shoe exactly where the plain one is, the
  inner wall beside the bulge is 10 mm further out (within 0.7 mm) and the
  outer wall where it was (within 0.05 mm), and the outside is 10 mm further
  out there from the ground up. With a 40 mm bulge the inside is let out by
  the 20 mm limit and the sheet says where the foot is still wider.
- A foot narrower than the standard shape (the block, 90 mm across, in a
  shoe sized for 98 mm): across the ball the walls stand where the standard
  shape's do, to 0.05 mm. Never narrower anywhere.
- A block standing 4 mm out of the back of the heel above the floor: the
  foot counts as 244 mm long, and stands with that bulge against the back.
- A ruler length 10% over the scan's: the block's patch of fill comes out
  10% longer, 1.21 times the area, and still 11.0 mm high. A ruler length
  alone, 5% over: the shoe is sized for the block 94.5 mm across (its 90
  scaled), not 90.
- The block made 20% wider (108 mm, wider than a normal shoe's proportions
  for 240 mm): the walls are let out on both sides across the ball, and the
  sheet says that, not that it may be tight; from ruler numbers alone it
  does say it may be tight.
- The block's footbed raised 10 mm everywhere: a 12 mm rim (2 mm over it)
  is refused; the 26 mm one stands at least 12 mm over it all along. The
  footbed eases between the insole's caps where the insole's own heel zone
  says, not by a copy of its rule.
- The footbed just inside the block's edge, at it and past it is what the
  insole's surface is 3 mm in (10.85 mm, within 0.2), not the insole's dip
  at the edge (6.2 mm); a made-up insole stepping from 12 to 20 mm where its
  caps meet comes out as a slope, never more than 0.2 mm per half millimetre.
- The floor is level across at every point along it (no posting), and the
  shoe has no setting that could tilt it.
- A style changes the outside and never the inside: the three styles' walls
  stand in the same place to 0.02 mm.
- The upper's thickness on a SYNTHETIC generated 260 x 97 mm shape, from
  2,132 points spread over the inside's walls and roof to the nearest point
  of the outside: least 2.27 mm, median 2.43 mm, for 2.4 mm asked. (With
  the roof raised by the thickness straight up, before it was measured
  square to the slope: least 2.12 mm.)
- Left is the mirror of right; a mirrored pair says the second shoe is not
  from that foot's scan (or, from ruler numbers, that it is sized from the
  other foot's).
- An openness below 0 or above 0.5 is refused; one given to `stone`, which
  has no windows, is said to change nothing.
- The sheet carries NOT A MEDICAL DEVICE, walking and casual wear only, no
  posting, the standard-shape note, the untested note, the sign-off block,
  and the break-in: one paragraph in `insole.py` that both sheets print.
- Every behaviour above has a test that fails when the behaviour is taken
  out: 29 changes tried one at a time (the weld, the roof's thickness, the
  proportion band, where the foot is stood, the let-out and its limits, the
  sole under it, the footbed's height, scale, edge and caps, the level
  floor, the opening, each of the windows' keep-out rules, the sheet's
  wording), and each made a test fail. The seven tests added with the code
  review's fixes (the width a ruler length alone gives, a wide foot's note,
  the rim over the footbed, the caps' heel zone, the openness, a mirrored
  flat shoe, the one break-in paragraph) each failed on the code before.
- Two SYNTHETIC sweeps outside the test suite. 182 generated shoes from
  ruler numbers (feet 180 to 330 mm long in 6 mm steps, widths 0.34 to
  0.40 of the length, seven combinations of style, fit and toe, left and right, some with the
  pattern 0.45 open): all 182 came out as one closed solid with the inside
  at the asked length (run before the let-out was added; ruler-only shapes
  have none). And 63 shoes on synthetic scanned feet (the block foot plain,
  with an inner bulge of 10 and 16 mm and with a heel bulge, the curved
  foot, left and right; each as scanned and with a ruler length 10% under
  and 7% over the scan's; three combinations of style, fit and toe): all 63
  came out as one closed solid, the most let out being the 20 mm limit.

### The first real scan

Right sole scan 2349 (`LIDAR_nwb_relaxed_R_20261027-151404-2349`: a sole-up
iPhone model, the foot resting in the air), sized by ruler at 260 x 97 mm
standing, regular fit. Generated, looked at, not printed:

- The scan reads the foot 244.0 mm long, so its footbed was scaled +6.6% in
  plan. It reads 89.6 mm across the ball; scaled, 95.5 mm against the
  ruler's 97.
- Stood by its sole (turned 1 degree, slid 1.75 mm), the foot's whole
  outline (everything under 30 mm) is wider than the standard shape along
  its inner side: by more than 5 mm from 10% to 57% of the length, 15.9 mm
  at most (35% along). On its outer side it is nowhere wider. It is a flat
  foot: its inner side leans out over its own footprint. The inner wall was
  let out by up to 16.9 mm (the 1 mm of ease included); nothing was left
  hanging over. The first version of this module stood the foot by its
  whole outline in the standard shape, and reported the same scan 10.3 mm
  wider than the inside at the arch's inner side.
- The footbed inside the shoe is 19.25 mm at its highest (under the arch at
  the inner wall; the insole's cap there is 20 mm) and 12 mm round the heel
  (its cap). The opening's edge stands at least 14.0 mm above it, behind
  the heel (the 26 mm rim less the heel cup).
- All three styles came out closed and fit a 256 mm bed turned cornerwise:
  `stone` 278.3 x 112.9 x 84.3 mm, `vent` 278.3 x 115.9 x 87.3 mm, `stream`
  278.3 x 120.9 x 93.3 mm (the standard shape in that size is 103.8, 106.8
  and 111.8 mm wide).

One real foot. Whether a wall let out this way sits well against that foot,
and whether the footbed's shelf along the inner side is comfortable to
stand on, are for the first print to answer.

## Not done yet

- Print trials, and the settings and thicknesses they will correct.
- The studio: a *Make shoe* button, the preferences, a 3-D preview, and a
  plain description turned into these settings.
- A left shoe from the left foot's own scan; a fit log that feeds back into
  the allowances.
- A rolled edge round the opening, toe spring, other printers and beds, a
  second shoe shape (a closed-heel sneaker).
