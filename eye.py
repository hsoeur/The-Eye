"""The Eye - network discovery & mapping. Stdlib only, Python 3.9+."""
import argparse, ipaddress, json, os, re, socket, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import hosts as hostmon

BASE = Path(__file__).parent
STATIC = BASE / "static"
STATE_FILE = BASE / "data" / "state.json"
STATE_FILE.parent.mkdir(exist_ok=True)
NOWIN = 0x08000000 if os.name == "nt" else 0

PORTS = {21: "FTP", 22: "SSH", 23: "Telnet", 53: "DNS", 80: "HTTP", 135: "RPC", 139: "NetBIOS",
         161: "SNMP", 443: "HTTPS", 445: "SMB", 502: "Modbus", 515: "LPD", 631: "IPP",
         1433: "MSSQL", 1883: "MQTT", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
         5900: "VNC", 5985: "WinRM", 8080: "HTTP-alt", 8443: "HTTPS-alt", 9100: "JetDirect",
         44818: "EtherNet/IP", 102: "S7 (Siemens)", 47808: "BACnet"}

OUI = {"00:0C:29": "VMware", "00:50:56": "VMware", "00:05:69": "VMware", "08:00:27": "VirtualBox",
       "00:15:5D": "Hyper-V", "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi",
       "E4:5F:01": "Raspberry Pi", "00:1B:21": "Intel", "3C:D9:2B": "HP", "00:1E:0B": "HP",
       "00:00:0C": "Cisco", "00:1A:A1": "Cisco", "00:0E:C6": "Cisco", "F8:B1:56": "Dell",
       "00:14:22": "Dell", "00:1C:23": "Dell", "00:1D:09": "Dell", "00:0F:B5": "Netgear",
       "00:09:5B": "Netgear", "FC:EC:DA": "Ubiquiti", "24:A4:3C": "Ubiquiti", "00:27:22": "Ubiquiti",
       "00:80:F4": "Telemecanique", "00:0E:8C": "Siemens", "00:1B:1B": "Siemens",
       "00:00:BC": "Rockwell", "00:1D:9C": "Rockwell", "00:11:32": "Synology",
       "00:08:9B": "QNAP", "00:C0:EE": "Kyocera", "00:00:48": "Epson", "00:80:92": "Brother",
       "00:1E:8F": "Canon", "00:17:C8": "Kyocera", "00:1F:A4": "Zebra", "00:A0:F8": "Zebra"}

try:
    OUI_DB = json.loads((BASE / "oui.json").read_text(encoding="utf-8"))
except Exception:
    OUI_DB = {}


def vendor_of(mac):
    if not mac:
        return ""
    k = mac.replace(":", "")[:6]
    v = OUI_DB.get(k) or OUI.get(mac[:8], "")
    if not v and int(k[1], 16) & 2:
        return "Adresse aléatoire/privée"
    return v


lock = threading.Lock()
state = {"devices": {}, "scans": [], "gateway": None, "subnets": []}
progress = {"running": False, "phase": "idle", "done": 0, "total": 0, "started": 0, "subnet": ""}


def run(cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=NOWIN, errors="ignore").stdout
    except Exception:
        return ""


def local_networks():
    """Return [(ip, prefix)] of local IPv4 interfaces, and default gateway."""
    nets, gw = [], None
    if os.name == "nt":
        out = run(["powershell", "-NoProfile", "-Command",
                   "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '169.254*' -and $_.IPAddress -ne '127.0.0.1'} | "
                   "Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress"])
        try:
            data = json.loads(out)
            for d in data if isinstance(data, list) else [data]:
                nets.append((d["IPAddress"], int(d["PrefixLength"])))
        except Exception:
            pass
        m = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", run(["route", "print", "-4", "0.0.0.0"]))
        gw = m.group(1) if m else None
    else:
        for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", run(["ip", "-4", "addr"])):
            if not m.group(1).startswith("127."):
                nets.append((m.group(1), int(m.group(2))))
        m = re.search(r"default via (\S+)", run(["ip", "route"]))
        gw = m.group(1) if m else None
    return nets, gw


def ping(ip):
    if os.name == "nt":
        cmd = ["ping", "-n", "1", "-w", "700", ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    out = run(cmd, 5)
    return ("TTL=" in out.upper()), (re.search(r"TTL=(\d+)", out, re.I) or [None, None])[1]


def arp_table():
    res = {}
    for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2})",
                         run(["arp", "-a"]), re.I):
        mac = m.group(2).upper().replace("-", ":")
        if not mac.startswith(("FF:FF", "01:00:5E")):
            res[m.group(1)] = mac
    return res


def rdns(ip):
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except Exception:
        return ""


def netbios_name(ip):
    if os.name != "nt":
        return ""
    m = re.search(r"^\s*(\S+)\s+<00>\s+UNIQUE", run(["nbtstat", "-A", ip], 4), re.M)
    return m.group(1) if m else ""


