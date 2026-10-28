"""История цен в SQLite: каждое сканирование дописывается, отчёт берёт последнее значение."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
  scanned_at TEXT, origin TEXT, dest TEXT, out_date TEXT, ret_date TEXT,
  price REAL, airlines TEXT, stops INTEGER, url TEXT);
CREATE TABLE IF NOT EXISTS lodging (
  scanned_at TEXT, resort TEXT, check_in TEXT, nights INTEGER,
  n INTEGER, min REAL, p25 REAL, median REAL, top_json TEXT, search_url TEXT);
CREATE TABLE IF NOT EXISTS snow (
  scanned_at TEXT, resort TEXT, depth_cm INTEGER, fresh_7d_cm INTEGER, forecast_7d_cm INTEGER);
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    @staticmethod
    def now() -> str:
        return dt.datetime.now().isoformat(timespec="seconds")

    def add_flight(self, origin, dest, out, ret, q: dict | None):
        q = q or {}
        self.db.execute(
            "INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?)",
            (self.now(), origin, dest, str(out), str(ret), q.get("price"), q.get("airlines"), q.get("stops"), q.get("url")),
        )
        self.db.commit()

    def add_lodging(self, resort_id, check_in, nights, s: dict):
        self.db.execute(
            "INSERT INTO lodging VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.now(), resort_id, str(check_in), nights, s["n"], s["min"], s["p25"], s["median"],
             json.dumps(s["top"], ensure_ascii=False), s.get("search_url")),
        )
        self.db.commit()

    def add_snow(self, resort_id, s: dict):
        self.db.execute("INSERT INTO snow VALUES (?,?,?,?,?)",
                        (self.now(), resort_id, s["depth_cm"], s["fresh_7d_cm"], s["forecast_7d_cm"]))
        self.db.commit()

    # --- последние значения ---
    def latest_flights(self) -> dict:
        rows = self.db.execute("""
          SELECT f.* FROM flights f JOIN (
            SELECT dest, out_date, ret_date, MAX(scanned_at) m FROM flights GROUP BY dest, out_date, ret_date
          ) l ON f.dest=l.dest AND f.out_date=l.out_date AND f.ret_date=l.ret_date AND f.scanned_at=l.m""").fetchall()
        return {(r["dest"], r["out_date"]): dict(r) for r in rows}

    def flight_history(self, dest, out_date) -> list[float]:
        rows = self.db.execute(
            "SELECT price FROM flights WHERE dest=? AND out_date=? AND price IS NOT NULL ORDER BY scanned_at",
            (dest, out_date)).fetchall()
        return [r[0] for r in rows]

    def latest_lodging(self) -> dict:
        rows = self.db.execute("""
          SELECT g.* FROM lodging g JOIN (
            SELECT resort, check_in, MAX(scanned_at) m FROM lodging GROUP BY resort, check_in
          ) l ON g.resort=l.resort AND g.check_in=l.check_in AND g.scanned_at=l.m""").fetchall()
        out = {}
        for r in rows:
            d = dict(r)
            d["top"] = json.loads(d.pop("top_json") or "[]")
            out[(r["resort"], r["check_in"])] = d
        return out

    def latest_snow(self) -> dict:
        rows = self.db.execute("""
          SELECT s.* FROM snow s JOIN (SELECT resort, MAX(scanned_at) m FROM snow GROUP BY resort) l
          ON s.resort=l.resort AND s.scanned_at=l.m""").fetchall()
        return {r["resort"]: dict(r) for r in rows}
