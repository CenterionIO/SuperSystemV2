#!/usr/bin/env python3
"""
Conflicting reinterpretation of the health-check endpoint requirement.

Requirement: "build a minimal health-check endpoint"
Reinterpretation: Instead of the SERVICE reporting its own health (the standard
interpretation), this endpoint reinterprets /health as a CLIENT health intake —
callers POST their own health status to us, and we record it. The service itself
never claims to be healthy or unhealthy; it merely receives and stores health
reports from external clients.

Conflict with standard: Standard GET /health → 200 {"status":"ok"}
This impl:            POST /health with body → 202 {"received": true}
                      GET /health → 405 Method Not Allowed
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9881
_health_log: list[dict] = []


class ClientHealthReceiver(BaseHTTPRequestHandler):
    """
    Reinterpretation: /health is an intake endpoint for CLIENT health reports,
    not a self-declaration of server health.
    """

    def do_POST(self) -> None:
        if self.path != "/health":
            self._respond(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        entry = {"received_at": time.time(), "client_report": payload}
        _health_log.append(entry)
        self._respond(202, {"received": True, "total_reports": len(_health_log)})

    def do_GET(self) -> None:
        if self.path == "/health":
            # Conflicting: GET is not how you check health here.
            # We return 405 with an explanation.
            self._respond(
                405,
                {
                    "error": "method_not_allowed",
                    "detail": (
                        "This endpoint receives health reports (POST), "
                        "it does not emit them. "
                        "Reinterpretation: clients report health TO us."
                    ),
                    "hint": "POST /health with your client health payload.",
                },
            )
        elif self.path == "/health/log":
            self._respond(200, {"reports": _health_log, "count": len(_health_log)})
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def run(port: int = PORT) -> None:
    server = HTTPServer(("127.0.0.1", port), ClientHealthReceiver)
    print(
        f"Health intake server (reinterpreted) on http://127.0.0.1:{port}/health\n"
        f"  POST /health        — submit a client health report\n"
        f"  GET  /health        — 405 (clients report health; service doesn't)\n"
        f"  GET  /health/log    — view all received reports\n"
    )
    server.serve_forever()


if __name__ == "__main__":
    run()
