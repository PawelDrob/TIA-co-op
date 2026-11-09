"""HTML for changed networks: before | after per network, LAD as TIA-style SVG, SCL as a side-by-side line diff.
Self-contained (inline CSS/JS, no fetches). fragment=True gives one <div class="ldiff"> with its own <style> and
<script>, scoped to .ldiff, to paste into a change-log page."""
import collections
import difflib
import os
import re
import sys
from html import escape, unescape
from urllib.parse import quote

from .render_lad import Layout
from .s7dcl import scl_lines
from .source import LEFT_OUT, UNREADABLE

WINCC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'TiaHmiGenerator')
if WINCC not in sys.path:
    sys.path.insert(0, WINCC)
from hmipreview import rail   # noqa: E402  the project tree, shared with the HMI preview

CSS = '\n' + rail.BASE_CSS    # the colours and font, shared with the HMI preview (hmipreview/static/ldiff.css)

# Inside a host page (one such page boxes every section, draws a grid on every cell, makes th text
# white): what the host sets on bare elements and on the text the fragment inherits stops at the fragment, back to
# the browser's defaults; the fragment's own rules below set its look.
CSS += """
.ldiff{text-align:left;text-transform:none;letter-spacing:normal;word-spacing:normal;text-indent:0;white-space:normal;
  word-break:normal;text-shadow:none}
.ldiff section{display:block;width:auto;max-width:none;margin:0;padding:0;border:0;border-radius:0;background:none;box-shadow:none}
.ldiff table{width:auto;max-width:none;margin:0;border:0;border-radius:0;border-collapse:separate;border-spacing:2px;
  table-layout:auto;background:none;box-shadow:none;font:inherit;color:inherit}
.ldiff thead,.ldiff tbody,.ldiff tfoot,.ldiff tr{vertical-align:middle;background:none;border:0}
.ldiff th,.ldiff td{padding:1px;border:0;background:none;box-shadow:none;font:inherit;color:inherit;text-align:inherit;
  vertical-align:inherit;white-space:inherit;text-transform:inherit;letter-spacing:inherit}
.ldiff a{margin:0;padding:0;border:0;background:none;font:inherit;text-transform:inherit;letter-spacing:inherit}
.ldiff button{display:inline-block;width:auto;height:auto;min-width:0;min-height:0;margin:0;border-radius:0;
  box-shadow:none;text-align:center;text-transform:none;letter-spacing:normal;word-spacing:normal;text-indent:0;
  text-shadow:none;vertical-align:baseline}
.ldiff svg{display:inline;max-width:none;max-height:none;overflow:hidden;vertical-align:baseline;fill:#000;stroke:none}
"""

CSS += """
.ldiff .bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;margin:6px 0 10px;font-size:12.5px;color:var(--muted)}
.ldiff .bar .k{display:inline-flex;align-items:center;gap:6px}
.ldiff .sw{display:inline-block;width:16px;height:11px;border:1px solid #8c8c8c}
.ldiff .sw.add{background:var(--add-bg)} .ldiff .sw.del{background:var(--del-bg)}
.ldiff .sw.chg{background:var(--chg-bg)}
.ldiff .sw.mov{background:var(--mov-bg)}
.ldiff button{font:12px "Segoe UI",Arial,sans-serif;color:#000;background:#f0f0f0;border:1px solid #adadad;padding:2px 10px;cursor:pointer}
.ldiff button:hover{background:#e5e5e5}
.ldiff .nw{border:1px solid var(--band);margin:10px 0;background:#fff}
.ldiff .nwh{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;background:var(--band);padding:3px 8px}
.ldiff .nwh b{font-size:13px}
.ldiff .nwh .tag{margin-left:auto;font:10.5px Consolas,monospace;color:var(--muted);letter-spacing:.05em}
.ldiff .panes{display:grid;grid-template-columns:1fr 1fr}
.ldiff .pane{min-width:0;border-right:1px solid var(--grid)}
.ldiff .pane:last-child{border-right:0}
.ldiff .pb{overflow:hidden;padding:4px 2px;box-sizing:border-box}
.ldiff .pb svg.lad{display:block;width:var(--fw,100%);height:auto;cursor:zoom-in}
.ldiff .nw.zoom .pb svg.lad{width:auto;max-width:none}
.ldiff .empty{padding:18px 12px;color:#8c8c8c;font-style:italic}
.ldiff table.scl{border-collapse:collapse;width:100%;font:12px/1.4 Consolas,"Courier New",monospace;table-layout:fixed}
.ldiff table.scl td{padding:0 6px;vertical-align:top;white-space:break-spaces;word-break:normal;overflow-wrap:anywhere;border:0}
.ldiff table.scl td.ln{width:3.2em;color:#8c8c8c;text-align:right;user-select:none;border-right:1px solid var(--grid);white-space:nowrap}
.ldiff table.scl td.del{background:var(--del-bg)} .ldiff table.scl td.ins{background:var(--add-bg)}
.ldiff table.scl td.del span{background:var(--del-word)} .ldiff table.scl td.ins span{background:var(--add-word)}
.ldiff table.scl td.nil{background:#f5f5f5}
.ldiff table.scl tr.skip td{background:var(--row);color:var(--muted);font:italic 11.5px "Segoe UI",Arial,sans-serif;text-align:center;cursor:pointer}
.ldiff table.scl tr.ctx{display:none}
.ldiff .nw.all table.scl tr.ctx{display:table-row} .ldiff .nw.all table.scl tr.skip{display:none}
"""

# Block header as TIA's "Block title:" band; tables as TIA's table editors: grey column heads,
# light grid, section rows in the field grey. Box columns as narrow as their headings' words; an interface table still
# wider than the report scrolls sideways in its frame, not the page (1000 px window, tree open).
CSS += """
.ldiff .blk{margin:16px 0 24px}
.ldiff .bh{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px;background:var(--band);border-bottom:1px solid #b2b2b2;
  padding:3px 8px}
.ldiff .bh b{font-size:15px}
.ldiff .bh .paths{margin-left:auto;font-size:12px;color:var(--muted);word-break:break-all}
.ldiff .bh .st{font:bold 11px Arial;padding:0 6px;border-radius:2px;color:#fff}
.ldiff .ver{font-weight:bold;white-space:nowrap} .ldiff .ver i{font:bold 10.5px Arial;color:var(--chg)}
.ldiff .ver i.rel{color:var(--add)}
.ldiff .lib{white-space:nowrap} .ldiff .lib.differs{background:var(--chg-bg);border:1px solid var(--chg);padding:0 5px}
.ldiff .bh .st.new{background:var(--add)} .ldiff .bh .st.deleted{background:var(--del)} .ldiff .bh .st.same{background:#8c8c8c}
.ldiff .bh .st.version{background:#6b6b6b} .ldiff .bh .st.moved{background:var(--mov)}
.ldiff section.blk.mvd.mvd{display:none}
.ldiff details.mvd{margin:8px 0} .ldiff details.mvd summary{cursor:pointer}
.ldiff details.oth summary{cursor:pointer} .ldiff details.oth>div{margin-top:6px;overflow-wrap:anywhere}
.ldiff .bh .nsh{background:var(--chg-bg);border:1px solid var(--chg);padding:0 5px}
.ldiff .bh .fa{display:inline-flex;gap:4px}
.ldiff .bh .fa button{padding:0 7px;font-size:11px;line-height:16px}
@media print{.ldiff .bh .fa{display:none}}
.ldiff table.sum{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0 4px}
.ldiff table.sum th{background:var(--band);font-weight:normal;text-align:left;padding:2px 8px;border:1px solid var(--line)}
.ldiff table.sum td{border:1px solid var(--grid);padding:2px 8px}
.ldiff table.sum a{color:#000;text-decoration:underline;text-decoration-color:#8c8c8c}
.ldiff table.itf{border-collapse:collapse;width:100%;font-size:12.5px}
.ldiff table.itf td{border-bottom:1px solid var(--row);padding:2px 8px;vertical-align:top;white-space:pre-wrap}
.ldiff table.itf tr.sec td{background:var(--field);border-top:1px solid var(--line)}
.ldiff table.itf td.nm{white-space:nowrap}
.ldiff table.itf tr.hd td{background:var(--row);font-size:11.5px;border-bottom:1px solid var(--line);white-space:normal;vertical-align:bottom}
.ldiff table.itf td.c{text-align:center;width:56px;padding:2px 4px} .ldiff table.itf tr.hd td.c{font-size:10.5px;line-height:1.2}
.ldiff .itfw{overflow-x:auto} @media print{.ldiff .itfw{overflow:visible}}
.ldiff table.itf .tw{display:inline-block;width:14px;font-size:11px}
.ldiff table.itf .cb{display:inline-block;width:12px;height:12px;border:1px solid #8c8c8c;border-radius:2px;background:#fff;vertical-align:-2px;position:relative}
.ldiff table.itf .cb.on{background:#2f7fd0;border-color:#1d5fa3}
.ldiff table.itf .cb.on::after{content:'';position:absolute;left:3.5px;top:0.5px;width:3px;height:7px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg)}
.ldiff table.itf .cb.dis{border-color:#b5b5b5;background:#e7e8e8} .ldiff table.itf .cb.dis.on{background:#f7f9fb;border-color:#7e7e7e} .ldiff table.itf .cb.dis.on::after{border-color:#666}
.ldiff table.itf .tx .cb{margin:0 3px}
.ldiff table.itf .dflt,.ldiff table.itf .inh{color:#8c8c8c}
.ldiff table.itf tr.skip td{text-align:left}
.ldiff table.itf tr.ins td{background:var(--add-bg)} .ldiff table.itf tr.del td{background:var(--del-bg)}
.ldiff table.itf tr.del td.nm{text-decoration:line-through}
.ldiff table.itf tr.chg td{background:#fffbe8}
.ldiff table.itf tr.mov td{background:#eef4fa;border-top:2px dashed var(--mov);border-bottom:2px dashed var(--mov)}
.ldiff table.itf td.dis{background-color:var(--field)}
.ldiff table.itf tr.ins td.dis,.ldiff table.itf tr.del td.dis,.ldiff table.itf tr.chg td.dis,.ldiff table.itf tr.mov td.dis{background-image:linear-gradient(#0000000f,#0000000f)}
.ldiff table.itf .ex{font-size:11.5px;color:var(--muted);white-space:normal}
.ldiff table.itf td.tn{white-space:nowrap} .ldiff table.itf tr.del td.tn>span{text-decoration:line-through}
.ldiff table tr.ctx{display:none}
.ldiff .nw.all table tr.ctx{display:table-row} .ldiff .nw.all table tr.skip{display:none}
.ldiff table tr.skip td{background:var(--row);color:var(--muted);font:italic 11.5px "Segoe UI",Arial,sans-serif;text-align:center;cursor:pointer}
"""

