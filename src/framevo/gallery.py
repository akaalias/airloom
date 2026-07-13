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
from .genome import describe_genome

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
h1{font-weight:400;font-size:34px;line-height:1.12;letter-spacing:-.01em;
  margin:0 0 6px;text-align:center}
h1 code{font:400 26px var(--mono);color:var(--muted)}
.sub{font-size:15px;color:var(--muted);margin:0 auto 4px;text-align:center}
.sub .updated{color:var(--faint);font-style:italic}
.sub.intro{max-width:820px;margin:12px auto 16px;line-height:1.55}
.inspiration{max-width:820px;margin:14px auto 4px;font-size:14.5px;
  color:var(--muted)}
.inspiration summary{cursor:pointer;text-align:center;list-style:none}
.inspiration summary::-webkit-details-marker{display:none}
.inspiration summary b{font:600 12px var(--serif);
  font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.08em}
.inspiration summary code{font:12.5px var(--mono);color:var(--faint)}
.inspiration pre{white-space:pre-wrap;font:13.5px/1.55 var(--serif);
  border-left:2px solid var(--rule);padding:2px 0 2px 16px;
  margin:10px 0 0;text-align:left}
h2{font:600 13px/1.2 var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
  border-bottom:1px solid var(--rule);padding-bottom:6px;margin:44px 0 14px}
/* chart legend, same visual language as the lineage page's */
.lgd{display:flex;flex-wrap:wrap;gap:7px 20px;justify-content:center;
  align-items:center;font-size:13.5px;color:var(--muted);
  max-width:1080px;margin:0 auto}
.lgd+.lgd{margin-top:6px}
.lg{position:relative;display:inline-flex;align-items:center;gap:7px;padding:2px 0}
.lg:has(.tip){cursor:help}
.lg:hover{color:var(--ink)}
.lg .sw{display:inline-flex;align-items:center}
.lg .dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.lg .tip{display:none;position:absolute;left:calc(100% + 12px);top:50%;
  transform:translateY(-50%);width:300px;z-index:30;background:var(--paper);
  border:1px solid var(--ink);padding:10px 13px;font-size:13.5px;
  line-height:1.5;color:var(--ink);box-shadow:6px 6px 0 rgba(17,17,17,.07)}
.lg:hover .tip{display:block}
.lg:nth-last-child(-n+2) .tip{left:auto;right:calc(100% + 12px)}
.lg .tip b{font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.05em;font-size:11.5px;color:var(--muted)}
.lg.gl{color:var(--ink);font-weight:700}
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
.detail{border-top:1px solid var(--rule);padding:22px 0 26px;margin:16px 0 0}
.detail .dhead{font:400 21px var(--serif);margin:0 0 14px}
.detail .dhead .hash{font:17px var(--mono);color:var(--muted)}
.detail .dcols{display:flex;gap:26px}
.viewer{width:50%;min-width:320px;position:relative}
.viewer canvas,.viewer img{width:100%;aspect-ratio:4/3;display:block;
  cursor:grab;touch-action:none}
/* static fallback renders are 360px wide: never upscale them past
   natural size or they pixelate */
.viewer img{object-fit:contain;width:auto;max-width:100%;cursor:default}
.viewer .vr{position:relative}
.viewer .hint{position:absolute;left:2px;bottom:2px;font:italic 11.5px var(--serif);
  color:var(--faint);pointer-events:none}
