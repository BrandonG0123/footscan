# Running footscan on an always-on computer

> Not a medical device. See [SAFETY.md](SAFETY.md). This page keeps the studio
> running on your **home Wi-Fi** only: no tunnel, no port forwarding, nothing on
> the internet. Putting it online is a separate step ([HOSTING.md](HOSTING.md),
> [DEPLOY-TANK.md](DEPLOY-TANK.md)) that waits for your go-ahead.

What you end up with:

- **The studio runs all the time.** The computer starts `footscan serve` at boot
  and restarts it if it stops. Phones on your Wi-Fi send scans to it as they do
  to the Mac today.
- **Every new insole gets a review packet.** Within about 20 seconds of *Make
  insole*, the server writes `data/reviews/<capture>/<made>/`: a copy of the
  insole's files, its numbers, the plain checks below (PASS or FLAG), and
  pictures drawn from the STL (`top.png`, `side.png`, and `pair.png` once both
  feet have one).
- **A Claude Code session in the same folder reviews it** (`/review-insole`)
  and writes `claude-review.md` beside the packet: READY TO SLICE, REBUILD, or
  ASK BRANDON.

Who does what: the generator makes the geometry (the same answer every time,
and explained on the summary sheet); the plain checks are arithmetic on its
files; Claude looks at the pictures, explains the flags and the warnings, and
suggests what to change; you decide; a clinician signs before any sport.

---

## Checklist

### 1. Get the code on the computer

Clone this repo (not the old copy inside the website repo, which is the public
deploy's):

```bash
git clone https://github.com/BrandonG0123/footscan.git ~/footscan        # Windows: C:\srv\footscan
cd ~/footscan
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[recon]"   # Python 3.11 or newer
```

On Windows use Python 3.12 or 3.13 (`py -3.13 -m venv .venv`, then
`.venv\Scripts\python -m pip install -e ".[recon]"`), as in DEPLOY-TANK.md.

### 2. Bring the library over (only if it's a different computer)

The studio's library is the `data/` folder in the checkout. Copy
`data/captures/` from the Mac across your own network or a USB drive. It is
photos and scans of feet (personal data): don't send it through a cloud chat or
commit it.

### 3. Start it once by hand

```bash
.venv/bin/footscan serve --host 0.0.0.0 --https --review
```

On Windows run this from **Git Bash** (`.venv/Scripts/footscan.exe ...`): the
first start makes the HTTPS certificate with `openssl`, which Git for Windows
provides. This first start writes `.studio_key` and `.certs/`, which the service
then reuses. Check it prints the addresses, open the studio, then Ctrl+C.

### 4. Make it start by itself

```bash
.venv/bin/footscan service          # Windows: .venv\Scripts\footscan service
```

prints the start-up file for this computer, filled in with this checkout's
paths, and the numbered steps to install it. It installs nothing itself.

- **Windows** (tank): a service through NSSM, plus a firewall rule for Private
  networks only. Keep the data folder's path free of spaces. **First check `nssm status Footscan`**: if a service by that name
  already exists, it's the public deploy from DEPLOY-TANK.md on the same port.
  Stop and decide which one tank should run; two can't share port 8765.
- **macOS**: a LaunchAgent. It runs while your account is logged in, so turn on
  automatic login and *Prevent automatic sleeping*; a sleeping Mac drops off the
  Wi-Fi.
- **Linux**: a systemd user unit, with `loginctl enable-linger` so it runs with
  nobody logged in.

Then **restart the computer** and check the studio comes back by itself. If it
doesn't, the service isn't set up right. The log is `data/server.log`.

### 5. Pair the phone with it

A different computer has a different studio key and certificate, so the
iPhone app has to connect again: in the studio open **Import a 3D scan**, press
**Show the connect code**, and scan it from the app. Then send one scan and check it
arrives.

### 6. Let project threads work on this computer (Remote Control)

So Claude in the project can run things there (builds, the accuracy run,
reviews):

1. Install Claude Code on the computer and sign in with the same account.
2. Either turn on Remote Control in the Claude desktop app's settings and add
   the footscan folder, or run this in a terminal and leave it running:

   ```bash
   cd ~/footscan && claude remote-control
   ```

3. Tell the project when it's on: the computer then shows up next to the
   MacBook and threads can use it.

### 7. Review insoles

Open Claude Code in the footscan folder. When a session starts, it lists any
packet nobody has answered yet. Type:

```text
/review-insole
```

Claude reads `packet.md`, looks at the pictures, reads the summary sheet,
answers each question, and writes `claude-review.md` in the packet folder. It
never edits, rescales or rebuilds the insole. The steps it follows are in
[.claude/skills/review-insole/SKILL.md](../.claude/skills/review-insole/SKILL.md).

Without the server's `--review` (or on another computer), make the packets by
hand: `footscan review`. `footscan review --list` shows what's waiting.

**Fully automatic (not tried yet).** In a terminal where Claude Code is signed
in (not as the service, which has no sign-in), this hands every packet still
waiting for an answer, whoever wrote it, to a headless Claude session, once each:

```bash
.venv/bin/footscan review --watch --exec 'claude -p "/review-insole {packet}" --permission-mode acceptEdits'
```

---

## What is checked

The shoe comes from [review-spec.json](../review-spec.json): ASICS Gel
Resolution X, US men's 9.5, insole length 275 mm. That length is the size
chart's, not a ruler measurement of the shoe's insole; change the file when
you have one.

| Check | PASS when | Why |
|---|---|---|
| `length` | within ±1 mm of the shoe's length | an insole built without the shoe length comes out at the foot's own length |
| `pair_length` | left and right within ±1 mm of each other | both feet are built to the same shoe |
| `3mf_size` | the 3MF is in millimetres, its placement only turns and moves it, and it and the STL are as long as insole.json says | it prints at the right size with the slicer at 100% |
| `foot` | the insole was made for the capture's foot | a left/right mix-up |
| `no_posting` | no posting angle set | the first fit has no posting (SAFETY.md) |
| `fill_cap` | highest fill within the arch cap | the generator's own safety cap held |
| `bed` | fits the spec's printer bed (256 mm), straight or turned | |
| `summary_sheet` | the clinician sheet is there, with the notice, the signature line and the break-in section | SAFETY.md requirement 1 |
| `real_scan` | (only appears for synthetic geometry, always FLAG) | test shapes must never be printed |

The ±1 mm tolerances are a judgment, not measured. The picture questions
(outline foot-shaped, big-toe side where it should be, heel cup, arch under the
arch, smooth top, pair outlines matching) are in each `packet.md`.

**Slicing:** Bambu Studio at 100% scale, always. If a file is the wrong size,
rebuild it in the studio with the shoe's length; never fix size in the slicer.

## Updating

```bash
cd ~/footscan && git pull
.venv/bin/python -m pip install -e ".[recon]"     # only if dependencies changed
```

Then restart the service: `nssm restart Footscan` (Windows),
`launchctl kickstart -k gui/$(id -u)/dev.footscan.server` (macOS),
`systemctl --user restart footscan` (Linux).

## Good to know

- **Backups.** Everything is in `data/`: captures, insoles and review packets.
  Back it up; git doesn't, by design.
- **Never commit** `data/` (the review pictures are a person's foot shape),
  `.studio_key` or `.certs/`.
- **3-D builds use the whole CPU** for minutes; on tank that competes with the
  Minecraft server.
