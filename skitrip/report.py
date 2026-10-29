"""Static HTML report: resort × week heatmap, top options, resort reference."""
from __future__ import annotations

import datetime as dt
import html
import re

from .passes import age_on
from .plan import origins, scenarios, transfer_cost, has_flights, ranked, score

STATUS = {
    "verified_2026_27": "26/27 prices",
    "from_2025_26": "25/26 prices",
    "estimate": "estimate",
}
CITY = {"TLL": "Tallinn", "RIX": "Riga", "WAW": "Warsaw"}
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Strings saved in the database by older scans were in Russian.
_TR = [
    (r"Ryanair \(напрямую, без багажа\)", "Ryanair (direct, no bags)"),
    (r"Ryanair, 2 билета через (\S+) — самостоятельная пересадка", r"Ryanair, 2 tickets via \1, self-transfer"),
    (r" — 2 билета через (\S+), самостоятельная пересадка", r" — 2 tickets via \1, self-transfer"),
    (r" \(2 × в одну сторону\)", " (2 one-ways)"),
    (r"туда:", "out:"),
    (r"обратно:", "back:"),
]


def tr(s) -> str:
    s = str(s or "")
    for a, b in _TR:
        s = re.sub(a, b, s)
    return s


def e(x) -> str:
    return html.escape(str(x))


def eur(x) -> str:
    return "—" if x is None else f"€{x:,.0f}"


def dshort(d: dt.date) -> str:
    return f"{d.day} {MONTHS[d.month]}"


def heat_color(v, lo, hi) -> str:
    if v is None:
        return "var(--card)"
    t = 0 if hi == lo else (v - lo) / (hi - lo)
    # green (cheap) to red (expensive) in OKLCH — readable in both themes
    hue = 145 - 120 * t
    return f"oklch(var(--heat-l) 0.13 {hue:.0f})"


def air_rows(a, r, cfg) -> str:
    if a:
        orig = a.get("origin") or cfg["trip"]["origin"]
        detail = f'<br><i>{e(tr(a["detail"]))}</i>' if a.get("detail") else ""
        stops = f', {a["stops"]} stop{"s" if a["stops"] > 1 else ""}' if a.get("stops") else ""
        ground = (f'<dt>Getting to {e(orig)}</dt><dd>{eur(a["ground"])}</dd>' if a.get("ground") else "")
        drive = (f'<dt>Car and fuel</dt><dd>{eur(a["transfer"])} <i>{a["km"]} km each way</i></dd>' if a["transfer"]
                 else f'<dt>Drive</dt><dd>{a["km"]} km from the airport, ~{a["hours"]} h <i>not in the total</i></dd>')
        return (f'<dt>Flight {e(orig)}⇄{e(a["airport"])}</dt><dd><a href="{e(a["url"])}">{eur(a["price"])}</a> '
                f'<i>{e(tr(a.get("airlines")))}{stops}</i>{detail}</dd>' + ground + drive)
    code, km = min(r["airports"].items(), key=lambda x: x[1])
    return (f'<dt>Flight</dt><dd><i>no data — search {e(", ".join(r["airports"]))} by hand</i></dd>'
            + (f'<dt>Car and fuel</dt><dd>{eur(transfer_cost(km, cfg))} <i>from {e(code)}, {km} km</i></dd>' if transfer_cost(km, cfg)
               else f'<dt>Drive</dt><dd>from {e(code)}, {km} km <i>not in the total</i></dd>'))


