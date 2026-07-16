"""The landing page -- index.html, the link you hand to people first.

It leads with the RESULT: the run champion spinning in live 3D, its
energy score, and the % improvement over the baseline (the gen-0
winner). A "how we got here" section reuses the shared 3D engine
(viewer.js, written by write_gallery) for the evolution replay, the
net-change superimposition, and the lineage trail. The full gallery
lives on as log.html -- the research log -- for anyone who wants the
whole process.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

from .dbstore import Store
from .gallery import (CARD_CSS, GH_RIBBON_HTML, LAZY_IMG_JS, NAV_CSS,
                      OVERLAY_CSS, TUFTE_TOKENS, VIEWER_JS, _fmt,
                      _mesh_js_for, _rel, candidate_card_html, nav_html,
                      overlay_html)
from .lineage import TREE_CSS, tree_section_html

LANDING_CSS = (TUFTE_TOKENS + NAV_CSS + CARD_CSS + OVERLAY_CSS
               + TREE_CSS + """
.wrap{max-width:1080px;margin:0 auto;padding:40px 28px 96px}
h1{font-weight:400;font-size:30px;line-height:1.3;letter-spacing:-.01em;
  margin:0 0 14px;text-align:center}
h1 .hash{font:26px var(--mono);color:var(--muted)}
p.sub{text-align:center;font-style:italic;color:var(--muted);
  font-size:15.5px;line-height:1.7;margin:0 auto 8px;max-width:760px}
h2{font-weight:400;font-size:24px;margin:64px 0 6px;text-align:center}
/* headline stats strip; the label rule targets DIRECT children only so
   the highlighted %-figure inside <b> keeps the big number size */
.stats{display:flex;justify-content:center;gap:56px;flex-wrap:wrap;
  margin:30px 0 8px;text-align:center}
.stats .stat b{display:block;font-size:30px;font-weight:600;
  font-variant-numeric:lining-nums tabular-nums;line-height:1.15}
.stats .stat>span{font:600 11px var(--serif);
  font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.08em;color:var(--faint)}
