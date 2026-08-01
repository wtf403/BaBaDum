#!/usr/bin/env python3
"""
Simple HTTP server with HTML5 History API support for Ba Ba Dum
Serves index.html for all routes that don't match existing files
Includes DeepL API proxy endpoint
"""

import http.server
import json
import logging
import os
import socketserver
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("deepl_errors.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

PORT = 8001
DEEPL_API_KEY = ""  # Set your DeepL API key here or in config
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"


class HistoryAPIHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler with HTML5 History API support and DeepL proxy"""

    def do_POST(self):
        """Handle POST requests for DeepL API proxy"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/api/deepl/translate":
            self.handle_deepl_request()
        else:
            self.send_error(404, "Endpoint not found")

    def handle_deepl_request(self):
        """Proxy DeepL API requests"""
        text = ""
        source_lang = "ZH"
        target_lang = "EN"

        try:
            # Read request body
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            request_data = json.loads(post_data.decode("utf-8"))

            text = request_data.get("text", "")
            source_lang = request_data.get("source_lang", "ZH")
            target_lang = request_data.get("target_lang", "EN")

            # Get API key from request or server config
            api_key = request_data.get("auth_key", DEEPL_API_KEY)

            if not api_key:
                logger.error(
                    f"DeepL API request failed: API key not configured - Text: '{text[:50]}...'"
                )
                self.send_response(400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                response = {"error": "API key not configured"}
                self.wfile.write(json.dumps(response).encode())
                return

            # Make request to DeepL API with header-based authentication
            data = urllib.parse.urlencode(
                {
                    "text": text,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                }
            ).encode()

            headers = {
                "Authorization": f"DeepL-Auth-Key {api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            req = urllib.request.Request(DEEPL_API_URL, data=data, headers=headers)

            with urllib.request.urlopen(req) as response:
                deepl_response = response.read()

                # Send successful response
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(deepl_response)

        except urllib.error.HTTPError as e:
            logger.error(
                f"DeepL API HTTP Error {e.code}: {e.reason} - Text: '{text[:50]}...', Source: {source_lang}, Target: {target_lang}"
            )
            self.send_response(e.code)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            error_response = {"error": f"DeepL API error: {e.reason}"}
            self.wfile.write(json.dumps(error_response).encode())

        except Exception as e:
            logger.error(
                f"DeepL API Exception: {str(e)} - Text: '{text[:50]}...', Source: {source_lang}, Target: {target_lang}"
            )
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            error_response = {"error": str(e)}
            self.wfile.write(json.dumps(error_response).encode())

    def do_GET(self):
        """Handle GET requests with fallback to index.html"""
        # Parse the URL
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # Remove leading slash
        if path.startswith("/"):
            path = path[1:]

        # If path is empty, serve index.html
        if not path:
            path = "index.html"

        # Check if the requested file exists
        if os.path.exists(path) and os.path.isfile(path):
            # File exists, serve it normally
            return http.server.SimpleHTTPRequestHandler.do_GET(self)
        else:
            # File doesn't exist, check if it's a route (not a file extension)
            if "." not in os.path.basename(path):
                # Looks like a route, serve index.html
                self.path = "/index.html"
                return http.server.SimpleHTTPRequestHandler.do_GET(self)
            else:
                # Has extension but doesn't exist, return 404
                return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS preflight"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self):
        """Add CORS headers for development"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        http.server.SimpleHTTPRequestHandler.end_headers(self)


def main():
    """Start the server"""
    handler = HistoryAPIHTTPRequestHandler

    class ReusableThreadingServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        allow_reuse_port = True

        def server_bind(self):
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            super().server_bind()

    with ReusableThreadingServer(("", PORT), handler) as httpd:
        print(f"🚀 Ba Ba Dum server running at http://localhost:{PORT}/")
        print(f"📁 Serving files from: {os.getcwd()}")
        print(f"✨ HTML5 History API support enabled")
        print(f"\nPress Ctrl+C to stop the server\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n👋 Server stopped")
            httpd.shutdown()


if __name__ == "__main__":
    main()
