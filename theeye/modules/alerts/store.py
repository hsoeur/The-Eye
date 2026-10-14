"""Persistance des alertes : MySQL/MariaDB (production) ou SQLite (secours, développement), même schéma.

Les dates sont stockées en UTC (DATETIME(3)) et converties en secondes epoch côté application.
Toutes les écritures sont idempotentes (identifiants générés par l'application), ce qui permet de les rejouer
après une indisponibilité de la base (voir journal.py).
"""
import calendar
import json
import logging
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("eye.alerts.store")
VENDOR = Path(__file__).resolve().parents[3] / "vendor"
ALERT_COLUMNS = ("fingerprint", "rule_id", "rule_name", "source", "target", "target_name", "item", "metric", "severity",
                 "state", "started_at", "resolved_at", "resolve_reason", "value", "peak_value", "threshold", "operator",
                 "message", "acked", "ack_by", "ack_comment", "ack_at", "ack_until", "ack_ip", "silenced",
                 "silence_name", "suppressed_by", "flaps", "notes", "reopened", "updated_at")
TIME_COLUMNS = ("started_at", "resolved_at", "ack_at", "ack_until", "updated_at")
CLIP = {"fingerprint": 255, "rule_id": 64, "rule_name": 120, "source": 32, "target": 128, "target_name": 255,
        "item": 255, "metric": 64, "severity": 16, "state": 16, "resolve_reason": 32, "operator": 4, "ack_by": 80,
        "ack_ip": 64, "silence_name": 120, "suppressed_by": 32}

MIGRATIONS: List[List[str]] = [[
    "CREATE TABLE schema_version (version INT NOT NULL)",
    "CREATE TABLE meta (k VARCHAR(64) NOT NULL PRIMARY KEY, v TEXT)",
    "CREATE TABLE alert_rules (id VARCHAR(64) NOT NULL PRIMARY KEY, name VARCHAR(120) NOT NULL, "
    "metric VARCHAR(64) NOT NULL, enabled TINYINT NOT NULL, data TEXT NOT NULL, updated_at DATETIME(3) NOT NULL)",
    "CREATE TABLE maintenance_windows (id VARCHAR(64) NOT NULL PRIMARY KEY, name VARCHAR(120) NOT NULL, "
    "data TEXT NOT NULL, updated_at DATETIME(3) NOT NULL)",
    "CREATE TABLE alerts (id VARCHAR(32) NOT NULL PRIMARY KEY, fingerprint VARCHAR(255) NOT NULL, "
    "rule_id VARCHAR(64) NOT NULL, rule_name VARCHAR(120) NOT NULL, source VARCHAR(32) NOT NULL, "
    "target VARCHAR(128) NOT NULL, target_name VARCHAR(255) NOT NULL, item VARCHAR(255) NOT NULL, "
    "metric VARCHAR(64) NOT NULL, severity VARCHAR(16) NOT NULL, state VARCHAR(16) NOT NULL, "
    "started_at DATETIME(3) NOT NULL, resolved_at DATETIME(3) NULL, resolve_reason VARCHAR(32) NOT NULL, "
    "value DOUBLE NOT NULL, peak_value DOUBLE NOT NULL, threshold DOUBLE NOT NULL, operator VARCHAR(4) NOT NULL, "
    "message TEXT NOT NULL, acked TINYINT NOT NULL, ack_by VARCHAR(80) NOT NULL, ack_comment TEXT NOT NULL, "
    "ack_at DATETIME(3) NULL, ack_until DATETIME(3) NULL, ack_ip VARCHAR(64) NOT NULL, silenced TINYINT NOT NULL, "
    "silence_name VARCHAR(120) NOT NULL, suppressed_by VARCHAR(32) NULL, flaps INT NOT NULL, notes INT NOT NULL, "
    "reopened INT NOT NULL, updated_at DATETIME(3) NOT NULL)",
    "CREATE INDEX idx_alerts_state ON alerts (state, started_at)",
    "CREATE INDEX idx_alerts_target ON alerts (target, started_at)",
    "CREATE INDEX idx_alerts_started ON alerts (started_at)",
    "CREATE INDEX idx_alerts_fp ON alerts (fingerprint, started_at)",
    "CREATE TABLE alert_events (id VARCHAR(32) NOT NULL PRIMARY KEY, alert_id VARCHAR(32) NOT NULL, "
    "t DATETIME(3) NOT NULL, type VARCHAR(24) NOT NULL, author VARCHAR(80) NOT NULL, comment TEXT NOT NULL, "
    "severity VARCHAR(16) NOT NULL, value DOUBLE NULL, data TEXT NOT NULL)",
    "CREATE INDEX idx_events_alert ON alert_events (alert_id, t)",
    "CREATE INDEX idx_events_t ON alert_events (t)",
]]


