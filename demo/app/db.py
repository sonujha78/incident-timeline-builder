"""Demo database stub: accepts TCP connections and answers OK. Standard library only."""
import os
import signal
import socketserver
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(minutes=int(os.environ.get("LOG_TZ_MIN", "330"))))
LOG_PATH = os.environ.get("LOG_PATH", "/logs/app.log")


def log(level, msg):
    now = datetime.now(TZ)
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')},{now.microsecond // 1000:03d} {level} db: {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"OK\n")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    log("INFO", "starting")
    Server(("0.0.0.0", 8081), Handler).serve_forever()
