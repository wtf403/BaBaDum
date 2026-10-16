#!/usr/bin/env python3
"""Collect bounded public game rounds into a resumable local media library.

No answers are submitted. API rounds are random, so a run is not guaranteed to
cover every word. Re-run to extend the same manifest and retry missing media.
"""

import argparse
import http.client
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time
import queue
import urllib.error
import urllib.parse
import urllib.request


LANGUAGES = {
    "es": 4, "gb": 7, "us": 1, "pl": 2, "de": 3, "fr": 5,
    "it": 6, "ru": 8, "jp": 9, "se": 10, "gr": 11, "cz": 14,
    "lt": 15, "pt": 16, "ro": 18, "hu": 23, "da": 12, "cn": 13,
    "eo": 24, "tr": 25, "uk": 26,
}
BASE_URL = "https://babadum.xyz"
MAX_RESPONSE = 4 * 1024 * 1024


class DiskSpaceError(RuntimeError):
    pass


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o644)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class HTTPClient:
    def __init__(self, interval=1.0, timeout=20, retries=2, shared_state=None):
        minimum_interval = 0.125 if shared_state is not None else 0.5
        if interval < minimum_interval:
            raise ValueError("interval must be at least {} seconds".format(minimum_interval))
        self.interval = interval
        self.timeout = timeout
        self.retries = retries
        self.last_request = None
        self.cooldown_until = 0
        self.shared_state = shared_state
        self._stats = {"requests": 0, "retries": 0, "transport_errors": 0,
                       "rate_limited": 0, "status_counts": {}}

    @property
    def stats(self):
        return dict(self._stats, status_counts=dict(self._stats["status_counts"]))

    def _wait(self):
        now = time.monotonic()
        delay = max(0, self.cooldown_until - now)
        if self.last_request is not None:
            delay = max(delay, self.interval - (now - self.last_request))
        if delay > 0:
            time.sleep(delay)
            now = time.monotonic()
        shared = self.shared_state
        if shared is not None:
            while True:
                with shared["lock"]:
                    now = time.monotonic()
                    delay = max(shared["next_request"].value,
                                shared["cooldown_until"].value) - now
                    if delay <= 0:
                        shared["next_request"].value = now + self.interval
                        shared["requests"].value += 1
                        break
                time.sleep(delay)
        self.last_request = now

    def _defer(self, seconds):
        until = time.monotonic() + seconds
        self.cooldown_until = max(self.cooldown_until, until)
        if self.shared_state is not None:
            with self.shared_state["lock"]:
                value = self.shared_state["cooldown_until"]
                value.value = max(value.value, until)

    @staticmethod
    def _retry_after(headers):
        value = headers.get("Retry-After") if headers else None
        if value is None:
            return None
        try:
            seconds = float(value)
            if seconds >= 0 and seconds < float("inf"):
                return seconds
        except (ValueError, TypeError):
            pass
        try:
            from email.utils import parsedate_to_datetime
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError, AttributeError):
            return None

    def _status(self, code):
        counts = self._stats["status_counts"]
        counts[code] = counts.get(code, 0) + 1

    def request(self, url, data=None):
        for attempt in range(self.retries + 1):
            if attempt:
                self._stats["retries"] += 1
            self._wait()
            self._stats["requests"] += 1
            headers = {"User-Agent": "BaBaDumLocalLibrary/1.0"}
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self._status(getattr(response, "status", 200))
                    length = getattr(response, "headers", {}).get("Content-Length")
                    expected = int(length) if length is not None else None
                    if expected is not None and expected > MAX_RESPONSE:
                        raise ValueError("upstream response exceeds size limit")
                    result = response.read(MAX_RESPONSE + 1)
                    if expected is not None and len(result) < expected:
                        raise http.client.IncompleteRead(result, expected - len(result))
                if len(result) > MAX_RESPONSE:
                    raise ValueError("upstream response exceeds size limit")
                return result
            except urllib.error.HTTPError as error:
                self._status(error.code)
                retry_after = self._retry_after(error.headers)
                error.close()
                if error.code == 429:
                    self._stats["rate_limited"] += 1
                    if self.shared_state is not None:
                        with self.shared_state["lock"]:
                            self.shared_state["rate_limited"].value += 1
                    self._defer(retry_after if retry_after is not None else min(30 * 2 ** attempt, 120))
                elif error.code == 503 and retry_after is not None:
                    self._defer(retry_after)
                if error.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise
                if error.code == 429 or (error.code == 503 and retry_after is not None):
                    continue
            except (OSError, http.client.HTTPException) as error:
                self._stats["transport_errors"] += 1
                if attempt == self.retries:
                    # Normalize exhausted transport failures for the per-round
                    # error/checkpoint handling, without publishing partial data.
                    if isinstance(error, urllib.error.URLError):
                        raise
                    raise urllib.error.URLError(error) from error
            time.sleep(min(2 ** (attempt + 1), 8))


