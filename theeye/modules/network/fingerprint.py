"""Identification des équipements : constructeur (MAC) et type probable (ports, nom)."""
import json
import re
from pathlib import Path
from typing import Dict

PORTS = {21: "FTP", 22: "SSH", 23: "Telnet", 53: "DNS", 80: "HTTP", 135: "RPC", 139: "NetBIOS",
         161: "SNMP", 443: "HTTPS", 445: "SMB", 502: "Modbus", 515: "LPD", 631: "IPP",
         1433: "MSSQL", 1883: "MQTT", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
         5900: "VNC", 5985: "WinRM", 8080: "HTTP-alt", 8443: "HTTPS-alt", 9100: "JetDirect",
         44818: "EtherNet/IP", 102: "S7 (Siemens)", 47808: "BACnet"}

DEVICE_TYPES = ("router", "switch", "server", "windows", "linux", "printer", "plc", "vm",
                "web", "iot", "unknown")

OUI_FALLBACK = {"00:0C:29": "VMware", "00:50:56": "VMware", "00:05:69": "VMware", "08:00:27": "VirtualBox",
                "00:15:5D": "Hyper-V", "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi",
                "E4:5F:01": "Raspberry Pi", "00:1B:21": "Intel", "3C:D9:2B": "HP", "00:1E:0B": "HP",
                "00:00:0C": "Cisco", "00:1A:A1": "Cisco", "00:0E:C6": "Cisco", "F8:B1:56": "Dell",
                "00:14:22": "Dell", "00:1C:23": "Dell", "00:1D:09": "Dell", "00:0F:B5": "Netgear",
                "00:09:5B": "Netgear", "FC:EC:DA": "Ubiquiti", "24:A4:3C": "Ubiquiti", "00:27:22": "Ubiquiti",
                "00:80:F4": "Telemecanique", "00:0E:8C": "Siemens", "00:1B:1B": "Siemens",
                "00:00:BC": "Rockwell", "00:1D:9C": "Rockwell", "00:11:32": "Synology",
                "00:08:9B": "QNAP", "00:C0:EE": "Kyocera", "00:00:48": "Epson", "00:80:92": "Brother",
                "00:1E:8F": "Canon", "00:17:C8": "Kyocera", "00:1F:A4": "Zebra", "00:A0:F8": "Zebra"}


def load_oui(path: Path) -> Dict[str, str]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def vendor_of(mac: str, oui_db: Dict[str, str]) -> str:
    if not mac:
        return ""
    k = mac.replace(":", "")[:6]
    v = oui_db.get(k) or OUI_FALLBACK.get(mac[:8], "")
    if not v and len(k) == 6 and k[1] in "0123456789abcdefABCDEF" and int(k[1], 16) & 2:
        return "Adresse aléatoire/privée"
    return v


def guess_type(d: dict) -> str:
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
    if (p & {3389, 445, 5985, 135}) and re.search(r"srv|server|dc\d|sql|app|web", n):
        return "server"
    if p & {3389, 445, 135, 139}:
        return "windows"
    if 22 in p:
        return "linux"
    if p & {80, 443, 8080, 8443}:
        return "web"
    return "unknown"
