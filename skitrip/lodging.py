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


ROOM_TYPES = {"entire": "Entire%20home%2Fapt", "hotel": "Hotel%20room"}


def guests_key(party: dict) -> str:
    """'2+1' — взрослые + дети; так помечаются цены жилья в базе."""
    return f"{party['adults']}+{len(party.get('children', []))}"


def search_url(resort: dict, check_in: dt.date, check_out: dt.date, party: dict, kind: str = "entire",
               min_bedrooms: int = 0) -> str:
    s, w, n, e = resort["lodging_bbox"]
    kids = len(party.get("children", []))
    return (
        "https://www.airbnb.com/s/homes?"
        f"checkin={check_in}&checkout={check_out}&adults={party['adults']}&children={kids}"
        f"&ne_lat={n}&ne_lng={e}&sw_lat={s}&sw_lng={w}&search_by_map=true&room_types%5B%5D={ROOM_TYPES[kind]}"
        + (f"&min_bedrooms={min_bedrooms}" if min_bedrooms else "")
    )


def fetch(resort: dict, check_in: dt.date, nights: int, party: dict, cfg: dict, kind: str = "entire",
          min_bedrooms: int | None = None) -> dict:
    """Airbnb: kind='entire' — жильё целиком, 'hotel' — номера отелей и апарт-отелей."""
    import pyairbnb

    s, w, n, e = resort["lodging_bbox"]
    check_out = check_in + dt.timedelta(days=nights)
    lc = cfg["lodging"]
    if min_bedrooms is None:
        min_bedrooms = lc.get("min_bedrooms", 0)
    if kind == "hotel":
        url = search_url(resort, check_in, check_out, party, "hotel")
        listings = pyairbnb.search_all_from_url(url, currency=cfg["trip"]["currency"], language="en")
        out = summarize(listings, nights)
        out["search_url"] = url
        return out
    listings = pyairbnb.search_all(
        check_in=check_in.isoformat(),
        check_out=check_out.isoformat(),
        ne_lat=n, ne_long=e, sw_lat=s, sw_long=w,
        zoom_value=12,
        price_min=0, price_max=0,
        place_type=lc.get("place_type", ""),
        adults=party["adults"],
        children=len(party.get("children", [])),
        min_bedrooms=min_bedrooms,
        currency=cfg["trip"]["currency"],
        language="en",
    )
    out = summarize(listings, nights)
    out["search_url"] = search_url(resort, check_in, check_out, party, "entire", min_bedrooms)
    return out


# --- Google Hotels: отели и апартаменты с Booking и сайтов отелей ---

COUNTRY = {"AT": "Austria", "IT": "Italy", "FR": "France", "CH": "Switzerland"}


def hotel_place(resort: dict) -> str:
    """Название места для Google Hotels — со страной, иначе Google путает (Längenfeld → Langenfeld у Дюссельдорфа)."""
    place = (resort.get("base_hotel_query") or resort.get("base_name") or resort.get("hotel_query")
             or resort["name"].split(" /")[0].split(" (")[0].split(" –")[0])
    return f"{place}, {COUNTRY.get(resort['country'], resort['country'])}"


SKIP_WORDS = ("camping", "campsite", "camp&")


def _google_hotels_page(place: str, check_in: dt.date, check_out: dt.date, nights: int, cfg: dict,
                        gl: str = "ee") -> list[dict] | None:
    """Отели из одной выдачи. None — Google не понял даты (цены не за nights ночей)."""
    import re
    import urllib.parse

    from primp import Client
    from selectolax.lexbor import LexborHTMLParser

    from .flights import CONSENT_COOKIE

    q = f"hotels in {place} from {check_in:%-d %B %Y} to {check_out:%-d %B %Y} for 2 adults"
    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True)
    html = client.get("https://www.google.com/travel/search",
                      params={"q": q, "hl": "en-GB", "gl": gl, "curr": cfg["trip"]["currency"]},
                      headers={"Cookie": CONSENT_COOKIE}).text
    seen, rows, wrong = set(), [], 0
    for node in LexborHTMLParser(html).css("div.CQYfx.UDzrdc"):
        box = node.parent.text(separator=" ").replace("\xa0", " ") if node.parent else ""
        m = re.search(r"([\d,]+)\s*total", box)
        k = re.search(r"(\d+)\s+nights?", box)
        if not m:
            continue
        if not k or int(k.group(1)) != nights:  # цена не за весь срок
            wrong += 1
            continue
        card = node
        for _ in range(12):
            card = card.parent
            if card is None or card.css("h2"):
                break
        if card is None or not card.css("h2"):
            continue
        name = card.css("h2")[0].text().strip()
        if name in seen or any(w in name.lower() for w in SKIP_WORDS):
            continue
        seen.add(name)
        rows.append({"title": name, "total": float(m.group(1).replace(",", "")), "rating": 0,
                     "url": "https://www.google.com/travel/search?q=" + urllib.parse.quote(f"{name} {place}")})
    if not rows and wrong:
        return None
    return rows


def google_hotels(resort: dict, check_in: dt.date, nights: int, cfg: dict, top_n: int = 5) -> dict:
    """Цена за весь срок с налогами по каждому отелю в выдаче Google Hotels.

    Google не учитывает число гостей из запроса: цены — за номер на 2 взрослых.
    Берутся только цены, где Google явно пишет «N nights» с нашим числом ночей.
    """
    import urllib.parse

    check_out = check_in + dt.timedelta(days=nights)
    place = hotel_place(resort)
    # «Breuil-Cervinia» Google понимает хуже, чем «Cervinia» — пробуем упрощённые названия
    head, _, country = place.rpartition(", ")
    variants = list(dict.fromkeys([place, f"{head.replace('-', ' ')}, {country}",
                                   f"{head.split('-')[-1].strip()}, {country}"]))
    rows = None
    for v in variants:
        rows = _google_hotels_page(v, check_in, check_out, nights, cfg, gl=resort["country"].lower())
        if rows is not None:
            place = v
            break
    rows = sorted(rows or [], key=lambda r: r["total"])
    url = "https://www.google.com/travel/search?q=" + urllib.parse.quote(
        f"hotels in {place} from {check_in:%-d %B %Y} to {check_out:%-d %B %Y} for 2 adults")
    if not rows:
        return {"n": 0, "min": None, "p25": None, "median": None, "top": [], "search_url": url}
    prices = [r["total"] for r in rows]
    p25 = prices[0] if len(prices) < 4 else statistics.quantiles(prices, n=4)[0]
    return {"n": len(rows), "min": prices[0], "p25": round(p25, 2), "median": round(statistics.median(prices), 2),
            "top": rows[:top_n], "search_url": url}
