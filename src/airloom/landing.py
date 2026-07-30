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
/* build it: the champion's flat part templates, drawn to one scale */
#tpl-row{display:flex;gap:40px 48px;margin:30px auto 0;flex-wrap:wrap;
  justify-content:center;align-items:flex-end;max-width:1040px}
#tpl-row figure{margin:0;text-align:center}
#tpl-row img{display:block;margin:0 auto 10px;max-width:100%}
#tpl-row figcaption{font-size:13.5px;color:var(--muted);line-height:1.55}
#tpl-row figcaption b{color:var(--ink);font-weight:600}
#tpl-row .dim{font-variant-numeric:lining-nums tabular-nums}
#tpl-row .bnote{font-style:italic;color:var(--faint)}
.buildfoot{text-align:center;font-size:14.5px;font-style:italic;
  color:var(--muted);margin:26px auto 0;max-width:760px;line-height:1.7}
/* the replay panel */
.panel{margin:22px 0 0;border-top:1px solid var(--rule);padding-top:18px}
.panel h3{font:600 12px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
  margin:0 0 4px}
.panel p{font-size:14.5px;font-style:italic;color:var(--muted);
  line-height:1.65;margin:0 0 10px;max-width:820px}
/* a quiet border marks where the wheel drives the model, not the page */
.panel canvas{width:100%;height:420px;display:block;cursor:grab;
  background:var(--paper);border:1px solid var(--rule);border-radius:6px;
  touch-action:none}
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
/* pressure row: same six-tile layout as the performance row above, but
   a visually distinct section -- deliberately never mixed with the
   streamline tiles */
#pressure-row{display:flex;gap:12px;margin-top:22px;flex-wrap:wrap;
  justify-content:center;width:100vw;margin-left:calc(50% - 50vw);
  padding:0 28px}
#pressure-row .pf{flex:1;min-width:150px;margin:0}
#pressure-row canvas{width:100%;aspect-ratio:1/1;display:block;
  cursor:grab;border:1px solid var(--rule);border-radius:6px;
  touch-action:none}
#pressure-row figcaption{font:12px var(--mono);color:var(--faint);
  text-align:center;margin-top:4px}
#cp-legend{display:flex;align-items:center;justify-content:center;
  gap:10px;margin:16px auto 0;font:12px var(--mono);color:var(--faint)}
#cp-legend .bar{width:180px;height:10px;border-radius:5px;
  background:linear-gradient(to right,
    rgb(26,64,166) 0%,rgb(242,242,235) 50%,rgb(191,20,20) 100%)}
/* streamline speed colormap: sequential viridis (dark purple = slow,
   yellow = fast) -- unlike pressure, speed has no meaningful zero to
   diverge around, so this is a perceptually-uniform sequential map
   instead of #cp-legend's diverging one (see speedColor() in
   viewer.js); stops match its 5-color viridis approximation */
#flow-legend{display:flex;align-items:center;justify-content:center;
  gap:10px;margin:16px auto 0;font:12px var(--mono);color:var(--faint)}
#flow-legend .bar{width:180px;height:10px;border-radius:5px;
  background:linear-gradient(to right,
    rgb(68,1,84) 0%,rgb(65,68,135) 25%,rgb(42,120,142) 50%,
    rgb(34,168,132) 75%,rgb(253,231,37) 100%)}
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

