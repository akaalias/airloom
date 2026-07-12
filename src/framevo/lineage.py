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
    "mutation": "#8c2f1f",
    "immigrant": "#8a6a1e",
    "elite": "#9b998c",
    "seed": "#b9b6a6",
    "cmaes": "#888888",
}


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
        lines.append(f'  "{r["hash"]}" [label="{label}", fillcolor="{color}",'
                     f' style="{style}", fontcolor={font}];')
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
.nd,.ed,.el,.bs{{transition:opacity .12s ease}}
.hit{{cursor:pointer}}
svg.focus .nd:not(.lit),svg.focus .ed:not(.lit),svg.focus .el:not(.lit),
svg.focus .bs:not(.lit){{opacity:.12}}
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
.ncard .hash{{font:13px var(--mono);color:var(--faint);margin-top:7px;word-break:break-all}}
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
</style>
<meta charset="utf-8">
<title>framevo family tree</title>
<div class="wrap">
<h1>family tree &mdash; run <code>{run_id}</code></h1>
<p class="sub">one row per generation, candidates ordered best&#8594;worst.
Filled nodes are births, shaded dark&thinsp;=&thinsp;better fitness; hollow
nodes are invalid. Dotted lines are elite carry-overs: the same candidate
surviving unchanged into the next generation, where it reappears as a small
node. Rust rings mark best-so-far improvements (the candidates labeled in
the gallery chart). Edge colors name the operator. Hover any node to see
the candidate and its full ancestry; click a node to pin the highlight
while you scroll (click again or press esc to release).
&middot; <a href="gallery.html">back to the gallery</a></p>
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
  svg.querySelectorAll(".nd,.bs").forEach(function(n){{
    n.classList.toggle("lit",!!set[n.dataset.h])}});
  svg.querySelectorAll(".ed").forEach(function(e){{
    e.classList.toggle("lit",!!set[e.dataset.c])}});
  svg.querySelectorAll(".el").forEach(function(e){{
    e.classList.toggle("lit",!!set[e.dataset.h])}});
  if(!c){{card.style.display="none";return}}
  var nAnc=Object.keys(set).length-1;
  var head;
  if(c.fit!=null){{ // same headline as the gallery detail block
    head='<div class="head">agg <b>'+c.fit.toFixed(3)+"</b>"
      +(c.mean!=null?" &middot; mean "+c.mean.toFixed(3):"")
      +(c.worst!=null?" &middot; worst "+c.worst.toFixed(3):"")
      +" Wh/km"
      +(c.mass?" &middot; frame "+c.mass.toFixed(1)+"&thinsp;g":"")
      +(c.mat?" &middot; "+esc(c.mat):"")
      +" &middot; born g"+c.g+" via "+esc(c.op)
      +(c.mut?" (mut "+c.mut+")":"")+"</div>";
  }}else{{
    head='<div class="head">born g'+c.g+" via "+esc(c.op)
      +(c.mat?" &middot; "+esc(c.mat):"")+"</div>"
      +'<div class="fail">'+esc(c.fail||"invalid")+"</div>";
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
  card.innerHTML=(c.png?'<img src="'+esc(c.png)+'" alt="">':"")
    +'<div class="hash">'+esc(h)+"</div>"
    +head+table
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
            if math.isfinite(fit):
                fill = _fitness_color(fit, lo, hi)
                stroke = "#6b6a60"
            else:
                fill = "none"  # hollow = invalid
                stroke = "#b9b6a6"
            head = (f"{h} gen{cand['generation_born'] if cand else g} "
                    f"{cand['operator'] if cand else ''} "
                    + (f"{fit:.3f}" if math.isfinite(fit)
                       else (cand["failure_reason"] or "invalid") if cand else ""))
            if cand is not None:  # full genome breakdown in the tooltip
                genes = describe_genome(json.loads(cand["genome_json"]),
                                        cand["material"])
                head += "\n" + "\n".join(f"{lab}: {val}" for lab, val in genes)
            title = html.escape(head)
            svg.append(f'<circle class="nd" data-h="{h}"'
                       f' cx="{x:.0f}" cy="{y:.0f}" r="{rr:.1f}"'
                       f' fill="{fill}" stroke="{stroke}" stroke-width="1.2">'
                       f'<title>{title}</title></circle>')
            if is_birth and h in best_hashes:  # rust ring = best-so-far
                svg.append(f'<circle class="bs" data-h="{h}"'
                           f' cx="{x:.0f}" cy="{y:.0f}" r="{r_node + 3.5:.1f}"'
                           f' fill="none" stroke="#8c2f1f" stroke-width="1.3"/>')
            # generous invisible hit target for hover on the html page
            svg.append(f'<circle class="hit" data-h="{h}"'
                       f' cx="{x:.0f}" cy="{y:.0f}" r="{max(rr + 5, 14):.1f}"'
                       f' fill="transparent" stroke="none"/>')
        # generation label
    for gi, g in enumerate(gens):
        svg.append(f'<text x="{margin - 44}" y="{margin + gi * ystep + 4}"'
                   f' font-size="11" fill="#9b998c">g{g}</text>')

    # legend, above the first generation row; the elite swatch is dashed
    # like the carry-over lines it stands for
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
    svg.append("</svg>")
    out = results_dir / "lineage.svg"
    out.write_text("\n".join(svg))
    return out
