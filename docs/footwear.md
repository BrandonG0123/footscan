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

A slip-on clog, one print per shoe, made for one foot. From the studio, a
foot capture's **Make printed shoe** button makes it with a form and a 3-D
preview (see *In the studio*); from the command line:

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
one's mirror image (see *A pair from one foot*). `--trials` also writes
small pieces of the shoe to print first (see *Print trials*). It writes,
per shoe:

| File | What |
|---|---|
| `right-clog.3mf` | Open in Bambu Studio (or Orca, Prusa). Millimetres, one closed solid, sole down on the bed, turned to the angle that fits. Geometry only: you choose printer and filament settings. |
| `right-clog.stl` | The same shape, for other tools. |
| `right-clog-summary.html` | The summary sheet: what the shoe was made to, which numbers are a standard shape rather than this foot, the footbed's first-fit parameters (posting 0°), warnings, the clinician's sign-off block, break-in and stop rule. Print it. |
| `right-clog-print-notes.txt` | Starting points for TPU 95A. Untested. |
| `right-clog.json` | Everything above as data. |
| `right-clog-views.png` | Six pictures on one sheet (side, three-quarter, top, sole, back, front), and one file per view. |
| `right-clog-trial-*.3mf`, `right-clog-trials.txt` | With `--trials`: the print-trial pieces and their sheet. |

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

