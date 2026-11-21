"""A Healthchecks stand-in for deploy/e2e-jobs.sh: records each ping, answers 200.

One line per ping in /tmp/pings.log: the path without the run id, a tab, the body on one line.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = "/tmp/pings.log"  # noqa: S108 (a throwaway test container)
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        line = self.path.split("?")[0] + "\t" + body.decode("utf-8", "replace").replace("\n", " | ")
        with lock, open(LOG, "a", encoding="utf-8") as log:
            log.write(line + "\n")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


open(LOG, "a").close()
ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()  # noqa: S104 (inside the test network)
