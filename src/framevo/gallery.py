"""Static result artifacts regenerated after every generation:

- gallery.html   self-refreshing, framework-free, opens via file://
- leaderboard.md top 10 with all metrics
- convergence.png matplotlib fitness-vs-generation plot
"""
from __future__ import annotations

import html
import math
from pathlib import Path

from .dbstore import Store

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { background: #faf9f7; color: #2b2926; margin: 2.2rem auto; max-width: 1180px;
  font: 14px/1.45 -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
  padding: 0 1.2rem; }
h1 { font-size: 1.25rem; font-weight: 600; letter-spacing: .02em; }
h2 { font-size: .82rem; font-variant: small-caps; letter-spacing: .14em;
  color: #8a8580; border-bottom: 1px solid #e4dfd8; padding-bottom: .3rem;
  margin: 2.0rem 0 .8rem; font-weight: 600; }
.meta { color: #8a8580; font-size: .8rem; }
.row { display: flex; flex-wrap: wrap; gap: 10px; }
.card { background: #fff; border: 1px solid #e4dfd8; border-radius: 4px;
  padding: 8px; width: 172px; font-variant-numeric: tabular-nums; }
.card img { width: 100%; height: auto; display: block; background: #fff; }
.card.best { outline: 2px solid #14324f; }
.card.invalid { opacity: .55; background: #f3f0ec; }
.card .agg { font-size: 1.02rem; font-weight: 600; margin-top: 2px; }
.card .hash { font-family: ui-monospace, Menlo, monospace; font-size: .72rem;
  color: #8a8580; }
.card .lab { font-variant: small-caps; letter-spacing: .1em; font-size: .66rem;
  color: #8a8580; }
.card .fail { color: #a05a4a; font-size: .72rem; }
table.sc { width: 100%; border-collapse: collapse; font-size: .7rem;
  margin-top: 4px; font-variant-numeric: tabular-nums; }
table.sc td { padding: 0; color: #5a5650; }
table.sc td:last-child { text-align: right; }
.detail { display: flex; gap: 14px; background: #fff; border: 1px solid #e4dfd8;
  border-radius: 4px; padding: 12px; margin-bottom: 10px;
  font-variant-numeric: tabular-nums; }
.detail img { width: 180px; height: auto; align-self: flex-start; }
.detail .parents { display: flex; gap: 8px; }
.detail .parents img { width: 110px; }
.detail table { font-size: .74rem; border-collapse: collapse; }
.detail table td { padding: 1px 10px 1px 0; }
a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; }
"""


def _fmt(x: float | None, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "&#8734;"  # infinity
    return f"{x:.{digits}f}"


def _rel(results_dir: Path, p: str | None) -> str:
    if not p:
        return ""
    try:
        return str(Path(p).relative_to(results_dir))
    except ValueError:
        return p


def write_gallery(store: Store, run_id: str, results_dir: Path) -> Path:
    cands = {r["hash"]: r for r in store.candidates_for_run(run_id)}
    gens = store.generations_with_population(run_id)
    scen_cache: dict[str, list] = {}

    finite = [(h, store.fitness_of(r)) for h, r in cands.items()
              if math.isfinite(store.fitness_of(r))]
    best_hash = min(finite, key=lambda t: t[1])[0] if finite else None

    parts = [f"<style>{CSS}</style>",
             '<meta http-equiv="refresh" content="30">',
             "<title>framevo gallery</title>",
             f"<h1>frame evolution &mdash; run <code>{html.escape(run_id)}</code></h1>",
             f'<p class="meta">{len(gens)} generation(s) &middot; '
             f'{len(cands)} unique candidates &middot; lower Wh/km is better '
             f'&middot; <a href="lineage.svg">family tree</a> &middot; '
             f'this page refreshes itself every 30&thinsp;s</p>']

    detail_ids: list[str] = []
    for g in reversed(gens):
        rows = sorted(store.population(run_id, g),
                      key=lambda r: (r["fitness"] is None, r["fitness"] or 0.0))
        parts.append(f"<h2>generation {g}</h2>")
        parts.append('<div class="row">')
        for row in rows:
            h = row["hash"]
            c = cands.get(h)
            if c is None:
                continue
            fit = store.fitness_of(c)
            invalid = not math.isfinite(fit)
            cls = "card" + (" best" if h == best_hash else "") + \
                (" invalid" if invalid else "")
            img = _rel(results_dir, c["png_path"])
            if h not in scen_cache:
                scen_cache[h] = store.scenario_results_for(run_id, h)
            sc_rows = "".join(
                f"<tr><td>{html.escape(s['scenario'])}</td>"
                f"<td>{_fmt(s['wh_per_km'], 2) if s['valid'] else 'fail'}</td></tr>"
                for s in scen_cache[h])
            fail = (f'<div class="fail">{html.escape(c["failure_reason"] or "")}'
                    "</div>") if invalid and c["failure_reason"] else ""
            parts.append(
                f'<div class="{cls}">'
                f'<a href="#d-{h}"><img src="{img}" alt="{h}"></a>'
                f'<div class="hash">{h} &middot; g{c["generation_born"]}'
                f' {c["operator"]}</div>'
                f'<div class="agg">{_fmt(fit)} <span class="lab">wh/km agg</span></div>'
                f"{fail}"
                f'<table class="sc">{sc_rows}</table>'
                "</div>")
            if h not in detail_ids:
                detail_ids.append(h)
        parts.append("</div>")

    parts.append("<h2>candidate details &amp; parentage</h2>")
    for h in detail_ids:
        c = cands[h]
        fit = store.fitness_of(c)
        img = _rel(results_dir, c["png_path"])
        parent_imgs = []
        for pkey in ("parent_a", "parent_b"):
            ph = c[pkey]
            if ph and ph in cands:
                pimg = _rel(results_dir, cands[ph]["png_path"])
                pfit = store.fitness_of(cands[ph])
                parent_imgs.append(
                    f'<figure style="margin:0"><a href="#d-{ph}">'
                    f'<img src="{pimg}" alt="{ph}"></a>'
                    f'<figcaption class="hash">{ph} &middot; {_fmt(pfit)}'
                    "</figcaption></figure>")
        parents_html = ("".join(parent_imgs)
                        or '<span class="meta">no parents (seed / immigrant)</span>')
        sc_rows = "".join(
            f"<tr><td>{html.escape(s['scenario'])}</td>"
            f"<td>{_fmt(s['wh_per_km'])}</td><td>{_fmt(s['avg_power_w'], 1)} W</td>"
            f"<td>{_fmt(s['max_tilt_deg'], 1)}&deg;</td>"
            f"<td>{html.escape(s['failure_reason'] or '')}</td></tr>"
            for s in scen_cache.get(h, []))
        mass = f"{c['frame_mass'] * 1e3:.1f}" if c["frame_mass"] else "-"
        parts.append(
            f'<div class="detail" id="d-{h}">'
            f'<img src="{img}" alt="{h}">'
            f"<div><div class='hash'>{h}</div>"
            f"<div>agg <b>{_fmt(fit)}</b> &middot; mean {_fmt(c['mean_whkm'])}"
            f" &middot; worst {_fmt(c['worst_whkm'])} Wh/km"
            f" &middot; frame {mass} g &middot; born g{c['generation_born']}"
            f" via {c['operator']}</div>"
            f'<table><tr class="lab"><td>scenario</td><td>wh/km</td>'
            f"<td>avg power</td><td>max tilt</td><td></td></tr>{sc_rows}</table>"
            f"</div><div class='parents'>{parents_html}</div></div>")

    out = results_dir / "gallery.html"
    out.write_text("\n".join(parts))
    return out


def write_leaderboard(store: Store, run_id: str, results_dir: Path,
                      scenario_names: list[str]) -> Path:
    cands = store.candidates_for_run(run_id)
    ranked = sorted((c for c in cands if c["fitness"] is not None),
                    key=lambda c: c["fitness"])[:10]
    head = ["rank", "hash", "gen", "operator", "frame g", "agg Wh/km",
            "mean", "worst"] + scenario_names
    lines = ["# Leaderboard — top 10", "",
             "| " + " | ".join(head) + " |",
             "|" + "---|" * len(head)]
    for i, c in enumerate(ranked, 1):
        sc = {s["scenario"]: s for s in store.scenario_results_for(run_id, c["hash"])}
        per = [(f"{sc[n]['wh_per_km']:.3f}" if n in sc and sc[n]["valid"]
                else "—") for n in scenario_names]
        lines.append("| " + " | ".join(
            [str(i), f"`{c['hash']}`", str(c["generation_born"]), c["operator"],
             f"{(c['frame_mass'] or 0) * 1e3:.1f}", f"{c['fitness']:.3f}",
             f"{c['mean_whkm']:.3f}", f"{c['worst_whkm']:.3f}"] + per) + " |")
    out = results_dir / "leaderboard.md"
    out.write_text("\n".join(lines) + "\n")
    return out


def write_convergence(store: Store, run_id: str, results_dir: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gens = store.generations_with_population(run_id)
    best, median, best_so_far = [], [], []
    run_best = math.inf
    for g in gens:
        fits = [r["fitness"] for r in store.population(run_id, g)
                if r["fitness"] is not None]
        if fits:
            run_best = min(run_best, min(fits))
            best.append(min(fits))
            fits_sorted = sorted(fits)
            median.append(fits_sorted[len(fits_sorted) // 2])
        else:
            best.append(math.nan)
            median.append(math.nan)
        best_so_far.append(run_best if math.isfinite(run_best) else math.nan)

    fig, ax = plt.subplots(figsize=(7, 4), dpi=110)
    ax.plot(gens, median, color="#b0a9a1", lw=1.2, label="population median")
    ax.plot(gens, best, color="#4a6fa5", lw=1.2, label="generation best")
    ax.plot(gens, best_so_far, color="#14324f", lw=1.8, label="best so far")
    ax.set_xlabel("generation")
    ax.set_ylabel("aggregate fitness (Wh/km)")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    out = results_dir / "convergence.png"
    fig.savefig(out)
    plt.close(fig)
    return out
