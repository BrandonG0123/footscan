# Getting a good sole scan

> Not a medical device. See [SAFETY.md](SAFETY.md). Whatever the scan, the
> insole is a first fit: clinician sign-off on the summary sheet before it's
> worn for sport, and the break-in protocol.

What went wrong with the first real left-foot scans, and how to avoid it.
The scans themselves stay out of git (personal data); the numbers below come
from running the studio's own preparation (`foot_prep.py`, the same code as
**Make insole**) on them.

## What went wrong on 27 October 2026

Three sole scans were taken that afternoon (iPhone app 0.1, Object Capture,
model built on the phone, one lap each):

| Scan | Kind | Photos | Insole outline | What the preparation found |
|---|---|---|---|---|
| right, `…_R_20261027-151404-2349` | sole up | 46 | 246.4 x 102.3 mm | Fine. Both sides of the ball of the foot within 1.2 mm of the floor. |
| left, `…_L_20261027-151404-89df` | sole up | 35 | 227.0 x 86.3 mm | Forefoot rolled onto its outer edge: the big-toe side of the ball 8.6 mm higher than the little-toe side. Toes curled up. |
| left, `…_L_20261027-151815-2190` | legs flat | 41 | (rejected) | Both legs and both feet in the scan (the model is about a metre long), joined at the feet: 221 x 217 mm on the floor. |

The two left scans fail for different reasons:

1. **The forefoot rolled over (89df).** A relaxed foot with no weight on it
   tends to roll onto its outer edge. Standing, the big-toe side of the ball
   comes down to the floor; in the scan it stayed 8.6 mm up. The floor the
   studio sets runs through the heel and both sides of the ball, but only
   looks 8 mm up for them, so it didn't level this one. An insole made from
   it would fill up to about that much under the big-toe joint: a wedge, a
   correction a first fit must not have. The forefoot also came out narrow
   (52-56 mm across the footprint at the ball, against 80-84 mm on the
   right), and the curled toes make the foot read short. Before this change,
   only the cap-clipping note was raised. Now it's flagged as **THE
   FOREFOOT WAS ROLLED ONTO ONE EDGE**.
2. **Both feet in the box (2190).** Legs flat, both legs lie on the bed, and
   the box held both feet. Side by side they touched, and Object Capture
   joined them into one piece. The studio now cuts the two apart down the
   gap between the shins and keeps the chosen foot. This scan is still not
   usable: where the feet touched, the inner side of the left foot is missing
   (236 mm of torn edge near the floor), and its forefoot is rolled too.
3. **Short captures.** 35 and 41 photos, one lap each. The right scan also
   had one lap and came out fine, so this isn't proven to be a cause, but a
   second, closer lap over the toes and the back of the heel is cheap.

## How to scan a sole (phone)

**Sole up** is the pose that has worked (the right foot). Use it for the
left rescan.

1. Lie face down on a bed, chin on your hands. Bend this knee so the lower
   leg points straight up, sole to the ceiling. The other leg stays flat on
   the bed.
2. Ankle relaxed: don't point the foot or pull the toes back. Let the toes
   lie straight; if they curl, wiggle them and let go.
3. **Level the ball of the foot.** The helper lays a book (anything flat
   and stiff) across the ball of the foot, from the big-toe joint to the
   little-toe joint. Both sides should touch it. If one doesn't, turn the
   foot gently until it does, then take the book away and keep still. This
   is the step the failed left scan missed.

   (This replaced "look along the sole: if the big-toe side is higher, turn
   the foot outward". The 8.6 mm on 89df is the big-toe side's height above
   the floor in the *prepared scan*, sole down. Seen by the helper with the
   sole up, that same side is the *lower* one, so the old wording pointed at
   the wrong side. The book doesn't need either. Not yet tried on a real
   scan.)
4. In the app, drag the box so it holds this foot, past the toe tips and the
   back of the heel, and a hand's width of the leg, nothing else. The camera
   repeats the checks under the box until you tap Start.
