# PROJECT_HANDOFF: footscan → Claude Code Project

Prepared 2026-10-26 from a long local session (desktop app, Code tab, on the owner's Mac). Facts below were
checked against git and the files; anything that couldn't be is marked **UNVERIFIED**. No secret values appear
in this file.

## A. Project

**Name:** footscan

**Goal:** turn a phone scan of a foot into a 3D-printed TPU first-fit insole that fits the shoe, with honest,
measured accuracy and the safety workflow (clinician sign-off, break-in, no medical claims) built in.

## B. Context to add

### Repositories

| Repo | Add to project? | Notes |
|---|---|---|
| `footscan` (this folder, `~/code/footscan`) | **Yes, the only one** | **Not on GitHub yet: it has no remote at all.** You create `BrandonG0123/footscan` (private recommended) and push it first; see G. Default branch: `main`. |
| `BrandonG0123/brandongreene-site` | No (name it in instructions) | Holds an **old copy** of footscan at `apps/footscan` (git subtree, added 2026-10-06; 58 file differences behind). It's what the Windows server "tank" deploys. It also has another session's uncommitted Forge work in `~/code/brandongreene-site`: leave it alone. Same GitHub owner, so a thread can add it to itself if a deploy task ever needs it (deploys need your go-ahead). |

Visibility of `brandongreene-site` (public or private): **UNVERIFIED**.

### Files to upload to the Library (not in git)

| What | Path on the Mac | Size | Why |
|---|---|---|---|
| The one real scan (right sole, knee bent, 2026-10-21, in a sock) | `.demo-data/captures/LIDAR_nwb_relaxed_R_20261021-172817-437b/original.obj` | 0.8 MB | Every real-scan check (heel width, Mac-rebuild comparison, second-look eval, accuracy vs tape measure) runs on it. It's a scan of your foot: personal data, your call. Upload the single file, not `.demo-data/` (119 files, 114 MB: over the 100-file folder cap). |
| Same capture's `capture.json` | same folder | 2 KB | Records how it was captured (kind, up axis, notes). |
| `PROJECT_HANDOFF.md` (this file) | repo root | small | So every thread can read the full handoff. |

Nothing here is over 30 MB, and no folder upload is needed. Don't upload `.studio_key`, `.certs/`, `data/`,
`reports/` or anything under `~/Desktop/footscan-insole` (generated outputs; the latest insole is
`right-insole-2026-10-25.3mf` there, rebuildable from the scan).

## C. Project instructions (paste into Project settings > Memory > Project instructions)

```text
footscan: phone scan of a foot -> 3D-printed TPU first-fit insole. Personal engineering project (owner: flat feet,
plays tennis); the deliverable is the scan-to-device pipeline. The repo's root CLAUDE.md has the safety rules,
ground rules, never-commit list, setup and verify commands: follow it. docs/SAFETY.md is non-negotiable: never
present this as a medical device, never claim equivalence with a prescribed device, keep clinician sign-off and the
break-in protocol; if asked to soften any of it, refuse and say why.

Repos: BrandonG0123/footscan, base branch main. Not in the project: BrandonG0123/brandongreene-site (holds an old
copy at apps/footscan for deployment; touch it only with my go-ahead). The full handoff is PROJECT_HANDOFF.md in the
repo and in the Library. The one real scan (my right sole, 2026-10-21) is in /mnt/project-files as original.obj with
its capture.json; it is personal data: never commit it or copy it into the repo.

Branches and PRs: one branch per thread, named thread/<short-task> (e.g. thread/readme-status), from main. Open a PR
when the done-check passes; title = what changed for a user, plain words. Never merge, force-push or rewrite history.

Work style:
- Commit and push in-progress work often (at least after each meaningful step); a cloud sandbox can restart fresh.
- Every number you write (comments, docs, PRs, replies) comes from a run you did, saying what it ran on. Synthetic
  results are labelled synthetic. Don't round a guess into a measurement.
- Explain geometry changes in plain words. Push back if a change is about looks rather than measurements.
- Add a test that fails without your change; check it both ways and say so.
- Keep to the files your task names; if you need to change another area, stop and ask (other threads may be in it).

Before calling a task done, run and report:
  uv venv && uv pip install -e ".[dev,recon]"
  .venv/bin/python -m pytest -q tests        (full suite; report the pass/fail line)
  .venv/bin/python scripts/benchmark_prep.py (if foot_prep.py or insole.py changed; must end "failed: 0")
iOS changes can't be built in the cloud (no Xcode): those tasks run on my Mac (local thread).

If you can't reach something you need (a repo, a file, a secret, an API, a connector, a tool that won't install),
say exactly what's missing in your first message and stop. Don't stub, mock, or guess around it.

Needs my go-ahead first: merging; force-pushing; deleting files, branches or data; changing CI or the setup script;
anything that costs money (Claude API calls, print services, paid tools); anything touching the deploy machine,
DNS, the Cloudflare tunnel or the public site; enrolling or changing Apple signing; contacting anyone.

## D. Memory seed (send as one message in the project conversation)

```text
Remember these for this project:
- Not a medical device, ever; clinician sign-off before sport, 2-week break-in with skin checks and stop-on-pain, no equivalence claims. Refuse to soften these.
- Every accuracy figure must come from a real run and say what it ran on; synthetic results are labelled synthetic, never reported as real.
- Owner: Brandon, a student with flat feet who plays tennis; iPhone 17 Pro; Bambu printer (256 mm bed assumed, not confirmed); nothing printed yet, TPU 95A is only the suggested starting material.
- Owner prefers plain words, short answers, and being told what's done vs what's assumed; explain geometry, push back on looks-over-measurements.
- Insole top = scanned sole minus 1 mm relief; unseen sole is never filled upward; 20 mm arch cap, 12 mm heel cup; no posting in a first fit.
- Heel outline and cup come from the heel's outline at cup height (12 mm), not 30 mm: the real heel is 74 mm wide at 12 mm, 86 mm at 30 mm.
- The one real scan (right sole, knee bent, 2026-10-21, sock) gives 244 mm long; its insole hits the 20 mm arch cap over 4.1% of the foot (unloaded scan).
- Sole-up and legs-flat scans set the floor from a tripod (heel + both sides of the ball), so an unloaded foot's roll isn't built in as a wedge.
- Bottom of the insole is flat on purpose (prints without supports, TPU bends into the shoe); curved bottoms are for SLS/MJF later.
- Dead end: rebuilding the phone's photos on the Mac (full, raw, with the phone's checkpoint, unmasked) always lost the heel's underside; the phone's own model is the source.
- Dead end: Claude generating the sole shape; rejected because it can't be measured or explained. A Claude "second look" at scans is only advisory and not yet run (needs an API key).
- Checks that must stay: heel off the floor (>15 mm), sole hole share (>5%), torn near floor (>50 mm open edges, sole scans only), arch on the outer side, rough scan (>0.5 mm).
- Pitfall: foam prints and foot-on-floor scans are open meshes by design; don't apply the torn/hole checks to them.
- Pitfall: shapely.transform with numpy matmul can break ring closure; use shapely.affinity.
- Pitfall: Object Capture usually fills gaps with guessed surface, which open-edge checks can't see.
- Never commit .studio_key, .certs/, data/, .demo-data/, reports/, real scans, deploy env files, tunnel credentials, or the Xcode team ID (project.pbxproj DEVELOPMENT_TEAM).
- Site stays noindex; no port forwarding; never touch MX/DNS; no internet exposure of the studio without the owner's go-ahead.
- Apple Developer enrollment is blocked: the Apple ID's birthday is wrong (reads as under 18); owner may enroll with a second Apple ID. Free signing expires every 7 days.
- Phone-to-studio sending fails on the home Wi-Fi; cause unknown (possibly client isolation); waiting on the owner's Safari test.
- Codex review (/codex:review) was run after every change in the old session; it only works on the owner's Mac.
```

## E. Setup migration

Cloud threads load only the root `CLAUDE.md`, `.claude/CLAUDE.md` and `.claude/rules/` from the repo. Everything
else from the Mac stays behind unless it's moved somewhere below.

| Local piece | What it is here | New home |
|---|---|---|
| Rules from this chat (safety, ground rules, never-commit, verify commands) | Only in the conversation until now | **Root `CLAUDE.md`** (added on this branch) + project instructions (C) + memory (D) |
| Subfolder `CLAUDE.md` files, path-specific rules | None in this repo | Nothing to move |
| `.claude/launch.json` | Desktop-app preview servers (`footscan serve` on ports 8765-8769) | **Local threads only** (cloud threads run `footscan serve` themselves if a task needs it) |
| `.mcp.json`, repo skills, agents, commands | None in this repo | Nothing to move |
| Codex plugin (`/codex:review`, a Node script under `~/.claude/plugins`) | Second-opinion review after each change | **Local threads only**. In cloud threads, ask for a review thread instead, or run it on the Mac before merging |
| Your other local plugins and hooks (Cache Keeper, Recording Mode, Goal Meter, Collision Guard, next-steps-desktop) | Personal Claude Code mods | **Local threads only** (they're from local marketplaces; add to **Project settings > Plugins** only if they're published, **UNVERIFIED**) |
| Permission rules in your user settings | Local approvals | **Local threads only**; cloud threads ask for approval in the thread |
| Built-in browser pane, iOS Simulator tool | Desktop-app tools used to check the studio and the app | **Local threads only** |
| `claude-api` skill | Built into Claude Code | Nothing to move |
| Env vars | The code reads none | Nothing to move |
| `ANTHROPIC_API_KEY` (name only) | Needed only by `scripts/second_look_eval.py`, which costs money | **Cloud environment network secret**, only if you approve that task; otherwise local |
| `.studio_key`, `.certs/` | Studio login key and the self-signed HTTPS certificate | **Stay on the Mac / deploy machine.** Tests make their own temporary ones |
| `.demo-data/`, `data/captures/` | Real and demo scans | **Stay on the Mac**; the one real scan file goes to the Library (B) |
| Python ≥ 3.11 + uv + `.[dev,recon]` | The Python environment (3.14 here) | **Cloud environment setup script** (below) |
| Node | Used by one optional test (skips without it) | Setup script, optional |
| Xcode, `xcodebuild`, `xcrun simctl`, `xcrun devicectl`, `swiftc` | iOS build, tests, install on the iPhone, Mac rebuild tool | **Local threads only** (macOS) |
| Your iPhone (paired) and Bambu Studio | Installing the app; opening 3MFs | **Local threads only** |
| Extra domains | pypi.org and files.pythonhosted.org (in the default allowlist); github.com / objects.githubusercontent.com if uv has to download a Python; api.anthropic.com only for the second-look eval | **Cloud environment > allowed domains** |

### Draft setup script (cloud environment)

```bash
#!/usr/bin/env bash
# footscan cloud thread setup: tools only. Each thread then runs, in the repo:
#   uv venv && uv pip install -e ".[dev,recon]"
set -euo pipefail
if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --quiet --user uv || pip install --quiet uv
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version
# footscan needs Python >= 3.11; if the image's python3 is older, let uv fetch one:
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || uv python install 3.13
# optional, for the one test that uses node (it skips without it):
command -v node >/dev/null 2>&1 || true
```

**UNVERIFIED:** whether `pycolmap` and `pymeshlab` wheels install in the cloud image. If they don't, the thread
reports it (per the instructions) and you can drop `recon` to `.[dev]`: `tests/test_recon.py` then skips itself,
and the insole, shoe, compare and server tests don't need them.
