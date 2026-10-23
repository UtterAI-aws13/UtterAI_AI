import importlib.util, json, pathlib, threading, unittest, urllib.request, urllib.error
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location(
    "lifecycle", pathlib.Path(__file__).resolve().parents[2] / "app/workers/lifecycle.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Tests(unittest.TestCase):
    def test_no_new_message_after_sigterm_during_long_poll(self):
        lifecycle = m.Lifecycle()
        sqs = Mock()
        lifecycle.drain()
        self.assertFalse(lifecycle.accept(sqs, "queue", "receipt"))
        self.assertEqual(lifecycle.state()["active"], 0)
        sqs.change_message_visibility.assert_called_once_with(
            QueueUrl="queue", ReceiptHandle="receipt", VisibilityTimeout=0
        )

    def test_draining_does_not_cancel_inflight(self):
        lifecycle = m.Lifecycle()
        lifecycle.mark_ready()
        self.assertTrue(lifecycle.accept(Mock(), "q", "r"))
        lifecycle.drain()
        self.assertFalse(lifecycle.state()["ready"])
        self.assertEqual(lifecycle.state()["active"], 1)
        lifecycle.finish()
        self.assertEqual(lifecycle.state()["active"], 0)

    def test_two_cpu_threads_tracked(self):
        lifecycle = m.Lifecycle()
        sqs = Mock()
        lifecycle.accept(sqs, "q", "a")
        lifecycle.accept(sqs, "q", "b")
        self.assertEqual(lifecycle.state()["active"], 2)
        lifecycle.finish()
        self.assertEqual(lifecycle.state()["active"], 1)

    def test_heartbeat_first_extension_and_stop(self):
        sqs = Mock()
        stop = threading.Event()
        sqs.change_message_visibility.side_effect = lambda **kwargs: stop.set()
        m.heartbeat(sqs, "q", "r", stop)
        self.assertEqual(sqs.change_message_visibility.call_args.kwargs["VisibilityTimeout"], 120)

    def test_signal_can_drain_while_main_thread_holds_lock(self):
        import subprocess, sys

        code = """import importlib.util, os, signal
s=importlib.util.spec_from_file_location('life', 'app/workers/lifecycle.py')
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
l=m.Lifecycle(); server=l.start(port=0)
with l.lock:
    os.kill(os.getpid(), signal.SIGTERM)
assert l.stop.is_set()
server.shutdown(); server.server_close()
"""
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=pathlib.Path(__file__).resolve().parents[2],
            check=True,
            timeout=3,
        )

    def test_actual_health_endpoint_and_drain(self):
        lifecycle = m.Lifecycle()
        server = lifecycle.start(port=0)
        url = "http://127.0.0.1:" + str(server.server_port)
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(url + "/readyz")
            self.assertEqual(e.exception.code, 503)
            lifecycle.mark_ready()
            with urllib.request.urlopen(url + "/readyz") as r:
                self.assertTrue(json.load(r)["ready"])
            with urllib.request.urlopen(urllib.request.Request(url + "/drain", method="POST")) as r:
                self.assertEqual(r.status, 200)
            self.assertTrue(lifecycle.stop.is_set())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
