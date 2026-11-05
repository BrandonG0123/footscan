"""Keep the studio running on an always-on computer: the start-up file for each system.

``footscan service`` prints the file (or commands) that make the computer start
``footscan serve`` by itself at boot and restart it if it stops, filled in with
this checkout's real paths. It writes nothing and installs nothing: the person
runs the printed steps, because installing a service needs their password.

The studio is served the way it is on the Mac today for phones on the same
Wi-Fi (``--host 0.0.0.0 --https``, the phone app pins the certificate), plus
``--review`` so each new insole gets its review packet (footscan.review). It
is never ``--public`` here: putting the studio on the internet is a separate
step that waits for the owner's go-ahead (docs/HOSTING.md).

Each file also sets ``PYTHONUTF8=1``: Python's UTF-8 mode, so the studio reads
and writes text as UTF-8 on every system. Windows' own default (cp1252) can't
write characters like √ and crashes on them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "dev.footscan.server"
NSSM_DIR = r"C:\Program Files\nssm"
NSSM_EXE = NSSM_DIR + r"\nssm.exe"
# Windows' built-in Local Service account (SID S-1-5-19): a service account with no more rights than a normal
# user. The Windows service runs the studio as it, not as LocalSystem, so code in the checkout (which the owner's
# own account can change) can't take over the computer when the service starts it.
LOCAL_SERVICE = r"NT AUTHORITY\LocalService"
LOCAL_SERVICE_SID = "*S-1-5-19"
SYSTEMS = ("macos", "linux", "windows")


def this_system() -> str:
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def footscan_exe(system: str, root: Path) -> Path:
    """The footscan command inside this checkout's .venv."""
    return root / ".venv" / ("Scripts/footscan.exe" if system == "windows" else "bin/footscan")


def serve_args(data_dir: Path, port: int = 8765, review: bool = True) -> list[str]:
    args = ["serve", "--host", "0.0.0.0", "--https", "--port", str(port), "--data", str(data_dir)]
    return args + (["--review"] if review else [])


def render(system: str, root: Path, data_dir: Path | None = None, port: int = 8765, review: bool = True,
           python_home: Path | str | None = None) -> dict:
    """{"path": where the file goes (or None), "content": the file or commands, "steps": what to run}.

    ``python_home``: the Python installation the checkout's .venv runs on (default: this one's,
    ``sys.base_prefix``, as ``footscan service`` runs from that .venv). The Windows service account is given
    read access to it."""
    if system not in SYSTEMS:
        raise ValueError(f"system must be one of {', '.join(SYSTEMS)}")
    root = Path(root)
    data_dir = Path(data_dir) if data_dir else root / "data"
    exe = footscan_exe(system, root)
    args = serve_args(data_dir, port, review)
    log = data_dir / "server.log"
    # the same command again, with the same choices, for the step that saves its output into place
    regen = f'"{exe}" service --system {system} --data "{data_dir}" --port {port}' + ("" if review else " --no-review")
    if system == "macos":
        return _launchd(root, exe, args, log, port, regen)
    if system == "linux":
        return _systemd(root, exe, args, log, port, regen)
    if any(" " in a for a in args):
        # NSSM takes the arguments as one quoted string; a quoted path inside it can't survive PowerShell
        raise ValueError("on Windows, choose a data folder without spaces in its path (e.g. C:\\srv\\footscan-data)")
    return _nssm(root, exe, args, log, port, Path(python_home or sys.base_prefix), data_dir)


def _launchd(root, exe, args, log, port, regen) -> dict:
    """A LaunchAgent: starts when the owner's account logs in, restarts if it stops.
    (A LaunchAgent, not a system daemon: it runs as the owner, so it uses their checkout and their files.)"""
    prog = "".join(f"\n    <string>{escape(str(a))}</string>" for a in [exe, *args])
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>{prog}
  </array>
  <key>WorkingDirectory</key>
  <string>{escape(str(root))}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUTF8</key>
    <string>1</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>{escape(str(log))}</string>
  <key>StandardErrorPath</key>
  <string>{escape(str(log))}</string>
</dict>
</plist>
"""
    path = f"~/Library/LaunchAgents/{LABEL}.plist"
    steps = [f'mkdir -p ~/Library/LaunchAgents "{log.parent}"',
             f"{regen} > {path}",
             f"launchctl bootstrap gui/$(id -u) {path}",
             "System Settings > Energy (or Battery > Options): turn on 'Prevent automatic sleeping when the display "
             "is off'; Users & Groups: log in automatically as you, so it starts again after a power cut",
             f"tail -f {log}    # the studio's addresses",
             f"to stop: launchctl bootout gui/$(id -u)/{LABEL}"]
    return dict(path=path, content=content, steps=steps, port=port)


def _systemd(root, exe, args, log, port, regen) -> dict:
    """A user unit: runs as the owner; 'linger' keeps it running when nobody is logged in."""
    def q(s):
        s = str(s)
        return f'"{s}"' if any(c in s for c in ' "\\') else s

    content = f"""[Unit]
