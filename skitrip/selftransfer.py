"""Перелёт с самостоятельной пересадкой: два отдельных билета Ryanair через хаб.

Туда:    origin → хаб, затем хаб → аэропорт курорта в тот же день, не раньше чем
         через `min_connection_h` часов после прилёта (заново регистрация и багаж).
Обратно: аэропорт курорта → хаб, затем хаб → origin так же.

Хабы — все аэропорты, куда Ryanair летает из origin. Цена — базовые тарифы без
багажа × число пассажиров (дети 2–11 у Ryanair платят как взрослые).
Риск отдельных билетов: при задержке первого рейса второй не ждёт.
"""
from __future__ import annotations

import datetime as dt
import time
import urllib.parse
from functools import lru_cache

from .ryanair import _get

WINDOWS = [("00:00", "11:59"), ("12:00", "23:59")]


def _fares(dep: str, day: dt.date, t_from: str = "00:00", t_to: str = "23:59", arr: str | None = None,
           currency: str = "EUR") -> list[dict]:
    """Самый дешёвый рейс на каждое направление из dep в окне времени."""
    return list(_fares_cached(dep, day.isoformat(), t_from, t_to, arr, currency))


@lru_cache(maxsize=None)
def _fares_cached(dep, day, t_from, t_to, arr, currency) -> tuple:
    params = dict(departureAirportIataCode=dep, outboundDepartureDateFrom=day, outboundDepartureDateTo=day,
                  outboundDepartureTimeFrom=t_from, outboundDepartureTimeTo=t_to, currency=currency, limit=300)
    if arr:
        params["arrivalAirportIataCode"] = arr
    time.sleep(0.3)
    data = _get("farfnd/v4/oneWayFares", **params)
    out = []
    for f in data.get("fares", []):
        o = f["outbound"]
        if not o.get("price"):
            continue
        out.append({
            "from": o["departureAirport"]["iataCode"], "to": o["arrivalAirport"]["iataCode"],
            "dep": dt.datetime.fromisoformat(o["departureDate"]), "arr": dt.datetime.fromisoformat(o["arrivalDate"]),
            "price": float(o["price"]["value"]), "flight": o.get("flightNumber", ""),
        })
    return tuple(out)


def _first_legs(dep: str, day: dt.date, cur: str, arr: str | None = None) -> list[dict]:
    """Кандидаты первого плеча: самый дешёвый рейс утром и самый дешёвый после обеда."""
    legs = []
    for a, b in WINDOWS:
        legs += _fares(dep, day, a, b, arr, cur)
    return legs


def _connect(leg1: dict, dest: str | None, cur: str, min_h: float) -> list[dict]:
    """Вторые плечи из точки прилёта leg1 в тот же день с запасом min_h часов."""
    earliest = leg1["arr"] + dt.timedelta(hours=min_h)
    # вся дорога — в один календарный день: без ночёвки в аэропорту
    if not (leg1["dep"].date() == leg1["arr"].date() == earliest.date()):
        return []
    return _fares(leg1["to"], earliest.date(), earliest.strftime("%H:%M"), "23:59", dest, cur)


def _pair_str(a: dict, b: dict) -> str:
    return f"{a['from']}→{a['to']} {a['dep']:%H:%M}–{a['arr']:%H:%M}, {b['from']}→{b['to']} {b['dep']:%H:%M}–{b['arr']:%H:%M}"


