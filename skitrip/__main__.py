"""CLI.

  python -m skitrip passes                 # ски-пассы на вашу группу по всем курортам, без сети
  python -m skitrip run                    # снег + перелёты + жильё + отчёт
  python -m skitrip run --resorts tignes cervinia --weeks 4
  python -m skitrip report                 # пересобрать отчёт из базы
  python -m skitrip demo                   # отчёт на синтетических ценах, чтобы посмотреть вид
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
import time
import webbrowser

from . import plan, report
from .config import ROOT, checkin_dates, load_config, load_resorts
from .passes import party_pass_cost, pass_party
from .store import Store

DB = ROOT / "data" / "prices.sqlite"
OUT = ROOT / "data" / "report.html"


def _sleep(rng):
    time.sleep(random.uniform(*rng))


def select(args, cfg):
    resorts = [r for r in load_resorts() if r["top_m"] >= cfg["trip"].get("min_top_m", 0)]
    if args.resorts:
        resorts = [r for r in resorts if r["id"] in args.resorts]
    weeks = checkin_dates(cfg)
    if getattr(args, "start", None):
        weeks = [w for w in weeks if w >= dt.date.fromisoformat(args.start)]
    if getattr(args, "weeks", None):
        weeks = weeks[: args.weeks]
    return resorts, weeks


def cmd_passes(args, cfg):
    resorts, weeks = select(args, cfg)
    day = dt.date.fromisoformat(args.date) if args.date else weeks[0] + dt.timedelta(days=1)
    print(f"Ски-пассы на группу, первый ски-день {day}:\n")
    rows = []
    for r in resorts:
        q = party_pass_cost(r, pass_party(cfg), day)
        rows.append((q.total, r, q))
    for total, r, q in sorted(rows, key=lambda x: x[0]):
        print(f"{total:8.0f} €  {r['name']:<26} [{q.status}] {q.period}")
        for line in q.lines:
            print(f"{'':12}{line}")


def cmd_run(args, cfg):
    resorts, weeks = select(args, cfg)
    st = Store(DB)
    party, nights = cfg["party"], cfg["trip"]["nights"]

    if not args.skip_snow:
        from . import snow
        for r in resorts:
            try:
                st.add_snow(r["id"], snow.fetch(r))
            except Exception as ex:  # сеть, лимиты
                print(f"снег {r['id']}: {ex}", file=sys.stderr)

    if not args.skip_flights:
        from . import flights
        airports = sorted({a for r in resorts for a in r["airports"]})
        jobs = [(a, w) for w in weeks for a in airports]
        if args.limit:
            jobs = jobs[: args.limit]
        errors, prev = 0, st.latest_flights()
        for i, (a, w) in enumerate(jobs, 1):
            ret = w + dt.timedelta(days=nights)
            try:
                q = flights.fetch_roundtrip(cfg["trip"]["origin"], a, w, ret, party, cfg)
                errors = 0
            except Exception as ex:
                errors += 1
                print(f"[{i}/{len(jobs)}] {a} {w}: ошибка {ex}", file=sys.stderr)
                if errors >= cfg["flights"]["max_consecutive_errors"]:
                    print("Подряд слишком много ошибок — похоже на блокировку Google. Останавливаю перелёты.", file=sys.stderr)
                    break
                continue
            st.add_flight(cfg["trip"]["origin"], a, w, ret, q)
            old = prev.get((a, str(w)))
            msg = f"{q['price']:.0f} €" if q else "нет рейсов"
            if q and old and old.get("price") and q["price"] <= old["price"] * (1 - cfg["alerts"]["drop_pct"] / 100):
                msg += f"  ↓ было {old['price']:.0f} €"
            print(f"[{i}/{len(jobs)}] TLL⇄{a} {w}: {msg}")
            _sleep(cfg["flights"]["delay_s"])

    if not args.skip_lodging:
        from . import lodging
        jobs = [(r, w) for r in resorts for w in weeks]
        if args.limit:
            jobs = jobs[: args.limit]
        for i, (r, w) in enumerate(jobs, 1):
            try:
                s = lodging.fetch(r, w, nights, party, cfg)
            except Exception as ex:
                print(f"[{i}/{len(jobs)}] жильё {r['id']} {w}: ошибка {ex}", file=sys.stderr)
                continue
            st.add_lodging(r["id"], w, nights, s)
            print(f"[{i}/{len(jobs)}] {r['name']} {w}: {s['n']} вариантов, p25 {s['p25']}, медиана {s['median']}")
            _sleep(cfg["lodging"]["delay_s"])

    cmd_report(args, cfg)


def cmd_report(args, cfg, demo_data=None):
    resorts, weeks = select(args, cfg)
    if demo_data:
        flights, lodging, snow = demo_data
    else:
        st = Store(DB)
        flights, lodging, snow = st.latest_flights(), st.latest_lodging(), st.latest_snow()
    opts = plan.build(cfg, resorts, weeks, flights, lodging, snow)
    OUT.parent.mkdir(exist_ok=True)
    out = OUT.with_name("report-demo.html") if demo_data else OUT
    out.write_text(report.render(cfg, resorts, weeks, opts, demo=bool(demo_data)), encoding="utf-8")
    best = plan.ranked(opts)[:5]
    print(f"\nОтчёт: {out}")
    for o in best:
        via = f"через {o['air']['airport']}" if o["air"] else "без перелёта"
        print(f"  {plan.score(o, plan.has_flights(opts)):8.0f} €  {o['resort']['name']:<26} {o['week']}  {via}")
    if args.open:
        webbrowser.open(out.as_uri())


def demo_data(cfg, resorts, weeks):
    """Синтетика: только чтобы показать вид отчёта."""
    rnd = random.Random(7)
    party, nights = cfg["party"], cfg["trip"]["nights"]
    base_air = {"MUC": 480, "INN": 700, "MXP": 430, "BGY": 360, "VRN": 520, "TRN": 610, "LIN": 640,
                "GVA": 540, "LYS": 590, "SZG": 560, "CMF": 900, "GNB": 950}
    peak = lambda w: 1.55 if (w.month == 12 and w.day >= 19) or (w.month == 1 and w.day <= 3) else (1.3 if w.month == 2 else 1.0)
    flights, lodging, snow = {}, {}, {}
    for w in weeks:
        for a, p in base_air.items():
            if rnd.random() < 0.12:
                continue
            price = round(p * peak(w) * rnd.uniform(0.85, 1.2))
            flights[(a, str(w))] = {"price": price, "airlines": "demo", "stops": rnd.choice([0, 1]),
                                    "url": "https://www.google.com/travel/flights"}
    for r in resorts:
        lvl = {"FR": 1.25, "IT": 0.95, "AT": 1.0}[r["country"]]
        for w in weeks:
            p25 = round(1100 * lvl * peak(w) * rnd.uniform(0.85, 1.25))
            lodging[(r["id"], str(w))] = {
                "n": rnd.randint(3, 60), "min": round(p25 * 0.8), "p25": p25, "median": round(p25 * 1.3),
                "top": [{"title": "Demo apartment", "total": round(p25 * 0.85), "rating": 4.8, "url": "https://www.airbnb.com"}],
                "search_url": "https://www.airbnb.com"}
        snow[r["id"]] = {"depth_cm": rnd.randint(40, 180), "fresh_7d_cm": rnd.randint(0, 40), "forecast_7d_cm": rnd.randint(0, 50)}
    return flights, lodging, snow


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skitrip")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("passes", "run", "report", "demo"):
        p = sub.add_parser(name)
        p.add_argument("--resorts", nargs="*", help="id курортов из resorts.yaml")
        p.add_argument("--weeks", type=int, help="сколько недель заезда взять")
        p.add_argument("--start", help="первая дата заезда, YYYY-MM-DD")
        p.add_argument("--open", action="store_true", help="открыть отчёт в браузере")
        if name == "passes":
            p.add_argument("--date", help="первый ски-день, YYYY-MM-DD")
        if name == "run":
            p.add_argument("--limit", type=int, help="ограничить число запросов (пробный прогон)")
            p.add_argument("--skip-flights", action="store_true")
            p.add_argument("--skip-lodging", action="store_true")
            p.add_argument("--skip-snow", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.cmd == "passes":
        cmd_passes(args, cfg)
    elif args.cmd == "run":
        cmd_run(args, cfg)
    elif args.cmd == "report":
        cmd_report(args, cfg)
    elif args.cmd == "demo":
        resorts, weeks = select(args, cfg)
        cmd_report(args, cfg, demo_data=demo_data(cfg, resorts, weeks))


if __name__ == "__main__":
    main()
