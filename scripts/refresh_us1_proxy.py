#!/usr/bin/env python3
"""Refresh the crawler's SOCKS route through a ready Colab slot on us1."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time

PROXY_FILE = Path("data/proxy/proxy.url")
LOCAL_PORT = 11980
ASKPASS = Path("/tmp/babadum-colab-askpass")
PROBE_DATA = (
    "category=words&type=getWord&lang=1&game=chooseImage"
    "&onReceiveLocation=Words"
)
PROBE_URL = "https://babadum.com/get.php"
UA = "BaBaDumLocalLibrary/1.0"


def remote_slots():
    command = (
        "set -a; . /opt/colab-proxy/.env; set +a; "
        "curl -fsS --max-time 30 -H \"Authorization: Bearer $PROXY_TOKEN\" "
        "http://127.0.0.1:27590/v1/proxies"
    )
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "us1", command],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode:
        return []
    try:
        return [
            slot for slot in json.loads(result.stdout).get("slots", [])
            if slot.get("live") and slot.get("proxy_ready") and slot.get("ssh")
        ]
    except (ValueError, AttributeError):
        return []


def route_ok(timeout=25):
    result = subprocess.run(
        [
            "curl", "-sS", "--max-time", str(timeout), "--proxy",
            "socks5h://127.0.0.1:{}".format(LOCAL_PORT),
            "-A", UA, "-e", "https://babadum.com/", "-d", PROBE_DATA,
            PROBE_URL,
        ],
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout.decode("utf-8", "replace"))
    except Exception:
        return False
    return (
        result.returncode == 0
        and payload.get("type") == "getWord"
        and bool(payload.get("data", {}).get("words"))
    )


def stop_port_owner():
    result = subprocess.run(
        ["lsof", "-t", "-iTCP:{}".format(LOCAL_PORT), "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
    )
    for token in result.stdout.split():
        try:
            os.kill(int(token), signal.SIGTERM)
        except (OSError, ValueError):
            pass


def start_tunnel(slot):
    parts = shlex.split(slot["ssh"])
    host = next(part for part in parts if "@" in part)
    port = parts[parts.index("-p") + 1] if "-p" in parts else "22"
    password = os.environ.get("BABADUM_COLAB_SSH_PASSWORD", "admin")
    ASKPASS.write_text("#!/bin/sh\nprintf '%s\\n' {!r}\n".format(password))
    ASKPASS.chmod(0o700)
    env = {
        **os.environ,
        "SSH_ASKPASS": str(ASKPASS),
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": ":0",
    }
    with Path("/tmp/babadum-colab-ssh.log").open("ab") as log:
        process = subprocess.Popen(
            [
                "ssh", "-N", "-D", "127.0.0.1:{}".format(LOCAL_PORT),
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=15",
                "-o", "ServerAliveCountMax=2",
                "-o", "ConnectTimeout=20",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "NumberOfPasswordPrompts=1",
                "-J", "us1", "-p", str(port), host,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,
        )
    time.sleep(1)
    return process.poll() is None


def main():
    PROXY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if route_ok():
        PROXY_FILE.write_text("socks5h://127.0.0.1:{}\n".format(LOCAL_PORT))
        PROXY_FILE.chmod(0o600)
        print("us1 Colab proxy route ok")
        return 0

    slots = remote_slots()
    stop_port_owner()
    for slot in slots:
        if not start_tunnel(slot) or not route_ok():
            stop_port_owner()
            continue
        PROXY_FILE.write_text("socks5h://127.0.0.1:{}\n".format(LOCAL_PORT))
        PROXY_FILE.chmod(0o600)
        print("us1 Colab proxy route ok via", slot["slot"])
        return 0
    print("no working us1 Colab proxy route")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