def _section(cfg: dict, resorts: list[dict], weeks: list[dt.date], options: list[dict], sc: dict, demo: bool,
             froms: list[str] | None = None) -> str:
    party = sc["party"]
    kids = party.get("children", [])
    by = {(o["resort"]["id"], o["week"]): o for o in options}
    full = has_flights(options)
    totals = [score(o, full) for o in options if score(o, full) is not None]
    lo, hi = (min(totals), max(totals)) if totals else (0, 0)
    top = ranked(options)[:15]

    head = "".join(f"<th>{dshort(w)}</th>" for w in weeks)
    rows = []
    for ri, r in enumerate(resorts):
        cells = []
        for wi, w in enumerate(weeks):
            o = by.get((r["id"], w))
            v = score(o, full) if o else None
            tip = eur(v) if v is not None else ("no data: " + ", ".join(o["missing"]) if o else "—")
            label = "" if v is None else f"{v/1000:.1f}"
            cells.append(f'<td style="background:{heat_color(v, lo, hi)};--d:{(ri + wi) * 14}ms" '
                         f'title="{e(r["name"])}, {dshort(w)}: {e(tip)}">{label}</td>')
        short = r["name"].split(" · ")[0]
        base = f'<span class="via">from {e(r["base_name"])}</span>' if r.get("base_of") else ""
        rows.append(f'<tr><th class="rn" scope="row">{e(short)} ({r["country"]}){base}</th>{"".join(cells)}</tr>')

    cards = []
    for i, o in enumerate(top, 1):
        r, a, lg, p = o["resort"], o["air"], o["lodging"], o["passes"]
        lodg_links = "".join(
            f'<li><a href="{e(x["url"])}">{e(x["title"][:60] or "listing")}</a> · {eur(x["total"])}'
            f'{" · ★" + str(x["rating"]) if x["rating"] else ""}</li>' for x in (lg["top"][:3] if lg else []))
        warn = []
        if o["few_lodging"]:
            warn.append(f"few lodging results ({lg['n']})")
        if p.status != "verified_2026_27":
            warn.append("lift pass: " + STATUS.get(p.status, p.status))
        base = (f'<p>Stay in {e(r["base_name"])}, ~{r["base_km"]} km to the lifts'
                f'{". " + e(r["base_note"]) if r.get("base_note") else ""}</p>' if r.get("base_of") else "")
        flight_note = (f'<dt></dt><dd><i>flight price for 3 seats rescaled to {sc["seats"]} — estimate</i></dd>'
                       if a and a.get("estimate") and a.get("ratio", 1) != 1 else "")
        cards.append(f"""
<article class="card">
  <header><div><h3>{e(r['name'])}</h3>{base}
  <p>{dshort(o['week'])} – {dshort(o['check_out'])} · {f"fly to {e(a['airport'])}, {a['hours']} h to the resort" if a else "no flight"}</p></div>
  <div class="tot">{eur(score(o, full))}</div></header>
  <dl>
    {air_rows(a, r, cfg)}{flight_note}
    <dt>Lodging, {cfg['trip']['nights']} nights</dt><dd><a href="{e(lg['search_url'])}">{eur(o['lodging_price'])}</a> <i>{e(o['lodging_kind'])}; {cfg['lodging']['stat']} of {lg['n']}, min {eur(lg['min'])}</i></dd>
    <dt>Lift passes</dt><dd>{eur(p.total)} <i>{e(p.period)}; {e('; '.join(p.lines))}</i></dd>
    {f"<dt>Ski bags</dt><dd>{eur(o['bags'])}</dd>" if o['bags'] else ''}
  </dl>
  {f'<ul class="lodg">{lodg_links}</ul>' if lodg_links else ''}
  {f'<p class="warn"><i>{e(" · ".join(warn))}</i></p>' if warn else ''}
</article>""")

    ref = []
    for r in [x for x in resorts if not x.get("base_of")]:
        lp = r["lift_pass"]
        o = next((x for x in options if x["resort"]["id"] == r["id"]), None)
        sn = o["snow"] if o else None
        snow = (f"{sn['depth_cm']} cm, +{sn['fresh_7d_cm']} last 7 d, forecast +{sn['forecast_7d_cm']}"
                if sn and sn.get("depth_cm") is not None else "—")
        kid_rule = "; ".join(t.get("note", "") for t in lp["child_tiers"] if t.get("note"))
        p = o["passes"] if o else None
        season = r.get("season")
        season_txt = f"<br><i>open {season['from']:%d.%m}–{season['to']:%d.%m}</i>" if season else ""
        ref.append(f"""<tr><td>{e(r['name'])}<br><i>{r['top_m']} m · {e(r['glacier'])}</i>{season_txt}</td>
<td>{e(lp['pass_name'])}<br><i>{eur(lp['default']['adult'])} / {eur(lp['default']['child'])}</i></td>
<td class="num">{eur(p.total) if p else '—'}</td>
<td>{e(kid_rule) or '—'}</td>
<td><i>{STATUS.get(lp.get('status'), lp.get('status', ''))}</i>, <a href="{e(lp['source'])}">source</a></td>
<td>{e(snow)}</td>
<td>{e(', '.join(f'{k} {v} km' for k, v in r['airports'].items()))}</td></tr>""")

    # age, not birth date: the report is public
    kid_txt = ", ".join(f"child ({age_on(c['birth_date'], weeks[0])})" for c in kids) if weeks else ""
    who = f"{party['adults']} adult{'s' if party['adults'] > 1 else ''}" + (f" + {kid_txt}" if kid_txt else "")
    filled = sum(1 for o in options if score(o, full) is not None)
    nofly = "" if full or not totals else '<p class="note"><i>No flights in the database — totals exclude flights.</i></p>'
    banner = nofly + '<p class="note"><i>Demo: flights and lodging are synthetic numbers to show the layout. Lift passes are real.</i></p>' if demo else ""
    car = cfg['transfer']['car_rent_week'] or cfg['transfer']['per_km']

    return f"""<p class="meta">{who} · from {' or '.join(CITY.get(o, o) for o in (froms or origins(cfg)))} · {cfg['trip']['nights']} nights, {cfg['trip']['ski_days']}-day pass · {filled} of {len(options)} priced · built {dt.datetime.now():%d %b %Y, %H:%M}</p>
{banner}
<h2>Resort × check-in week <i>thousand €</i></h2>
<table class="heat"><colgroup><col class="cn">{'<col>' * len(weeks)}</colgroup><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="cap">Total = flights for everyone{' + car and fuel' if car else ' (car and driving not included)'} from the best airport + cheapest lodging ({cfg['lodging']['stat']} of Airbnb homes, Airbnb hotels and Google Hotels) + lift passes for adults. Grey cells: missing flight or lodging price, or the resort is closed.</p>
<h2>Top {len(top)}</h2>
<div class="cards">{''.join(cards) or '<p><i>No complete option yet — run a scan.</i></p>'}</div>
<h2>Resorts and lift passes</h2>
<table class="ref"><thead><tr><th>Resort</th><th>Pass <i>adult / child</i></th><th class="num">Your group</th><th>Children</th><th>Data</th><th>Snow at the top</th><th>Airports</th></tr></thead><tbody>{''.join(ref)}</tbody></table>
<p class="cap">Flight and lodging prices change; links open a live search. “Your group” is the lift pass cost for the first week of the season.</p>
"""


