"""Lineage: ancestor-chain queries, Graphviz DOT export, and a pure-Python
SVG family tree (no graphviz binary required).

Layout: one row per generation showing that generation's population sorted by
fitness; filled nodes are births (colored dark = better fitness), hollow nodes
are invalid candidates, small pass-through nodes are elite carry-overs
connected by dotted edges. Parent edges are colored by operator.
"""
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

from .dbstore import Store
from .genome import describe_genome

OPERATOR_COLORS = {
    "crossover": "#4a6fa5",
    "pivot": "#2e6e63",
    "designer": "#6a4a8a",  # the gallery's claude purple
    "mutation": "#8c2f1f",
    "immigrant": "#8a6a1e",
    "elite": "#9b998c",
    "seed": "#b9b6a6",
    "cmaes": "#888888",
}
CLAUDE = "#6a4a8a"  # one purple everywhere: chart halos, bands, cards


def format_lineage(store: Store, run_id: str, h: str) -> str:
    """Human-readable ancestor chain of a candidate, fitness at each step."""
    rows = store.ancestor_rows(run_id, h)
    if not rows:
        return f"no candidate {h} in run {run_id}"
    lines = [f"ancestry of {h} (run {run_id}), nearest first:"]
    for r in rows:
        fit = store.fitness_of(r)
        fit_s = f"{fit:8.3f} Wh/km-agg" if math.isfinite(fit) else "  invalid"
        parents = " + ".join(x for x in (r["parent_a"], r["parent_b"]) if x) or "-"
        mut = f"  mut={r['mutation_mag']:.3f}" if r["mutation_mag"] else ""
        note = f"  [{r['failure_reason']}]" if r["failure_reason"] else ""
        lines.append(
            f"  depth {r['depth']}: {r['hash']}  gen {r['generation_born']:3d}"
            f"  {r['operator']:<9s} {fit_s}  parents: {parents}{mut}{note}")
    return "\n".join(lines)


def _fitness_color(fit: float, lo: float, hi: float) -> str:
    """Dark = better. Maps fitness onto a light->dark ramp."""
    if not math.isfinite(fit):
        return "#ffffff"
    x = 0.0 if hi <= lo else (fit - lo) / (hi - lo)
    # interpolate near-black ink (best) -> warm pale (worst), Tufte ramp
    c0, c1 = (0x11, 0x11, 0x11), (0xd9, 0xd5, 0xc3)
    rgb = tuple(round(a + (b - a) * x) for a, b in zip(c0, c1))
    return "#%02x%02x%02x" % rgb


def write_dot(store: Store, run_id: str, results_dir: Path) -> Path:
    cands = store.candidates_for_run(run_id)
    fits = [store.fitness_of(r) for r in cands]
    finite = [f for f in fits if math.isfinite(f)]
    lo, hi = (min(finite), max(finite)) if finite else (0.0, 1.0)

    lines = ["digraph lineage {",
             '  rankdir=TB; node [shape=circle, style=filled, fontsize=8];']
    by_gen: dict[int, list[str]] = {}
    for r, fit in zip(cands, fits):
        color = _fitness_color(fit, lo, hi)
        style = "filled" if math.isfinite(fit) else "solid"  # hollow = invalid
        label = f"{r['hash'][:6]}\\n{fit:.2f}" if math.isfinite(fit) \
            else f"{r['hash'][:6]}\\ninv"
        font = "white" if math.isfinite(fit) and (fit - lo) < 0.5 * (hi - lo + 1e-9) \
            else "black"
        border = ' color="#6a4a8a", penwidth=2.4' \
            if r["operator"] == "designer" else ""
        lines.append(f'  "{r["hash"]}" [label="{label}", fillcolor="{color}",'
                     f' style="{style}", fontcolor={font}{border}];')
        by_gen.setdefault(r["generation_born"], []).append(r["hash"])
        for parent, tag in ((r["parent_a"], "a"), (r["parent_b"], "b")):
            if parent:
                col = OPERATOR_COLORS.get(r["operator"], "#888888")
                lines.append(f'  "{parent}" -> "{r["hash"]}"'
                             f' [label="{r["operator"]}", color="{col}", fontsize=7];')
    for gen, hs in sorted(by_gen.items()):
        ranked = "; ".join(f'"{h}"' for h in hs)
        lines.append(f"  {{ rank=same; {ranked} }}")
    # elite pass-through: same hash present in consecutive populations
    gens = store.generations_with_population(run_id)
    for g0, g1 in zip(gens, gens[1:]):
        prev = {r["hash"] for r in store.population(run_id, g0)}
        for r in store.population(run_id, g1):
            if r["hash"] in prev:
                lines.append(f'  "{r["hash"]}" -> "{r["hash"]}"'
                             f' [style=dotted, color="#999188", label="elite"];')
    lines.append("}")
    out = results_dir / "lineage.dot"
    out.write_text("\n".join(lines))
    return out


