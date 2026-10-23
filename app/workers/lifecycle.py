"""Model readiness, cooperative draining and bounded SQS redelivery.

This does not provide exactly-once execution. Abrupt process death leaves the
message invisible until the last successful visibility extension expires.
"""

import json
import logging
import os
import signal
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = logging.getLogger(__name__)
VISIBILITY_SECONDS = int(os.environ.get("WORKER_VISIBILITY_SECONDS", "120"))
HEARTBEAT_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_SECONDS", "30"))
if not 0 < HEARTBEAT_SECONDS < VISIBILITY_SECONDS / 2:
    raise ValueError("heartbeat must be shorter than half the visibility timeout")


class Lifecycle:
    def __init__(self):
        self.stop = threading.Event()
        # Python signal handlers run on the main thread. A signal may interrupt
        # accept() while it holds this lock, so drain() must be reentrant.
        self.lock = threading.RLock()
        self.loaded = False
        self.active = 0

    def drain(self):
        with self.lock:
            self.stop.set()

    def mark_ready(self):
        with self.lock:
            self.loaded = True

    def state(self):
        with self.lock:
            return {
                "ready": self.loaded and not self.stop.is_set(),
                "active": self.active,
                "draining": self.stop.is_set(),
            }

    def accept(self, sqs, queue, receipt):
        with self.lock:
            if not self.stop.is_set():
                self.active += 1
                return True
        release(sqs, queue, receipt)
        return False

    def finish(self):
        with self.lock:
            self.active -= 1

    def start(self, port=None):
        signal.signal(signal.SIGTERM, lambda *_: self.drain())
        signal.signal(signal.SIGINT, lambda *_: self.drain())
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                state = runtime.state()
                if self.path not in ("/state", "/readyz", "/healthz"):
                    self.send_error(404)
                    return
                self.send_response(503 if self.path == "/readyz" and not state["ready"] else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(state).encode())

            def do_POST(self):
                # Drain is only accepted from the container itself (preStop).
                if self.path != "/drain" or self.client_address[0] not in ("127.0.0.1", "::1"):
                    self.send_error(403)
                    return
                runtime.drain()
                self.send_response(200)
                self.end_headers()

        server = ThreadingHTTPServer(
            (
                "0.0.0.0",
                port if port is not None else int(os.environ.get("WORKER_HEALTH_PORT", "9091")),
            ),
            Handler,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server


def release(sqs, queue, receipt):
    try:
        sqs.change_message_visibility(QueueUrl=queue, ReceiptHandle=receipt, VisibilityTimeout=0)
    except Exception:
        LOG.warning(
            "Could not release message; it will expire by visibility timeout", exc_info=True
        )


def heartbeat(sqs, queue, receipt, stopped, interval=HEARTBEAT_SECONDS):
    while not stopped.is_set():
        try:
            sqs.change_message_visibility(
                QueueUrl=queue, ReceiptHandle=receipt, VisibilityTimeout=VISIBILITY_SECONDS
            )
        except Exception:
            LOG.warning(
                "SQS visibility heartbeat failed; duplicate execution is possible", exc_info=True
            )
        if stopped.wait(interval):
            break


def start_heartbeat(sqs, queue, receipt):
    stopped = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(sqs, queue, receipt, stopped), daemon=True)
    thread.start()
    return stopped, thread


def stop_heartbeat(handle):
    stopped, thread = handle
    stopped.set()
    # A client network call may still be outstanding; use bounded AWS client timeouts.
    thread.join(timeout=5)


if __name__ == "__main__":
    request = urllib.request.Request(
        "http://127.0.0.1:" + os.environ.get("WORKER_HEALTH_PORT", "9091") + "/drain", method="POST"
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        response.read()