class Crawler:
    def __init__(self, output_dir, client=None, metadata_only=False, progress=None, min_free_mb=512,
                 manifest_path=None):
        self.output_dir = Path(output_dir)
        self.manifest_path = Path(manifest_path) if manifest_path else self.output_dir / "vocabulary.json"
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

    def run(self, languages, rounds_per_language=100, max_no_new=100, target_per_language=1500,
            round_robin=False):
        def schedule():
            if round_robin:
                for number in range(1, rounds_per_language + 1):
                    for language in languages:
                        yield language, number
            else:
                for language in languages:
                    for number in range(1, rounds_per_language + 1):
                        yield language, number

        backfilled = set()
        finished = set()
        no_new = {code: 0 for code in languages}
        for code, round_number in schedule():
            if len(finished) == len(languages):
                break
            if code in finished:
                continue
            if code not in backfilled and not self.metadata_only:
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
            backfilled.add(code)
            total, audio_count = self.coverage(code)
            if (total if self.metadata_only else audio_count) >= target_per_language:
                finished.add(code)
                continue
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
            no_new[code] = no_new[code] + 1 if new_words == 0 else 0
            if no_new[code] >= max_no_new or round_number == rounds_per_language:
                finished.add(code)


def private_path(output_dir, code):
    return Path(output_dir) / ".workers" / (code + ".json")


def merge_private(manifest, output_dir, code):
    path = private_path(output_dir, code)
    if not path.exists():
        return
    saved = json.loads(path.read_text("utf-8"))
    language = saved.get("languages", {}).get(code)
    if (saved.get("version") != 1 or not isinstance(language, dict) or
            language.get("id") != LANGUAGES[code] or not isinstance(language.get("words"), dict)):
        raise ValueError("malformed private language checkpoint: " + code)
    current = manifest["languages"].setdefault(code, {"id": LANGUAGES[code], "words": {}})
    current["words"].update(language["words"])


