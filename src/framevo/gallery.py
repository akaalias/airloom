"""Static result artifacts regenerated after every generation:

- gallery.html    self-refreshing, framework-free, opens via file://
                  (Tufte-style: cream paper, ink, one rust accent, hairlines)
- leaderboard.md  top 10 with all metrics
- convergence.png matplotlib fitness-vs-generation plot

The gallery carries a progress chart (every candidate in evaluation order,
best-so-far step line, invalid marks) and per-candidate detail blocks with an
interactive 3D viewer (vanilla canvas, drag to rotate, wheel to zoom) fed by
compact mesh blobs written at build time.
"""
from __future__ import annotations

import html
import json
import math
import time
from pathlib import Path

from .dbstore import Store

TUFTE_TOKENS = """
:root{
  --paper:#fffff8; --ink:#111111; --muted:#6b6a60; --faint:#9b998c;
  --rule:#d9d5c3; --rule-soft:#ece9da; --accent:#8c2f1f;
  --kept:#111111; --disc:#b9b6a6;
  --serif:"Palatino","Palatino Linotype","Book Antiqua","URW Palladio L",Georgia,serif;
  --mono:ui-monospace,"SF Mono",Menlo,monospace;
}
*{box-sizing:border-box}
html{background:var(--paper)}
body{margin:0;background:var(--paper);color:var(--ink);
  font:17px/1.55 var(--serif);font-feature-settings:"onum" 1,"liga" 1;
  -webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none;border-bottom:1px solid transparent}
a:hover{border-bottom-color:var(--accent)}
.num{font-variant-numeric:lining-nums tabular-nums}
.smallcaps{font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.06em;color:var(--muted)}
"""

CSS = TUFTE_TOKENS + """
.wrap{max-width:92vw;margin:0 auto;padding:40px 0 96px}
@media(max-width:1100px){.wrap{max-width:none;padding-left:28px;padding-right:28px}}
h1{font-weight:400;font-size:34px;line-height:1.12;letter-spacing:-.01em;margin:0 0 6px}
h1 code{font:400 26px var(--mono);color:var(--muted)}
.sub{font-size:15px;color:var(--muted);margin:0 0 4px}
.sub .updated{color:var(--faint);font-style:italic}
h2{font:600 13px/1.2 var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
  border-bottom:1px solid var(--rule);padding-bottom:6px;margin:44px 0 14px}
.legend{display:flex;flex-wrap:wrap;gap:18px;align-items:center;
  font-size:13.5px;color:var(--muted);margin:10px 0 0}
.legend .k{display:inline-flex;align-items:center;gap:7px}
.legend .dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.legend .bar{width:16px;height:0;border-top:2px solid var(--ink);display:inline-block}
.legend .x{color:var(--accent);font-weight:700}
.chart-card{border-top:1px solid var(--rule);padding:14px 0 0;margin-top:14px}
.chart-card svg{width:100%;height:auto;display:block}
.row{display:flex;flex-wrap:wrap;gap:14px}
.card{border:1px solid var(--rule);padding:10px 12px;width:190px;background:var(--paper)}
.card.best{border:1.5px solid var(--ink)}
.card.invalid{color:var(--muted)}
.card.invalid img{opacity:.55}
.card img{width:100%;height:auto;display:block;mix-blend-mode:multiply}
.card .hash{font:12px var(--mono);color:var(--faint);margin-top:4px}
.card .agg{font-size:19px;font-weight:700;margin-top:2px}
.card .agg .unit{font:600 10.5px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.06em;color:var(--faint)}
.card .fail{color:var(--accent);font-size:13px;font-style:italic;line-height:1.35;margin-top:4px}
table.sc{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
table.sc td{padding:1px 0;color:var(--muted);border:none}
table.sc td:last-child{text-align:right;color:var(--ink)}
.detail{display:flex;gap:26px;border-top:1px solid var(--rule);
  padding:22px 0 26px;margin:0}
.viewer{width:50%;min-width:320px;position:relative}
.viewer canvas,.viewer img{width:100%;aspect-ratio:4/3;display:block;
  cursor:grab;touch-action:none}
.viewer img{object-fit:contain}
.viewer .hint{position:absolute;left:2px;bottom:2px;font:italic 11.5px var(--serif);
  color:var(--faint);pointer-events:none}
.dmeta{flex:1;min-width:280px}
.dmeta .hash{font:14px var(--mono);color:var(--muted)}
.dmeta .headline{font-size:17px;margin:4px 0 10px}
.dmeta .headline b{font-size:21px}
table.dt{border-collapse:collapse;font-size:14px;margin-top:2px}
table.dt td,table.dt th{text-align:left;padding:3px 18px 3px 0;border-bottom:1px solid var(--rule-soft)}
table.dt th{font:600 11px/1.2 var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  border-bottom:1.5px solid var(--ink)}
table.dt td:nth-child(n+2){font-variant-numeric:lining-nums tabular-nums}
.parents{width:220px;flex-shrink:0}
.parents .lab{font:600 11px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.06em;color:var(--faint);margin-bottom:6px}
.parents figure{margin:0 0 10px}
.parents img{width:100%;mix-blend-mode:multiply}
.parents figcaption{font:12px var(--mono);color:var(--faint)}
"""

