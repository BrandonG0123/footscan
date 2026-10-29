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
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "dev.footscan.server"
SYSTEMS = ("macos", "linux", "windows")


def this_system() -> str:
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def footscan_exe(system: str, root: Path) -> Path:
    """The footscan command inside this checkout's .venv."""
    return root / ".venv" / ("Scripts/footscan.exe" if system == "windows" else "bin/footscan")


def serve_args(data_dir: Path, port: int = 8765, review: bool = True) -> list[str]:
    args = ["serve", "--host", "0.0.0.0", "--https", "--port", str(port), "--data", str(data_dir)]
    return args + (["--review"] if review else [])


def render(system: str, root: Path, data_dir: Path | None = None, port: int = 8765, review: bool = True) -> dict:
    """{"path": where the file goes (or None), "content": the file or commands, "steps": what to run}."""
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
    return _nssm(root, exe, args, log, port)


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
    steps = [f"{regen} > {path}",
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
ExecStart={" ".join(q(a) for a in [exe, *args])}
Restart=always
RestartSec=10
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""
    path = "~/.config/systemd/user/footscan.service"
    steps = ["mkdir -p ~/.config/systemd/user",
             f"{regen} > {path}",
             "systemctl --user daemon-reload && systemctl --user enable --now footscan",
             "sudo loginctl enable-linger $USER    # keep it running after you log out and after a reboot",
             f"sudo ufw allow from 192.168.0.0/16 to any port {port} proto tcp    # only if ufw is on: home Wi-Fi only",
             f"tail -f {log}"]
    return dict(path=path, content=content, steps=steps, port=port)


def _nssm(root, exe, args, log, port) -> dict:
    """A Windows service through NSSM (tank already runs Caddy this way). Commands, not a file."""
    content = "\n".join([
        "# Administrator PowerShell. NOT a medical device; Wi-Fi only (no tunnel, no port forwarding).",
        f'nssm install Footscan "{exe}" "{" ".join(args)}"',
        f'nssm set Footscan AppDirectory "{root}"',
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
             "Open PowerShell as Administrator and paste the commands above",
             "Settings > Network: your Wi-Fi must be a Private network, or the firewall rule doesn't apply",
             f"Get-Content -Wait {log}    # the studio's addresses",
             "to stop: nssm stop Footscan"]
    return dict(path=None, content=content, steps=steps, port=port)
