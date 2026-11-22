"""Demo web service for Incident Timeline Builder. Standard library only.

APP_BUG: ""           healthy
         "bad_driver" /health fails (a bad deploy)
         "leak"       memory grows until the container is OOM-killed
Demo only: /admin/fault lets the scenario runner inject a fault with no change event.
"""
import json
import os
import signal
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = os.environ.get("APP_VERSION", "v1")
BUG = os.environ.get("APP_BUG", "")
LEAK_MB_PER_S = float(os.environ.get("LEAK_MB_PER_S", "6"))
DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = int(os.environ.get("DB_PORT", "8081"))
# fake credentials on purpose: they leak into logs, the tool must redact them
DB_URL = f"postgres://app:Demo-S3cret-pw@{DB_HOST}:{DB_PORT}/orders"
LOG_PATH = os.environ.get("LOG_PATH", "/logs/app.log")
# the app writes naive local time (IST by default) on purpose
TZ = timezone(timedelta(minutes=int(os.environ.get("LOG_TZ_MIN", "330"))))
STATE = {"fault": ""}
LEAK = []


def log(level, msg):
    now = datetime.now(TZ)
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')},{now.microsecond // 1000:03d} {level} web: {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def leak():
    while True:
        LEAK.append(b"x" * int(LEAK_MB_PER_S * 1024 * 1024 / 10))
        time.sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def health(self):
        if STATE["fault"] == "errors":
            log("ERROR", "upstream timeout calling payments-api, api_key=demo-key-98765")
            return self.reply(503, "upstream timeout")
        if BUG == "bad_driver":
            log("ERROR", "unsupported protocol in new db driver, password=Demo-S3cret-pw")
            return self.reply(503, "driver error")
        try:
            socket.create_connection((DB_HOST, DB_PORT), timeout=0.5).close()
        except OSError:
            log("ERROR", f"connection refused to db:{DB_PORT} (url={DB_URL})")
            return self.reply(503, "db down")
        self.reply(200, json.dumps({"ok": True, "version": VERSION}))

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self.health()
        if url.path == "/admin/fault":
            mode = parse_qs(url.query).get("mode", [""])[0]
            STATE["fault"] = "" if mode == "none" else mode
            return self.reply(200, f"fault={STATE['fault'] or 'none'}")
        self.reply(200, f"hello from web {VERSION}")


def main():
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    log("INFO", f"starting version={VERSION} bug={BUG or 'none'} db_url={DB_URL}")
    if BUG == "leak":
        threading.Thread(target=leak, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
