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
  networks only. The commands copy `nssm.exe` to `C:\Program Files\nssm` first:
  it is the service's own program, and every `nssm` you type later runs it as
  administrator, so it must not sit in your own folder, where winget puts it. (A service installed from winget's copy: copy `nssm.exe` there, then point the
  service at it with
  `Set-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Services\Footscan ImagePath '"C:\Program Files\nssm\nssm.exe"'`
  and `nssm restart Footscan`; its settings stay. The quotes inside the value
  matter: unquoted, Windows may try to run `C:\Program.exe` instead. Check it
  with `sc.exe qc Footscan`.) The commands also put `C:\Program Files\nssm`
  first on the computer's own PATH, so a later `nssm` in an Administrator
  PowerShell runs that copy and never winget's. The studio itself runs as
  Windows' **Local Service** account, not LocalSystem: the checkout and its
  `.venv` are yours to change (git pull, pip install), so whatever is in them
  must not run with full control of the computer. Local Service gets read
  access to the checkout and to the Python the `.venv` runs on, and write
  access to the data folder only. Keep the data folder's path free of spaces. **First check `nssm status Footscan`**: if a service by that name
  already exists, it's the public deploy from DEPLOY-TANK.md on the same port.
  Stop and decide which one tank should run; two can't share port 8765.
- **macOS**: a LaunchAgent. It runs while your account is logged in, so turn on
  automatic login and *Prevent automatic sleeping*; a sleeping Mac drops off the
  Wi-Fi.
- **Linux**: a systemd user unit, with `loginctl enable-linger` so it runs with
  nobody logged in.

Then **restart the computer** and check the studio comes back by itself. If it
doesn't, the service isn't set up right. The log is `data/server.log`.

### 5. Reach it away from home (Tailscale)

Tailscale is a private network between your own devices: the phone reaches the
studio from anywhere, and nothing is opened to the internet. On the computer and
on the iPhone, install Tailscale and sign in with the same account. Then, on the
computer:

- In the Tailscale admin console, turn off **key expiry** for this computer, or
  it drops off every few months until you sign in again.
- Let Tailscale's addresses through the firewall (Windows, Administrator
  PowerShell; the home Wi-Fi rule above is for Private networks only):

  ```powershell
  New-NetFirewallRule -DisplayName "footscan (Tailscale)" -Direction Inbound -Protocol TCP -LocalPort 8766 -RemoteAddress 100.64.0.0/10 -InterfaceAlias Tailscale -Action Allow
  ```

  (8766 is tank's port; use the studio's own.) `-InterfaceAlias Tailscale`
  keeps it to the Tailscale adapter: some other networks (a phone hotspot,
  carrier NAT, Cloudflare WARP) also hand out 100.64.0.0/10 addresses. A rule
  made without it is narrowed with `Set-NetFirewallRule -DisplayName "footscan
  (Tailscale)" -InterfaceAlias Tailscale`.
- Windows: in Tailscale's settings turn on **Run unattended**, so Tailscale
  keeps running after a restart when nobody has signed in yet.

The studio then prints `over Tailscale, from anywhere (the connect code
includes it): https://100.x.x.x:<port>/` when it starts, and the connect code
carries that address as well as the home one. On Windows the service runs as
Local Service, and Tailscale doesn't tell that account its address (tank, 6 Nov
2026), so the studio reads it from the adapter called "Tailscale" instead
(unless Tailscale says it is stopped or logged out). If the line is missing,
check the adapter is there and up: `Get-NetAdapter Tailscale`.

### 6. Pair the phone with it

A different computer has a different studio key and certificate, so the
iPhone app has to connect again: in the studio open **Import a 3D scan**, press
**Show the connect code**, and scan it from the app. Then send one scan and check it
arrives.

### 7. Let project threads work on this computer (Remote Control)

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

### 8. Review insoles

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
| `length` | within ±1 mm of the shoe's length (for an insole cut to a shoe's outline, that outline's length) | an insole built without the shoe length comes out at the foot's own length |
| `shoe` | a saved shoe's name and size are the spec's | an insole cut to another shoe |
| `shoe_length` | the shoe's outline within ±5 mm of the spec's chart length (a judgment, not measured) | a stock insole scanned at the wrong scale, or another size, makes insoles that match it but not the shoe |
| `pair_length` | left and right within ±1 mm of each other (cut to a shoe's outline: the outlines' own lengths, as each is turned a little to its foot) | both feet are built to the same shoe |
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

**A Windows service installed before it ran as Local Service** (tank's, until
this is done): in an Administrator PowerShell, paste the PATH lines and the
three `icacls` lines from `footscan service --system windows`, then
`nssm set Footscan ObjectName "NT AUTHORITY\LocalService"` and
`nssm restart Footscan`. `sc.exe qc Footscan` should then show
`SERVICE_START_NAME : NT AUTHORITY\LocalService`. Open the studio and make an
insole to check it still works; if `server.log` says *Access is denied*, a
folder it needs wasn't granted (not yet tried on tank).

Local Service can only read the checkout, so the studio can't make a new
`.studio_key` or certificate there. To change the key (or the certificate),
`nssm stop Footscan`, delete `.studio_key` (or `.certs`), start `footscan serve
--host 0.0.0.0 --https` once as yourself to make new ones, stop it, then `nssm
start Footscan` and pair the phone again. If the service can't write the key,
`server.log` says so.

**On Windows, use these steps instead: they stop the service first.** The running
service holds `.venv\Scripts\footscan.exe` open, so `pip install -e .` can't
replace it, and pip's rollback leaves footscan half uninstalled: the next start
can't find it. In an Administrator PowerShell:

```powershell
cd C:\srv\footscan; git pull
nssm stop Footscan
.venv\Scripts\python -m pip install -e ".[recon]"    # only if dependencies changed
nssm start Footscan
```

Installing other packages (pytest, for example) is fine while it runs.

## Good to know

- **Backups.** Everything is in `data/`: captures, insoles and review packets.
  Back it up; git doesn't, by design.
- **Never commit** `data/` (the review pictures are a person's foot shape),
  `.studio_key` or `.certs/`.
- **3-D builds use the whole CPU** for minutes; on tank that competes with the
  Minecraft server.
- **Opening the camera from the phone.** The app's Photos + mat scan shows
  "Opening the studio's camera…" until the studio's capture page and its
  scripts (15 files) have loaded over Wi-Fi. The studio keeps each phone
  connection open between files (closed after 30 s idle) and sets up each new
  HTTPS connection in its own thread, with a 10 s limit, so one slow or stuck
  phone connection doesn't hold up the others (until 2 Nov 2026, one that
  opened and went quiet stopped the studio answering anyone).