class StoreUnavailable(Exception):
    """Base injoignable : l'opération pourra être rejouée plus tard."""


class StoreError(Exception):
    """Opération rejetée par la base (donnée invalide...) : inutile de la rejouer."""


def to_dt(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def to_epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return calendar.timegm(value.utctimetuple()) + value.microsecond / 1e6
    text = str(value)
    parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f" if "." in text else "%Y-%m-%d %H:%M:%S")
    return calendar.timegm(parsed.utctimetuple()) + parsed.microsecond / 1e6


def _clip(key: str, value: Any) -> Any:
    limit = CLIP.get(key)
    return value[:limit] if limit and isinstance(value, str) else value


class SqlStore:
    def __init__(self, kind: str, cfg: Dict[str, Any], password: str = "", sqlite_path: Optional[Path] = None):
        if kind not in ("mysql", "sqlite"):
            raise ValueError("type de base inconnu : " + kind)
        self.kind, self.cfg, self.password = kind, cfg, password
        self.sqlite_path = sqlite_path
        self._lock = threading.RLock()
        self._conn: Any = None
        self._errors: Tuple[type, ...] = ()
        self.description = (f"{cfg.get('user', '')}@{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 3306)}/"
                            f"{cfg.get('database', 'theeye')}") if kind == "mysql" else str(sqlite_path)

    # --- connexion -----------------------------------------------------------------------------------------------
    def _connect(self) -> Any:
        if self.kind == "sqlite":
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.sqlite_path), timeout=10, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        if VENDOR.is_dir():
            for wheel in sorted(VENDOR.glob("*.whl")):
                if str(wheel) not in sys.path:
                    sys.path.append(str(wheel))
        try:
            import pymysql
        except ImportError:
            raise StoreError("PyMySQL introuvable : installez-le (pip install PyMySQL) ou placez sa roue dans vendor/")
        self._errors = (pymysql.err.OperationalError, pymysql.err.InterfaceError, OSError)
        c = self.cfg
        extra: Dict[str, Any] = {}
        if c.get("tls"):
            extra["ssl"] = {"ca": c["tls_ca"]} if c.get("tls_ca") else {"fake_flag_to_enable_tls": True}
            extra["ssl_verify_cert"] = bool(c.get("tls_ca"))
            extra["ssl_verify_identity"] = False
        return pymysql.connect(host=c.get("host", "127.0.0.1"), port=int(c.get("port", 3306)),
                               user=c.get("user", "theeye"), password=self.password,
                               database=c.get("database", "theeye"), charset="utf8mb4", autocommit=False,
                               connect_timeout=int(c.get("connect_timeout", 5)), read_timeout=30, write_timeout=30,
                               init_command="SET time_zone='+00:00'", **extra)

    def _sql(self, sql: str) -> str:
        return sql.replace("%s", "?") if self.kind == "sqlite" else sql

    def run(self, fn):
        """Exécute fn(cursor) dans une transaction ; reconnecte si besoin et classe les erreurs."""
        with self._lock:
            try:
                if self._conn is None:
                    self._conn = self._connect()
                cur = self._conn.cursor()
                try:
                    result = fn(cur)
                    self._conn.commit()
                    return result
                finally:
                    cur.close()
            except StoreError:
                raise
            except Exception as e:
                self.close()
                if isinstance(e, (sqlite3.OperationalError, ConnectionError, OSError) + self._errors):
                    raise StoreUnavailable(str(e)[:300])
                raise StoreError(str(e)[:300])

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def _exec(self, cur, sql: str, params: tuple = ()) -> None:
        cur.execute(self._sql(sql), params)

    def _rows(self, cur, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cur.execute(self._sql(sql), params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    # --- schéma --------------------------------------------------------------------------------------------------
    def init(self) -> None:
        def migrate(cur):
            if self.kind == "mysql":
                probe = ("SELECT COUNT(*) AS n FROM information_schema.tables "
                         "WHERE table_schema = DATABASE() AND table_name = 'schema_version'")
            else:
                probe = "SELECT COUNT(*) AS n FROM sqlite_master WHERE name = 'schema_version'"
            current = 0
            if self._rows(cur, probe)[0]["n"]:
                current = int(self._rows(cur, "SELECT MAX(version) AS v FROM schema_version")[0]["v"] or 0)
            for number, statements in enumerate(MIGRATIONS, 1):
                if number <= current:
                    continue
                for stmt in statements:
                    if stmt.startswith("CREATE TABLE"):
                        stmt = stmt.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
                        if self.kind == "mysql":
                            stmt += " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
                    try:
                        self._exec(cur, stmt)
                    except Exception as e:
                        # MySQL n'a pas CREATE INDEX IF NOT EXISTS : une migration interrompue doit pouvoir reprendre.
                        if not (stmt.startswith("CREATE INDEX") and "uplicate" in str(e)):
                            raise
                self._exec(cur, "INSERT INTO schema_version (version) VALUES (%s)", (number,))
        self.run(migrate)

    # --- écritures idempotentes ----------------------------------------------------------------------------------
    def _upsert(self, cur, table: str, row: Dict[str, Any]) -> None:
        cols = list(row)
        marks = ", ".join(["%s"] * len(cols))
        updates = [c for c in cols if c != "id"]
        if self.kind == "mysql":
            tail = " ON DUPLICATE KEY UPDATE " + ", ".join(f"{c} = VALUES({c})" for c in updates)
        else:
            tail = " ON CONFLICT(id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in updates)
        self._exec(cur, f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks}){tail}", tuple(row.values()))

    def apply(self, op: Dict[str, Any]) -> None:
        kind, d = op["op"], op["d"]

        def go(cur):
            if kind == "alert":
                row = {"id": d["id"], **{c: _clip(c, d.get(c)) for c in ALERT_COLUMNS}}
                for c in TIME_COLUMNS:
                    row[c] = to_dt(row[c])
                for c in ("acked", "silenced"):
                    row[c] = 1 if row[c] else 0
                for c in ("rule_name", "source", "target_name", "item", "resolve_reason", "ack_by", "ack_ip",
                          "silence_name", "ack_comment", "message"):
                    row[c] = row[c] or ""
                for c in ("flaps", "notes", "reopened"):
                    row[c] = int(row[c] or 0)
                self._upsert(cur, "alerts", row)
            elif kind == "event":
                verb = "INSERT IGNORE" if self.kind == "mysql" else "INSERT OR IGNORE"
                self._exec(cur, f"{verb} INTO alert_events (id, alert_id, t, type, author, comment, severity, value, data) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                           (d["id"], d["alert_id"], to_dt(d["t"]), d["type"][:24], d["author"][:80], d["comment"],
                            d["severity"][:16], d.get("value"), json.dumps(d.get("data") or {}, ensure_ascii=False)))
            elif kind == "rule":
                self._upsert(cur, "alert_rules", {"id": d["id"], "name": d["name"][:120], "metric": d["metric"],
                                                  "enabled": 1 if d.get("enabled", True) else 0,
                                                  "data": json.dumps(d, ensure_ascii=False),
                                                  "updated_at": to_dt(op["t"])})
            elif kind == "rule_del":
                self._exec(cur, "DELETE FROM alert_rules WHERE id = %s", (d["id"],))
            elif kind == "maint":
                self._upsert(cur, "maintenance_windows", {"id": d["id"], "name": d["name"][:120],
                                                          "data": json.dumps(d, ensure_ascii=False),
                                                          "updated_at": to_dt(op["t"])})
            elif kind == "maint_del":
                self._exec(cur, "DELETE FROM maintenance_windows WHERE id = %s", (d["id"],))
            elif kind == "meta":
                self._upsert_meta(cur, d["k"], d["v"])
            else:
                raise StoreError("opération inconnue : " + str(kind))
        self.run(go)

    def _upsert_meta(self, cur, key: str, value: str) -> None:
        if self.kind == "mysql":
            self._exec(cur, "INSERT INTO meta (k, v) VALUES (%s, %s) ON DUPLICATE KEY UPDATE v = VALUES(v)", (key, value))
        else:
            self._exec(cur, "INSERT INTO meta (k, v) VALUES (%s, %s) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                       (key, value))

    # --- lectures ------------------------------------------------------------------------------------------------
    def load_config(self) -> Dict[str, Any]:
        def go(cur):
            rules = [json.loads(r["data"]) for r in self._rows(cur, "SELECT data FROM alert_rules ORDER BY id")]
            maint = [json.loads(r["data"]) for r in self._rows(cur, "SELECT data FROM maintenance_windows ORDER BY id")]
            meta = {r["k"]: r["v"] for r in self._rows(cur, "SELECT k, v FROM meta")}
            return {"rules": rules, "maintenance": maint, "meta": meta}
        return self.run(go)

    def _alert_out(self, row: Dict[str, Any]) -> Dict[str, Any]:
        for c in TIME_COLUMNS:
            row[c] = to_epoch(row.get(c))
        row["acked"], row["silenced"] = bool(row["acked"]), bool(row["silenced"])
        return row

    def load_active(self) -> List[Dict[str, Any]]:
        return self.run(lambda cur: [self._alert_out(r) for r in self._rows(
            cur, "SELECT * FROM alerts WHERE state = 'firing' ORDER BY started_at")])

    def get_alert(self, alert_id: str) -> Optional[Dict[str, Any]]:
        def go(cur):
            rows = self._rows(cur, "SELECT * FROM alerts WHERE id = %s", (alert_id,))
            return self._alert_out(rows[0]) if rows else None
        return self.run(go)

    def events(self, alert_id: str) -> List[Dict[str, Any]]:
        def go(cur):
            rows = self._rows(cur, "SELECT id, alert_id, t, type, author, comment, severity, value, data "
                                   "FROM alert_events WHERE alert_id = %s ORDER BY t, id", (alert_id,))
            for r in rows:
                r["t"] = to_epoch(r["t"])
                try:
                    r["data"] = json.loads(r["data"] or "{}")
                except ValueError:
                    r["data"] = {}
            return rows
        return self.run(go)

    def query(self, f: Dict[str, Any], limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        where, params = ["1 = 1"], []
        if f.get("state") in ("firing", "resolved"):
            where.append("state = %s")
            params.append(f["state"])
        if f.get("severity"):
            where.append("severity = %s")
            params.append(f["severity"])
        if f.get("target"):
            where.append("target = %s")
            params.append(f["target"])
        if f.get("rule"):
            where.append("rule_id = %s")
            params.append(f["rule"])
        if f.get("acked") in (True, False):
            where.append("acked = %s")
            params.append(1 if f["acked"] else 0)
        if f.get("q"):
            like = "%" + str(f["q"]).replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            where.append("(message LIKE %s ESCAPE '!' OR target_name LIKE %s ESCAPE '!' "
                         "OR ack_comment LIKE %s ESCAPE '!' OR ack_by LIKE %s ESCAPE '!')")
            params += [like] * 4
        if f.get("since") is not None:
            where.append("started_at >= %s")
            params.append(to_dt(f["since"]))
        if f.get("until") is not None:
            where.append("started_at <= %s")
            params.append(to_dt(f["until"]))
        clause = " AND ".join(where)

        def go(cur):
            total = self._rows(cur, f"SELECT COUNT(*) AS n FROM alerts WHERE {clause}", tuple(params))[0]["n"]
            rows = self._rows(cur, f"SELECT * FROM alerts WHERE {clause} ORDER BY started_at DESC, id LIMIT %s OFFSET %s",
                              tuple(params) + (int(limit), int(offset)))
            return [self._alert_out(r) for r in rows], int(total)
        return self.run(go)

    def stats(self, since: float) -> Dict[str, Any]:
        rows, _ = self.query({"since": since}, limit=20000)
        by_sev: Dict[str, int] = {}
        noisy: Dict[Tuple[str, str, str], int] = {}
        mtta, mttr = [], []
        for r in rows:
            by_sev[r["severity"]] = by_sev.get(r["severity"], 0) + 1
            key = (r["rule_name"], r["target_name"], r["item"])
            noisy[key] = noisy.get(key, 0) + 1
            if r["ack_at"] and r["ack_at"] >= r["started_at"]:
                mtta.append(r["ack_at"] - r["started_at"])
            if r["resolved_at"]:
                mttr.append(r["resolved_at"] - r["started_at"])
        top = sorted(noisy.items(), key=lambda kv: -kv[1])[:10]
        return {"total": len(rows), "by_severity": by_sev,
                "mtta_s": round(sum(mtta) / len(mtta)) if mtta else None,
                "mttr_s": round(sum(mttr) / len(mttr)) if mttr else None,
                "noisiest": [{"rule": k[0], "target": k[1], "item": k[2], "count": n} for k, n in top]}

    def purge(self, before: float) -> int:
        def go(cur):
            cutoff = to_dt(before)
            ids = [r["id"] for r in self._rows(cur, "SELECT id FROM alerts WHERE state = 'resolved' AND resolved_at < %s "
                                                    "LIMIT 5000", (cutoff,))]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ", ".join(["%s"] * len(chunk))
                self._exec(cur, f"DELETE FROM alert_events WHERE alert_id IN ({marks})", tuple(chunk))
                self._exec(cur, f"DELETE FROM alerts WHERE id IN ({marks})", tuple(chunk))
            return len(ids)
        return self.run(go)

    def ping(self) -> None:
        self.run(lambda cur: self._exec(cur, "SELECT 1"))


def unprotect(runner, blob: str) -> str:
    """Déchiffre un secret protégé par DPAPI (ConvertFrom-SecureString) ; Windows uniquement."""
    if os.name != "nt" or not blob:
        return ""
    r = runner.powershell("$s = ConvertTo-SecureString $env:EYE_SEC; "
                          "[Runtime.InteropServices.Marshal]::PtrToStringAuto("
                          "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))", 20, {"EYE_SEC": blob})
    return r.out.rstrip("\r\n") if r.ok else ""
