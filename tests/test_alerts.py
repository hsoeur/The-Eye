import tempfile
import unittest
from pathlib import Path

from theeye.modules.alerts.engine import Engine
from theeye.modules.alerts.journal import Journal
from theeye.modules.alerts.rules import Maintenance, Rule
from theeye.modules.alerts.store import SqlStore, StoreUnavailable


def obs(value, metric="cpu_pct", target="m1", item="", name="Srv"):
    return {"source": "machines", "target": target, "target_name": name, "item": item, "metric": metric,
            "value": value}


def make(rule=None, **kw):
    e = Engine(**kw)
    e.set_rules([rule or Rule("cpu", "CPU", "cpu_pct", ">", 90, "warning", for_seconds=60, recover_seconds=30)])
    return e


class EngineTest(unittest.TestCase):
    def test_pending_then_firing_then_resolved(self):
        e = make()
        self.assertFalse(e.evaluate([obs(95)], 0))
        self.assertFalse(e.active)
        c = e.evaluate([obs(95)], 61)
        self.assertEqual([x["type"] for x in c.events], ["fired"])
        self.assertEqual(e.counts()["to_handle"], 1)
        e.evaluate([obs(10)], 70)
        self.assertEqual(len(e.active), 1)
        c = e.evaluate([obs(10)], 101)
        self.assertEqual([x["type"] for x in c.events], ["resolved"])
        self.assertFalse(e.active)

    def test_short_spike_never_fires(self):
        e = make()
        e.evaluate([obs(95)], 0)
        e.evaluate([obs(10)], 30)
        e.evaluate([obs(95)], 40)
        e.evaluate([obs(95)], 90)
        self.assertFalse(e.active)

    def test_ack_requires_author_and_comment_and_keeps_history(self):
        e = make()
        e.evaluate([obs(95)], 0)
        e.evaluate([obs(95)], 61)
        aid = next(iter(e.active.values())).id
        with self.assertRaises(ValueError):
            e.ack(aid, "hugo", "")
        with self.assertRaises(ValueError):
            e.ack(aid, "", "ok")
        with self.assertRaises(LookupError):
            e.ack("nope", "hugo", "ok")
        c = e.ack(aid, "hugo", "en cours", ip="10.0.0.5")
        self.assertEqual(c.events[0]["type"], "acked")
        self.assertEqual(c.events[0]["comment"], "en cours")
        self.assertEqual(e.counts()["to_handle"], 0)
        e.unack(aid, "hugo")
        self.assertEqual(e.counts()["to_handle"], 1)
        c = e.comment(aid, "hugo", "note")
        self.assertEqual(c.events[0]["type"], "comment")

    def test_escalation_removes_ack(self):
        rule = Rule("cpu", "CPU", "cpu_pct", ">", 80, "warning", critical_threshold=95, recover_seconds=30)
        e = make(rule)
        e.evaluate([obs(85)], 0)
        aid = next(iter(e.active.values())).id
        e.ack(aid, "hugo", "vu")
        c = e.evaluate([obs(99)], 15)
        self.assertIn("escalated", [x["type"] for x in c.events])
        self.assertTrue(next(iter(e.active.values())).needs_attention)

    def test_root_cause_suppression(self):
        e = Engine()
        e.set_rules([Rule("down", "Hôte", "reachable", "<", 1, "critical"),
                     Rule("cpu", "CPU", "cpu_pct", ">", 90, "warning")])
        e.evaluate([obs(0, "reachable"), obs(99)], 0)
        self.assertEqual(e.counts()["to_handle"], 1)
        self.assertEqual(e.counts()["suppressed"], 1)

    def test_maintenance_silences(self):
        e = make(Rule("cpu", "CPU", "cpu_pct", ">", 90, "warning"))
        e.set_maintenance([Maintenance.from_dict({"name": "patch", "starts_at": 0, "ends_at": 1000})])
        e.evaluate([obs(99)], 10)
        self.assertEqual(e.counts()["to_handle"], 0)
        self.assertEqual(e.counts()["silenced"], 1)

    def test_no_data_auto_resolves(self):
        e = make(Rule("cpu", "CPU", "cpu_pct", ">", 90, "warning"), stale_seconds=100)
        e.evaluate([obs(99)], 0)
        e.evaluate([], 50)
        c = e.evaluate([], 200)
        self.assertEqual(c.events[-1]["type"], "resolved")
        self.assertFalse(e.active)

    def test_reopen_counts_flaps(self):
        e = make(Rule("cpu", "CPU", "cpu_pct", ">", 90, "warning", recover_seconds=0))
        e.evaluate([obs(99)], 0)
        e.evaluate([obs(10)], 10)
        c = e.evaluate([obs(99)], 20)
        self.assertIn("reopened", [x["type"] for x in c.events])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqlStore("sqlite", {}, "", Path(self.tmp.name) / "a.db")
        self.store.init()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_roundtrip_journal_and_query(self):
        e = make()
        e.evaluate([obs(95)], 1000)
        c = e.evaluate([obs(95)], 1061)
        aid = c.alerts[0]["id"]
        j = Journal(self.store, Path(self.tmp.name) / "o.jsonl")
        j.push([{"op": "alert", "d": a} for a in c.alerts] + [{"op": "event", "d": x} for x in c.events])
        c2 = e.ack(aid, "hugo", "pris en charge 100% _ok_")
        j.push([{"op": "alert", "d": a} for a in c2.alerts] + [{"op": "event", "d": x} for x in c2.events])
        self.assertTrue(j.flush())
        rows, total = self.store.query({"q": "100% _ok_"})
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["ack_by"], "hugo")
        self.assertEqual([x["type"] for x in self.store.events(aid)], ["fired", "acked"])
        self.assertEqual(len(self.store.load_active()), 1)
        self.assertEqual(self.store.query({"severity": "critical"})[1], 0)

    def test_journal_survives_restart_and_outage(self):
        path = Path(self.tmp.name) / "o.jsonl"

        class Down(SqlStore):
            def apply(self, op):
                raise StoreUnavailable("down")

        j = Journal(Down("sqlite", {}, "", Path(self.tmp.name) / "x.db"), path)
        j.push([{"op": "meta", "d": {"k": "a", "v": "1"}}])
        self.assertFalse(j.flush())
        self.assertEqual(j.pending(), 1)
        j2 = Journal(self.store, path)
        self.assertEqual(j2.pending(), 1)
        self.assertTrue(j2.flush())
        self.assertEqual(self.store.load_config()["meta"]["a"], "1")


if __name__ == "__main__":
    unittest.main()
