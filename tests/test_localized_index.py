import io
import unittest
from unittest.mock import patch

import server


class LocalizedIndexTest(unittest.TestCase):
    def handler(self, cookie=None):
        h = object.__new__(server.HistoryAPIHTTPRequestHandler)
        h.headers = {"Cookie": cookie} if cookie else {}
        h.command = "GET"
        h.wfile = io.BytesIO()
        h.headers_sent = {}
        h.send_response = lambda status: setattr(h, "status", status)
        h.send_header = lambda name, value: h.headers_sent.__setitem__(name, value)
        h.end_headers = lambda: None
        return h

    def test_cookie_language_is_applied_to_page(self):
        h = self.handler("local_interface=fr")
        with patch.object(
            server.LOCAL_GAME,
            "interface",
            return_value={"lang": "Langue de menu", "lang_code": "fr"},
        ):
            h.serve_localized_index()
        body = h.wfile.getvalue().decode("utf-8")
        self.assertEqual(h.status, 200)
        self.assertIn("Object.assign(InterfaceData.data", body)
        self.assertIn('"lang": "Langue de menu"', body)
        self.assertEqual(h.headers_sent.get("Vary"), "Cookie")

    def test_page_without_cookie_is_unchanged(self):
        h = self.handler()
        with patch.object(server.LOCAL_GAME, "interface") as interface:
            h.serve_localized_index()
        body = h.wfile.getvalue().decode("utf-8")
        interface.assert_not_called()
        self.assertNotIn("Object.assign(InterfaceData.data", body)

    def test_malformed_cookie_falls_back_to_english(self):
        h = self.handler("local_interface=../../etc/passwd")
        with patch.object(server.LOCAL_GAME, "interface") as interface:
            h.serve_localized_index()
        interface.assert_not_called()
        self.assertNotIn("Object.assign(InterfaceData.data", h.wfile.getvalue().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
