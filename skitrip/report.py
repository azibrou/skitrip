"""Статический HTML-отчёт: тепловая карта «курорт × неделя», топ вариантов, справка по курортам."""
from __future__ import annotations

import datetime as dt
import html

from .passes import age_on
from .plan import transfer_cost, has_flights, ranked, score

STATUS = {
    "verified_2026_27": ("цены 26/27", "ok"),
    "from_2025_26": ("цены 25/26", "warn"),
    "estimate": ("оценка", "warn"),
}
MONTHS = ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def e(x) -> str:
    return html.escape(str(x))


def eur(x) -> str:
    return "—" if x is None else f"{x:,.0f} €".replace(",", " ")


def dshort(d: dt.date) -> str:
    return f"{d.day} {MONTHS[d.month]}"


def heat_color(v, lo, hi) -> str:
    if v is None:
        return "var(--empty)"
    t = 0 if hi == lo else (v - lo) / (hi - lo)
    # от зелёного (дёшево) к красному (дорого) в OKLCH — читается в обеих темах
    hue = 145 - 120 * t
    return f"oklch(var(--heat-l) 0.13 {hue:.0f})"


def air_rows(a, r, cfg) -> str:
    if a:
        return (f'<dt>Перелёт TLL⇄{e(a["airport"])}</dt><dd><a href="{e(a["url"])}">{eur(a["price"])}</a> '
                f'<span class="mut">{e(a.get("airlines") or "")}{", пересадок: " + str(a["stops"]) if a.get("stops") else ""}</span></dd>'
                + (f'<dt>Машина + топливо</dt><dd>{eur(a["transfer"])} <span class="mut">{a["km"]} км в одну сторону</span></dd>' if a["transfer"]
                 else f'<dt>Дорога</dt><dd class="mut">{a["km"]} км от аэропорта, ~{a["hours"]} ч — не в сумме</dd>'))
    code, km = min(r["airports"].items(), key=lambda x: x[1])
    return (f'<dt>Перелёт</dt><dd class="mut">нет данных — смотрите вручную до {e(", ".join(r["airports"]))}</dd>'
            + (f'<dt>Машина + топливо</dt><dd>{eur(transfer_cost(km, cfg))} <span class="mut">от {e(code)}, {km} км</span></dd>' if transfer_cost(km, cfg)
            else f'<dt>Дорога</dt><dd class="mut">от {e(code)}, {km} км — не в сумме</dd>'))