// ---- scenario rows: the champion flying every weather scenario at
// once, one row for streamlines and a SEPARATE row for surface
// pressure -- same telemetry-driven pose math, own camera state and
// own data per row, so neither leaks into the other. All the mini
// views within a row share ONE camera state, so orbiting any box
// orbits the rest of that row; each poses the model from its own
// telemetry. WebGL contexts are a scarce, capped resource on mobile
// browsers, so a row mounts its contexts only while it (plus a margin)
// is on screen and releases them the moment it scrolls well clear --
// same discipline AL.lazySection gives every section on this page.
// Each box only ever needs the CHAMPION's own mesh + its own scenario's
// telemetry, so rows never wait on (or get delayed by) the lineage
// chain the replay/trail sections below fetch.
function startScenarioRow(rowId,mode){
  var row=document.getElementById(rowId);
  if(!row)return;
  var pst=null,views=null,raf=null,on=false,pending=false,last=null;
  function lerp(d,ch,f0,i,j){return d[ch][i]*(1-f0)+d[ch][j]*f0}
  function tick(ts){
    raf=requestAnimationFrame(tick);
    if(!on||!views)return; // parked offscreen, or contexts torn down
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
      var hx0=d.x[i1]-d.x[i0],hy0=d.y[i1]-d.y[i0],hm=Math.hypot(hx0,hy0);
      // the out-and-back mission reverses ground-track heading by
      // exactly 180 degrees at the turnaround (and again at the loop
      // restart) -- a straight-line reciprocating path, not a curve, so
      // the raw position-derivative heading flips sign in a single
      // sample. Copying that in directly read as a sudden flip with no
      // visible cause. Slew-limit the heading ANGLE instead of the raw
      // vector, so a reversal reads as a fast continuous turn.
      if(hm>=1e-4){
        var hxN=hx0/hm,hyN=hy0/hm;
        var curAng=Math.atan2(w.hy||0,w.hx||1),tgtAng=Math.atan2(hyN,hxN);
        var dAng=((tgtAng-curAng+Math.PI)%(2*Math.PI)+2*Math.PI)%(2*Math.PI)-Math.PI;
        var maxStep=dt*10; // rad/s turn-rate cap: fast but continuous
        dAng=Math.max(-maxStep,Math.min(maxStep,dAng));
        var newAng=curAng+dAng;
        w.hx=Math.cos(newAng);w.hy=Math.sin(newAng);
      }
      var hx=w.hx||1,hy=w.hy||0;
      var dot=hx*tx+hy*ty;
      var bx=[hx-dot*tx,hy-dot*ty,-dot*tz];
      var bm=Math.hypot(bx[0],bx[1],bx[2])||1;
      bx=[bx[0]/bm,bx[1]/bm,bx[2]/bm];
      var by=[ty*bx[2]-tz*bx[1],tz*bx[0]-tx*bx[2],tx*bx[1]-ty*bx[0]];
      w.v.modelR=[bx[0],bx[1],bx[2],by[0],by[1],by[2],tx,ty,tz];
      w.th+=lerp(d,"rpm",f0,i,j)*0.0035*dt;
      w.v.setPropAngle(w.th);
      var wv=[lerp(d,"wx",f0,i,j),lerp(d,"wy",f0,i,j),
              lerp(d,"wz",f0,i,j)];
      // the wind channel / pressure repaint is what tells the boxes
      // in a row apart
      if(mode==="flow")w.v.windUpdate(wv,dt);
      else w.v.pressureUpdate(wv,dt);
    });
    pst.redraw(); // one shared state: draws every box in the row
  }
  function markFailed(w){ // context lost well AFTER creation (GPU/OS
    // pressure, another context stealing the budget) -- w.v is already
    // dead at this point, just stop touching it and show our own
    // fallback instead of whatever the browser would otherwise paint
    w.fig.classList.remove("al-loading");
    w.fig.classList.add("al-failed");
    if(views){var idx=views.indexOf(w);if(idx>=0)views.splice(idx,1)}
  }
  function mount(){
    if(views||pending)return;
    var boxes=[].slice.call(row.querySelectorAll("canvas"));
    if(!boxes.length)return;
    pending=true;
    pst=AL.makeState(0.35); // low chase-cam pitch, shared by the row
    // per-tile state, not row-level: a WebGL context is a per-canvas
    // resource (mobile browsers cap the total available), so one tile
    // failing to get one must never block or hide the other five, and
    // every tile gets its OWN spinner the instant we start on it rather
    // than only once the whole row's fetch has already succeeded.
    var vs=[];
    boxes.forEach(function(cv){
      var fig=cv.closest("figure")||cv.parentNode;
      fig.classList.add("al-loading");
      var fresh=AL.freshCanvas(cv);
      var w={scen:fresh.dataset.scen,fig:fig,t:0,th:0,hx:1,hy:0};
      // antialiasing roughly doubles a context's GPU memory footprint;
      // up to a dozen of these can be live across both rows at once on
      // a small mobile GPU, and AA is barely visible at this tile size
      var v=AL.makeViewer(fresh,pst,{flowLines:mode==="flow"?30:0,
        antialias:false,onLost:function(){markFailed(w)}});
      if(!v){ // context budget exhausted or WebGL unavailable on this tile
        fig.classList.remove("al-loading");
        fig.classList.add("al-failed");
        return;
      }
      w.v=v;vs.push(w);
    });
    pending=false;
    if(!vs.length)return; // every tile in the row failed to get a context
    if(!on){vs.forEach(function(w){w.v.destroy();w.fig.classList.remove("al-loading")});return} // scrolled away mid-mount
    views=vs;
    views.forEach(function(w){
      // the champion's own mesh, not just this tile's telemetry, has to
      // actually be in hand before .load() can draw anything -- it used
      // to arrive for free because the (slow) lineage-chain fetch this
      // row no longer waits on gave it plenty of time in the background.
      // Race it explicitly instead of assuming someone else fetched it.
      Promise.all([AL.ensureFlight(CH,w.scen),AL.ensureBlobs(["m-"+CH])])
      .then(function(){
        if(!views||views.indexOf(w)<0)return; // torn down meanwhile
        w.v.load([{id:"m-"+CH,propSpin:true,mono:true}]);
        if(mode==="flow"){
          // real CFD streamlines where solved; analytic field otherwise.
          // Anchored at the trace's mean attitude: the wind stays
          // world-fixed while the craft oscillates within it.
          AL.ensureFlowLines(CH,w.scen).then(function(d){
            if(!views||views.indexOf(w)<0)return; // torn down meanwhile
            var fd=AL.FLIGHTS[CH+"|"+w.scen];
            w.v.setFlowLines(d,d&&fd?AL.meanPose(fd):null)});
        }else{
          // surface pressure (Pa), blended live between the nearest
          // solved attitudes as the craft's own AoA changes -- see
          // pressureUpdate in viewer.js
          AL.ensurePressure(CH,w.scen).then(function(d){
            if(!views||views.indexOf(w)<0)return;
            w.v.setPressureData(d)});
        }
        w.fig.classList.remove("al-loading"); // this tile's own data is in
        pst.redraw();
      });
    });
    last=null;
    raf=requestAnimationFrame(tick);
  }
  function unmount(){
    if(raf){cancelAnimationFrame(raf);raf=null}
    if(views)views.forEach(function(w){
      w.v.destroy();w.fig.classList.remove("al-loading");
    });
    views=null;pst=null;
  }
  AL.lazySection(row,function(){on=true;mount()},
                     function(){on=false;unmount()});
}
startScenarioRow("perf-row","flow");
startScenarioRow("pressure-row","pressure");

