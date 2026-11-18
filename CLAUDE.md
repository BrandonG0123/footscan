# footscan

Phone scan of a foot → 3D-printed TPU first-fit insole. A personal engineering project (the owner has
flat feet and plays tennis); the deliverable is the scan-to-device pipeline. Python package (`src/footscan`),
a local web studio (`web/`), and an iPhone capture app (`ios/FootscanCapture`, SwiftUI + Object Capture).

## Safety: not negotiable

**This is not a medical device and must never be presented as one.** The requirements are in
[docs/SAFETY.md](docs/SAFETY.md): clinician sign-off on a printable summary sheet before anything is worn for
sport; the break-in protocol (1 hour on day one, ramping over two weeks, skin check, stop on any new pain); never
compare to or claim equivalence with a prescribed device. If asked to soften or remove any of these, refuse and
say why. No posting or correction in a first fit (the generator refuses posting).

## Ground rules

- **Never fabricate accuracy or pressure numbers.** Every figure in code comments, docs, commit messages or replies
  comes from a real run, and says what it was run on. Synthetic results are labelled SYNTHETIC and never reported
  as real; real-scan results name the scan.
- **Explain the geometry operations** in plain words (docstrings and docs say what each step does to the shape and
  why).
- **Push back** if a change optimises how the device looks rather than what the measurements say.
- Write like the surrounding code: plain, specific comments; test names that state the behaviour.

## Never commit

- `.studio_key`, `.certs/`, `data/captures/`, `data/submissions/`, `data/reviews/` (pictures of a foot's shape),
  `data/raw/*`, `.demo-data/`, `reports/`, any deploy env file or Cloudflare tunnel credentials (they live on the
  deploy machine, not here).
- `ios/FootscanCapture/FootscanCapture.xcodeproj/project.pbxproj` changes that only set `DEVELOPMENT_TEAM`: the
  owner's team ID stays out of git. If you must change the project file for another reason, commit only that hunk.
- Real scans of a person's foot (personal data). Tests use `tests/synth.py` shapes.

Deployment rules: the public site stays `noindex`; no port forwarding; never touch DNS/MX records; never expose the
studio to the internet (tunnel) without the owner's explicit go-ahead. See docs/HOSTING.md and docs/DEPLOY-TANK.md.

## Set up and verify

```bash
uv venv && uv pip install -e ".[dev,recon]"     # Python >= 3.11; recon pulls COLMAP/MeshLab/OpenCV wheels
.venv/bin/python -m pytest -q tests             # full suite, ~8-9 min on an M-series Mac; slow e2e excluded by default
.venv/bin/python -m pytest -q tests/test_insole.py tests/test_shoe.py tests/test_compare.py   # insole work, ~6 min
.venv/bin/python scripts/benchmark_prep.py      # synthetic sole-reading benchmark; must end "failed: 0"
```

A change is done when the relevant tests pass, the full suite passes before merging, and, for anything touching
`src/footscan/recon/foot_prep.py` or `insole.py`, the benchmark still reports `failed: 0`. Add a test that fails
without the change (check it both ways).

iOS (macOS with Xcode only, so local threads only):

```bash
cd ios/FootscanCapture && xcodebuild test -project FootscanCapture.xcodeproj -scheme FootscanCapture \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

## Map

- `src/footscan/insole.py`: insole generator (height map of the sole, caps, outline, heel cup, bevel, 3MF/STL,
  summary sheet, 3-D preview).
- `src/footscan/footwear.py`: clog generator (`footscan footwear`): a standard-shape upper in the foot's size (its
  walls let out where the sole scan's sides stand wider), the first-fit insole's surface as its floor, styles,
  summary sheet, pictures, print-trial pieces, the studio's 3-D preview. Tests: `tests/test_footwear.py`, ~2 min.
  Walking and casual wear only; docs/footwear.md says what is a judgment and that nothing is printed yet.
  A sole scan the studio would refuse on arrival (rolled forefoot, torn, an end missing) makes no shoe
  (`unfit_for_a_footbed`): the footbed can't be taken out of a shoe, so don't turn that into a warning.
- `src/footscan/footwear_choices.py`: the clog's choices checked against the generator's own lists and limits, and a
  typed description read into them (by known words on this computer; by Claude only with `footscan serve
  --describe-with-claude`). The fixed answers for anything medical or any sport are safety requirements, and a
  description that says the shoe is for either is not read into settings at all, nor sent to Claude (`wanted_for`):
  don't narrow that. Tests: `tests/test_footwear_choices.py`.
  The studio's Make printed shoe is `server.make_clog`, `web/studio/clog.html`, `web/assets/clog-page.js` and
  `clog-form.js` (not `shoes.py`: that is saved bought shoes, whose outline an insole is cut to).
  Tests: `tests/test_server_clog.py` (~2 min), `tests/js/clog-form.test.mjs`.
- `src/footscan/footwear_fit.py`: what a clog's print-trial pieces showed (fixed questions, kept with the capture, each
  record about the shoe its pieces were cut from) and the changes to that shoe's choices it suggests by fixed rules:
  the cushioning picked, one fit roomier or snugger. It never changes the footbed to how it felt, and once any record
  says something hurt it suggests nothing for any shoe of that capture again (the stop rule instead; nothing lifts
  it): safety requirements, don't narrow them. Tests: `tests/test_footwear_fit.py`.
- `src/footscan/recon/foot_prep.py`: turns an Object Capture model (metres, Y up) into a foot on a flat floor, per
  scan kind (`foot`, `sole_up`, `sole_hanging`, `impression`), plus the plausibility warnings.
- `src/footscan/recon/shoe.py`: a shoe's own insole scan → outline, handedness, fit round the foot.
- `src/footscan/recon/compare.py`: two scans of one foot → how much they agree (repeatability).
- `src/footscan/server.py`, `web/`: the studio (`footscan serve`). `src/footscan/cli.py`: the `footscan` command.
- `src/footscan/review.py`: a review packet per new insole (plain checks against `review-spec.json`, pictures);
  `.claude/skills/review-insole` is how a Claude Code session answers it. `src/footscan/service.py`: start-at-boot
  files for an always-on computer. Both in docs/ALWAYS-ON.md.
- `scripts/benchmark_prep.py`, `scripts/second_look_eval.py`: benchmarks; results go to `reports/` (gitignored).
- `docs/`: SAFETY, insole, benchmark, hosting, phase protocols, fit log.