.stats .stat b .up{color:#2e6e63}
/* the replay panel */
.panel{margin:22px 0 0;border-top:1px solid var(--rule);padding-top:18px}
.panel h3{font:600 12px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
  margin:0 0 4px}
.panel p{font-size:14.5px;font-style:italic;color:var(--muted);
  line-height:1.65;margin:0 0 10px;max-width:820px}
.panel canvas{width:100%;height:420px;display:block;cursor:grab;
  background:var(--paper)}
.panel .cap{font:12px var(--mono);color:var(--faint);margin:6px 0 0;
  min-height:16px}
/* replay controls reuse the research log's visual language */
.wbtn{font:600 10.5px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  background:var(--paper);border:1px solid var(--rule);padding:4px 10px;
  cursor:pointer;margin-right:6px}
.wbtn:hover:not(:disabled){color:var(--ink);border-color:var(--ink)}
.wbtn:disabled{opacity:.35;cursor:default}
""")

# the landing's inline replay: the timeline docks inside the panel, so
# the overlay's fixed-chrome spacing is trimmed back to the flow
TIMELINE_TWEAKS_CSS = """
.panel .wtl{padding:8px 2px;margin-bottom:0;border-top:none}
"""

# share links for candidates the landing does not carry live in the
# research log; the champion's own hashes are handled by the shared
# overlay right here
REDIRECT_JS = (
    "<script>(function(){"
    "var m=location.hash.match(/^#(?:ovl|perf|d)-([0-9a-f]+)/);"
    'if(m&&m[1]!==CHAMP)location.replace("log.html"+location.hash);'
    "})()</script>")

LANDING_JS = r"""
(function(){
"use strict";
var AL=window.AL,CH=window.CHAMP;
if(!AL||!CH)return;
var need=AL.walkChainFor(CH).steps.map(function(h){return "m-"+h});
AL.ensureBlobs(need).then(function(){
  var rep=AL.makeReplay({canvas:document.getElementById("replay-canvas"),
    timeline:document.getElementById("replay-tl"),
    label:document.getElementById("replay-lab"),
    prev:document.getElementById("replay-prev"),
    next:document.getElementById("replay-next")});
  if(!rep.open(CH)){
    var rp=document.getElementById("replay-panel");
    if(rp)rp.style.display="none";
    return;
  }
  function redraw(){rep.redraw()}
  requestAnimationFrame(redraw);
  setTimeout(redraw,80);
  window.addEventListener("resize",redraw);
});
})();
"""


INTRO_TITLE = ("&ldquo;The snuggle is real&rdquo;: &mdash; evolving "
               "quadcopter frame geometry for Wh/km, with Claude as an "
               "occasional co-designer")

INTRO_TEXT = (
    "I let a genetic algorithm loose on the geometry of a 7-inch "
    "quadcopter frame &mdash; the real, GPLv3 Source One V6 plate "
    "drawings, morphed by twelve genes and flown through six simulated "
    "weather scenarios, with Claude sitting in every few generations to "
    "propose designs from the run&rsquo;s own telemetry. Every candidate "
    'ever flown is in the <a href="log.html">gallery</a>, failures '
    "included: click one to spin the 3D model, superimpose its whole "
    "lineage as ghosts, or replay its evolution generation by "
    'generation. Free software, <a href="https://github.com/akaalias/'
    'airloom">GPLv3</a>.')


def write_landing(store: Store, run_id: str, results_dir: Path) -> Path:
    """index.html: the result-first landing page. Fail-soft: with no
    valid candidates it still writes a page pointing at the log."""
    cands = {r["hash"]: r for r in store.candidates_for_run(run_id)}
    finite = [(h, store.fitness_of(r)) for h, r in cands.items()
              if math.isfinite(store.fitness_of(r))]
    champ_hash, champ_fit = (min(finite, key=lambda t: t[1])
                             if finite else (None, math.inf))
    gen0 = [(h, f) for h, f in finite if cands[h]["generation_born"] == 0]
    base_hash, base_fit = (min(gen0, key=lambda t: t[1])
                           if gen0 else (None, math.inf))
    gens = store.generations_with_population(run_id)
    n_gens = (max(gens) + 1) if gens else 0

    parts = ["<!doctype html>",
             '<meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,'
             'initial-scale=1">',
             "<title>Airloom &mdash; an evolved drone frame</title>",
             f"<style>{LANDING_CSS}{TIMELINE_TWEAKS_CSS}</style>",
             '<div class="wrap">',
             nav_html("the result")]

    if champ_hash is None:
        parts += ["<h1>Airloom</h1>",
                  '<p class="sub">no completed run yet &mdash; see the '
                  '<a href="log.html">research log</a>.</p>',
                  "</div>", GH_RIBBON_HTML]
        out = results_dir / "index.html"
        out.write_text("\n".join(parts))
        return out

    champ = cands[champ_hash]
    improvement = ((base_fit - champ_fit) / base_fit * 100
                   if math.isfinite(base_fit) and base_fit > 0 else None)
    mass = (f"{champ['frame_mass'] * 1e3:.1f}"
            if champ["frame_mass"] else "&mdash;")

    # intro: what this project is, for someone landing cold
    parts += [f"<h1>{INTRO_TITLE}</h1>",
              f'<p class="sub">{INTRO_TEXT}</p>']

    # headline stats, then the champion's full detail card
    parts += [
        '<div class="stats">',
        f'<div class="stat"><b>{_fmt(champ_fit)}</b>'
        "<span>Wh/km energy score</span></div>"]
    if improvement is not None:
        parts.append(
            f'<div class="stat"><b><span class="up">'
            f"{improvement:.1f}%</span></b>"
            "<span>better than the baseline</span></div>")
    parts += [
        f'<div class="stat"><b>{mass}&thinsp;g</b>'
        "<span>frame mass</span></div>",
        f'<div class="stat"><b>{len(cands)}</b>'
        "<span>candidates evaluated</span></div>",
        "</div>"]

    # the champion's full detail card -- the same component the research
    # log renders for every candidate; the shared overlay embedded below
    # makes its controls work right here on the landing
    viewer_hashes = {h for h in (champ_hash, base_hash)
                     if h and _mesh_js_for(results_dir, cands[h]["png_path"])}
    flight_src: dict[str, dict[str, str]] = {}
    for fh in (champ_hash, base_hash):
        if not fh or not cands[fh]["png_path"]:
            continue
        fdir = Path(cands[fh]["png_path"]).parent
        scens = {p.name.split(".")[1]: _rel(results_dir, str(p))
                 for p in sorted(fdir.glob(f"{fh}.*.flight.js"))}
        if scens:
            flight_src[fh] = scens
    parts.append(candidate_card_html(
        store, run_id, results_dir, cands, champ_hash,
        viewer_hashes=viewer_hashes,
        flight_src=flight_src,
        setter_hashes=set(), best_hash=champ_hash,
        baseline_hash=base_hash, baseline_fit=base_fit,
        href_base="log.html"))

    # the evolution: replay the champion's own line
    parts += [
        "<h2>the evolution</h2>",
        '<p class="sub">'
        f"{len(cands)} candidate frames flown through six weather "
        f"scenarios across {n_gens} generations, breeding lower-energy "
        "designs each round. Replay the champion&rsquo;s own line: step "
        "generation by generation from the baseline to the winner "
        "&mdash; the current step solid, the next in line a gray "
        "ghost. Press play, click a thumbnail, or step with the "
        "buttons.</p>",
        '<div class="panel" id="replay-panel">'
        '<div><button class="wbtn" id="replay-prev">&#8249; older</button>'
        '<button class="wbtn" id="replay-next">newer &#8250;</button>'
        '<span class="cap" id="replay-lab"></span></div>'
        '<canvas id="replay-canvas"></canvas>'
        '<div class="wtl" id="replay-tl"></div></div>']

    # the family tree, champion lineage lit -- the same component the
    # dedicated lineage page renders
    parts += [
        "<h2>the family tree</h2>",
        '<p class="sub">every candidate of the run in two lenses '
        "&mdash; performance on the left, breeding on the right &mdash; "
        "with the champion&rsquo;s full ancestry highlighted. Hover any "
        "node to inspect it, click to pin another lineage (esc "
        'releases); the <a href="lineage.html">family tree page</a> '
        "tells the whole story, and the "
        '<a href="log.html">research log</a> has every candidate in '
        "full.</p>",
        tree_section_html(store, run_id, results_dir, pin=champ_hash)]

    # data payloads for the shared engine: only the champion's ancestry
    walk_meta: dict[str, dict] = {}
    blob_src: dict[str, str] = {}
    seen: set[str] = set()
    stack = [champ_hash]
    if base_hash:
        stack.append(base_hash)
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in cands:
            continue
        seen.add(cur)
        c = cands[cur]
        if c["parent_a"]:
            stack.append(c["parent_a"])
        if c["parent_b"]:
            stack.append(c["parent_b"])
        fit = store.fitness_of(c)
        walk_meta[cur] = {"p": c["parent_a"], "q": c["parent_b"],
                          "g": c["generation_born"],
                          "f": f"{fit:.3f}" if math.isfinite(fit) else None,
                          "i": _rel(results_dir, c["png_path"])}
        src = _mesh_js_for(results_dir, c["png_path"])
        if src is not None:
            blob_src[f"m-{cur}"] = src

    # the SAME full-screen overlay the research log uses: the card's
    # thumbnail and buttons open it right here instead of navigating away
    parts += [
        overlay_html(),
        LAZY_IMG_JS,
        '<script type="application/json" id="walk-meta">'
        f"{json.dumps(walk_meta, separators=(',', ':'))}</script>",
        '<script type="application/json" id="blob-src">'
        f"{json.dumps(blob_src, separators=(',', ':'))}</script>",
        '<script type="application/json" id="flight-src">'
        f"{json.dumps(flight_src, separators=(',', ':'))}</script>",
        f"<script>var BASELINE={json.dumps(base_hash)};"
        f"var CHAMP={json.dumps(champ_hash)};</script>",
        REDIRECT_JS,
        '<script src="viewer.js"></script>',
        f"<script>{VIEWER_JS}</script>",
        f"<script>{LANDING_JS}</script>",
        "</div>",
        GH_RIBBON_HTML]

    out = results_dir / "index.html"
    out.write_text("\n".join(parts))
    return out