5. The helper walks slowly all the way round, phone pointing down at the
   sole, until the ring fills. Then a **second lap**, closer, over the
   arch, the toes and the back of the heel. Then Finish.
6. Make insole in the studio and read the warnings before anything else. Any
   capitalised warning means scan again, not print.

**Legs flat** (feet past the end of the bed): the same checks, plus move the
other leg well to the side, a forearm's width between the feet, so only one
foot is in the scan. Hanging relaxed, the foot points and rolls more easily
than in the sole-up pose, so check the ball is level before scanning.

## Foam print instead

A foam impression box takes the problem of holding the foot still out of
the scan: press the foot in, lift it out, and the print stays put while it
is scanned. The app's **Right / Left foam print** and the studio's
`impression` preparation already handle it (see [insole.md](insole.md)):
the print is cut out of the box, turned to face down and rested on its
deepest points, and the studio reports how deep the print is
(`print_deepest_mm`; it warns under 15 mm, where the arch may not have
reached the foam).

How to press a print (the way orthotic labs describe it: about 1 to 1.5
inches deep, [Footmaxx](https://www.footmaxx.com/about-us/services/casting-methods/non-weight-bearing/foam)):

- Sit with hip, knee and ankle at right angles, the knee over the foot.
- Put the foot on the foam with the ball level (the same check as above),
  then press down through the knee until the heel and the ball are sunk in,
  and press the toes in last.
- Lift straight up without rocking. Scan the box on a table from all round,
  two laps, the second looking straight down into the print.

This isn't fully unloaded or fully standing; the studio records the scan
kind on the summary sheet. **No foam print has been through the pipeline
yet**: the preparation is tested on synthetic prints only
(tests/test_insole.py).

### Impression kits

Foot impression foam is a closed-cell phenolic foam made for this
([Orthopedia](https://orthopedia.fandom.com/wiki/Foot_Impression_Foam)).
Clinic suppliers sell it by the case, for example 6 x 12 x 2 in boxes,
10-12 pairs, US$127-176 a case
([AliMed](https://www.alimed.com/products/foamart-foot-impression-foam)), or
4 cm and 6 cm deep boxes at £52.50 for 25
([Algeos](https://www.algeos.com/casting-boxes)). For one person, Amazon has
small packs. Prices weren't checked: Amazon blocks automated reading, so
check the price and the box's depth (2 in / 5 cm or more) on the page.

- [Foot Impression Foam Box, 2 boxes of 2 pads](https://www.amazon.com/Foot-Impression-Foam-Boxes-Pads/dp/B0GVYKCMPJ)
  (one print per foot, nothing spare)
- [Foot Impression Foam Box, 4 boxes of 2 pads](https://www.amazon.com/Foot-Impression-Foam-Boxes-Pads/dp/B0GWH5KVSK)
  (spares for a retake)
- [Foot Impression Foam Box Kit, high density, 12.5 x 12.2 x 1.5 in](https://www.amazon.com/Impression-High-Density-Orthotic-Shoemaking-Assessment/dp/B0FMQYB96F)
  (1.5 in is the shallow end of the 1-1.5 in press)
- [GLEAVI Foot Casting Kit Impression Box](https://www.amazon.com/GLEAVI-Molding-Footprint-Orthotic-Impression/dp/B0CP7MMSBF)
- [Foot Impression Foam Box for Custom Insoles](https://www.amazon.com/Impression-Adults-Custom-Insole-Shape/dp/B0CVR12DFW)

A box is single use: a retake needs a fresh one.

### Floral foam (the green foam for holding flower stems)

Possible and cheap, but untested here, and a worse material for this.

- **What it is.** Wet floral foam (OASIS and similar, the green kind for
  fresh flowers) is a phenolic foam too, but a light, open-celled, brittle
  one made to soak up water and let stems through. Impression foam is made
  to crush cleanly and hold a sharp edge. Expect floral foam to crumble at
  the print's edges rather than crush, which blurs the outline the insole
  takes its shape from. Use it dry: don't soak it.
- **Size.** A standard brick is 9 x 4 x 3 in, about 229 x 102 x 76 mm
  ([FiftyFlowers](https://fiftyflowers.com/products/oasis-standard-floral-foam-bricks)).
  The right foot's insole outline is 246 x 102 mm, so one brick is too short
  and only just as wide as the ball of the foot, whose print would break
  through the sides. Use **four bricks**, two long by two wide (about
  458 x 204 mm), packed tight in a shallow box or taped round the outside so
  they can't spread apart. Don't glue them: glue lines are harder than the
  foam and print as ridges. The seams between bricks should run along and
  across the foot, not just under the arch. The studio treats patches of
  foam top less than 20 mm apart as one block, so seams don't cut the print
  out, but a seam the foot crushes unevenly can show as a step in the sole.
- **Depth.** 3 in is deep enough for a 1-1.5 in press, with foam left under
  the heel.
- **Mess.** It sheds fine green crumbs and dust: press the print on a hard
  floor you can vacuum, and wash the foot after. OASIS's own safety sheet
  lists no hazardous ingredients and says a mask is optional
  ([OASIS SDS](https://www.oasisfloral.co.uk/pub/media/wysiwyg/Light-Floral-Foam-SDS.pdf));
  a dust mask while cutting or brushing it off doesn't hurt.
- **Before trusting it,** press the heel into a spare brick and look at the
  edge. If it is ragged, use an impression kit. In the studio, check the
  print depth and the warnings as for any print.

Where to buy: craft shops and Amazon sell wet floral foam bricks in packs
(search "wet floral foam brick"). Dry floral foam, for artificial flowers,
is a different, firmer material; don't use it.

## When the studio says scan again

A sole scan that would make a bad insole is refused as soon as it reaches
the studio, and the phone marks it *Scan again*. Open it: the page lists
what to change, in steps, with a **Scan again** button that goes straight
to a new scan of the same foot (the steps again on the get-ready list, and
"Last time: ..." on the camera until you tap Start). The studio's own
findings, with its measurements, are folded under *What the studio found*.

| The phone says | Most likely cause | What to change |
|---|---|---|
| The toes were cut off | The box ended at the toes, or they curled out of view | Toes relaxed and straight; the box past the toe tips; a close second lap round the toes |
| The back of the heel was cut off | The phone never went behind the heel | The box past the back of the heel; take the phone right round behind it |
| The underside of the heel wasn't scanned | The heel pad left out of the box or the laps | The box over the whole sole; look at the heel on each lap, not just the toes |
| More than this foot was in the scan | The other foot, the bed or the leg in the box | The other foot a forearm's width away; the box in to this foot and a hand's width of leg |
| The other foot hid one side of this one | Both feet in the box, touching | As above |
| Part of the foot wasn't scanned | Part of the foot outside the box, or a lap not finished | The whole foot in the box; the ring full, then a second lap |
| This foot came out shorter than your other scan | An end missing that the shape checks didn't see | Toes straight; the box past both ends; two laps |
| The toes were curled up | Pointed ankle, curled toes | Ankle relaxed; wiggle the toes and let go |
| The ball of the foot wasn't level | The relaxed forefoot rolled onto its outer edge | The book check (step 3 above) |
| The studio couldn't find the whole foot | The scan held too little of the foot | The whole foot in the box; the ring full |

The steps are in `RETAKE_STEPS` in `src/footscan/recon/completeness.py`.

## What the studio checks

Make insole lists warnings at the top of its result; the capitalised ones
mean don't print. For sole scans: not foot-shaped on the floor, too little
of the sole scanned, a hole in the sole, the heel off the floor, torn near
the floor, the forefoot rolled onto one edge, the arch on the outside (the
other foot?), a rough surface. A legs-flat scan with both feet in it keeps
the chosen foot and says so. All are in `plausibility()` in
`src/footscan/recon/foot_prep.py`.
