"""Сборка полной стоимости: перелёт + машина + жильё + ски-пассы, для каждого курорта и недели."""
from __future__ import annotations

import datetime as dt

from .passes import party_pass_cost, pass_party


def origins(cfg: dict) -> dict[str, float]:
    """Города вылета → наземная дорога до аэропорта на всю группу."""
    return cfg["trip"].get("origins") or {cfg["trip"]["origin"]: 0}


def transfer_cost(km: float, cfg: dict) -> float:
    t = cfg["transfer"]
    return round(t["car_rent_week"] + 2 * km * t["per_km"], 2)


def scaled_party(party: dict, families: int) -> dict:
    """Несколько одинаковых семей: взрослые и дети умножаются."""
    return {**party, "adults": party["adults"] * families, "children": list(party.get("children", [])) * families}


def scenarios(cfg: dict) -> list[dict]:
    """Составы группы для переключателя в отчёте.

    families: N — N одинаковых семей из party; adults/children — отдельный состав (дети берутся из party).
    """
    out = []
    for sc in cfg.get("scenarios") or [1]:
        if not isinstance(sc, dict):
            sc = {"families": sc}
        if "adults" in sc:
            party = {**cfg["party"], "adults": sc["adults"], "children": list(cfg["party"].get("children", []))[: sc.get("children", 0)]}
            pp = {**party, "children": party["children"] if cfg["trip"].get("pass_children", True) else []}
            units = 1
            key = sc.get("key") or f"a{sc['adults']}c{len(party['children'])}"
            label = sc.get("label") or f"{sc['adults']} adults"
        else:
            f = sc["families"]
            party, pp, units = scaled_party(cfg["party"], f), scaled_party(pass_party(cfg), f), f
            key = sc.get("key") or f"f{f}"
            label = sc.get("label") or ("1 family" if f == 1 else f"{f} families")
        base = cfg["party"]["adults"] + len(cfg["party"].get("children", []))
        seats = party["adults"] + len(party["children"])
        out.append({"key": key, "label": label, "party": party, "pass_party": pp, "units": units,
                    "seats": seats, "air_ratio": seats / base})
    return out


def gkey(party: dict) -> str:
    return f"{party['adults']}+{len(party.get('children', []))}"


def lodging_choice(rows, cfg: dict, families: int):
    """Самое дешёвое жильё на группу из families семей: (цена, сводка, что это)."""
    stat = cfg["lodging"]["stat"]
    g1, gf = gkey(cfg["party"]), gkey(scaled_party(cfg["party"], families))
    rows = [rows] if isinstance(rows, dict) else (rows or [])
    many = f" × {families}" if families > 1 else ""
    cands = []
    for row in rows:
        price = row.get(stat)
        if price is None:
            continue
        kind, guests = row.get("kind") or "entire", row.get("guests") or g1
        if kind == "entire" and guests == gf:
            cands.append((price, row, "entire home" + (" for everyone" if families > 1 else "")))
        elif kind == "entire" and guests == g1 and families > 1:
            cands.append((price * families, row, f"a home per family{many}"))
        elif kind == "hotel" and guests == g1:
            cands.append((price * families, row, f"hotel room, Airbnb{many}"))
        elif kind == "ghotel":
            cands.append((price * families, row, f"hotel, Google Hotels — room for 2 adults{many}"))
    return min(cands, key=lambda c: c[0]) if cands else (None, None, None)


def build(cfg: dict, resorts: list[dict], weeks: list[dt.date], flights: dict, lodging: dict, snow: dict,
          families: int = 1, scenario: dict | None = None) -> list[dict]:
    sc = scenario or scenarios({**cfg, "scenarios": [families]})[0]
    party, families, ratio = sc["party"], sc["units"], sc["air_ratio"]
    nights = cfg["trip"]["nights"]
    stat = cfg["lodging"]["stat"]
    n_people = party["adults"] + len(party.get("children", []))
    bags = cfg["costs"].get("ski_bag_per_person_rt", 0) * n_people
    orig = origins(cfg)
    options = []
    for r in resorts:
        for wk in weeks:
            first_ski = wk + dt.timedelta(days=1)
            passes = party_pass_cost(r, sc["pass_party"], first_ski)

            best_air = None
            for code, km in r["airports"].items():
                quotes = flights.get((code, str(wk))) or []
                for f in [quotes] if isinstance(quotes, dict) else quotes:
                    if f.get("price") is None:
                        continue
                    origin = f.get("origin") or cfg["trip"]["origin"]
                    if origin not in orig:
                        continue
                    # цена в базе — на одну семью (2+1); для другого состава пересчёт по местам (оценка)
                    price = round(f["price"] * ratio, 2)
                    cost = price + orig[origin] + transfer_cost(km, cfg)
                    if best_air is None or cost < best_air["air_and_car"]:
                        best_air = {**f, "price": price, "ratio": ratio, "per_family": f["price"], "origin": origin, "ground": orig[origin], "airport": code, "km": km,
                                    "hours": round(km / 70, 1), "transfer": transfer_cost(km, cfg),
                                    "air_and_car": round(cost, 2)}

            lodging_price, lg, lodging_kind = lodging_choice(lodging.get((r["id"], str(wk))), cfg, families)

            missing = []
            season = r.get("season") or {}
            if season_closed(r, first_ski, cfg):
                missing.append(f"resort closed (season {season['from']:%d.%m}–{season['to']:%d.%m})")
            if best_air is None:
                missing.append("flight")
            if lodging_price is None:
                missing.append("lodging")
            total = None
            if not missing:
                total = round(best_air["air_and_car"] + lodging_price + passes.total + bags, 2)
            # Без перелёта: жильё + пассы + машина от ближайшего аэропорта — чтобы сравнивать хоть что-то.
            ground = None
            if lodging_price is not None and not season_closed(r, first_ski, cfg):
                km = min(r["airports"].values())
                ground = round(lodging_price + passes.total + transfer_cost(km, cfg), 2)

            options.append({
                "resort": r, "week": wk, "check_out": wk + dt.timedelta(days=nights),
                "passes": passes, "air": best_air, "lodging": lg, "lodging_price": lodging_price,
                "bags": bags, "total": total, "ground": ground, "missing": missing, "snow": snow.get(r.get("base_of", r["id"])),
                "few_lodging": bool(lg) and lg["n"] < cfg["lodging"]["min_results"],
                "lodging_kind": lodging_kind, "families": families, "scenario": sc["key"],
            })
    return options


def season_closed(r: dict, first_ski: dt.date, cfg: dict) -> bool:
    s = r.get("season")
    last = first_ski + dt.timedelta(days=cfg["trip"]["ski_days"] - 1)
    return bool(s) and (first_ski < s["from"] or last > s["to"])


def has_flights(options: list[dict]) -> bool:
    return any(o["total"] is not None for o in options)


def score(o: dict, full: bool):
    return o["total"] if full else o["ground"]


def ranked(options: list[dict]) -> list[dict]:
    """По полной сумме; если перелётов нет совсем — по сумме без перелёта."""
    full = has_flights(options)
    return sorted([o for o in options if score(o, full) is not None], key=lambda o: score(o, full))