# Zoom like an image viewer (replaces an earlier zoom in the page): one scale per network for both
# ladders, from fit (0) up to 4x fit. The frames (.pb) keep their size, locked when the zoom starts; the picture
# zooms inside them (overflow hidden), so the page neither moves nor reflows and the plain wheel scrolls the page.
# A click zooms in 2x at that spot, a click on a zoomed ladder goes back to fit; Ctrl+wheel (a touchpad pinch too)
# zooms around the pointer, 1.25 per wheel notch, over every ladder, never the browser's page zoom there. The point
# under the mouse stays under it: the blank right of and below the widest and tallest ladder at fit stays as room
# to pan (margins, per frame: stacked in focus, the frames differ in height), so both panes have one
# scroll range. Both panes scroll in step, led by the pane the pointer is on (the other's own scroll events would
# set it back); 'ldiffzoom' updates the minimaps. Going back to fit keeps the spot too, where the frame still scrolls
# (a tall ladder in focus); on the page nothing scrolls at fit. n.ldiffFit goes back to the start.
# n.ldiffHalves: a text network's two tables, made in focus, take the place of the drawings for the scroll sync, the
# lead and the way back to the start; a text has no zoom.
JS = """
(function(){var r=document.currentScript&&document.currentScript.closest('.ldiff');if(!r)return;
r.querySelectorAll('.nw').forEach(function(n){
 var ss=[].slice.call(n.querySelectorAll('.pb svg.lad')),pb=n.querySelectorAll('.pb'),z=0,wide=1,tall=1,lead=null;
 ss.forEach(function(s){wide=Math.max(wide,+s.getAttribute('width'));tall=Math.max(tall,+s.getAttribute('height'))});
 ss.forEach(function(s){var g=tall-s.getAttribute('height');if(g)s.style.setProperty('--mb','min('+g+'px,'+100*g/wide+'%)')});
 function fit(){var p=ss[0].closest('.pb'),c=getComputedStyle(p);
  return Math.min(1,(p.clientWidth-parseFloat(c.paddingLeft)-parseFloat(c.paddingRight))/wide)}
 function above(v){return v>fit()*1.001}
 function low(k){return Math.min.apply(null,ss.map(function(s){return k(s.closest('.pb'))}))}
 function room(){var c=getComputedStyle(pb[0]),f=fit(),l=low(function(q){return q.getBoundingClientRect().height});
  pb.forEach(function(q){q._bx=q.clientWidth-parseFloat(c.paddingLeft)-parseFloat(c.paddingRight)-wide*f;
   q._by=Math.max(0,l-parseFloat(c.paddingTop)-parseFloat(c.paddingBottom)-tall*f)+q.getBoundingClientRect().height-l})}
 function draw(){ss.forEach(function(q){var w=+q.getAttribute('width'),h=+q.getAttribute('height');
   q.style.width=z?w*z+'px':'';q.style.maxWidth=z?'none':w+'px';
   var o=q.closest('.pb');q.style.marginRight=z?Math.max(0,(wide-w)*z+o._bx)+'px':'';
   q.style.marginBottom=z?Math.max(0,(tall-h)*z+o._by)+'px':''})}
 function set(v,p,e){var s=p.querySelector('svg.lad'),b=s.getBoundingClientRect(),fx=(e.clientX-b.left)/b.width,
  fy=(e.clientY-b.top)/b.height,nz=above(v)?v:0;lead=p;
  if(nz&&!z){pb.forEach(function(q){q.style.height=q.parentNode.getBoundingClientRect().bottom-q.getBoundingClientRect().top+'px'});room()}
  if(!nz)pb.forEach(function(q){q.style.height=''});
  z=nz;n.classList.toggle('zoom',z>0);draw();
  b=s.getBoundingClientRect();p.scrollLeft=p.scrollLeft+b.left+fx*b.width-e.clientX;
  p.scrollTop=p.scrollTop+b.top+fy*b.height-e.clientY;
  pb.forEach(function(q){q.scrollLeft=p.scrollLeft;q.scrollTop=p.scrollTop});
  n.dispatchEvent(new Event('ldiffzoom'))}
 ss.forEach(function(s){s.onclick=function(e){var p=s.closest('.pb');set(z?0:2*fit(),p,e)}});
 n.ldiffFit=function(){if(z)set(0,ss[0].closest('.pb'),{clientX:0,clientY:0});pb.forEach(function(q){q.scrollLeft=q.scrollTop=0})};n.ldiffScale=fit;
 n.ldiffResize=function(){var l=low(function(q){return q.clientHeight});
  ss.forEach(function(s){s.style.setProperty('--fh',s.closest('.pb').clientHeight-l+'px')});
  if(!z)return;var p=ss[0].closest('.pb'),o=p.getBoundingClientRect();
  if(!above(z)){set(0,p,{clientX:o.left+o.width/2,clientY:o.top+o.height/2});return}
  room();draw();n.dispatchEvent(new Event('ldiffzoom'))};
 n.ldiffLead=function(){return lead=ss[0].closest('.pb')};
 pb.forEach(function(p){if(!p.querySelector('svg.lad'))return;
  p.addEventListener('wheel',function(e){if(!e.ctrlKey)return;e.preventDefault();
   var f=fit(),c=z||f,v=c*Math.pow(1.25,-e.deltaY*(e.deltaMode==1?33:e.deltaMode==2?800:1)/100);
   v=Math.max(f,Math.min(4*f,v));if(Math.abs(v-c)>c*.001)set(v,p,e)},{passive:false})});
 function inStep(){pb.forEach(function(p){['pointerenter','pointerdown','wheel'].forEach(function(t){
   p.parentNode.addEventListener(t,function(){lead=p},{passive:true})});
  p.onscroll=function(){if(lead&&lead!=p)return;
   pb.forEach(function(q){if(q!=p){q.scrollLeft=p.scrollLeft;q.scrollTop=p.scrollTop}})}})}
 inStep();n.ldiffHalves=function(t){ss=t;pb=t.map(function(x){return x.closest('.pb')});inStep()};
 n.querySelectorAll('tr.skip').forEach(function(t){t.onclick=function(){n.classList.add('all')}})});
})();
"""

# Title bar and comment row before | after, each half over its pane; a changed title or comment marked
# as a changed SCL line, as is every changed text of the report (GitHub's style): a member's cell, a
# block property, an HMI text, the before and after in one cell (.tx); in print too, the browser's "Background
# graphics" or not. In print a block header, the Interface header, a title bar and a comment row
# stay with what follows, a LAD network that fits a page is not split (a longer one, SCL and the Interface table break
# where they must); a fold row says "N unchanged lines" without "(click to show all)".
CSS += """
.ldiff .nwt{position:relative;display:grid;grid-template-columns:1fr 1fr;background:#d9d9d9;padding:2px 0;
  font:13px/1.55 Consolas,"Courier New",monospace;color:#000;cursor:pointer;user-select:none}
.ldiff .nwt::before,.ldiff .ht::before{content:'';position:absolute;left:8px;top:50%;margin-top:-3px;border:5px solid transparent;
  border-top:6px solid #222;border-bottom:0}
.ldiff .nw.fold .nwt::before,.ldiff .hc.shut .ht::before{left:10px;margin-top:-5px;border:5px solid transparent;border-left:6px solid #222;border-right:0}
.ldiff .nwt .side{display:flex;align-items:stretch;min-width:0;padding:0 8px 0 24px}
.ldiff .nwt .no{font-weight:bold;background:#c3c3c3;padding:0 12px 0 6px;white-space:nowrap}
.ldiff .nwt .ti{flex:1 1 auto;min-width:0;background:#e1e1e1;padding:0 8px;white-space:pre-wrap}
.ldiff .nwt .st{align-self:center;margin-left:10px;font:bold 11px/1.4 Arial;padding:0 6px;border:1px solid #8c8c8c;
  border-radius:2px;color:#000}
.ldiff .nwt .st.new{background:var(--add-bg)} .ldiff .nwt .st.deleted{background:var(--del-bg)}
.ldiff .nwt .st.changed{background:var(--chg-bg)} .ldiff .nwt .st.moved{background:var(--mov-bg)}
.ldiff .nwc{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--grid)}
.ldiff .nwc .side{min-width:0;padding:4px 8px 5px 30px}
.ldiff .nwc .side+.side{border-left:1px solid var(--grid)}
.ldiff .nwc .cf{display:block;min-height:1.55em;background:var(--field);padding:0 8px;
  font:13px/1.55 Consolas,"Courier New",monospace;white-space:pre-wrap}
.ldiff .nwc .cf.none{color:#808080}
.ldiff .nwt .ti.del,.ldiff .nwc .cf.del{background:var(--del-bg)} .ldiff .nwt .ti.ins,.ldiff .nwc .cf.ins{background:var(--add-bg)}
.ldiff .nwt .ti.del span,.ldiff .nwc .cf.del span{background:var(--del-word)}
.ldiff .nwt .ti.ins span,.ldiff .nwc .cf.ins span{background:var(--add-word)}
.ldiff .tx{display:inline-block;max-width:100%;padding:0 3px} .ldiff .tx.del{background:var(--del-bg)}
.ldiff .tx.ins{background:var(--add-bg)}
.ldiff .tx.del span:not([class]){background:var(--del-word)} .ldiff .tx.ins span:not([class]){background:var(--add-word)}
@media print{.ldiff .ti.del,.ldiff .ti.ins,.ldiff .cf.del,.ldiff .cf.ins,.ldiff .tx,.ldiff table.scl td,.ldiff table.hd td,
  .ldiff table.itf tr td{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
.ldiff .nw.fold>:not(.nwt){display:none}
@media print{.ldiff .bh,.ldiff .nwh,.ldiff .nwt,.ldiff .nwc{break-inside:avoid;break-after:avoid}
  .ldiff .nw:has(>.panes:not(.txt)){break-inside:avoid} .ldiff tr.skip .hint{display:none}}
.ldiff .pane{position:relative}
.ldiff .nw.zoom .pb{cursor:grab}
.ldiff .nw.zoom .pb svg.lad{cursor:inherit}
.ldiff .nw.zoom .pb.drag{cursor:grabbing;user-select:none}
.ldiff .mm{position:absolute;right:22px;bottom:22px;background:#fff;border:1px solid #8c8c8c;opacity:.35;
  box-shadow:0 1px 4px rgba(0,0,0,.25);cursor:crosshair;transition:opacity .15s}
.ldiff .mm:hover{opacity:.92}
.ldiff .mm svg{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}
.ldiff .mm .vw{position:absolute;border:1.5px solid #3c3c3c;background:rgba(0,0,0,.08);pointer-events:none}
.ldiff .top{display:none;position:fixed;right:16px;bottom:16px;z-index:20;width:32px;height:32px;padding:0;
  box-shadow:0 1px 4px rgba(0,0,0,.25)}
.ldiff .top.show{display:block}
.ldiff .top::before{content:'';position:absolute;left:9px;top:8px;width:12px;border-top:2px solid #222}
.ldiff .top::after{content:'';position:absolute;left:9px;top:13px;border:6px solid transparent;
  border-bottom:7px solid #222;border-top:0}
"""

