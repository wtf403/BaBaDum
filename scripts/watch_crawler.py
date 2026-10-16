#!/usr/bin/env python3
"""Resume collection and refresh its SOCKS route after five minutes without new words."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def count(folder, languages):
    data = json.loads((folder / 'vocabulary.json').read_text())
    return sum(len(data['languages'].get(code, {}).get('words', {})) for code in languages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-command', required=True)
    parser.add_argument('--socks-file', required=True)
    parser.add_argument('--stall-seconds', type=int, default=300)
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
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=40)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        refreshed = subprocess.run([args.refresh_command], timeout=120).returncode == 0
        if not refreshed:
            print('Proxy refresh failed; retrying in 60 seconds', flush=True)
            time.sleep(60)
            continue
        env = dict(os.environ, BABADUM_SOCKS_FILE=args.socks_file)
        with (folder / 'crawl.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, 'scripts/crawl_with_socks.py',
                '--languages', ','.join(languages), '--workers', str(len(languages)), '--request-rate', '8',
                '--rounds-per-language', '5000', '--target-per-language', '10000',
                '--max-no-new', '500'], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        (folder / 'crawl.pid').write_text(str(child.pid) + '\n')
        previous, changed = count(folder, languages), time.monotonic()
        print('Started proxy crawler', child.pid, 'words', previous, flush=True)
        while child.poll() is None:
            time.sleep(10)
            current = count(folder, languages)
            if current > previous:
                previous, changed = current, time.monotonic()
            if time.monotonic() - changed >= args.stall_seconds:
                print('No new words; checkpointing and refreshing proxy', flush=True)
                child.terminate()
                child.wait(timeout=40)
                break
        time.sleep(5)


if __name__ == '__main__':
    main()
