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
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(flights)")}
        if "source" not in cols:  # google | self (самостоятельная пересадка); detail — расписание
            self.db.execute("ALTER TABLE flights ADD COLUMN source TEXT")
            self.db.execute("ALTER TABLE flights ADD COLUMN detail TEXT")
            self.db.commit()

    @staticmethod
    def now() -> str:
        return dt.datetime.now().isoformat(timespec="seconds")

    def add_flight(self, origin, dest, out, ret, q: dict | None, source: str = "google"):
        q = q or {}
        self.db.execute(
            "INSERT INTO flights (scanned_at, origin, dest, out_date, ret_date, price, airlines, stops, url, source, detail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.now(), origin, dest, str(out), str(ret), q.get("price"), q.get("airlines"), q.get("stops"),
             q.get("url"), source, q.get("detail")),
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
        """{(аэропорт, дата вылета): [последняя цена по каждому городу вылета и источнику]}."""
        rows = self.db.execute("""
          SELECT f.* FROM flights f JOIN (
            SELECT origin, dest, out_date, ret_date, COALESCE(source,'google') s, MAX(scanned_at) m
            FROM flights GROUP BY origin, dest, out_date, ret_date, s
          ) l ON f.origin=l.origin AND f.dest=l.dest AND f.out_date=l.out_date AND f.ret_date=l.ret_date
             AND COALESCE(f.source,'google')=l.s AND f.scanned_at=l.m""").fetchall()
        out: dict = {}
        for r in rows:
            out.setdefault((r["dest"], r["out_date"]), []).append(dict(r))
        return out

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