# Network title folds its network; a zoomed ladder pans by drag (both panes follow through the scroll sync above),
# a drag is never a click (zoomed or not); a minimap per pane that overflows, mostly transparent, updated on every
# zoom step; always on while zoomed (no Minimap button, no x), except on a frame lower than 120 px, where
# it would cover the spot just clicked. A press on a frame's own scrollbar is the browser's.
JS += """
(function(){var r=document.currentScript&&document.currentScript.closest('.ldiff');if(!r)return;
var drag=null;
window.addEventListener('mousemove',function(e){if(!drag)return;if(drag.go){drag.go(e);return}
 var dx=e.clientX-drag.x,dy=e.clientY-drag.y,p=drag.p;
 if(!drag.moved&&Math.abs(dx)+Math.abs(dy)>4){drag.moved=true;p.classList.add('drag')}
 if(drag.moved){p.scrollLeft=drag.l-dx;p.scrollTop=drag.t-dy}});
window.addEventListener('mouseup',function(){if(!drag)return;if(drag.p){drag.p.classList.remove('drag');drag.p._moved=drag.moved}drag=null});
function minimaps(n){var zm=n.classList.contains('zoom');
 n.querySelectorAll('.pane').forEach(function(pane){var p=pane.querySelector('.pb'),s=p&&p.querySelector('svg.lad');if(!s)return;
  if(!zm||p.clientHeight<120||(p.scrollWidth<=p.clientWidth+2&&p.scrollHeight<=p.clientHeight+2)){if(p._m)p._m.remove();p._m=p._mm=null;return}
  if(p._mm){p._mm();return}
  var m=document.createElement('div'),c=s.cloneNode(true),v=document.createElement('div'),k=1;
  c.removeAttribute('class');c.removeAttribute('style');m.className='mm';v.className='vw';
  m.appendChild(c);m.appendChild(v);pane.appendChild(m);p._m=m;
  p._mm=function(){var W=p.scrollWidth,H=p.scrollHeight;k=Math.min(200/W,130/H);m.style.width=W*k+'px';m.style.height=H*k+'px';
   var a=s.getBoundingClientRect(),o=p.getBoundingClientRect();c.style.left=(a.left-o.left+p.scrollLeft)*k+'px';
   c.style.top=(a.top-o.top+p.scrollTop)*k+'px';c.style.width=a.width*k+'px';c.style.height=a.height*k+'px';
   v.style.left=p.scrollLeft*k+'px';v.style.top=p.scrollTop*k+'px';
   v.style.width=Math.min(W,p.clientWidth)*k+'px';v.style.height=Math.min(H,p.clientHeight)*k+'px'};p._mm();
  function go(e){var b=m.getBoundingClientRect();p.scrollLeft=(e.clientX-b.left)/k-p.clientWidth/2;
   p.scrollTop=(e.clientY-b.top)/k-p.clientHeight/2}
  m.addEventListener('mousedown',function(e){if(e.button)return;e.preventDefault();go(e);drag={go:go}})})}
r.querySelectorAll('.nw').forEach(function(n){
 var t=n.querySelector('.nwt');if(t)t.addEventListener('click',function(){n.classList.toggle('fold')});
 n.querySelectorAll('.pb').forEach(function(p){
  p.addEventListener('scroll',function(){if(p._mm)p._mm()});
  p.addEventListener('mousedown',function(e){if(e.button||!p.querySelector('svg.lad'))return;var o=p.getBoundingClientRect();
   if(e.clientX>=o.left+p.clientLeft+p.clientWidth||e.clientY>=o.top+p.clientTop+p.clientHeight)return;e.preventDefault();p._moved=false;
   drag={p:p,x:e.clientX,y:e.clientY,l:p.scrollLeft,t:p.scrollTop,moved:false}});
  p.addEventListener('click',function(e){if(p._moved){p._moved=false;e.stopPropagation()}},true)});
 n.addEventListener('ldiffzoom',function(){minimaps(n)})});
r.querySelectorAll('section.blk').forEach(function(s){var f=s.querySelector('.bh .fa');if(!f)return;
 f.querySelectorAll('button').forEach(function(b,k){b.onclick=function(){s.querySelectorAll('.nw').forEach(function(n){
  if(n.querySelector('.nwt'))n.classList.toggle('fold',!k)})}})});
})();
"""

# Back to the top: bottom right, shown once the report's top is half a window above the view and the
# report still fills the lower half; up to the page top, in a fragment (no data-page) to the report's own top.
JS += """
(function(){var r=document.currentScript&&document.currentScript.closest('.ldiff');if(!r)return;
var b=r.querySelector('button.top');if(!b)return;
function show(){var t=r.getBoundingClientRect(),h=window.innerHeight;b.classList.toggle('show',t.top<-h/2&&t.bottom>h/2)}
document.addEventListener('scroll',show,{capture:true,passive:true});window.addEventListener('resize',show);show();
b.addEventListener('click',function(){if(r.hasAttribute('data-page'))window.scrollTo({top:0,behavior:'smooth'});
 else r.scrollIntoView({behavior:'smooth',block:'start'})})})();
"""

# Summary links: each to its own block, the ids unique in the report (block_keys). With a second
# report of the same block on the page (two fragments in one change log) the browser would go to the first element
# of that id: there the link scrolls to the header in its own report and sets the address itself (a history step,
# as a link's); a Ctrl / Shift / middle click stays the browser's.
JS += """
(function(){var r=document.currentScript&&document.currentScript.closest('.ldiff');if(!r)return;
r.querySelectorAll('table.sum a[href^="#blk-"]').forEach(function(a){a.addEventListener('click',function(e){
 var u=a.getAttribute('href'),id,h;try{id=decodeURIComponent(u.slice(1))}catch(x){return}
 h=[].filter.call(r.querySelectorAll('.bh[id]'),function(x){return x.id==id})[0];
 if(!h||document.getElementById(id)===h||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();
 if(location.hash!=u)history.pushState(null,'',u);h.scrollIntoView()})})})();
"""


WORD = re.compile(r'\d+(?:\.\d+)+|\w+|\s+|[^\w\s]')


def _inline(a, b):
    """Word-level highlight of one paired line (whitespace never highlighted); a number with points (1.5, 0.2.1)
    one word."""
    ta = WORD.findall(a)
    tb = WORD.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    oa, ob = [], []

    def mark(toks):
        return ''.join(escape(t) if t.isspace() else '<span>%s</span>' % escape(t) for t in toks)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            oa.append(escape(''.join(ta[i1:i2])))
            ob.append(escape(''.join(tb[j1:j2])))
        else:
            oa.append(mark(ta[i1:i2]))
            ob.append(mark(tb[j1:j2]))
    return ''.join(oa), ''.join(ob)


def _pair_lines(bl, al, i1, i2, j1, j2, minratio=0.5):
    """Rows of a replaced stretch: similar lines side by side (order kept, best total similarity), the others
    alone as (i, None) / (None, j)."""
    xs, ys = range(i1, i2), range(j1, j2)
    sim = {}
    for i in xs:
        for j in ys:
            r = difflib.SequenceMatcher(None, bl[i].strip(), al[j].strip(), autojunk=False).ratio()
            if r >= minratio:
                sim[i, j] = r
    best = {}
    for i in range(i2, i1 - 1, -1):
        for j in range(j2, j1 - 1, -1):
            if i == i2 or j == j2:
                best[i, j] = 0.0
                continue
            v = max(best[i + 1, j], best[i, j + 1])
            if (i, j) in sim:
                v = max(v, best[i + 1, j + 1] + sim[i, j])
            best[i, j] = v
    rows, i, j = [], i1, j1
    while i < i2 or j < j2:
        if i < i2 and j < j2 and (i, j) in sim and best[i, j] == best[i + 1, j + 1] + sim[i, j]:
            rows.append((i, j))
            i, j = i + 1, j + 1
        elif i < i2 and (j == j2 or best[i, j] == best[i + 1, j]):
            rows.append((i, None))
            i += 1
        else:
            rows.append((None, j))
            j += 1
    return rows