// ---- lineage chain (replay + trail): the champion's FULL ancestry can
// be large on a long run (every steppable ancestor's mesh, tens of MB
// combined) -- fetch it once, lazily, only once the reader actually
// scrolls toward one of these two sections, never on page load.
var rep=AL.makeReplay({canvas:document.getElementById("replay-canvas"),
  timeline:document.getElementById("replay-tl"),
  label:document.getElementById("replay-lab")});
var chainPromise=null,opened=false,openFailed=false;
var replayPanelEl=document.getElementById("replay-panel"),
    trailPanelEl=document.getElementById("trail-panel");
function ensureChain(){
  if(!chainPromise){
    // whichever of the two sections scrolled into view first triggers
    // this; show BOTH panels' spinners since either may be on screen
    if(replayPanelEl)replayPanelEl.classList.add("al-loading");
    if(trailPanelEl)trailPanelEl.classList.add("al-loading");
    var need=AL.walkChainFor(CH).steps.map(function(h){return "m-"+h});
    chainPromise=AL.ensureBlobs(need);
  }
  return chainPromise;
}
function openOnce(){
  if(opened||openFailed)return Promise.resolve();
  return ensureChain().then(function(){
    if(replayPanelEl)replayPanelEl.classList.remove("al-loading");
    if(trailPanelEl)trailPanelEl.classList.remove("al-loading");
    if(openFailed||opened)return; // a second caller raced us here
    if(rep.open(CH)){
      opened=true;
      var redraw=function(){rep.redraw()};
      requestAnimationFrame(redraw);
      setTimeout(redraw,80);
      window.addEventListener("resize",redraw);
      // the timeline/label are built by open(); the GL context itself
      // is what each section below mounts/unmounts on its own schedule
      rep.closeViewer();
      if(rep.chain.length<=1&&trailPanelEl)trailPanelEl.style.display="none";
    }else{
      openFailed=true;
      if(replayPanelEl)replayPanelEl.style.display="none";
      if(trailPanelEl)trailPanelEl.style.display="none";
    }
  });
}
var replayPanel=document.getElementById("replay-panel");
AL.lazySection(replayPanel,
  function(){openOnce().then(function(){
    if(!opened)return;
    var ok=rep.reopenViewer(AL.freshCanvas(document.getElementById("replay-canvas")));
    replayPanel.classList.toggle("al-failed",!ok);
  })},
  function(){replayPanel.classList.remove("al-failed");if(opened)rep.closeViewer()});

