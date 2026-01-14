"""Minimal health server for Docker healthcheck."""

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

_server: HTTPServer | None = None
_thread: threading.Thread | None = None


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health endpoint."""

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress access logs."""
        pass


def start_health_server(port: int = 8000) -> None:
    """Start health server in background thread.

    Args:
        port: Port to listen on. Defaults to 8000.
    """
    global _server, _thread
    _server = HTTPServer(("0.0.0.0", port), HealthHandler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    logger.info(f"Health server started on port {port}")


def stop_health_server() -> None:
    """Stop health server."""
    global _server
    if _server:
        _server.shutdown()
        _server = None
        logger.info("Health server stopped")
