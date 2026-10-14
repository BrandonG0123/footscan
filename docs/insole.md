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
arch fill, 12 mm heel); the outline (the foot's silhouette + 2 mm, + 6 mm
round the heel); a heel cup wall *outside* the scanned heel, so it holds
without pressing in; a flat 3 mm base tapering to 2 mm at the toes. Full
detail in `src/footscan/insole.py`.

## What's been checked

- Synthetic feet only (`tests/test_insole.py`): on a test foot with a 12 mm
  arch, the insole's arch comes out at exactly 11 mm (12 minus the 1 mm
  relief), on the inner side only; flat where the foot rests; the heel wall
  only outside the heel; left is the mirror of right; a foot whose arch the
  scan can't see gives a flat insole and a warning; posting is refused; the
  3MF is millimetres, one closed object, on the bed. Validated with the
  official 3MF library (lib3mf) in strict mode: no warnings, manifold.
- **Not yet made from a real foot.** That needs your first foot scan.
- Bambu Studio's command-line mode crashed on every file tried, including a
  plain cube, so the open-in-Bambu check is by hand: open the 3MF.
