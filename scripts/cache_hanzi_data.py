#!/usr/bin/env python3
"""Cache pinned Hanzi Writer stroke data for the local Chinese vocabulary."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('data/library/vocabulary.json'))
    parser.add_argument('--output-dir', type=Path, default=Path('data/hanzi'))
    args = parser.parse_args()
    words = json.loads(args.manifest.read_text('utf-8')).get('languages', {}).get('cn', {}).get('words', {})
    characters = sorted({char for word in words.values() for char in word['word']
                         if '\u3400' <= char <= '\u9fff' or '\U00020000' <= char <= '\U0002fa1f'})
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def valid(data):
        return (isinstance(data, dict) and isinstance(data.get('strokes'), list) and
                isinstance(data.get('medians'), list) and data['strokes'] and
                len(data['strokes']) == len(data['medians']))

    def download(character):
        path = args.output_dir / (character + '.json')
        if path.is_file():
            try:
                if valid(json.loads(path.read_text('utf-8'))):
                    return True
            except (OSError, ValueError):
                pass
        try:
            url = 'https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0/' + urllib.parse.quote(character) + '.json'
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read(1024 * 1024))
            if not valid(data):
                raise ValueError('invalid stroke data')
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), 'utf-8')
            temporary.replace(path)
            return True
        except (OSError, ValueError) as error:
            print('Failed {}: {}'.format(character, error), flush=True)
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(download, characters))
    print(json.dumps({'characters':len(characters),'cached':sum(results),'failed':results.count(False)}))
    return 1 if False in results else 0


if __name__ == '__main__':
    raise SystemExit(main())
