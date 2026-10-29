"""Перелёт туда-обратно на всю группу через Google Flights (библиотека fast-flights).

У Google Flights нет публичного API: fast-flights повторяет запрос сайта и может
сломаться при изменениях Google. Цена — минимальная в выдаче, за всех пассажиров.
"""
from __future__ import annotations

import datetime as dt
import os
import urllib.parse


def google_link(origin: str, dest: str, out: dt.date, ret: dt.date, adults: int, children: int) -> str:
    q = f"Flights from {origin} to {dest} on {out.isoformat()} through {ret.isoformat()} for {adults} adults and {children} children"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


# Из ЕС Google сначала показывает окно согласия на cookies. SOCS — ответ «отклонить всё»
# (только необходимые cookies), с ним сразу отдаётся страница с рейсами.
CONSENT_COOKIE = "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"
URL = "https://www.google.com/travel/flights"


def fetch_html(query) -> str:
    from primp import Client

    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True,
                    proxy=os.environ.get("FLIGHTS_PROXY") or None)
    return client.get(URL, params=query.params(), headers={"Cookie": CONSENT_COOKIE}).text


def parse(html: str) -> list[dict]:
    """Рейсы из встроенного JSON страницы. Рейсы без цены пропускаются (fast-flights на них падает)."""
    import json

    from fast_flights.exceptions import FlightsNotFound
    from selectolax.lexbor import LexborHTMLParser

    script = LexborHTMLParser(html).css_first(r"script.ds\:1")
    if script is None:
        raise RuntimeError("Google не отдал страницу с рейсами (блокировка или согласие на cookies)")
    data = script.text().split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        raise FlightsNotFound("no flights")
    payload = json.loads(data)
    out = []
    for block in (payload[2], payload[3]):  # «лучшие» и «остальные»
        for k in (block or [None])[0] or []:
            try:
                price = k[1][0][1]
                flight = k[0]
            except (IndexError, TypeError):
                continue
            if price:
                out.append({"price": float(price), "airlines": flight[1] or [], "legs": len(flight[2] or [])})
    return out


def _search(legs: list[tuple[str, str, dt.date]], trip: str, party: dict, cfg: dict) -> dict | None:
    """Самый дешёвый вариант в выдаче Google или None."""
    from fast_flights import FlightQuery, FlightsNotFound, Passengers, create_query

    query = create_query(
        flights=[FlightQuery(date=d.isoformat(), from_airport=a, to_airport=b) for a, b, d in legs],
        trip=trip,
        passengers=Passengers(adults=party["adults"], children=len(party.get("children", []))),
        currency=cfg["trip"]["currency"],
        language="en-GB",
        max_stops=cfg["flights"].get("max_stops"),
    )
    try:
        results = parse(fetch_html(query))
    except FlightsNotFound:
        return None
    return min(results, key=lambda r: r["price"]) if results else None


def fetch_roundtrip(origin: str, dest: str, out: dt.date, ret: dt.date, party: dict, cfg: dict) -> dict | None:
    n_kids = len(party.get("children", []))
    url = google_link(origin, dest, out, ret, party["adults"], n_kids)
    best = _search([(origin, dest, out), (dest, origin, ret)], "round-trip", party, cfg)
    if best:
        return {"price": best["price"], "airlines": ", ".join(best["airlines"]),
                "stops": max(best["legs"] - 1, 0), "url": url}
    # На части дат Google не отдаёт цену туда-обратно, хотя рейсы в одну сторону есть —
    # тогда складываем два билета в одну сторону.
    there = _search([(origin, dest, out)], "one-way", party, cfg)
    if not there:
        return None
    back = _search([(dest, origin, ret)], "one-way", party, cfg)
    if not back:
        return None
    airlines = list(dict.fromkeys(there["airlines"] + back["airlines"]))
    return {"price": there["price"] + back["price"], "airlines": ", ".join(airlines) + " (2 × в одну сторону)",
            "stops": max(there["legs"], back["legs"]) - 1, "url": url}


def fetch_best(origin: str, dest: str, out: dt.date, ret: dt.date, party: dict, cfg: dict) -> dict | None:
    """Дешевле из Google Flights и прямого запроса к Ryanair."""
    from . import ryanair

    google = fetch_roundtrip(origin, dest, out, ret, party, cfg)
    try:
        fr = ryanair.fetch_roundtrip(origin, dest, out, ret, party, cfg)
    except Exception:  # Ryanair недоступен — остаёмся с Google
        fr = None
    options = [x for x in (google, fr) if x]
    return min(options, key=lambda x: x["price"]) if options else None
