#!/usr/bin/env python3
"""Watch the babadum library: log git status and commit snapshots at a sane cadence.

Runs forever. Each cycle records word totals and git working-tree counts to
data/library/monitor.log (ignored by git). It makes a local snapshot commit when
the vocabulary has grown by --commit-threshold words or --commit-interval
seconds have passed with changes present. It never pushes.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

FOLDER = Path('data/library')
MANIFEST = FOLDER / 'vocabulary.json'
LOG = FOLDER / 'monitor.log'


def read_totals():
    try:
        data = json.loads(MANIFEST.read_text())
    except Exception:
        return None, 0
    languages = data.get('languages', {})
    per = {code: len(entry.get('words', {})) for code, entry in languages.items()}
    return per, sum(per.values())


def git(*args, check=False):
    result = subprocess.run(['git', *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or 'git failed: ' + ' '.join(args))
    return result


def status_counts():
    result = git('status', '--porcelain')
    untracked = sum(1 for line in result.stdout.splitlines() if line.startswith('??'))
    modified = sum(1 for line in result.stdout.splitlines() if line[:2].strip() == 'M')
    return untracked, modified


def commit_snapshot(per, total):
    git('add', 'data/library')
    detail = ', '.join('{} {}'.format(code, count)
                       for code, count in sorted(per.items(), key=lambda item: -item[1]))
    message = 'Extend local vocabulary and recordings ({}, total {})'.format(detail, total)
    result = git('commit', '-m', message)
    if result.returncode != 0:
        return None
    head = git('rev-parse', '--short', 'HEAD').stdout.strip()
    return head


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--commit-threshold', type=int, default=25)
    parser.add_argument('--commit-interval', type=int, default=1800)
    parser.add_argument('--no-commit', action='store_true')
    args = parser.parse_args()

    last_commit_total = None
    last_commit_time = time.monotonic()
    per, total = read_totals()
    if total:
        last_commit_total = total
    while True:
        per, total = read_totals()
        untracked, modified = status_counts()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with LOG.open('a') as stream:
            stream.write(json.dumps({
                'time': now, 'total': total, 'languages': per,
                'untracked': untracked, 'modified': modified,
            }, ensure_ascii=False) + chr(10))
        if not args.no_commit and last_commit_total is not None:
            grew = total - last_commit_total
            elapsed = time.monotonic() - last_commit_time
            if (grew >= args.commit_threshold or
                    (elapsed >= args.commit_interval and (untracked or modified))):
                head = commit_snapshot(per, total)
                if head:
                    last_commit_total = total
                    last_commit_time = time.monotonic()
                    with LOG.open('a') as stream:
                        stream.write(json.dumps({
                            'time': now, 'committed': head, 'total': total,
                        }, ensure_ascii=False) + chr(10))
        time.sleep(args.interval)


if __name__ == '__main__':
    sys.exit(main())