def search_week(origin: str, out: dt.date, ret: dt.date, dests: set[str], party: dict, cfg: dict) -> dict[str, dict]:
    """Лучший вариант с самостоятельной пересадкой для каждого аэропорта из dests."""
    cur = cfg["trip"]["currency"]
    min_h = cfg.get("self_transfer", {}).get("min_connection_h", 3)
    n = party["adults"] + len(party.get("children", []))

    # Туда: origin → хаб → dest
    best_out: dict[str, tuple[float, dict, dict]] = {}
    for leg1 in _first_legs(origin, out, cur):
        if leg1["to"] in dests:  # это прямой рейс, его считает Google/Ryanair напрямую
            continue
        for leg2 in _connect(leg1, None, cur, min_h):
            if leg2["to"] not in dests:
                continue
            p = leg1["price"] + leg2["price"]
            if leg2["to"] not in best_out or p < best_out[leg2["to"]][0]:
                best_out[leg2["to"]] = (p, leg1, leg2)

    # Обратно: dest → хаб → origin
    results = {}
    for dest, (p_out, o1, o2) in best_out.items():
        best_back = None
        for leg1 in _first_legs(dest, ret, cur):
            if leg1["to"] == origin:
                continue
            for leg2 in _connect(leg1, origin, cur, min_h):
                p = leg1["price"] + leg2["price"]
                if best_back is None or p < best_back[0]:
                    best_back = (p, leg1, leg2)
        if not best_back:
            continue
        p_back, b1, b2 = best_back
        results[dest] = {
            "price": round((p_out + p_back) * n, 2),
            "airlines": f"Ryanair, 2 билета через {o1['to']}/{b1['to']} — самостоятельная пересадка",
            "stops": 1,
            "url": "https://www.ryanair.com/",
            "detail": f"туда: {_pair_str(o1, o2)}; обратно: {_pair_str(b1, b2)}",
        }
    return results


# --- Хаб с отдельными билетами любых авиакомпаний (Google) + Ryanair из хаба ---

def _ok(a: dict, b: dict, min_h: float) -> bool:
    """b вылетает в тот же день, что a, не раньше чем через min_h часов после прилёта a."""
    return (a["dep"].date() == a["arr"].date() == b["dep"].date()
            and b["dep"] >= a["arr"] + dt.timedelta(hours=min_h))


def ryanair_routes(airport: str) -> frozenset[str]:
    from . import ryanair
    return ryanair.routes(airport)


def _ryanair_legs(dep: str, arr: str, day: dt.date, n: int, cur: str) -> list[dict]:
    from . import ryanair
    if arr not in ryanair.routes(dep):
        return []
    legs = []
    for a, b in WINDOWS:
        for f in _fares(dep, day, a, b, arr, cur):
            legs.append({**f, "price": f["price"] * n, "airline": "Ryanair"})
    return legs


def _best_pair(first: list[dict], second: list[dict], min_h: float):
    best = None
    for a in first:
        for b in second:
            if _ok(a, b, min_h) and (best is None or a["price"] + b["price"] < best[0]):
                best = (a["price"] + b["price"], a, b)
    return best


def _leg_str(x: dict) -> str:
    return f"{x['from']}→{x['to']} {x['dep']:%H:%M}–{x['arr']:%H:%M} {x.get('airline', '')}".strip()


def search_hub_week(origin: str, hub: str, out: dt.date, ret: dt.date, dests: list[str], party: dict,
                    cfg: dict, delay=(3, 6)) -> dict[str, dict]:
    """origin → hub (отдельный билет) → прямой рейс до аэропорта курорта, и так же обратно."""
    import random

    from .flights import oneway_options

    cur = cfg["trip"]["currency"]
    min_h = cfg.get("self_transfer", {}).get("min_connection_h", 3)
    n = party["adults"] + len(party.get("children", []))

    def google(a, b, day):
        time.sleep(random.uniform(*delay))
        return oneway_options(a, b, day, party, cfg)

    to_hub, from_hub = google(origin, hub, out), google(hub, origin, ret)
    if not to_hub or not from_hub:
        return {}
    results = {}
    for d in dests:
        there = google(hub, d, out) + _ryanair_legs(hub, d, out, n, cur)
        p_out = _best_pair(to_hub, there, min_h)
        if not p_out:
            continue
        back = google(d, hub, ret) + _ryanair_legs(d, hub, ret, n, cur)
        p_back = _best_pair(back, from_hub, min_h)
        if not p_back:
            continue
        airlines = sorted({x["airline"] for x in (p_out[1], p_out[2], p_back[1], p_back[2]) if x.get("airline")})
        results[d] = {
            "price": round(p_out[0] + p_back[0], 2),
            "airlines": f"{', '.join(airlines)} — 2 билета через {hub}, самостоятельная пересадка",
            "stops": 1,
            "url": f"https://www.google.com/travel/flights?q=" + urllib.parse.quote(f"one way flights from {hub} to {d} on {out}"),
            "detail": f"туда: {_leg_str(p_out[1])}, {_leg_str(p_out[2])}; обратно: {_leg_str(p_back[1])}, {_leg_str(p_back[2])}",
        }
    return results
