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
h1{font-weight:400;font-size:60px;line-height:1.15;letter-spacing:-.01em;
  margin:0 0 22px;text-align:center}
h1 .hash{font:26px var(--mono);color:var(--muted)}
p.sub{text-align:center;font-style:italic;color:var(--muted);
  font-size:15.5px;line-height:1.7;margin:0 auto 8px;max-width:760px}
p.sub.lead{font-size:19px;max-width:880px}
h2{font-weight:400;font-size:24px;margin:64px 0 6px;text-align:center}
h2 .hash{font:400 21px var(--mono);color:var(--muted)}
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
/* a quiet border marks where the wheel drives the model, not the page */
.panel canvas{width:100%;height:420px;display:block;cursor:grab;
  background:var(--paper);border:1px solid var(--rule);border-radius:6px}
/* performance row: one small flight view per scenario, cameras shared;
   full-bleed -- the row breaks out of the column to browser width */
#perf-row{display:flex;gap:12px;margin-top:22px;flex-wrap:wrap;
  justify-content:center;width:100vw;margin-left:calc(50% - 50vw);
  padding:0 28px}
#perf-row .pf{flex:1;min-width:150px;margin:0}
#perf-row canvas{width:100%;aspect-ratio:1/1;display:block;cursor:grab;
  border:1px solid var(--rule);border-radius:6px;touch-action:none}