def scl_table(bl, al, context=3):
    """Before and after, a line of each side by side, a row per line: a long line folds in its row, with its one
    number."""
    rows = []                                   # (ctx?, lnb, cls_b, html_b, lna, cls_a, html_a)
    sm = difflib.SequenceMatcher(None, [l.rstrip() for l in bl], [l.rstrip() for l in al], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                rows.append([True, i + 1, '', escape(bl[i]), j + 1, '', escape(al[j])])
            continue
        for i, j in _pair_lines(bl, al, i1, i2, j1, j2):
            hb = escape(bl[i]) if i is not None else ''
            ha = escape(al[j]) if j is not None else ''
            if i is not None and j is not None:
                hb, ha = _inline(bl[i], al[j])
            rows.append([False, i + 1 if i is not None else '', 'del' if i is not None else 'nil', hb,
                         j + 1 if j is not None else '', 'ins' if j is not None else 'nil', ha])
    # context: unchanged rows near a change stay visible
    near = set()
    for k, r in enumerate(rows):
        if not r[0]:
            near.update(range(k - context, k + context + 1))
    out = []
    k = 0
    while k < len(rows):
        r = rows[k]
        if r[0] and k not in near:
            j = k
            while j < len(rows) and rows[j][0] and j not in near:
                j += 1
            out.append('<tr class="skip"><td colspan="4">⋯ %d unchanged line%s<span class="hint"> (click to show all)'
                       '</span></td></tr>'
                       % (j - k, '' if j - k == 1 else 's'))
            for r2 in rows[k:j]:
                out.append(_row(r2, 'ctx'))
            k = j
            continue
        out.append(_row(r, ''))
        k += 1
    cols = '<colgroup><col style="width:3.2em"><col><col style="width:3.2em"><col></colgroup>'
    return '<table class="scl side">%s%s</table>' % (cols, ''.join(out))


def _row(r, cls):
    return ('<tr%s><td class="ln lb">%s</td><td class="b %s">%s</td><td class="ln">%s</td><td class="%s">%s</td></tr>'
            % (' class="%s"' % cls if cls else '', r[1], r[2], r[3] or '&#8203;', r[4], r[5], r[6] or '&#8203;'))


def _lad_pane(lay, other, d, side=None):
    """One pane; in fit mode both panes of a network share one scale (width relative to the wider drawing). side:
    Layout.marks'."""
    if lay is None:
        return '<div class="empty">no network</div>'
    widest = max(lay.width, other.width if other else 0)
    svg = lay.svg(d.status, d.other, side=side, partner=other)
    natural = re.search(r' width="(\d+)"', svg).group(1)        # TIA's 100%: a narrow ladder is not blown up
    return svg.replace('<svg ', '<svg style="--fw:%.2f%%;max-width:%spx" ' % (100.0 * lay.width / widest, natural), 1)


def _fields(pair, attr, cls, empty=''):
    """The before and after field of a title or comment: the same text unmarked on both sides; a
    changed one as a changed SCL line, before marked removed, after added, the changed words highlighted; a side
    without the text TIA's empty field (`empty` in gray); a side without the network nothing."""
    b, a = pair.before, pair.after
    tb, ta = getattr(b, attr) if b else '', getattr(a, attr) if a else ''
    hb, ha, mb, ma = escape(tb), escape(ta), '', ''
    if b and a and tb != ta:
        hb, ha = _inline(tb, ta)
        mb, ma = ' del' if tb else '', ' ins' if ta else ''

    def field(net, text, html, mark):
        if not net:
            return None
        if not text and empty:
            return '<span class="%s none">%s</span>' % (cls, empty)
        return '<span class="%s%s">%s</span>' % (cls, mark, html)
    return field(b, tb, hb, mb), field(a, ta, ha, ma)


# The state tag of a network, in the legend's colours: changed, removed (a deleted network), new; an
# unchanged one (--all) none. A moved network also "moved", on both sides: "moved to 13"
# before, "moved from 11" after.
NET_TAG = {'changed': 'changed', 'deleted': 'removed', 'new': 'new'}


def _title_bar(pair):
    """TIA's title bar, before | after: "Network n:" and the title field on each side that has the network; the
    state tag on the after side, a deleted network's on the before side; a moved one's moved tag on each side."""
    state = pair.state
    badge = '<span class="st %s">%s</span>' % (state, NET_TAG[state]) if state in NET_TAG else ''
    moved = (('<span class="st moved">moved to %d</span>' % pair.after.index,
              '<span class="st moved">moved from %d</span>' % pair.before.index) if pair.moved else ('', ''))
    halves = []
    for net, ti, mv in zip((pair.before, pair.after), _fields(pair, 'title', 'ti'), moved):
        own = (badge if net is (pair.after or pair.before) else '') + mv
        halves.append('<span class="side">%s</span>'
                      % ('<span class="no">Network %d:</span>%s%s' % (net.index, ti, own) if net else ''))
    extra = ''.join('<span class="st moved">%s</span>' % text for text, on in (('other order', pair.reordered),
                                                                               (NET_NOT_SHOWN, pair.not_shown)) if on)
    if extra:
        halves[-1] = halves[-1][:-len('</span>')] + extra + '</span>'
    return '<div class="nwt">%s</div>' % ''.join(halves)


def _comment(pair):
    """TIA's comment row, before | after: the comment in its field, the gray "Comment" when there is none."""
    return '<div class="nwc">%s</div>' % ''.join(
        '<span class="side">%s</span>' % (f or '') for f in _fields(pair, 'comment', 'cf', 'Comment'))


def network_html(pair, bblock, ablock):
    b, a = pair.before, pair.after
    head = _title_bar(pair)
    if pair.lad is not None:
        lb = Layout(b.rungs, bblock.interface, bblock.callees, b.label, pair.label_state, pair.lad.other) if b else None
        la = Layout(a.rungs, ablock.interface, ablock.callees, a.label, pair.label_state, pair.lad.other) if a else None
        body = ('<div class="panes"><div class="pane"><div class="pb">%s</div></div>'
                '<div class="pane"><div class="pb">%s</div></div></div>'
                % (_lad_pane(lb, la, pair.lad, 'removed'), _lad_pane(la, lb, pair.lad, 'added')))
    else:
        bl = scl_lines(b.body) if b else []
        al = scl_lines(a.body) if a else []
        if b and a and b.lang != a.lang:
            bl = ['(%s network)' % b.lang] + bl
        body = scl_table(bl, al)
    return '<div class="nw">%s%s%s</div>' % (head, _comment(pair), body)


def _ver(v, released=False):
    state = ' <i>in work</i>' if v.in_work else ' <i class="rel">released</i>' if released else ''
    return '<span title="Author: %s">%s%s</span>' % (escape(v.author or '?'), escape(v.number), state)


def _released(vb, va):
    """A version in work came out released: the after export says so (TIA's .libinfo has IsDefault), at the same or a
    higher number. A lower one is a discard, back to an older version: nothing was released."""
    try:
        return vb.in_work and va.default and [int(x) for x in va.number.split('.')] >= [int(x) for x in vb.number.split('.')]
    except ValueError:
        return False


def version_html(vb, va):
    """Library type version before -> after (source.LibVersion, None when the block is no library type); one
    version when number and state (in work or not) are the same or only one side has one."""
    if not vb and not va:
        return ''
    if not vb or not va or (vb.number, vb.in_work) == (va.number, va.in_work):
        return '<span class="ver">%s</span>' % _ver(va or vb)
    return '<span class="ver">%s → %s</span>' % (_ver(vb), _ver(va, released=_released(vb, va)))


def library_html(d):
    """A program block that is the project instance of a library type: "library type Trolley 3.0.6 →
    3.0.7"; "differs from library type ..." (marked, explained on hover) when the type's change is another."""
    lib = d.library
    if lib is None:
        return ''
    if d.library_differs:
        tip = "This block's text is not the same as library type %s's. Compare the two entries in this report." % lib.name
        return '<span class="lib differs" title="%s">differs from library type %s %s</span>' % (
            escape(tip, quote=True), escape(lib.name), version_html(lib.ver_b, lib.ver_a))
    return '<span class="lib">library type %s %s</span>' % (escape(lib.name), version_html(lib.ver_b, lib.ver_a))


STATE_TEXT = {'version': 'version only'}
NOT_SHOWN = 'the file differs in something this report does not show'
NET_NOT_SHOWN = 'differs in something this report does not show'

# Collapse all / expand all: fold or unfold every network of the block, as a click on each title bar;
# in the block header, before the page's previous / next.
FOLD_ALL = ('<span class="fa"><button type="button" title="Collapse every network of this block">Collapse all</button>'
            '<button type="button" title="Expand every network of this block">Expand all</button></span>')


def block_keys(diffs):
    """The key of each block in the report: its name, a second one of the same name `name~2`; the
    tree's address and, as `blk-<key>`, the id of its header."""
    seen, keys = {}, []
    for d in diffs:
        name = d.block.name
        seen[name] = seen.get(name, 0) + 1
        keys.append(name if seen[name] == 1 else '%s~%d' % (name, seen[name]))
    return keys


ADDED_OR_REMOVED = ('new', 'deleted')     # a block's states drawn whole on one side, as added or as removed


def listed(d, full=False, draw_added_removed=True):
    """A block by its heading only, unless full: one whose library version alone changed, one that only moved, and
    with draw_added_removed False (--new-blocks-listed) a new or deleted one. The list and --json leave out what it
    leaves out."""
    return not full and (d.state in ('version', 'moved') or (d.state in ADDED_OR_REMOVED and not draw_added_removed))


def block_html(d, full=False, key=None, draw_added_removed=True):
    """One block: header, properties and interface when changed, the networks to show; listed() by its heading.
    A new block drawn shows its members and code as added, a deleted one as removed. key: from block_keys (default
    the name)."""
    from . import iface
    b = d.block
    head_only = listed(d, full, draw_added_removed)
    head = ('<div class="bh" id="blk-%s"><b>%s [%s%s]</b>%s%s<span class="paths">%s</span>%s</div>'
            % (escape(key or b.name), escape(d.name), escape(d.kind), escape(b.props.get('S7_BlockNumber') or ''),
               version_html(d.ver_b, d.ver_a) + library_html(d),
               ('<span class="nsh">%s</span>%s' % (NOT_SHOWN, '<span class="st moved">moved</span>' if d.moved else '')
                if d.not_shown else '') +
               ('' if d.state == 'changed' else '<span class="st %s">%s</span>' % (d.state, STATE_TEXT.get(d.state, d.state))),
               escape((d.path_b or '') if d.path_b == d.path_a else '%s → %s' % (d.path_b or '–', d.path_a or '–')),
               '' if head_only or not d.nets else FOLD_ALL))
    if head_only:
        return '<section class="blk%s">%s</section>' % (' mvd' if d.state == 'moved' else '', head)
    parts = [head]
    if d.props_changed:                                     # apart from the interface
        parts.append('<div class="nw itfw"><div class="nwh"><b>Properties</b></div>%s</div>'
                     % iface.props_html(d.before, d.after))
    texts = iface.block_texts_html(d.block, removed=d.state == 'deleted') if d.state in ADDED_OR_REMOVED else ''
    if texts:
        parts.append('<div class="nw itfw"><div class="nwh"><b>Properties</b></div>%s</div>' % texts)
    if d.declaration:
        parts.append('<div class="nw itfw"><div class="nwh"><b>Declaration</b></div>%s</div>'
                     % iface.declaration_html(*d.declaration))
    if d.itf_changed:                                      # also of a new or deleted block drawn: as the list says
        parts.append('<div class="nw itfw"><div class="nwh"><b>Interface</b><span class="tag">%s</span></div>%s</div>'
                     % ('DECLARATION', iface.html(d.before, d.after)))
    parts += [network_html(p, d.before or d.after, d.after or d.before) for p in d.nets]
    return '<section class="blk">%s</section>' % ''.join(parts)


def summary_html(diffs):
    """The Version column only when a block is a library type or the project instance of one."""
    vers = any(d.ver_b or d.ver_a or d.library for d in diffs)
    rows = []
    for d, key in zip(diffs, block_keys(diffs)):
        if d.state == 'moved':
            continue
        n = len([p for p in d.nets if p.state != 'same' or p.moved])
        rows.append('<tr><td><a href="#blk-%s">%s</a></td><td>%s</td>%s<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (quote(key, safe=''), escape(d.name), escape(d.kind),
                       '<td>%s</td>' % (version_html(d.ver_b, d.ver_a) + library_html(d)) if vers else '',
                       STATE_TEXT.get(d.state, d.state),
                       'changed' if d.itf_changed and d.state == 'changed' else '',
                       'changed' if d.props_changed or d.declaration else 'not shown' if d.not_shown else '',
                       n if d.state == 'changed' else ''))
    table = ('<table class="sum"><tr><th>Block</th><th>Type</th>%s<th>State</th><th>Interface</th><th>Properties</th>'
             '<th>Networks changed</th></tr>%s</table>' % ('<th>Version</th>' if vers else '', ''.join(rows))
             if rows else '')
    return table + _moved_html([d for d in diffs if d.state == 'moved'])


