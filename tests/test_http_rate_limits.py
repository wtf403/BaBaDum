import importlib.util
import io
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('http_crawler', Path(__file__).parents[1] / 'scripts/crawl_babadum.py')
crawler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawler)


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


def shared():
    return {'lock': threading.Lock(), 'next_request': SimpleNamespace(value=0),
            'cooldown_until': SimpleNamespace(value=0), 'requests': SimpleNamespace(value=0),
            'rate_limited': SimpleNamespace(value=0)}


def error(code, retry_after=None):
    headers = {} if retry_after is None else {'Retry-After': retry_after}
    return urllib.error.HTTPError('https://babadum.xyz/get.php', code, 'retry', headers, None)


class RateLimitsTests(unittest.TestCase):
    def run_requests(self, client, responses, clock):
        with patch.object(crawler.time, 'monotonic', side_effect=lambda: clock.now), \
                patch.object(crawler.time, 'sleep', side_effect=clock.sleep), \
                patch.object(crawler.urllib.request, 'urlopen', side_effect=responses):
            return client.request('https://babadum.xyz/get.php')

    def test_retry_after_seconds_is_not_capped_and_stats_are_observable(self):
        client, clock = crawler.HTTPClient(retries=1), Clock()
        self.assertEqual(self.run_requests(client, [error(429,'300'), io.BytesIO(b'ok')], clock), b'ok')
        self.assertEqual(clock.sleeps, [300])
        self.assertEqual(client.stats, {'requests':2,'retries':1,'transport_errors':0,
                                       'rate_limited':1,'status_counts':{429:1,200:1}})
        client.stats['status_counts'][429] = 99
        self.assertEqual(client.stats['status_counts'][429],1)

    def test_http_date_retry_after_and_503(self):
        from email.utils import formatdate
        client, clock = crawler.HTTPClient(retries=1), Clock()
        with patch.object(crawler.time, 'time', return_value=1000):
            self.run_requests(client, [error(503,formatdate(1090,usegmt=True)),io.BytesIO(b'ok')],clock)
        self.assertEqual(clock.sleeps,[90])
        self.assertEqual(client.stats['rate_limited'],0)
        self.assertEqual(client.stats['status_counts'][503],1)

    def test_default_429_backoff_grows_and_publishes_final_cooldown(self):
        client, clock = crawler.HTTPClient(retries=2), Clock()
        with self.assertRaises(urllib.error.HTTPError):
            self.run_requests(client,[error(429),error(429),error(429)],clock)
        self.assertEqual(clock.sleeps,[30,60])
        self.assertEqual(client.cooldown_until,clock.now+120)
        self.assertEqual(client.stats['rate_limited'],3)

    def test_shared_cooldown_reaches_other_worker_after_exhausted_retry(self):
        state, clock = shared(), Clock()
        first = crawler.HTTPClient(interval=.25,retries=0,shared_state=state)
        second = crawler.HTTPClient(interval=.25,retries=0,shared_state=state)
        with self.assertRaises(urllib.error.HTTPError):
            self.run_requests(first,[error(429,'45')],clock)
        self.assertEqual(clock.sleeps,[])
        self.run_requests(second,[io.BytesIO(b'ok')],clock)
        self.assertEqual(clock.sleeps,[45])
        self.assertEqual(state['requests'].value,2)
        self.assertEqual(state['rate_limited'].value,1)

    def test_global_gate_spaces_workers_and_transport_errors_are_counted(self):
        state, clock = shared(), Clock()
        first = crawler.HTTPClient(interval=.125,shared_state=state)
        second = crawler.HTTPClient(interval=.125,shared_state=state)
        self.run_requests(first,[io.BytesIO(b'ok')],clock)
        self.run_requests(second,[io.BytesIO(b'ok')],clock)
        self.assertEqual(clock.sleeps,[.125])
        third = crawler.HTTPClient(retries=1)
        self.run_requests(third,[OSError('reset'),io.BytesIO(b'ok')],clock)
        self.assertEqual(third.stats['transport_errors'],1)
        self.assertEqual(third.stats['retries'],1)
        with self.assertRaises(ValueError):
            crawler.HTTPClient(interval=.125)


if __name__ == '__main__':
    unittest.main()
