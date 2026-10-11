#!/usr/bin/env python3
"""Collect bounded public game rounds into a resumable local media library.

No answers are submitted. API rounds are random, so a run is not guaranteed to
cover every word. Re-run to extend the same manifest and retry missing media.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


LANGUAGES = {
    "es": 4, "gb": 7, "us": 1, "pl": 2, "de": 3, "fr": 5,
    "it": 6, "ru": 8, "jp": 9, "se": 10, "gr": 11, "cz": 14,
    "lt": 15, "pt": 16, "ro": 18, "hu": 23, "da": 12, "cn": 13,
    "eo": 24, "tr": 25, "uk": 26,
}
BASE_URL = "https://babadum.com"
MAX_RESPONSE = 4 * 1024 * 1024


class DiskSpaceError(RuntimeError):
    pass


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
    os.replace(temporary, path)


class HTTPClient:
    def __init__(self, interval=1.0, timeout=20, retries=2):
        if interval < 0.5:
            raise ValueError("interval must be at least 0.5 seconds")
        self.interval = interval
        self.timeout = timeout
        self.retries = retries
        self.last_request = None

    def request(self, url, data=None):
        for attempt in range(self.retries + 1):
            if self.last_request is not None:
                delay = self.interval - (time.monotonic() - self.last_request)
                if delay > 0:
                    time.sleep(delay)
            self.last_request = time.monotonic()
            headers = {"User-Agent": "BaBaDumLocalLibrary/1.0"}
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    result = response.read(MAX_RESPONSE + 1)
                if len(result) > MAX_RESPONSE:
                    raise ValueError("upstream response exceeds size limit")
                return result
            except urllib.error.HTTPError as error:
                error.close()
                if error.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.retries:
                    raise
            time.sleep(min(2 ** (attempt + 1), 8))


class Crawler:
    def __init__(self, output_dir, client=None, metadata_only=False, progress=None, min_free_mb=512):
        self.output_dir = Path(output_dir)
        self.manifest_path = self.output_dir / "vocabulary.json"
        self.client = client if client is not None else HTTPClient()
        self.metadata_only = metadata_only
        self.min_free_mb = min_free_mb
        self.progress = progress if progress is not None else self.print_progress
        self.manifest = {"version": 1, "languages": {}}
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text("utf-8"))
            if self.manifest.get("version") != 1 or not isinstance(self.manifest.get("languages"), dict):
                raise ValueError("unsupported or malformed vocabulary manifest")

    @staticmethod
    def print_progress(event):
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def checkpoint(self):
        atomic_write(self.manifest_path,
                     json.dumps(self.manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def ensure_space(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.output_dir).free < self.min_free_mb * 1024 * 1024:
            raise DiskSpaceError("free disk space is below configured reserve")

    def coverage(self, code):
        words = self.manifest["languages"].get(code, {}).get("words", {})
        audio = sum(bool(word.get("audio") and (self.output_dir / word["audio"]).is_file())
                    for word in words.values())
        return len(words), audio

    def get_round(self, code):
        data = urllib.parse.urlencode({
            "category": "words", "type": "getWord", "lang": LANGUAGES[code],
            "game": "chooseImage", "onReceiveLocation": "Words",
        }).encode("ascii")
        result = json.loads(self.client.request(BASE_URL + "/get.php", data))
        if (not isinstance(result, dict) or result.get("type") != "getWord" or
                not isinstance(result.get("data"), dict) or
                not isinstance(result["data"].get("words"), list)):
            raise ValueError("upstream did not return a game round")
        return result["data"]["words"]

    def download_audio(self, code, entry):
        stem = entry["audio_file"]
        paths = []
        unavailable = entry.setdefault("audio_unavailable", [])
        for extension in ("ogg", "m4a"):
            relative = "media/audio/{}/{}.{}".format(code, stem, extension)
            path = self.output_dir / relative
            if path.exists() and path.stat().st_size:
                paths.append(relative)
            else:
                if extension in unavailable:
                    continue
                self.ensure_space()
                try:
                    content = self.client.request(BASE_URL + "/audio/" + code + "/" +
                                                  urllib.parse.quote(stem, safe="") + "." + extension)
                except urllib.error.HTTPError as error:
                    error.close()
                    if error.code in (404, 410):
                        unavailable.append(extension)
                        continue
                    raise
                # Reject error pages even if the upstream responds with HTTP 200.
                valid = content.startswith(b"OggS") if extension == "ogg" else content[4:8] == b"ftyp"
                if not valid:
                    raise ValueError("upstream returned invalid " + extension + " audio")
                atomic_write(path, content)
                paths.append(relative)
            # Preserve a completed primary if fetching the alternate later fails.
            entry["audio"] = paths[0]
            if len(paths) > 1:
                entry["audio_alt"] = paths[1]
        return bool(paths)

    def audio_complete(self, code, entry):
        stem = entry.get("audio_file", "")
        unavailable = entry.get("audio_unavailable", [])
        references = (entry.get("audio"), entry.get("audio_alt"))
        for extension in ("ogg", "m4a"):
            relative = "media/audio/{}/{}.{}".format(code, stem, extension)
            path = self.output_dir / relative
            if path.is_file() and path.stat().st_size:
                if relative not in references:
                    return False
            elif extension not in unavailable:
                return False
        return True

    def ingest(self, code, words):
        language = self.manifest["languages"].setdefault(code, {"id": LANGUAGES[code], "words": {}})
        new_words = audio_saved = errors = 0
        for word in words:
            if not isinstance(word, dict):
                errors += 1
                continue
            concept = str(word.get("word_key", ""))
            record_id = str(word.get("id", ""))
            stem = word.get("audio_file")
            text = word.get("word")
            if (str(word.get("lang_key")) != str(LANGUAGES[code]) or
                    not concept.isascii() or not concept.isdigit() or
                    not record_id.isascii() or not record_id.isdigit() or
                    not isinstance(text, str) or not text or
                    not isinstance(stem, str) or not stem or len(stem) > 180 or
                    any(char in stem for char in ("/", "\\", "\0")) or stem in (".", "..")):
                errors += 1
                continue
            existing = language["words"].get(concept)
            if existing is None:
                new_words += 1
            entry = {"id": record_id, "word": text, "audio_file": stem}
            if word.get("color_key") is not None:
                entry["color_key"] = str(word["color_key"])
            if existing and existing.get("audio_file") == stem:
                for key in ("image", "audio", "audio_alt", "audio_unavailable"):
                    if existing.get(key):
                        entry[key] = existing[key]
            image = word.get("img")
            if isinstance(image, str) and "<svg" in image and len(image) < MAX_RESPONSE:
                relative = "media/images/" + concept + ".svg"
                path = self.output_dir / relative
                if not path.exists():
                    self.ensure_space()
                    atomic_write(path, image.encode("utf-8"))
                entry["image"] = relative
            language["words"][concept] = entry
            if not self.metadata_only:
                had_audio = bool(entry.get("audio") and (self.output_dir / entry["audio"]).is_file())
                try:
                    if self.download_audio(code, entry) and not had_audio:
                        audio_saved += 1
                except (urllib.error.URLError, TimeoutError, ValueError):
                    errors += 1
        return new_words, audio_saved, errors

    def run(self, languages, rounds_per_language=100, max_no_new=100, target_per_language=1500):
        for code in languages:
            if not self.metadata_only:
                words = self.manifest["languages"].get(code, {}).get("words", {})
                for entry in words.values():
                    stem = entry.get("audio_file")
                    if (not isinstance(stem, str) or not stem or len(stem) > 180 or
                            any(char in stem for char in ("/", "\\", "\0")) or stem in (".", "..")):
                        continue
                    if self.audio_complete(code, entry):
                        continue
                    self.ensure_space()
                    audio_saved = errors = 0
                    try:
                        audio_saved = int(self.download_audio(code, entry))
                    except (urllib.error.URLError, TimeoutError, ValueError):
                        errors = 1
                    self.checkpoint()
                    total, audio_count = self.coverage(code)
                    self.progress({"phase": "backfill", "language": code, "words": total,
                                   "audio": audio_count, "audio_saved": audio_saved, "errors": errors})
            no_new = 0
            for round_number in range(1, rounds_per_language + 1):
                total, audio_count = self.coverage(code)
                if (total if self.metadata_only else audio_count) >= target_per_language:
                    break
                self.ensure_space()
                try:
                    new_words, audio_saved, errors = self.ingest(code, self.get_round(code))
                except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                    new_words, audio_saved, errors = 0, 0, 1
                self.checkpoint()
                total, audio_count = self.coverage(code)
                total_words = sum(len(language["words"]) for language in self.manifest["languages"].values())
                self.progress({"language": code, "round": round_number, "words": total,
                               "audio": audio_count, "target": target_per_language, "total_words": total_words,
                               "new_words": new_words, "audio_saved": audio_saved, "errors": errors})
                no_new = no_new + 1 if new_words == 0 else 0
                if no_new >= max_no_new:
                    break


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", default="all", help="Comma-separated playable codes, or all")
    parser.add_argument("--rounds-per-language", type=int, default=100)
    parser.add_argument("--max-no-new", type=int, default=100)
    parser.add_argument("--target-per-language", type=int, default=1500)
    parser.add_argument("--min-free-mb", type=int, default=512)
    parser.add_argument("--output-dir", default="data/library")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0, help="Global request interval, at least 0.5 seconds")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args(argv)
    languages = list(LANGUAGES) if args.languages == "all" else list(dict.fromkeys(args.languages.split(",")))
    if not languages or any(code not in LANGUAGES for code in languages):
        parser.error("languages must be playable codes: " + ",".join(LANGUAGES))
    if (not 1 <= args.rounds_per_language <= 5000 or args.max_no_new < 1 or args.timeout <= 0 or
            args.interval < 0.5 or args.target_per_language < 1 or args.min_free_mb < 1):
        parser.error("rounds must be 1–5000; limits and timeout must be positive; interval must be at least 0.5")
    # Concurrent processes must not overwrite each other's manifest checkpoints.
    import fcntl
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".crawler.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("another crawler already owns this output directory")
        crawler = Crawler(output_dir, HTTPClient(args.interval, args.timeout), args.metadata_only,
                          min_free_mb=args.min_free_mb)

        def interrupted(signum, frame):
            raise KeyboardInterrupt

        # Background shells can inherit SIGINT as ignored; install both handlers
        # explicitly so Ctrl+C and service stop checkpoint the current work.
        previous_handlers = {signum: signal.signal(signum, interrupted)
                             for signum in (signal.SIGINT, signal.SIGTERM)}
        try:
            crawler.run(languages, args.rounds_per_language, args.max_no_new, args.target_per_language)
        except DiskSpaceError:
            crawler.checkpoint()
            crawler.progress({"stopped": "low_disk_space", "min_free_mb": args.min_free_mb})
            return 2
        except KeyboardInterrupt:
            crawler.checkpoint()
            return 130
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
