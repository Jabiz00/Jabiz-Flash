import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard" / "index.html"
STATUS = ROOT / "dashboard" / "status.json"


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] in ("/healthz", "/health"):
            self._send(200, b'{"ok":true,"service":"jabiz-flash-paper"}', "application/json")
            return
        if self.path.split("?", 1)[0] in ("/api/status", "/status"):
            try:
                payload = STATUS.read_bytes()
                json.loads(payload)
            except (OSError, ValueError):
                self._send(503, b'{"ok":false,"error":"status not ready"}', "application/json")
                return
            self._send(200, payload, "application/json")
            return
        if self.path.split("?", 1)[0] in ("/", "/index.html"):
            try:
                payload = DASHBOARD.read_bytes()
            except OSError:
                self._send(404, b"Dashboard file not found", "text/plain; charset=utf-8")
                return
            self._send(200, payload, "text/html; charset=utf-8")
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def _send(self, code, payload, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print("[http] " + fmt % args)


def start_status_server(host="127.0.0.1", port=8080):
    server = ThreadingHTTPServer((host, port), StatusHandler)
    thread = Thread(target=server.serve_forever, name="jabiz-status-http", daemon=True)
    thread.start()
    return server