def port_open(ip, port, t=0.6):
    try:
        with socket.create_connection((ip, port), timeout=t):
            return True
    except Exception:
        return False


def scan_ports(ip):
    return sorted(p for p in PORTS if port_open(ip, p))


def guess_type(d):
    p, v, n = set(d.get("ports", [])), d.get("vendor", "").lower(), d.get("hostname", "").lower()
    if d.get("is_gateway"):
        return "router"
    if 9100 in p or 515 in p or 631 in p or any(k in v for k in ("kyocera", "epson", "brother", "canon")):
        return "printer"
    if p & {502, 44818, 102, 47808} or any(k in v for k in ("siemens", "rockwell", "telemecanique")):
        return "plc"
    if any(k in v for k in ("vmware", "hyper-v", "virtualbox")):
        return "vm"
    if "raspberry" in v:
        return "iot"
    if any(k in v for k in ("cisco", "ubiquiti", "netgear")) and not (p & {3389, 445}):
        return "switch"
    if p & {1433, 3306, 5432}:
        return "database"
    if (p & {3389, 445, 5985, 135}) and re.search(r"srv|server|dc\d|sql|app|web", n):
        return "server"
    if p & {3389, 445, 135, 139}:
        return "windows"
    if 22 in p:
        return "linux"
    if p & {80, 443, 8080, 8443}:
        return "web"
    return "unknown"


def save():
    with lock:
        STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def load():
    if STATE_FILE.exists():
        try:
            state.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass


def scan(cidrs=None, do_ports=True):
    if progress["running"]:
        return
    progress.update(running=True, phase="init", done=0, total=0, started=time.time())
    try:
        nets, gw = local_networks()
        local_ips = {ip for ip, _ in nets}
        if not cidrs:
            cidrs = [str(ipaddress.ip_interface(f"{ip}/{pf}").network) for ip, pf in nets if pf >= 22] \
                or [str(ipaddress.ip_interface(f"{ip}/24").network) for ip, _ in nets]
        networks = list(dict.fromkeys(ipaddress.ip_network(c, strict=False) for c in cidrs))
        hosts = [str(h) for n in networks for h in n.hosts()][:4096]
        state["subnets"] = [str(n) for n in networks]
        state["gateway"] = gw
        now = time.time()

        progress.update(phase="ping", total=len(hosts), done=0)
        alive = {}

        def p(ip):
            ok, ttl = ping(ip)
            progress["done"] += 1
            if ok:
                alive[ip] = ttl

        with ThreadPoolExecutor(128) as ex:
            list(ex.map(p, hosts))
        arp = arp_table()
        for ip in arp:
            if ip in hosts and ip not in alive:
                alive[ip] = None
        for ip in local_ips & set(hosts):
            alive.setdefault(ip, None)

        progress.update(phase="details", total=len(alive), done=0)

        def detail(ip):
            d = {"ip": ip, "ttl": alive[ip], "mac": arp.get(ip, "")}
            d["vendor"] = vendor_of(d["mac"])
            d["hostname"] = rdns(ip) or netbios_name(ip)
            d["ports"] = scan_ports(ip) if do_ports else []
            progress["done"] += 1
            return d

        with ThreadPoolExecutor(48) as ex:
            found = list(ex.map(detail, alive))

        with lock:
            devs = state["devices"]
            for d in found:
                old = devs.get(d["ip"])
                d["is_gateway"] = d["ip"] == gw
                d["is_self"] = d["ip"] in local_ips
                d["first_seen"] = old["first_seen"] if old else now
                d["new"] = old is None and bool(devs)
                d["last_seen"] = now
                d["online"] = True
                d["label"] = old.get("label", "") if old else ""
                if not d["hostname"] and old:
                    d["hostname"] = old.get("hostname", "")
                if not d["ports"] and old and not do_ports:
                    d["ports"] = old.get("ports", [])
                d["type"] = (old or {}).get("forced_type") or guess_type(d)
                if old and old.get("forced_type"):
                    d["forced_type"] = old["forced_type"]
                devs[d["ip"]] = d
            seen = {d["ip"] for d in found}
            scanned = {str(h) for n in networks for h in n.hosts()}
            for ip, d in devs.items():
                if ip not in seen and ip in scanned:
                    d["online"] = False
                    d["new"] = False
            state["scans"] = (state["scans"] + [{"t": now, "found": len(found)}])[-50:]
        save()
    finally:
        progress.update(running=False, phase="idle")


docker = {"available": False, "error": "", "containers": [], "history": {}, "t": 0, "actions": False}
PS_FMT = ('{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","state":"{{.State}}",'
          '"status":"{{.Status}}","ports":"{{.Ports}}","project":"{{.Label "com.docker.compose.project"}}"}')


def pct(s):
    try:
        return float(s.strip().rstrip("%"))
    except Exception:
        return 0.0


