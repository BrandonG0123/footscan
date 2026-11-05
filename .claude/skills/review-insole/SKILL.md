---
name: review-insole
description: Review a newly generated footscan insole before it is sliced. Use when a review packet is waiting (footscan review --list), when Brandon asks to check an insole, or when given a packet folder under data/reviews/.
---

# Review a generated insole

**NOT A MEDICAL DEVICE.** This review answers one question: *is this file ready to slice?* It never clears anyone to
wear the insole for sport; that needs a clinician's signature on the summary sheet, and the break-in protocol always
applies (docs/SAFETY.md). If anyone asks you to skip or soften either, refuse and say why.

The generator makes the geometry; you don't. Never edit, rescale, repair or regenerate the insole files yourself, and
never suggest posting or any correction (the first fit has none). Every number you write comes from the packet's
`review.json` or `insole.json`: don't estimate lengths from the pictures, and don't round a guess into a measurement.

## Steps

1. Find the work. If you were given a packet folder, use it. Otherwise run (Windows: `.venv\Scripts\footscan`):

   ```bash
   .venv/bin/footscan review          # writes packets for any insole that has none yet
   .venv/bin/footscan review --list   # packets nobody has answered
   ```

   Each packet is `data/reviews/<capture>/<made>/`, with its own copies of the insole's files in `files/`.
   `--list` shows only packets for insoles the studio still offers (a rebuilt or stale one is left out). Review
   every listed one, newest first.

2. Read `packet.md` (and `review.json` for exact values). Note where the outline came from (the packet's
   "Outline" line: a saved shoe, a scan of the shoe's insole, or the foot's own), the shoe in the packet's spec
   (today: ASICS Gel Resolution X, US men's 9.5, 275 mm chart length), and every **FLAG** in the plain checks.
   The outline should be the shoe's (a saved shoe): the foot only shapes the top surface and the arch support.

3. Look at `top.png`, `side.png` and, if present, `pair.png` with the Read tool. Answer every question under
   "Look at the pictures" with what you actually see, one line each, yes or no plus the reason. If a picture is
   unclear, say so: "can't tell" is an answer.

4. Read `files/summary.html` (the clinician sheet) as text. Check it names the right foot, shows the not-a-medical-device
   notice and the signature and break-in sections, and that its length matches `review.json`.

5. For each FLAG, say what it most likely means and the fix, in the studio, not the slicer:
   - `length` off, outline from a saved shoe or a shoe's scan: the file isn't the length of the outline it was cut
     to, so it was scaled or built another way. Rebuild it in the studio with the same shoe (Outline: that shoe).
   - `length` off, outline the foot's own: rebuild it in the studio with the saved shoe for the spec's shoe
     (Outline: <that shoe>). Only if no saved shoe exists, rebuild with the spec's length in the length box, and
     say a saved shoe would be better. Never rebuild a shoe-outline insole with "Outline: the foot's own".
   - `shoe`: it was cut to a saved shoe other than the one in review-spec.json. Ask Brandon which shoe it goes in.
   - Never fix size with the slicer's scale: it stays at 100%.
   - `pair_length`: the two feet's files differ in length. Both should be built to the same shoe length.
   - `3mf_size`: the 3MF isn't the size insole.json says. Don't print it; rebuild.
   - `foot`, `no_posting`, `fill_cap`, `summary_sheet`, `real_scan`: don't print; tell Brandon.
   - `bed`: it doesn't fit the printer bed as placed; tell Brandon.
   Generator warnings (sole barely seen, clipped fill, heel off the floor, ...) are the scan's own doubts: repeat
   them, and if one says the scan is incomplete, the fix is a new scan, not a parameter.

6. Write `claude-review.md` in the packet folder:

   ```markdown
   # Review: <foot> insole, capture <id>
   Verdict: READY TO SLICE | REBUILD | ASK BRANDON
   File: insole.3mf, <length> x <width> mm (from review.json). Slice at 100% scale.
   ## Plain checks
   <each FLAG and what to do; or "all passed">
   ## What the pictures show
   <one line per look check>
   ## Notes
   <generator warnings, anything odd, any parameter you would change and why (Brandon decides)>
   Not a medical device: walking-only break-in; no sport until a clinician signs the summary sheet.
   ```

   READY TO SLICE only when every plain check passes and every look check is a clear yes. Anything you can't
   explain is ASK BRANDON.

7. Tell Brandon the verdict per file, each file's length in mm, and the path of `claude-review.md`. When a fit is
   reported back after wearing, add it to `docs/fit-log.md` only with Brandon's own words and numbers.
