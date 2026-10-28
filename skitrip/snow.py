"""Снег на высоте курорта: Open-Meteo, бесплатно и без ключа."""
from __future__ import annotations

import json
import urllib.request

URL = "https://api.open-meteo.com/v1/forecast"


def fetch(resort: dict) -> dict:
    lat, lon = resort["coords"]
    q = (
        f"{URL}?latitude={lat}&longitude={lon}&elevation={resort['top_m']}"
        "&hourly=snow_depth&daily=snowfall_sum&forecast_days=7&past_days=7&timezone=Europe%2FBerlin"
    )
    with urllib.request.urlopen(q, timeout=30) as r:
        data = json.load(r)
    return parse(data)


def parse(data: dict) -> dict:
    depths = [d for d in data["hourly"]["snow_depth"] if d is not None]
    falls = data["daily"]["snowfall_sum"]
    past, future = falls[:7], falls[7:]
    return {
        "depth_cm": round(depths[len(depths) // 2] * 100) if depths else None,  # сегодня ≈ середина ряда
        "fresh_7d_cm": round(sum(x or 0 for x in past)),
        "forecast_7d_cm": round(sum(x or 0 for x in future)),
    }