def _rel(results_dir: Path, p: str | None) -> str:
    if not p:
        return ""
    try:
        return str(Path(p).relative_to(results_dir))
    except ValueError:
        return p



LEGEND_TIPS = {
    "crossover": "Simulated Binary Crossover: the child's genes are sampled "
                 "around its two parents' values (closer for higher eta) -- "
                 "the digital analogue of breeding two good frames.",
    "pivot": "Patience exhausted: after 6 generations without a >=0.5% "
             "improvement, children are bred from a tournament winner and a "
             "FAR parent (the most genetically distant still-decent candidate "
             "in the run's history) under boosted mutation, to break the "
             "plateau.",
    "designer": "Claude-designed: proposed by a designer round (opening, "
                "scheduled, or pivot), born from a prompt rather than "
                "parents -- so it has no incoming edge; the purple halo is "
                "its mark, the same purple the gallery uses. Carried-over "
                "copies keep a thinner halo.",
    "mutation": "Gaussian noise on a subset of genes. Its sigma decays per "
                "generation, so early search explores and late search "
                "fine-tunes.",
    "immigrant": "A fresh random genome injected (~10% of non-elite slots) "
                 "to keep genetic diversity from collapsing. No parents, so "
                 "no edge -- the small gold caret above a node marks the "
                 "injection.",
    "elite": "Elite carry-over: the top candidates pass unchanged into the "
             "next generation so the best design can never be lost. The "
             "dashed line follows one candidate surviving; it reappears as "
             "a SMALL node in the later row.",
    "seed": "Generation 0: the real Source One V6 baseline plus random "
            "genomes -- no parents.",
    "cmaes": "Sampled from CMA-ES's adapted Gaussian (the flag-gated "
             "alternative optimizer). No discrete parents; provenance is "
             "the distribution's mean and sigma.",
    "shade": "Node fill maps fitness onto a light-to-dark ramp within this "
             "run: DARKER = lower aggregate Wh/km = better. The scale is "
             "relative to this run's best and worst valid candidates.",
    "size": "Large node = the candidate was BORN in that generation. Small "
            "node = an elite carried over unchanged, shown again in a later "
            "generation's population.",
    "hollow": "Invalid design: it violated a hard constraint (tongue "
              "collision, stack fit, rotor clearance, structural failure...) "
              "or failed a flight scenario. Fitness = infinity; it is never "
              "selected as a parent.",
    "ring": "This candidate set a new best-so-far when it was evaluated -- "
            "the same improvements the gallery chart labels on its step "
            "line. A DOUBLE ring is the run champion (the gallery's "
            "red-outlined card).",
    "claude_gen": "A light purple row means a Claude designer round shaped "
                  "this generation -- the same purple band the gallery "
                  "chart shows; the g-label carries a purple &#10022;. The "
                  "round's prompt and proposals are in the gallery's "
                  "generation panel.",
    "pivot_gen": "A teal dashed rule above the row (and &#10227; on the "
                 "g-label) marks a pivot generation: patience ran out and "
                 "half the non-elite slots were bred with far parents "
                 "under boosted mutation.",
    "lens": "The lens buttons restyle this one tree: PERFORMANCE fades "
            "edges so node status (fitness shade, rings, halos) reads "
            "clean; BREEDING flattens the fitness shading and boosts edge "
            "colors so the operators read clean; COMBINED shows both.",
}