def docker_poll():
    while True:
        try:
            r = subprocess.run(["docker", "ps", "-a", "--format", PS_FMT], capture_output=True, text=True,
                               timeout=20, creationflags=NOWIN, errors="ignore")
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "docker indisponible")
            cs = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
            st = {}
            s = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], capture_output=True,
                               text=True, timeout=30, creationflags=NOWIN, errors="ignore")
            for l in s.stdout.splitlines():
                try:
                    j = json.loads(l)
                    st[j["ID"]] = j
                except Exception:
                    pass
            now = time.time()
            for c in cs:
                j = st.get(c["id"], {})
                c.update(cpu=pct(j.get("CPUPerc", "0")), mem_pct=pct(j.get("MemPerc", "0")),
                         mem=j.get("MemUsage", ""), net=j.get("NetIO", ""), blk=j.get("BlockIO", ""),
                         pids=j.get("PIDs", ""), health="healthy" if "(healthy)" in c["status"] else
                         "unhealthy" if "(unhealthy)" in c["status"] else "starting" if "(health: starting)" in c["status"] else "")
                h = docker["history"].setdefault(c["id"], [])
                h.append([round(now), c["cpu"], c["mem_pct"]])
                del h[:-90]
            for k in set(docker["history"]) - {c["id"] for c in cs}:
                del docker["history"][k]
            docker.update(available=True, error="", containers=cs, t=now)
        except FileNotFoundError:
            docker.update(available=False, error="CLI docker introuvable", containers=[])
        except Exception as e:
            docker.update(available=False, error=str(e)[:200], containers=[])
        time.sleep(2)


def docker_cmd(args, timeout=30):
    r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout,
                       creationflags=NOWIN, errors="ignore")
    return r.returncode == 0, (r.stdout + r.stderr)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self.send(200, {**state, "ports": PORTS, "progress": progress, "now": time.time()})
        if path == "/api/hosts":
            return self.send(200, {"hosts": hostmon.view(), "now": time.time()})
        if path == "/api/docker":
            return self.send(200, {**docker, "now": time.time()})
        if path == "/api/docker/logs":
            cid = re.search(r"id=([0-9a-f]{12,64})", self.path)
            if not cid:
                return self.send(400, {"error": "id invalide"})
            ok, out = docker_cmd(["logs", "--tail", "200", "--timestamps", cid.group(1)])
            return self.send(200, {"logs": out[-30000:]})
        if path == "/":
            path = "/index.html"
        f = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() in f.parents and f.is_file():
            ct = {".js": "text/javascript", ".html": "text/html; charset=utf-8", ".css": "text/css"}.get(f.suffix, "application/octet-stream")
            return self.send(200, f.read_bytes(), ct)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        b = self.body()
        if self.path == "/api/hosts/add":
            try:
                return self.send(200, {"id": hostmon.add(b)})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
        if self.path == "/api/hosts/delete":
            hostmon.remove(b.get("id"))
            return self.send(200, {"ok": True})
        if self.path == "/api/docker/action":
            if not docker["actions"]:
                return self.send(403, {"error": "actions désactivées (lancer avec --docker-actions)"})
            cid, act = str(b.get("id", "")), b.get("action")
            if not re.fullmatch(r"[0-9a-f]{12,64}", cid) or act not in ("start", "stop", "restart"):
                return self.send(400, {"error": "requête invalide"})
            ok, out = docker_cmd([act, cid], 60)
            return self.send(200 if ok else 500, {"ok": ok, "out": out[-500:]})
        if self.path == "/api/scan":
            cidrs = [c for c in b.get("cidrs", []) if isinstance(c, str)]
            try:
                for c in cidrs:
                    ipaddress.ip_network(c, strict=False)
            except ValueError:
                return self.send(400, {"error": "CIDR invalide"})
            threading.Thread(target=scan, args=(cidrs or None, b.get("ports", True)), daemon=True).start()
            return self.send(200, {"ok": True})
        if self.path == "/api/device":
            d = state["devices"].get(b.get("ip"))
            if not d:
                return self.send(404, {"error": "unknown"})
            if "label" in b:
                d["label"] = str(b["label"])[:80]
            if "type" in b:
                d["type"] = d["forced_type"] = str(b["type"])[:20]
            save()
            return self.send(200, {"ok": True})
        if self.path == "/api/forget":
            state["devices"].pop(b.get("ip"), None)
            save()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


def auto_loop(minutes):
    while True:
        time.sleep(minutes * 60)
        scan()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="The Eye - cartographie réseau")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--auto", type=int, default=15, help="re-scan toutes les N minutes (0 = off)")
    ap.add_argument("--docker-actions", action="store_true", help="autorise start/stop/restart des containers depuis l'UI")
    a = ap.parse_args()
    load()
    docker["actions"] = a.docker_actions
    hostmon.start({ip for ip, _ in local_networks()[0]})
    threading.Thread(target=docker_poll, daemon=True).start()
    if a.auto:
        threading.Thread(target=auto_loop, args=(a.auto,), daemon=True).start()
    threading.Thread(target=scan, daemon=True).start()
    print(f"The Eye -> http://localhost:{a.port}")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
