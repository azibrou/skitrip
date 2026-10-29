import datetime as dt

from skitrip import lodging, plan, snow
from skitrip.config import checkin_dates, load_config, load_resorts
from skitrip.passes import age_on, party_pass_cost

D = dt.date
R = {r["id"]: r for r in load_resorts()}


def party(birth):
    return {"adults": 2, "children": [{"birth_date": birth}]}


def test_age():
    assert age_on(D(2020, 6, 1), D(2027, 5, 31)) == 6
    assert age_on(D(2020, 6, 1), D(2027, 6, 1)) == 7


def test_zillertal_birth_year_boundary():
    day = D(2027, 1, 10)
    assert party_pass_cost(R["hintertux"], party(D(2020, 12, 31)), day).total == 2 * 399 + 179.5
    assert party_pass_cost(R["hintertux"], party(D(2021, 1, 2)), day).total == 2 * 399


def test_cervinia_cutoff_date():
    day = D(2027, 1, 10)
    assert party_pass_cost(R["cervinia"], party(D(2020, 11, 24)), day).total == 2 * 338 + 236.5
    assert party_pass_cost(R["cervinia"], party(D(2020, 11, 25)), day).total == 2 * 338


def test_tignes_free_under_8():
    day = D(2027, 2, 7)
    assert party_pass_cost(R["tignes"], party(D(2020, 1, 1)), day).total == 2 * 468       # 7 лет
    assert party_pass_cost(R["tignes"], party(D(2019, 1, 1)), day).total == 2 * 468 + 378  # 8 лет


def test_soelden_periods():
    p = party(D(2020, 6, 1))
    assert party_pass_cost(R["soelden"], p, D(2026, 12, 27)).period == "Topsaison"
    assert party_pass_cost(R["soelden"], p, D(2027, 1, 10)).period == "Hauptsaison"
    assert party_pass_cost(R["soelden"], p, D(2027, 2, 7)).total == 2 * 478.5 + 12


def test_val_thorens_family_flex():
    q = party_pass_cost(R["valthorens"], party(D(2020, 6, 1)), D(2027, 1, 10))
    assert q.total == 3 * 301
    # ребёнок до 5 лет бесплатный → Family Flex не включается
    q2 = party_pass_cost(R["valthorens"], party(D(2023, 1, 1)), D(2027, 1, 10))
    assert q2.total == 2 * 367.5


def test_checkin_saturdays():
    weeks = checkin_dates(load_config())
    assert weeks[0] == D(2026, 12, 5) and all(w.weekday() == 5 for w in weeks)


def test_lodging_summary():
    mk = lambda pid, total, unit=0, rating=4.9: {"room_id": pid, "name": f"L{pid}", "rating": {"value": rating},
                                                  "price": {"total": {"amount": total}, "unit": {"amount": unit}}}
    s = lodging.summarize([mk(1, 1400), mk(2, 0, 150), mk(3, 900, rating=4.0), mk(4, 2000), mk(5, 0)], nights=7)
    assert s["n"] == 4 and s["min"] == 900 and s["median"] == 1225
    assert s["top"][0]["url"].endswith("/2")  # 150×7=1050, рейтинг 4.9 — самый дешёвый хороший


def test_lodging_unit_qualifier_total_not_multiplied():
    l = {"room_id": 1, "price": {"unit": {"qualifier": "total", "amount": 1201.0, "discount": 1033.0},
                                 "total": {"amount": 0}}}
    assert lodging._total(l, 7) == 1033.0
    l["price"]["break_down"] = [{"description": "Total", "amount": 1032.4}]
    assert lodging._total(l, 7) == 1032.4


def test_snow_parse():
    data = {"hourly": {"snow_depth": [0.5] * 168 + [0.7] * 168},
            "daily": {"snowfall_sum": [1, 2, 0, 0, 0, 3, 4, 10, 0, 0, 0, 0, 0, 5]}}
    assert snow.parse(data) == {"depth_cm": 70, "fresh_7d_cm": 10, "forecast_7d_cm": 15}


def test_plan_total_picks_cheapest_airport_with_car():
    cfg = load_config()
    wk = D(2027, 1, 9)
    r = R["cervinia"]
    flights = {("TRN", str(wk)): {"price": 600, "url": "x"}, ("BGY", str(wk)): {"price": 450, "url": "y"}}
    lodg = {("cervinia", str(wk)): {"n": 20, "min": 900, "p25": 1100, "median": 1400, "top": [], "search_url": "z"}}
    [o] = plan.build(cfg, [r], [wk], flights, lodg, {})
    trn = 600 + plan.transfer_cost(120, cfg)
    bgy = 450 + plan.transfer_cost(215, cfg)
    assert o["air"]["airport"] == ("TRN" if trn < bgy else "BGY")
    assert o["total"] == round(min(trn, bgy) + 1100 + o["passes"].total, 2)


