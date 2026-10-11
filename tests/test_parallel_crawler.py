import concurrent.futures
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import crawl_babadum as crawler


class OfflineClient:
    def __init__(self, interval=1, timeout=20, shared_state=None):
        self.shared = shared_state
        self.counts = {}
        self.stats = {"requests": 0, "rate_limited": 0}

    def request(self, url, data=None):
        self.stats["requests"] += 1
        if self.shared is not None:
            with self.shared["lock"]:
                self.shared["requests"].value += 1
        if data is None:
            return b"OggSrecording" if url.endswith(".ogg") else b"\x00\x00\x00\x18ftypM4A recording"
        language = urllib.parse.parse_qs(data.decode())["lang"][0]
        self.counts[language] = self.counts.get(language, 0) + 1
        concept = str(self.counts[language])
        return json.dumps({"type": "getWord", "data": {"words": [{
            "word_key": concept, "id": language + concept,
            "lang_key": language, "word": "word " + concept,
            "audio_file": "word_" + language + concept,
            "img": '<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>',
        }]}}).encode()


class FailingClient(OfflineClient):
    def request(self, url, data=None):
        raise RuntimeError("simulated worker failure")


def options(folder, workers=2, metadata_only=True, rounds=2):
    return {"output_dir": folder, "workers": workers, "request_rate": 4,
            "timeout": 20, "metadata_only": metadata_only, "min_free_mb": 1,
            "rounds_per_language": rounds, "max_no_new": 100,
            "target_per_language": 10000, "round_robin": True}


class ParallelCrawlerTest(unittest.TestCase):
    def test_spawn_workers_merge_disjoint_languages_and_preserve_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            events = []
            parent = crawler.Crawler(folder, progress=events.append)
            parent.manifest["languages"] = {
                "es": {"id": 4, "words": {"99": {"id": "999", "word": "existing", "audio_file": "existing_999"}}},
                "ar": {"id": 100, "words": {"42": {"word": "preserved"}}},
            }
            parent.checkpoint()
            crawler.atomic_write(crawler.private_path(folder, "fr"), json.dumps({
                "version": 1, "languages": {"fr": {"id": 5, "words": {
                    "98": {"id": "998", "word": "private", "audio_file": "private_998"}
                }}}
            }).encode())
            result = crawler.run_parallel(parent, ["es", "fr", "de"], options(folder),
                                          context=multiprocessing.get_context("spawn"), client_factory=OfflineClient)
            self.assertEqual(result, 0)
            saved = json.loads((Path(folder) / "vocabulary.json").read_text())
            for code in ("es", "fr", "de"):
                self.assertIn("1", saved["languages"][code]["words"])
                self.assertIn("2", saved["languages"][code]["words"])
                private = json.loads(crawler.private_path(folder, code).read_text())
                self.assertEqual(list(private["languages"]), [code])
            self.assertIn("99", saved["languages"]["es"]["words"])
            self.assertIn("98", saved["languages"]["fr"]["words"])
            self.assertIn("42", saved["languages"]["ar"]["words"])
            self.assertEqual(events[-1]["requests"], 6)
            ownership = {}
            for event in events:
                if "language" in event:
                    ownership.setdefault(event["language"], set()).add(event["worker"])
            self.assertTrue(all(len(workers) == 1 for workers in ownership.values()))

    def test_workers_share_images_and_publish_both_audio_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = crawler.Crawler(folder, progress=lambda event: None)
            result = crawler.run_parallel(parent, ["es", "fr"], options(folder, metadata_only=False, rounds=1),
                                          context=multiprocessing.get_context("spawn"), client_factory=OfflineClient)
            self.assertEqual(result, 0)
            for code in ("es", "fr"):
                entry = parent.manifest["languages"][code]["words"]["1"]
                self.assertTrue((Path(folder) / entry["audio"]).is_file())
                self.assertTrue((Path(folder) / entry["audio_alt"]).is_file())
            self.assertEqual(len(list((Path(folder) / "media/images").glob("*.svg"))), 1)
            self.assertFalse(list(Path(folder).rglob("*.tmp")))

    def test_unexpected_worker_failure_is_reported_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            events = []
            parent = crawler.Crawler(folder, progress=events.append)
            result = crawler.run_parallel(parent, ["es", "fr"], options(folder),
                                          context=multiprocessing.get_context("spawn"), client_factory=FailingClient)
            self.assertEqual(result, 1)
            self.assertTrue(any(event.get("phase") == "worker_error" for event in events))
            self.assertTrue(events[-1]["failed"])
            self.assertTrue((Path(folder) / "vocabulary.json").is_file())

    def test_parent_interrupt_finally_merges_children_checkpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            events = []

            def progress(event):
                events.append(event)
                if "round" in event:
                    raise KeyboardInterrupt

            parent = crawler.Crawler(folder, progress=progress)
            result = crawler.run_parallel(parent, ["es", "fr"], options(folder, rounds=20),
                                          context=multiprocessing.get_context("spawn"), client_factory=OfflineClient)
            self.assertEqual(result, 130)
            self.assertTrue(events[-1]["interrupted"])
            for code in ("es", "fr"):
                private = json.loads(crawler.private_path(folder, code).read_text())
                self.assertEqual(parent.manifest["languages"][code], private["languages"][code])

    def test_atomic_writes_to_same_image_have_unique_temporary_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "1.svg"
            payloads = [(str(index) * 10000).encode() for index in range(8)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda payload: crawler.atomic_write(path, payload), payloads))
            self.assertIn(path.read_bytes(), payloads)
            self.assertFalse(list(Path(folder).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