CSS = """
:root{--bg:#fff;--fg:#000;--rule:#000;--card:rgba(0,0,0,.04);--heat-l:0.86;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#202124;--fg:#d4d4d2;--rule:#d4d4d2;--card:rgba(255,255,255,.05);--heat-l:0.42;color-scheme:dark}}
:root[data-theme=dark]{--bg:#202124;--fg:#d4d4d2;--rule:#d4d4d2;--card:rgba(255,255,255,.05);--heat-l:0.42;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;font-optical-sizing:auto;font-feature-settings:"cv11","ss01";transition:background .25s,color .25s}
main{width:100%;padding:32px 64px 72px}
@media (max-width:700px){main{padding:24px 16px 56px}}
h1{font-size:28px;font-weight:600;margin:0;letter-spacing:-.02em}
h2{font-size:20px;font-weight:600;margin:44px 0 14px}h2 i{font-weight:400;font-size:16px}
h3{font-size:17px;font-weight:600;margin:0}
a{color:inherit;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
:focus-visible{outline:2px solid var(--rule);outline-offset:2px}
p{margin:0}.meta{margin:14px 0 0}.cap{margin:12px 0 0;font-size:14px}.note{margin:12px 0 0}
.top{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:baseline;justify-content:space-between}
.bar{margin:18px 0 0;display:flex;flex-wrap:wrap;gap:8px 48px}
.tog{display:flex;flex-wrap:wrap;gap:4px 20px}
.tog button,.theme{font:inherit;color:inherit;background:none;border:0;padding:2px 0;cursor:pointer;border-bottom:1px solid transparent}
.tog button[aria-selected=true]{border-bottom-color:var(--rule);font-style:italic}
.theme{display:inline-flex;align-items:center;gap:8px}
.theme .sw{width:34px;height:18px;border:1px solid var(--rule);border-radius:99px;position:relative}
.theme .sw::after{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--fg);transition:transform .2s}
.theme[aria-checked=true] .sw::after{transform:translateX(16px)}
table{width:100%;font-variant-numeric:tabular-nums lining-nums}
thead th{font-weight:600}
/* heatmap: no frame, no rules — just tiles; always fits the page width */
table.heat{border-collapse:separate;border-spacing:2px;font-size:12px;table-layout:fixed}
.heat col.cn{width:200px}
@media (max-width:900px){.heat col.cn{width:120px}}
@media (max-width:600px){.heat col.cn{width:96px}}
.heat th,.heat td{padding:3px 2px;text-align:center;font-weight:400}
.heat thead th{position:sticky;top:0;z-index:1;background:var(--bg);padding:8px 0 6px;font-weight:600;white-space:nowrap;overflow:hidden}
.heat td{height:38px;border-radius:3px;overflow:hidden}
.heat th.rn{text-align:left;padding:3px 10px 3px 0;line-height:1.25;overflow-wrap:anywhere}
.heat .via{display:block;font-style:italic}
@media (max-width:900px){.heat{font-size:10px;border-spacing:1px}.heat thead th{font-size:9px;writing-mode:vertical-rl;transform:rotate(180deg);height:46px;padding:4px 0}}
@media (max-width:600px){.heat td{font-size:0}.heat td{height:30px}}
/* reference table: book rules */
table.ref{border-collapse:collapse;font-size:13px;overflow-wrap:anywhere;border-top:2px solid var(--rule);border-bottom:2px solid var(--rule)}
.ref thead th{position:sticky;top:0;z-index:1;background:var(--bg);box-shadow:inset 0 -1px var(--rule)}
.ref td,.ref th{text-align:left;padding:8px 12px 8px 0;vertical-align:top}
.ref .num{text-align:right}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.card{background:var(--card);border-radius:10px;padding:16px}
.card header{display:flex;gap:10px;align-items:flex-start}.card header>div{flex:1}.card header p{font-size:14px}
.tot{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:14px 0 0;font-size:14px}dt{font-style:italic}dd{margin:0}
.lodg{margin:10px 0 0;padding-left:18px;font-size:14px}.warn{margin:10px 0 0;font-size:14px}
@media (max-width:420px){.cards{grid-template-columns:1fr}dl{grid-template-columns:1fr}dt{margin-top:6px}}
/* heatmap load: tiles settle in on a diagonal wave */
.heat td{animation:settle .55s cubic-bezier(.2,.7,.2,1) both;animation-delay:var(--d)}
@keyframes settle{from{opacity:0;transform:translateY(6px) scale(.6);filter:blur(3px)}to{opacity:1;transform:none;filter:none}}
@media (prefers-reduced-motion:reduce){.heat td{animation:none}body{transition:none}}
"""