def _moved_html(moved):
    """The blocks that only moved to another folder: apart from the summary, collapsed, their old and new folder."""
    if not moved:
        return ''
    return ('<details class="mvd"><summary>Only moved to another folder: %d</summary><table class="itf"><tr class="hd"><td>'
            'Block</td><td>Type</td><td>From</td><td>To</td></tr>%s</table></details>'
            % (len(moved), ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                                   % (escape(d.name), escape(d.kind), escape(_folder_text(d.path_b)),
                                      escape(_folder_text(d.path_a))) for d in moved)))


LEGEND = ('<div class="bar"><span class="k"><span class="sw add"></span>added</span>'
          '<span class="k"><span class="sw del"></span>removed</span>'
          '<span class="k"><span class="sw chg"></span>changed</span>'
          '<span class="k"><span class="sw mov"></span>moved</span></div>')

# The column header: one for the whole report instead of a label per pane, each half over its column
# with the source of that side; it stays at the top while scrolling. Its grid and borders are the network frame's
# (.nw, .panes), so the halves line up with the panes; a block a summary link jumps to stops below it.
CSS += """
.ldiff .cols{position:sticky;top:0;z-index:10;display:grid;grid-template-columns:1fr 1fr;
  background:var(--row);border:1px solid var(--band);border-bottom-color:#b2b2b2;font-size:12.5px;color:var(--muted)}
.ldiff .cols .side{min-width:0;padding:3px 8px;word-break:break-all}
.ldiff .cols .side+.side{border-left:1px solid var(--grid)}
.ldiff .cols b{color:#000;font-weight:600;margin-right:8px}
.ldiff .bh{scroll-margin-top:32px}
"""


def columns_html(before_label, after_label):
    """The column header: "Before <source>" over the left column, "After <source>" over the right."""
    return '<div class="cols">%s</div>' % ''.join(
        '<div class="side"><b>%s</b>%s</div>' % (side, escape(label))
        for side, label in (('Before', before_label), ('After', after_label)))


# Project tree and one object at a time, the page only: a rail on the left (fixed, 260 px, its own
# scroll), collapsed by its button or Ctrl+B to a strip, open / closed kept in the browser. The tree shows TIA's
# names for the top folders and the repo's folders below them (TiaBridge mirrors TIA's tree). Each object is an
# address (report.html#Trolley; a summary link's #blk-Trolley opens it too): a click on it, back / forward, the buttons in the block header and Alt+Up / Alt+Down
# step through the objects in tree order; the page shows the one selected and keeps the scroll position of each.
# The summary table gives way to the tree. Print, PDF and `?all` (the --png shot) show every object in a row with
# the summary as the table of contents, as the fragment does. r.ldiffOpen(a) opens the object of a tree link.
# Search: a box above the tree filters it to the objects whose name has the letters typed in order
# (fuzzy, case-insensitive, spaces ignored); best matches first (CSS order, the tree's own order kept in the DOM;
# the best 200 ranked, the rest after them in tree order, so a one-letter search over 1500 objects stays fast),
# folders opened and counting their matches, the matched letters marked; Up / Down pick a match in the order shown,
# Enter or a click opens it, Esc clears. The score favours letters at word starts (start, after _ or a space, camel case, digits)
# and runs of letters, and penalises gaps; ties go to the shorter name, then to tree order.
# Lookup: one window over the page (LAUNCHER), r.ldiffLookup(c) fills it from a lookup c: its bar text
# (c.ph), c.load() the items as a source (r.ldiffSource: texts, numbers, items) and their rows, c.go(item) for Enter
# or a click; ranked by the same search (rank; a number typed matches an item's numbers first), the best 100 listed;
# Up / Down, Enter or a click, Esc or a click beside it closes. The program blocks (Ctrl+K or /), the networks of the
# open object (FOCUS_JS) and the list of keys (?) are such lookups.
# Keys: r.ldiffKey registers a key with its text for the list (?), one dispatcher runs them; none while
# typing in a text field (Esc there is the field's own). Not Alt+Space: Edge and Firefox open the window menu on it
# and the page never gets the Space; no Ctrl+N / T / W, which the browsers keep.
# The rail's style and script are the HMI preview's too: hmipreview/static/rail.css and rail.js.
RAIL_CSS = rail.CSS
RAIL_JS = rail.JS + "ldiffRail(document.currentScript&&document.currentScript.closest('.ldiff'));\n"

# A PLC's folders of a TiaBridge repo by TIA's names (system blocks hold TIA's `System blocks` folder), under plc/ or,
# with several PLCs, under plc/<device>/; the project library's types under library/types/.
PLC_ROOTS = {'blocks': 'Program blocks', 'systemblocks': 'Program blocks', 'technology': 'Technology objects',
             'tags': 'PLC tags', 'types': 'PLC data types'}
# The top folders, and a device's, in TIA's order: the devices (any other folder) before the library's types.
ORDER = {'Program blocks': 0, 'Technology objects': 1, 'PLC tags': 1.5, 'PLC data types': 2, 'Types': 4}


def _place(d):
    """The tree folders of an object, whether the first is a PLC device, and a note: TIA's name for the top folder
    (with several PLCs: the device, TIA's name below it), the repo's folders below it; a library type's own folder
    (`Trolley/Trolley.s7dcl`) left out, its released version (`Trolley.released/`) noted. A file without folders (a
    single-file comparison) sits at the top."""
    return _folders(d.path_a or d.path_b or d.block.name)


def _folder_text(path):
    return '/'.join(_folders(path)[0])


def _folders(path):
    folders = path.replace('\\', '/').split('/')
    stem = folders.pop().rsplit('.', 1)[0]
    note = ''
    if folders and folders[-1] in (stem, stem + '.released'):
        note = 'released' if folders.pop().endswith('.released') else ''
    if folders[:2] == ['library', 'types']:
        return ['Types'] + folders[2:], False, note
    if folders[:1] == ['plc'] and len(folders) > 1 and folders[1] in PLC_ROOTS:
        return [PLC_ROOTS[folders[1]]] + folders[2:], False, note
    if folders[:1] == ['plc'] and len(folders) > 2:
        return folders[1:2] + [PLC_ROOTS.get(folders[2], folders[2])] + folders[3:], True, note
    return folders, False, note


_tree_items = rail.tree_items


def _block_li(i, key, d, note):
    b = d.block
    moved = d.state == 'moved'
    note = ' '.join(x for x in (note, 'differs' if d.library_differs else '', 'moved' if moved else '',
                                'not shown' if d.not_shown else '') if x)
    where = '%s \u2192 %s' % (_folder_text(d.path_b), _folder_text(d.path_a)) if moved else ''
    kind = '[%s%s]%s' % (d.kind, b.props.get('S7_BlockNumber') or '', ' ' + note if note else '')
    return ('<li><a class="obj %s" href="#%s" data-i="%d" data-key="%s" title="%s"><span class="mk"></span>'
            '<span class="nm">%s</span><span class="k">%s</span></a></li>'
            % (d.state, quote(key, safe=''), i, escape(key),
               escape('%s: %s%s' % (where or d.path_a or d.path_b or b.name, STATE_TEXT.get(d.state, d.state),
                                    ('; ' + unescape(re.sub(r'<[^>]+>', '', library_html(d))) if d.library else '')
                                    + ('; ' + NOT_SHOWN if d.not_shown else ''))),
               escape(b.name), escape(kind)))


_node = rail.node


