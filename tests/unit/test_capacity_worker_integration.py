"""Execute actual worker loops with model/AWS/DB boundaries replaced by fakes."""

import ast, importlib.util, pathlib, sys, threading, time, types, unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_worker(filename):
    path = ROOT / "app/workers" / filename
    tree = ast.parse(path.read_text())
    modules = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module != "app.workers.lifecycle"
        ):
            if node.module.startswith(("app.", "sqlalchemy", "opentelemetry", "loguru")):
                mod = modules.setdefault(node.module, types.ModuleType(node.module))
                for alias in node.names:
                    setattr(mod, alias.name, MagicMock())
                modules[node.module] = mod
    modules["boto3"] = MagicMock()
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("test_" + filename[:-3], path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


class Tests(unittest.TestCase):
    def test_gpu_signal_during_receive_releases_without_inference(self):
        m = load_worker("ml_gpu_worker.py")
        sqs = MagicMock()
        m.boto3.client.return_value = sqs
        m._runtime.start = MagicMock()
        m._load_models = MagicMock()

        def receive(**kwargs):
            m._runtime.drain()
            return {"Messages": [{"ReceiptHandle": "receipt", "Body": "{}"}]}

        sqs.receive_message.side_effect = receive
        m.start_worker()
        sqs.delete_message.assert_not_called()
        m.run_ml_gpu_stage.assert_not_called()
        sqs.change_message_visibility.assert_called_with(
            QueueUrl=m.settings.sqs_gpu_inference_queue_url,
            ReceiptHandle="receipt",
            VisibilityTimeout=0,
        )

    def test_gpu_finishes_current_job_after_drain_then_exits(self):
        m = load_worker("ml_gpu_worker.py")
        sqs = MagicMock()
        m.boto3.client.return_value = sqs
        m._runtime.start = MagicMock()
        m._load_models = MagicMock()
        m.start_heartbeat = MagicMock(return_value="handle")
        m.stop_heartbeat = MagicMock()
        sqs.receive_message.return_value = {
            "Messages": [{"ReceiptHandle": "receipt", "Body": "{}"}]
        }
        calls = []

        async def process(*args):
            m._runtime.drain()
            calls.append("completed")

        m.run_ml_gpu_stage = process
        m.start_worker()
        self.assertEqual(calls, ["completed"])
        sqs.delete_message.assert_called_once()
        self.assertEqual(sqs.receive_message.call_count, 1)
        self.assertEqual(m._runtime.state()["active"], 0)

    def test_cpu_shutdown_joins_report_thread(self):
        m = load_worker("cpu_worker.py")
        m._runtime.start = MagicMock()
        m._load_models = MagicMock()
        entered = threading.Event()
        release = threading.Event()

        def report(*args):
            entered.set()
            release.wait(2)

        def preprocess(*args):
            entered.wait(1)
            m._runtime.drain()

        m._run_report_loop = report
        m._run_preprocess_loop = preprocess
        thread = threading.Thread(target=m.start_worker)
        thread.start()
        entered.wait(1)
        time.sleep(0.02)
        self.assertTrue(thread.is_alive())
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
