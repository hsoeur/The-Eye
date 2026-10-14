"""Supervision de machines Windows (WinRM) et Linux (SSH)."""
import base64, json, os, re, subprocess, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).parent
FILE = BASE / "data" / "hosts.json"
NOWIN = 0x08000000 if os.name == "nt" else 0
INTERVAL = 10

hosts = {}      # id -> config (contient le secret chiffré, jamais exposé)
live = {}       # id -> dernier état
busy = set()
lock = threading.Lock()
local_ips = set()

LINUX_SCRIPT = r"""
echo "##host"; hostname
echo "##os"; . /etc/os-release 2>/dev/null; echo "$PRETTY_NAME $(uname -r)"
echo "##uptime"; cut -d' ' -f1 /proc/uptime
echo "##cpu"; head -1 /proc/stat; sleep 1; head -1 /proc/stat
echo "##nproc"; nproc
echo "##mem"; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
echo "##disk"; df -P -B1 -x tmpfs -x devtmpfs -x overlay -x squashfs 2>/dev/null | tail -n +2
echo "##net"; tail -n +3 /proc/net/dev
echo "##procs"; ps -eo pid,comm,%cpu,rss --sort=-rss 2>/dev/null | head -16
echo "##count"; ps -e --no-headers | wc -l
echo "##services"; systemctl list-units --type=service --all --no-legend --no-pager --plain 2>/dev/null
echo "##ports"; ss -tlnH 2>/dev/null | awk '{print $4}'
echo "##events"; journalctl -p err -n 15 --no-pager -o short-iso 2>/dev/null
"""


def save():
    FILE.parent.mkdir(exist_ok=True)
    with lock:
        FILE.write_text(json.dumps(hosts, indent=1), encoding="utf-8")


def load():
    if FILE.exists():
        try:
            hosts.update(json.loads(FILE.read_text(encoding="utf-8")))
        except Exception:
            pass


def ps(script, env, timeout):
    e = {**os.environ, **env}
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       capture_output=True, text=True, timeout=timeout, creationflags=NOWIN, env=e, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


def encrypt_secret(pw):
    if not pw or os.name != "nt":
        return ""
    _, out, _ = ps("ConvertTo-SecureString $env:EYE_PW -AsPlainText -Force | ConvertFrom-SecureString", {"EYE_PW": pw}, 20)
    return out.strip()