Description=footscan studio (not a medical device)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory={root}
Environment=PYTHONUTF8=1
ExecStart={" ".join(q(a) for a in [exe, *args])}
Restart=always
RestartSec=10
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""
    path = "~/.config/systemd/user/footscan.service"
    steps = [f'mkdir -p ~/.config/systemd/user "{log.parent}"',
             f"{regen} > {path}",
             "systemctl --user daemon-reload && systemctl --user enable --now footscan",
             "sudo loginctl enable-linger $USER    # keep it running after you log out and after a reboot",
             f"sudo ufw allow from 192.168.0.0/16 to any port {port} proto tcp    # only if ufw is on: home Wi-Fi only",
             f"tail -f {log}"]
    return dict(path=path, content=content, steps=steps, port=port)


def _nssm(root, exe, args, log, port, python_home, data_dir) -> dict:
    """A Windows service through NSSM (tank already runs Caddy this way). Commands, not a file.

    Two things keep the service from being a way to take over the computer:

    - nssm.exe is the service's own program, and every ``nssm`` command is run in an Administrator PowerShell.
      winget puts it in the user's own folder, where the user (or anything running as them) can replace it; so
      the commands copy it to Program Files, which only an administrator can change, install the service from
      there, and put that folder first on the computer's own PATH, so a later ``nssm`` in an Administrator
      PowerShell runs that copy too, not winget's.
    - The studio runs as Local Service, not LocalSystem: the checkout and its .venv are the owner's to change (git
      pull, pip install), so whatever is in them runs with no more rights than a normal user. Local Service gets
      read access to the checkout and the Python it runs on, and write access to the data folder only.
    """
    content = "\n".join([
        "# Administrator PowerShell. NOT a medical device; Wi-Fi only (no tunnel, no port forwarding).",
        "# nssm where only an administrator can change it (it is the service's program, and runs as administrator",
        "# whenever you type nssm here), first on the computer's PATH so every later Administrator PowerShell's nssm",
        "# is this one",
        f'New-Item -ItemType Directory -Force "{NSSM_DIR}" | Out-Null',
        "# (pasted a second time: that nssm is already there, and may be running a service, so it's left as it is)",
        f'if (-not (Test-Path "{NSSM_EXE}")) {{ Copy-Item (Get-Command nssm).Source "{NSSM_EXE}" -ErrorAction Stop }}',
        '$machine = [Environment]::GetEnvironmentVariable("Path", "Machine")',
        f'if (($machine -split ";") -notcontains "{NSSM_DIR}") {{ '
        f'[Environment]::SetEnvironmentVariable("Path", "{NSSM_DIR};" + $machine, "Machine") }}',
        f'$env:Path = "{NSSM_DIR};" + $env:Path',
        "# the studio runs as Local Service (no more rights than a normal user): it may read the checkout and the",
        "# Python it runs on, and write only the data folder",
        f'icacls "{root}" /grant "{LOCAL_SERVICE_SID}:(OI)(CI)RX"',
        f'icacls "{python_home}" /grant "{LOCAL_SERVICE_SID}:(OI)(CI)RX"',
        f'icacls "{data_dir}" /grant "{LOCAL_SERVICE_SID}:(OI)(CI)M"',
        f'nssm install Footscan "{exe}" "{" ".join(args)}"',
        f'nssm set Footscan ObjectName "{LOCAL_SERVICE}"',
        f'nssm set Footscan AppDirectory "{root}"',
        "nssm set Footscan AppEnvironmentExtra PYTHONUTF8=1",
        f'nssm set Footscan AppStdout "{log}"',
        f'nssm set Footscan AppStderr "{log}"',
        "nssm set Footscan Start SERVICE_AUTO_START",
        f'New-NetFirewallRule -DisplayName "footscan (home Wi-Fi)" -Direction Inbound -Protocol TCP '
        f"-LocalPort {port} -Profile Private -Action Allow",
        "nssm start Footscan",
        "",
    ])
    bash = " ".join(a.replace("\\", "/") for a in args)  # Git Bash reads a backslash as an escape
    steps = [f'First start it once by hand from Git Bash, where openssl is on the PATH: "{exe}" {bash} '
             "(it makes .studio_key and the HTTPS certificate in .certs, which the service then reuses); Ctrl+C",
             f'Open PowerShell as Administrator: New-Item -ItemType Directory -Force "{log.parent}", '
             "then paste the commands above",
             "Settings > Network: your Wi-Fi must be a Private network, or the firewall rule doesn't apply",
             'sc.exe qc Footscan    # BINARY_PATH_NAME must be "C:\\Program Files\\nssm\\nssm.exe", in quotes, '
             "and SERVICE_START_NAME NT AUTHORITY\\LocalService (not LocalSystem)",
             f"Get-Content -Wait {log}    # the studio's addresses",
             "to stop: nssm stop Footscan"]
    return dict(path=None, content=content, steps=steps, port=port)