def tree_html(diffs, others=()):
    """The rail with the project tree of the objects on the page. An object's address is its name, a second one
    of the same name `name~2` (block_keys); data-i is its section on the page. others: objects of other kinds after
    the blocks (hmi.Item: folders, order of its device's folders, name, li(i))."""
    top = {'dirs': {}, 'objs': [], 'order': ORDER}
    for i, (d, key) in enumerate(zip(diffs, block_keys(diffs))):
        folders, device, note = _place(d)
        _node(top, folders, ORDER if device else None)['objs'].append((d.block.name, i, _block_li(i, key, d, note)))
    for i, x in enumerate(others, len(diffs)):
        _node(top, x.folders, x.order)['objs'].append((x.name, i, x.li(i)))
    _count_moved(top)
    return rail.nav_html(top)


def _count_moved(node):
    """A folder's count with its moved blocks apart, and a folder of moved blocks only collapsed. (others, moved)"""
    moved = sum('class="obj moved"' in o[2] for o in node['objs'])
    others = len(node['objs']) - moved
    for sub in node['dirs'].values():
        o, m = _count_moved(sub)
        others, moved = others + o, moved + m
    if moved:
        node['n'] = '%d + %d moved' % (others, moved) if others else '%d moved' % moved
        node['shut'] = not others
    return others, moved


# The lookup window, one for every lookup, outside the rail so that it shows with the rail
# collapsed; its bar text and rows set by RAIL_JS per lookup.
LAUNCHER = rail.LAUNCHER
LOADING = '<div class="ld" role="status">Loading the report (%d objects)…</div>'
WAIT_JS = """
(function(){var s=document.currentScript,r=s&&s.closest('.ldiff'),t=r&&r.querySelector('.rail .tree');if(!t)return;
if(/[?&]all(&|=|$)/.test(location.search)){r.classList.add('flat');return}
try{r.classList.toggle('rail-off',localStorage.getItem('ldiff-rail')=='off')}catch(e){}
var css=document.createElement('style');s.parentNode.insertBefore(css,s);r.classList.add('one','wait');
function pick(){if(!r.classList.contains('wait'))return;var objs=t.querySelectorAll('a.obj'),a=null,o,
  h=location.hash.replace(/^#/,'').replace(/\\/b?\\d+$/,'');try{h=decodeURIComponent(h)}catch(e){h=''}
 [h,h.replace(/^blk-/,'')].forEach(function(k){for(var j=0;j<objs.length&&!a;j++)if(objs[j].getAttribute('data-key')===k)a=objs[j]});
 a=a||[].filter.call(objs,function(x){return !x.classList.contains('moved')})[0]||objs[0];o=t.querySelector('a.obj.sel');if(o)o.classList.remove('sel');a.classList.add('sel');
 css.textContent='.ldiff.wait section.blk:nth-of-type('+(+a.getAttribute('data-i')+1)+'){display:block}'}
window.addEventListener('hashchange',pick);pick()})();
"""

# Focus, the page only: a button at the right of every network's title bar shows that network over the
# whole window, before | after as on the page, the column header on top; Esc or the button again puts it back and
# the page where it was. The network itself moves into the overlay (a placeholder of its height keeps the page), so
# zoom, Ctrl+wheel, drag and the minimap work there as on the page; it starts at fit (the ladders fit the wider
# panes) and goes back to fit. Its address is the object's and the network number of the after side, of the before
# side with b for a deleted network (#Trolley/59, #Trolley/b12): set while focused, opened straight into focus. A
# middle click on the button opens that address in a new window (a new tab when the browser gives no window).
# Stacked: a LAD network in focus shows before above after, each pane the full width (about twice the
# scale), its label ("Before <source>") in a strip at its left edge instead of the column header, its title line and
# comment (copies of its half of the title bar and comment row, made on the first focus) right above its
# render, a missing half none ("no network" alone); the focus and stack buttons stand at the top right; zoom, scroll
# sync, drag and the minimap as side by side. The button left of the focus button or S switches stacked / side by
# side, one choice for ladders and text, kept in the browser.
# A text network (SCL) stacked: its halves are made from the table on the first focus (halves(), class txt),
# so the page and paper keep the one table. One row per row of the table, the other side's added or removed line an empty
# row, each pair of rows at the taller's height (a line folds on one side only): the same line stands at the same place
# in both halves, and they scroll in step at one number per line; a higher frame keeps its difference as blank below its
# table, so one scroll range for both. A side the network does not have says "no network"; a network with no text on a
# side keeps its empty rows. Class lad on the overlay is what fills the window: a ladder always, text only stacked. Text
# side by side keeps its table in the scrolling overlay; its buttons stand on the column header, clear of the overlay's
# scrollbar and at the same place stacked, so a second click on the stack button goes back.
# A LAD network in focus fills the window, in both layouts: stacked one half each under its title line,
# side by side one column each under the column header, the title bar and the comment; whatever the network's size or
# the window's, no overlay scroll and no gutter around them (SCL side by side keeps both). A network taller than its frame scrolls
# inside it, at the fit scale (the frames' scrollbar place kept, so a tall and a short side keep one scale). One scroll
# range for both: a shorter ladder keeps the difference as blank below it (--mb), a higher frame its own difference
# (--fh, room to pan zoomed: n.ldiffResize, on every change of a frame's size, as a resize or a long comment). A long
# comment scrolls in its own place, at most 35 % of the network; stacked, a title and comment at most 45 % of the half.
# A new or deleted network: stacked, its one side takes the window but for the 64 px of the missing half; side by side
# the missing side keeps its column. Zoomed, a resize redoes the room to pan and the minimaps, back to fit when the
# window has outgrown the zoom. The arrows, Page Up / Down, Home, End, Space and T scroll the frames (fc.ldiffFrame),
# as they scrolled the overlay. The focus and stack buttons stand at the same place in both layouts, side by side on
# the column header, so a second click on the stack button goes back.
# The PNG (`?all&png`, the page flat): a LAD network drawn below 70 % side by side (fit, as the zoom's) is
# stacked the same way in the page (class stk on the network), the column header kept; the others side by side.
# Keys: F focuses the network under the pointer or the last one used (again: back); Ctrl+G or G opens
# the network lookup of the open object (title or number, either side), Enter opens that network in focus.
FOCUS_CSS = """
.ldiff.fxs .nwt .side+.side{padding-right:34px}
.ldiff .nwt .fx{position:absolute;right:5px;top:50%;width:24px;height:18px;margin-top:-9px;padding:0;
  display:flex;align-items:center;justify-content:center}
.ldiff .nwt .fl{position:absolute;right:33px;top:50%;width:24px;height:18px;margin-top:-9px;padding:0;
  display:none;align-items:center;justify-content:center}
.ldiff .nwt .fx svg,.ldiff .nwt .fl svg{fill:none;stroke:#222;stroke-width:1.5}
.ldiff .nwt .fx .i,.ldiff .fcs .nwt .fx .o{display:none} .ldiff .fcs .nwt .fx .i{display:inline}
.ldiff .nwph{margin:10px 0}
.ldiff .fcs{position:fixed;inset:0;z-index:35;overflow:auto;overscroll-behavior:contain;background:#fff;padding:0 16px 16px}
.ldiff .fcs[hidden]{display:none}
.ldiff .fcs:focus{outline:none}
.ldiff .fcs.lad .nwt .fl{display:flex} .ldiff .fcs.lad .nwt .side+.side{padding-right:8px}
.ldiff .nwt .fl .v,.ldiff .fcs.stk .nwt .fl .h{display:none} .ldiff .fcs.stk .nwt .fl .v{display:inline}
.ldiff .pane>.sl{display:none}
.ldiff .fcs.stk>.cols{display:none}
.ldiff .fcs.stk .nw>.nwt{z-index:5;display:block;height:0;padding:0;background:none}
.ldiff .fcs.stk .nw>.nwt::before,.ldiff .fcs.stk .nw>.nwt>.side,.ldiff .fcs.stk .nw>.nwc{display:none}
.ldiff .fcs.stk .nw>.nwt .fx,.ldiff .fcs.stk .nw>.nwt .fl{top:12px}
.ldiff .nw.stk>.nwt,.ldiff .nw.stk>.nwc{display:none}
.ldiff .pane>.sh{display:none}
.ldiff :is(.fcs.stk,.nw.stk) .pane>.sh{display:block}
.ldiff :is(.fcs.stk,.nw.stk) .sh .nwt,.ldiff :is(.fcs.stk,.nw.stk) .sh .nwc{grid-template-columns:1fr;cursor:auto;user-select:text}
.ldiff :is(.fcs.stk,.nw.stk) .sh .nwt::before{display:none}
.ldiff :is(.fcs.stk,.nw.stk) .sh .nwt .side{padding:0 8px 0 4px}
.ldiff .fcs.stk .pane:first-child .sh .nwt .side{padding-right:62px}
.ldiff :is(.fcs.stk,.nw.stk) .sh .nwc .side{padding:4px 8px 5px}
.ldiff :is(.fcs.stk,.nw.stk) .panes{grid-template-columns:1fr}
.ldiff :is(.fcs.stk,.nw.stk) .pane{min-height:64px;padding-left:22px;border-right:0}
.ldiff :is(.fcs.stk,.nw.stk) .pane+.pane{border-top:1px solid var(--line)}
.ldiff :is(.fcs.stk,.nw.stk) .pane>.sl{display:block;position:absolute;left:0;top:0;bottom:0;width:22px;padding:6px 0;
  writing-mode:vertical-rl;transform:rotate(180deg);text-align:end;background:var(--row);border-left:1px solid var(--grid);
  font-size:12px;line-height:21px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ldiff :is(.fcs.stk,.nw.stk) .pane>.sl b{color:#000;font-weight:600;margin-inline-end:8px}
.ldiff :is(.fcs.stk,.nw.stk) .empty{padding:4px 10px;font-size:11.5px}
.ldiff .fcs.lad{display:flex;flex-direction:column;overflow:hidden;padding:0}
.ldiff .fcs.lad>.cols{flex:none}
.ldiff .fcs.lad:not(.stk)>.cols .side+.side{padding-right:62px}
.ldiff .fcs.lad:not(.stk) .nw>.nwt .fx,.ldiff .fcs.lad:not(.stk) .nw>.nwt .fl{position:fixed;top:12px;z-index:11}
.ldiff .fcs.lad>.nw{flex:1 1 0;min-height:0;display:flex;flex-direction:column;margin:0}
.ldiff .fcs.lad .nw>.nwt{flex:none}
.ldiff .fcs.lad .nw>.nwc{flex:0 1 auto;min-height:0;max-height:35%;overflow:auto}
.ldiff .fcs.lad .panes{flex:1 1 0;min-height:0;grid-template-rows:minmax(0,1fr)}
.ldiff .fcs.stk .panes{grid-template-rows:minmax(0,1fr) minmax(0,1fr)}
.ldiff .fcs.stk .panes:has(>.pane:first-child>.pb>.empty){grid-template-rows:64px minmax(0,1fr)}
.ldiff .fcs.stk .panes:has(>.pane:last-child>.pb>.empty){grid-template-rows:minmax(0,1fr) 64px}
.ldiff .fcs.lad .pane{display:flex;flex-direction:column;min-height:0}
.ldiff .fcs.stk .pane>.sh{flex:none;max-height:45%;overflow:auto}
.ldiff .fcs.lad .pane>.pb{flex:1 1 0;min-height:0;overflow:auto;scrollbar-gutter:stable}
.ldiff .fcs.lad .nw:not(.zoom) .pb svg.lad{margin-bottom:calc(var(--mb,0px) + var(--fh,0px))}
.ldiff .nw>.panes.txt{display:none}
.ldiff .fcs.stk .nw>.panes.txt{display:grid}
.ldiff .fcs.stk .nw>table.scl{display:none}
.ldiff .fcs.txt .nwt .fl{display:flex} .ldiff .fcs.txt .nwt .side+.side{padding-right:8px}
.ldiff .fcs.txt .nw>.nwt .fx{right:37px} .ldiff .fcs.txt .nw>.nwt .fl{right:65px}
.ldiff .fcs.txt:not(.stk) .nw>.nwt .fx,.ldiff .fcs.txt:not(.stk) .nw>.nwt .fl{position:fixed;top:12px;z-index:11}
.ldiff .fcs.txt:not(.stk)>.cols .side+.side{padding-right:94px}
.ldiff .fcs.stk.txt .pane:first-child .sh .nwt .side{padding-right:94px}
@media print{.ldiff .nwt .fx,.ldiff .fcs{display:none!important} .ldiff.fxs .nwt .side+.side{padding-right:8px}}
"""

