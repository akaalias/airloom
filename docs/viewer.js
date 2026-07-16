
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
  "uniform float uF;"+ // per-model fade for cross-fade transitions
  "void main(){vec3 L=normalize(vec3(0.35,0.48,0.85));"+
  "float d=abs(dot(normalize(vN),L));float s=0.45+0.55*d;"+
  "gl_FragColor=vec4(vC.rgb*s+0.07,vC.a*uF);}";

// default camera: nose-side three-quarter view (the FPV camera faces the
// viewer); the pre-flip back view was DEF_YAW=-0.9
var DEF_YAW=Math.PI-0.9,DEF_PITCH=0.8;
// hover parallax: until the user's first real drag, a hovered canvas
// leans a few degrees toward the cursor -- a wordless hint that the
// view is live 3D. One drag anywhere retires the effect for the page.
var PARALLAX=!(window.matchMedia&&
  matchMedia("(prefers-reduced-motion: reduce)").matches);
var blobCache={};
// ---- on-demand mesh loading: payloads live in per-candidate
// frames/gen_XXXX/<hash>.mesh.js files (JSONP-style: they call
// airloomBlob(id, data)). <script src> injection works over BOTH file://
// (where fetch() is CORS-blocked) and GitHub Pages, so index.html stays
// small no matter how long the run gets.
var BLOBS={},BLOB_PENDING={};
var bsEl=document.getElementById("blob-src");
var BLOB_SRC=bsEl?JSON.parse(bsEl.textContent):{};
window.airloomBlob=function(id,data){
  BLOBS[id]=data;
  (BLOB_PENDING[id]||[]).forEach(function(r){r()});
  delete BLOB_PENDING[id];
};
function blobAvailable(id){ // known payload: loaded, lazy-loadable or inline
  return !!(id&&(BLOBS[id]||BLOB_SRC[id]||document.getElementById(id)));
}
function ensureBlobs(ids){ // resolve when every needed payload has arrived
  var need=[];
  ids.forEach(function(id){
    if(!id||BLOBS[id]||document.getElementById(id)||!BLOB_SRC[id])return;
    if(need.indexOf(id)<0)need.push(id);
  });
  return Promise.all(need.map(function(id){
    return new Promise(function(res){
      if(BLOB_PENDING[id]){BLOB_PENDING[id].push(res);return}
      BLOB_PENDING[id]=[res];
      var s=document.createElement("script");
      s.src=BLOB_SRC[id];
      s.onerror=function(){ // missing file: resolve anyway, viewer shows
        (BLOB_PENDING[id]||[]).forEach(function(r){r()}); // what it has
        delete BLOB_PENDING[id];
      };
      document.head.appendChild(s);
    });
  }));
}
// ---- flight telemetry loading: same JSONP pattern as the mesh payloads
var FLIGHTS={},FLIGHT_PENDING={};
var fsEl=document.getElementById("flight-src");
var FLIGHT_SRC=fsEl?JSON.parse(fsEl.textContent):{};
window.airloomFlight=function(h,scen,data){
  var k=h+"|"+scen;
  FLIGHTS[k]=data;
  (FLIGHT_PENDING[k]||[]).forEach(function(r){r()});
  delete FLIGHT_PENDING[k];
};
function ensureFlight(h,scen){
  var k=h+"|"+scen,src=(FLIGHT_SRC[h]||{})[scen];
  if(FLIGHTS[k]||!src)return Promise.resolve();
  return new Promise(function(res){
    if(FLIGHT_PENDING[k]){FLIGHT_PENDING[k].push(res);return}
    FLIGHT_PENDING[k]=[res];
    var s=document.createElement("script");
    s.src=src;
    s.onerror=function(){
      (FLIGHT_PENDING[k]||[]).forEach(function(r){r()});
      delete FLIGHT_PENDING[k];
    };
    document.head.appendChild(s);
  });
}
function decodeBlob(id){
  if(blobCache[id])return blobCache[id];
  var d=BLOBS[id];
  if(!d){ // inline <script type=application/json> fallback (old pages)
    var el=document.getElementById(id);
    if(!el)return null;
    d=JSON.parse(el.textContent);
  }
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
      uPn=gl.getUniformLocation(prog,"uPn"),uF=gl.getUniformLocation(prog,"uF");
  gl.enable(gl.DEPTH_TEST);
  gl.clearColor(1.0,1.0,0.973,1.0);
  var models=[]; // [{bufs, nf, nOpq}], shared center/scale from first
  var frame={c:[0,0,0],r:0.3};
  var view={
    canvas:canvas,
    loadBlob:function(id){view.load([{id:id}])},
    setPropAngle:function(theta){ // spin prop clusters; CW/CCW by diagonal
      for(var m3=0;m3<models.length;m3++){
        var pr=models[m3].prop;
        if(!pr)continue;
        var cs=[Math.cos(theta),Math.cos(-theta)],
            sn=[Math.sin(theta),Math.sin(-theta)];
        for(var v4=0;v4<pr.base.length;v4+=3){
          var q4=pr.cl[v4/3],dir=pr.spin[q4]>0?0:1;
          var dx4=pr.base[v4]-pr.cc[q4][0],dy4=pr.base[v4+1]-pr.cc[q4][1];
          pr.scr[v4]=pr.cc[q4][0]+cs[dir]*dx4-sn[dir]*dy4;
          pr.scr[v4+1]=pr.cc[q4][1]+sn[dir]*dx4+cs[dir]*dy4;
          pr.scr[v4+2]=pr.base[v4+2];
        }
        gl.bindBuffer(gl.ARRAY_BUFFER,models[m3].bufs.aP);
        gl.bufferData(gl.ARRAY_BUFFER,pr.scr,gl.DYNAMIC_DRAW);
      }
    },
    // fixedFrame: an optional pre-computed {c,r,mx,my,mz} shared across
    // several loads so swapping models never re-centers or re-fits the
    // camera (the walkthrough uses one frame for its whole chain)
    load:function(specs,fixedFrame){
      models=[];
      for(var i2=0;i2<specs.length;i2++){
        var sp=specs[i2],d2=decodeBlob(sp.id);
        if(!d2)continue;
        if(sp.evolved){
          if(!d2.ev)continue;
          models.push({bufs:upload(d2.ev.P,d2.ev.N,sp.ghost?d2.ev.Cg:d2.ev.Ce),
                       nf:d2.ev.nf,nOpq:sp.ghost?0:d2.ev.nf,
                       fade:sp.fade==null?1:sp.fade});
        }else if(sp.propSpin&&d2.nf>d2.nOpq){
          // flight tab: props are the (only) translucent tail of the
          // buffers -- split them into a dynamic model so setPropAngle can
          // spin each rotor about its own axis, diagonal pairs opposed
          models.push({bufs:upload(d2.P,d2.N,d2.C),nf:d2.nOpq,nOpq:d2.nOpq,
                       fade:sp.fade==null?1:sp.fade});
          var off=d2.nOpq*9,pP=d2.P.slice(off),pN=d2.N.slice(off),
              pC=d2.C.slice(d2.nOpq*12),np=pP.length/3;
          // assign blades to their 4 rotors: farthest-point seeding +
          // Lloyd iterations on (x,y) -- robust to any arm sweep, where a
          // naive quadrant split misassigns blades near the boundaries
          var seeds=[[pP[0],pP[1]]],v3,q3,s3;
          while(seeds.length<4){
            var bi=0,bd=-1;
            for(v3=0;v3<pP.length;v3+=3){
              var dmin=1e9;
              for(s3=0;s3<seeds.length;s3++){
                var ddx=pP[v3]-seeds[s3][0],ddy=pP[v3+1]-seeds[s3][1];
                var dd=ddx*ddx+ddy*ddy;
                if(dd<dmin)dmin=dd;
              }
              if(dmin>bd){bd=dmin;bi=v3}
            }
            seeds.push([pP[bi],pP[bi+1]]);
          }
          var cl=new Uint8Array(np),cc;
          for(var it=0;it<3;it++){
            cc=[[0,0,0],[0,0,0],[0,0,0],[0,0,0]];
            for(v3=0;v3<pP.length;v3+=3){
              var qb=0,qd=1e9;
              for(s3=0;s3<4;s3++){
                var qx=pP[v3]-seeds[s3][0],qy=pP[v3+1]-seeds[s3][1];
                var qq=qx*qx+qy*qy;
                if(qq<qd){qd=qq;qb=s3}
              }
              cl[v3/3]=qb;
              cc[qb][0]+=pP[v3];cc[qb][1]+=pP[v3+1];cc[qb][2]++;
            }
            for(s3=0;s3<4;s3++)if(cc[s3][2])
              seeds[s3]=[cc[s3][0]/cc[s3][2],cc[s3][1]/cc[s3][2]];
          }
          cc=seeds.map(function(s6){return [s6[0],s6[1]]});
          // counter-rotation by diagonal: sign from the quadrant of each
          // CLUSTER CENTER (not the vertex), so pairs stay consistent
          var spin=new Int8Array(4);
          for(s3=0;s3<4;s3++)
            spin[s3]=((cc[s3][0]>=0)===(cc[s3][1]>=0))?1:-1;
          // re-center each cluster on its HUB: the raw vertex centroid of
          // a decimated 3-blade prop sits off-axis (visible wobble); the
          // innermost blade-root vertices are symmetric about the shaft
          var rr=[0,0,0,0];
          for(v3=0;v3<pP.length;v3+=3){
            var qc=cl[v3/3];
            var rdx=pP[v3]-cc[qc][0],rdy=pP[v3+1]-cc[qc][1];
            var rd2=rdx*rdx+rdy*rdy;
            if(rd2>rr[qc])rr[qc]=rd2;
          }
          for(s3=0;s3<4;s3++){
            var rmax=Math.sqrt(rr[s3])||1,hx8=0,hy8=0,hn8=0;
            for(v3=0;v3<pP.length;v3+=3){
              if(cl[v3/3]!==s3)continue;
              var ex8=pP[v3]-cc[s3][0],ey8=pP[v3+1]-cc[s3][1];
              if(Math.sqrt(ex8*ex8+ey8*ey8)<rmax*0.3){
                hx8+=pP[v3];hy8+=pP[v3+1];hn8++;
              }
            }
            if(hn8>6){cc[s3][0]=hx8/hn8;cc[s3][1]=hy8/hn8}
          }
          var db={aP:gl.createBuffer(),aN:gl.createBuffer(),aC:gl.createBuffer()};
          gl.bindBuffer(gl.ARRAY_BUFFER,db.aP);
          gl.bufferData(gl.ARRAY_BUFFER,pP,gl.DYNAMIC_DRAW);
          gl.bindBuffer(gl.ARRAY_BUFFER,db.aN);
          gl.bufferData(gl.ARRAY_BUFFER,pN,gl.STATIC_DRAW);
          gl.bindBuffer(gl.ARRAY_BUFFER,db.aC);
          gl.bufferData(gl.ARRAY_BUFFER,pC,gl.STATIC_DRAW);
          models.push({bufs:db,nf:d2.nf-d2.nOpq,nOpq:0,
                       fade:sp.fade==null?1:sp.fade,
                       prop:{base:pP,cl:cl,cc:cc,spin:spin,
                             scr:new Float32Array(pP.length)}});
        }else{
          models.push({bufs:upload(d2.P,d2.N,d2.C),nf:d2.nf,nOpq:d2.nOpq,
                       fade:sp.fade==null?1:sp.fade});
        }
        var ext=sp.evolved?d2.ev:d2;
        if(fixedFrame)continue;
        if(i2===0){frame={c:d2.c,r:d2.r,mx:ext.mx,my:ext.my,mz:ext.mz}}
        else{frame.mx=Math.max(frame.mx,ext.mx);
             frame.my=Math.max(frame.my,ext.my);
             frame.mz=Math.max(frame.mz,ext.mz)}
      }
      if(fixedFrame)frame=fixedFrame;
      gl.uniform3f(uT,frame.c[0],frame.c[1],frame.c[2]);
    },
    setFade:function(i,v){if(models[i])models[i].fade=v},
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
      // the hover lean rides on top of the real camera and never
      // mutates it, so grabbing the model starts from where it looks
      var yw=state.yaw+(state.hovX||0),pt=state.pitch+(state.hovY||0);
      var cy2=Math.cos(yw),sy=Math.sin(yw),
          cp=Math.cos(pt),sp=Math.sin(pt);
      var Rb=[cy2,-sy*sp,sy*cp,
              sy,cy2*sp,-cy2*cp,
              0,cp,sp];
      gl.uniformMatrix3fv(uR,false,Rb);
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
        var mo=models[m2],fade=mo.fade==null?1:mo.fade;
        if(fade<=0.004)continue;
        // flight tab: pose the vehicle by telemetry attitude, but leave
        // world-frame models (weather particles) under the orbit alone
        var MR=mo.noPose?null:view.modelR;
        if(MR){
          var Cm=new Array(9);
          for(var mc=0;mc<3;mc++)for(var mr=0;mr<3;mr++)
            Cm[mc*3+mr]=Rb[mr]*MR[mc*3]+Rb[3+mr]*MR[mc*3+1]
                        +Rb[6+mr]*MR[mc*3+2];
          gl.uniformMatrix3fv(uR,false,Cm);
        }else{
          gl.uniformMatrix3fv(uR,false,Rb);
        }
        bindBuf(mo.bufs.aP,"aP",3);bindBuf(mo.bufs.aN,"aN",3);
        bindBuf(mo.bufs.aC,"aC",4);
        gl.uniform1f(uF,fade);
        if(fade<0.996){ // fading: draw everything blended, no depth writes
          gl.enable(gl.BLEND);
          gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
          gl.depthMask(false);
          gl.drawArrays(gl.TRIANGLES,0,mo.nf*3);
          gl.depthMask(true);
          continue;
        }
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
  // ease the hover lean toward its target; a tiny rAF loop that stops
  // itself the moment the offsets settle
  function hovTo(tx,ty){
    state.hovTX=tx;state.hovTY=ty;
    if(state.hovAnim)return;
    function step(){
      state.hovAnim=null;
      var dx=(state.hovTX||0)-(state.hovX||0),
          dy=(state.hovTY||0)-(state.hovY||0);
      if(Math.abs(dx)<0.0008&&Math.abs(dy)<0.0008){
        state.hovX=state.hovTX;state.hovY=state.hovTY;
        state.redraw();return}
      state.hovX=(state.hovX||0)+dx*0.10;
      state.hovY=(state.hovY||0)+dy*0.10;
      state.redraw();
      state.hovAnim=requestAnimationFrame(step);
    }
    state.hovAnim=requestAnimationFrame(step);
  }
  var dragging=false,panning=false,lastX=0,lastY=0;
  canvas.addEventListener("pointerdown",function(e){
    dragging=true;panning=e.metaKey||e.ctrlKey; // cmd/ctrl-drag pans
    // freeze the lean where it is: fold it into the real camera so the
    // grab starts from exactly what the eye sees, with no snap
    if(state.hovAnim){cancelAnimationFrame(state.hovAnim);state.hovAnim=null}
    state.yaw+=(state.hovX||0);state.pitch+=(state.hovY||0);
    state.hovX=state.hovY=state.hovTX=state.hovTY=0;
    lastX=e.clientX;lastY=e.clientY;
    canvas.setPointerCapture(e.pointerId);canvas.style.cursor="grabbing"});
  canvas.addEventListener("pointermove",function(e){
    if(!dragging){
      if(!PARALLAX)return;
      var r=canvas.getBoundingClientRect();
      hovTo(((e.clientX-r.left)/r.width-0.5)*0.12,
            ((e.clientY-r.top)/r.height-0.5)*0.08);
      return;
    }
    PARALLAX=false; // the invitation worked: the user is driving now
    if(panning){
      state.panX+=(e.clientX-lastX)*2/Math.max(1,canvas.clientWidth);
      state.panY-=(e.clientY-lastY)*2/Math.max(1,canvas.clientHeight);
    }else{
      state.yaw+=(e.clientX-lastX)*0.011;
      state.pitch=Math.max(-1.6,Math.min(1.6,state.pitch+(e.clientY-lastY)*0.011));
    }
    lastX=e.clientX;lastY=e.clientY;state.redraw()});
  canvas.addEventListener("pointerleave",function(){
    if(state.hovTX||state.hovTY||state.hovX||state.hovY)hovTo(0,0)});
  canvas.addEventListener("pointerup",function(){
    dragging=false;canvas.style.cursor="grab"});
  canvas.addEventListener("wheel",function(e){
    e.preventDefault();
    state.zoom=Math.max(0.3,Math.min(8,state.zoom*Math.exp(-e.deltaY*0.0016)));
    state.redraw()},{passive:false});
  canvas.addEventListener("dblclick",function(){state.reset()});
  return view;
}


// ---- lineage metadata: parent map + the run baseline (gen-0 winner);
// pages provide #walk-meta JSON and a window.BASELINE global
var wmetaEl=document.getElementById("walk-meta");
var WMETA=wmetaEl?JSON.parse(wmetaEl.textContent):{};
var BASELINE=typeof window.BASELINE==="string"?window.BASELINE:null;
function hasEvBlob(x){ // a mesh payload carrying the evolved-parts subset
  if(BLOBS["m-"+x])return !!BLOBS["m-"+x].pn;
  if(BLOB_SRC["m-"+x])return true; // lazy files always carry pn
  var el=document.getElementById("m-"+x);
  return !!el&&el.textContent.indexOf('"pn"')>=0;
}
function walkChainFor(h){
  // FULL ancestry via both parents (a primary-line walk dead-ends when
  // parent_a is a parentless designer/immigrant while the deep lineage
  // runs through parent_b), ordered oldest generation first, the
  // candidate itself last. Returns {all, steps}: every member for
  // timeline display, and the 3D-steppable subset.
  var seen={},stack=[h];
  while(stack.length){
    var cur=stack.pop();
    if(seen[cur])continue;
    seen[cur]=1;
    var m=WMETA[cur];
    if(!m)continue;
    if(m.p)stack.push(m.p);
    if(m.q)stack.push(m.q);
  }
  delete seen[h];
  // the baseline (gen-0 winner) leads every chain: it is the reference
  // the replay starts from and the trail is drawn against
  if(BASELINE&&BASELINE!==h)seen[BASELINE]=1;
  var anc=Object.keys(seen);
  anc.sort(function(a,b){
    var ga=(WMETA[a]||{}).g||0,gb=(WMETA[b]||{}).g||0;
    return ga-gb||(a<b?-1:1);
  });
  var bi=anc.indexOf(BASELINE);
  if(bi>0){anc.splice(bi,1);anc.unshift(BASELINE)}
  var all=anc.concat([h]);
  return {all:all,steps:all.filter(hasEvBlob)};
}
// one shared camera frame for a whole chain: common center + union of
// every member's extents, so stepping never re-centers or re-fits --
// only the actual geometry differences move
function chainFrame(chain){
  var cyw=Math.cos(DEF_YAW),syw=Math.sin(DEF_YAW);
  var ents=[],C=[0,0,0];
  chain.forEach(function(h){
    var e=decodeBlob("m-"+h);
    if(e&&e.ev)ents.push(e);
  });
  if(!ents.length)return null;
  ents.forEach(function(e){C[0]+=e.c[0];C[1]+=e.c[1];C[2]+=e.c[2]});
  C[0]/=ents.length;C[1]/=ents.length;C[2]/=ents.length;
  var mx=0,my=0,mz=0;
  ents.forEach(function(e){
    // extents are stored about the blob's own center in the DEF_YAW
    // frame; shift them by the rotated offset to the common center
    var dx=e.c[0]-C[0],dy=e.c[1]-C[1],dz=e.c[2]-C[2];
    var ox=Math.abs(cyw*dx+syw*dy),oy=Math.abs(cyw*dy-syw*dx);
    mx=Math.max(mx,e.ev.mx+ox);
    my=Math.max(my,e.ev.my+oy);
    mz=Math.max(mz,e.ev.mz+Math.abs(dz));
  });
  return {c:C,r:ents[0].r,mx:mx,my:my,mz:mz};
}
// lineage trail: every prior frame a gray ghost, depth-graded so the
// nearest parent is strongest and the oldest faintest; candidate solid
// LAST so it stays crisp on top of the stacked ghosts
function trailSpecs(chain){
  var n=chain.length,fs=[];
  for(var i=0;i<n-1;i++)
    fs.push({id:"m-"+chain[i],evolved:true,ghost:true,
             fade:n>2?0.35+0.65*i/(n-2):1});
  fs.push({id:"m-"+chain[n-1],evolved:true});
  return fs;
}
// ---- evolution replay component: steps through a candidate's ancestry
// from the baseline to the candidate, cross-fading between steps. Pages
// hand it their own canvas/timeline/label/prev/next elements.
function makeReplay(o){
  var state=makeState(o.pitch===undefined?1.2:o.pitch);
  var viewer=null,anim=null,timer=null,playBtn=null;
  var rep={state:state,chain:[],all:[],frame:null,idx:0};
  rep.redraw=function(){state.redraw()};
  function specs(k){
    var s=[{id:"m-"+rep.chain[k],evolved:true}];
    if(k+1<rep.chain.length)
      s.push({id:"m-"+rep.chain[k+1],evolved:true,ghost:true});
    return s;
  }
  function label(){
    var h=rep.chain[rep.idx],m=WMETA[h]||{};
    var t="step "+(rep.idx+1)+" of "+rep.chain.length+" · g"+m.g+
      (h===BASELINE?" · baseline":"")+
      " · "+h+(m.f?" · "+m.f+" Wh/km":" · invalid");
    if(rep.idx+1<rep.chain.length){
      var h2=rep.chain[rep.idx+1],m2=WMETA[h2]||{};
      t+="  —  ghost: g"+m2.g+" · "+h2.slice(0,8);
    }
    if(o.label)o.label.textContent=t;
    if(o.prev)o.prev.disabled=rep.idx===0;
    if(o.next)o.next.disabled=rep.idx>=rep.chain.length-1;
    if(o.timeline)
      o.timeline.querySelectorAll(".wthumb").forEach(function(b){
        var on=+b.dataset.k===rep.idx;
        b.classList.toggle("on",on);
        if(on)b.scrollIntoView({block:"nearest",inline:"nearest"});
      });
  }
  rep.stop=function(){
    if(!timer)return;
    clearInterval(timer);timer=null;
    if(playBtn){playBtn.innerHTML="&#9654;";playBtn.title="play"}
  };
  // autoplay: one step per beat, stops at the end or on any manual input
  rep.play=function(){
    if(!playBtn||rep.chain.length<2)return;
    if(rep.idx>=rep.chain.length-1)rep.go(0); // at the end: rewind first
    playBtn.innerHTML="&#10074;&#10074;";playBtn.title="pause";
    timer=setInterval(function(){
      if(rep.idx>=rep.chain.length-1){rep.stop();return}
      rep.go(rep.idx+1);
    },1600);
  };
  rep.go=function(k){
    if(k<0||k>=rep.chain.length||k===rep.idx||!viewer)return;
    if(anim){cancelAnimationFrame(anim);anim=null}
    var key=function(s){return s.id+(s.ghost?"|g":"|s")};
    var oldS=specs(rep.idx),newS=specs(k);
    var oldK={},newK={};
    oldS.forEach(function(s){oldK[key(s)]=1});
    newS.forEach(function(s){newK[key(s)]=1});
    rep.idx=k;
    // union of both steps' models: leavers fade out, joiners fade in
    var sp=[],fades=[];
    oldS.forEach(function(s){
      if(!newK[key(s)]){sp.push(s);fades.push([1,0])}});
    newS.forEach(function(s){
      sp.push(s);fades.push(oldK[key(s)]?[1,1]:[0,1])});
    viewer.load(sp.map(function(s,i){
      return {id:s.id,evolved:true,ghost:s.ghost,fade:fades[i][0]}}),
      rep.frame);
    label();
    var t0=null,DUR=950;
    function tick(ts){
      if(t0===null)t0=ts;
      var t=Math.min(1,(ts-t0)/DUR),e=t*(2-t); // ease-out
      fades.forEach(function(f,i){viewer.setFade(i,f[0]+(f[1]-f[0])*e)});
      state.redraw();
      if(t<1){anim=requestAnimationFrame(tick)}
      else{anim=null;viewer.load(specs(rep.idx),rep.frame);
        state.redraw()}
    }
    anim=requestAnimationFrame(tick);
  };
  rep.next=function(){rep.stop();rep.go(rep.idx+1)};
  rep.prev=function(){rep.stop();rep.go(rep.idx-1)};
  rep.open=function(h){ // false when there is nothing to replay
    if(!viewer)viewer=makeViewer(o.canvas,state);
    var c=walkChainFor(h);
    rep.all=c.all;rep.chain=c.steps;
    // need >=2 steppable frames AND the chain must reach the candidate
    if(!viewer||rep.chain.length<2||
       rep.chain[rep.chain.length-1]!==h){
      rep.chain=[];rep.frame=null;
      return false;
    }
    rep.stop();
    rep.idx=0;
    rep.frame=chainFrame(rep.chain);
    viewer.load(specs(0),rep.frame);
    state.reset();
    if(o.timeline){
      // timeline: play button + one thumbnail per lineage step
      // (meta values are trusted generator output: paths, hex, numbers)
      var stepIdx={};
      rep.chain.forEach(function(sh,si){stepIdx[sh]=si});
      var tp=['<button class="wplay" title="play">&#9654;</button>'];
      rep.all.forEach(function(th){
        var tm=WMETA[th]||{},ti=stepIdx[th];
        var lab=th===BASELINE?"base":"g"+tm.g;
        var tt=th+(th===BASELINE?" · baseline":"")+
          (tm.f?" · "+tm.f+" Wh/km":" · invalid");
        var inner=(tm.i?'<img src="'+tm.i+'" alt="'+th+
          '" loading="lazy" decoding="async">':"")+
          "<span>"+lab+"</span>";
        if(ti===undefined){ // ancestor without an embedded 3D model
          tp.push('<span class="wthumb off" title="'+tt+
            ' · no 3D model">'+inner+"</span>");
        }else{
          tp.push('<button class="wthumb" data-k="'+ti+'" title="'+tt+
            '">'+inner+"</button>");
        }
      });
      o.timeline.innerHTML=tp.join("");
      o.timeline.querySelectorAll(".wthumb").forEach(function(b){
        b.addEventListener("click",function(){
          rep.stop();rep.go(+b.dataset.k)});
      });
      playBtn=o.timeline.querySelector(".wplay");
      playBtn.addEventListener("click",
        function(){timer?rep.stop():rep.play()});
    }
    label();
    return true;
  };
  return rep;
}

window.AL={makeState:makeState,makeViewer:makeViewer,
  decodeBlob:decodeBlob,ensureBlobs:ensureBlobs,ensureFlight:ensureFlight,
  blobAvailable:blobAvailable,FLIGHTS:FLIGHTS,FLIGHT_SRC:FLIGHT_SRC,
  WMETA:WMETA,BASELINE:BASELINE,DEF_YAW:DEF_YAW,DEF_PITCH:DEF_PITCH,
  walkChainFor:walkChainFor,chainFrame:chainFrame,trailSpecs:trailSpecs,
  makeReplay:makeReplay};
})();
