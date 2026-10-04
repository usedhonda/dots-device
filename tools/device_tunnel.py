#!/usr/bin/env python3
"""Manage the dedicated device tunnel without exposing runtime credentials."""
import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local" / "device-tunnel"
ALIAS = "kai-device"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "connect", "status", "stop"])
    args = parser.parse_args()
    os.umask(0o077)
    binary = PRIVATE / "tunnel-client"
    if not binary.is_file():
        raise ValueError("Install the official tunnel-client in .local/device-tunnel first")
    if args.action in ("status", "stop"):
        return subprocess.call([str(binary), "runtimes", args.action, ALIAS, "--json"], cwd=ROOT)
    settings = PRIVATE / "settings.json"
    key = PRIVATE / "runtime-key"
    if not settings.is_file() or not key.is_file():
        print(json.dumps({"ready": False, "missing": [p.name for p in (settings, key) if not p.is_file()]}))
        return 2
    for path in (settings, key):
        mode = path.lstat()
        if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.getuid() or stat.S_IMODE(mode.st_mode) != 0o600:
            raise ValueError("Tunnel settings and key must be user-owned regular files with mode 0600")
    config = json.loads(settings.read_text())
    tunnel_id = config.get("tunnel_id")
    if not isinstance(tunnel_id, str) or not tunnel_id.startswith("tunnel_"):
        raise ValueError("An actual registered tunnel_id is required")
    launcher = ROOT / "tools" / "device_mcp_stdio.py"
    command = shlex.join([sys.executable, str(launcher)])
    if args.action == "preflight":
        print(json.dumps({"ready": True, "alias": ALIAS, "credentials": "owner-only", "cloud_verified": False}))
        return 0
    return subprocess.call([str(binary), "runtimes", "connect", "--alias", ALIAS,
        "--tunnel-id", tunnel_id, "--profile", ALIAS, "--profile-dir", str(PRIVATE / "profiles"),
        "--runtime-api-key", "file:" + str(key), "--mcp-command", command, "--json"], cwd=ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError):
        print(json.dumps({"ready": False, "error": "Invalid or unavailable private tunnel configuration"}))
        sys.exit(2)