**A sole scan the studio would refuse makes no shoe.** A sole scan missing
its toes or its heel, torn open near the floor, or with its forefoot rolled
onto one edge is refused by the studio when it arrives (docs/insole.md).
Given such a scan anyway, the insole generator warns ("Don't print this
insole") and still writes its insole, a small print that is looked at on
its own. The shoe generator makes nothing (`footwear.unfit_for_a_footbed`,
the same checks in the same words): a shoe's footbed can't be taken out of
it. Under a rolled forefoot the fill is higher on the raised side, a wedge
across the shoe's floor, and a first fit has no posting; with part of the
foot missing, the footbed and the walls let out to the scan would follow a
foot that isn't all there. The refusal says what was found and what to do
on the next scan. In the studio this is for scans kept before the arrival
check existed, and a shoe made from such a scan earlier is removed, not
kept. A foam print or a whole-foot model isn't checked on arrival, and
isn't checked here.

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
a scan of its own, not instead of that scan. A pair proper is two shoes,
each made from its own foot's scan: in the studio, one from each foot's
capture ([A pair](#a-pair), below).

## In the studio

Every foot capture in the research library with a 3D model has a **Make
printed shoe** button beside *Make insole*. ("Printed", because a shoe in
the library is otherwise a bought shoe that an insole is cut to fit: the
saved shoes of [insole.md](insole.md), `footscan shoe`. Those play no part
here.) It opens a page for that capture (`/studio/clog.html`): the
preferences above as a form, the foot's two ruler numbers, a box to also cut
the print-trial pieces, and *Make shoe*. The studio makes the clog from the
capture's model, picked and prepared as *Make insole* does it
(`server.make_clog`), so the footbed is the first-fit surface that capture's
insole has, on the foot's own outline: a saved shoe's outline shapes an
insole's edge, never a clog's floor. Like everything under `/studio`, it
answers only on the studio's own computer or with the studio key.

- The form's lists and limits are the generator's own
  (`/api/footwear/options`, from `footwear_choices.options`), and what is
  sent is checked against them again (`footwear_choices.checked`): a value
  outside them, or a key that isn't one of the shoe's settings (there is no
  posting setting to send), is refused in words and nothing is made.
- The shoe is kept with its capture (`<capture>/clog/`, and a `clog` entry
  in `capture.json` with the choices it was made to, so the form opens as it
  was left). One shoe per capture: making it again replaces it, trial pieces
  included.
- Its footbed is that model's. If the model is replaced or rebuilt, or the
  way a sole scan is prepared changes, the shoe is marked stale and its
  files are refused until it is made again; a new import removes it. A
  build that fails leaves nothing to download.
- **The 3-D preview** is the shoe's own solid, not a drawing of it
  (`footwear.write_preview`). *Cut it open* shows the same solid with its
  outer half taken away by one flat upright cut along the middle of the heel
  (`footwear.opened_up`): the half on the foot's inner side is kept, so the
  footbed rising under the arch, the sole under it and the thickness of the
  upper can be seen. The cut's face has its own colour. Nothing is printed
  from the cut shape. The viewer rounds an edge over when the faces on both
  sides share their points, so the preview's points are split wherever two
  faces meet at more than 35 degrees (`PREVIEW_CREASE_DEG`, a judgment about
  a picture): the sole's lines and the windows' edges are drawn as edges.

### Describing the shoe

The page has a box for a description in the wearer's own words ("airy and
roomy, with a thick sole, for thick socks"). **No shape is made from the
words.** They are read into the same form (`footwear_choices.read`), the
page shows which words each choice was read from, and nothing is made until
*Make shoe* is pressed.

There are two readers, and the page says which one this studio uses before
anything is typed:

- **On this computer** (the default): `from_keywords` looks for known words
  (`WORDS`). It does not understand a sentence. A word with "no", "not" or
  "without" up to three words before it, in the same clause, doesn't count.
  Nothing leaves the computer.
- **By Claude**, only where the studio was started with
  `footscan serve --describe-with-claude` and has an API key
  (`ANTHROPIC_API_KEY`, and `pip install anthropic`): `from_claude` sends
  the typed words, and nothing else (no scan, no measurement, no name), to
  Anthropic's API. Its answer can only be one value per setting from the
  generator's lists, and is then held to the form's rules whatever it says:
  a value outside the limits is dropped and said; a choice is kept only if
  the words it was read from are in the description as the person wrote it
  (whole words); those words are the only text shown from the answer; and
  an amount the person gave no figure for ("a chunky sole" read as 30 mm) is
  shown as Claude's own number. If it can't be reached or declines, the
  keyword reader reads the description and the page says why.

What a description asks for that no setting gives is answered in fixed
words (`NOT_SETTINGS`), found by looking for words whichever reader read the
rest: colour is the spool; the heel's height, laces and other kinds of shoe
don't exist; grip is untested; a shoe size isn't used (the ruler is). Two of
those answers are safety rules and must not be softened:

- anything medical (flat feet, arch support, pain, a foot condition): *Not a
  medical device: no setting supports, corrects or treats anything, and none
  was changed for that. [...] see a podiatrist or another clinician.*
- any sport: *This shoe is for walking and casual wear only, not for sport:
  nothing was set for that.*

To make those two true, **a description that says the shoe is wanted for a
foot condition or for sport is not read into settings at all**
(`footwear_choices.wanted_for`), by either reader, and it is never sent to
Claude. "A firm sole and a snug fit for my flat feet" sets nothing, and so
does "Airy and roomy. I have flat feet.": the page gives the fixed answer,
says the description was not read, and leaves the form as it was. The rule
is the whole description because a wish is often written as a list ("For my
flat feet:", then a line each for a firm sole and a snug fit), and no rule
about sentences can tell which lines belong to it. It is a rule about
words, not about meaning, and it errs toward not reading:

- a sport said not to be wanted ("not for sport") is no wish for sport, and
  the description is read; a pain said not to be wanted ("so my feet don't
  hurt") is still a wish to treat a foot, and it is not;
- a description that mentions hiking socks is a description about a sport;
- the lists can't name every sport or every way to say a foot hurts, so the
  keyword reader will read a description that names a sport it has never
  heard of. Where Claude reads, it is also asked whether the description
  says the shoe is for a foot condition or for a sport, and its yes is
  enough for nothing to be set.

A request the generator refuses in its own words (a ruler length more than
15% from the scan's, a pattern that left the upper in pieces) changes
nothing: the page says why beside the button, and the shoe already made
from that model, if there is one, stays.

### What the trial pieces showed

Under the shoe, the page asks what a shoe's print-trial pieces showed: the
trial sheet's own questions, piece by piece, each with fixed answers, and a
note in the person's own words (`footwear_fit.py`,
`/api/captures/<id>/clog/fit`).

**A record is about the shoe its pieces were cut from.** Pieces take hours
to print, and the shoe on the page may have been made again meanwhile, so
the studio keeps the shoes whose trial pieces it cut (`clog_trial_shoes` in
`capture.json`, the newest 10: when each was made, its choices and its
pieces) and the form asks which one the pieces are from. Only that shoe's
own pieces are asked about (Stone has no pattern swatch); a shoe made
without trial pieces has nothing to record. Records are kept with the
capture (`clog_fit`, the newest 20) and stay when a shoe is made again or
its model is replaced. They are the fit log of what was printed, and what
went wrong is recorded as carefully as what went right
([fit-log.md](fit-log.md)).

**A shoe's suggestion is made from everything recorded about it.** Pieces
are recorded one at a time as they are printed, so the answers of all the
records about one shoe are read together, the newest answer to each
question standing. From them the studio suggests changes to that shoe's
choices, by fixed rules and no model. It suggests and changes nothing. A
suggestion is shown with the answers it came from; *Put these into the
choices* moves it into the form, and nothing is made until *Make shoe* is
pressed. (It is offered only for the shoe on the page, while that shoe
still matches its scan.) Two choices are ever suggested:

- **Cushioning:** the sole block picked (soft, medium or firm) is the
  cushioning suggested.
- **Fit:** one step along the generator's three fits. Roomier where the toe
  cap's roof pressed on the toes, the toe cap pressed on their sides, or
  the back half's walls pressed on the foot; snugger where those walls
  stood off it. Several answers one way still move it one step. Answers
  that point both ways suggest no fit and say why: a fit moves the room
  across the ball, over the toes and past them together. For the same
  reason toes that touched the end hold a snugger fit back (it would take
  room from past the toes too), though they ask for no roomier one. Past
  the roomiest or the snuggest fit there is nothing further to suggest,
  and that is said.

What is never suggested:

- **The footbed.** An answer about the heel cup or the rise under the arch
  (a ridge, or nothing felt) is kept and changes nothing. The footbed is
  the first-fit insole's surface, from the sole scan. It is not raised,
  lowered or tilted to how it felt: that would be correcting a foot by feel
  (no posting or correction: [SAFETY.md](SAFETY.md)).
- **Anything, once something hurt.** Every record has to say whether
  anything hurt, rubbed or left a mark. A yes shows the stop rule
  (SAFETY.md, requirement 2), and from then on nothing at all is suggested
  for any shoe of that capture, the cushioning included: this program does
  not adjust a shoe round a pain, and its fixed rules can't know what a
  later, painless piece has to do with an earlier pain. That holds for
  later records, for the shoe made again, and after the record itself has
  dropped off the newest 20 (`clog_fit_stop`). Nothing in the studio lifts
  it: the rule is "until reviewed", and the program can't know of a
  review. The answers are kept, and the form is still the person's to
  change.
- **Slicer settings.** A top that didn't close, strands across a window, a
  roof that sagged or tore with its supports: how the piece printed, not
  the shoe's shape. Broken bars point at the pattern's openness (a less
  open pattern leaves wider bars; Stone has no windows), with no number
  suggested, because none has been tried.
- **Length.** Toes touching the end of a toe cap is not a measure of the
  shoe's length: the piece has no heel to stand the foot against. The
  answer points back to the ruler.
- **The rim behind the heel.** Too high or too low is kept. Its height is
  not a choice on the form yet.

The note is kept as written and shown beside its record. Nothing reads it.

### A pair

A pair is two shoes, each made from its own foot's capture. A left
capture's *Make printed shoe* makes a left shoe with the left foot's own
footbed and its own walls let out (the generator turns a left foot's sole
to a right foot's layout, builds the shoe, and mirrors the result, so the
steps are the same for both feet). Where the other foot has a shoe that
still matches its scan, the page shows it under this one: the feet the two
were made for, in their reports' own numbers, how far apart those are in
length, and which of the pair's choices differ (compared as the shoes were
made: a sole left empty is the style's own, the same as that number typed
in). Where one length is a ruler's and the other a scan's it says so,
whether or not the two numbers match, and asks for both feet to be
measured by ruler before a pair is printed: the two don't always agree (on
scan 2349 the scan read 244.0 mm where the ruler read 260). *Use the other
shoe's choices* puts its style, fit, toe, cushioning, sole, pattern and
sock into this form. Each foot keeps its own ruler numbers.

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
- What a word for an amount becomes when a description is read on this
  computer (`footwear_choices.py`): "a thick sole" 24 mm, "a thin sole"
  10 mm, "very open" 38% and "less open" 18% of the patterned area, "thick
  socks" 1.5 mm. Each is shown as the reader's own number beside the
  setting. Which words mean which style, fit, toe and cushioning (`WORDS`)
  is a judgment too.
- Which answers about the trial pieces suggest another fit, and that they
  move it one step (`footwear_fit.py`). Written before any piece was
  printed.

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
- **Before a whole shoe:** the trial pieces below.

## Print trials

A whole shoe is a long print, and nothing about this design has been
printed. `--trials` (or `footwear.write_trials`) cuts small pieces out of
the finished shoe with flat cuts and nothing else changed, so each is that
part of the shoe: what goes wrong on a piece would have gone wrong on the
shoe. The cut faces are the one difference: a slicer closes them with walls
the shoe doesn't have there, which is why the sole block is pressed in the
middle of its top and not at its edges. In the order to print them:

| Piece | What it is | What it is printed to find out |
|---|---|---|
| `sole-block` | A block of the sole from under the heel (8% to 22% of the length, 14% of the length wide about the heel's middle line): the tread under it, the footbed on top, no wall. | The cushioning. Print three, at 15, 20 and 25% infill, and squeeze them. |
| `swatch` | Styles with windows only. A ring across the shoe forward of its opening: from 58% of the length, or from 10 mm past where the opening ends if that is further on; 40 mm long, or two and a half windows where that is longer; never more than a bar's width (2.6 mm) past the last window. Cut off flat 2 mm under the inside's floor at the ball of the foot and set down on that cut. | Whether the windows' edges and the bars between them print cleanly, and whether the roof prints over supports that then come out. |
| `toe-cap` | Everything forward of 70% of the length (forward of any opening the generator makes: it ends by 65% of the floor's length). | The roof over the toes, which hangs over empty space and needs supports inside; and, seated, the room past and over the toes. |
| `back-half` | Everything behind 46% of the length, or 6 mm short of where the opening ends if that is sooner, so it is cut where the shoe is still open above. Its walls are cut off level 40 mm above the heel's floor (8 mm above the rim behind the heel where that is higher), so no tall free ends are left standing at the cut. | The fit a sole scan is used for: the heel cup, the footbed under the arch, the walls where they were let out for this foot, the rim. No roof, so no supports. |

Files: `<name>-trial-<piece>.3mf` and `.stl`, `<name>-trials.txt` (what
each piece is, how to print it, what to look at), `<name>-trials.json`,
`<name>-trials.png`. With `--pair` they are the scanned foot's shoe's
only, not its mirror image's.

- **Old pieces are removed.** A piece of an earlier shoe left in the folder
  would be printed as the new one's. Writing the trials again removes the
  set written before (only the names above), and the command removes them
  once it has written a shoe again without `--trials`. `write_outputs`
  itself removes nothing: code that writes a shoe again calls
  `footwear.clear_trials` after it.
- **A piece that can't be made is left out and said.** Where a shoe has less
  than a window and a half's spacing of patterned roof forward of its
  opening there is no swatch; a piece that doesn't come out as one closed
  solid is left out. Either way the sheet has a line for it, the command
  prints a warning, and the other pieces are written. Only when no piece
  can be made is it an error.
- **Slivers.** Where two cuts meet the edge of a window they can free a
  sliver of the upper far smaller than a nozzle's line. Loose bits of less
  than 1 mm³ altogether are dropped (`TRIAL_CRUMB_MM3`): the one thing a
  piece has less of than the shoe. Anything more coming loose and the piece
  is left out.
- **A let-out wall.** Under the back half the sheet has a line for each
  stretch along which a wall was let out for this foot by a millimetre or
  more: from where to where, in millimetres from the back of the shoe, and
  by how much at most. It says whether the piece holds all of that stretch
  or shows it only as far as its cut, and then whether the most of it is in
  the piece. The shoe's report has the same under `let_out`: `at_mm`, and
  `stretches` (each `from_mm`, `to_mm`, `max_mm`, `at_mm`). A wall let out
  in two places, with the standard shape between, is two stretches.

**Trial pieces are not shoes.** They are for looking at, squeezing by hand
and trying against the foot while seated. The sheet, each 3MF's own note
and the data file say NOT A MEDICAL DEVICE and: do not stand or walk in
one. (An STL has nowhere to carry a note, and the picture is only a
picture: keep the sheet with them.) A cut-off piece of a shoe has nothing
holding it on the foot or level on the floor.

The cut positions are judgments (`TRIAL_*` in `footwear.py`), like
everything else here: each is meant to be a small piece that still shows
what it is printed for.

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
- The trial pieces: each is one closed solid standing on its flat side. The
  toe cap's volume is what trimesh's own cut of the shoe has forward of the
  same plane (to 1 part in 10,000), and 300 of its points lie on the shoe's
  surface (within 0.001 mm). The sole block's top is the footbed and
  nothing stands on it; the swatch has the shoe's windows through it (20 or
  more on `vent`, 6 or more on `stream`) and a 2 mm floor; the back half
  answers the same probes as the shoe for its footbed, both walls and the
  lip, and no slice across it is closed over (no roof).
- The trial cuts follow the shoe. A small shoe with a 12 mm drop, a 36 mm
  rim and its opening ending at 0.35 (where a cut at 46% whatever the
  opening leaves a strip of roof on the back half): the back half ends 6 mm
  short of the opening's end and is open above all along. An opening ending
  at 0.65: the swatch starts 10 mm past it, where the same shoe without
  windows is closed over, and ends a bar's width past the last window; the
  toe cap of the smallest adult size is still roofed where it is cut. A
  44 mm rim is whole in its back half. A 185 mm foot's `stream` shoe with
  the opening at 0.65 has too little patterned roof left for a swatch
  (under a window and a half's spacing), so there is none, and the sheet
  says so.
- The block foot's inner wall against the same shoe from ruler numbers
  alone: it stands out by the reported most (within 0.3 mm) at the reported
  place, and by 1 mm where the reported stretch ends (within 1.5 mm), both
  measured from the back of the shoe. A made-up outline with two 6 mm bumps
  on its inner side, 80 mm apart, is let out in two stretches of 6 mm, not
  one span.
- A piece faked to come out broken is left out with its line on the sheet,
  in the data and as a warning from the command, and the others are
  written; with every piece broken it is an error, nothing is written or
  removed, and the command still ends on its NOT A MEDICAL DEVICE line. Old
  trial files go when the trials are written again or the command writes
  the shoe again, and a file of one's own beside them stays.
- 38 changes to the trial code tried one at a time (a cut moved or left
  out or no longer following the opening or the rim, the swatch not set
  down or run past the last window, a failed piece failing them all, old
  files left, the let-out's place or wording, the not-a-shoe warning or NOT
  A MEDICAL DEVICE dropped from the notes or the files, the command's error
  handling), and each made a test fail.
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
- A third SYNTHETIC sweep, for the trial pieces: ruler-number shoes for feet
  185 to 325 mm long (width 0.373 of the length) in the three styles, with
  the opening ending at 0.35, 0.42, 0.50, 0.58 and 0.65 and the rim at 20,
  26 and 38 mm: 270 combinations. 9 were refused as shoes (a 38 mm rim as
  high as the roof on the two smallest sizes). Of the 261 built, every
  piece cut came out as one closed solid; 4 have no swatch and say why
  (`stream` on the two smallest sizes with the opening at 0.65: too little
  patterned roof left). Before slivers were dropped, the same sweep, stopped
  part way, had lost the back half of three shoes (245 mm, patterned, the
  opening at 0.35 or 0.42), each to one loose sliver of 0.004 mm³.
- The studio, on the SYNTHETIC block foot imported as the iPhone app sends
  one (`tests/test_server_clog.py`): the shoe is made to the choices sent
  and they are kept with it; its footbed's highest fill is the block's
  11 mm (within 0.6 mm); a choice outside the generator's lists and limits,
  a key that isn't a setting (posting, arch support) or a body that isn't
  an object is refused and nothing is made; the shoe goes stale when its
  model changes and is removed when the model is replaced; a build or a
  save that fails leaves nothing to download; trial pieces are there when
  asked for and gone when the shoe is made again without them; two builds
  at once leave one whole result; a phone on the Wi-Fi is refused all of it.
- The cut-open preview (`tests/test_footwear.py`): what is kept is one
  closed solid, the half on the foot's inner side (right and left), closed
  by one flat face on the heel's middle line whose area is the material a
  cut there goes through, and its footbed is where the whole shoe has it
  (within 0.0001 mm at four places under the arch).
- A description read on this computer (`tests/test_footwear_choices.py`):
  known words into their settings, the words each was read from, a "not"
  that stops at its own clause, numbers in millimetres, and each fixed
  answer. Nothing is read from a description that says the shoe is for a
  foot condition or for sport, wherever in it that is said (another
  sentence, a list, after a semicolon), and a pain said not to be wanted
  counts. The reader that asks Claude is tested with a stand-in for the API
  only: what is sent (the typed words, the generator's lists as the only
  answers), that such a description is not sent at all, that Claude's own
  yes to "for a sport" or "for a foot condition" sets nothing, and that a
  choice without the person's own whole words or a value outside the limits
  is dropped.
- Each of those rules has a test that fails without it: 66 changes
  tried one at a time across the studio, the preview, the reader and the
  page's form (`tests/js/clog-form.test.mjs`), and each made a test fail.
- A code review of this stage found ten things, the first that the
  not-read rule was then a sentence wide and leaked ("For my flat feet:"
  followed by a list still set a firm sole beside the answer that nothing
  was changed for that). Eight have a test now that failed on the code
  before. The ninth is in the page's own script, which the suite doesn't
  run: the cut-open box ticked and unticked before the cut-open preview
  arrives must leave the whole shoe drawn. That was tried in a headless
  browser on scan 2349's shoe, as the page is (the whole shoe stayed) and
  with the check taken out (the cut-open shoe was drawn with the box
  unticked). The tenth was left as it is: the studio's Make printed shoe
  repeats Make insole's choice of model instead of sharing one piece of
  code with it, until the changes waiting on that code are merged. A test
  holds the two to the same footbed.
- What the trial pieces showed (`tests/test_footwear_fit.py`, and the
  studio's part in `tests/test_server_clog.py`). Every answer in these
  tests is made up: no piece has been printed. The questions are about the
  generator's own pieces and cushionings, and a shoe with no swatch is not
  asked about one; a record that isn't answers to them, or doesn't say
  whether anything hurt, is refused and nothing is kept; the block picked
  is the cushioning suggested; a piece that pressed suggests one fit
  roomier and walls that stood off one snugger, one step however many
  answers say so; answers both ways, and a fit with none further, change
  nothing and say why; toes that touched the end hold a snugger fit back
  and ask for no roomier one; an answer about the footbed, the print or
  the rim changes nothing and gets its fixed words; a record is about the
  shoe named, which must be one made here with its trial pieces (one made
  without them has nothing to record), also after that shoe was made again
  or its model replaced; what is recorded about one shoe is read together
  (the block picked in one record and a wall that pressed in the next both
  stand, and a toe cap that pressed in one and walls that stood off in the
  next point both ways); once a record says something hurt, the stop rule
  is shown and no shoe of that capture gets a suggestion, in later records
  about the same shoe, for the shoe made again, and after that record has
  been dropped as one of the oldest; a record changes neither the shoe nor
  its choices; only the newest 20 records and 10 shoes are kept; a phone on
  the Wi-Fi is refused all of it.
- The page's part of that and of a pair (`tests/js/clog-form.test.mjs`):
  what is sent for the form (which shoe included), a suggestion laid over
  the choices, which shoe of the record is the shoe on the page (not one
  made again since, nor one whose scan changed), which shoe the form opens
  on, which shoe is the other foot's (the newest that still matches its
  scan), which choices a pair shares (never the ruler numbers) and that a
  sole or pattern left empty is the style's own, and what is said of two
  feet's lengths (the ruler-against-scan line also when they match).
- A sole scan the studio would refuse makes no shoe: a SYNTHETIC sole-up
  scan with its forefoot rolled 15 degrees is refused in the arrival check's
  own words, and one rolled 5 degrees (which the floor levels) makes a shoe;
  a SYNTHETIC scan cut off 200 mm from the heel is refused by the command,
  which writes nothing; a whole-foot model or a foam print with the same
  open edges is not judged. In the studio (the rolled scan put in the
  library as scans were kept before the arrival check, and a shoe faked
  from it as before this rule): no shoe is made, the earlier one is
  removed, and *Make insole* still warns as it always has.
- Each of those rules has a test that fails without it: 89 changes tried
  one at a time across the rules, the studio, the page's arithmetic and the
  unfit-scan rule, and each made a test fail.
- The page itself, in a headless browser against a scratch studio holding
  scan 2349 and a SYNTHETIC left foot (`tests/synth.py`), each with its
  shoe. The other foot's shoe was shown with the two feet's lengths (260 mm
  by ruler against the synthetic foot's 240 mm by scan, and the line about
  ruler and scan), and its choices were put into the form with this foot's
  ruler numbers kept. A shoe made without trial pieces said there was
  nothing to record. For one made with them, a record was refused until it
  said whether anything hurt; walls that pressed, recorded first, suggested
  fit regular to roomy; the firm sole block, recorded next, added
  cushioning medium to firm beside it; the button put both into the form.
  With the shoe made again to those choices the form asked which shoe the
  pieces were from, the first shoe's records stayed under it without the
  button, and a third record was added to it. A record that said a piece
  of the new shoe hurt put the stop rule above both shoes with no
  suggestion and no button for either, and a later painless record about
  the first shoe brought none back. No page errors. No real left scan was
  used, and no person has used the page.

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

Through the studio (a copy of that capture in a scratch studio on a cloud
machine, 10 November 2026), *Make shoe* with the ruler's 260 x 97 mm gave the
same `stone` shoe as the command (278.3 x 112.9 x 84.3 mm, 548.2 cm³, the
inner wall let out by up to 16.9 mm from 10.4 to 187.4 mm from the back),
with three trial pieces (`stone` has no windows, so no swatch). From the
page in a headless browser, `vent`, roomy, with a 20 mm sole came out
281.4 x 119 x 95 mm (inside 275 x 102 mm), the footbed's highest fill
19.25 mm again, and both previews drew. The description "Something airy and
roomy with a thick sole, for thick socks, in red." set the style, the fit,
a 24 mm sole and 1.5 mm for the sock, left the ruler numbers alone, and
answered the colour in the fixed words. With "I play tennis and have flat
feet." added it set nothing, gave the medical and the sport answers, and
said the description was not read.

One real foot. Whether a wall let out this way sits well against that foot,
and whether the footbed's shelf along the inner side is comfortable to
stand on, are for the first print to answer.

### The real left scans

Left sole scan 2190 (`LIDAR_nwb_relaxed_L_20261027-151815-2190`: a
legs-flat iPhone model with both feet in it, the left one cut out by the
preparation), put through the command on the Mac on 10 November 2026 with
the code as it was before the rule that a scan the studio would refuse
makes no shoe (`2dfc561`):

- Sized by the scan alone, it reads the foot 220.0 x 111.0 mm (the right
  foot is 260 mm by ruler). The preparation warned of 225 mm of open edges
  within 40 mm of the floor, one side of the ball of the foot 23 mm higher
  than the other, both feet in the scan, and the fill clipped by the caps
  over 28.2% of the foot.
- The generator passed those warnings on and still wrote a shoe: 238.1 x
  121.7 x 74.4 mm, its inner wall let out by the whole 20 mm allowed, with
  its footbed made from that scan.
- Sized by the right foot's ruler numbers (260 x 97 mm) it was refused: 220
  mm against 260 is not the same foot in millimetres.

That shoe is why the rule was added.

With the rule (`8ffb900`), the same day on the Mac, each of the three real
left sole scans was put through the command, sized by the scan alone, Stone.
None makes a shoe, and nothing was written for any of them:

- `LIDAR_nwb_relaxed_L_20261027-151404-89df` (sole up): refused, one side of
  the ball of the foot 8 mm higher than the other.
- `LIDAR_nwb_relaxed_L_20261027-151408-537f` (sole up): refused, the same
  8 mm.
- `LIDAR_nwb_relaxed_L_20261027-151815-2190` (legs flat): refused, both feet
  in the scan and touching (225 mm of open edges near the floor once they
  were cut apart), and one side of the ball of the foot 23 mm higher than
  the other.

Right sole scan 2349, run beside them with the ruler's 260 x 97 mm, still
makes the same Stone shoe: 278.3 x 112.9 x 84.3 mm, 548.2 cm³.

## Not done yet

- Printing the trial pieces, and the settings and thicknesses they will
  correct. The pieces are generated; none has been printed.
- Reading a description by Claude against the real API. Its code is tested
  with a stand-in for the API (what is sent, and what is done with each kind
  of answer); no description has been sent to Anthropic from it yet, so how
  well it reads one is not known.
- The shoe in the iPhone app (the studio page only, for now).
- A left shoe from a real left sole scan. The generator and the studio make
  one from a left foot's own scan by the same steps as a right (tested on
  SYNTHETIC left feet). None of the three real left scans makes a shoe
  (above: the forefoot rolled in each, and both feet in one): a pair needs
  a new left sole scan, the ball of the foot level and only that foot in
  view.
- Changing the generator's own allowances (the fits' millimetres, the roof,
  the rim) from what printed pieces show. The records are kept for that;
  nothing reads them into the tables, and none exists yet.
- A rolled edge round the opening, toe spring, other printers and beds, a
  second shoe shape (a closed-heel sneaker).
