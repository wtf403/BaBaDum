import io
import json
import unittest
import urllib.parse
from unittest.mock import patch
import server

class TranslationProxyTest(unittest.TestCase):
    def handler(self, texts):
        h = object.__new__(server.HistoryAPIHTTPRequestHandler)
        payload = json.dumps({'text': texts, 'source_lang': 'EN', 'target_lang': 'AR', 'auth_key': 'test'}).encode()
        h.headers = {'Content-Length': str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.wfile = io.BytesIO()
        h.send_response = lambda status: setattr(h, 'status', status)
        h.send_header = lambda *args: None
        h.end_headers = lambda: None
        h.send_error = lambda status, message: setattr(h, 'status', status)
        return h

    def test_batch_is_encoded_as_repeated_text_fields(self):
        h = self.handler(['cat', 'dog'])
        response = io.BytesIO(b'{"translations":[{"text":"cat"},{"text":"dog"}]}')
        with patch('server.urllib.request.urlopen', return_value=response) as upstream:
            h.handle_deepl_request()
        data = urllib.parse.parse_qs(upstream.call_args.args[0].data.decode())
        self.assertEqual(data['text'], ['cat', 'dog'])
        self.assertEqual(data['target_lang'], ['AR'])
        self.assertEqual(h.status, 200)

    def test_existing_single_text_remains_supported(self):
        h = self.handler('cat')
        with patch('server.urllib.request.urlopen', return_value=io.BytesIO(b'{}')) as upstream:
            h.handle_deepl_request()
        self.assertEqual(urllib.parse.parse_qs(upstream.call_args.args[0].data.decode())['text'], ['cat'])
        self.assertEqual(h.status, 200)

    def test_environment_key_works_when_browser_key_is_empty(self):
        h = self.handler('cat')
        payload = json.dumps({'text': ['cat'], 'auth_key': ''}).encode()
        h.rfile = io.BytesIO(payload)
        h.headers = {'Content-Length': str(len(payload))}
        with patch('server.DEEPL_API_KEY', 'environment-test'), patch('server.urllib.request.urlopen', return_value=io.BytesIO(b'{}')) as upstream:
            h.handle_deepl_request()
        self.assertEqual(upstream.call_args.args[0].get_header('Authorization'), 'DeepL-Auth-Key environment-test')
        self.assertEqual(h.status, 200)

    def test_invalid_batches_never_reach_upstream(self):
        for texts in [[], [''], [123], ['cat'] * 51]:
            h = self.handler(texts)
            with patch('server.urllib.request.urlopen') as upstream:
                h.handle_deepl_request()
                upstream.assert_not_called()
            self.assertEqual(h.status, 400)
