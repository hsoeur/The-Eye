import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from theeye.app import App
from theeye.core.config import Settings
from theeye.core.events import EventBus
from theeye.core.http import HttpError, Router
from theeye.core.module import discover
from theeye.core.scheduler import Scheduler
from theeye.core.storage import JsonStore
from theeye.modules.machines.collectors import base as collectors
from theeye.modules.machines.collectors.linux import parse as parse_linux
from theeye.modules.network.fingerprint import guess_type, vendor_of


class RouterTest(unittest.TestCase):
    def test_params_and_errors(self):
        r = Router()
        r.get("/a/{id}", lambda req: None)
        handler, params = r.resolve("GET", "/a/x%20y")
        self.assertEqual(params, {"id": "x y"})
        with self.assertRaises(HttpError) as e:
            r.resolve("POST", "/a/1")
        self.assertEqual(e.exception.status, 405)
        with self.assertRaises(HttpError) as e:
            r.resolve("GET", "/nope")
        self.assertEqual(e.exception.status, 404)

    def test_scoped_prefix(self):
        r = Router()
        r.scoped("/api/m").get("/x", lambda req: None)
        self.assertIn("GET /api/m/x", r.paths())


class StorageTest(unittest.TestCase):
    def test_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            s = JsonStore(Path(d) / "a.json", default=dict)
            self.assertEqual(s.load(), {})
            s.save({"k": 1})
            self.assertEqual(s.load(), {"k": 1})
            (Path(d) / "a.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(s.load(), {})


class EventsTest(unittest.TestCase):
    def test_publish_filter_subscribe(self):
        bus, seen = EventBus(), []
        bus.subscribe(seen.append)
        bus.publish("a", "k", "m1", "info")
        bus.publish("b", "k", "m2", "critical")
        self.assertEqual(len(seen), 2)
        self.assertEqual([e["message"] for e in bus.recent(source="b")], ["m2"])
        self.assertEqual([e["message"] for e in bus.recent(min_severity="critical")], ["m2"])


class SchedulerTest(unittest.TestCase):
    def test_job_runs_and_errors_are_contained(self):
        s, hits = Scheduler(workers=2), []
        s.every("ok", 0.05, lambda: hits.append(1))
        s.every("boom", 0.05, lambda: 1 / 0)
        s.start()
        time.sleep(1.6)
        s.stop()
        self.assertGreaterEqual(len(hits), 2)


class FingerprintTest(unittest.TestCase):
    def test_vendor_and_type(self):
        self.assertEqual(vendor_of("zz", {}), "")
        self.assertIsInstance(guess_type({"ports": [22], "vendor": ""}), str)


class CollectorTest(unittest.TestCase):
    def test_registry_and_descriptions(self):
        kinds = set(collectors.COLLECTORS)
        self.assertTrue({"windows", "linux"} <= kinds)

    def test_linux_parse_empty_is_safe(self):
        self.assertIsInstance(parse_linux(""), dict)


class ModulesTest(unittest.TestCase):
    def test_discovery(self):
        ids = {m.id for m in discover()}
        self.assertTrue({"network", "docker", "machines"} <= ids)


class AppIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = App(Settings(host="127.0.0.1", port=0, data_dir=Path(cls.tmp.name), disabled_modules=["docker"]))
        cls.app.server.start_background()
        cls.base = f"http://127.0.0.1:{cls.app.server.port}"

    @classmethod
    def tearDownClass(cls):
        cls.app.server.shutdown()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.read()

    def test_health_and_modules(self):
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        ids = [m["id"] for m in json.loads(self.get("/api/modules")[1])["modules"]]
        self.assertIn("network", ids)
        self.assertNotIn("docker", ids)

    def test_static_and_traversal(self):
        self.assertEqual(self.get("/")[0], 200)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/..%2f..%2feye.py")
        self.assertEqual(e.exception.code, 404)

    def test_unknown_api_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/api/zzz")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
