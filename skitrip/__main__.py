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
        resorts = [r for r in resorts if r["id"] in args.resorts or r.get("base_of") in args.resorts]
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


def flights_done(st, party) -> set:
    """(город, аэропорт, дата, состав, источник) — что уже собрано сегодня."""
    # поиски до dead_since шли по странице и часто ложно давали «нет рейсов» — их не считаем сделанными
    # «сделано» = найдено за последние 3 дня: прерванный скан можно продолжить и на следующий день
    recent = (dt.datetime.now() - dt.timedelta(days=3)).isoformat(timespec="seconds")
    today = max(recent, str(load_config()["flights"].get("dead_since", "")))
    return {(x["origin"], x["dest"], x["out_date"], x.get("pax") or plan.gkey(party), x.get("source") or "google")
            for rows in st.latest_flights().values() for x in rows if x["scanned_at"] >= today}


def skip_dead_routes(st, jobs, weeks, party, cfg, flights) -> list:
    """Направления, где ни разу не нашлось рейса, не сканируем целиком.

    Раз в flights.recheck_days дней по такому направлению делается один пробный поиск
    (середина сезона); если рейс появился — направление снова сканируется полностью.
    """
    fc = cfg["flights"]
    min_rows, recheck = fc.get("dead_min_searches", 10), fc.get("recheck_days", 7)
    stats = st.route_stats(str(fc.get("dead_since", "")))
    probe_week = weeks[len(weeks) // 2]
    dead = set()
    for o, a in sorted({(j[1], j[2]) for j in jobs}):
        n, found, last = stats.get((o, a), (0, 0, None))
        if n < min_rows or found:
            continue
        age = (dt.datetime.now() - dt.datetime.fromisoformat(last)).days if last else 999
        if age >= recheck:  # пора проверить, не появились ли рейсы
            ret = probe_week + dt.timedelta(days=cfg["trip"]["nights"])
            try:
                q = flights.fetch_best(o, a, probe_week, ret, party, cfg)
            except Exception as ex:
                print(f"проверка {o}⇄{a}: ошибка {ex}", file=sys.stderr)
                q = None
            st.add_flight(o, a, probe_week, ret, q, pax=plan.gkey(party))
            _sleep(fc["delay_s"])
            if q:
                print(f"{o}⇄{a}: появились рейсы ({q['price']:.0f} €) — сканирую полностью")
                continue
        dead.add((o, a))
    if dead:
        print(f"Без рейсов, пропускаю (проверка раз в {recheck} дн.): "
              + ", ".join(f"{o}⇄{a}" for o, a in sorted(dead)))
    return [j for j in jobs if (j[1], j[2]) not in dead]


def cmd_run(args, cfg):
    resorts, weeks = select(args, cfg)
    st = Store(DB)
    party, nights = cfg["party"], cfg["trip"]["nights"]
    # составы групп из сценариев: перелёты и Airbnb ищутся отдельно для каждого
    groups = {plan.gkey(s["party"]): s for s in plan.scenarios(cfg)}
    if args.pax:
        groups = {k: v for k, v in groups.items() if k in args.pax}
    # перелёты — только на одну семью/группу: несколько семей бронируют каждая свои 2+1
    # (Google на 5+ пассажиров в одном заказе часто не находит ничего)
    fly = {k: s["party"] for k, s in groups.items() if s["units"] == 1}
    stay = {k: s["party"] for k, s in groups.items() if s["units"] == 1}  # жильё на одну группу

    if not args.skip_snow:
        from . import snow
        for r in resorts:
            if r.get("base_of"):  # снег тот же, что у ледника
                continue
            try:
                st.add_snow(r["id"], snow.fetch(r))
            except Exception as ex:  # сеть, лимиты
                print(f"снег {r['id']}: {ex}", file=sys.stderr)

    if not args.skip_flights:
        from . import flights
        airports = sorted({a for r in resorts for a in r["airports"]})
        origins = args.origins or list(plan.origins(cfg))
        jobs = [(g, o, a, w) for g in fly for o in origins for w in weeks for a in airports]
        if not args.all_airports:
            jobs = skip_dead_routes(st, jobs, weeks, party, cfg, flights)
        if args.skip_done:  # уже собранное сегодня не повторяем
            fd = flights_done(st, party)
            jobs = [j for j in jobs if (j[1], j[2], str(j[3]), j[0], "google") not in fd]
        if args.limit:
            jobs = jobs[: args.limit]
        errors, prev = 0, st.latest_flights()
        for i, (g, o, a, w) in enumerate(jobs, 1):
            ret = w + dt.timedelta(days=nights)
            try:
                q = flights.fetch_best(o, a, w, ret, fly[g], cfg)
                errors = 0
            except Exception as ex:
                errors += 1
                print(f"[{i}/{len(jobs)}] {o}⇄{a} {w}: ошибка {ex}", file=sys.stderr)
                if errors >= cfg["flights"]["max_consecutive_errors"]:
                    print("Подряд слишком много ошибок — похоже на блокировку Google. Останавливаю перелёты.", file=sys.stderr)
                    break
                continue
            st.add_flight(o, a, w, ret, q, pax=g)
            old = next((x for x in prev.get((a, str(w)), [])
                        if x["origin"] == o and (x.get("source") or "google") == "google"
                        and (x.get("pax") or plan.gkey(party)) == g), None)
            msg = f"{q['price']:.0f} €" if q else "нет рейсов"
            if q and old and old.get("price") and q["price"] <= old["price"] * (1 - cfg["alerts"]["drop_pct"] / 100):
                msg += f"  ↓ было {old['price']:.0f} €"
            print(f"[{i}/{len(jobs)}] {g} {o}⇄{a} {w}: {msg}")
            _sleep(cfg["flights"]["delay_s"])

    if not args.skip_self and cfg.get("self_transfer", {}).get("enabled"):
        from . import selftransfer
        airports = {a for r in resorts for a in r["airports"]}
        origins = args.origins or list(plan.origins(cfg))
        jobs = [(g, o, w) for g in fly for o in origins for w in weeks]
        if args.skip_done:
            done = {(x[0], x[2], x[3]) for x in flights_done(st, party) if x[4] == "self"}
            jobs = [j for j in jobs if (j[1], str(j[2]), j[0]) not in done]
        for i, (g, o, w) in enumerate(jobs, 1):
            ret = w + dt.timedelta(days=nights)
            try:
                found = selftransfer.search_week(o, w, ret, airports, fly[g], cfg)
            except Exception as ex:
                print(f"[{i}/{len(jobs)}] {g} пересадки {o} {w}: ошибка {ex}", file=sys.stderr)
                continue
            for a in sorted(airports):
                st.add_flight(o, a, w, ret, found.get(a), source="self", pax=g)
            best = ", ".join(f"{a} {q['price']:.0f} €" for a, q in sorted(found.items(), key=lambda x: x[1]["price"])[:4])
            print(f"[{i}/{len(jobs)}] {g} пересадки {o} {w}: {len(found)} аэропортов. {best}")

    hubs = cfg.get("self_transfer", {}).get("hubs") or []
    if not args.skip_hubs and hubs:
        from . import flights, selftransfer
        airports = sorted({a for r in resorts for a in r["airports"]})
        origins = args.origins or list(plan.origins(cfg))
        probe = weeks[len(weeks) // 2]
        for hub in hubs:
            # куда из хаба вообще есть прямые рейсы (одна проверочная дата)
            served = []
            for a in airports:
                try:
                    if flights.oneway_options(hub, a, probe, party, cfg) or a in selftransfer.ryanair_routes(hub):
                        served.append(a)
                except Exception as ex:
                    print(f"{hub}→{a}: ошибка {ex}", file=sys.stderr)
                _sleep(cfg["flights"]["delay_s"])
            print(f"Из {hub} прямые рейсы в: {', '.join(served) or '—'}")
            jobs = [(g, o, w) for g in fly for o in origins for w in weeks if o != hub]
            for i, (g, o, w) in enumerate(jobs, 1):
                ret = w + dt.timedelta(days=nights)
                try:
                    found = selftransfer.search_hub_week(o, hub, w, ret, served, fly[g], cfg,
                                                         delay=cfg["flights"]["delay_s"])
                except Exception as ex:
                    print(f"[{i}/{len(jobs)}] {g} через {hub} {o} {w}: ошибка {ex}", file=sys.stderr)
                    continue
                for a in airports:
                    st.add_flight(o, a, w, ret, found.get(a), source=f"hub-{hub}", pax=g)
                best = ", ".join(f"{a} {q['price']:.0f} €" for a, q in sorted(found.items(), key=lambda x: x[1]["price"])[:4])
                print(f"[{i}/{len(jobs)}] {g} через {hub} {o} {w}: {best or 'нет связок'}")

    if not args.skip_lodging:
        from . import lodging
        # тип из config → [(как искать, тип в базе, состав гостей)] — по каждому составу из сценариев
        kinds: dict = {"entire": [], "hotel": [], "entire-big": [],
                       "ghotel": [(lambda r, w: lodging.google_hotels(r, w, nights, cfg), "ghotel", "2+0")]}
        for g, p in stay.items():
            kinds["entire"].append((lambda r, w, p=p: lodging.fetch(r, w, nights, p, cfg), "entire", g))
            kinds["hotel"].append((lambda r, w, p=p: lodging.fetch(r, w, nights, p, cfg, kind="hotel"), "hotel", g))
        for g, s in groups.items():
            if s["units"] > 1:
                kinds["entire-big"].append((lambda r, w, p=s["party"]: lodging.fetch(r, w, nights, p, cfg, min_bedrooms=2),
                                            "entire", g))
        wanted = args.lodging_kinds or cfg["lodging"].get("kinds") or ["entire"]
        done = set()
        if args.skip_done:  # уже собранное сегодня не повторяем
            today = dt.date.today().isoformat()
            done = {(x["resort"], x["check_in"], x.get("kind") or "entire", x.get("guests") or plan.gkey(party))
                    for rows in st.latest_lodging().values() for x in rows if x["scanned_at"] >= today}
        jobs = [(job, r, w) for k in wanted for job in kinds[k] for r in resorts for w in weeks
                if (r["id"], str(w), job[1], job[2]) not in done]
        if args.limit:
            jobs = jobs[: args.limit]
        for i, ((fetch, k, guests), r, w) in enumerate(jobs, 1):
            try:
                s = fetch(r, w)
            except Exception as ex:
                print(f"[{i}/{len(jobs)}] {k} {r['id']} {w}: ошибка {ex}", file=sys.stderr)
                continue
            st.add_lodging(r["id"], w, nights, s, kind=k, guests=guests)
            print(f"[{i}/{len(jobs)}] {k} {guests} {r['name']} {w}: {s['n']} вариантов, p25 {s['p25']}, медиана {s['median']}")
            _sleep(cfg["lodging"]["delay_s"] if k != "ghotel" else cfg["flights"]["delay_s"])

    cmd_report(args, cfg)


def cmd_report(args, cfg, demo_data=None):
    resorts, weeks = select(args, cfg)
    if demo_data:
        flights, lodging, snow = demo_data
    else:
        st = Store(DB)
        flights, lodging, snow = st.latest_flights(), st.latest_lodging(), st.latest_snow()
    # переключатели в отчёте: состав группы × город вылета;
    # город попадает в переключатель, только когда по нему уже есть цены
    have = {q.get("origin") for qs in flights.values() for q in ([qs] if isinstance(qs, dict) else qs) if q.get("price")}
    flown = [o for o in plan.origins(cfg) if o in have] or list(plan.origins(cfg))
    scen = {(s["key"], o): plan.build(cfg, resorts, weeks, flights, lodging, snow, scenario=s,
                                      only_origin=None if o == "any" else o)
            for s in plan.scenarios(cfg) for o in flown}
    opts = next(iter(scen.values()))
    OUT.parent.mkdir(exist_ok=True)
    out = OUT.with_name("report-demo.html") if demo_data else OUT
    out.write_text(report.render(cfg, resorts, weeks, scen, demo=bool(demo_data)), encoding="utf-8")
    best = plan.ranked(opts)[:5]
    print(f"\nОтчёт: {out}")
    for o in best:
        via = f"{o['air']['origin']}⇄{o['air']['airport']}" if o["air"] else "без перелёта"
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
        lvl = {"FR": 1.25, "IT": 0.95, "AT": 1.0, "CH": 1.5}.get(r["country"], 1.0)
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
            p.add_argument("--skip-self", action="store_true", help="без пересадок Ryanair через любые хабы")
            p.add_argument("--skip-hubs", action="store_true", help="без пересадок через хабы из self_transfer.hubs")
            p.add_argument("--origins", nargs="*", help="города вылета, по умолчанию все из config.yaml")
            p.add_argument("--lodging-kinds", nargs="*", choices=["entire", "entire-big", "hotel", "ghotel"],
                           help="типы жилья, по умолчанию lodging.kinds из config.yaml")
            p.add_argument("--all-airports", action="store_true", help="сканировать и направления без рейсов")
            p.add_argument("--pax", nargs="*", help="составы групп, напр. 2+0 1+0; по умолчанию все из scenarios")
            p.add_argument("--skip-done", action="store_true", help="не повторять то, что уже собрано сегодня")
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
