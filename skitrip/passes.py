"""Стоимость ски-пассов на всю группу по данным resorts.yaml."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class PassQuote:
    total: float
    period: str
    lines: list[str] = field(default_factory=list)
    status: str = ""


def age_on(birth: dt.date, day: dt.date) -> int:
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def period_for(lp: dict, first_ski_day: dt.date) -> dict:
    for p in lp.get("periods") or []:
        if p["from"] <= first_ski_day <= p["to"]:
            return p
    return lp["default"]


def child_price(lp: dict, period: dict, birth: dt.date, first_ski_day: dt.date) -> tuple[float, str]:
    """Цена пасса для одного ребёнка и пояснение, какое правило сработало."""
    age = age_on(birth, first_ski_day)
    for tier in lp["child_tiers"]:
        if "born_from" in tier and birth < tier["born_from"]:
            continue
        if "max_age" in tier and age > tier["max_age"]:
            continue
        price = period["child"] if tier["price"] == "child" else float(tier["price"])
        return price, tier.get("note", "")
    return period["adult"], "adult rate"


def pass_party(cfg: dict) -> dict:
    """Кому покупаем ски-пассы: вся группа или только взрослые (trip.pass_children: false)."""
    party = cfg["party"]
    if cfg["trip"].get("pass_children", True):
        return party
    return {**party, "children": []}


def party_pass_cost(resort: dict, party: dict, first_ski_day: dt.date) -> PassQuote:
    lp = resort["lift_pass"]
    period = period_for(lp, first_ski_day)
    lines, total, paying_kids = [], 0.0, 0
    for ch in party.get("children", []):
        price, note = child_price(lp, period, ch["birth_date"], first_ski_day)
        age = age_on(ch["birth_date"], first_ski_day)
        lines.append(f"child {age}: €{price:.0f} ({note})" if note else f"child {age}: €{price:.0f}")
        total += price
        paying_kids += price > 0 and price >= period["child"] * 0.5
    adult = period["adult"]
    if lp.get("family_flex") and paying_kids >= 1 and party["adults"] <= 2:
        adult = period["child"]
        lines.append("Family Flex: adults at child rate")
    total += adult * party["adults"]
    lines.insert(0, f"{party['adults']} × adult €{adult:.0f}")
    return PassQuote(round(total, 2), period["name"], lines, lp.get("status", ""))
