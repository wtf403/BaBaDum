#!/usr/bin/env python3
"""Receive babadum rounds fetched by the local browser."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "library" / "browser-rounds.jsonl"
LOCK = threading.Lock()
MAX_BODY = 5 * 1024 * 1024

class Handler(BaseHTTPRequestHandler):
    def _common(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._common()
        self.end_headers()

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        count = 0
        try:
            with OUT.open("rb") as stream:
                count = sum(1 for _ in stream)
        except FileNotFoundError:
            pass
        data = json.dumps({"ok": True, "rounds": count}).encode()
        self.send_response(200)
        self._common()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/ingest":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("invalid length")
            raw = self.rfile.read(length)
            payload = json.loads(raw)
            language = payload["language"]
            body = payload["body"]
            if not isinstance(language, str) or len(language) > 8:
                raise ValueError("invalid language")
            parsed = json.loads(body)
            if parsed.get("type") != "getWord" or not isinstance(parsed.get("data", {}).get("words"), list):
                raise ValueError("not a game round")
            record = {"received": time.time(), "language": language, "body": parsed}
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
            with LOCK:
                OUT.parent.mkdir(parents=True, exist_ok=True)
                with OUT.open("a", encoding="utf-8") as stream:
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
            self.send_response(204)
            self._common()
            self.end_headers()
        except Exception as exc:
            data = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(400)
            self._common()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args, flush=True)

if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    server.serve_forever()
