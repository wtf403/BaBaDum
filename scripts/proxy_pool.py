#!/usr/bin/env python3
"""Maintain verified SSH SOCKS5 tunnels and expose one live proxy URL.

Tunnels are ordinary SSH dynamic forwards (ssh -N -D). Each host in HOSTS gets a
local port. --refresh (re)starts missing tunnels, verifies each by asking
babadum.com for a real game round through it, and writes the first working
socks5h URL to --url-file. Exit 0 when at least one proxy is verified.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HOSTS = ['us1', 'reg1']
BASE_PORT = 11880
STATE = Path('/tmp/babadum-proxy-pool.json')
ASKPASS = Path('/tmp/babadum-proxy-askpass')
PROBE_DATA = 'category=words&type=getWord&lang=1&game=chooseImage&onReceiveLocation=Words'
PROBE_URL = 'https://babadum.com/get.php'
UA = 'BaBaDumLocalLibrary/1.0'


def load():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {}


def save(state):
    STATE.write_text(json.dumps(state))
    STATE.chmod(0o600)


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_tunnel(pid):
    if not alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def start_tunnel(host, port):
    cmd = [
        'ssh', '-N', '-D', '127.0.0.1:{}'.format(port),
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=15',
        '-o', 'ServerAliveCountMax=2',
        '-o', 'ConnectTimeout=15',
        '-o', 'StrictHostKeyChecking=accept-new',
        host,
    ]
    log = Path('/tmp/babadum-proxy-pool.log').open('ab')
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log,
                            stderr=log, start_new_session=True).pid


def listen(port, timeout=5):
    import socket
    try:
        sock = socket.create_connection(('127.0.0.1', port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def verify(port, timeout=25):
    """Return True when babadum returns a real round through this tunnel."""
    if not shutil.which('curl'):
        # Fall back to a python SOCKS probe when curl is unavailable.
        return verify_python(port, timeout)
    result = subprocess.run([
        'curl', '-sS', '--max-time', str(timeout),
        '--proxy', 'socks5h://127.0.0.1:{}'.format(port),
        '-A', UA, '-e', 'https://babadum.com/',
        '-d', PROBE_DATA, PROBE_URL,
    ], capture_output=True)
    try:
        payload = json.loads(result.stdout.decode('utf-8', 'replace'))
    except Exception:
        return False
    return result.returncode == 0 and payload.get('type') == 'getWord' and bool(
        payload.get('data', {}).get('words'))


def verify_python(port, timeout=25):
    try:
        import socks  # noqa: F401
    except Exception:
        return False
    import socket as _socket
    import urllib.request
    original = _socket.socket
    try:
        import socks
        socks.set_default_proxy(socks.SOCKS5, '127.0.0.1', port, rdns=True)
        _socket.socket = socks.socksocket
        urllib.request.install_opener(urllib.request.build_opener(
            urllib.request.ProxyHandler({})))
        request = urllib.request.Request(
            PROBE_URL, data=PROBE_DATA.encode('ascii'),
            headers={'User-Agent': UA, 'Referer': 'https://babadum.com/',
                     'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8', 'replace'))
        return payload.get('type') == 'getWord' and bool(
            payload.get('data', {}).get('words'))
    except Exception:
        return False
    finally:
        _socket.socket = original


def refresh(url_file, hosts):
    state = load()
    working = []
    for index, host in enumerate(hosts):
        port = BASE_PORT + index
        entry = state.get(host) or {}
        if not alive(entry.get('pid')) or not listen(port):
            kill_tunnel(entry.get('pid'))
            entry['pid'] = start_tunnel(host, port)
            entry['port'] = port
            entry['started'] = time.time()
            state[host] = entry
            save(state)
            deadline = time.time() + 20
            while time.time() < deadline and not listen(port, 2):
                time.sleep(1)
        entry.setdefault('port', port)
        if listen(port, 3) and verify(port):
            entry['ok'] = True
            entry['url'] = 'socks5h://127.0.0.1:{}'.format(port)
            working.append(entry['url'])
        else:
            entry['ok'] = False
        state[host] = entry
    save(state)
    if working:
        Path(url_file).write_text(working[0] + chr(10))
        Path(url_file).chmod(0o600)
        print('proxy pool ok:', ', '.join(working))
        return 0
    print('no working proxy in pool')
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url-file', default='data/proxy/proxy.url')
    parser.add_argument('--hosts', default=','.join(HOSTS))
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='ensure tunnels and verify')
    args = parser.parse_args()
    hosts = [h for h in args.hosts.split(',') if h]
    if args.status:
        state = load()
        for host in hosts:
            entry = state.get(host, {})
            print(host, 'pid', entry.get('pid'), 'port', entry.get('port'),
                  'ok', entry.get('ok'), 'running', alive(entry.get('pid')))
        return 0
    return refresh(args.url_file, hosts)


if __name__ == '__main__':
    sys.exit(main())
