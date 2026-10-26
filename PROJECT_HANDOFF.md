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
