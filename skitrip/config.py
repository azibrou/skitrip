from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(path: str | Path | None = None) -> dict:
    cfg = _load(Path(path) if path else ROOT / "config.yaml")
    for ch in cfg["party"].get("children", []):
        if isinstance(ch["birth_date"], str):
            ch["birth_date"] = dt.date.fromisoformat(ch["birth_date"])
    return cfg


def load_resorts(path: str | Path | None = None) -> list[dict]:
    """Курорты; каждая запись из `bases` становится отдельным вариантом «ледник + жильё в соседнем посёлке»."""
    out = []
    for r in _load(Path(path) if path else ROOT / "resorts.yaml")["resorts"]:
        out.append(r)
        for b in r.get("bases") or []:
            out.append({**r, "id": f"{r['id']}@{b['id']}", "name": f"{r['name']} · жильё в {b['name']}",
                        "lodging_bbox": b["lodging_bbox"], "base_of": r["id"], "base_name": b["name"],
                        "base_km": b["km"], "base_note": b.get("note", ""), "bases": []})
    return out


def checkin_dates(cfg: dict) -> list[dt.date]:
    t = cfg["trip"]
    d, end = t["season_from"], t["season_to"]
    while d.weekday() != t["checkin_weekday"]:
        d += dt.timedelta(days=1)
    out = []
    while d <= end:
        out.append(d)
        d += dt.timedelta(days=7)
    return out
