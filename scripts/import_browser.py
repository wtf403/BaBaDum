#!/usr/bin/env python3
"""Import compact rounds downloaded from babadum.com through Chrome."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawl_babadum import Crawler, LANGUAGES


def load_groups(path: Path) -> dict[str, list[dict]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    groups: dict[str, list[dict]] = {}
    if isinstance(value, dict) and value.get("type") == "getWord":
        data = value.get("data", {})
        code = data.get("lang")
        if code in LANGUAGES:
            groups[code] = list(data.get("words", []))
        return groups
    if not isinstance(value, list):
        raise ValueError("unsupported browser capture format")
    for item in value:
        if not isinstance(item, dict):
            continue
        code = item.get("l")
        if code not in LANGUAGES:
            continue
        groups.setdefault(code, []).append({
            "word_key": item.get("k"),
            "id": item.get("id"),
            "word": item.get("t"),
            "audio_file": item.get("af"),
            "color_key": item.get("c"),
            "lang_key": LANGUAGES[code],
        })
    return groups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--root", type=Path, default=Path("data/library"))
    args = parser.parse_args()
    crawler = Crawler(args.root, metadata_only=True)
    totals: dict[str, list[int]] = {}
    for capture in args.captures:
        for code, words in load_groups(capture).items():
            new_words, _, errors = crawler.ingest(code, words)
            score = totals.setdefault(code, [0, 0, 0])
            score[0] += new_words
            score[1] += len(words)
            score[2] += errors
    crawler.checkpoint()
    for code in sorted(totals):
        new_words, seen, errors = totals[code]
        total, _ = crawler.coverage(code)
        print(f"{code}: +{new_words} new, {seen} records, {total} total, {errors} invalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
