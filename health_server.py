#!/usr/bin/env python3
"""Minimal health endpoint for SuperSystemV2."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9880


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body = json.dumps({"status": "ok", "service": "supersystemv2", "timestamp": time.time()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # suppress access log noise


def run(port: int = PORT) -> None:
    server = HTTPServer(("127.0.0.1", port), HealthHandler)
    print(f"Health server listening on http://127.0.0.1:{port}/health")
    server.serve_forever()


if __name__ == "__main__":
    run()