// the lineage trail: same chain the replay opens, all steps
// superimposed at once instead of stepped through -- near-top-down
// pitch (1.2), same as the overlay's own "lineage trail" tab, since
// the plan shape is what reads best from above
var trailState=AL.makeState(1.2),trailV=null;
var trailPanel=document.getElementById("trail-panel");
AL.lazySection(trailPanel,
  function(){openOnce().then(function(){
    if(!opened||rep.chain.length<=1||trailV)return;
    var cv=document.getElementById("trail-canvas");
    if(!cv)return;
    trailV=AL.makeViewer(AL.freshCanvas(cv),trailState);
    trailPanel.classList.toggle("al-failed",!trailV);
    if(!trailV)return;
    trailV.load(AL.trailSpecs(rep.chain),rep.frame);
    requestAnimationFrame(function(){trailState.redraw()});
  })},
  function(){trailPanel.classList.remove("al-failed");
             if(trailV){trailV.destroy();trailV=null}});
window.addEventListener("resize",function(){trailState.redraw()});
})();
"""


SITE_URL = "https://alexisrondeau.me/airloom/"


def write_share_card(results_dir: Path, store, run_id: str,
                     cands: dict, champ_hash: str,
                     improvement: float | None, champ_fit: float,
                     n_gens: int) -> Path | None:
    """share.png (1200x630): a Tufte-style small-multiples plate --
    the run AS a grid of real candidates, one discreet caption line.
    Setters invert to ink, claude-designed frames carry the purple
    ring, the champion the accent ring."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    import math as _math

    paper, ink = (255, 255, 248), (17, 17, 17)
    muted, accent = (107, 106, 96), (140, 47, 31)
    rule, claude = (222, 218, 202), (106, 74, 138)

    def font(size: int, face: int = 0):
        for path, idx in (("/System/Library/Fonts/Palatino.ttc", face),
                          ("/System/Library/Fonts/Supplemental/Georgia.ttf",
                           0)):
            try:
                return ImageFont.truetype(path, size, index=idx)
            except OSError:
                continue
        return ImageFont.load_default()

    W, H = 1200, 630
    im = Image.new("RGB", (W, H), paper)
    dr = ImageDraw.Draw(im)

    ordered, seen = [], set()
    setters, best = set(), _math.inf
    for c in store.candidates_in_eval_order(run_id):
        h = c["hash"]
        if h in seen or not c["png_path"]:
            continue
        seen.add(h)
        ordered.append(h)
        f = store.fitness_of(c)
        if _math.isfinite(f) and f < best:
            best = f
            setters.add(h)

    COLS, ROWS, gap = 14, 6, 5
    margin, cap_h = 26, 44
    cell = min((W - 2 * margin - (COLS - 1) * gap) // COLS,
               (H - 2 * margin - cap_h - (ROWS - 1) * gap) // ROWS)
    gw = COLS * cell + (COLS - 1) * gap
    gh = ROWS * cell + (ROWS - 1) * gap
    gx0 = (W - gw) // 2
    gy0 = (H - cap_h - gh) // 2
    n_cells = COLS * ROWS

    def sample(pool, k):
        if len(pool) <= k:
            return list(pool)
        return [pool[int(i * len(pool) / k)] for i in range(k)]

    setter_pick = sample([h for h in ordered
                          if h in setters and h != champ_hash], 10)
    claude_pick = sample([h for h in ordered
                          if cands[h]["operator"] == "designer"
                          and h not in setters and h != champ_hash], 6)
    forced = set(setter_pick) | set(claude_pick) | {champ_hash}
    rest = [h for h in ordered if h not in forced]
    fill = sample(rest, n_cells - len(forced))
    order_idx = {h: i for i, h in enumerate(ordered)}
    sel = sorted(forced | set(fill), key=lambda h: order_idx[h])
    sel = sel[:n_cells]

    for i, h in enumerate(sel):
        r, c9 = divmod(i, COLS)
        x = gx0 + c9 * (cell + gap)
        y = gy0 + r * (cell + gap)
        try:
            th = Image.open(cands[h]["png_path"]).convert("RGB")
            th.thumbnail((cell, cell - 8))
            im.paste(th, (x + (cell - th.width) // 2,
                          y + (cell - 8 - th.height) // 2))
        except OSError:
            continue
        # data-ink only: a small dot beneath marks the special frames
        mark = (accent if h == champ_hash
                else ink if h in setters
                else claude if cands[h]["operator"] == "designer"
                else None)
        if mark:
            mx, my = x + cell // 2, y + cell - 4
            dr.ellipse([mx - 3, my - 3, mx + 3, my + 3], fill=mark)

    # one discreet caption line, the Tufte way
    cap_y = gy0 + gh + 16
    cap = ("\u201cThe snuggle is real\u201d \u2014 "
           f"{len(cands)} quadcopter frames, evolved"
           + (f" {improvement:.0f}% more efficient"
              if improvement is not None else "")
           + " \u00b7 alexisrondeau.me/airloom")
    fnt = font(23, 1)
    tw = dr.textlength(cap, font=fnt)
    dr.text(((W - tw) / 2, cap_y), cap, font=fnt, fill=muted)

    out = results_dir / "share.png"
    im.save(out)
    return out


INTRO_TITLE = ("&ldquo;The snuggle is real&rdquo;: &mdash; evolving "
               "quadcopter frame geometry for Wh/km, with Claude as an "
               "occasional co-designer")

INTRO_TEXT = (
    "I let a genetic algorithm loose on the geometry of a 7-inch "
    "quadcopter frame &mdash; the real, "
    '<a href="https://github.com/tbs-trappy/source_one">open-source '
    "Source One V6</a> plate drawings, morphed by fourteen genes and "
    "flown through six simulated weather scenarios, with Claude sitting in "
    "every few generations to propose designs from the run&rsquo;s own "
    "telemetry.")


def _build_section_html(results_dir: Path, champ) -> list[str]:
    """The "build it" card: the champion's five flat templates drawn to
    one shared scale (the true-scale SVGs the parts export writes), each
    with its dimensions, quantity and STL/SVG download links. Renders
    nothing if the parts export (parts.json) is missing."""
    if not champ["png_path"]:
        return []
    pdir = Path(champ["png_path"]).parent / f"{champ['hash']}.parts"
    try:
        spec = json.loads((pdir / "parts.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    plist = [p for p in spec.get("parts", []) if p.get("svg")]
    if not plist:
        return []
    # one shared scale: the longest part sets px-per-mm, capped for print
    longest = max(p["length_mm"] for p in plist)
    k = min(1.8, 500.0 / longest)
    figs = []
    for p in plist:
        rel_svg = _rel(results_dir, str(pdir / p["svg"]))
        rel_stl = _rel(results_dir, str(pdir / p["file"]))
        w_px = (p["length_mm"] + 4.0) * k  # + the SVG's 2 mm margins
        note = (f'<br><span class="bnote">{html.escape(p["note"])}</span>'
                if p.get("note") else "")
        figs.append(
            f'<figure><img src="{rel_svg}" alt="{html.escape(p["label"])} '
            f'outline" style="width:{w_px:.0f}px" decoding="async">'
            f'<figcaption><b>{p["qty"]}&times; {html.escape(p["label"])}'
            f'</b> &middot; <span class="dim">{p["length_mm"]:g}&times;'
            f'{p["width_mm"]:g}&thinsp;mm</span> &middot; '
            f'<a href="{rel_stl}" download>STL</a> / '
            f'<a href="{rel_svg}" download>SVG</a>{note}</figcaption>'
            f"</figure>")
    foot = (f"Print or cut every part in <b>"
            f'{html.escape(spec["material_label"])}</b> &mdash; arms '
            f"{spec['arm_thickness_mm']}&thinsp;mm thick, deck plates "
            f"{spec['plate_thickness_mm']}&thinsp;mm. The STLs are "
            "already extruded to final thickness; the SVGs are "
            "true-scale (mm) for CNC or laser cutting. Standoffs, "
            "screws and electronics are the stock Source One kit&rsquo;s.")
    if spec.get("clamp_holes_recut"):
        foot += (" The arm-clamp bolt holes in the main and mid plates "
                 "are re-cut where the swept arms actually sit, so the "
                 "arms bolt straight on.")
    if spec.get("assembled"):
        rel_asm = _rel(results_dir, str(pdir / spec["assembled"]))
        foot += (f' Also: the <a href="{rel_asm}" download>assembled '
                 "frame</a> as one solid, for reference and scale checks")
        rel_readme = _rel(results_dir, str(pdir / "README.txt"))
        if (pdir / "README.txt").exists():
            foot += (f', and a <a href="{rel_readme}" download>build '
                     "README</a>")
        foot += "."
    return [
        "<h2>build it: the champion as five flat templates</h2>",
        '<p class="sub">the exact parts the champion scored with, laid '
        "flat in print/cut orientation and drawn to one shared scale "
        "&mdash; bolt holes, lightening cutouts and all.</p>",
        f'<div id="tpl-row">{"".join(figs)}</div>',
        f'<p class="buildfoot">{foot}</p>']


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

    # social cards: dynamic copy + a share image rebuilt per champion
    champ_png_path = (cands[champ_hash]["png_path"]
                      if champ_hash and cands[champ_hash]["png_path"]
                      else None)
    improvement_early = ((base_fit - champ_fit) / base_fit * 100
                         if champ_hash is not None
                         and math.isfinite(base_fit) and base_fit > 0
                         else None)
    if champ_hash is not None:
        write_share_card(results_dir, store, run_id, cands, champ_hash,
                         improvement_early, champ_fit, n_gens)
    og_title = ("\u201cThe snuggle is real\u201d \u2014 evolving "
                "quadcopter frame geometry for Wh/km")
    og_desc = ("A genetic algorithm with Claude as an occasional "
               "co-designer bred a 7-inch quad frame"
               + (f" {improvement_early:.0f}% more efficient"
                  if improvement_early is not None else "")
               + " across six simulated weather scenarios. Every "
               "candidate explorable in 3D, with real OpenFOAM "
               "streamlines. Free software, GPLv3.")
    social_meta = [
        f'<meta name="description" content="{og_desc}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Airloom">',
        f'<meta property="og:title" content="{og_title}">',
        f'<meta property="og:description" content="{og_desc}">',
        f'<meta property="og:url" content="{SITE_URL}">',
        f'<meta property="og:image" content="{SITE_URL}share.png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{og_title}">',
        f'<meta name="twitter:description" content="{og_desc}">',
        f'<meta name="twitter:image" content="{SITE_URL}share.png">',
    ]

    parts = ["<!doctype html>",
             '<meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,'
             'initial-scale=1">',
             "<title>Airloom &mdash; an evolved drone frame</title>",
             *social_meta,
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
        "<span>frame mass</span></div>"]
    base_mass = cands[base_hash]["frame_mass"] if base_hash else None
    mass_saving = ((base_mass - champ["frame_mass"]) / base_mass * 100
                   if base_mass and champ["frame_mass"] else None)
    if mass_saving is not None:
        parts.append(
            f'<div class="stat"><b><span class="up">'
            f"{mass_saving:.0f}%</span></b>"
            "<span>lighter than the baseline</span></div>")
    else:
        parts.append(
            f'<div class="stat"><b>{len(cands)}</b>'
            "<span>candidates evaluated</span></div>")
    parts.append("</div>")

    # the champion's full detail card -- the same component the research
    # log renders for every candidate; the shared overlay embedded below
    # makes its controls work right here on the landing
    viewer_hashes = {h for h in (champ_hash, base_hash)
                     if h and _mesh_js_for(results_dir, cands[h]["png_path"])}
    flight_src: dict[str, dict[str, str]] = {}
    flow_src: dict[str, dict[str, str]] = {}
    # surface-pressure (Pa) payloads, kept in their own dict/data-attribute
    # so the pressure tiles never share state with the streamline viewers
    pressure_src: dict[str, dict[str, str]] = {}
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
        pressures = {p.name.split(".")[1]: _rel(results_dir, str(p))
                    for p in sorted(fdir.glob(f"{fh}.*.pressure.js"))}
        if pressures:
            pressure_src[fh] = pressures
    parts.append(candidate_card_html(
        store, run_id, results_dir, cands, champ_hash,
        viewer_hashes=viewer_hashes,
        flight_src=flight_src,
        setter_hashes=set(), best_hash=champ_hash,
        baseline_hash=base_hash, baseline_fit=base_fit,
        href_base="log.html"))

    # performance + pressure: every scored flight replayed side by side
    # twice, once as streamlines and once as surface pressure -- one
    # intro paragraph covering both, two 6-tile rows underneath. Kept as
    # separate row ids/states/cameras internally (the streamline and
    # pressure viewers never share data), just presented as one section.
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
            '<p class="sub">the champion&rsquo;s actual scored flights, '
            "replayed from simulation telemetry. Top row: airflow "
            "streamlines colored by speed (dark purple slow, yellow "
            "fast). Bottom row: surface pressure in pascals (deep red "
            "is high-pressure stagnation, deep blue is suction). Drag "
            "any box and the whole row orbits together; the <b>view "
            "candidate performance</b> button above opens the "
            "full-screen replay with live telemetry.</p>",
            f'<div id="perf-row">{boxes}</div>',
            '<div id="flow-legend"><span>slow</span>'
            '<span class="bar"></span><span>fast</span></div>']

    if pressure_src.get(champ_hash):
        pboxes = "".join(
            f'<figure class="pf"><canvas data-scen="{s}"></canvas>'
            f"<figcaption>{s.replace('_', ' ')}</figcaption></figure>"
            for s in flow_src.get(champ_hash, pressure_src[champ_hash]))
        parts += [
            f'<div id="pressure-row">{pboxes}</div>',
            '<div id="cp-legend"><span>suction</span>'
            '<span class="bar"></span><span>stagnation</span></div>']

    # the evolution: the whole lineage superimposed, then the replay of
    # the champion's own line -- the trail comes first (the net shape
    # change, all at once) so the step-by-step replay that follows reads
    # as "how it got there," not a repeat of the same information
    parts += [
        f"<h2>the lineage trail: {n_gens} generations, superimposed</h2>",
        '<p class="sub">'
        f"every ancestor on the champion&rsquo;s line, from the baseline "
        "to the winner, drawn on top of each other &mdash; the winner "
        "solid, each ancestor a fainter gray ghost the further back it "
        "goes. Evolved parts only, so the shape change itself is what "
        "reads.</p>",
        '<div class="panel" id="trail-panel">'
        '<canvas id="trail-canvas"></canvas></div>',

        "<h2>watch it evolve: the same line, step by step</h2>",
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

    # build it: the champion's flat templates, the very end of the page
    parts += _build_section_html(results_dir, champ)


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
        '<script type="application/json" id="pressure-src">'
        f"{json.dumps(pressure_src, separators=(',', ':'))}</script>",
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