def _legend_html() -> str:
    from .lineage import OPERATOR_COLORS  # self-import safe at call time
    items = []

    def tip(key, title):
        return (f'<span class="tip"><b>{title}</b><br>'
                f'{html.escape(LEGEND_TIPS[key])}</span>')

    for name, col in OPERATOR_COLORS.items():
        if name == "designer":  # no edges: shown as the purple halo
            items.append(
                '<span class="lg"><span class="sw">'
                '<svg width="18" height="18"><circle cx="9" cy="9" r="4.5" '
                'fill="#7a766b"/><circle cx="9" cy="9" r="7.5" fill="none" '
                f'stroke="{col}" stroke-width="1.6"/></svg></span>'
                'claude-designed' + tip(name, "claude-designed") + "</span>")
            continue
        if name == "immigrant":  # no edges: shown as the gold caret
            items.append(
                '<span class="lg"><span class="sw">'
                '<svg width="16" height="18"><path d="M4,2 l4,6 l4,-6 z" '
                f'fill="{col}"/><circle cx="8" cy="13" r="4.5" '
                'fill="#7a766b"/></svg></span>'
                'immigrant' + tip(name, "immigrant") + "</span>")
            continue
        label = "elite carry-over" if name == "elite" else name
        dash = "border-top:2px dashed " if name == "elite" else "border-top:2px solid "
        items.append(
            f'<span class="lg"><span class="sw" style="width:16px;height:0;'
            f'{dash}{col}"></span>{label}{tip(name, label)}</span>')
    items.append(
        '<span class="lg"><span class="sw" style="width:16px;height:12px;'
        'background:rgba(106,74,138,.14)"></span>purple row = claude round'
        + tip("claude_gen", "claude generation") + "</span>")
    items.append(
        '<span class="lg"><span class="sw" style="width:16px;height:0;'
        'border-top:2px dashed #2e6e63"></span>pivot generation'
        + tip("pivot_gen", "pivot generation") + "</span>")
    items.append(
        '<span class="lg"><span class="sw">'
        '<svg width="52" height="12"><circle cx="6" cy="6" r="5" fill="#111111"/>'
        '<circle cx="22" cy="6" r="5" fill="#7a766b"/>'
        '<circle cx="38" cy="6" r="5" fill="#d9d5c3"/></svg></span>'
        'node shade = fitness' + tip("shade", "node shade") + "</span>")
    items.append(
        '<span class="lg"><span class="sw">'
        '<svg width="34" height="16"><circle cx="8" cy="8" r="7" fill="#6b6a60"/>'
        '<circle cx="24" cy="8" r="4" fill="#6b6a60"/></svg></span>'
        'node size = born / carried' + tip("size", "node size") + "</span>")
    items.append(
        '<span class="lg"><span class="sw">'
        '<svg width="16" height="16"><circle cx="8" cy="8" r="6" fill="none" '
        'stroke="#b9b6a6" stroke-width="1.4"/></svg></span>'
        'hollow = invalid' + tip("hollow", "hollow node") + "</span>")
    items.append(
        '<span class="lg"><span class="sw">'
        '<svg width="44" height="22"><circle cx="9" cy="11" r="5" fill="#111111"/>'
        '<circle cx="9" cy="11" r="7.5" fill="none" stroke="#8c2f1f" '
        'stroke-width="1.4"/>'
        '<circle cx="32" cy="11" r="5" fill="#111111"/>'
        '<circle cx="32" cy="11" r="7.5" fill="none" stroke="#8c2f1f" '
        'stroke-width="1.4"/>'
        '<circle cx="32" cy="11" r="10" fill="none" stroke="#8c2f1f" '
        'stroke-width="1.4"/></svg></span>'
        'best so far / champion' + tip("ring", "best-so-far rings") + "</span>")
    return '<div class="lgd">' + "".join(items) + "</div>"