FOCUS_JS = """
(function(){var r=document.currentScript&&document.currentScript.closest('.ldiff');
if(!r||!r.querySelector('.rail'))return;var cols=r.querySelector('.cols');
if(r.classList.contains('flat')){if(/[?&]png(&|=|$)/.test(location.search))r.querySelectorAll('.nw').forEach(function(n){
 if(n.querySelector('.panes svg.lad')&&n.ldiffScale()<.7){n.classList.add('stk');labels(n)}});return}
var secs=[].slice.call(r.querySelectorAll('section.blk')),de=document.documentElement,cur=null,
 fc=document.createElement('div'),
 ico='<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path class="o" d="M1 4.5V1h3.5M7.5 1H11v3.5'+
  'M11 7.5V11H7.5M4.5 11H1V7.5"/><path class="i" d="M4.5 1v3.5H1M7.5 1v3.5H11M11 7.5H7.5V11M1 7.5h3.5V11"/></svg>';
var sized=new ResizeObserver(function(){if(cur&&fc.classList.contains('lad'))cur.n.ldiffResize()});
var stk=keep()!='0',sb=document.createElement('button');sb.type='button';sb.className='fl';
sb.innerHTML='<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path class="h" d="M1.5 1.5h9V5h-9zM1.5 7h9v3.5h-9z"/>'+
 '<path class="v" d="M1.5 1.5H5v9H1.5zM7 1.5h3.5v9H7z"/></svg>';
sb.onclick=function(e){e.stopPropagation();stack(!stk)};
function keep(v){try{if(v)localStorage.setItem('ldiff-stack',v);return localStorage.getItem('ldiff-stack')}catch(e){return null}}
function lay(){var w=cur&&cur.n.querySelector(':scope>.panes'),t=!!w&&w.classList.contains('txt'),lad=!!w&&(!t||stk);
 fc.classList.toggle('txt',t);fc.classList.toggle('lad',lad);fc.classList.toggle('stk',lad&&stk);
 sb.title=stk?'Before beside after (S)':'Before above after (S)';sb.setAttribute('aria-label',sb.title);
 sized.disconnect();if(lad)cur.n.querySelectorAll('.panes .pb').forEach(function(q){sized.observe(q)});if(t&&lad)cur.n.ldiffResize()}
function stack(v){stk=v;keep(v?'1':'0');if(cur&&cur.n.ldiffFit)cur.n.ldiffFit();lay();fc.scrollTop=0}
function halves(n){var t=n.querySelector(':scope>table.scl');if(!t||n.querySelector(':scope>.panes'))return;
 var h=n.querySelectorAll(':scope>.nwt>.side'),w=document.createElement('div'),tb=[],done='';w.className='panes txt';
 [0,1].forEach(function(s){var p=w.appendChild(document.createElement('div')),q=p.appendChild(document.createElement('div'));
  p.className='pane';q.className='pb';if(!h[s].firstChild){q.innerHTML='<div class="empty">no network</div>';return}
  var c=q.appendChild(document.createElement('table'));c.className='scl';
  c.innerHTML='<colgroup><col style="width:3.2em"><col></colgroup>';tb.push(c);
  [].forEach.call(t.rows,function(x){var r=c.insertRow(-1);r.className=x.className;
   if(x.cells.length==1){r.appendChild(x.cells[0].cloneNode(true)).colSpan=2;
    r.onclick=function(){n.classList.add('all');n.ldiffResize()};return}
   r.appendChild(x.cells[2*s].cloneNode(true));r.appendChild(x.cells[2*s+1].cloneNode(true))})});
 n.insertBefore(w,t);n.ldiffHalves(tb);
 n.ldiffResize=function(){var key=tb[0].clientWidth+(n.classList.contains('all')?'all':'');if(!tb[1])return;
  var l=Math.min(tb[0].parentNode.clientHeight,tb[1].parentNode.clientHeight);
  tb.forEach(function(c){c.style.marginBottom=c.parentNode.clientHeight-l+'px'});
  if(!tb[0].clientWidth||key==done)return;done=key;var a=tb[0].rows,b=tb[1].rows,o=[],k;
  for(k=0;k<a.length;k++)a[k].style.height=b[k].style.height='';
  for(k=0;k<a.length;k++)o[k]=Math.max(a[k].getBoundingClientRect().height,b[k].getBoundingClientRect().height);
  for(k=0;k<a.length;k++)a[k].style.height=b[k].style.height=o[k]+'px'}}
function labels(n){var t=n.querySelectorAll(':scope>.nwt>.side'),c=n.querySelectorAll(':scope>.nwc>.side');
 n.querySelectorAll('.panes>.pane').forEach(function(p,i){var d=cols&&cols.children[i];if(p.querySelector('.sl,.sh'))return;
 if(t[i]&&t[i].firstChild){var h=document.createElement('div');h.className='sh';
  [t[i],c[i]].forEach(function(x,k){var w=document.createElement('div');w.className=k?'nwc':'nwt';
   if(x)w.appendChild(x.cloneNode(true));h.appendChild(w)});
  p.insertBefore(h,p.querySelector('.pb'))}
 if(!d)return;var l=document.createElement('div');l.className='sl';l.innerHTML=d.innerHTML;
 l.title=[].map.call(d.childNodes,function(x){return x.textContent}).join(' ');p.insertBefore(l,p.firstChild)})}
fc.className='fcs';fc.hidden=true;fc.tabIndex=-1;fc.setAttribute('role','dialog');fc.setAttribute('aria-label','Network in focus');
if(cols)fc.appendChild(cols.cloneNode(true));r.appendChild(fc);
function num(n){var s=n.querySelectorAll('.nwt>.side'),a=s[1]&&s[1].querySelector('.no'),b=s[0]&&s[0].querySelector('.no');
 return a?a.textContent.replace(/\\D/g,''):b?'b'+b.textContent.replace(/\\D/g,''):''}
function title(b,on){b.setAttribute('aria-pressed',on?'true':'false');
 b.title=on?'Back to the page (Esc or F)':'Focus: this network over the whole window (F; middle click: in a new window)'}
function open(n,url){var b=n.querySelector('.nwt .fx'),ph=document.createElement('div');close(true);last=n;
 if(n.ldiffFit)n.ldiffFit();ph.className='nwph';ph.style.height=n.offsetHeight+'px';
 cur={n:n,ph:ph,y:window.scrollY,url:url,fold:n.classList.contains('fold'),ov:de.style.overflow,pre:'Network '+n.num.replace('b','')+' - '};
 n.parentNode.replaceChild(ph,n);n.classList.remove('fold');fc.appendChild(n);fc.hidden=false;de.style.overflow='hidden';
 halves(n);if(n.querySelector(':scope>.panes')){labels(n);n.querySelector('.nwt').appendChild(sb)}lay();
 fc.scrollTop=0;title(b,true);document.title=cur.pre+document.title;
 if(location.hash!=n.addr)history.replaceState(history.state,'',n.addr);fc.focus({preventScroll:true})}
function close(quiet){if(!cur)return;var c=cur,n=c.n;cur=null;if(n.ldiffFit)n.ldiffFit();
 if(sb.parentNode)sb.parentNode.removeChild(sb);lay();
 c.ph.parentNode.replaceChild(n,c.ph);n.classList.toggle('fold',c.fold);fc.hidden=true;de.style.overflow=c.ov;
 title(n.querySelector('.nwt .fx'),false);if(document.title.indexOf(c.pre)==0)document.title=document.title.slice(c.pre.length);
 if(quiet)return;history.replaceState(history.state,'',n.addr.replace(/\\/b?\\d+$/,''));
 window.scrollTo(0,c.url?n.getBoundingClientRect().top+window.scrollY-40:c.y);n.querySelector('.nwt .fx').focus({preventScroll:true})}
function pop(n){var u=location.href.split('#')[0]+n.addr,w=null;
 try{w=window.open(u,'_blank','popup,left=0,top=0,width='+screen.availWidth+',height='+screen.availHeight)}catch(e){}
 if(!w)window.open(u,'_blank')}
function target(){var m=/\\/(b?\\d+)$/.exec(location.hash),s=r.querySelector('section.blk.on');if(!m||!s)return null;
 if(cur&&cur.n.num==m[1]&&location.hash==cur.n.addr)return cur.n;
 return [].filter.call(s.querySelectorAll('.nw'),function(n){return n.num==m[1]})[0]||null}
function about(n){var s=n.querySelectorAll('.nwt>.side'),no=[].map.call(s,function(x){var e=x.querySelector('.no');
  return e?e.textContent.replace(/\\D/g,''):''}),t=s[no[1]?1:0].querySelector('.ti'),g=s[no[1]?1:0].querySelectorAll('.st');
 return {t:t?t.textContent:'',n:no.filter(String),
  g:g.length?[g[0].classList[1],[].map.call(g,function(x){return x.textContent}).join(', ')]:null,
  k:'Network '+(no[0]&&no[1]&&no[0]!=no[1]?no[0]+' | '+no[1]:no[1]||no[0])}}
var last=null;
secs.forEach(function(s,i){var a=r.querySelector('.tree a.obj[data-i="'+i+'"]');s.nets=[];if(!a)return;
 s.querySelectorAll('.nw').forEach(function(n){var t=n.querySelector('.nwt');if(!t)return;
  var b=document.createElement('button');b.type='button';b.className='fx';b.innerHTML=ico;title(b,false);t.appendChild(b);
  n.num=num(n);n.addr=a.getAttribute('href')+'/'+n.num;n.lk=about(n);s.nets.push(n);
  n.addEventListener('pointerover',function(){last=n});
  b.onclick=function(e){e.stopPropagation();if(cur&&cur.n==n)close();else open(n)};
  b.onmousedown=function(e){if(e.button==1)e.preventDefault()};
  b.addEventListener('auxclick',function(e){if(e.button!=1)return;e.preventDefault();e.stopPropagation();pop(n)})})});
r.classList.add('fxs');
document.addEventListener('keydown',function(e){if(cur&&e.key=='Escape'&&!e.defaultPrevented){e.preventDefault();close()}});
function shown(){var s=r.querySelector('section.blk.on');return s?s.nets:[]}
var nets={ph:'Lookup networks...',none:'No network found',go:function(n){if(!cur||cur.n!=n)open(n)},
 load:function(){var ns=shown();return {s:r.ldiffSource(ns.map(function(n){return n.lk.t}),ns.map(function(n){return n.lk.n}),ns),
  row:function(k){var l=ns[k].lk;return ['net',l.k,'',l.g]}}}};
r.ldiffKey({o:6,show:'F',text:'Focus: the network under the pointer or the last one used; again: back to the page',keys:['f'],
 run:function(){if(cur){close();return}var ns=shown(),h=window.innerHeight;if(!ns.length)return;
  open(ns.indexOf(last)>=0?last:ns.filter(function(n){var b=n.getBoundingClientRect();return b.bottom>40&&b.top<h})[0]||ns[0])}});
r.ldiffKey({o:7,show:'S',text:'In focus: before above after, or beside it',keys:['s'],
 when:function(){return !!cur&&!!cur.n.querySelector(':scope>.panes')},run:function(){stack(!stk)}});
r.ldiffKey({o:10,show:'Ctrl+G or G',text:'Lookup networks of this object',keys:['Ctrl+g','g'],run:function(){r.ldiffLookup(nets)}});
window.addEventListener('hashchange',function(){var t=target();if(t&&cur&&t==cur.n)return;close(true);if(t)open(t,true)});
window.addEventListener('beforeprint',function(){close()});
fc.ldiffFrame=function(){return cur&&fc.classList.contains('lad')?cur.n.ldiffLead():null};
fc.addEventListener('keydown',function(e){var k=e.key,sp=k==' '&&!e.target.closest('button');if(e.ctrlKey||e.altKey||e.metaKey||
  !(sp||/^(Arrow(Up|Down|Left|Right)|Page(Up|Down)|Home|End)$/.test(k)))return;var p=fc.ldiffFrame();if(!p)return;
 var h=p.clientHeight*.9,a=sp?[0,e.shiftKey?-h:h]:{ArrowDown:[0,40],ArrowUp:[0,-40],ArrowRight:[40,0],ArrowLeft:[-40,0],PageDown:[0,h],PageUp:[0,-h],
  Home:[0,-p.scrollHeight],End:[0,p.scrollHeight]}[k];
 e.preventDefault();p.scrollLeft+=a[0];p.scrollTop+=a[1]});
var t=target();if(t)open(t,true)})();
"""