#perf-row figcaption{font:12px var(--mono);color:var(--faint);
  text-align:center;margin-top:4px}
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
    label:document.getElementById("replay-lab")});
  if(rep.open(CH)){
    var redraw=function(){rep.redraw()};
    requestAnimationFrame(redraw);
    setTimeout(redraw,80);
    window.addEventListener("resize",redraw);
  }else{
    var rp=document.getElementById("replay-panel");
    if(rp)rp.style.display="none";
  }
  // ---- performance row: the champion flying every scenario at once.
  // All the mini views share ONE camera state, so orbiting any box
  // orbits them all; each poses the model from its own telemetry.
  var boxes=[].slice.call(document.querySelectorAll("#perf-row canvas"));
  if(!boxes.length)return;
  var pst=AL.makeState(0.35); // low chase-cam pitch, shared by the row
  var views=[];
  boxes.forEach(function(cv){
    var v=AL.makeViewer(cv,pst,{flowLines:30});
    if(v)views.push({v:v,scen:cv.dataset.scen,t:0,th:0,hx:1,hy:0});
  });
  if(!views.length)return;
  Promise.all(views.map(function(w){return AL.ensureFlight(CH,w.scen)}))
  .then(function(){
    views.forEach(function(w){
      w.v.load([{id:"m-"+CH,propSpin:true,mono:true}]);
      // real CFD streamlines where solved; analytic field otherwise
      AL.ensureFlowLines(CH,w.scen).then(function(d){
        w.v.setFlowLines(d)});
    });
    var row=document.getElementById("perf-row"),on=true,last=null;
    if("IntersectionObserver" in window){
      new IntersectionObserver(function(es){
        es.forEach(function(en){on=en.isIntersecting;last=null});
      }).observe(row);
    }
    function lerp(d,ch,f0,i,j){return d[ch][i]*(1-f0)+d[ch][j]*f0}
    function tick(ts){
      requestAnimationFrame(tick);
      if(!on)return; // parked offscreen: no work
      if(last===null)last=ts;
      var dt=Math.min((ts-last)/1000,0.1);last=ts;
      views.forEach(function(w){
        var d=AL.FLIGHTS[CH+"|"+w.scen];
        if(!d)return;
        var n=d.x.length;
        w.t=(w.t+dt*8)%(n/d.hz); // 8x replay, looped per scenario
        var fx=Math.min(w.t*d.hz,n-1.001),i=Math.floor(fx),
            j=Math.min(i+1,n-1),f0=fx-i;
        // attitude: body z = thrust vector, body x follows the motion
        var tx=lerp(d,"tx",f0,i,j),ty=lerp(d,"ty",f0,i,j),
            tz=lerp(d,"tz",f0,i,j);
        var tm=Math.hypot(tx,ty,tz)||1;tx/=tm;ty/=tm;tz/=tm;
        var i0=Math.max(0,i-1),i1=Math.min(n-1,i+1);
        var hx=d.x[i1]-d.x[i0],hy=d.y[i1]-d.y[i0],hm=Math.hypot(hx,hy);
        if(hm<1e-4){hx=w.hx;hy=w.hy}else{hx/=hm;hy/=hm;w.hx=hx;w.hy=hy}
        var dot=hx*tx+hy*ty;
        var bx=[hx-dot*tx,hy-dot*ty,-dot*tz];
        var bm=Math.hypot(bx[0],bx[1],bx[2])||1;
        bx=[bx[0]/bm,bx[1]/bm,bx[2]/bm];
        var by=[ty*bx[2]-tz*bx[1],tz*bx[0]-tx*bx[2],tx*bx[1]-ty*bx[0]];
        w.v.modelR=[bx[0],bx[1],bx[2],by[0],by[1],by[2],tx,ty,tz];
        w.th+=lerp(d,"rpm",f0,i,j)*0.0035*dt;
        w.v.setPropAngle(w.th);
        // the wind channel is what tells the six boxes apart
        w.v.windUpdate([lerp(d,"wx",f0,i,j),lerp(d,"wy",f0,i,j),
                        lerp(d,"wz",f0,i,j)],dt);
      });
      pst.redraw(); // one shared state: draws every box in the row
    }
    requestAnimationFrame(tick);
  });
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
              f'<p class="sub lead">{INTRO_TEXT}</p>']

    # the champion's own header, then headline stats and the full card
    n_scen = len(store.scenario_results_for(run_id, champ_hash))
    scen_word = {6: "six"}.get(n_scen, str(n_scen))
    if improvement is not None:
        parts.append("<h2>the bottom line: we evolved the champion to "
                     f"fly {improvement:.0f}% more efficiently (Wh/km) "
                     f"across {scen_word} weather scenarios</h2>")
    else:
        parts.append(f"<h2>the bottom line: we evolved a champion "
                     f"candidate across {n_gens} generations</h2>")
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
    flow_src: dict[str, dict[str, str]] = {}
    for fh in (champ_hash, base_hash):
        if not fh or not cands[fh]["png_path"]:
            continue
        fdir = Path(cands[fh]["png_path"]).parent
        scens = {p.name.split(".")[1]: _rel(results_dir, str(p))
                 for p in sorted(fdir.glob(f"{fh}.*.flight.js"))}
        if scens:
            flight_src[fh] = scens
        flows = {p.name.split(".")[1]: _rel(results_dir, str(p))
                 for p in sorted(fdir.glob(f"{fh}.*.flow.js"))}
        if flows:
            flow_src[fh] = flows
    parts.append(candidate_card_html(
        store, run_id, results_dir, cands, champ_hash,
        viewer_hashes=viewer_hashes,
        flight_src=flight_src,
        setter_hashes=set(), best_hash=champ_hash,
        baseline_hash=base_hash, baseline_fit=base_fit,
        href_base="log.html"))

    # performance: every scored flight replayed side by side, cameras
    # locked together (all the mini views share one orbit state)
    if flight_src.get(champ_hash):
        scen_ws = {s["scenario"]: s["wh_per_km"]
                   for s in store.scenario_results_for(run_id, champ_hash)}
        boxes = "".join(
            f'<figure class="pf"><canvas data-scen="{s}"></canvas>'
            f"<figcaption>{s.replace('_', ' ')}"
            + (f" &middot; {_fmt(scen_ws[s])} Wh/km"
               if scen_ws.get(s) is not None else "")
            + "</figcaption></figure>"
            for s in flight_src[champ_hash])
        n_scen = len(flight_src[champ_hash])
        parts += [
            f"<h2>performance: the champion flying all {n_scen} weather "
            "scenarios</h2>",
            '<p class="sub">the actual scored flights, replayed from '
            "simulation telemetry &mdash; attitude and rotor speed are "
            "what the simulator graded. Flow lines are OpenFOAM RANS "
            "streamlines at each scenario&rsquo;s mean relative wind "
            "where solved (rotors not modeled), an illustrative field "
            f"otherwise. Drag inside any box and all {n_scen} cameras "
            "orbit in unison; the <b>view candidate performance</b> "
            "button on the card above opens the full-screen replay "
            "with live telemetry.</p>",
            f'<div id="perf-row">{boxes}</div>']

    # the evolution: replay the champion's own line
    parts += [
        f"<h2>watch the champion evolve: {n_gens} generations, "
        "replayed step by step</h2>",
        '<p class="sub">'
        f"{len(cands)} candidate frames flew six weather scenarios "
        f"across {n_gens} generations, breeding lower-energy designs "
        "each round. This replay walks the champion&rsquo;s own line, "
        "from the baseline to the winner &mdash; the current step "
        "solid, the next in line a gray ghost. Press play or click a "
        "thumbnail.</p>",
        '<div class="panel" id="replay-panel">'
        '<div><span class="cap" id="replay-lab"></span></div>'
        '<canvas id="replay-canvas"></canvas>'
        '<div class="wtl" id="replay-tl"></div></div>']

    # the family tree, champion lineage lit -- the same component the
    # dedicated lineage page renders
    parts += [
        "<h2>the family tree: where the champion&rsquo;s bloodline "
        "runs through the whole run</h2>",
        '<p class="sub">every candidate of the run, newest generation '
        "at the top, in two lenses &mdash; performance on the left, "
        "breeding on the right &mdash; with the champion&rsquo;s full "
        "ancestry highlighted. Hover any node to inspect it, click to "
        "pin another lineage (esc releases); the "
        '<a href="lineage.html">family tree page</a> tells the whole '
        'story, and the <a href="log.html">research log</a> has every '
        "candidate in full.</p>",
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
        '<script type="application/json" id="flow-src">'
        f"{json.dumps(flow_src, separators=(',', ':'))}</script>",
        f"<script>var BASELINE={json.dumps(base_hash)};"
        f"var CHAMP={json.dumps(champ_hash)};"
        "window.NO_LIVE_RELOAD=true;</script>",
        REDIRECT_JS,
        '<script src="viewer.js"></script>',
        f"<script>{VIEWER_JS}</script>",
        f"<script>{LANDING_JS}</script>",
        "</div>",
        GH_RIBBON_HTML]

    out = results_dir / "index.html"
    out.write_text("\n".join(parts))
    return out
