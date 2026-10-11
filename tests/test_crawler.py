import importlib.util
import io
import json
import signal
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location("crawl_babadum", Path(__file__).parents[1] / "scripts/crawl_babadum.py")
crawler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawler)


def sample(concept="1253", stem="volar_3141"):
    return {"word_key": concept, "id": "3141", "word": "volar", "lang_key": "4",
            "audio_file": stem, "img": '<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>'}


class FakeClient:
    def __init__(self, words=None, missing_ogg=False):
        self.words = words if words is not None else [sample()]
        self.requests = []
        self.missing_ogg = missing_ogg

    def request(self, url, data=None):
        self.requests.append((url, data))
        if data is not None:
            return json.dumps({"type": "getWord", "data": {"words": self.words}}).encode()
        if url.endswith(".ogg"):
            if self.missing_ogg:
                raise urllib.error.HTTPError(url, 404, "missing", {}, None)
            return b"OggSrecording"
        return b"\x00\x00\x00\x18ftypM4A recording"


class CrawlerTest(unittest.TestCase):
    def test_round_is_scoring_free_and_downloads_exact_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient()
            events = []
            job = crawler.Crawler(folder, client, progress=events.append)
            job.run(["es"], 1)
            form = urllib.parse.parse_qs(client.requests[0][1].decode())
            self.assertEqual(form["type"], ["getWord"])
            self.assertEqual(form["lang"], ["4"])
            self.assertNotIn("a", form)
            self.assertEqual(client.requests[1][0], "https://babadum.com/audio/es/volar_3141.ogg")
            saved = json.loads((Path(folder) / "vocabulary.json").read_text())
            entry = saved["languages"]["es"]["words"]["1253"]
            self.assertEqual(entry["id"], "3141")
            self.assertEqual((Path(folder) / entry["audio"]).read_bytes(), b"OggSrecording")
            self.assertTrue(entry["audio_alt"].endswith(".m4a"))
            self.assertTrue((Path(folder) / entry["audio_alt"]).is_file())
            self.assertIn("<svg", (Path(folder) / entry["image"]).read_text())
            self.assertEqual(events[0]["new_words"], 1)

    def test_resume_reuses_media_and_stops_after_no_new(self):
        with tempfile.TemporaryDirectory() as folder:
            crawler.Crawler(folder, FakeClient(), progress=lambda e: None).run(["es"], 1)
            client = FakeClient()
            events = []
            crawler.Crawler(folder, client, progress=events.append).run(["es"], 10, max_no_new=2)
            self.assertEqual(len(events), 2)
            self.assertEqual(len(client.requests), 2)
            self.assertTrue(all(data is not None for _, data in client.requests))

    def test_metadata_only_can_resume_to_download_missing_media(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient()
            crawler.Crawler(folder, client, metadata_only=True, progress=lambda e: None).run(["es"], 1)
            self.assertEqual(len(client.requests), 1)
            client = FakeClient(missing_ogg=True)
            job = crawler.Crawler(folder, client, progress=lambda e: None)
            job.run(["es"], 1)
            entry = job.manifest["languages"]["es"]["words"]["1253"]
            self.assertTrue(entry["audio"].endswith(".m4a"))
            self.assertTrue((Path(folder) / entry["audio"]).is_file())

    def test_backfill_does_not_require_random_rediscovery(self):
        with tempfile.TemporaryDirectory() as folder:
            crawler.Crawler(folder, FakeClient(), metadata_only=True, progress=lambda e: None).run(["es"], 1)
            client = FakeClient(words=[])
            events = []
            job = crawler.Crawler(folder, client, progress=events.append)
            job.run(["es"], 1, target_per_language=1)
            self.assertEqual(len(client.requests), 2)
            self.assertIsNone(client.requests[0][1])
            self.assertEqual(events[0]["phase"], "backfill")

    def test_resume_backfills_alternate_without_api_rediscovery(self):
        with tempfile.TemporaryDirectory() as folder:
            job = crawler.Crawler(folder, FakeClient(), progress=lambda e: None)
            job.run(["es"], 1)
            entry = job.manifest["languages"]["es"]["words"]["1253"]
            (Path(folder) / entry.pop("audio_alt")).unlink()
            job.checkpoint()
            client = FakeClient(words=[])
            resumed = crawler.Crawler(folder, client, progress=lambda e: None)
            resumed.run(["es"], 1, target_per_language=1)
            self.assertEqual(len(client.requests), 1)
            self.assertTrue(client.requests[0][0].endswith(".m4a"))
            self.assertEqual(resumed.coverage("es"), (1, 1))

    def test_expected_missing_format_is_not_an_error_or_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient(missing_ogg=True)
            events = []
            job = crawler.Crawler(folder, client, progress=events.append)
            job.run(["es"], 2)
            self.assertTrue(all(event["errors"] == 0 for event in events))
            audio_requests = [url for url, data in client.requests if data is None]
            self.assertEqual(len(audio_requests), 2)
            self.assertEqual(job.coverage("es"), (1, 1))

    def test_resume_repairs_media_written_before_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            job = crawler.Crawler(folder, FakeClient(), progress=lambda e: None)
            job.run(["es"], 1)
            entry = job.manifest["languages"]["es"]["words"]["1253"]
            alternate = entry.pop("audio_alt")
            job.checkpoint()
            client = FakeClient(words=[])
            resumed = crawler.Crawler(folder, client, progress=lambda e: None)
            resumed.run(["es"], 1, target_per_language=1)
            self.assertEqual(client.requests, [])
            self.assertEqual(resumed.manifest["languages"]["es"]["words"]["1253"]["audio_alt"], alternate)

    def test_low_disk_stops_before_any_network_request(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient()
            job = crawler.Crawler(folder, client, progress=lambda e: None)
            with patch.object(crawler.shutil, "disk_usage") as usage:
                usage.return_value.free = 100
                with self.assertRaises(crawler.DiskSpaceError):
                    job.run(["es"], 1)
            self.assertEqual(client.requests, [])

    def test_rejects_wrong_language_and_unsafe_media_path(self):
        with tempfile.TemporaryDirectory() as folder:
            wrong = sample()
            wrong["lang_key"] = "5"
            client = FakeClient([wrong, sample(stem="../escape")])
            job = crawler.Crawler(folder, client, progress=lambda e: None)
            job.run(["es"], 1)
            self.assertEqual(job.manifest["languages"]["es"]["words"], {})
            self.assertEqual(len(client.requests), 1)

    def test_invalid_audio_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient()
            original = client.request
            client.request = lambda url, data=None: original(url, data) if data else b"<html>error</html>"
            job = crawler.Crawler(folder, client, progress=lambda e: None)
            job.run(["es"], 1)
            entry = job.manifest["languages"]["es"]["words"]["1253"]
            self.assertNotIn("audio", entry)
            self.assertTrue((Path(folder) / "vocabulary.json").is_file())

    def test_malformed_round_does_not_abort_remaining_rounds(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient()
            responses = iter([b"[]", b'{"type":"getWord","data":null}',
                              b'{"type":"getWord","data":{"words":[null]}}'])
            client.request = lambda url, data=None: next(responses)
            events = []
            job = crawler.Crawler(folder, client, metadata_only=True, progress=events.append)
            job.run(["es"], 3)
            self.assertEqual(len(events), 3)
            self.assertTrue(all(event["errors"] == 1 for event in events))

    def test_http_pacing_covers_api_and_audio(self):
        client = crawler.HTTPClient(interval=1)
        with patch.object(crawler.time, "monotonic", side_effect=[10, 10.2, 11]), \
                patch.object(crawler.time, "sleep") as sleep, \
                patch.object(crawler.urllib.request, "urlopen", side_effect=[io.BytesIO(b"{}"), io.BytesIO(b"OggS")]):
            client.request("https://babadum.com/get.php", b"type=getWord")
            client.request("https://babadum.com/audio/es/volar_3141.ogg")
        self.assertAlmostEqual(sleep.call_args.args[0], 0.8)

    def test_service_stop_checkpoints_and_restores_signal_handlers(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Mock()
            job.run.side_effect = lambda *args: signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
            with patch.object(crawler, "Crawler", return_value=job):
                status = crawler.main(["--output-dir", folder, "--languages", "es", "--rounds-per-language", "1"])
            self.assertEqual(status, 130)
            job.checkpoint.assert_called_once_with()
            for sig, handler in previous.items():
                self.assertEqual(signal.getsignal(sig), handler)


if __name__ == "__main__":
    unittest.main()