def render(cfg: dict, resorts: list[dict], weeks: list[dt.date], options: list[dict], demo: bool = False) -> str:
    party = cfg["party"]
    kids = party.get("children", [])
    by = {(o["resort"]["id"], o["week"]): o for o in options}
    full = has_flights(options)
    totals = [score(o, full) for o in options if score(o, full) is not None]
    lo, hi = (min(totals), max(totals)) if totals else (0, 0)
    top = ranked(options)[:15]

    head = "".join(f"<th>{dshort(w)}</th>" for w in weeks)
    rows = []
    for r in resorts:
        cells = []
        for w in weeks:
            o = by.get((r["id"], w))
            v = score(o, full) if o else None
            tip = eur(v) if v is not None else ("нет данных: " + ", ".join(o["missing"]) if o else "—")
            label = "" if v is None else f"{v/1000:.1f}"
            cells.append(f'<td style="background:{heat_color(v, lo, hi)}" title="{e(r["name"])}, {dshort(w)}: {e(tip)}">{label}</td>')
        rows.append(f'<tr><th class="rn">{e(r["name"])} <span class="cc">{r["country"]}</span></th>{"".join(cells)}</tr>')

    cards = []
    for i, o in enumerate(top, 1):
        r, a, lg, p = o["resort"], o["air"], o["lodging"], o["passes"]
        lodg_links = "".join(
            f'<li><a href="{e(x["url"])}">{e(x["title"][:60] or "вариант")}</a> · {eur(x["total"])}'
            f'{" · ★" + str(x["rating"]) if x["rating"] else ""}</li>' for x in (lg["top"][:3] if lg else []))
        warn = []
        if o["few_lodging"]:
            warn.append(f"мало жилья в выдаче ({lg['n']})")
        if p.status != "verified_2026_27":
            warn.append("ски-пасс: " + STATUS.get(p.status, (p.status,))[0])
        cards.append(f"""
<article class="card">
  <header><span class="rank">{i}</span><div><h3>{e(r['name'])}</h3>
  <p class="sub">{dshort(o['week'])} – {dshort(o['check_out'])} · {f"вылет {e(a['airport'])}, {a['hours']} ч до курорта" if a else "без перелёта"}</p></div>
  <div class="tot">{eur(score(o, full))}</div></header>
  <dl>
    {air_rows(a, r, cfg)}
    <dt>Жильё, {cfg['trip']['nights']} ночей</dt><dd><a href="{e(lg['search_url'])}">{eur(o['lodging_price'])}</a> <span class="mut">{cfg['lodging']['stat']} из {lg['n']}, мин. {eur(lg['min'])}</span></dd>
    <dt>Ски-пассы, {p.period}</dt><dd>{eur(p.total)} <span class="mut">{e('; '.join(p.lines))}</span></dd>
    {f"<dt>Ски-багаж</dt><dd>{eur(o['bags'])}</dd>" if o['bags'] else ''}
  </dl>
  {f'<ul class="lodg">{lodg_links}</ul>' if lodg_links else ''}
  {f'<p class="warn">{e(" · ".join(warn))}</p>' if warn else ''}
</article>""")

    ref = []
    for r in resorts:
        lp = r["lift_pass"]
        st, cls = STATUS.get(lp.get("status"), (lp.get("status", ""), "warn"))
        o = next((x for x in options if x["resort"]["id"] == r["id"]), None)
        sn = o["snow"] if o else None
        snow = f"{sn['depth_cm']} см, +{sn['fresh_7d_cm']} за 7 дн, прогноз +{sn['forecast_7d_cm']}" if sn and sn.get("depth_cm") is not None else "—"
        kid_rule = "; ".join(t.get("note", "") for t in lp["child_tiers"] if t.get("note"))
        p = o["passes"] if o else None
        ref.append(f"""<tr><td>{e(r['name'])}<br><span class="mut">{r['top_m']} м · {e(r['glacier'])}</span></td>
<td>{e(lp['pass_name'])}<br><span class="mut">{eur(lp['default']['adult'])} / {eur(lp['default']['child'])}</span></td>
<td>{eur(p.total) if p else '—'}<br><span class="mut">{e(kid_rule)}</span></td>
<td><span class="pill {cls}">{st}</span> <a href="{e(lp['source'])}">источник</a></td>
<td>{e(snow)}</td>
<td class="mut">{e(', '.join(f'{k} {v} км' for k, v in r['airports'].items()))}</td></tr>""")

    # возраст, а не дата рождения: отчёт может быть опубликован
    kid_txt = ", ".join(f"ребёнок {age_on(c['birth_date'], weeks[0])} лет" for c in kids) if weeks else ""
    filled = sum(1 for o in options if score(o, full) is not None)
    nofly = "" if full or not totals else '<p class="demo">Перелётов в базе нет — суммы БЕЗ перелёта: жильё + ски-пассы + машина от ближайшего аэропорта.</p>'
    banner = nofly + '<p class="demo">ДЕМО: перелёты и жильё — синтетические цифры, чтобы показать вид отчёта. Ски-пассы — реальные данные из resorts.yaml.</p>' if demo else ""

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ski Trip Cost</title>
<style>
:root{{--bg:#f7f6f2;--fg:#1d1d1b;--mut:#6b6a66;--card:#fff;--line:#e3e1da;--empty:#ecebe6;--heat-l:0.86;--ok:#2f7d4a;--warn:#a35a00;--acc:#1f5fbf}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#141413;--fg:#ecebe6;--mut:#9a9893;--card:#1e1e1c;--line:#33322f;--empty:#262624;--heat-l:0.42;--ok:#6cc48a;--warn:#e0a050;--acc:#7aa7ff}}}}
:root[data-theme=dark]{{--bg:#141413;--fg:#ecebe6;--mut:#9a9893;--card:#1e1e1c;--line:#33322f;--empty:#262624;--heat-l:0.42;--ok:#6cc48a;--warn:#e0a050;--acc:#7aa7ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:18px;margin:36px 0 12px}}
a{{color:var(--acc)}}.mut,.sub{{color:var(--mut);font-size:13px}}.demo{{background:var(--warn);color:#fff;padding:8px 12px;border-radius:8px}}
.scroll{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}}
table.heat{{border-collapse:collapse;font-size:12px;width:100%}}.heat th,.heat td{{padding:6px 4px;text-align:center;border-bottom:1px solid var(--line);white-space:nowrap}}
.heat td{{font-variant-numeric:tabular-nums;min-width:40px}}.heat th.rn{{text-align:left;position:sticky;left:0;background:var(--card);padding-left:10px}}
.cc{{color:var(--mut);font-weight:400;font-size:11px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}
.card header{{display:flex;gap:10px;align-items:flex-start}}.card h3{{margin:0;font-size:16px}}.card header>div{{flex:1}}
.rank{{font-weight:700;color:var(--mut);min-width:20px}}.tot{{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:12px 0 0;font-size:13px}}dt{{color:var(--mut)}}dd{{margin:0}}
.lodg{{margin:10px 0 0;padding-left:18px;font-size:13px}}.warn{{color:var(--warn);font-size:13px;margin:10px 0 0}}
table.ref{{border-collapse:collapse;width:100%;font-size:13px;background:var(--card)}}.ref td,.ref th{{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}}
.pill{{font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid currentColor}}.pill.ok{{color:var(--ok)}}.pill.warn{{color:var(--warn)}}
</style></head><body><main>
<h1>Горнолыжная поездка: полная стоимость</h1>
<p class="sub">{party['adults']} взрослых + {kid_txt} · из {cfg['trip']['origin']} · {cfg['trip']['nights']} ночей, ски-пасс {cfg['trip']['ski_days']} дней · заполнено {filled} из {len(options)} вариантов · собрано {dt.datetime.now():%d.%m.%Y %H:%M}</p>
{banner}
<h2>Курорт × неделя заезда, тыс. €</h2>
<div class="scroll"><table class="heat"><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="sub">Сумма = перелёт на всех{' + аренда машины и топливо' if cfg['transfer']['car_rent_week'] or cfg['transfer']['per_km'] else ' (машина и дорога не считаются)'} из лучшего аэропорта + жильё ({cfg['lodging']['stat']} по Airbnb) + ски-пассы. Серые клетки — нет цены перелёта или жилья.</p>
<h2>Топ {len(top)} вариантов</h2>
<div class="cards">{''.join(cards) or '<p class="mut">Пока нет ни одного полного варианта — запустите сбор.</p>'}</div>
<h2>Курорты и ски-пассы</h2>
<div class="scroll"><table class="ref"><thead><tr><th>Курорт</th><th>Пасс, взр/дет</th><th>На вашу группу</th><th>Данные</th><th>Снег на верху</th><th>Аэропорты</th></tr></thead><tbody>{''.join(ref)}</tbody></table></div>
<p class="sub">Цены перелётов и жилья меняются; ссылки ведут на живой поиск. Ски-пасс «на вашу группу» посчитан для первой недели сезона.</p>
</main></body></html>"""
