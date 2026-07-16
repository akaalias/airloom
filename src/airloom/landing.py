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
from .gallery import (GH_RIBBON_HTML, NAV_CSS, TUFTE_TOKENS, _bottom_png_for,
                      _fmt, _mesh_js_for, _parts_legend_html, _rel, nav_html)

LANDING_CSS = TUFTE_TOKENS + NAV_CSS + """
.wrap{max-width:1080px;margin:0 auto;padding:40px 28px 96px}
h1{font-weight:400;font-size:38px;line-height:1.1;letter-spacing:-.01em;
  margin:0 0 8px;text-align:center}
h1 .hash{font:26px var(--mono);color:var(--muted)}
p.sub{text-align:center;font-style:italic;color:var(--muted);
  font-size:15.5px;line-height:1.7;margin:0 auto 8px;max-width:760px}
h2{font-weight:400;font-size:24px;margin:64px 0 6px;text-align:center}
/* hero: the champion, live */
.hero{position:relative;margin:26px 0 0}
.hero canvas{width:100%;height:520px;display:block;cursor:grab}
.hero .hint{position:absolute;right:6px;bottom:6px;
  font:italic 11.5px var(--serif);color:var(--faint);pointer-events:none}
.hero .lgd{justify-content:center;font-size:12.5px;gap:4px 14px}
/* headline stats strip */
.stats{display:flex;justify-content:center;gap:56px;flex-wrap:wrap;
  margin:26px 0 0;text-align:center}
.stats .stat b{display:block;font-size:30px;font-weight:600;
  font-variant-numeric:lining-nums tabular-nums;line-height:1.15}
.stats .stat span{font:600 11px var(--serif);
  font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.08em;color:var(--faint)}
.stats .stat b .up{color:#2e6e63}
/* the three how-we-got-here panels */
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
/* footer pointer into the process */
.more{margin:70px 0 0;border-top:1px solid var(--rule);padding-top:22px;
  text-align:center;font-size:15px;font-style:italic;color:var(--muted);
  line-height:1.8}
.baseline-figs{display:flex;justify-content:center;gap:40px;
  align-items:flex-end;flex-wrap:wrap;margin:18px 0 0}
.baseline-figs figure{margin:0;text-align:center;width:300px}
.baseline-figs img{width:100%;border-radius:6px;mix-blend-mode:multiply}
.baseline-figs figcaption{font:12px var(--mono);color:var(--faint);
  margin-top:4px}
.baseline-figs .arrow{font-size:30px;color:var(--faint);
  align-self:center;padding-bottom:40px}
"""

# the walk-timeline styles the shared replay component expects; kept in
# sync with the research log by copying the same class names, values
# authored once here for the landing's lighter layout
TIMELINE_CSS = """
.wtl{display:flex;gap:6px;overflow-x:auto;padding:8px 2px;margin-top:8px}
.wplay{flex:none;font:14px var(--serif);background:none;color:var(--muted);
  border:1px solid var(--rule);width:34px;cursor:pointer}
.wplay:hover{color:var(--ink);border-color:var(--ink)}
.wthumb{flex:none;width:74px;display:block;background:none;
  border:1px solid var(--rule);padding:2px;cursor:pointer}
.wthumb.off{opacity:.4;cursor:default}
.wthumb img{width:100%;display:block;mix-blend-mode:multiply;
  border-radius:3px}
.wthumb span{display:block;font:10.5px var(--mono);color:var(--faint);
  text-align:center}
.wthumb:hover{border-color:var(--muted)}
.wthumb.on{border:2px solid var(--ink);padding:1px}
.wthumb.on span{color:var(--ink);font-weight:700}
"""

