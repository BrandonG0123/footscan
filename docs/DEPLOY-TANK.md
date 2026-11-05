# Running footscan on tank (Windows 11) at footscan.brandongreene.dev

> Not a medical device. See [SAFETY.md](SAFETY.md). Putting this on the
> internet means strangers can send you photos of their feet and answers to
> health questions. **Read [HOSTING.md](HOSTING.md) first**, and keep the
> site behind Cloudflare Access (step 5) until that checklist is done.

Self-contained instructions for the machine that already serves
`brandongreene.dev` (see the site repo's `deploy/TANK-AGENT-BRIEF.md`). It
assumes that brief is done: Git installed, the site cloned to
`C:\srv\brandongreene-site`, Caddy serving it, and a Cloudflare Tunnel named
`brandongreene` running as a service.

---

## How it fits

```
tank (Windows 11)                                          internet
┌──────────────────────────────────────────────┐          ┌──────────┐
│ Caddy  :8080  ← brandongreene.dev   (static)  │  tunnel  │          │
│ footscan :8765 ← footscan.brandongreene.dev   │ ───────▶ │ visitors │
│ cloudflared dials out to Cloudflare           │          └──────────┘
└──────────────────────────────────────────────┘
```

- **A subdomain, not a path.** footscan is a running Python program (photo
  uploads, the studio, 3-D builds), not a folder of files, and every page
  addresses `/api/...`, `/studio/...`, `/assets/...` from the site root.
  `footscan.brandongreene.dev` needs no changes to the app and keeps its
  cookies and security rules separate from the main site.
- **Same tunnel, one more line.** No new ports, no port forwarding: footscan
  listens on `localhost:8765` only and cloudflared carries it out, exactly
  like the main site.
- **The code lives in the site repo** at `apps/footscan/` (a git subtree of
  the footscan project). `git pull` in `C:\srv\brandongreene-site` updates
  both.
- **Data lives outside the repo**, in `C:\srv\footscan-data`, so a pull can
  never touch anyone's photos.

---

## Step 1 — Python

footscan needs Python 3.12 or 3.13 on Windows (the 3-D libraries publish
Windows builds for those first). In an Administrator PowerShell:

```powershell
winget install --id Python.Python.3.13 -e
```

Reopen PowerShell, then `py -3.13 --version`.

## Step 2 — Install footscan

```powershell
cd C:\srv\brandongreene-site
git pull
cd apps\footscan
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[recon]"
mkdir C:\srv\footscan-data -Force
```

`[recon]` adds COLMAP, MeshLab and OpenCV for building 3-D models. If one of
them has no Windows build for your Python, `pip` says which; install
Python 3.12 instead and repeat.

Check it starts (Ctrl+C to stop):

```powershell
.venv\Scripts\footscan serve --public --port 8765 --data C:/srv/footscan-data
```

In a second window:

```powershell
curl.exe -sI http://localhost:8765/ | Select-Object -First 1            # 200
curl.exe -s  http://localhost:8765/robots.txt                           # Disallow: /
```

The first start writes the **studio key** to
`C:\srv\brandongreene-site\apps\footscan\.studio_key`. It is the only way into
the studio from the internet. It is gitignored; never paste it anywhere
public.

### What `--public` does

- Nothing counts as "this computer": every request arrives through the
  tunnel, so the studio opens **only** with the studio key.
- Search engines are told to stay out (`X-Robots-Tag: noindex` on every
  response, `robots.txt` disallowing everything). Add `--allow-indexing`
  only when you decide the app should be findable.

## Step 3 — Run it as a service

tank reboots weekly; a window someone has to reopen isn't good enough. With
NSSM (already used for Caddy in the site brief), in an Administrator
PowerShell. As in [ALWAYS-ON.md](ALWAYS-ON.md): nssm runs from
`C:\Program Files\nssm` (only an administrator can change it, and it's first
on the computer's PATH), the studio runs as Local Service (not LocalSystem, so
code in the checkout can't take over the computer), and in Python's UTF-8 mode
(Windows' own cp1252 can't write characters like √ and crashes on them):

```powershell
New-Item -ItemType Directory -Force "C:\Program Files\nssm" | Out-Null
Copy-Item (Get-Command nssm).Source "C:\Program Files\nssm\nssm.exe"
$machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
if (($machine -split ";") -notcontains "C:\Program Files\nssm") { [Environment]::SetEnvironmentVariable("Path", "C:\Program Files\nssm;" + $machine, "Machine") }
$env:Path = "C:\Program Files\nssm;" + $env:Path
$py = & "C:\srv\brandongreene-site\apps\footscan\.venv\Scripts\python.exe" -c "import sys; print(sys.base_prefix)"
icacls "C:\srv\brandongreene-site\apps\footscan" /grant "*S-1-5-19:(OI)(CI)RX"
icacls $py /grant "*S-1-5-19:(OI)(CI)RX"
icacls "C:\srv\footscan-data" /grant "*S-1-5-19:(OI)(CI)M"
nssm install Footscan "C:\srv\brandongreene-site\apps\footscan\.venv\Scripts\footscan.exe" "serve --public --port 8765 --data C:/srv/footscan-data"
nssm set Footscan ObjectName "NT AUTHORITY\LocalService"
nssm set Footscan AppDirectory "C:\srv\brandongreene-site\apps\footscan"
nssm set Footscan AppEnvironmentExtra PYTHONUTF8=1
nssm set Footscan AppStdout "C:\srv\footscan-data\server.log"
nssm set Footscan AppStderr "C:\srv\footscan-data\server.log"
nssm start Footscan
```

(`sc.exe qc Footscan` should show the Program Files nssm, in quotes, and
`NT AUTHORITY\LocalService`.)

## Step 4 — Add it to the tunnel

```powershell
cloudflared tunnel route dns brandongreene footscan.brandongreene.dev
```

In `C:\Users\<user>\.cloudflared\config.yml` add one rule **above** the
final `http_status:404` line:

```yaml
ingress:
  - hostname: brandongreene.dev
    service: http://localhost:8080
  - hostname: www.brandongreene.dev
    service: http://localhost:8080
  - hostname: footscan.brandongreene.dev     # new
    service: http://localhost:8765           # new
  - service: http_status:404
```

```powershell
Restart-Service cloudflared
nslookup -type=MX brandongreene.dev     # the four eforward MX records must still be there
```

## Step 5 — Cloudflare Access (do this before sharing the link)

Until the [HOSTING.md](HOSTING.md) checklist is done (device rules, health
data, under-13s, liability), don't let the open internet send you foot
photos and health answers. Cloudflare Zero Trust (free) can put a login in
front of the subdomain:

Zero Trust dashboard → Access → Applications → **Add an application** →
Self-hosted → domain `footscan.brandongreene.dev` → policy **Allow**, rule
**Emails** → your own address (and anyone you're testing with).

Visitors then sign in with a one-time code sent to an allowed email. Remove
the application when you're ready to open it up.

## Step 6 — Verify

```powershell
curl.exe -sI https://footscan.brandongreene.dev/ | Select-Object -First 1    # 302 to Access while it's on, else 200
curl.exe -s  https://footscan.brandongreene.dev/robots.txt
```

Then on your phone: open `https://footscan.brandongreene.dev/` (camera works:
Cloudflare provides real HTTPS, no certificate warning). For the studio,
open `https://footscan.brandongreene.dev/studio/?key=<the studio key>` once;
the phone remembers it.

**Reboot tank and check again.** If footscan doesn't come back by itself, the
service isn't set up right.

## Updating

Stop the service **before** reinstalling: the running service holds
`.venv\Scripts\footscan.exe` open, so `pip install -e` can't replace it, and
pip's rollback leaves footscan half uninstalled (the next start can't find
it; this happened on tank once). In an Administrator PowerShell:

```powershell
cd C:\srv\brandongreene-site
git pull
nssm stop Footscan
apps\footscan\.venv\Scripts\python -m pip install -e "apps\footscan[recon]"   # only if dependencies changed
nssm start Footscan
```

## Good to know

- **3-D builds use the whole CPU** for several minutes each, and tank also
  runs the Minecraft server. Builds run one at a time; start them when
  nobody's playing.
- **Upload limits.** Cloudflare's free plan caps a single upload at 100 MB.
  Photos (under 8 MB each) are fine; a LiDAR model over 100 MB won't import
  through the tunnel. Import it on tank itself (`http://localhost:8765` with
  the key) instead.
- **Backups.** Everything people send is in `C:\srv\footscan-data`. Back that
  folder up; git does not, by design.
- **Nothing from tank gets committed.** Not the studio key, not the data
  folder, not the tunnel credentials.
