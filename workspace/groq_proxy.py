#!/usr/bin/env python3
"""Local reverse proxy for Groq — adds browser User-Agent so Cloudflare doesn't block."""

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error
from pathlib import Path
import datetime

LOG = Path(os.environ.get("USERPROFILE", ".")) / ".openclaw" / "workspace" / "proxy.log"

def plog(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")

PORT       = 11435
GROQ_BASE  = "https://api.groq.com/openai/v1"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress access logs

    def _proxy(self, body=None):
        import json as _json
        plog(f"{self.command} {self.path}")
        # Return a silent empty response — openclaw agent gets a valid reply
        # but sends nothing to WhatsApp. check_text.py handles all real replies.
        empty = _json.dumps({
            "id": "silent",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
            "model": "llama-3.3-70b-versatile",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(empty)))
        self.end_headers()
        self.wfile.write(empty)
        plog("  → silent 200 OK")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self._proxy(self.rfile.read(length) if length else None)

    def do_GET(self):
        self._proxy()

if __name__ == "__main__":
    plog("proxy starting on 11435")
    server = HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    plog("proxy listening")
    server.serve_forever()
