#!/usr/bin/env python3
"""Import public menu translations; gameplay never uses this upstream endpoint."""
import argparse
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

CODES = 'gb us pl de es fr it ru jp se gr cz lt pt ro nl af no hu da cn eo tr uk fi sr'.split()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--languages', default=','.join(CODES))
    parser.add_argument('--endpoint', default='https://babadum.com/get.php')
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / 'data/local-api/interfaces'
    destination.mkdir(parents=True, exist_ok=True)
    failed = []
    for code in args.languages.split(','):
        if code not in CODES:
            parser.error('Unknown interface language: ' + code)
        path = destination / (code + '.json')
        if path.exists():
            continue
        body = urllib.parse.urlencode({'type':'changeLang', 'category':'utils', 'lang_code':code,
                                       'onReceiveLocation':'UserMenu'}).encode()
        for attempt in range(3):
            try:
                request = urllib.request.Request(args.endpoint, data=body,
                    headers={'User-Agent':'Mozilla/5.0', 'Referer':'https://babadum.com/'})
                with urllib.request.urlopen(request, timeout=20) as response:
                    value = json.load(response)
                interface = value.get('interface')
                if not isinstance(interface, dict) or interface.get('lang_code') != code or 'play' not in interface:
                    raise ValueError('Invalid interface response')
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'interface':interface}, ensure_ascii=False, indent=2)+'\n')
                temporary.replace(path)
                print(code + ': cached', flush=True)
                break
            except Exception as error:
                if attempt == 2:
                    print(code + ': ' + type(error).__name__, flush=True)
                    failed.append(code)
                else:
                    time.sleep(2)
        time.sleep(1)
    return bool(failed)

if __name__ == '__main__':
    raise SystemExit(main())