LANDING_JS = r"""
(function(){
"use strict";
// old share links pointed at the gallery when it WAS index.html; hand
// them to the research log where the overlays live
if(/^#(ovl|perf|d)-/.test(location.hash)){
  location.replace("log.html"+location.hash);
  return;
}
var AL=window.AL,CH=window.CHAMP;
if(!AL||!CH)return;
var chain=AL.walkChainFor(CH).steps;
var need=["m-"+CH];
chain.forEach(function(h){need.push("m-"+h)});
AL.ensureBlobs(need).then(function(){
  var states=[];
  function view(id,pitch,specs,frame){
    var el=document.getElementById(id);
    if(!el)return null;
    var st=AL.makeState(pitch),v=AL.makeViewer(el,st);
    if(!v)return null;
    v.load(specs,frame||undefined);
    states.push(st);
    return st;
  }
  view("hero-canvas",undefined,[{id:"m-"+CH}]);
  if(AL.BASELINE&&AL.BASELINE!==CH)
    view("diff-canvas",1.2,[{id:"m-"+CH,evolved:true},
      {id:"m-"+AL.BASELINE,evolved:true,ghost:true}]);
  var rep=AL.makeReplay({canvas:document.getElementById("replay-canvas"),
    timeline:document.getElementById("replay-tl"),
    label:document.getElementById("replay-lab"),
    prev:document.getElementById("replay-prev"),
    next:document.getElementById("replay-next")});
  if(rep.open(CH)){
    states.push(rep.state);
    view("trail-canvas",1.2,AL.trailSpecs(rep.chain),rep.frame);
  }else{
    var rp=document.getElementById("replay-panel");
    if(rp)rp.style.display="none";
    var tp=document.getElementById("trail-panel");
    if(tp)tp.style.display="none";
  }
  function redraw(){states.forEach(function(s){s.redraw()})}
  requestAnimationFrame(redraw);
  setTimeout(redraw,80);
  window.addEventListener("resize",redraw);
});
})();
"""


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
             f"<style>{LANDING_CSS}{TIMELINE_CSS}</style>",
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

    # hero + stats
    parts += [
        "<h1>an evolved drone frame &mdash; "
        f'<span class="hash">{champ_hash}</span></h1>',
        '<p class="sub">the champion of an evolutionary design run: '
        f"{len(cands)} candidate frames flown through six weather "
        f"scenarios across {n_gens} generations, breeding lower-energy "
        "designs each round. This is the winner &mdash; drag it around; "
        "it is the real simulated geometry.</p>",
        '<div class="hero"><canvas id="hero-canvas"></canvas>'
        '<div class="hint">drag to rotate &middot; scroll to zoom &middot; '
        "double-click resets</div>"
        f"{_parts_legend_html()}</div>",
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

    # vs baseline stills
    if base_hash and base_hash != champ_hash:
        base = cands[base_hash]
        bimg = (_bottom_png_for(results_dir, base["png_path"])
                or _rel(results_dir, base["png_path"]))
        cimg = (_bottom_png_for(results_dir, champ["png_path"])
                or _rel(results_dir, champ["png_path"]))
        parts += [
            "<h2>the baseline vs the champion</h2>",
            '<p class="sub">left: the best design of generation 0, where '
            "the run started. Right: the champion evolution arrived at "
            f"&mdash; {_fmt(base_fit)} &rarr; {_fmt(champ_fit)} Wh/km "
            "across the same six weather scenarios.</p>",
            '<div class="baseline-figs">',
            f'<figure><img src="{html.escape(bimg)}" alt="{base_hash}" '
            'decoding="async">'
            f"<figcaption>baseline &middot; {base_hash} &middot; "
            f"{_fmt(base_fit)} Wh/km</figcaption></figure>",
            '<div class="arrow">&rarr;</div>',
            f'<figure><img src="{html.escape(cimg)}" alt="{champ_hash}" '
            'decoding="async">'
            f"<figcaption>champion &middot; {champ_hash} &middot; "
            f"{_fmt(champ_fit)} Wh/km</figcaption></figure>",
            "</div>"]

    # how we got here: replay, net change, trail (shared 3D components)
    parts += [
        "<h2>how we got here</h2>",
        '<p class="sub">the same interactive views the research log uses, '
        "focused on the champion&rsquo;s own ancestry.</p>",
        '<div class="panel" id="replay-panel">'
        "<h3>evolution replay</h3>"
        "<p>step generation by generation from the baseline to the "
        "champion; the current step is solid, the next in line a gray "
        "ghost. Press play, click a thumbnail, or step with the "
        "buttons.</p>"
        '<div><button class="wbtn" id="replay-prev">&#8249; older</button>'
        '<button class="wbtn" id="replay-next">newer &#8250;</button>'
        '<span class="cap" id="replay-lab"></span></div>'
        '<canvas id="replay-canvas"></canvas>'
        '<div class="wtl" id="replay-tl"></div></div>',
        '<div class="panel">'
        "<h3>net change</h3>"
        "<p>the champion&rsquo;s evolved parts (deck + arms) solid, the "
        "baseline&rsquo;s as a gray ghost, superimposed &mdash; the total "
        "geometric distance evolution covered. Fixed kit hidden.</p>"
        '<canvas id="diff-canvas"></canvas></div>',
        '<div class="panel" id="trail-panel">'
        "<h3>lineage trail</h3>"
        "<p>every ancestor ghosted at once, fainter the older it is "
        "&mdash; a motion trail of the whole lineage converging on the "
        "champion.</p>"
        '<canvas id="trail-canvas"></canvas></div>',
        '<p class="more">obsessed with the process too? the '
        '<a href="log.html">research log</a> has every candidate, every '
        "generation, flight replays in every weather scenario, and the "
        'full <a href="lineage.html">family tree</a>. terms live in the '
        '<a href="glossary.html">glossary</a>.</p>']

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

    parts += [
        '<script type="application/json" id="walk-meta">'
        f"{json.dumps(walk_meta, separators=(',', ':'))}</script>",
        '<script type="application/json" id="blob-src">'
        f"{json.dumps(blob_src, separators=(',', ':'))}</script>",
        f"<script>var BASELINE={json.dumps(base_hash)};"
        f"var CHAMP={json.dumps(champ_hash)};</script>",
        '<script src="viewer.js"></script>',
        f"<script>{LANDING_JS}</script>",
        "</div>",
        GH_RIBBON_HTML]

    out = results_dir / "index.html"
    out.write_text("\n".join(parts))
    return out
