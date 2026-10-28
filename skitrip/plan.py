"""Сборка полной стоимости: перелёт + машина + жильё + ски-пассы, для каждого курорта и недели."""
from __future__ import annotations

import datetime as dt

from .passes import party_pass_cost, pass_party


def transfer_cost(km: float, cfg: dict) -> float:
    t = cfg["transfer"]
    return round(t["car_rent_week"] + 2 * km * t["per_km"], 2)


def build(cfg: dict, resorts: list[dict], weeks: list[dt.date], flights: dict, lodging: dict, snow: dict) -> list[dict]:
    party = cfg["party"]
    nights = cfg["trip"]["nights"]
    stat = cfg["lodging"]["stat"]
    n_people = party["adults"] + len(party.get("children", []))
    bags = cfg["costs"].get("ski_bag_per_person_rt", 0) * n_people
    options = []
    for r in resorts:
        for wk in weeks:
            first_ski = wk + dt.timedelta(days=1)
            passes = party_pass_cost(r, pass_party(cfg), first_ski)

            best_air = None
            for code, km in r["airports"].items():
                f = flights.get((code, str(wk)))
                if not f or f.get("price") is None:
                    continue
                cost = f["price"] + transfer_cost(km, cfg)
                if best_air is None or cost < best_air["air_and_car"]:
                    best_air = {**f, "airport": code, "km": km, "hours": round(km / 70, 1),
                                "transfer": transfer_cost(km, cfg), "air_and_car": round(cost, 2)}

            lg = lodging.get((r["id"], str(wk)))
            lodging_price = lg.get(stat) if lg else None

            missing = []
            if best_air is None:
                missing.append("перелёт")
            if lodging_price is None:
                missing.append("жильё")
            total = None
            if not missing:
                total = round(best_air["air_and_car"] + lodging_price + passes.total + bags, 2)
            # Без перелёта: жильё + пассы + машина от ближайшего аэропорта — чтобы сравнивать хоть что-то.
            ground = None
            if lodging_price is not None:
                km = min(r["airports"].values())
                ground = round(lodging_price + passes.total + transfer_cost(km, cfg), 2)

            options.append({
                "resort": r, "week": wk, "check_out": wk + dt.timedelta(days=nights),
                "passes": passes, "air": best_air, "lodging": lg, "lodging_price": lodging_price,
                "bags": bags, "total": total, "ground": ground, "missing": missing, "snow": snow.get(r["id"]),
                "few_lodging": bool(lg) and lg["n"] < cfg["lodging"]["min_results"],
            })
    return options


def has_flights(options: list[dict]) -> bool:
    return any(o["total"] is not None for o in options)


def score(o: dict, full: bool):
    return o["total"] if full else o["ground"]


def ranked(options: list[dict]) -> list[dict]:
    """По полной сумме; если перелётов нет совсем — по сумме без перелёта."""
    full = has_flights(options)
    return sorted([o for o in options if score(o, full) is not None], key=lambda o: score(o, full))