def _not_compared_html(files):
    """A note per kind of reason with its paths, each once: a file can be named from both sides, with two reasons. Not
    the reasons themselves: one can hold a path of this PC. An export named as not read may be one whose .s7res or
    .libinfo could not be read."""
    notes = {}
    for path, why in files:
        note = ('Left out of this comparison, not in a folder the bridge exports to' if why == LEFT_OUT else
                'Not compared, could not be read and may hold a change' if why.startswith(UNREADABLE) else
                'Not compared, no block export though a block is in it')
        notes.setdefault(note, {})[path] = True
    return ''.join('<div class="empty">%s: %s</div>' % (note, escape(', '.join(paths))) for note, paths in notes.items())


FROM_COMMITS = ('This report reads what was exported and committed to a git repo. A change in TIA that was never exported '
                'and committed is not in it.')
FROM_WORKING_TREE = 'This report reads what was exported to a git repo. A change in TIA that was never exported is not in it.'


OTHER_FILES_SHOWN = 10                                  # more fold behind a count per kind


def _other_files_html(paths):
    """The line "n other files changed, not read" with the paths; over OTHER_FILES_SHOWN of them, a count per kind
    (the extension, else the file name) and the paths folded open on a click."""
    head = '%d other file%s changed, not read: ' % (len(paths), '' if len(paths) == 1 else 's')
    names = escape(', '.join(paths))
    if len(paths) <= OTHER_FILES_SHOWN:
        return '<div class="empty">%s%s</div>' % (head, names)
    kinds = collections.Counter(os.path.splitext(p)[1].lower() or p.rsplit('/', 1)[-1] for p in paths)
    count = ', '.join('%d %s' % (n, kind) for kind, n in sorted(kinds.items(), key=lambda x: (-x[1], x[0])))
    return ('<details class="empty oth"><summary>%s%s</summary><div>%s</div></details>'
            % (head, escape(count), names))


def render(diffs, before_label, after_label, fragment=False, title=None, full=False, hmi=None, lang='en-US',
           draw_added_removed=True, plc_tags=None, not_compared=(), source_note=None, other_files=()):
    """diffs: [compare.BlockDiff]. fragment: only the <div class="ldiff"> (with its style and script). hmi: an
    hmi.HmiPart, its objects after the blocks (tree, sections, summary). draw_added_removed: as listed(). plc_tags: a
    plctags.PlcTagPart, its tables between the blocks and the HMI objects. not_compared: [(path, why)] of the files
    not compared: named, and the page does not say "No changes." over them. source_note: stands
    under the page's title, what a report of a git repo cannot see. other_files: the changed files it does not read
    (otherfiles.py), the same as not_compared."""
    from . import hmi as hmipart
    others = (plc_tags.items if plc_tags else []) + (hmi.items if hmi else [])
    n = len(diffs) + len(others)
    body = [columns_html(before_label, after_label), LEGEND]
    if len(diffs) > 1 or (diffs and others) or any(d.state == 'moved' for d in diffs):
        body.append(summary_html(diffs))
    if len(others) > 1 or (diffs and others):
        body += [part.summary_html() for part in (plc_tags, hmi) if part]
    body += [block_html(d, full, k, draw_added_removed) for d, k in zip(diffs, block_keys(diffs))]
    body += [part.sections_html() for part in (plc_tags, hmi) if part]
    if not_compared:
        body.append(_not_compared_html(not_compared))
    if other_files:
        body.append(_other_files_html(other_files))
    if not (n or not_compared or other_files):
        body.append('<div class="empty">No changes.</div>')
    body.append('<button type="button" class="top" title="Back to top" aria-label="Back to top"></button>')
    rail = (tree_html(diffs, others) + LAUNCHER + LOADING % n + '<script>%s</script>' % WAIT_JS
            if n and not fragment else '')
    frag = '<div class="ldiff"%s><style>%s</style>%s%s%s<script>%s</script></div>' % (
        '' if fragment else ' data-page', CSS + (RAIL_CSS + FOCUS_CSS if rail else '') + (hmipart.css() if hmi else ''),
        rail, ''.join(body), hmi.data_html(lang) if hmi else '',
        JS + (RAIL_JS + FOCUS_JS if rail else '') + (hmipart.js() if hmi else ''))
    if fragment:
        return frag
    if not title:
        title = (('%s changes' % diffs[0].block.name) if len(diffs) == 1 and not others else
                 'Block changes' if not others else 'Changes' if diffs or (hmi and plc_tags) else
                 'HMI changes' if hmi else 'PLC tag changes')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>%s</title><style>'
            'body{margin:0;background:#fff;font:13px/1.45 "Segoe UI",Arial,Helvetica,sans-serif;color:#000}'
            'main{padding:0 16px 40px}'
            'header{background:#f0f0f0;border-bottom:1px solid #c8c8c8;margin:0 -16px 8px;padding:8px 16px}'
            'h1{font-size:17px;margin:0}header p{margin:2px 0 0}'
            'main:has(>.ldiff>.rail){margin-left:260px}main:has(>.ldiff.rail-off){margin-left:28px}'
            'main:has(>.ldiff.flat){margin-left:0}@media print{main{margin-left:0!important}}@page{size:A4 landscape}'
            '</style></head><body><main><header><h1>%s</h1>%s</header>%s</main></body></html>'
            % (escape(title), escape(title), '<p>%s</p>' % source_note if source_note else '', frag))
