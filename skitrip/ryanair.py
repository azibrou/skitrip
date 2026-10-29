"""Ryanair напрямую: публичный API с минимальными тарифами (тот же, что у их сайта).

Цена — базовый тариф на одного пассажира без багажа. Дети 2–11 лет у Ryanair платят
как взрослые, поэтому сумма = (туда + обратно) × число пассажиров.
Wizz Air так подключить нельзя: их сайт закрыт проверкой «вы человек?».
Рейсы Wizz Air видны через Google Flights.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from functools import lru_cache

API = "https://www.ryanair.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(path: str, **params) -> dict | list:
    url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


@lru_cache(maxsize=None)
def routes(origin: str) -> frozenset[str]:
    """Аэропорты, куда Ryanair летает из origin."""
    data = _get(f"views/locate/searchWidget/routes/en/airport/{origin}")
    return frozenset(r["arrivalAirport"]["code"] for r in data)


def cheapest_oneway(origin: str, dest: str, day: dt.date, currency: str = "EUR") -> float | None:
    data = _get("farfnd/v4/oneWayFares", departureAirportIataCode=origin, arrivalAirportIataCode=dest,
                outboundDepartureDateFrom=day.isoformat(), outboundDepartureDateTo=day.isoformat(),
                currency=currency)
    prices = [f["outbound"]["price"]["value"] for f in data.get("fares", []) if f["outbound"].get("price")]
    return min(prices) if prices else None


def fetch_roundtrip(origin: str, dest: str, out: dt.date, ret: dt.date, party: dict, cfg: dict) -> dict | None:
    if dest not in routes(origin):
        return None
    cur = cfg["trip"]["currency"]
    there = cheapest_oneway(origin, dest, out, cur)
    back = cheapest_oneway(dest, origin, ret, cur) if there else None
    if not (there and back):
        return None
    n = party["adults"] + len(party.get("children", []))
    return {
        "price": round((there + back) * n, 2),
        "airlines": "Ryanair (напрямую, без багажа)",
        "stops": 0,
        "url": f"https://www.ryanair.com/gb/en/trip/flights/select?adults={party['adults']}&children={n - party['adults']}"
               f"&dateOut={out}&dateIn={ret}&originIata={origin}&destinationIata={dest}&isReturn=true",
    }