VIEWER_JS = r"""
(function(){
"use strict";
function b64bytes(s){var b=atob(s),a=new Uint8Array(b.length);
  for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a}
function initViewer(canvas){
  var blob=document.getElementById(canvas.dataset.mesh);
  if(!blob)return;
  var d=JSON.parse(blob.textContent);
  var V=new Float32Array(b64bytes(d.v).buffer);
  var F=d.i==="u16"?new Uint16Array(b64bytes(d.f).buffer)
                   :new Uint32Array(b64bytes(d.f).buffer);
  var cx=d.c[0],cy=d.c[1],cz=d.c[2],R=d.r||0.3;
  var nf=F.length/3;
  // per-face palette index (part colors: evolved vs fixed) with fallback
  var FC=d.fc?new Uint8Array(b64bytes(d.fc)):new Uint8Array(nf);
  var PAL=d.p&&d.p.length?d.p:[[138,151,168,1]];
  var yaw=-0.9,pitch=0.42,zoom=1.0;
  var dpr=window.devicePixelRatio||1;
  var order=new Array(nf),depth=new Float32Array(nf);
  function draw(){
    var w=canvas.clientWidth,h=canvas.clientHeight;
    if(canvas.width!==w*dpr){canvas.width=w*dpr;canvas.height=h*dpr}
    var g=canvas.getContext("2d");
    g.setTransform(dpr,0,0,dpr,0,0);
    g.fillStyle="#fffff8";g.fillRect(0,0,w,h);
    var cyaw=Math.cos(yaw),syaw=Math.sin(yaw),
        cpi=Math.cos(pitch),spi=Math.sin(pitch);
    // rows of the view matrix (yaw about z-up, then pitch)
    var r0x=cyaw,r0y=syaw,r0z=0,
        r1x=-syaw*spi,r1y=cyaw*spi,r1z=cpi,
        r2x=syaw*cpi,r2y=-cyaw*cpi,r2z=spi;
    var s=0.44*Math.min(w,h)/R*zoom,ox=w/2,oy=h/2;
    var n=V.length/3,px=new Float32Array(n),py=new Float32Array(n),pz=new Float32Array(n);
    for(var i=0;i<n;i++){
      var x=V[3*i]-cx,y=V[3*i+1]-cy,z=V[3*i+2]-cz;
      px[i]=ox+(r0x*x+r0y*y+r0z*z)*s;
      py[i]=oy-(r1x*x+r1y*y+r1z*z)*s;
      pz[i]=r2x*x+r2y*y+r2z*z;
    }
    for(var f=0;f<nf;f++){
      order[f]=f;
      depth[f]=pz[F[3*f]]+pz[F[3*f+1]]+pz[F[3*f+2]];
    }
    order.sort(function(a,b){return depth[a]-depth[b]});
    var lx=0.35,ly=0.48,lz=0.80;
    for(var k=0;k<nf;k++){
      var f2=order[k],a=F[3*f2],b=F[3*f2+1],c=F[3*f2+2];
      var ax=px[a],ay=py[a],bx=px[b],by=py[b],qx=px[c],qy=py[c];
      // screen-space normal z decides facing; shade from 3D normal
      var ux=bx-ax,uy=by-ay,vx=qx-ax,vy=qy-ay;
      if(ux*vy-uy*vx<=0)continue;
      var e1x=V[3*b]-V[3*a],e1y=V[3*b+1]-V[3*a+1],e1z=V[3*b+2]-V[3*a+2];
      var e2x=V[3*c]-V[3*a],e2y=V[3*c+1]-V[3*a+1],e2z=V[3*c+2]-V[3*a+2];
      var nx=e1y*e2z-e1z*e2y,ny=e1z*e2x-e1x*e2z,nz=e1x*e2y-e1y*e2x;
      var nl=Math.sqrt(nx*nx+ny*ny+nz*nz)||1;
      // rotate normal into view space for stable lighting
      var vnx=(r0x*nx+r0y*ny+r0z*nz)/nl,
          vny=(r1x*nx+r1y*ny+r1z*nz)/nl,
          vnz=(r2x*nx+r2y*ny+r2z*nz)/nl;
      var lambert=Math.abs(vnx*lx+vny*ly+vnz*lz);
      var sh=0.55+0.45*lambert;
      var pc=PAL[FC[f2]]||PAL[0];
      var rr=Math.round(pc[0]*sh+26),gg=Math.round(pc[1]*sh+26),
          bb2=Math.round(pc[2]*sh+26);
      g.fillStyle="rgba("+rr+","+gg+","+bb2+","+pc[3]+")";
      g.beginPath();g.moveTo(ax,ay);g.lineTo(bx,by);g.lineTo(qx,qy);
      g.closePath();g.fill();
    }
  }
  var dragging=false,lastX=0,lastY=0;
  canvas.addEventListener("pointerdown",function(e){
    dragging=true;lastX=e.clientX;lastY=e.clientY;
    canvas.setPointerCapture(e.pointerId);canvas.style.cursor="grabbing"});
  canvas.addEventListener("pointermove",function(e){
    if(!dragging)return;
    yaw+=(e.clientX-lastX)*0.011;
    pitch=Math.max(-1.5,Math.min(1.5,pitch+(e.clientY-lastY)*0.011));
    lastX=e.clientX;lastY=e.clientY;draw()});
  canvas.addEventListener("pointerup",function(){
    dragging=false;canvas.style.cursor="grab"});
  canvas.addEventListener("wheel",function(e){
    e.preventDefault();
    zoom=Math.max(0.3,Math.min(8,zoom*Math.exp(-e.deltaY*0.0016)));
    draw()},{passive:false});
  canvas.addEventListener("dblclick",function(){
    yaw=-0.9;pitch=0.42;zoom=1.0;draw()});
  draw();
  canvas.dataset.ready="1";
}
// lazy init: build a viewer once its canvas comes within 300px of the
// viewport (plain scroll sweep -- reliable under file:// and every browser)
var pending=Array.prototype.slice.call(document.querySelectorAll("canvas[data-mesh]"));
var sweeping=false;
function sweep(){
  sweeping=false;
  for(var i=pending.length-1;i>=0;i--){
    var c=pending[i],r=c.getBoundingClientRect();
    if(r.bottom>-300&&r.top<window.innerHeight+300){
      pending.splice(i,1);
      try{initViewer(c)}catch(err){}
    }
  }
}
function queueSweep(){
  if(!sweeping){sweeping=true;
    setTimeout(sweep,60)}
}
window.addEventListener("scroll",queueSweep,{passive:true});
window.addEventListener("resize",queueSweep);
window.addEventListener("hashchange",queueSweep);
sweep();
})();
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


def _mesh_blob_for(results_dir: Path, png_path: str | None) -> str | None:
    if not png_path:
        return None
    p = Path(png_path).with_suffix(".mesh.json")  # hash.png -> hash.mesh.json
    if p.exists():
        try:
            return p.read_text()
        except OSError:
            return None
    return None


# --------------------------------------------------------------- the chart --
def progress_chart_svg(store: Store, run_id: str) -> str:
    """Every candidate in evaluation order: discarded dots, a best-so-far
    step line with labeled improvements, invalid marks in a top strip, and
    generation boundaries as faint ticks. Tufte: thin rules, ink data."""
    cands = store.candidates_in_eval_order(run_id)
    if not cands:
        return ""
    fits = [store.fitness_of(r) for r in cands]
    finite = sorted(f for f in fits if math.isfinite(f))
    if not finite:
        return ""
    # conventional orientation, origin at 0/0: Wh/km grows upward from zero,
    # so "lower is better" reads as the best-so-far line stepping DOWN.
    # Cap the scale at the 95th percentile so one terrible candidate does not
    # squash the interesting region (clipped dots are drawn hollow at the top).
    hi = finite[min(len(finite) - 1, int(len(finite) * 0.95))]
    y_max = hi * 1.06
    if y_max <= 0:
        y_max = 1.0

    W, H = 1180, 400
    ml, mr, mt, mb = 64, 24, 40, 42
    pw, ph = W - ml - mr, H - mt - mb
    n = len(cands)

    def xat(i: int) -> float:
        return ml + (pw * (i + 0.5) / n)

    def yat(f: float) -> float:
        f = min(max(f, 0.0), y_max)
        return mt + ph * (1.0 - f / y_max)

    s: list[str] = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
                    f'font-family="Palatino,Georgia,serif">']
    # y gridlines at nice round steps, plus the zero baseline
    raw = y_max / 5.0
    mag = 10.0 ** math.floor(math.log10(raw))
    step = min((m for m in (1.0, 2.0, 2.5, 5.0, 10.0) if m * mag >= raw),
               default=10.0) * mag
    fv = 0.0
    while fv <= y_max + 1e-9:
        y = yat(fv)
        if fv == 0.0:  # the axis baseline: a firmer rule
            s.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W - mr}" y2="{y:.1f}" '
                     f'stroke="#9b998c" stroke-width="1.2"/>')
        else:
            s.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W - mr}" y2="{y:.1f}" '
                     f'stroke="#ece9da" stroke-width="1"/>')
        label = f"{fv:g}"
        s.append(f'<text x="{ml - 10}" y="{y + 4:.1f}" text-anchor="end" '
                 f'font-size="13" fill="#9b998c">{label}</text>')
        fv += step
    # generation boundaries
    prev_gen = None
    for i, c in enumerate(cands):
        if c["generation_born"] != prev_gen:
            prev_gen = c["generation_born"]
            x = ml + pw * i / n
            s.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt + ph}" '
                     f'stroke="#ece9da" stroke-width="1" stroke-dasharray="1,4"/>')
            s.append(f'<text x="{x + 3:.1f}" y="{mt + ph + 16}" font-size="11" '
                     f'fill="#9b998c">g{prev_gen}</text>')

    # invalid strip (design fails)
    y_inv = mt - 12
    # discarded dots + invalid marks
    for i, (c, f) in enumerate(zip(cands, fits)):
        x = xat(i)
        tip = html.escape(f"{c['hash']} g{c['generation_born']} {c['operator']}"
                          + (f" · {f:.3f}" if math.isfinite(f)
                             else f" · {c['failure_reason'] or 'invalid'}"))
        if math.isfinite(f):
            clipped = f > hi
            fill = "#b9b6a6" if not clipped else "none"
            stroke = ' stroke="#b9b6a6" stroke-width="1.2"' if clipped else ""
            s.append(f'<circle cx="{x:.1f}" cy="{yat(f):.1f}" r="3.4" '
                     f'fill="{fill}"{stroke}><title>{tip}</title></circle>')
        else:
            s.append(f'<text x="{x:.1f}" y="{y_inv}" text-anchor="middle" '
                     f'font-size="12" font-weight="700" fill="#8c2f1f">'
                     f'&#215;<title>{tip}</title></text>')

    # best-so-far step line with labeled improvements
    best = math.inf
    path: list[str] = []
    labels: list[str] = []
    flip = False
    for i, (c, f) in enumerate(zip(cands, fits)):
        if not math.isfinite(f) or f >= best:
            continue
        x, y = xat(i), yat(f)
        if not path:
            path.append(f"M{x:.1f},{y:.1f}")
        else:
            path.append(f"H{x:.1f}")
            path.append(f"V{y:.1f}")
        dy = -9 if not flip else 18
        flip = not flip
        labels.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.4" fill="#111111">'
                      f'<title>{html.escape(c["hash"])} &#8594; {f:.3f}</title></circle>')
        labels.append(f'<text x="{x + 6:.1f}" y="{y + dy:.1f}" font-size="12" '
                      f'fill="#111111">{c["hash"][:6]}</text>')
        best = f
    if path:
        path.append(f"H{W - mr}")
        s.append(f'<path d="{" ".join(path)}" fill="none" stroke="#111111" '
                 f'stroke-width="1.8"/>')
    s.extend(labels)
    s.append(f'<text x="{ml + pw / 2}" y="{H - 8}" text-anchor="middle" '
             f'font-size="13" font-style="italic" fill="#6b6a60">'
             f'candidate # (evaluation order) &mdash; lower is better</text>')
    s.append("</svg>")
    return "".join(s)


# -------------------------------------------------------------- the gallery --
def write_gallery(store: Store, run_id: str, results_dir: Path) -> Path:
    cands = {r["hash"]: r for r in store.candidates_for_run(run_id)}
    gens = store.generations_with_population(run_id)
    scen_cache: dict[str, list] = {}

    finite = [(h, store.fitness_of(r)) for h, r in cands.items()
              if math.isfinite(store.fitness_of(r))]
    best_hash = min(finite, key=lambda t: t[1])[0] if finite else None
    n_valid = len(finite)

    parts = [f"<style>{CSS}</style>",
             '<meta charset="utf-8">',
             '<meta http-equiv="refresh" content="30">',
             "<title>framevo gallery</title>",
             '<div class="wrap">',
             f"<h1>frame evolution &mdash; run <code>{html.escape(run_id)}</code></h1>",
             f'<p class="sub num">{len(gens)} generation(s) &middot; '
             f'{len(cands)} candidates ({n_valid} valid) &middot; '
             f'<a href="lineage.html">family tree</a> &middot; '
             f'<a href="glossary.html">glossary</a> &middot; '
             f'<span class="updated">regenerated {time.strftime("%H:%M:%S")}, '
             f'refreshes every 30&thinsp;s</span></p>',
             '<div class="legend">'
             '<span class="k"><span class="dot" style="background:#b9b6a6"></span>candidate</span>'
             '<span class="k"><span class="bar"></span>best so far</span>'
             '<span class="k"><span class="x">&#215;</span>invalid (design fail)</span>'
             '<span class="k num" style="color:#9b998c">aggregate Wh/km, lower is better</span>'
             "</div>",
             f'<div class="chart-card">{progress_chart_svg(store, run_id)}</div>']

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
                f"<td class='num'>{_fmt(s['wh_per_km'], 2) if s['valid'] else 'fail'}</td></tr>"
                for s in scen_cache[h])
            fail = (f'<div class="fail">{html.escape(c["failure_reason"] or "")}'
                    "</div>") if invalid and c["failure_reason"] else ""
            mat = f" &middot; {c['material']}" if c["material"] else ""
            parts.append(
                f'<div class="{cls}">'
                f'<a href="#d-{h}" style="border:none"><img src="{img}" alt="{h}"></a>'
                f'<div class="hash">{h}<br>g{c["generation_born"]} '
                f'{c["operator"]}{mat}</div>'
                f'<div class="agg num">{_fmt(fit)} <span class="unit">wh/km agg</span></div>'
                f"{fail}"
                f'<table class="sc">{sc_rows}</table>'
                "</div>")
            if h not in detail_ids:
                detail_ids.append(h)
        parts.append("</div>")

    parts.append("<h2>candidate details &amp; parentage</h2>")
    parts.append('<p class="sub" style="font-style:italic">drag a model to '
                 "rotate it, scroll to zoom, double-click to reset the view</p>")
    parts.append(
        '<div class="legend" style="margin:0 0 8px">'
        '<span class="k"><span class="dot" style="background:#8c2f1f"></span>'
        "arms (evolved)</span>"
        '<span class="k"><span class="dot" style="background:#34322e"></span>'
        "deck plates (evolved)</span>"
        '<span class="k"><span class="dot" style="background:#4a6fa5"></span>'
        "battery (fixed)</span>"
        '<span class="k"><span class="dot" style="background:#55534c"></span>'
        "motors (fixed)</span>"
        '<span class="k"><span class="dot" style="background:#d8d5c8"></span>'
        "prop disks (fixed)</span></div>")
    blobs: list[str] = []
    for h in detail_ids:
        c = cands[h]
        fit = store.fitness_of(c)
        img = _rel(results_dir, c["png_path"])
        blob = _mesh_blob_for(results_dir, c["png_path"])
        if blob is not None:
            blobs.append(f'<script type="application/json" id="m-{h}">{blob}</script>')
            viewer = (f'<div class="viewer"><canvas data-mesh="m-{h}"></canvas>'
                      f'<div class="hint">drag &middot; scroll &middot; '
                      f"double-click resets</div></div>")
        else:
            viewer = f'<div class="viewer"><img src="{img}" alt="{h}"></div>'

        parent_imgs = []
        for pkey in ("parent_a", "parent_b"):
            ph = c[pkey]
            if ph and ph in cands:
                pimg = _rel(results_dir, cands[ph]["png_path"])
                pfit = store.fitness_of(cands[ph])
                parent_imgs.append(
                    f'<figure><a href="#d-{ph}" style="border:none">'
                    f'<img src="{pimg}" alt="{ph}"></a>'
                    f'<figcaption>{ph} &middot; <span class="num">{_fmt(pfit)}'
                    "</span></figcaption></figure>")
        parents_html = ('<div class="lab">parents</div>' + "".join(parent_imgs)
                        if parent_imgs else
                        '<div class="lab">no parents</div>'
                        '<div style="font-style:italic;color:var(--faint);font-size:13px">'
                        "seed / immigrant</div>")
        sc_rows = "".join(
            f"<tr><td>{html.escape(s['scenario'])}</td>"
            f"<td>{_fmt(s['wh_per_km'])}</td><td>{_fmt(s['avg_power_w'], 1)}</td>"
            f"<td>{_fmt(s['max_tilt_deg'], 1)}&deg;</td>"
            f"<td style='color:var(--accent);font-style:italic'>"
            f"{html.escape(s['failure_reason'] or '')}</td></tr>"
            for s in scen_cache.get(h, []))
        mass = f"{c['frame_mass'] * 1e3:.1f}" if c["frame_mass"] else "&mdash;"
        mat = f" &middot; {c['material']}" if c["material"] else ""
        parts.append(
            f'<div class="detail" id="d-{h}">'
            f"{viewer}"
            f'<div class="dmeta"><div class="hash">{h}</div>'
            f'<div class="headline num">agg <b>{_fmt(fit)}</b> &middot; '
            f"mean {_fmt(c['mean_whkm'])} &middot; worst {_fmt(c['worst_whkm'])} Wh/km"
            f" &middot; frame {mass}&thinsp;g{mat}"
            f" &middot; born g{c['generation_born']} via {c['operator']}</div>"
            f'<table class="dt"><tr><th>scenario</th><th>wh/km</th>'
            f"<th>avg power, w</th><th>max tilt</th><th></th></tr>{sc_rows}</table>"
            f'</div><div class="parents">{parents_html}</div></div>')

    parts.extend(blobs)
    parts.append(f"<script>{VIEWER_JS}</script>")
    parts.append("</div>")

    out = results_dir / "gallery.html"
    out.write_text("\n".join(parts))
    return out


def write_leaderboard(store: Store, run_id: str, results_dir: Path,
                      scenario_names: list[str]) -> Path:
    cands = store.candidates_for_run(run_id)
    ranked = sorted((c for c in cands if c["fitness"] is not None),
                    key=lambda c: c["fitness"])[:10]
    head = ["rank", "hash", "gen", "operator", "material", "frame g",
            "agg Wh/km", "mean", "worst"] + scenario_names
    lines = ["# Leaderboard — top 10", "",
             "| " + " | ".join(head) + " |",
             "|" + "---|" * len(head)]
    for i, c in enumerate(ranked, 1):
        sc = {s["scenario"]: s for s in store.scenario_results_for(run_id, c["hash"])}
        per = [(f"{sc[n]['wh_per_km']:.3f}" if n in sc and sc[n]["valid"]
                else "—") for n in scenario_names]
        lines.append("| " + " | ".join(
            [str(i), f"`{c['hash']}`", str(c["generation_born"]), c["operator"],
             c["material"] or "—",
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
    fig.patch.set_facecolor("#fffff8")
    ax.set_facecolor("#fffff8")
    ax.plot(gens, median, color="#b9b6a6", lw=1.2, label="population median")
    ax.plot(gens, best, color="#8c2f1f", lw=1.0, label="generation best")
    ax.plot(gens, best_so_far, color="#111111", lw=1.8, label="best so far")
    ax.set_xlabel("generation")
    ax.set_ylabel("aggregate fitness (Wh/km)")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    out = results_dir / "convergence.png"
    fig.savefig(out, facecolor="#fffff8")
    plt.close(fig)
    return out
