"""Жильё: поиск по Airbnb в прямоугольнике вокруг курорта (библиотека pyairbnb).

Официального API у Airbnb нет: pyairbnb повторяет запросы сайта и может ломаться.
Booking.com открытого API для частных лиц не даёт, Hotellook (Travelpayouts)
закрыт с 20.10.2025 — поэтому здесь только Airbnb.
"""
from __future__ import annotations

import datetime as dt
import statistics


def _total(listing: dict, nights: int) -> float:
    price = listing.get("price") or {}
    # Самый точный источник — строка «Total» в разбивке (со скидками и налогами).
    for row in price.get("break_down") or []:
        if str(row.get("description", "")).strip().lower() == "total" and row.get("amount"):
            return float(row["amount"])
    total = (price.get("total") or {}).get("amount") or 0
    if total:
        return float(total)
    u = price.get("unit") or {}
    unit = u.get("discount") or u.get("amount") or 0
    if not unit:
        return 0.0
    # qualifier "total" — в unit уже цена за весь срок, умножать на ночи не надо
    return float(unit) if u.get("qualifier") == "total" else float(unit) * nights


def summarize(listings: list[dict], nights: int, top_n: int = 5) -> dict:
    """Сводка цен по выдаче: минимум, 25-й перцентиль, медиана, самые дешёвые варианты."""
    rows = []
    for l in listings:
        total = _total(l, nights)
        if total <= 0:
            continue
        rows.append({
            "total": round(total, 2),
            "title": l.get("name") or l.get("title") or "",
            "rating": (l.get("rating") or {}).get("value") or 0,
            "url": f"https://www.airbnb.com/rooms/{l.get('room_id')}",
        })
    rows.sort(key=lambda r: r["total"])
    if not rows:
        return {"n": 0, "min": None, "p25": None, "median": None, "top": []}
    prices = [r["total"] for r in rows]
    p25 = prices[0] if len(prices) < 4 else statistics.quantiles(prices, n=4)[0]
    good = [r for r in rows if r["rating"] >= 4.5] or rows
    return {
        "n": len(rows),
        "min": prices[0],
        "p25": round(p25, 2),
        "median": round(statistics.median(prices), 2),
        "top": good[:top_n],
    }


def search_url(resort: dict, check_in: dt.date, check_out: dt.date, party: dict) -> str:
    s, w, n, e = resort["lodging_bbox"]
    kids = len(party.get("children", []))
    return (
        "https://www.airbnb.com/s/homes?"
        f"checkin={check_in}&checkout={check_out}&adults={party['adults']}&children={kids}"
        f"&ne_lat={n}&ne_lng={e}&sw_lat={s}&sw_lng={w}&search_by_map=true&room_types%5B%5D=Entire%20home%2Fapt"
    )


def fetch(resort: dict, check_in: dt.date, nights: int, party: dict, cfg: dict) -> dict:
    import pyairbnb

    s, w, n, e = resort["lodging_bbox"]
    check_out = check_in + dt.timedelta(days=nights)
    lc = cfg["lodging"]
    listings = pyairbnb.search_all(
        check_in=check_in.isoformat(),
        check_out=check_out.isoformat(),
        ne_lat=n, ne_long=e, sw_lat=s, sw_long=w,
        zoom_value=12,
        price_min=0, price_max=0,
        place_type=lc.get("place_type", ""),
        adults=party["adults"],
        children=len(party.get("children", [])),
        min_bedrooms=lc.get("min_bedrooms", 0),
        currency=cfg["trip"]["currency"],
        language="en",
    )
    out = summarize(listings, nights)
    out["search_url"] = search_url(resort, check_in, check_out, party)
    return out