class WorkerCrawler(Crawler):
    """Own only assigned languages; the parent alone writes the public manifest."""

    def __init__(self, output_dir, codes, **kwargs):
        self.codes = codes
        super().__init__(output_dir, manifest_path=private_path(output_dir, codes[0]), **kwargs)
        for code in codes[1:]:
            merge_private(self.manifest, output_dir, code)

    def checkpoint(self):
        for code in self.codes:
            language = self.manifest["languages"].get(code)
            if language is not None:
                atomic_write(private_path(self.output_dir, code), json.dumps(
                    {"version": 1, "languages": {code: language}},
                    ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def worker_entry(index, codes, options, shared_state, messages, stop, client_factory=None):
    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    job = None
    client = None
    status = 0
    try:
        factory = client_factory or HTTPClient
        client = factory(interval=1.0 / options["request_rate"], timeout=options["timeout"],
                         shared_state=shared_state)

        def progress(event):
            event["worker"] = index
            event["http"] = getattr(client, "stats", {})
            messages.put({"type": "progress", "event": event})
            if stop.is_set():
                raise KeyboardInterrupt

        job = WorkerCrawler(options["output_dir"], codes, client=client,
                            metadata_only=options["metadata_only"], progress=progress,
                            min_free_mb=options["min_free_mb"])
        job.run(codes, options["rounds_per_language"], options["max_no_new"],
                options["target_per_language"], round_robin=options["round_robin"])
    except KeyboardInterrupt:
        status = 130
    except Exception as error:
        status = 1
        messages.put({"type": "error", "worker": index,
                      "error": type(error).__name__ + ": " + str(error)})
    finally:
        # Finish the final atomic checkpoint even if a service manager sends a
        # second termination signal while this worker is shutting down.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if job is not None:
            try:
                job.checkpoint()
            except Exception as error:
                status = 1
                messages.put({"type": "error", "worker": index,
                              "error": "checkpoint: " + str(error)})
        messages.put({"type": "done", "worker": index, "status": status,
                      "http": getattr(client, "stats", {}) if client is not None else {}})
    if status == 1:
        raise SystemExit(1)


def run_parallel(parent, languages, options, context=None, client_factory=None):
    context = context or multiprocessing.get_context("spawn")
    count = min(options["workers"], len(languages))
    shared = {"lock": context.Lock(), "next_request": context.Value("d", 0.0),
              "cooldown_until": context.Value("d", 0.0), "requests": context.Value("i", 0),
              "rate_limited": context.Value("i", 0)}
    messages = context.Queue()
    stop = context.Event()
    processes = []
    failed = interrupted = False
    # A private checkpoint may be newer than the public one after a crash.
    for code in languages:
        merge_private(parent.manifest, parent.output_dir, code)
        language = parent.manifest["languages"].setdefault(code, {"id": LANGUAGES[code], "words": {}})
        atomic_write(private_path(parent.output_dir, code), json.dumps(
            {"version": 1, "languages": {code: language}},
            ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    parent.checkpoint()

    def stop_children():
        if stop.is_set():
            return
        stop.set()
        for process in processes:
            if process.is_alive():
                process.terminate()

    try:
        for index in range(count):
            codes = languages[index::count]
            process = context.Process(target=worker_entry, args=(
                index, codes, options, shared, messages, stop, client_factory))
            process.start()
            processes.append(process)
        parent.progress({"phase": "parallel_start", "workers": count,
                         "pids": [process.pid for process in processes],
                         "request_rate": options["request_rate"]})
        while True:
            try:
                message = messages.get(timeout=0.2)
            except queue.Empty:
                if any(process.exitcode not in (None, 0) for process in processes) and not stop.is_set():
                    failed = True
                    stop_children()
                if not any(process.is_alive() for process in processes):
                    break
                continue
            if message["type"] == "progress":
                event = message["event"]
                merge_private(parent.manifest, parent.output_dir, event["language"])
                parent.checkpoint()
                event["total_words"] = sum(len(language["words"]) for language in parent.manifest["languages"].values())
                event["http_global"] = {"requests": shared["requests"].value,
                                        "rate_limited": shared["rate_limited"].value}
                parent.progress(event)
            elif message["type"] == "error":
                parent.progress({"phase": "worker_error", "worker": message["worker"], "error": message["error"]})
                failed = True
                if not stop.is_set():
                    stop_children()
            elif message["type"] == "done" and message["status"] != 0 and not stop.is_set():
                failed = True
                stop_children()
    except KeyboardInterrupt:
        interrupted = True
        stop_children()
    finally:
        cleanup_handlers = {sig: signal.signal(sig, signal.SIG_IGN)
                            for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            if any(process.is_alive() for process in processes):
                stop_children()
            deadline = time.monotonic() + 25
            # Keep draining while children flush their Queue feeder threads, so an
            # interrupted parent cannot deadlock a child during its final checkpoint.
            while any(process.is_alive() for process in processes) and time.monotonic() < deadline:
                try:
                    messages.get(timeout=0.1)
                except queue.Empty:
                    pass
            for process in processes:
                process.join(max(0, deadline - time.monotonic()))
                if process.is_alive():
                    process.kill()
                    process.join()
                    failed = True
                elif process.exitcode not in (0, None) and not interrupted:
                    failed = True
            for code in languages:
                merge_private(parent.manifest, parent.output_dir, code)
            parent.checkpoint()
            parent.progress({"phase": "parallel_complete", "workers": count,
                             "requests": shared["requests"].value,
                             "rate_limited": shared["rate_limited"].value,
                             "interrupted": interrupted, "failed": failed})
            messages.close()
            messages.join_thread()
        finally:
            for sig, handler in cleanup_handlers.items():
                signal.signal(sig, handler)
    return 130 if interrupted else 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", default="all", help="Comma-separated playable codes, or all")
    parser.add_argument("--rounds-per-language", type=int, default=100)
    parser.add_argument("--max-no-new", type=int, default=100)
    parser.add_argument("--target-per-language", type=int, default=1500)
    parser.add_argument("--min-free-mb", type=int, default=512)
    parser.add_argument("--output-dir", default="data/library")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--round-robin", action="store_true", help="Rotate one round per language each cycle")
    parser.add_argument("--workers", type=int, default=1, help="Parallel language workers, 1–21")
    parser.add_argument("--request-rate", type=float, default=4.0, help="Global parallel request starts/second, 1–8")
    parser.add_argument("--interval", type=float, default=1.0, help="Global request interval, at least 0.5 seconds")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args(argv)
    languages = list(LANGUAGES) if args.languages == "all" else list(dict.fromkeys(args.languages.split(",")))
    if not languages or any(code not in LANGUAGES for code in languages):
        parser.error("languages must be playable codes: " + ",".join(LANGUAGES))
    if (not 1 <= args.rounds_per_language <= 5000 or args.max_no_new < 1 or args.timeout <= 0 or
            args.interval < 0.5 or args.target_per_language < 1 or args.min_free_mb < 1):
        parser.error("rounds must be 1–5000; limits and timeout must be positive; interval must be at least 0.5")
    if not 1 <= args.workers <= 21 or not 1 <= args.request_rate <= 8:
        parser.error("workers must be 1–21 and parallel request rate must be 1–8")
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
            if args.workers > 1:
                return run_parallel(crawler, languages, vars(args))
            crawler.run(languages, args.rounds_per_language, args.max_no_new, args.target_per_language,
                        round_robin=args.round_robin)
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
