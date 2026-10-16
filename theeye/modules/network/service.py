"""Logique métier du scan réseau : balayage, fusion dans l'inventaire, événements."""
import copy
import ipaddress
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from ...core.module import Context
from ...core.netinfo import local_networks
from .discovery import Probes
from .fingerprint import PORTS, guess_type, vendor_of

MAX_HOSTS = 4096
LEGACY_TYPE_ALIASES = {"database": "server"}


class NetworkService:
    def __init__(self, ctx: Context, probes: Probes, oui: Dict[str, str]):
        self.ctx, self.probes, self.oui = ctx, probes, oui
        self.store = ctx.store("state")
        self.lock = threading.RLock()
        self.state: Dict[str, Any] = {"devices": {}, "scans": [], "gateway": None, "subnets": []}
        self.state.update(self.store.load())
        for device in self.state.get("devices", {}).values():
            if device.get("type") in LEGACY_TYPE_ALIASES:
                device["type"] = LEGACY_TYPE_ALIASES[device["type"]]
            if device.get("forced_type") in LEGACY_TYPE_ALIASES:
                device["forced_type"] = LEGACY_TYPE_ALIASES[device["forced_type"]]
        self.progress = {"running": False, "phase": "idle", "done": 0, "total": 0, "started": 0, "subnet": ""}
        self.last_error = ""
        self._scan_lock = threading.Lock()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {**copy.deepcopy(self.state), "ports": PORTS, "progress": dict(self.progress), "now": time.time()}

    def start_scan(self, cidrs: Optional[List[str]] = None, do_ports: bool = True) -> bool:
        if self._scan_lock.locked():
            return False
        self.ctx.scheduler.submit(self.scan, cidrs, do_ports)
        return True

    def scan(self, cidrs: Optional[List[str]] = None, do_ports: bool = True) -> None:
        if not self._scan_lock.acquire(blocking=False):
            return
        try:
            self._scan(cidrs, do_ports)
            self.last_error = ""
        except Exception as e:
            self.last_error = str(e)[:200]
            self.ctx.log.exception("scan en échec")
            self.ctx.emit("scan_failed", f"Scan réseau en échec : {self.last_error}", "warning")
        finally:
            self.progress.update(running=False, phase="idle")
            self._scan_lock.release()

    def _tick(self) -> None:
        with self.lock:
            self.progress["done"] += 1

    def _scan(self, cidrs: Optional[List[str]], do_ports: bool) -> None:
        self.progress.update(running=True, phase="init", done=0, total=0, started=time.time())
        nets, gw = local_networks(self.ctx.runner)
        local_ips = {ip for ip, _ in nets}
        if not cidrs:
            cidrs = [str(ipaddress.ip_interface(f"{ip}/{pf}").network) for ip, pf in nets if pf >= 22] \
                or [str(ipaddress.ip_interface(f"{ip}/24").network) for ip, _ in nets]
        networks = list(dict.fromkeys(ipaddress.ip_network(c, strict=False) for c in cidrs))
        all_hosts = [str(h) for n in networks for h in n.hosts()]
        hosts = all_hosts[:MAX_HOSTS]
        now = time.time()
        with self.lock:
            self.state["subnets"] = [str(n) for n in networks]
            self.state["gateway"] = gw
            known = set(self.state["devices"])

        self.progress.update(phase="ping", total=len(hosts), done=0)
        alive: Dict[str, Optional[str]] = {}

        def sweep(ip: str) -> None:
            ok, ttl = self.probes.ping(ip)
            if not ok and ip in known:
                ok, ttl = self.probes.ping(ip)
            self._tick()
            if ok:
                alive[ip] = ttl

        with ThreadPoolExecutor(128) as ex:
            list(ex.map(sweep, hosts))
        arp = self.probes.arp_table()
        hostset = set(hosts)
        for ip in arp:
            if ip in hostset:
                alive.setdefault(ip, None)
        for ip in local_ips & hostset:
            alive.setdefault(ip, None)

        self.progress.update(phase="details", total=len(alive), done=0)

        def detail(ip: str) -> Dict[str, Any]:
            d = {"ip": ip, "ttl": alive[ip], "mac": arp.get(ip, "")}
            d["vendor"] = vendor_of(d["mac"], self.oui)
            d["hostname"] = self.probes.reverse_dns(ip) or self.probes.netbios_name(ip)
            d["ports"] = self.probes.open_ports(ip) if do_ports else []
            self._tick()
            return d

        with ThreadPoolExecutor(48) as ex:
            found = list(ex.map(detail, alive))

        self._merge(found, gw, local_ips, set(all_hosts), do_ports, now)
        self.store.save(self.state_for_save())

    def state_for_save(self) -> Dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.state)

    def _merge(self, found, gw, local_ips, scanned, do_ports, now) -> None:
        events = []
        with self.lock:
            devs = self.state["devices"]
            inventory_was_empty = not devs
            for d in found:
                old = devs.get(d["ip"])
                d.update(is_gateway=d["ip"] == gw, is_self=d["ip"] in local_ips, last_seen=now, online=True,
                         first_seen=old["first_seen"] if old else now,
                         new=old is None and not inventory_was_empty,
                         label=old.get("label", "") if old else "")
                if not d["hostname"] and old:
                    d["hostname"] = old.get("hostname", "")
                if not d["ports"] and old and not do_ports:
                    d["ports"] = old.get("ports", [])
                forced = LEGACY_TYPE_ALIASES.get((old or {}).get("forced_type"), (old or {}).get("forced_type"))
                d["type"] = forced or guess_type(d)
                if forced:
                    d["forced_type"] = forced
                devs[d["ip"]] = d
                name = d["label"] or d["hostname"] or d["ip"]
                if d["new"]:
                    events.append(("device_new", f"Nouvel équipement : {name} ({d['ip']})", "warning", d["ip"]))
                elif old and not old.get("online", True):
                    events.append(("device_up", f"{name} ({d['ip']}) est de nouveau en ligne", "ok", d["ip"]))
            seen = {d["ip"] for d in found}
            for ip, d in devs.items():
                if ip not in seen and ip in scanned:
                    if d.get("online", True):
                        events.append(("device_down", f"{d.get('label') or d.get('hostname') or ip} ({ip}) ne répond plus", "info", ip))
                    d["online"] = False
                    d["new"] = False
            self.state["scans"] = (self.state["scans"] + [{"t": now, "found": len(found)}])[-50:]
        for kind, msg, sev, ip in events:
            self.ctx.emit(kind, msg, sev, ip=ip)

    def update_device(self, ip: str, label: Optional[str], dtype: Optional[str]) -> bool:
        with self.lock:
            d = self.state["devices"].get(ip)
            if not d:
                return False
            if label is not None:
                d["label"] = label[:80]
            if dtype:
                d["type"] = d["forced_type"] = dtype
        self.store.save(self.state_for_save())
        return True

    def forget(self, ip: str) -> None:
        with self.lock:
            self.state["devices"].pop(ip, None)
        self.store.save(self.state_for_save())
