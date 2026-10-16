#!/usr/bin/env python3
"""Mint a fresh SOCKS5 proxy via the Colab notebook and persist its URL.

Runs the proxy skill's node script (Chrome CDP on port 9229), extracts the
ip:port it prints, verifies the proxy, and writes a socks5h URL to the state
file the crawler watcher reads. Exits nonzero when no working proxy results.
"""
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

SKILL_DIR = Path("/Users/wtf403/.agents/skills/proxy")
STATE_DIR = Path(__file__).resolve().parents[1] / "data" / "proxy"
URL_FILE = STATE_DIR / "proxy.url"


def run_skill():
    proc = subprocess.run(
        ["node", str(SKILL_DIR / "scripts" / "proxy.js")],
        cwd=str(SKILL_DIR), capture_output=True, text=True, timeout=600)
    output = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}:\d+)", output)
    if proc.returncode != 0 or not match:
        print(output[-2000:])
        return None
    return match.group(1)


def verify(ip_port):
    host, _, port = ip_port.partition(":")
    try:
        sock = socket.create_connection((host, int(port)), timeout=10)
        sock.close()
        return True
    except OSError:
        return False


def read_existing():
    try:
        proxy = urlsplit(URL_FILE.read_text().strip())
        if proxy.scheme in ("socks5", "socks5h") and proxy.hostname and proxy.port:
            return proxy.hostname + ":" + str(proxy.port)
    except OSError:
        pass
    return None


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    current = read_existing()
    if current and verify(current):
        print("Selected verified SOCKS proxy")
        return 0
    fresh = run_skill()
    if fresh and verify(fresh):
        URL_FILE.write_text("socks5h://" + fresh)
        print("Selected verified SOCKS proxy")
        return 0
    print("No ready proxy slots")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