def write_lineage_page(store: Store, run_id: str, results_dir: Path) -> Path:
    """A dedicated Tufte-styled page for the family tree, linked from the
    gallery. Embeds lineage.svg inline plus per-candidate metadata so that
    hovering a node shows a small candidate card and lights up the full
    ancestor lineage (nodes and edges) of that candidate."""
    svg_path = results_dir / "lineage.svg"
    svg = svg_path.read_text() if svg_path.exists() else "<p>no tree yet</p>"
    # drop the paper-colored background rect: the page supplies the paper
    svg = svg.replace('<rect width="100%" height="100%" fill="#fffff8"/>', "", 1)
    # drop native <title> tooltips: the hover card replaces them here
    # (they stay in the standalone lineage.svg)
    svg = re.sub(r"<title>.*?</title>", "", svg, flags=re.S)
    m = re.search(r'width="(\d+)"', svg)
    svg_w = int(m.group(1)) if m else 900  # dock the card beside the tree

    # per-candidate metadata for the hover card + ancestor walk
    meta: dict[str, dict] = {}
    for r in store.candidates_for_run(run_id):
        fit = store.fitness_of(r)
        meta[r["hash"]] = {
            "a": r["parent_a"], "b": r["parent_b"],
            "g": r["generation_born"], "op": r["operator"],
            "fit": round(fit, 3) if math.isfinite(fit) else None,
            "mean": round(r["mean_whkm"], 3) if r["mean_whkm"] is not None else None,
            "worst": round(r["worst_whkm"], 3) if r["worst_whkm"] is not None else None,
            "png": _rel(results_dir, r["png_path"]),
            "mat": r["material"],
            "mass": round(r["frame_mass"] * 1e3, 1) if r["frame_mass"] else None,
            "mut": round(r["mutation_mag"], 3) if r["mutation_mag"] else None,
            "fail": r["failure_reason"],
            "hyp": (r["hypothesis"] or "")[:260] if "hypothesis" in r.keys() else "",
            "res": (r["result_note"] or "")[:260] if "result_note" in r.keys() else "",
            "sc": [{"n": s["scenario"], "ok": bool(s["valid"]),
                    "w": round(s["wh_per_km"], 3) if s["wh_per_km"] is not None else None,
                    "p": round(s["avg_power_w"], 1) if s["avg_power_w"] is not None else None,
                    "t": round(s["max_tilt_deg"], 1) if s["max_tilt_deg"] is not None else None}
                   for s in store.scenario_results_for(run_id, r["hash"])],
        }

    page = f"""<style>
:root{{--paper:#fffff8;--ink:#111111;--muted:#6b6a60;--faint:#9b998c;
  --rule:#d9d5c3;--rule-soft:#ece9da;--accent:#8c2f1f;
  --serif:"Palatino","Palatino Linotype","Book Antiqua","URW Palladio L",Georgia,serif;
  --mono:ui-monospace,"SF Mono",Menlo,monospace}}
*{{box-sizing:border-box}}
html{{background:var(--paper)}}
body{{margin:0;background:var(--paper);color:var(--ink);
  font:17px/1.55 var(--serif);font-feature-settings:"onum" 1,"liga" 1;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:92vw;margin:0 auto;padding:40px 0 96px}}
h1{{font-weight:400;font-size:34px;letter-spacing:-.01em;margin:0 0 6px;text-align:center}}
h1 code{{font:400 26px var(--mono);color:var(--muted)}}
.sub{{font-size:15px;color:var(--muted);margin:0 auto 22px;max-width:820px;text-align:center}}
a{{color:var(--accent);text-decoration:none}}
.tree{{border-top:1px solid var(--rule);padding-top:18px;overflow-x:auto}}
.tree svg{{display:block;margin:0 auto}}
.note{{font-style:italic;color:var(--faint);font-size:14px;margin-top:14px;text-align:center}}
/* hover interactivity: dim everything outside the hovered ancestry */
.nd,.ed,.el,.bs,.cl,.im{{transition:opacity .12s ease}}
.hit{{cursor:pointer}}
svg.focus .nd:not(.lit),svg.focus .ed:not(.lit),svg.focus .el:not(.lit),
svg.focus .bs:not(.lit),svg.focus .cl:not(.lit),
svg.focus .im:not(.lit){{opacity:.12}}
svg.focus .ed.lit{{stroke-width:2;opacity:1}}
svg.focus .el.lit{{stroke-width:2;opacity:1}}
svg.focus .nd.lit{{stroke:var(--ink);stroke-width:1.6}}
/* the candidate card (matches the gallery detail block), docked just to
   the right of the tree so it never covers the highlighted ancestry */
.ncard{{position:fixed;top:50%;transform:translateY(-50%);
  left:min(calc(50% + {svg_w // 2 + 26}px),calc(100vw - 372px));
  z-index:10;width:340px;max-height:calc(100vh - 32px);overflow:hidden;
  background:var(--paper);border:1px solid var(--ink);
  padding:14px 16px 14px;pointer-events:none;
  box-shadow:6px 6px 0 rgba(17,17,17,.07);display:none}}
.ncard img{{width:100%;aspect-ratio:4/3;object-fit:contain;display:block;
  mix-blend-mode:multiply}}
.ncard .imgw{{position:relative}}
/* invalid candidates: same red diagonal cross as the gallery */
.ncard .imgw.x::after{{content:"";position:absolute;inset:0;
  pointer-events:none;background:
  linear-gradient(to top right,transparent calc(50% - 1px),
    rgba(140,47,31,.65) calc(50% - 1px),rgba(140,47,31,.65) calc(50% + 1px),
    transparent calc(50% + 1px)),
  linear-gradient(to bottom right,transparent calc(50% - 1px),
    rgba(140,47,31,.65) calc(50% - 1px),rgba(140,47,31,.65) calc(50% + 1px),
    transparent calc(50% + 1px))}}
.ncard .dhead{{font:400 16px var(--serif);margin-top:8px}}
.ncard .dhead .h{{font:13px var(--mono);color:var(--muted);word-break:break-all}}
.ncard .head{{font-size:14.5px;line-height:1.5;margin-top:3px;
  font-variant-numeric:lining-nums tabular-nums}}
.ncard .head b{{font-size:18px}}
.ncard .fail{{color:var(--accent);font-size:13.5px;font-style:italic;line-height:1.4;margin-top:3px}}
.ncard table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:9px;
  font-variant-numeric:lining-nums tabular-nums}}
.ncard th{{text-align:left;font:600 10px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  border-bottom:1.5px solid var(--ink);padding:2px 10px 3px 0;white-space:nowrap}}
.ncard td{{padding:2.5px 10px 2.5px 0;border-bottom:1px solid var(--rule-soft);
  color:var(--ink)}}
.ncard td:first-child{{color:var(--muted)}}
.ncard .anc{{font-size:12.5px;font-style:italic;color:var(--faint);margin-top:8px}}
.ncard .nb{{font-size:12.5px;line-height:1.45;margin-top:7px;color:#33312b}}
.ncard .nb b{{display:block;margin-bottom:1px;
  font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.05em;font-size:10.5px;color:var(--muted)}}
.ncard .nb.res b{{color:var(--accent)}}
/* interactive legend (replaces the SVG's baked-in one) */
.tree svg .svg-legend{{display:none}}
.lgd{{display:flex;flex-wrap:wrap;gap:7px 20px;justify-content:center;
  align-items:center;font-size:13.5px;color:var(--muted);
  max-width:1080px;margin:0 auto 16px}}
.lg{{position:relative;display:inline-flex;align-items:center;gap:7px;
  cursor:help;padding:2px 0}}
.lg:hover{{color:var(--ink)}}
.lg .sw{{display:inline-flex;align-items:center}}
.lg .tip{{display:none;position:absolute;left:calc(100% + 12px);top:50%;
  transform:translateY(-50%);width:300px;z-index:30;background:var(--paper);
  border:1px solid var(--ink);padding:10px 13px;font-size:13.5px;
  line-height:1.5;color:var(--ink);box-shadow:6px 6px 0 rgba(17,17,17,.07);
  font-style:normal}}
.lg:hover .tip{{display:block}}
.lg:nth-last-child(-n+3) .tip{{left:auto;right:calc(100% + 12px)}}
.lg .tip b{{font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.05em;font-size:11.5px;color:var(--muted)}}
/* lens switcher: one tree, three emphases */
.lens{{display:flex;gap:2px;justify-content:center;align-items:center;
  margin:0 0 16px}}
.lens .llab{{font:600 11px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.08em;color:var(--faint);
  margin-right:12px;cursor:help;position:relative}}
.lens .llab .tip{{display:none;position:absolute;left:0;top:calc(100% + 8px);
  width:320px;z-index:30;background:var(--paper);border:1px solid var(--ink);
  padding:10px 13px;font:normal 13.5px/1.5 var(--serif);color:var(--ink);
  box-shadow:6px 6px 0 rgba(17,17,17,.07);text-transform:none;
  letter-spacing:0}}
.lens .llab:hover .tip{{display:block}}
.lens button{{font:600 12px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  background:none;border:1px solid var(--rule);padding:6px 15px;
  cursor:pointer}}
.lens button.on{{color:var(--ink);border-color:var(--ink);
  border-bottom:2px solid var(--ink)}}
/* performance lens: candidate status forward, breeding recedes */
svg.lens-perf .ed,svg.lens-perf .el{{opacity:.1}}
/* breeding lens: operators forward, fitness shading recedes */
svg.lens-breed .nd{{fill:#e7e4d6}}
svg.lens-breed .nd.inv{{fill:none}}
svg.lens-breed .ed{{stroke-width:2.2;opacity:1}}
svg.lens-breed .el{{stroke-width:1.8;opacity:.95}}
svg.lens-breed .bs{{opacity:.18}}
</style>
<meta charset="utf-8">
<title>framevo family tree</title>
<div class="wrap">
<h1>family tree &mdash; run <code>{run_id}</code></h1>
<p class="sub">one row per generation, candidates ordered best&#8594;worst.
Nodes carry the candidate language: shaded dark&thinsp;=&thinsp;better
fitness, hollow&thinsp;=&thinsp;invalid, small&thinsp;=&thinsp;elite carried
over, rust ring&thinsp;=&thinsp;best-so-far (double&thinsp;=&thinsp;the run
champion), <span style="color:#6a4a8a">purple halo&thinsp;=&thinsp;
claude-designed</span>. Edges carry the breeding language: color names the
operator, a gold caret is an immigrant injection, a purple row is a claude
designer round, a teal dashed rule is a pivot generation. Hover any node to
see the candidate and its full ancestry; click to pin (esc releases).
&middot; <a href="gallery.html">back to the gallery</a></p>
{_legend_html()}
<div class="lens"><span class="llab">lens<span class="tip">
{html.escape(LEGEND_TIPS["lens"])}</span></span>
<button data-lens="" class="on">combined</button>
<button data-lens="lens-perf">performance</button>
<button data-lens="lens-breed">breeding</button></div>
<div class="tree">{svg}</div>
<p class="note">The same graph is exported as Graphviz DOT
(<a href="lineage.dot">lineage.dot</a>) and raw SVG
(<a href="lineage.svg">lineage.svg</a>); ancestry of any candidate:
<code style="font-size:13px">framevo lineage &lt;hash&gt;</code>.</p>
</div>
<script type="application/json" id="cand-meta">{json.dumps(meta)}</script>
<script>
(function(){{
"use strict";
var META=JSON.parse(document.getElementById("cand-meta").textContent);
var svg=document.querySelector(".tree svg");
if(!svg)return;
var card=document.createElement("div");
card.className="ncard";
document.body.appendChild(card);
function esc(s){{var d=document.createElement("i");d.textContent=s==null?"":s;
  return d.innerHTML}}
function ancestors(h){{ // hovered candidate + every ancestor, via parent walk
  var seen={{}};seen[h]=1;var q=[h];
  while(q.length){{
    var c=META[q.pop()];
    if(!c)continue;
    [c.a,c.b].forEach(function(p){{if(p&&!seen[p]){{seen[p]=1;q.push(p)}}}});
  }}
  return seen;
}}
var pinned=null;
function show(h,pin){{
  var c=META[h];
  var set=ancestors(h);
  svg.classList.add("focus");
  svg.querySelectorAll(".nd,.bs,.cl,.im").forEach(function(n){{
    n.classList.toggle("lit",!!set[n.dataset.h])}});
  svg.querySelectorAll(".ed").forEach(function(e){{
    e.classList.toggle("lit",!!set[e.dataset.c])}});
  svg.querySelectorAll(".el").forEach(function(e){{
    e.classList.toggle("lit",!!set[e.dataset.h])}});
  if(!c){{card.style.display="none";return}}
  var nAnc=Object.keys(set).length-1;
  var head;
  if(c.fit!=null){{ // same headline language as the gallery detail block
    head='<div class="head"><b>'+c.fit.toFixed(3)+"</b>&thinsp;Wh/km"
      +(c.mean!=null?" &middot; mean "+c.mean.toFixed(3):"")
      +(c.worst!=null?" &middot; worst "+c.worst.toFixed(3):"")
      +(c.mass?" &middot; "+c.mass.toFixed(1)+"&thinsp;g":"")
      +(c.mat?" &middot; "+esc(c.mat):"")
      +" &middot; born g"+c.g+" via "+esc(c.op)
      +(c.mut?" (mut "+c.mut+")":"")+"</div>";
  }}else{{
    head='<div class="fail">invalid &mdash; '+esc(c.fail||"unknown")
      +" &middot; never flew</div>"
      +'<div class="head">born g'+c.g+" via "+esc(c.op)
      +(c.mat?" &middot; "+esc(c.mat):"")+"</div>";
  }}
  var table="";
  if(c.sc&&c.sc.length){{
    table='<table><tr><th>scenario</th><th>wh/km</th>'
      +"<th>avg power, w</th><th>max tilt</th></tr>"
      +c.sc.map(function(s){{
        return "<tr><td>"+esc(s.n)+"</td>"
          +"<td>"+(s.ok&&s.w!=null?s.w.toFixed(3):"fail")+"</td>"
          +"<td>"+(s.ok&&s.p!=null?s.p.toFixed(1):"&mdash;")+"</td>"
          +"<td>"+(s.ok&&s.t!=null?s.t.toFixed(1)+"&deg;":"&mdash;")+"</td></tr>";
      }}).join("")+"</table>";
  }}
  var notes="";
  if(c.hyp)notes+='<div class="nb"><b>hypothesis</b> '+esc(c.hyp)+"</div>";
  if(c.res)notes+='<div class="nb res"><b>result</b> '+esc(c.res)+"</div>";
  card.innerHTML=(c.png?'<div class="imgw'+(c.fit==null?" x":"")+'">'
      +'<img src="'+esc(c.png)+'" alt=""></div>':"")
    +'<div class="dhead">candidate <span class="h">'+esc(h)+"</span></div>"
    +head+notes+table
    +'<div class="anc">'+(nAnc?nAnc+" ancestor"+(nAnc>1?"s":"")
      +" highlighted":"seed / immigrant &mdash; no ancestors")
    +(pin?" &middot; pinned &mdash; click again or press esc to release":"")
    +"</div>";
  card.style.display="block";
}}
function clear(){{
  svg.classList.remove("focus");
  card.style.display="none";
}}
function unpin(){{
  if(pinned){{pinned=null;clear()}}
}}
svg.querySelectorAll(".hit").forEach(function(hit){{
  hit.addEventListener("mouseenter",function(){{
    if(!pinned)show(hit.dataset.h,false)}});
  hit.addEventListener("mouseleave",function(){{
    if(!pinned)clear()}});
  hit.addEventListener("click",function(ev){{
    ev.stopPropagation();
    if(pinned===hit.dataset.h){{unpin()}}
    else{{pinned=hit.dataset.h;show(pinned,true)}}
  }});
}});
document.addEventListener("click",unpin);
document.addEventListener("keydown",function(ev){{
  if(ev.key==="Escape")unpin()}});
// lens switcher: restyle the same tree; survives the 30s auto-refresh
var lensBtns=document.querySelectorAll(".lens button");
function setLens(v){{
  svg.classList.remove("lens-perf","lens-breed");
  if(v)svg.classList.add(v);
  lensBtns.forEach(function(b){{b.classList.toggle("on",(b.dataset.lens||"")===v)}});
  try{{localStorage.setItem("framevo-lens",v)}}catch(e){{}}
}}
lensBtns.forEach(function(b){{b.addEventListener("click",function(ev){{
  ev.stopPropagation();setLens(b.dataset.lens||"")}})}});
try{{setLens(localStorage.getItem("framevo-lens")||"")}}catch(e){{}}
// auto-refresh (was a meta tag): hold off while a lineage is pinned
setInterval(function(){{if(!pinned)location.reload()}},30000);
}})();
</script>"""
    out = results_dir / "lineage.html"
    out.write_text(page)
    return out


