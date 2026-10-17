#!/usr/bin/env python3
"""Resume collection and refresh its SOCKS route when the route stops working.

Handles two failures: the crawler child dying, and the proxy route dying. A
route that listens locally but no longer reaches babadum.com is treated as dead,
so IP-level blocks trigger a refresh instead of silent error loops. Refresh
failures back off so a blocked pool is probed gently rather than hammered.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

PROBE_DATA = 'category=words&type=getWord&lang=1&game=chooseImage&onReceiveLocation=Words'
PROBE_URL = 'https://babadum.com/get.php'
UA = 'BaBaDumLocalLibrary/1.0'


def count(folder, languages):
    data = json.loads((folder / 'vocabulary.json').read_text())
    return sum(len(data['languages'].get(code, {}).get('words', {})) for code in languages)


def terminate_child(child, grace=45):
    """Stop the crawler child without letting a slow shutdown kill the watcher."""
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        child.kill()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass



def cleanup_orphans(grace=15):
    """Terminate crawler processes orphaned by a previous watcher.

    A crawler stuck in shutdown keeps the output directory lock, so every new
    crawler would exit immediately and collection would silently stop. Only
    processes reparented to init are touched; the current child never is.
    """
    try:
        listing = subprocess.run(['ps', '-eo', 'pid=,ppid=,command='],
                                 capture_output=True, text=True).stdout
    except OSError:
        return
    victims = []
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, ppid, command = parts
        if ppid == '1' and 'crawl_with_socks.py' in command:
            try:
                victims.append(int(pid))
            except ValueError:
                pass
    for pid in victims:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + grace
    while victims and time.monotonic() < deadline:
        victims = [pid for pid in victims if _alive(pid)]
        if victims:
            time.sleep(1)
    for pid in victims:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        print('Killed orphan crawler', pid, flush=True)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def route_ok(socks_file, timeout=20):
    """True when the proxy listed in socks_file returns a real babadum round."""
    try:
        proxy = urlsplit(Path(socks_file).read_text().strip())
    except OSError:
        return False
    if proxy.scheme not in ('socks5', 'socks5h') or not proxy.hostname or not proxy.port:
        return False
    url = 'socks5h://{}:{}'.format(proxy.hostname, proxy.port)
    result = subprocess.run([
        'curl', '-sS', '--max-time', str(timeout), '--proxy', url,
        '-A', UA, '-e', 'https://babadum.com/', '-d', PROBE_DATA, PROBE_URL,
    ], capture_output=True)
    try:
        payload = json.loads(result.stdout.decode('utf-8', 'replace'))
    except Exception:
        return False
    return result.returncode == 0 and payload.get('type') == 'getWord' and bool(
        payload.get('data', {}).get('words'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-command', required=True)
    parser.add_argument('--socks-file', required=True)
    parser.add_argument('--stall-seconds', type=int, default=300)
    parser.add_argument('--proxy-check-seconds', type=int, default=60)
    parser.add_argument('--request-rate', default='2')
    parser.add_argument('--languages', default='all')
    args = parser.parse_args()
    import crawl_babadum
    languages = list(crawl_babadum.LANGUAGES) if args.languages == 'all' else args.languages.split(',')
    if not languages or any(code not in crawl_babadum.LANGUAGES for code in languages):
        parser.error('Unknown language code')
    folder = Path('data/library')
    lock = (folder / '.watcher.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    child = None

    def stop(*_):
        terminate_child(child)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    failures = 0
    while True:
        refreshed = subprocess.run(shlex.split(args.refresh_command), timeout=600).returncode == 0
        if not refreshed or not route_ok(args.socks_file):
            failures += 1
            delay = min(60 * (2 ** (failures - 1)), 600)
            print('Proxy unavailable; retrying in {} seconds'.format(delay), flush=True)
            time.sleep(delay)
            continue
        failures = 0
        cleanup_orphans()
        env = dict(os.environ, BABADUM_SOCKS_FILE=args.socks_file)
        with (folder / 'crawl.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, 'scripts/crawl_with_socks.py',
                '--languages', ','.join(languages), '--workers', str(len(languages)),
                '--request-rate', args.request_rate,
                '--rounds-per-language', '5000', '--target-per-language', '10000',
                '--max-no-new', '500'], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        (folder / 'crawl.pid').write_text(str(child.pid) + '\n')
        previous, changed = count(folder, languages), time.monotonic()
        last_proxy_check = time.monotonic()
        print('Started proxy crawler', child.pid, 'words', previous, flush=True)
        while child.poll() is None:
            time.sleep(10)
            now = time.monotonic()
            if now - last_proxy_check >= args.proxy_check_seconds:
                last_proxy_check = now
                if not route_ok(args.socks_file):
                    print('Proxy route dead; checkpointing and refreshing proxy', flush=True)
                    terminate_child(child)
                    break
            current = count(folder, languages)
            if current > previous:
                previous, changed = current, now
            if now - changed >= args.stall_seconds:
                print('No new words; checkpointing and refreshing proxy', flush=True)
                terminate_child(child)
                break
        time.sleep(5)


if __name__ == '__main__':
    main()