.viewer .lgd{margin-top:10px;font-size:12.5px;gap:4px 14px}
.detail.setter .lgd{color:var(--disc)}
.detail.setter .lg:hover,.detail.setter .lg.gl{color:var(--paper)}
.dmeta{flex:1;min-width:280px}
.dmeta .headline{font-size:17px;margin:4px 0 10px}
.dmeta .headline b{font-size:21px}
.dmeta .tables{display:flex;gap:34px;flex-wrap:wrap;align-items:flex-start}
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
.viewer img.peek{cursor:zoom-in}
.chart-card svg [data-h]{cursor:pointer}
.chart-card svg circle[data-h]:hover{stroke:#111111;stroke-width:2.5}
.chart-card svg text[data-h]:hover{font-size:16px}
.card.setter{background:var(--ink);border-color:var(--ink);color:var(--paper)}
.card.setter .hash{color:#b9b6a6}
.card.setter .agg .unit{color:#b9b6a6}
.card.setter table.sc td{color:#b9b6a6}
.card.setter table.sc td:last-child{color:var(--paper)}
.card.setter img{mix-blend-mode:normal}
.card.champion{outline:2px solid var(--accent);outline-offset:-1px}
.chip{display:inline-block;font:600 10.5px var(--serif);
  font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.07em;background:var(--ink);color:var(--paper);
  padding:3px 9px;margin-left:10px;vertical-align:2px}
.chip.champ{background:var(--accent)}
table.dt.hd{margin:10px 0 4px}
table.dt.hd b{font-size:17px}
.headline .lab,.note .nlab{font:600 11px var(--serif);
  font-feature-settings:"smcp" 1;text-transform:uppercase;
  letter-spacing:.06em;color:var(--muted)}
.headline .fail{color:var(--accent);font-style:italic}
.note{max-width:660px;font-size:14.5px;line-height:1.55;margin:12px 0}
.note .nlab{display:block;margin-bottom:2px}
.note.res .nlab{color:var(--accent)}
.dmeta .tlab{font:600 14px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.09em;color:var(--ink);
  margin:24px 0 8px;padding-top:16px;border-top:1px solid var(--rule-soft)}
/* invalid candidates: red diagonal cross over the render */
.card.invalid>a{position:relative;display:block}
.xed{position:relative;display:inline-block;max-width:100%}
.card.invalid>a::after,.xed::after{content:"";position:absolute;inset:0;
  pointer-events:none;background:
  linear-gradient(to top right,transparent calc(50% - 1px),
    rgba(140,47,31,.65) calc(50% - 1px),rgba(140,47,31,.65) calc(50% + 1px),
    transparent calc(50% + 1px)),
  linear-gradient(to bottom right,transparent calc(50% - 1px),
    rgba(140,47,31,.65) calc(50% - 1px),rgba(140,47,31,.65) calc(50% + 1px),
    transparent calc(50% + 1px))}
/* improvement-setter / champion detail rows: inverted, like the grid cards */
.detail.setter{background:var(--ink);color:var(--paper);border-top-color:var(--ink);
  margin:16px -26px 0;padding-left:26px;padding-right:26px}
.detail.champion{outline:2px solid var(--accent);outline-offset:-1px}
.detail.setter .viewer img,.detail.setter .parents img{mix-blend-mode:normal}
.detail.setter .dhead .hash,.detail.setter .parents .lab,
.detail.setter .parents figcaption,.detail.setter table.dt th,
.detail.setter .note .nlab,
.detail.setter .viewer .hint{color:var(--disc)}
.detail.setter .dmeta .tlab{color:var(--paper)}
.detail.setter table.dt td{border-bottom-color:#3a382f}
.detail.setter table.dt th{border-bottom-color:var(--paper)}
.detail.setter .dmeta .tlab{border-top-color:#3a382f}
.detail.setter .note.res .nlab{color:#d0765b}
.detail.setter .chip{background:var(--paper);color:var(--ink)}
.detail.setter .chip.champ{background:var(--accent);color:var(--paper)}
#ovl{position:fixed;inset:0;background:var(--paper);z-index:60;display:none;
  flex-direction:column}
#ovl.open{display:flex}
.ovl-bar{display:flex;align-items:center;gap:22px;padding:14px 26px;
  border-bottom:1px solid var(--rule)}
.ovl-bar .hash{font:17px var(--serif);color:var(--ink)}
.ovl-bar .hash .h{font:15px var(--mono);color:var(--muted)}
.ovl-bar .hash .num{font-weight:700}
.ovl-tabs{display:flex;gap:2px}
.ovl-tabs button{font:600 12px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  background:none;border:1px solid var(--rule);padding:7px 16px;cursor:pointer}
.ovl-tabs button.on{color:var(--ink);border-color:var(--ink);
  border-bottom:2px solid var(--ink)}
.ovl-tabs button:disabled{opacity:.35;cursor:default}
#ovl-close{margin-left:auto;font:26px/1 var(--serif);background:none;
  border:none;color:var(--muted);cursor:pointer;padding:0 6px}
#ovl-close:hover{color:var(--ink)}
.ovl-lgd{border-bottom:1px solid var(--rule);padding:7px 16px;flex-shrink:0}
/* improvement setters / the champion keep their inverted bar in the overlay */
#ovl.inv .ovl-bar,#ovl.inv .ovl-lgd{background:var(--ink);
  border-bottom-color:#3a382f}
#ovl.inv .ovl-bar .hash{color:var(--paper)}
#ovl.inv .ovl-bar .hash .h{color:var(--disc)}
#ovl.inv .ovl-tabs button{color:var(--disc);border-color:#3a382f}
#ovl.inv .ovl-tabs button.on{color:var(--paper);border-color:var(--paper)}
#ovl.inv #ovl-close{color:var(--disc)}
#ovl.inv #ovl-close:hover{color:var(--paper)}
#ovl.inv .ovl-lgd .lgd{color:var(--disc)}
#ovl.inv .ovl-lgd .lg:hover,#ovl.inv .ovl-lgd .lg.gl{color:var(--paper)}
.ovl-views{position:absolute;left:26px;bottom:12px;display:flex;gap:2px;z-index:5}
.ovl-views button{font:600 10.5px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  background:var(--paper);border:1px solid var(--rule);padding:4px 10px;
  cursor:pointer}
.ovl-views button:hover{color:var(--ink);border-color:var(--ink)}
.ovl-body{flex:1;display:none;min-height:0}
.ovl-body.on{display:flex}
.ovl-body .pane{flex:1;display:flex;flex-direction:column;min-width:0}
.ovl-body .pane+.pane{border-left:1px solid var(--rule)}
.ovl-body .pane .cap{font:600 11px var(--serif);font-feature-settings:"smcp" 1;
  text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  padding:10px 18px 0;display:flex;gap:14px;align-items:baseline}
.ovl-body .pane .cap .hash{font:12px var(--mono);color:var(--faint)}
.ovl-body canvas{flex:1;width:100%;min-height:0;cursor:grab;touch-action:none}
.ovl-hint{position:absolute;right:26px;bottom:12px;font:italic 12px var(--serif);
  color:var(--faint);pointer-events:none}
"""

VIEWER_JS = r"""
(function(){
"use strict";
function b64bytes(s){var b=atob(s),a=new Uint8Array(b.length);
  for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a}
var VS="attribute vec3 aP;attribute vec3 aN;attribute vec4 aC;"+
  "uniform mat3 uR;uniform vec3 uT;uniform float uS;uniform vec2 uA;"+
  "uniform vec2 uPn;"+
  "varying vec3 vN;varying vec4 vC;"+
  "void main(){vec3 p=uR*(aP-uT);"+
  "gl_Position=vec4(p.x*uS*uA.x+uPn.x,p.y*uS*uA.y+uPn.y,-p.z*0.25,1.0);"+
  "vN=uR*aN;vC=aC;}";
var FS="precision mediump float;varying vec3 vN;varying vec4 vC;"+
  "void main(){vec3 L=normalize(vec3(0.35,0.48,0.85));"+
  "float d=abs(dot(normalize(vN),L));float s=0.45+0.55*d;"+
  "gl_FragColor=vec4(vC.rgb*s+0.07,vC.a);}";

var DEF_YAW=-0.9,DEF_PITCH=0.8;
var blobCache={};
function decodeBlob(id){
  if(blobCache[id])return blobCache[id];
  var el=document.getElementById(id);
  if(!el)return null;
  var d=JSON.parse(el.textContent);
  var V=new Float32Array(b64bytes(d.v).buffer);
  var F=d.i==="u16"?new Uint16Array(b64bytes(d.f).buffer)
                   :new Uint32Array(b64bytes(d.f).buffer);
  var nf=F.length/3;
  var FC=d.fc?new Uint8Array(b64bytes(d.fc)):new Uint8Array(nf);
  var PAL=d.p&&d.p.length?d.p:[[138,151,168,1]];
  var opaque=[],trans=[];
  for(var f=0;f<nf;f++)((PAL[FC[f]]||PAL[0])[3]<0.999?trans:opaque).push(f);
  var list=opaque.concat(trans),nOpq=opaque.length;
  var P=new Float32Array(nf*9),N=new Float32Array(nf*9),C=new Float32Array(nf*12);
  for(var k=0;k<nf;k++){
    var f2=list[k],a=F[3*f2],b=F[3*f2+1],c=F[3*f2+2];
    var pc=PAL[FC[f2]]||PAL[0];
    var e1x=V[3*b]-V[3*a],e1y=V[3*b+1]-V[3*a+1],e1z=V[3*b+2]-V[3*a+2];
    var e2x=V[3*c]-V[3*a],e2y=V[3*c+1]-V[3*a+1],e2z=V[3*c+2]-V[3*a+2];
    var nx=e1y*e2z-e1z*e2y,ny=e1z*e2x-e1x*e2z,nz=e1x*e2y-e1y*e2x;
    var idx=[a,b,c];
    for(var v=0;v<3;v++){
      var o=9*k+3*v,vi=idx[v];
      P[o]=V[3*vi];P[o+1]=V[3*vi+1];P[o+2]=V[3*vi+2];
      N[o]=nx;N[o+1]=ny;N[o+2]=nz;
      var co=12*k+4*v;
      C[co]=pc[0]/255;C[co+1]=pc[1]/255;C[co+2]=pc[2]/255;C[co+3]=pc[3];
    }
  }
  var entry={P:P,N:N,C:C,nf:nf,nOpq:nOpq,c:d.c,r:d.r||0.3,ev:null};
  // projected extents at the default yaw (pitch folded in at draw time)
  // -> lets each viewer start zoomed to fit regardless of model size
  var cyw=Math.cos(DEF_YAW),syw=Math.sin(DEF_YAW),mx=0,my=0,mz=0;
  for(var vi=0;vi<V.length;vi+=3){
    var X=V[vi]-d.c[0],Y=V[vi+1]-d.c[1],Z=V[vi+2]-d.c[2];
    var qx=Math.abs(cyw*X+syw*Y),qy=Math.abs(cyw*Y-syw*X),qz=Math.abs(Z);
    if(qx>mx)mx=qx;if(qy>my)my=qy;if(qz>mz)mz=qz;
  }
  entry.mx=mx;entry.my=my;entry.mz=mz;
  if(d.pn){ // evolved-parts subset (deck + arms) for the diff view
    var evIdx={};
    d.pn.forEach(function(nm,i){if(nm==="deck"||nm==="arms")evIdx[i]=1});
    var keep=[];
    for(var f4=0;f4<nf;f4++)if(evIdx[FC[f4]])keep.push(f4);
    if(keep.length){
      var Pe=new Float32Array(keep.length*9),Ne=new Float32Array(keep.length*9),
          Ce=new Float32Array(keep.length*12),Cg=new Float32Array(keep.length*12);
      for(var k2=0;k2<keep.length;k2++){
        var ff=keep[k2],aa=F[3*ff],bb=F[3*ff+1],cc=F[3*ff+2];
        var pc2=PAL[FC[ff]]||PAL[0];
        var g1x=V[3*bb]-V[3*aa],g1y=V[3*bb+1]-V[3*aa+1],g1z=V[3*bb+2]-V[3*aa+2];
        var g2x=V[3*cc]-V[3*aa],g2y=V[3*cc+1]-V[3*aa+1],g2z=V[3*cc+2]-V[3*aa+2];
        var mx=g1y*g2z-g1z*g2y,my=g1z*g2x-g1x*g2z,mz=g1x*g2y-g1y*g2x;
        var ind=[aa,bb,cc];
        for(var v2=0;v2<3;v2++){
          var o2=9*k2+3*v2,vj=ind[v2];
          Pe[o2]=V[3*vj];Pe[o2+1]=V[3*vj+1];Pe[o2+2]=V[3*vj+2];
          Ne[o2]=mx;Ne[o2+1]=my;Ne[o2+2]=mz;
          var co2=12*k2+4*v2;
          Ce[co2]=pc2[0]/255;Ce[co2+1]=pc2[1]/255;Ce[co2+2]=pc2[2]/255;Ce[co2+3]=1.0;
          Cg[co2]=0.44;Cg[co2+1]=0.43;Cg[co2+2]=0.40;Cg[co2+3]=0.40;
        }
      }
      entry.ev={P:Pe,N:Ne,Ce:Ce,Cg:Cg,nf:keep.length};
      // subset extents -> the diff view fits to deck+arms, not the props
      var ex2=0,ey2=0,ez2=0;
      for(var pi=0;pi<Pe.length;pi+=3){
        var X2=Pe[pi]-d.c[0],Y2=Pe[pi+1]-d.c[1],Z2=Pe[pi+2]-d.c[2];
        var ax=Math.abs(cyw*X2+syw*Y2),ay=Math.abs(cyw*Y2-syw*X2),
            az=Math.abs(Z2);
        if(ax>ex2)ex2=ax;if(ay>ey2)ey2=ay;if(az>ez2)ez2=az;
      }
      entry.ev.mx=ex2;entry.ev.my=ey2;entry.ev.mz=ez2;
    }
  }
  blobCache[id]=entry;
  return entry;
}

// one GL viewer per canvas, created once; loadBlob swaps model data;
// several viewers may share one state -> they rotate/zoom in sync
// zoom is relative to a per-viewer fit factor, so 1.0 = model fills the
// canvas (with a small margin) at the state's base pitch
function makeState(basePitch){
  var bp=(basePitch===undefined?DEF_PITCH:basePitch);
  var st={yaw:DEF_YAW,pitch:bp,zoom:1.0,panX:0,panY:0,basePitch:bp,viewers:[]};
  st.redraw=function(){st.viewers.forEach(function(v){v.draw()})};
  st.reset=function(){st.yaw=DEF_YAW;st.pitch=st.basePitch;st.zoom=1.0;
    st.panX=0;st.panY=0;st.redraw()};
  return st;
}
function makeViewer(canvas,state){
  var gl=canvas.getContext("webgl",{antialias:true,alpha:false})
       ||canvas.getContext("experimental-webgl");
  if(!gl)return null;
  function shader(type,src){var sh=gl.createShader(type);
    gl.shaderSource(sh,src);gl.compileShader(sh);return sh}
  var prog=gl.createProgram();
  gl.attachShader(prog,shader(gl.VERTEX_SHADER,VS));
  gl.attachShader(prog,shader(gl.FRAGMENT_SHADER,FS));
  gl.linkProgram(prog);gl.useProgram(prog);
  function bindBuf(buf,attr,size){
    gl.bindBuffer(gl.ARRAY_BUFFER,buf);
    var loc=gl.getAttribLocation(prog,attr);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc,size,gl.FLOAT,false,0,0);
  }
  function upload(P,N,C){
    var b={aP:gl.createBuffer(),aN:gl.createBuffer(),aC:gl.createBuffer()};
    gl.bindBuffer(gl.ARRAY_BUFFER,b.aP);gl.bufferData(gl.ARRAY_BUFFER,P,gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER,b.aN);gl.bufferData(gl.ARRAY_BUFFER,N,gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER,b.aC);gl.bufferData(gl.ARRAY_BUFFER,C,gl.STATIC_DRAW);
    return b;
  }
  var uR=gl.getUniformLocation(prog,"uR"),uT=gl.getUniformLocation(prog,"uT"),
      uS=gl.getUniformLocation(prog,"uS"),uA=gl.getUniformLocation(prog,"uA"),
      uPn=gl.getUniformLocation(prog,"uPn");
  gl.enable(gl.DEPTH_TEST);
  gl.clearColor(1.0,1.0,0.973,1.0);
  var models=[]; // [{bufs, nf, nOpq}], shared center/scale from first
  var frame={c:[0,0,0],r:0.3};
  var view={
    canvas:canvas,
    loadBlob:function(id){view.load([{id:id}])},
    load:function(specs){
      models=[];
      for(var i2=0;i2<specs.length;i2++){
        var sp=specs[i2],d2=decodeBlob(sp.id);
        if(!d2)continue;
        if(sp.evolved){
          if(!d2.ev)continue;
          models.push({bufs:upload(d2.ev.P,d2.ev.N,sp.ghost?d2.ev.Cg:d2.ev.Ce),
                       nf:d2.ev.nf,nOpq:sp.ghost?0:d2.ev.nf});
        }else{
          models.push({bufs:upload(d2.P,d2.N,d2.C),nf:d2.nf,nOpq:d2.nOpq});
        }
        var ext=sp.evolved?d2.ev:d2;
        if(i2===0){frame={c:d2.c,r:d2.r,mx:ext.mx,my:ext.my,mz:ext.mz}}
        else{frame.mx=Math.max(frame.mx,ext.mx);
             frame.my=Math.max(frame.my,ext.my);
             frame.mz=Math.max(frame.mz,ext.mz)}
      }
      gl.uniform3f(uT,frame.c[0],frame.c[1],frame.c[2]);
    },
    // zoom that fits the CURRENT pitch: draw()'s fit factor is anchored
    // at basePitch so rotation doesn't breathe, so after rotating the
    // fit button needs this correction ratio
    fitZoom:function(){
      if(!models.length||frame.mx===undefined)return null;
      var w=canvas.clientWidth,h=canvas.clientHeight;
      if(w<2||h<2)return null;
      var asp=w>h?[h/w,1]:[1,w/h];
      function need(p){
        var ex=frame.mx*asp[0],
            ey=(Math.abs(Math.sin(p))*frame.my+
                Math.abs(Math.cos(p))*frame.mz)*asp[1];
        return Math.max(ex,ey);
      }
      var cur=need(state.pitch);
      return cur>0?need(state.basePitch)/cur:null;
    },
    draw:function(){
      if(!models.length)return;
      var dpr=window.devicePixelRatio||1;
      var w=canvas.clientWidth,h=canvas.clientHeight;
      if(w<2||h<2)return;
      if(canvas.width!==Math.round(w*dpr)){
        canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr)}
      gl.viewport(0,0,canvas.width,canvas.height);
      var cy2=Math.cos(state.yaw),sy=Math.sin(state.yaw),
          cp=Math.cos(state.pitch),sp=Math.sin(state.pitch);
      gl.uniformMatrix3fv(uR,false,[cy2,-sy*sp,sy*cp,
                                    sy,cy2*sp,-cy2*cp,
                                    0,cp,sp]);
      var asp=w>h?[h/w,1]:[1,w/h];
      gl.uniform2f(uA,asp[0],asp[1]);
      gl.uniform2f(uPn,state.panX||0,state.panY||0);
      // fit factor: at zoom 1 the model's projected extents (at the
      // state's base pitch) reach 92% of the canvas on the tighter axis
      var fit=1;
      if(frame.mx!==undefined){
        var bs=Math.sin(state.basePitch),bc=Math.cos(state.basePitch);
        var ex=frame.mx*asp[0],
            ey=(Math.abs(bs)*frame.my+Math.abs(bc)*frame.mz)*asp[1];
        fit=0.92*frame.r/(0.85*Math.max(ex,ey));
      }
      gl.uniform1f(uS,0.85*state.zoom*fit/frame.r);
      gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      for(var m2=0;m2<models.length;m2++){
        var mo=models[m2];
        bindBuf(mo.bufs.aP,"aP",3);bindBuf(mo.bufs.aN,"aN",3);
        bindBuf(mo.bufs.aC,"aC",4);
        gl.disable(gl.BLEND);gl.depthMask(true);
        if(mo.nOpq>0)gl.drawArrays(gl.TRIANGLES,0,mo.nOpq*3);
        if(mo.nf>mo.nOpq){
          gl.enable(gl.BLEND);
          gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
          gl.depthMask(false);
          gl.drawArrays(gl.TRIANGLES,mo.nOpq*3,(mo.nf-mo.nOpq)*3);
          gl.depthMask(true);
        }
      }
    }
  };
  state.viewers.push(view);
  var dragging=false,panning=false,lastX=0,lastY=0;
  canvas.addEventListener("pointerdown",function(e){
    dragging=true;panning=e.metaKey||e.ctrlKey; // cmd/ctrl-drag pans
    lastX=e.clientX;lastY=e.clientY;
    canvas.setPointerCapture(e.pointerId);canvas.style.cursor="grabbing"});
  canvas.addEventListener("pointermove",function(e){
    if(!dragging)return;
    if(panning){
      state.panX+=(e.clientX-lastX)*2/Math.max(1,canvas.clientWidth);
      state.panY-=(e.clientY-lastY)*2/Math.max(1,canvas.clientHeight);
    }else{
      state.yaw+=(e.clientX-lastX)*0.011;
      state.pitch=Math.max(-1.6,Math.min(1.6,state.pitch+(e.clientY-lastY)*0.011));
    }
    lastX=e.clientX;lastY=e.clientY;state.redraw()});
  canvas.addEventListener("pointerup",function(){
    dragging=false;canvas.style.cursor="grab"});
  canvas.addEventListener("wheel",function(e){
    e.preventDefault();
    state.zoom=Math.max(0.3,Math.min(8,state.zoom*Math.exp(-e.deltaY*0.0016)));
    state.redraw()},{passive:false});
  canvas.addEventListener("dblclick",function(){state.reset()});
  return view;
}

// ---- overlay: tab 1 = solo model, tab 2 = ancestor vs candidate (synced)
var ovl=document.getElementById("ovl");
if(!ovl)return;
var soloState=makeState(),cmpState=makeState(),
    diffState=makeState(1.2); // near top-down: plan-shape reads best
var soloV=null,cmpA=null,cmpB=null,diffV=null,current=null;
function ensureViewers(){
  if(!soloV)soloV=makeViewer(document.getElementById("ovl-solo"),soloState);
  if(!cmpA)cmpA=makeViewer(document.getElementById("ovl-anc"),cmpState);
  if(!cmpB)cmpB=makeViewer(document.getElementById("ovl-cur"),cmpState);
  if(!diffV)diffV=makeViewer(document.getElementById("ovl-diff"),diffState);
}
function redrawAll(){soloState.redraw();cmpState.redraw();diffState.redraw()}
function setTab(name){
  ovl.querySelectorAll(".ovl-tabs button").forEach(function(b){
    b.classList.toggle("on",b.dataset.tab===name)});
  ovl.querySelectorAll(".ovl-body").forEach(function(b){
    b.classList.toggle("on",b.dataset.tab===name)});
  // the freshly shown canvas needs layout to settle before it has a size
  requestAnimationFrame(redrawAll);
  setTimeout(redrawAll,60);
  setTimeout(redrawAll,200);
}
function openOverlay(d){
  current=d;
  ensureViewers();
  if(!soloV)return; // no webgl
  ovl.classList.add("open");
  ovl.classList.toggle("inv",d.setter==="1");
  document.body.style.overflow="hidden";
  // hash and fit are trusted generator output (hex + number)
  ovl.querySelector(".ovl-bar .hash").innerHTML=
    'candidate <span class="h">'+(d.title||"")+"</span>"+
    (d.fit?' &middot; <span class="num">'+d.fit+"</span>&thinsp;Wh/km":"");
  soloV.loadBlob(d.mesh);
  soloState.reset();
  var cmpBtn=ovl.querySelector('button[data-tab="compare"]');
  var diffBtn=ovl.querySelector('button[data-tab="diff"]');
  var hasAnc=d.ancestor&&document.getElementById(d.ancestor)&&d.ancestor!==d.mesh;
  if(hasAnc){
    cmpBtn.disabled=false;
    cmpA.loadBlob(d.ancestor);cmpB.loadBlob(d.mesh);
    document.getElementById("anc-hash").textContent=d.anctitle||"";
    document.getElementById("cur-hash").textContent=
      (d.title||"")+(d.fit?" · "+d.fit:"");
    cmpState.reset();
  }else{
    cmpBtn.disabled=true;
  }
  var meshEv=decodeBlob(d.mesh),ancEv=hasAnc?decodeBlob(d.ancestor):null;
  if(hasAnc&&meshEv&&meshEv.ev&&ancEv&&ancEv.ev){
    diffBtn.disabled=false;
    diffV.load([{id:d.mesh,evolved:true},
                {id:d.ancestor,evolved:true,ghost:true}]);
    document.getElementById("diff-hash").textContent=(d.title||"")+
      (d.fit?" · "+d.fit:"")+"  vs  "+(d.anctitle||"");
    diffState.reset();
  }else{
    diffBtn.disabled=true;
  }
  setTab("solo");
}
function closeOverlay(){
  ovl.classList.remove("open");
  document.body.style.overflow="";
}
ovl.querySelectorAll(".ovl-tabs button").forEach(function(b){
  b.addEventListener("click",function(){if(!b.disabled)setTab(b.dataset.tab)});
});
document.getElementById("ovl-close").addEventListener("click",closeOverlay);
document.addEventListener("keydown",function(e){
  if(e.key==="Escape")closeOverlay()});
document.querySelectorAll("img.peek").forEach(function(img){
  img.addEventListener("click",function(){
    openOverlay({mesh:img.dataset.mesh,ancestor:img.dataset.ancestor,
                 title:img.dataset.title,anctitle:img.dataset.anctitle,
                 fit:img.dataset.fit,setter:img.dataset.setter});
  });
});
// quick view presets act on whichever tab is showing
// nose (FPV camera) = +X in mesh space; yaw/pitch pairs put it facing
// the viewer (front), pointing left/right in profile, or up in plan views
var VIEWS={front:[Math.PI/2,0],left:[Math.PI,0],right:[0,0],
           top:[-Math.PI/2,Math.PI/2],bottom:[Math.PI/2,-Math.PI/2]};
function activeState(){
  var b=ovl.querySelector(".ovl-tabs button.on");
  var t=b?b.dataset.tab:"solo";
  return t==="compare"?cmpState:t==="diff"?diffState:soloState;
}
ovl.querySelectorAll(".ovl-views button").forEach(function(b){
  b.addEventListener("click",function(){
    var st=activeState(),v=b.dataset.view;
    st.panX=0;st.panY=0;
    if(v==="default"){st.reset();return}
    if(v==="fit"){
      var zs=[];
      st.viewers.forEach(function(vv){var z=vv.fitZoom();if(z)zs.push(z)});
      st.zoom=zs.length?Math.max(0.3,Math.min(8,Math.min.apply(null,zs))):1.0;
    }else{st.yaw=VIEWS[v][0];st.pitch=VIEWS[v][1]}
    st.redraw();
  });
});
window.addEventListener("resize",function(){
  if(ovl.classList.contains("open")){soloState.redraw();cmpState.redraw();
    diffState.redraw()}
});
// auto-refresh while the run is live -- but never kill an open overlay
setInterval(function(){
  if(!ovl.classList.contains("open"))location.reload();
},30000);
// progress chart: click any marker to jump to that candidate's detail card
document.querySelectorAll(".chart-card [data-h]").forEach(function(el){
  el.addEventListener("click",function(){
    var t=document.getElementById("d-"+el.dataset.h);
    if(t)t.scrollIntoView({behavior:"smooth",block:"start"});
    location.hash="d-"+el.dataset.h;
  });
});
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


def _bottom_png_for(results_dir: Path, png_path: str | None) -> str | None:
    """Relative path of the from-below still; backfilled from the viewer
    blob for candidates built before bottom views existed."""
    if not png_path:
        return None
    p = Path(png_path)
    bottom = p.with_name(p.stem + "_bottom.png")
    if not bottom.exists():
        blob_path = p.with_suffix(".mesh.json")
        blob_path = Path(str(p)[:-4] + ".mesh.json")
        if not blob_path.exists():
            return None
        try:
            _render_bottom_from_blob(blob_path, bottom)
        except Exception:
            return None
    return _rel(results_dir, str(bottom))


def _render_bottom_from_blob(blob_path: Path, out_path: Path) -> None:
    """Rebuild the from-below still using the decimated viewer blob (used
    only to backfill runs that predate bottom views)."""
    import base64

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    d = json.loads(blob_path.read_text())
    verts = np.frombuffer(base64.b64decode(d["v"]), dtype=np.float32).reshape(-1, 3)
    dtype = np.uint16 if d["i"] == "u16" else np.uint32
    faces = np.frombuffer(base64.b64decode(d["f"]), dtype=dtype).reshape(-1, 3)
    fc = np.frombuffer(base64.b64decode(d["fc"]), dtype=np.uint8)
    pal = np.array(d["p"], dtype=float)
    colors = pal[fc]
    rgba = np.column_stack([colors[:, :3] / 255.0, colors[:, 3]])
    dpi = 90
    fig = plt.figure(figsize=(440 / dpi, 440 / dpi), dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")
    coll = Poly3DCollection(verts[faces], facecolors=rgba, zsort="average")
    coll.set_linewidth(0.0)
    ax.add_collection3d(coll)
    half = 0.235
    ax.set_xlim(-half, half); ax.set_ylim(-half, half); ax.set_zlim(-half, half)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=-82, azim=-90)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(out_path, dpi=dpi, facecolor="#fffff8")
    plt.close(fig)


def _oldest_ancestor(cands: dict, h: str) -> str | None:
    """Walk the primary parent chain to the lineage's root."""
    cur, seen = h, set()
    while True:
        c = cands.get(cur)
        if c is None or cur in seen:
            return cur if cur != h else None
        seen.add(cur)
        nxt = c["parent_a"] or c["parent_b"]
        if not nxt or nxt not in cands:
            return cur if cur != h else None
        cur = nxt


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
def progress_chart_svg(store: Store, run_id: str,
                       target_whkm: float | None = None,
                       record_whkm: float | None = None) -> str:
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
    if target_whkm:
        y_max = max(y_max, target_whkm * 1.2)
    if record_whkm:
        y_max = max(y_max, record_whkm * 1.2)
    if y_max <= 0:
        y_max = 1.0

    W, H = 1180, 470
    # tall top margin: the invalid strip lives ~100px above the finite
    # scale, in its own tinted band (a different value space)
    ml, mr, mt, mb = 64, 24, 116, 42
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
    # generation boundaries (pivot generations flagged in teal). At high
    # generation counts, ticks + labels thin to a spaced subset so they stay
    # readable; pivots take priority and tolerate a tighter gap.
    pivot_gens = {c["generation_born"] for c in cands if c["operator"] == "pivot"}
    bounds: list[tuple[int, float]] = []
    prev_gen = None
    for i, c in enumerate(cands):
        if c["generation_born"] != prev_gen:
            prev_gen = c["generation_born"]
            bounds.append((prev_gen, ml + pw * i / n))
    last_lx = -1e9
    for g, x in bounds:
        is_pivot = g in pivot_gens
        if is_pivot:
            # a pivot is a structural event: full-height teal marker plus
            # axis tick, drawn no matter how tight the label spacing gets
            s.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" '
                     f'y2="{mt + ph}" stroke="#2e6e63" stroke-width="1.1" '
                     f'stroke-dasharray="5,4" opacity="0.65">'
                     f'<title>g{g}: pivot generation (plateau broken up with '
                     f'far-parent crossovers)</title></line>')
            s.append(f'<line x1="{x:.1f}" y1="{mt + ph}" x2="{x:.1f}" '
                     f'y2="{mt + ph + 5}" stroke="#2e6e63" stroke-width="1.6">'
                     f'<title>g{g}: pivot generation (plateau broken up with '
                     f'far-parent crossovers)</title></line>')
        if x - last_lx < (14.0 if is_pivot else 36.0):
            continue
        last_lx = x
        if not is_pivot:
            s.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt + ph}" '
                     f'stroke="#ece9da" stroke-width="1" stroke-dasharray="1,4"/>')
        if is_pivot:
            s.append(f'<text x="{x + 3:.1f}" y="{mt + ph + 16}" font-size="11" '
                     f'font-weight="700" fill="#2e6e63">g{g} &#10227;'
                     f'<title>pivot generation: plateau broken up with '
                     f'far-parent crossovers</title></text>')
        else:
            s.append(f'<text x="{x + 3:.1f}" y="{mt + ph + 16}" font-size="11" '
                     f'fill="#9b998c">g{g}</text>')

    # invalid strip (design fails): floated well clear of the finite scale,
    # with its own infinity label on the y axis and a faint band behind it
    y_inv = 20
    s.append(f'<rect x="{ml}" y="{y_inv - 16}" width="{pw}" '
             f'height="{mt - 10 - (y_inv - 16)}" fill="#8c2f1f" '
             f'opacity="0.05"/>')
    s.append(f'<text x="{ml - 10}" y="{y_inv + 1}" text-anchor="end" '
             f'font-size="15" fill="#8c2f1f">&#8734;</text>')
    # discarded dots + invalid marks; both shrink as the run grows so a
    # 100-generation chart stays legible. Past ~400 candidates the invalid
    # strip switches from x glyphs to a barcode of thin ticks.
    r_dot = max(1.6, min(3.4, 1500.0 / n))
    dense = n > 400
    for i, (c, f) in enumerate(zip(cands, fits)):
        x = xat(i)
        tip = html.escape(f"{c['hash']} g{c['generation_born']} {c['operator']}"
                          + (f" · {f:.3f}" if math.isfinite(f)
                             else f" · {c['failure_reason'] or 'invalid'}"))
        hattr = f' data-h="{c["hash"]}"'  # every marker clicks to its card
        if math.isfinite(f):
            clipped = f > hi
            fill = "#b9b6a6" if not clipped else "none"
            stroke = ' stroke="#b9b6a6" stroke-width="1.2"' if clipped else ""
            s.append(f'<circle{hattr} cx="{x:.1f}" cy="{yat(f):.1f}" '
                     f'r="{r_dot:.1f}" '
                     f'fill="{fill}"{stroke}><title>{tip}</title></circle>')
        elif dense:
            s.append(f'<line{hattr} x1="{x:.1f}" y1="{y_inv - 5}" x2="{x:.1f}" '
                     f'y2="{y_inv + 1}" stroke="#8c2f1f" stroke-width="0.8" '
                     f'opacity="0.7"><title>{tip}</title></line>')
        else:
            s.append(f'<text{hattr} x="{x:.1f}" y="{y_inv}" text-anchor="middle" '
                     f'font-size="12" font-weight="700" fill="#8c2f1f">'
                     f'&#215;<title>{tip}</title></text>')

    # best-so-far step line with labeled improvements; every improvement
    # keeps its dot + tooltip, but a hash label is only drawn when it has
    # ~56px of clearance from the previous label
    best = math.inf
    path: list[str] = []
    labels: list[str] = []
    flip = False
    last_label_x = -1e9
    for i, (c, f) in enumerate(zip(cands, fits)):
        if not math.isfinite(f) or f >= best:
            continue
        x, y = xat(i), yat(f)
        if not path:
            path.append(f"M{x:.1f},{y:.1f}")
        else:
            path.append(f"H{x:.1f}")
            path.append(f"V{y:.1f}")
        labels.append(f'<circle data-h="{c["hash"]}" cx="{x:.1f}" cy="{y:.1f}" '
                      f'r="4.4" fill="#111111">'
                      f'<title>{html.escape(c["hash"])} &#8594; {f:.3f}</title></circle>')
        if x - last_label_x >= 56:
            dy = -9 if not flip else 18
            flip = not flip
            labels.append(f'<text x="{x + 6:.1f}" y="{y + dy:.1f}" font-size="12" '
                          f'fill="#111111">{c["hash"][:6]}</text>')
            last_label_x = x
        best = f
    if path:
        path.append(f"H{W - mr}")
        s.append(f'<path d="{" ".join(path)}" fill="none" stroke="#111111" '
                 f'stroke-width="1.8"/>')
    s.extend(labels)
    if target_whkm:
        yt = yat(target_whkm)
        s.append(f'<line x1="{ml}" y1="{yt:.1f}" x2="{W - mr}" y2="{yt:.1f}" '
                 f'stroke="#8c2f1f" stroke-width="1.2" stroke-dasharray="6,4"/>')
        s.append(f'<text x="{ml + 8}" y="{yt - 6:.1f}" font-size="12.5" '
                 f'font-style="italic" fill="#8c2f1f">{target_whkm:g} &#183; '
                 f'minimum target (current 7-inch long-range practice, '
                 f'&#8776;8 g/W)</text>')
    if record_whkm:
        yr = yat(record_whkm)
        s.append(f'<line x1="{ml}" y1="{yr:.1f}" x2="{W - mr}" y2="{yr:.1f}" '
                 f'stroke="#8a6a1e" stroke-width="1.1" stroke-dasharray="2,5"/>')
        s.append(f'<text x="{ml + 8}" y="{yr - 6:.1f}" font-size="12.5" '
                 f'font-style="italic" fill="#8a6a1e">{record_whkm:g} &#183; '
                 f'record-class stretch (&#8776;2 Wh/km calm cruise, '
                 f'Dave_C-style builds)</text>')
    s.append(f'<text x="{ml + pw / 2}" y="{H - 8}" text-anchor="middle" '
             f'font-size="13" font-style="italic" fill="#6b6a60">'
             f'candidate # (evaluation order) &mdash; lower is better</text>')
    s.append("</svg>")
    return "".join(s)


def _lgd_item(sw: str, label: str, tip: str | None = None,
              cls: str = "lg") -> str:
    t = (f'<span class="tip"><b>{html.escape(label)}</b><br>'
         f"{tip}</span>") if tip else ""
    sw_html = f'<span class="sw">{sw}</span>' if sw else ""
    return f'<span class="{cls}">{sw_html}{label}{t}</span>'


def _lgd_dot(col: str) -> str:
    return f'<span class="dot" style="background:{col}"></span>'


def _parts_legend_html() -> str:
    """Part-color legend (evolved vs fixed kit), shown under each detail
    render and in the 3D overlay bar."""
    item, dot = _lgd_item, _lgd_dot
    fixed_tip = ("Fixed kit, identical on every candidate &mdash; drawn in "
                 "the 3D model for context only; evolution never changes it.")
    row = [
        item("", "evolved:", cls="lg gl"),
        item(dot("#8c2f1f"), "arms",
             "Evolved part: the four arms &mdash; length, width, waist, "
             "thickness and sweep genes reshape them."),
        item(dot("#34322e"), "deck plates + standoffs",
             "Evolved part: the stacked deck plates and standoffs &mdash; "
             "plate size, thickness and deck gap genes reshape them."),
        item("", "fixed kit:", cls="lg gl"),
        item(dot("#4a6fa5"), "battery", fixed_tip),
        item(dot("#5a7a52"), "FC/ESC stack", fixed_tip),
        item(dot("#8a6a1e"), "wiring/XT60", fixed_tip),
        item(dot("#55534c"), "motors", fixed_tip),
        item(dot("#d8d5c8"), "prop disks", fixed_tip),
    ]
    return '<div class="lgd parts">' + "".join(row) + "</div>"


def _chart_legend_html() -> str:
    """Centered chart legend with hover explanations, matching the
    lineage page's legend language."""
    item, dot = _lgd_item, _lgd_dot
    row1 = [
        item(dot("#b9b6a6"), "candidate",
             "One evaluated design, drawn at its aggregate energy score "
             "across all scenarios. Lower is better."),
        item('<svg width="12" height="12"><circle cx="6" cy="6" r="4.5" '
             'fill="none" stroke="#b9b6a6" stroke-width="1.4"/></svg>',
             "off scale",
             "A valid but far-off candidate above the 95th-percentile cap, "
             "drawn hollow at the top edge so one terrible design does not "
             "squash the interesting region."),
        item('<span style="display:inline-block;width:16px;'
             'border-top:2px solid #111111"></span>', "best so far",
             "Step line tracking the lowest energy score reached so far; "
             "each black dot is an improvement. Click one to jump to that "
             "candidate&rsquo;s detail card."),
        item('<span style="color:#8c2f1f;font-weight:700">&#215;</span>',
             "invalid (design fail)",
             "Failed a structural or geometric check and never flew the "
             "scenarios, so it has no finite score &mdash; plotted on the "
             "&#8734; row."),
        item('<span style="color:#2e6e63;font-weight:700">g&#8202;&#10227;'
             "</span>", "pivot generation",
             "Patience ran out on a plateau: this generation was bred from "
             "far-apart parents to re-diversify the pool."),
    ]
    return '<div class="lgd">' + "".join(row1) + "</div>"


# -------------------------------------------------------------- the gallery --
def _inspiration_html(store: Store, run_id: str) -> str:
    """Collapsible block showing the user-supplied designer inspiration."""
    run = store.get_run(run_id)
    text = (run["inspiration_text"] or "").strip() if run else ""
    if not text:
        return ""
    return ('<details class="inspiration"><summary><b>designer inspiration'
            '</b> &middot; <code>'
            f'{html.escape(run["inspiration_path"] or "")}</code>'
            f'</summary><pre>{html.escape(text)}</pre></details>')


def write_gallery(store: Store, run_id: str, results_dir: Path,
                  target_whkm: float | None = None,
                  record_whkm: float | None = None) -> Path:
    cands = {r["hash"]: r for r in store.candidates_for_run(run_id)}
    gens = store.generations_with_population(run_id)
    scen_cache: dict[str, list] = {}

    finite = [(h, store.fitness_of(r)) for h, r in cands.items()
              if math.isfinite(store.fitness_of(r))]
    best_hash = min(finite, key=lambda t: t[1])[0] if finite else None
    n_valid = len(finite)
    # best-so-far setters: same visual language as the chart's black dots
    setter_hashes: set[str] = set()
    _rb = math.inf
    for _c in store.candidates_in_eval_order(run_id):
        _f = store.fitness_of(_c)
        if math.isfinite(_f) and _f < _rb:
            _rb = _f
            setter_hashes.add(_c["hash"])

    parts = ["<!doctype html>",  # quirks mode breaks color inheritance into tables
             f"<style>{CSS}</style>",
             '<meta charset="utf-8">',
             # auto-refresh is JS-based so an open overlay is never killed
             "<title>framevo gallery</title>",
             '<div class="wrap">',
             f"<h1>frame evolution &mdash; run <code>{html.escape(run_id)}</code></h1>",
             f'<p class="sub num">{len(gens)} generation(s) &middot; '
             f'{len(cands)} candidates ({n_valid} valid) &middot; '
             f'<a href="lineage.html">family tree</a> &middot; '
             f'<a href="glossary.html">glossary</a> &middot; '
             f'<span class="updated">regenerated {time.strftime("%H:%M:%S")}, '
             f'refreshes every 30&thinsp;s</span></p>',
             '<p class="sub intro">every candidate the run has flown, in '
             "evaluation order. Gray dots are evaluated designs &mdash; "
             "height is the aggregate energy score in Wh/km across all "
             "scenarios, lower is better. The black step line tracks the "
             "best so far, stepping down at each labeled improvement. Red "
             "&#215;&rsquo;s on the &#8734; row are invalid designs that "
             "failed a check and never flew. Click any black improvement "
             "dot to jump to that candidate&rsquo;s detail card below.</p>",
             _inspiration_html(store, run_id),
             _chart_legend_html(),
             f'<div class="chart-card">{progress_chart_svg(store, run_id, target_whkm, record_whkm)}</div>']

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
            cls = "card" + (" setter" if h in setter_hashes else "") + \
                (" champion" if h == best_hash else "") + \
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
            parts.append(
                f'<div class="{cls}">'
                f'<a href="#d-{h}" style="border:none"><img src="{img}" alt="{h}"></a>'
                f'<div class="hash">{h}</div>'
                f'<div class="agg num">{_fmt(fit)} <span class="unit">wh/km agg</span></div>'
                f"{fail}"
                f'<table class="sc">{sc_rows}</table>'
                "</div>")
            if h not in detail_ids:
                detail_ids.append(h)
        parts.append("</div>")

    # embedding a mesh blob for every candidate would make very long runs
    # enormous, so blobs are embedded by priority -- champion & setters,
    # recent generations, the strongest hundred, then everything else
    # (invalid included: the failures are instructive) newest first --
    # until the size budget is spent. Typical runs fit entirely; only very
    # long runs shed their oldest, weakest candidates.
    EMBED_BUDGET = 64 * 1024 * 1024
    prio: list[str] = []
    seen_p: set[str] = set()

    def _take(hashes) -> None:
        for hh in hashes:
            if hh in cands and hh not in seen_p:
                seen_p.add(hh)
                prio.append(hh)

    if best_hash:
        _take([best_hash])
    _take(sorted(setter_hashes, key=lambda hh: cands[hh]["generation_born"]))
    for g in reversed(gens[-3:]):
        _take(r["hash"] for r in store.population(run_id, g))
    ranked_all = sorted(((h, f) for h, f in
                         ((h, store.fitness_of(r)) for h, r in cands.items())
                         if math.isfinite(f)), key=lambda t: t[1])
    _take(h for h, _ in ranked_all[:100])
    _take(sorted((h for h in cands if h not in seen_p),
                 key=lambda hh: -(cands[hh]["generation_born"] or 0)))

    blob_texts: dict[str, str] = {}
    viewer_hashes: set[str] = set()
    used = 0
    for h in prio:
        if h in viewer_hashes:
            continue
        blob = _mesh_blob_for(results_dir, cands[h]["png_path"])
        if blob is None:
            continue
        cost = len(blob)
        # the compare tab needs the candidate's lineage root too
        root = _oldest_ancestor(cands, h)
        rblob = None
        if root and root not in viewer_hashes:
            rblob = _mesh_blob_for(results_dir, cands[root]["png_path"])
            if rblob is not None:
                cost += len(rblob)
        if used + cost > EMBED_BUDGET and viewer_hashes:
            break
        blob_texts[h] = blob
        viewer_hashes.add(h)
        if root and rblob is not None:
            blob_texts[root] = rblob
            viewer_hashes.add(root)
        used += cost

    parts.append("<h2>candidate details &amp; parentage</h2>")
    parts.append('<p class="sub" style="font-style:italic">click a model to '
                 "open it full-screen: tab 1 is the interactive 3D model, "
                 "tab 2 compares it side-by-side with the oldest ancestor of "
                 "its lineage, rotating in sync (very long runs shed the 3D "
                 "models of their oldest, weakest candidates first)</p>")
    blobs: list[str] = []
    embedded: set[str] = set()
    for h in detail_ids:
        c = cands[h]
        fit = store.fitness_of(c)
        invalid = not math.isfinite(fit)
        is_setter = h in setter_hashes or h == best_hash
        # invalid renders get a red diagonal cross drawn over them
        xo, xc = ('<span class="xed">', "</span>") if invalid else ("", "")
        img = _rel(results_dir, c["png_path"])
        blob = blob_texts.get(h)
        bottom = _bottom_png_for(results_dir, c["png_path"]) or img
        if blob is not None:
            if h not in embedded:
                blobs.append(f'<script type="application/json" id="m-{h}">{blob}</script>')
                embedded.add(h)
            root = _oldest_ancestor(cands, h)
            anc_attr = ""
            if root and root in viewer_hashes and root != h:
                rblob = blob_texts.get(root)
                if rblob is not None:
                    if root not in embedded:
                        blobs.append(f'<script type="application/json" '
                                     f'id="m-{root}">{rblob}</script>')
                        embedded.add(root)
                    rfit = store.fitness_of(cands[root])
                    anc_attr = (f' data-ancestor="m-{root}" data-anctitle='
                                f'"{root} · g{cands[root]["generation_born"]}'
                                f' · {_fmt(rfit)}"')
            setter_attr = ' data-setter="1"' if is_setter else ""
            viewer = (f'<div class="viewer"><div class="vr">{xo}'
                      f'<img class="peek" src="{bottom}" '
                      f'alt="{h}" data-mesh="m-{h}" data-title="{h}" '
                      f'data-fit="{_fmt(fit)}"{setter_attr}'
                      f'{anc_attr}>{xc}'
                      f'<div class="hint">click to open the 3D model</div></div>'
                      f"{_parts_legend_html()}</div>")
        else:
            viewer = (f'<div class="viewer"><div class="vr">{xo}'
                      f'<img src="{bottom}" alt="{h}">{xc}</div>'
                      f"{_parts_legend_html()}</div>")

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
        genes = describe_genome(json.loads(c["genome_json"]), c["material"])
        gene_rows = "".join(
            f"<tr><td>{html.escape(lab)}</td><td>{html.escape(val)}</td></tr>"
            for lab, val in genes)
        badge = ""
        if h == best_hash:
            badge = '<span class="chip champ">run champion</span>'
        elif h in setter_hashes:
            badge = '<span class="chip">new best when evaluated</span>'
        born = f"generation {c['generation_born']} via {c['operator']}"
        if invalid:
            metric_rows = [
                ("status", '<span style="color:var(--accent);font-style:'
                           'italic">invalid &mdash; '
                           f'{html.escape(c["failure_reason"] or "unknown")}'
                           "</span>"),
                ("energy score", "&#8734; (never flew the scenarios)"),
            ]
        else:
            metric_rows = [
                ("energy score", f"<b>{_fmt(fit)}</b> Wh/km"),
                ("scenario mean", f"{_fmt(c['mean_whkm'])} Wh/km"),
                ("worst scenario", f"{_fmt(c['worst_whkm'])} Wh/km"),
            ]
        metric_rows += [
            ("frame mass", f"{mass}&thinsp;g"),
            ("material", html.escape(c["material"] or "&mdash;")),
            ("born", born),
        ]
        headline = ('<table class="dt hd"><tr><th>metric</th><th>value</th>'
                    "</tr>" + "".join(
                        f"<tr><td>{k}</td><td class='num'>{v}</td></tr>"
                        for k, v in metric_rows) + "</table>")
        notes = ""
        for key, label, cls2 in (("hypothesis", "hypothesis", ""),
                                 ("method", "method", ""),
                                 ("result_note", "result", " res")):
            try:
                text = c[key]
            except (KeyError, IndexError):
                text = None
            if text:
                notes += (f'<div class="note{cls2}"><span class="nlab">'
                          f"{label}</span>{html.escape(text)}</div>")
        dcls = "detail" + (" setter" if is_setter else "") + \
            (" champion" if h == best_hash else "")
        gene_table = (f'<table class="dt"><tr><th>gene</th><th>value</th></tr>'
                      f"{gene_rows}</table>")
        if invalid:  # never flew: a scenario table would be a dead header
            tlab, tables = "genome", gene_table
        else:
            tlab = "scenario results &amp; genome"
            tables = (f'<table class="dt"><tr><th>scenario</th><th>wh/km</th>'
                      f"<th>avg power, w</th><th>max tilt</th><th></th></tr>"
                      f"{sc_rows}</table>" + gene_table)
        parts.append(
            f'<div class="{dcls}" id="d-{h}">'
            f'<div class="dhead">candidate <span class="hash">{h}</span>'
            f"{badge}</div>"
            f'<div class="dcols">'
            f"{viewer}"
            f'<div class="dmeta">'
            f"{headline}{notes}"
            f'<div class="tlab">{tlab}</div>'
            f'<div class="tables">{tables}</div>'
            f'</div><div class="parents">{parents_html}</div>'
            f"</div></div>")

    parts.append(
        '<div id="ovl">'
        '<div class="ovl-bar">'
        '<span class="ovl-tabs">'
        '<button data-tab="solo" class="on">3d model</button>'
        '<button data-tab="compare">compare with oldest ancestor</button>'
        '<button data-tab="diff">changed parts</button>'
        "</span>"
        '<span class="hash"></span>'
        '<button id="ovl-close" title="close (esc)">&#215;</button>'
        "</div>"
        f'<div class="ovl-lgd">{_parts_legend_html()}</div>'
        '<div class="ovl-body on" data-tab="solo" style="position:relative">'
        '<div class="pane"><canvas id="ovl-solo"></canvas></div>'
        '<div class="ovl-hint">drag to rotate &middot; &#8984;-drag pans '
        "&middot; scroll to zoom &middot; double-click resets &middot; "
        "esc closes</div></div>"
        '<div class="ovl-body" data-tab="compare" style="position:relative">'
        '<div class="pane"><div class="cap">oldest ancestor '
        '<span class="hash" id="anc-hash"></span></div>'
        '<canvas id="ovl-anc"></canvas></div>'
        '<div class="pane"><div class="cap">this candidate '
        '<span class="hash" id="cur-hash"></span></div>'
        '<canvas id="ovl-cur"></canvas></div>'
        '<div class="ovl-hint">the two models rotate and zoom in sync</div>'
        "</div>"
        '<div class="ovl-body" data-tab="diff" style="position:relative">'
        '<div class="pane"><div class="cap">evolved frame diff '
        '<span class="hash" id="diff-hash"></span>'
        '<span style="font-style:italic;text-transform:none;'
        'letter-spacing:0;font-weight:400">solid color = this candidate '
        "&middot; gray ghost = oldest ancestor &middot; fixed kit hidden"
        "</span></div>"
        '<canvas id="ovl-diff"></canvas></div>'
        '<div class="ovl-hint">only the parts evolution changes are shown, '
        "superimposed</div></div>"
        '<div class="ovl-views">'
        '<button data-view="fit" title="zoom to fit, keep orientation">fit</button>'
        '<button data-view="front">front</button>'
        '<button data-view="top">top</button>'
        '<button data-view="bottom">bottom</button>'
        '<button data-view="left">left</button>'
        '<button data-view="right">right</button>'
        '<button data-view="default" title="default view (double-click)">'
        "default</button></div>")
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
