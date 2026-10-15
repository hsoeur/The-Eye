import json
import os
import tempfile
import unittest
from pathlib import Path

from theeye.core.process import NOT_FOUND, TIMEOUT, Result
from theeye.modules.alerts.rules import Rule, default_rules, docker_watchdog_rules
from theeye.modules.docker.incident import IncidentCapture, ps_error
from theeye.modules.docker.recovery import Recoverer
from theeye.modules.docker.watchdog import (DEGRADED, FAIL, HEALTHY, HUNG, OK, RECOVERING, SLOW, RecoveryGuard,
                                            Watchdog, WatchdogConfig, classify, classify_listing, docker_is_local)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeRunner:
    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = fail_on

    def run(self, cmd, timeout=20, input=None, env=None):
        self.calls.append(cmd)
        if any(f in " ".join(cmd) for f in self.fail_on):
            raise RuntimeError("boom")
        return Result(0, "sortie", "")

    def powershell(self, script, timeout=30, env=None):
        self.calls.append(["powershell", script[:30]])
        if "powershell" in self.fail_on:
            raise RuntimeError("boom")
        return Result(0, "sortie", "")


def make(**cfg):
    clock, events = Clock(), []
    wd = Watchdog(WatchdogConfig.from_dict(cfg), clock, lambda t, m, s="info", **d: events.append((t, s)))
    return wd, clock, events


def feed(wd, clock, kinds):
    for k in kinds:
        clock.t += 30
        wd.record(k, 1.0)


class StateMachine(unittest.TestCase):
    def test_degraded_hung_recovered_one_event_each(self):
        wd, clock, events = make()
        feed(wd, clock, [SLOW])
        self.assertEqual(wd.state, HEALTHY)
        feed(wd, clock, [SLOW])
        self.assertEqual(wd.state, DEGRADED)
        feed(wd, clock, [FAIL, FAIL, FAIL, FAIL])
        self.assertEqual(wd.state, HUNG)
        feed(wd, clock, [OK])
        self.assertEqual(wd.state, RECOVERING)
        feed(wd, clock, [OK, OK])
        self.assertEqual(wd.state, HEALTHY)
        self.assertEqual([e[0] for e in events],
                         ["docker_engine_degraded", "docker_engine_hung", "docker_engine_recovered"])
        self.assertEqual([e[1] for e in events], ["warning", "critical", "ok"])

    def test_slow_never_hangs(self):
        wd, clock, _ = make()
        feed(wd, clock, [SLOW] * 10)
        self.assertEqual(wd.state, DEGRADED)

    def test_capture_once_per_incident(self):
        wd, clock, _ = make()
        feed(wd, clock, [FAIL] * 6)
        self.assertTrue(wd.take_capture())
        self.assertFalse(wd.take_capture())
        feed(wd, clock, [FAIL] * 3)
        self.assertFalse(wd.take_capture())
        feed(wd, clock, [OK] * 3)
        self.assertEqual(wd.state, HEALTHY)
        feed(wd, clock, [FAIL] * 3)
        self.assertTrue(wd.take_capture())

    def test_capture_disabled(self):
        wd, clock, _ = make(capture_on_hung=False)
        feed(wd, clock, [FAIL] * 3)
        self.assertEqual(wd.state, HUNG)
        self.assertFalse(wd.take_capture())

    def test_retry_capture(self):
        wd, clock, _ = make()
        feed(wd, clock, [FAIL] * 3)
        self.assertTrue(wd.take_capture())
        wd.retry_capture()
        self.assertTrue(wd.take_capture())
        wd.mark_capture_finished()
        wd.retry_capture()
        self.assertFalse(wd.take_capture())

    def test_recovery_grace_period(self):
        wd, clock, events = make()
        feed(wd, clock, [FAIL] * 3)
        wd.begin_recovery()
        self.assertEqual(wd.state, RECOVERING)
        feed(wd, clock, [FAIL] * 5)
        self.assertEqual(wd.state, RECOVERING)
        clock.t += 400
        feed(wd, clock, [FAIL] * 3)
        self.assertEqual(wd.state, HUNG)
        self.assertEqual([e[0] for e in events].count("docker_engine_hung"), 2)

    def test_abort_recovery(self):
        wd, clock, _ = make()
        feed(wd, clock, [FAIL] * 3)
        wd.begin_recovery()
        wd.abort_recovery()
        self.assertEqual(wd.state, HUNG)

    def test_cli_missing_flag_and_snapshot(self):
        wd, clock, _ = make()
        wd.record(FAIL, 0.0, "absent", NOT_FOUND)
        self.assertTrue(wd.cli_missing)
        snap = wd.snapshot()
        self.assertEqual(snap["state"], HEALTHY)
        self.assertEqual(len(snap["history"]), 1)