WIN_WRAPPER = r"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
try {
$sb=[scriptblock]::Create((Get-Content -Raw -Encoding UTF8 $env:EYE_SCRIPT))
if($env:EYE_LOCAL -eq '1'){ & $sb }
else{
  $a=@{ComputerName=$env:EYE_IP;ScriptBlock=$sb}
  if($env:EYE_USER){
    $pw = if($env:EYE_SEC){ConvertTo-SecureString $env:EYE_SEC}else{New-Object System.Security.SecureString}
    $a.Credential=New-Object PSCredential($env:EYE_USER,$pw)
  }
  Invoke-Command @a
}
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
"""


def clean_err(err):
    if "CLIXML" in err:
        parts = re.findall(r'<S S="Error">(.*?)</S>', err, re.S)
        err = " ".join(parts) if parts else ""
        err = re.sub(r"_x000D__x000A_", " ", err)
    return re.sub(r"\s+", " ", err).strip()


def collect_windows(h):
    local = h["ip"] in local_ips or h["ip"] in ("127.0.0.1", "localhost")
    env = {"EYE_SCRIPT": str(BASE / "collect_win.ps1"), "EYE_IP": h["ip"], "EYE_LOCAL": "1" if local else "0",
           "EYE_USER": h.get("user", ""), "EYE_SEC": h.get("secret", "")}
    code, out, err = ps(WIN_WRAPPER, env, 90)
    if code != 0 or not out.strip():
        raise RuntimeError((clean_err(err) or "aucune réponse")[:300])
    return json.loads(out)


def collect_linux(h):
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=accept-new"]
    if h.get("key"):
        cmd += ["-i", h["key"]]
    cmd += [f'{h.get("user") or "root"}@{h["ip"]}', "sh -s"]
    r = subprocess.run(cmd, input=LINUX_SCRIPT, capture_output=True, text=True, timeout=45,
                       creationflags=NOWIN, errors="ignore")
    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError((r.stderr.strip() or "SSH échoué")[:300])
    return parse_linux(r.stdout)


def parse_linux(txt):
    s, cur = {}, None
    for line in txt.splitlines():
        if line.startswith("##"):
            cur = line[2:]
            s[cur] = []
        elif cur:
            s[cur].append(line)
    g = lambda k: s.get(k, [])
    cpu = 0.0
    try:
        a = list(map(int, g("cpu")[0].split()[1:])); b = list(map(int, g("cpu")[1].split()[1:]))
        ta, tb = sum(a), sum(b)
        idle = (b[3] + b[4]) - (a[3] + a[4])
        cpu = round(100 * (1 - idle / max(1, tb - ta)), 1)
    except Exception:
        pass
    mem = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in g("mem") if ":" in l}
    disks = []
    for l in g("disk"):
        p = l.split()
        if len(p) >= 6:
            disks.append({"name": p[5], "total": float(p[1]), "free": float(p[3])})
    rx = tx = 0.0
    for l in g("net"):
        if ":" in l and not l.strip().startswith("lo:"):
            f = l.split(":")[1].split()
            rx += float(f[0]); tx += float(f[8])
    procs = []
    for l in g("procs")[1:]:
        p = l.split(None, 3)
        if len(p) == 4:
            procs.append({"pid": int(p[0]), "name": p[1], "cpu": float(p[2]), "mem": float(p[3]) * 1024})
    services = []
    for l in g("services"):
        p = l.split(None, 4)
        if len(p) >= 4:
            sub = p[3]
            services.append({"name": re.sub(r"\.service$", "", p[0]), "display": p[4] if len(p) > 4 else "",
                             "state": "failed" if p[2] == "failed" else "running" if sub == "running" else "stopped",
                             "start": ""})
    events = []
    for l in g("events"):
        m = re.match(r"(\S+)\s+\S+\s+([^:\s]+)(?:\[\d+\])?:\s*(.*)", l)
        if m:
            events.append({"t": m.group(1), "src": m.group(2), "msg": m.group(3)[:200]})
    return {"hostname": (g("host") or [""])[0], "os": (g("os") or [""])[0], "uptime_s": float((g("uptime") or ["0"])[0] or 0),
            "cpu": cpu, "cores": int((g("nproc") or ["1"])[0] or 1),
            "mem_total": mem.get("MemTotal", 0), "mem_used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
            "net_rx": rx, "net_tx": tx, "disks": disks, "procs": procs, "nproc": int((g("count") or ["0"])[0] or 0),
            "services": services, "ports": sorted({int(x.rsplit(":", 1)[1]) for x in g("ports") if ":" in x and x.rsplit(":", 1)[1].isdigit()}),
            "events": events[::-1]}


def poll(hid):
    h = hosts.get(hid)
    if not h:
        return
    st = live.setdefault(hid, {"history": [], "changes": [], "ok": None, "metrics": None, "error": "", "t": 0})
    t0 = time.time()
    try:
        m = collect_windows(h) if h["os"] == "windows" else collect_linux(h)
        now = time.time()
        prev = st.get("metrics")
        if prev and st.get("t_data") and m.get("net_rx") is not None:
            dt = max(1, now - st["t_data"])
            m["rx_rate"] = max(0, (m["net_rx"] - prev.get("net_rx", 0)) / dt)
            m["tx_rate"] = max(0, (m["net_tx"] - prev.get("net_tx", 0)) / dt)
        else:
            m["rx_rate"] = m["tx_rate"] = 0
        if prev:
            old = {s["name"]: s for s in prev.get("services", [])}
            for s in m.get("services", []):
                o = old.get(s["name"])
                if o and o["state"] != s["state"]:
                    st["changes"].append({"t": now, "msg": f'Service {s["name"]} : {o["state"]} → {s["state"]}'})
        if st["ok"] is False:
            st["changes"].append({"t": now, "msg": "Machine de nouveau joignable"})
        mp = 100 * m["mem_used"] / m["mem_total"] if m.get("mem_total") else 0
        st["history"] = (st["history"] + [[round(now), m["cpu"], round(mp, 1), round(m["rx_rate"]), round(m["tx_rate"])]])[-120:]
        st.update(ok=True, error="", metrics=m, t=now, t_data=now, ms=round((now - t0) * 1000))
    except Exception as e:
        if st["ok"] is not False:
            st["changes"].append({"t": time.time(), "msg": "Machine injoignable : " + str(e)[:120]})
        st.update(ok=False, error=str(e)[:300], t=time.time())
    st["changes"] = st["changes"][-60:]
    busy.discard(hid)


def loop():
    ex = ThreadPoolExecutor(8)
    while True:
        now = time.time()
        for hid in list(hosts):
            st = live.get(hid)
            if hid not in busy and (not st or now - st["t"] >= INTERVAL):
                busy.add(hid)
                ex.submit(poll, hid)
        time.sleep(1)


def start(ips):
    local_ips.update(ips)
    load()
    threading.Thread(target=loop, daemon=True).start()


def view():
    return [{"id": i, "name": h["name"], "ip": h["ip"], "os": h["os"], "user": h.get("user", ""), **live.get(i, {"ok": None})}
            for i, h in hosts.items()]


def add(b):
    ip = str(b.get("ip", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,100}", ip):
        raise ValueError("IP / nom invalide")
    osn = b.get("os")
    if osn not in ("windows", "linux"):
        raise ValueError("OS invalide")
    user = str(b.get("user", "")).strip()
    if user and not re.fullmatch(r"[\w.\-\\@]{1,100}", user):
        raise ValueError("Utilisateur invalide")
    h = {"name": str(b.get("name") or ip)[:60], "ip": ip, "os": osn, "user": user,
         "secret": encrypt_secret(b.get("password", "")) if osn == "windows" else "",
         "key": str(b.get("key", "")).strip() if osn == "linux" else ""}
    hid = uuid.uuid4().hex[:8]
    hosts[hid] = h
    save()
    return hid


def remove(hid):
    hosts.pop(hid, None)
    live.pop(hid, None)
    save()