def write_svg(store: Store, run_id: str, results_dir: Path) -> Path:
    """Self-contained SVG family tree, laid out generation-by-generation."""
    gens = store.generations_with_population(run_id)
    cands = {r["hash"]: r for r in store.candidates_for_run(run_id)}
    fits = {h: store.fitness_of(r) for h, r in cands.items()}
    finite = [f for f in fits.values() if math.isfinite(f)]
    lo, hi = (min(finite), max(finite)) if finite else (0.0, 1.0)

    xstep, ystep, r_node, margin = 46, 84, 9, 60
    pop_rows = {g: sorted(store.population(run_id, g),
                          key=lambda r: (r["fitness"] is None,
                                         r["fitness"] if r["fitness"] is not None else 0))
                for g in gens}
    legend_w = margin * 2 + sum(30 + 7 * len(n) for n in OPERATOR_COLORS) + 180
    width = max(margin * 2 + max((len(v) for v in pop_rows.values()), default=1)
                * xstep, legend_w)
    height = margin * 2 + (len(gens)) * ystep

    # best-so-far improvements: the candidates the gallery's step line labels
    best_hashes: set[str] = set()
    running_best = math.inf
    for c in store.candidates_in_eval_order(run_id):
        f = store.fitness_of(c)
        if math.isfinite(f) and f < running_best:
            running_best = f
            best_hashes.add(c["hash"])
    # claude involvement + pivots + the run champion (gallery language)
    claude_gens = {r["generation"] for r in store.designer_rounds_for(run_id)}
    pivot_gens = {r["generation_born"] for r in cands.values()
                  if r["operator"] == "pivot"}
    champion = min((h for h, f in fits.items() if math.isfinite(f)),
                   key=lambda h: fits[h], default=None)

    pos: dict[tuple[int, str], tuple[float, float]] = {}
    birth_pos: dict[str, tuple[float, float]] = {}
    for gi, g in enumerate(gens):
        for si, row in enumerate(pop_rows[g]):
            x = margin + si * xstep + xstep / 2
            y = margin + gi * ystep
            pos[(g, row["hash"])] = (x, y)
            cand = cands.get(row["hash"])
            if cand is not None and cand["generation_born"] == g \
                    and row["hash"] not in birth_pos:
                birth_pos[row["hash"]] = (x, y)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}"'
           f' height="{height}" font-family="Helvetica,Arial,sans-serif">',
           '<rect width="100%" height="100%" fill="#fffff8"/>']

    # generation bands behind everything: light purple = claude designer
    # round shaped this generation; teal dashed top rule = pivot generation
    for gi, g in enumerate(gens):
        y = margin + gi * ystep
        if g in claude_gens:
            svg.append(f'<rect class="gb" x="0" y="{y - ystep / 2:.0f}"'
                       f' width="{width}" height="{ystep}" fill="{CLAUDE}"'
                       f' opacity="0.06"><title>g{g}: claude designer round'
                       "</title></rect>")
        if g in pivot_gens:
            svg.append(f'<line class="gp" x1="8" y1="{y - ystep / 2:.0f}"'
                       f' x2="{width - 8}" y2="{y - ystep / 2:.0f}"'
                       f' stroke="#2e6e63" stroke-width="1"'
                       f' stroke-dasharray="5,4" opacity="0.5"/>')

    # edges first (classed + tagged with hashes so the html page can
    # highlight a hovered candidate's ancestry)
    for g in gens:
        for row in pop_rows[g]:
            h = row["hash"]
            cand = cands.get(h)
            if cand is None:
                continue
            x1, y1 = pos[(g, h)]
            if cand["generation_born"] == g:
                for parent in (cand["parent_a"], cand["parent_b"]):
                    if parent and (g - 1, parent) in pos:
                        px, py = pos[(g - 1, parent)]
                    elif parent and parent in birth_pos:
                        px, py = birth_pos[parent]
                    else:
                        continue
                    col = OPERATOR_COLORS.get(cand["operator"], "#888")
                    svg.append(f'<path class="ed" data-c="{h}" data-p="{parent}"'
                               f' d="M{px:.0f},{py + r_node:.0f}'
                               f' C{px:.0f},{(py + y1) / 2:.0f} {x1:.0f},'
                               f'{(py + y1) / 2:.0f} {x1:.0f},{y1 - r_node:.0f}"'
                               f' stroke="{col}" fill="none" stroke-width="1.1"'
                               f' opacity="0.75"/>')
            elif (g - 1, h) in pos:  # elite pass-through
                px, py = pos[(g - 1, h)]
                svg.append(f'<line class="el" data-h="{h}"'
                           f' x1="{px:.0f}" y1="{py + r_node:.0f}"'
                           f' x2="{x1:.0f}" y2="{y1 - r_node:.0f}"'
                           f' stroke="#999188" stroke-dasharray="3,3"'
                           f' stroke-width="1.2"/>')

    # nodes
    for g in gens:
        for row in pop_rows[g]:
            h = row["hash"]
            x, y = pos[(g, h)]
            cand = cands.get(h)
            fit = fits.get(h, math.inf)
            is_birth = cand is not None and cand["generation_born"] == g
            rr = r_node if is_birth else r_node * 0.55
            icls = ""
            if math.isfinite(fit):
                fill = _fitness_color(fit, lo, hi)
                stroke = "#6b6a60"
            else:
                fill = "none"  # hollow = invalid
                stroke = "#b9b6a6"
                icls = " inv"
            head = (f"{h} gen{cand['generation_born'] if cand else g} "
                    f"{cand['operator'] if cand else ''} "
                    + (f"{fit:.3f}" if math.isfinite(fit)
                       else (cand["failure_reason"] or "invalid") if cand else ""))
            if cand is not None:  # full genome breakdown in the tooltip
                genes = describe_genome(json.loads(cand["genome_json"]),
                                        cand["material"])
                head += "\n" + "\n".join(f"{lab}: {val}" for lab, val in genes)
            title = html.escape(head)
            svg.append(f'<circle class="nd{icls}" data-h="{h}"'
                       f' cx="{x:.0f}" cy="{y:.0f}" r="{rr:.1f}"'
                       f' fill="{fill}" stroke="{stroke}" stroke-width="1.2">'
                       f'<title>{title}</title></circle>')
            rad = rr + 3.5  # rings stack outward: setter, champion, claude
            if is_birth and h in best_hashes:  # rust ring = best-so-far
                svg.append(f'<circle class="bs" data-h="{h}"'
                           f' cx="{x:.0f}" cy="{y:.0f}" r="{rad:.1f}"'
                           f' fill="none" stroke="#8c2f1f" stroke-width="1.3"/>')
                rad += 3.0
                if h == champion:  # double rust ring = the run champion
                    svg.append(f'<circle class="bs" data-h="{h}"'
                               f' cx="{x:.0f}" cy="{y:.0f}" r="{rad:.1f}"'
                               f' fill="none" stroke="#8c2f1f"'
                               f' stroke-width="1.3"/>')
                    rad += 3.0
            if cand is not None and cand["operator"] == "designer":
                # claude-designed: purple halo (also on carried-over copies)
                svg.append(f'<circle class="cl" data-h="{h}"'
                           f' cx="{x:.0f}" cy="{y:.0f}" r="{rad:.1f}"'
                           f' fill="none" stroke="{CLAUDE}"'
                           f' stroke-width="{1.7 if is_birth else 1.1}"/>')
            if is_birth and cand is not None \
                    and cand["operator"] == "immigrant":
                # gold caret = random immigrant injected from outside
                svg.append(f'<path class="im" data-h="{h}"'
                           f' d="M{x - 4:.0f},{y - rr - 10:.0f} l4,6 l4,-6 z"'
                           f' fill="#8a6a1e"/>')
            # generous invisible hit target for hover on the html page
            svg.append(f'<circle class="hit" data-h="{h}"'
                       f' cx="{x:.0f}" cy="{y:.0f}" r="{max(rr + 5, 14):.1f}"'
                       f' fill="transparent" stroke="none"/>')
        # generation label
    for gi, g in enumerate(gens):
        marks = ""
        if g in claude_gens:
            marks += f'<tspan fill="{CLAUDE}"> &#10022;</tspan>'
        if g in pivot_gens:
            marks += '<tspan fill="#2e6e63"> &#10227;</tspan>'
        svg.append(f'<text x="{margin - 50}" y="{margin + gi * ystep + 4}"'
                   f' font-size="11" fill="#9b998c">g{g}{marks}</text>')

    # legend, above the first generation row; the elite swatch is dashed
    # like the carry-over lines it stands for. Wrapped in a group so the
    # html page can replace it with its interactive legend.
    svg.append('<g class="svg-legend">')
    lx, ly = margin, 24
    for name, col in OPERATOR_COLORS.items():
        label = "elite carry-over" if name == "elite" else name
        dash = ' stroke-dasharray="3,3"' if name == "elite" else ""
        svg.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 16}" y2="{ly}"'
                   f' stroke="{col}" stroke-width="2"{dash}/>')
        svg.append(f'<text x="{lx + 20}" y="{ly + 4}" font-size="10"'
                   f' fill="#6b6a60">{label}</text>')
        lx += 30 + 7 * len(label)
    svg.append(f'<circle cx="{lx + 8}" cy="{ly}" r="5.5" fill="none"'
               f' stroke="#8c2f1f" stroke-width="1.3"/>')
    svg.append(f'<text x="{lx + 20}" y="{ly + 4}" font-size="10"'
               f' fill="#6b6a60">best so far</text>')
    svg.append("</g>")
    svg.append("</svg>")
    out = results_dir / "lineage.svg"
    out.write_text("\n".join(svg))
    return out