class Classification(unittest.TestCase):
    cfg = WatchdogConfig()

    def test_cases(self):
        self.assertEqual(classify(Result(0, "27.1.1\n"), 0.5, self.cfg)[0], OK)
        self.assertEqual(classify(Result(0, "27.1.1"), 6.0, self.cfg)[0], SLOW)
        self.assertEqual(classify(Result(TIMEOUT), 15, self.cfg)[0], FAIL)
        self.assertEqual(classify(Result(NOT_FOUND), 0, self.cfg)[0], FAIL)
        self.assertEqual(classify(Result(1, "", "daemon down"), 0.2, self.cfg)[0], FAIL)
        self.assertEqual(classify(Result(0, "n'importe quoi"), 0.2, self.cfg)[0], FAIL)
        self.assertEqual(classify(Result(0, ""), 0.2, self.cfg)[0], FAIL)


class Config(unittest.TestCase):
    def test_bounds_and_defaults(self):
        cfg = WatchdogConfig.from_dict({"interval_s": 2, "probe_timeout_s": 999, "hung_after": "x",
                                        "auto_recover": "oui", "max_incidents": 5, "actions": True})
        self.assertEqual(cfg.interval_s, 15.0)
        self.assertEqual(cfg.hung_after, 3)
        self.assertFalse(cfg.auto_recover)
        self.assertEqual(cfg.max_incidents, 5)
        self.assertEqual(set(cfg.ignored), {"interval_s", "probe_timeout_s", "hung_after", "auto_recover"})

    def test_slow_clamped_to_timeout(self):
        cfg = WatchdogConfig.from_dict({"probe_timeout_s": 3, "slow_threshold_s": 10})
        self.assertEqual(cfg.slow_threshold_s, 3)

    def test_defaults_without_config(self):
        cfg = WatchdogConfig.from_dict(None)
        self.assertEqual((cfg.interval_s, cfg.auto_recover), (15.0, False))


class Locality(unittest.TestCase):
    def test_local_remote(self):
        self.assertTrue(docker_is_local({}, "nt")[0])
        self.assertTrue(docker_is_local({"DOCKER_HOST": "npipe:////./pipe/docker_engine"}, "nt")[0])
        self.assertFalse(docker_is_local({"DOCKER_HOST": "tcp://10.0.0.5:2375"}, "nt")[0])
        self.assertFalse(docker_is_local({}, "posix")[0])


class Guard(unittest.TestCase):
    def test_cooldown_and_daily_cap(self):
        clock = Clock()
        cfg = WatchdogConfig.from_dict({"recover_cooldown_min": 10, "max_recoveries_per_day": 2})
        g = RecoveryGuard(cfg, clock)
        self.assertTrue(g.allow()[0])
        g.record()
        self.assertFalse(g.allow()[0])
        clock.t += 11 * 60
        self.assertTrue(g.allow()[0])
        g.record()
        clock.t += 11 * 60
        self.assertFalse(g.allow()[0])
        clock.t += 86400
        self.assertTrue(g.allow()[0])

    def test_persisted_history_and_zero_cap(self):
        clock = Clock()
        g = RecoveryGuard(WatchdogConfig.from_dict({"max_recoveries_per_day": 0}), clock, [clock.t - 99999, "x"])
        self.assertFalse(g.allow()[0])
        g2 = RecoveryGuard(WatchdogConfig(), clock, [clock.t - 60])
        self.assertFalse(g2.allow()[0])
        self.assertEqual(g2.summary()["last_24h"], 1)