THEME_BOOT = """(function(){try{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}})();"""

SCRIPT = """
const root = document.documentElement, sw = document.querySelector('.theme');
const mq = matchMedia('(prefers-color-scheme: dark)');
const isDark = () => root.dataset.theme ? root.dataset.theme === 'dark' : mq.matches;
const sync = () => sw.setAttribute('aria-checked', isDark());
sw.onclick = () => { root.dataset.theme = isDark() ? 'light' : 'dark'; try { localStorage.setItem('theme', root.dataset.theme); } catch (e) {} sync(); };
mq.addEventListener('change', sync); sync();
const replay = s => s.querySelectorAll('.heat td').forEach(td => { td.style.animation = 'none'; td.offsetWidth; td.style.animation = ''; });
const pick = {s: document.querySelector('.scen').dataset.s, o: document.querySelector('.scen').dataset.o};
const show = () => document.querySelectorAll('.scen').forEach(s => {
  const was = s.hidden; s.hidden = s.dataset.s !== pick.s || s.dataset.o !== pick.o; if (was && !s.hidden) replay(s); });
document.querySelectorAll('.tog button').forEach(b => b.onclick = () => {
  const k = 's' in b.dataset ? 's' : 'o';
  b.parentNode.querySelectorAll('button').forEach(x => x.setAttribute('aria-selected', x === b));
  pick[k] = b.dataset[k]; show();
  try { localStorage.setItem('pick-' + k, pick[k]); } catch (e) {}
});
for (const k of ['s', 'o']) try { const v = localStorage.getItem('pick-' + k); const b = v && document.querySelector('.tog button[data-' + k + '="' + v + '"]'); if (b) b.click(); } catch (e) {}
"""


def render(cfg: dict, resorts: list[dict], weeks: list[dt.date], options, demo: bool = False) -> str:
    """options — a list of options, or {(scenario key, origin | 'any'): options} for the toggles."""
    specs = {s["key"]: s for s in scenarios(cfg)}
    if not isinstance(options, dict):
        options = {next(iter(specs)): options}
    scen = {(k if isinstance(k, tuple) else (k, "any")): v for k, v in options.items()}
    skeys = list(dict.fromkeys(k[0] for k in scen))
    okeys = list(dict.fromkeys(k[1] for k in scen))
    first = next(iter(scen))
    sections = "".join(
        f'<section class="scen" data-s="{s}" data-o="{o}"{"" if (s, o) == first else " hidden"}>'
        f'{_section(cfg, resorts, weeks, opts, specs[s], demo, None if o == "any" else [o])}</section>'
        for (s, o), opts in scen.items())

    def group(name, attr, keys, label):
        if len(keys) < 2:
            return ""
        return (f'<div class="tog" role="tablist" aria-label="{name}">' + "".join(
            f'<button role="tab" data-{attr}="{k}" aria-selected="{str(i == 0).lower()}">{e(label(k))}</button>'
            for i, k in enumerate(keys)) + "</div>")
    toggle = (group("Group", "s", skeys, lambda k: specs[k]["label"])
              + group("Fly from", "o", okeys, lambda k: "Tallinn or Riga" if k == "any" else f"from {CITY.get(k, k)}"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ski Week Cost</title>
<script>{THEME_BOOT}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,400;0,14..32,600;1,14..32,400&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<div class="top"><h1>Ski week: the full cost</h1>
<button class="theme" role="switch" aria-checked="false" aria-label="Dark theme"><span class="sw"></span><i>dark</i></button></div>
<div class="bar">{toggle}</div>
{sections}
</main>
<script>{SCRIPT}</script></body></html>"""