def test_plan_marks_missing():
    cfg = load_config()
    wk = D(2027, 1, 9)
    [o] = plan.build(cfg, [R["tignes"]], [wk], {}, {}, {})
    assert o["total"] is None and o["missing"] == ["перелёт", "жильё"]


def test_pass_adults_only():
    cfg = load_config()
    cfg["trip"]["pass_children"] = False
    [o] = plan.build(cfg, [R["kaprun"]], [D(2027, 1, 9)], {}, {}, {})
    assert o["passes"].total == 2 * 440


def test_plan_adds_bus_cost_for_riga():
    cfg = load_config()
    cfg["trip"]["origins"] = {"TLL": 0, "RIX": 150}
    wk = D(2027, 1, 9)
    lodg = {("cervinia", str(wk)): {"n": 20, "min": 900, "p25": 1100, "median": 1400, "top": [], "search_url": "z"}}
    quotes = [{"origin": "TLL", "price": 600, "url": "a"}, {"origin": "RIX", "price": 400, "url": "b"}]
    [o] = plan.build(cfg, [R["cervinia"]], [wk], {("TRN", str(wk)): quotes}, lodg, {})
    assert o["air"]["origin"] == "RIX" and o["air"]["ground"] == 150   # 400 + 150 < 600
    quotes[1]["price"] = 500
    [o] = plan.build(cfg, [R["cervinia"]], [wk], {("TRN", str(wk)): quotes}, lodg, {})
    assert o["air"]["origin"] == "TLL"                                   # 500 + 150 > 600


def test_self_transfer_same_day_only(monkeypatch):
    import datetime as _dt
    from skitrip import selftransfer
    calls = []
    monkeypatch.setattr(selftransfer, "_fares", lambda *a, **k: calls.append(a) or [])
    T = _dt.datetime
    late = {"to": "AGP", "dep": T(2027, 2, 6, 21, 0), "arr": T(2027, 2, 7, 0, 40)}
    assert selftransfer._connect(late, None, "EUR", 3) == [] and not calls
    ok = {"to": "STN", "dep": T(2027, 2, 6, 8, 0), "arr": T(2027, 2, 6, 9, 0)}
    selftransfer._connect(ok, None, "EUR", 3)
    assert calls and calls[0][2] == "12:00"


def test_hub_pair_needs_time_to_change():
    import datetime as _dt
    from skitrip import selftransfer
    T = _dt.datetime
    leg1 = {"dep": T(2027, 2, 6, 9, 45), "arr": T(2027, 2, 6, 10, 25), "price": 69}
    early = {"dep": T(2027, 2, 6, 12, 0), "arr": T(2027, 2, 6, 14, 0), "price": 50}    # < 3 ч
    late = {"dep": T(2027, 2, 6, 17, 45), "arr": T(2027, 2, 6, 19, 55), "price": 215}
    p, a, b = selftransfer._best_pair([leg1], [early, late], 3)
    assert p == 284 and b is late


def test_bases_expand_with_same_pass():
    rs = {r["id"]: r for r in load_resorts()}
    zell = rs["kaprun@zell"]
    assert zell["base_of"] == "kaprun" and zell["lift_pass"] is rs["kaprun"]["lift_pass"]
    assert zell["lodging_bbox"] != rs["kaprun"]["lodging_bbox"] and zell["base_km"] == 10


def test_two_families_lodging_and_passes():
    cfg = load_config()
    wk = D(2027, 1, 9)
    rows = [{"kind": "entire", "guests": "2+1", "p25": 1000, "n": 20, "min": 900, "top": [], "search_url": ""},
            {"kind": "entire", "guests": "4+2", "p25": 1700, "n": 10, "min": 1500, "top": [], "search_url": ""},
            {"kind": "ghotel", "guests": "2+0", "p25": 950, "n": 15, "min": 700, "top": [], "search_url": ""}]
    fl = {("INN", str(wk)): [{"origin": "TLL", "price": 600, "url": ""}]}
    [one] = plan.build(cfg, [R["kaprun"]], [wk], fl, {("kaprun", str(wk)): rows}, {}, families=1)
    [two] = plan.build(cfg, [R["kaprun"]], [wk], fl, {("kaprun", str(wk)): rows}, {}, families=2)
    assert one["lodging_price"] == 950 and "Google" in one["lodging_kind"]
    assert two["lodging_price"] == 1700 and "на всех" in two["lodging_kind"]      # < 2×950, < 2×1000
    assert two["air"]["price"] == 1200 and two["passes"].total == 2 * one["passes"].total