class Recovery(unittest.TestCase):
    def test_nothing_stopped_if_exe_missing(self):
        r = FakeRunner()
        ok, detail = Recoverer(r, "C:\\absent.exe", lambda p: False).run()
        self.assertFalse(ok)
        self.assertEqual(r.calls, [])
        self.assertIn("introuvable", detail)

    def test_sequence(self):
        r = FakeRunner()
        ok, _ = Recoverer(r, "C:\\d.exe", lambda p: True).run()
        self.assertTrue(ok)
        self.assertEqual(len(r.calls), 3)
        self.assertEqual(r.calls[1], ["wsl", "--shutdown"])


class Incident(unittest.TestCase):
    def test_capture_writes_files_and_isolates_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"LOCALAPPDATA": tmp, "APPDATA": tmp, "USERPROFILE": tmp}
            cap = IncidentCapture(FakeRunner(fail_on=("docker info", "powershell")), Path(tmp) / "inc", 2,
                                  environ=env)
            s = cap.capture("test", HUNG, [[1, 1.0, "fail", HUNG]], {"docker_server_last_ok": "27.0"})
            self.assertTrue(s["path"])
            folder = Path(s["path"])
            self.assertTrue((folder / "summary.json").is_file())
            self.assertTrue((folder / "probe-history.json").is_file())
            self.assertEqual(json.loads((folder / "summary.json").read_text("utf-8"))["reason"], "test")
            self.assertTrue(any(not v.get("ok") for v in s["steps"].values()))

    def test_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            cap = IncidentCapture(FakeRunner(), Path(tmp) / "inc", 2, environ={"LOCALAPPDATA": tmp})
            for _ in range(4):
                cap.capture("x", HUNG, [])
            self.assertEqual(len(cap.list_incidents(10)), 2)


class Listing(unittest.TestCase):
    cfg = WatchdogConfig()

    def test_listing_probe(self):
        self.assertIsNone(classify_listing(Result(0, ""), self.cfg))
        self.assertIsNone(classify_listing(Result(0, "abc123\n"), self.cfg))
        self.assertIn("délai", classify_listing(Result(TIMEOUT), self.cfg))
        self.assertIn("daemon", classify_listing(Result(1, "", "daemon unreachable"), self.cfg))


class PowerShellErrors(unittest.TestCase):
    def test_clixml_noise_removed(self):
        noise = '#< CLIXML\n<Objs><Obj S="progress"><AV>Préparation</AV></Obj></Objs>'
        self.assertEqual(ps_error(Result(1, "", noise)), "code 1")
        err = noise + '<S S="Error">Accès refusé_x000D__x000A_</S>'
        self.assertEqual(ps_error(Result(1, "", err)), "Accès refusé")
        self.assertEqual(ps_error(Result(1, "", "simple erreur")), "simple erreur")

    def test_events_kept_despite_exit_code(self):
        class R(FakeRunner):
            def powershell(self, script, timeout=30, env=None):
                return Result(1, '"Time","LogName"\n"x","System"\n', "#< CLIXML")
        with tempfile.TemporaryDirectory() as tmp:
            cap = IncidentCapture(R(), Path(tmp) / "inc", 2, environ={"LOCALAPPDATA": tmp})
            s = cap.capture("x", HUNG, [])
            if os.name == "nt":
                self.assertTrue((Path(s["path"]) / "events.csv").is_file())


class Rules(unittest.TestCase):
    def test_new_rules_valid(self):
        rules = docker_watchdog_rules()
        self.assertEqual({r.id for r in rules}, {"docker-engine-slow", "docker-engine-hung"})
        for r in rules:
            Rule.from_dict(r.to_dict(), r.id)

    def test_default_rules_include_watchdog(self):
        ids = {r.id for r in default_rules(True)}
        self.assertIn("docker-engine-hung", ids)
        down = [r for r in default_rules(False) if r.id == "docker-down"]
        self.assertTrue(all(not r.enabled for r in down))


if __name__ == "__main__":
    unittest.main()
