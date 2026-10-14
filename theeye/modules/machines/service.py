"""Inventaire des machines supervisées et cycle d'interrogation."""
import re
import threading
import time
import uuid
from typing import Any, Dict, Optional

from ...core.module import Context
from .collectors import COLLECTORS, CollectError, normalize

ADDRESS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,99}")
HISTORY_POINTS = 120


class MachineService:
    def __init__(self, ctx: Context, local_ips: set):
        self.ctx = ctx
        self.interval = float(ctx.config.get("interval_s", 10))
        self.store = ctx.store("hosts")
        self.lock = threading.RLock()
        self.hosts: Dict[str, Dict[str, Any]] = self._migrate(self.store.load())
        self.live: Dict[str, Dict[str, Any]] = {}
        self.busy: set = set()
        self.collectors = {k: cls(ctx.runner, local_ips) for k, cls in COLLECTORS.items()}

    @staticmethod
    def _migrate(hosts: Dict[str, Any]) -> Dict[str, Any]:
        for h in hosts.values():
            if "kind" not in h:
                h["kind"] = h.pop("os", "windows")
        return hosts

    def types(self):
        return [c.describe() for c in self.collectors.values()]

    def add(self, body: Dict[str, Any]) -> str:
        ip = str(body.get("ip", "")).strip()
        if not ADDRESS_RE.fullmatch(ip):
            raise ValueError("IP / nom invalide")
        collector = self.collectors.get(body.get("kind"))
        if not collector:
            raise ValueError("type de machine invalide")
        host = {"name": str(body.get("name") or ip).strip()[:60], "ip": ip, "kind": collector.kind,
                **collector.build_options(body)}
        hid = uuid.uuid4().hex[:8]
        with self.lock:
            self.hosts[hid] = host
            self.store.save(self.hosts)
        self.ctx.emit("machine_added", f"Machine ajoutée : {host['name']} ({ip})", "info", id=hid)
        return hid

    def remove(self, hid: str) -> bool:
        with self.lock:
            host = self.hosts.pop(hid, None)
            self.live.pop(hid, None)
            if host:
                self.store.save(self.hosts)
        if host:
            self.ctx.emit("machine_removed", f"Machine retirée : {host['name']}", "info", id=hid)
        return bool(host)

    def view(self) -> list:
        with self.lock:
            out = []
            for hid, h in self.hosts.items():
                c = self.collectors.get(h["kind"])
                out.append({"id": hid, "name": h["name"], "ip": h["ip"], "kind": h["kind"],
                            "proc_cpu_unit": c.proc_cpu_unit if c else "%",
                            **(c.public_options(h) if c else {}), **self.live.get(hid, {"ok": None})})
            return out

    def tick(self) -> None:
        now = time.time()
        with self.lock:
            due = [hid for hid in self.hosts if hid not in self.busy
                   and (hid not in self.live or now - self.live[hid]["t"] >= self.interval)]
            self.busy.update(due)
        for hid in due:
            self.ctx.scheduler.submit(self.poll, hid)

    def poll(self, hid: str) -> None:
        try:
            with self.lock:
                host = dict(self.hosts.get(hid) or {})
                st = self.live.setdefault(hid, {"history": [], "changes": [], "ok": None, "metrics": None,
                                                "error": "", "t": 0})
            if not host:
                return
            t0 = time.time()
            collector = self.collectors.get(host["kind"])
            try:
                if not collector:
                    raise CollectError(f"collecteur « {host['kind']} » indisponible")
                metrics = normalize(collector.collect(host))
                self._on_success(hid, host, st, metrics, t0)
            except Exception as e:
                if not isinstance(e, CollectError):
                    self.ctx.log.exception("collecte %s en erreur", host.get("name"))
                self._on_failure(hid, host, st, str(e))
        finally:
            with self.lock:
                self.busy.discard(hid)

    def _change(self, st, host, hid, msg: str, severity: str, kind: str) -> None:
        st["changes"] = (st["changes"] + [{"t": time.time(), "msg": msg}])[-60:]
        self.ctx.emit(kind, f"{host['name']} : {msg}", severity, id=hid)

    def _on_success(self, hid, host, st, m, t0) -> None:
        now = time.time()
        prev = st.get("metrics")
        if prev and st.get("t_data") and m["net_rx"]:
            dt = max(1, now - st["t_data"])
            m["rx_rate"] = max(0, (m["net_rx"] - prev.get("net_rx", 0)) / dt)
            m["tx_rate"] = max(0, (m["net_tx"] - prev.get("net_tx", 0)) / dt)
        else:
            m["rx_rate"] = m["tx_rate"] = 0
        if prev:
            old = {s["name"]: s for s in prev["services"]}
            for s in m["services"]:
                o = old.get(s["name"])
                if o and o["state"] != s["state"]:
                    sev = "critical" if s["state"] == "failed" else "warning" if s["state"] != "running" else "ok"
                    self._change(st, host, hid, f'service {s["name"]} : {o["state"]} → {s["state"]}', sev, "service_changed")
        if st["ok"] is False:
            self._change(st, host, hid, "de nouveau joignable", "ok", "host_up")
        mp = 100 * m["mem_used"] / m["mem_total"] if m["mem_total"] else 0
        entry = [round(now), m["cpu"], round(mp, 1), round(m["rx_rate"]), round(m["tx_rate"])]
        with self.lock:
            st["history"] = (st["history"] + [entry])[-HISTORY_POINTS:]
            st.update(ok=True, error="", metrics=m, t=now, t_data=now, ms=round((now - t0) * 1000))

    def _on_failure(self, hid, host, st, error: str) -> None:
        with self.lock:
            was_ok = st["ok"] is not False
            st.update(ok=False, error=error[:300], t=time.time())
        if was_ok:
            self._change(st, host, hid, "injoignable : " + error[:120], "critical", "host_down")

    def observations(self) -> list:
        """Mesures pour le moteur d'alertes ; une machine injoignable ne publie que `reachable`."""
        out = []
        with self.lock:
            snapshot = [(hid, dict(h), self.live.get(hid)) for hid, h in self.hosts.items()]
        for hid, host, st in snapshot:
            if not st or st.get("ok") is None:
                continue
            base = {"target": hid, "name": host["name"]}
            out.append({**base, "metric": "reachable", "value": 1.0 if st["ok"] else 0.0})
            m = st.get("metrics")
            if not st["ok"] or not m:
                continue
            out.append({**base, "metric": "cpu_pct", "value": float(m["cpu"])})
            if m["mem_total"]:
                out.append({**base, "metric": "mem_pct", "value": round(100 * m["mem_used"] / m["mem_total"], 1)})
            for d in m["disks"]:
                if d.get("total"):
                    out.append({**base, "metric": "disk_free_pct", "item": d["name"],
                                "value": round(100 * d["free"] / d["total"], 1)})
                    out.append({**base, "metric": "disk_free_gb", "item": d["name"],
                                "value": round(d["free"] / 1024 ** 3, 1)})
            for s in m["services"]:
                if s["state"] == "failed" or s.get("start") == "auto":
                    fault = s["state"] == "failed" or s["state"] != "running"
                    out.append({**base, "metric": "service_fault", "item": s["name"], "value": 1.0 if fault else 0.0})
            out.append({**base, "metric": "errors_recent", "value": float(len(m["events"]))})
        return out

    def counts(self) -> Dict[str, Any]:
        view = self.view()
        down = [h for h in view if h["ok"] is False]
        faults = 0
        for h in view:
            m = h.get("metrics") or {}
            faults += sum(1 for s in m.get("services", [])
                          if s["state"] == "failed" or (s.get("start") == "auto" and s["state"] != "running"))
        return {"total": len(view), "down": len(down), "service_faults": faults}
