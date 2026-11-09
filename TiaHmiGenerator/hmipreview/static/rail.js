// The project tree (rail), shared by the change report (TiaChangeReports page.py inlines this file and calls
// ldiffRail on its .ldiff root) and the HMI preview (loads it and calls ldiffRail(root, {go, lookup}) once the tree is
// in the page). Markup: hmipreview/rail.py (tree_html), styles: rail.css.
// Options (the preview's; the report passes none): go(a) opens a tree object instead of setting the address (#key),
// lookup names the objects of the Ctrl+K lookup. With go the rail does not run the report's sections, its address or
// its keys C, E, T. Exposed on the root: ldiffOpen(a), ldiffKey(key), ldiffLookup(c), ldiffSource(...),
// ldiffSelect(a) (marks a as the open object, opens its folders) and ldiffReindex() after the tree's items changed.
// The rail's fuzzy matching, shared with the HMI preview's property search (props.js): source(texts, numbers,
// objects) prepares texts, fuzzy(q, lowered text, bounds) -> [score, matched positions] or null, marked(text, at)
// the text as HTML with <mark>s, query(text) the search form of what was typed.
var ldiffFuzzy=(function(){
function wb(s,j){if(!j)return 10;var p=s.charAt(j-1),c=s.charAt(j),d=/[0-9]/;if(!/[A-Za-z0-9]/.test(p))return 9;
 if(/[a-z]/.test(p)&&/[A-Z]/.test(c))return 8;return d.test(p)!=d.test(c)?6:0}
function source(t,n,o){return {t:t,n:n,o:o,l:t.map(function(s){return s.toLowerCase()}),
 b:t.map(function(s){for(var b=[],j=0;j<s.length;j++)b[j]=wb(s,j);return b})}}
function fuzzy(q,l,b){var n=l.length,m=q.length,i,j,rows=[],prev,best=-1e9,bj=-1;
 for(i=0,j=0;j<n&&i<m;j++)if(l.charAt(j)==q.charAt(i))i++;if(i<m)return null;
 for(i=0;i<m;i++){var row=[],from=[],g=-1e9,gk=-1;
  for(j=0;j<n;j++){if(i&&j>1&&prev[j-2]-1>g-1){g=prev[j-2]-1;gk=j-2}else g-=1;row[j]=-1e9;
   if(l.charAt(j)!=q.charAt(i))continue;
   if(!i){row[j]=16+2*b[j];continue}
   var c=j?prev[j-1]+6:-1e9,v=g-2>c?g-2:c;if(v<-1e8)continue;row[j]=v+16+b[j];from[j]=v==c?j-1:gk}
  rows.push(from);prev=row}
 for(j=0;j<n;j++)if(prev[j]>best){best=prev[j];bj=j}if(bj<0)return null;
 var at=[bj];for(i=m-1;i>0;i--)at.unshift(bj=rows[i][bj]);return [best+(l==q?50:0),at]}
function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function marked(s,at){var o='',k=0;for(var j=0;j<s.length;j++){var on=at[k]===j;if(on)k++;
 o+=(on&&at[k-2]!==j-1?'<mark>':'')+esc(s.charAt(j))+(on&&at[k]!==j+1?'</mark>':'')}return o}
function query(v){return v.toLowerCase().replace(/\s+/g,'')}
return {source:source,fuzzy:fuzzy,esc:esc,marked:marked,query:query}})();
function ldiffRail(r,o){var source=ldiffFuzzy.source,fuzzy=ldiffFuzzy.fuzzy,esc=ldiffFuzzy.esc,marked=ldiffFuzzy.marked,query=ldiffFuzzy.query;
o=o||{};var app=!!o.go,rail=r&&r.querySelector('.rail');if(!rail)return;
if(!app&&/[?&]all(&|=|$)/.test(location.search)){r.classList.add('flat');return}
var secs=r.querySelectorAll('section.blk'),tree=rail.querySelector('.tree'),objs,nms,names,src,folds,info,
 sel=null,pos={},title=document.title;
function index(){objs=[].slice.call(tree.querySelectorAll('a.obj'));
 nms=objs.map(function(a){a.hl='';return a.querySelector('.nm')});names=nms.map(function(e){return e.textContent});
 src=source(names,null,objs);folds=[].slice.call(tree.querySelectorAll('li.fd'));
 folds.forEach(function(f){f.cnt=f.firstChild.querySelector('.n');f.n0=f.cnt.textContent});
 info=objs.map(function(a){for(var p=a.parentNode.parentNode,f=[];p!=tree;p=p.parentNode.parentNode)
  f.unshift(p.parentNode.firstChild.querySelector('.nm').textContent);
  return [a.classList[1],a.querySelector('.k').textContent,f.join(' / ')]});
 sel=app?tree.querySelector('a.obj.sel'):null;hits=[];act=null;vis=null;if(box&&box.value)search()}
// sel: the object shown. In the report the loading script (page.py WAIT_JS) has marked the address's object already;
// it is not shown until show() runs on it, so the report starts from none.
index();
function keep(v){try{if(v)localStorage.setItem('ldiff-rail',v);return localStorage.getItem('ldiff-rail')}catch(e){return null}}
function off(v){r.classList.toggle('rail-off',v);keep(v?'off':'on')}
function find(h){try{h=decodeURIComponent(h.replace(/^#/,'').replace(/\/b?\d+$/,''))}catch(e){return null}
 var o=null;[h,h.replace(/^blk-/,'')].forEach(function(x){
  for(var k=0;k<objs.length&&!o;k++)if(objs[k].getAttribute('data-key')===x)o=objs[k]});return o}
function go(a){if(!a)return;if(app)o.go(a);else location.hash=a.getAttribute('href')}
// Blocks that only moved to another folder are a group of their own: the rest comes first, next and previous stay inside.
function list(a){var m=a.classList.contains('moved');return objs.filter(function(x){return x.classList.contains('moved')==m})}
function first(){return objs.filter(function(x){return !x.classList.contains('moved')})[0]||objs[0]}
function step(d){var l=list(sel);go(l[l.indexOf(sel)+d])}
function show(a){if(!a||a==sel)return;var i=+a.getAttribute('data-i');
 if(sel)pos[sel.getAttribute('data-key')]=window.scrollY;
 [].forEach.call(secs,function(s,k){s.classList.toggle('on',k==i)});
 if(sel)sel.classList.remove('sel');a.classList.add('sel');sel=a;
 for(var p=a.parentNode;p!=tree;p=p.parentNode)p.classList.remove('shut');
 if(a.offsetTop<tree.scrollTop||a.offsetTop+a.offsetHeight>tree.scrollTop+tree.clientHeight)
  tree.scrollTop=a.offsetTop-tree.clientHeight/3;
 document.title=a.querySelector('.nm').textContent+' - '+title;
 window.scrollTo(0,pos[a.getAttribute('data-key')]||0)}
[].forEach.call(secs,function(s,i){var h=s.querySelector('.bh'),a=tree.querySelector('a.obj[data-i="'+i+'"]');
 if(!h||!a)return;var l=list(a),n=l.indexOf(a),p=document.createElement('span');p.className='pn';
 p.innerHTML=(n+1)+' of '+l.length+(a.classList.contains('moved')?' moved':'')+'<button type="button" title="Previous object (Alt+Up)"'+(n?'':' disabled')+
  '>&#9650;</button><button type="button" title="Next object (Alt+Down)"'+(n<l.length-1?'':' disabled')+'>&#9660;</button>';
 var b=p.querySelectorAll('button');b[0].onclick=function(){step(-1)};b[1].onclick=function(){step(1)};h.appendChild(p);
 [].forEach.call(h.querySelectorAll('.fa button'),function(b,k){b.title+=k?' (E)':' (C)'})});
rail.addEventListener('click',function(e){if(e.target.closest('.rq')){lookup(help);return}if(r.classList.contains('rail-off')){off(false);return}
 if(e.target.closest('.rt')){off(true);return}
 var a=app&&e.target.closest('a.obj');if(a){e.preventDefault();go(a);return}
 var f=e.target.closest('.fn');if(f)f.parentNode.classList.toggle('shut')});
if(!app)window.addEventListener('hashchange',function(){show(find(location.hash)||first())});
var box=rail.querySelector('.rs input'),hits=[],act=null,vis=null;
function pick(a,top){if(act)act.classList.remove('act');act=a||null;if(!act)return;act.classList.add('act');
 if(!top&&(act.offsetTop<tree.scrollTop||act.offsetTop+act.offsetHeight>tree.scrollTop+tree.clientHeight))
  tree.scrollTop=act.offsetTop-tree.clientHeight/3}
function shown(){return vis||(vis=hits.map(function(a){return [a.offsetTop,a]}).sort(function(x,y){return x[0]-y[0]})
 .map(function(x){return x[1]}))}
function put(e,o,miss){if(e.o!==o)e.style.order=e.o=o;if(e.m!==miss)e.classList.toggle('miss',e.m=miss)}
function num(q,ns){var d=q.replace(/^(network|nw)/,''),v=0;if(!/^\d+$/.test(d))return 0;
 ns.forEach(function(x){if(x==d)v=1e4;else if(!v&&x.indexOf(d)==0)v=5e3});return v}
function rank(q,s){s=s||src;var found=[];if(q)s.l.forEach(function(l,k){var f=fuzzy(q,l,s.b[k]),u=s.n?num(q,s.n[k]):0;
  if(u&&(!f||u>f[0]))f=[u,null];if(f)found.push([f[0],f[1]?l.length:0,k,s.o[k],f[1]])});
 return found.sort(function(x,y){return y[0]-x[0]||x[1]-y[1]||x[2]-y[2]})}
function search(){var q=query(box.value),found=rank(q),at=[];found.forEach(function(h){at[h[2]]=h[4]});
 objs.forEach(function(a,k){var h=at[k]?marked(names[k],at[k]):'';
  if(h!==a.hl){if(a.hl=h)nms[k].innerHTML=h;else nms[k].textContent=names[k]}
  if(!at[k])put(a.parentNode,'',!!q)});
 folds.forEach(function(f){f.hits=0});
 hits=found.map(function(h,k){var a=h[3],o=Math.min(k,200);put(a.parentNode,o,false);
  for(var p=a.parentNode.parentNode.parentNode;p!=rail;p=p.parentNode.parentNode){if(!p.hits)p.r=o;p.hits++}return a});
 folds.forEach(function(f){var t=String(q?f.hits:f.n0);put(f,f.hits?f.r:'',!!q&&!f.hits);if(f.cnt.textContent!==t)f.cnt.textContent=t});
 tree.classList.toggle('find',!!q);rail.classList.toggle('none',!!q&&!hits.length);vis=null;tree.scrollTop=0;pick(hits[0],true);
 if(!q&&sel)tree.scrollTop=sel.offsetTop-tree.clientHeight/3}
box.addEventListener('input',search);if(box.value)search();
box.addEventListener('keydown',function(e){var k=e.key;
 if(k=='Escape'){e.preventDefault();if(box.value){box.value='';search()}else box.blur()}
 else if(k=='Enter'){e.preventDefault();go(act)}
 else if((k=='ArrowDown'||k=='ArrowUp')&&!e.altKey&&hits.length){e.preventDefault();
  var v=shown();pick(v[(v.indexOf(act)+(k=='ArrowDown'?1:v.length-1))%v.length])}});
var lch=r.querySelector('.lch'),lbx=lch.querySelector('.lb'),lin=lch.querySelector('input'),lul=lch.querySelector('ul'),
 lrows=[],lat=0,back=null,lk=null,ls=null,keys=[],top=r.querySelector('button.top');
function typing(t){return t&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))}
function lookup(c){if(!lch.hidden&&lk==c){lin.select();return}if(lch.hidden)back=document.activeElement;
 lk=c;ls=c.load();lin.placeholder=c.ph;lin.setAttribute('aria-label',c.ph);lbx.setAttribute('aria-label',c.ph);
 lch.hidden=false;lin.value='';lfill();lin.focus()}
function lfill(){var q=query(lin.value),s=ls.s,found=q?rank(q,s):s.o.map(function(x,k){return [0,0,k,x,null]}),o='';
 lrows=found.slice(0,100);
 lrows.forEach(function(h,n){var k=h[2],t=s.t[k],i=ls.row(k);
  o+='<li class="'+i[0]+'" data-n="'+n+'" role="option"><span class="mk"></span><span class="nm">'+
   (h[4]?marked(t,h[4]):t?esc(t):'<i>no title</i>')+'</span><span class="k">'+esc(i[1])+'</span>'+
   (i[3]?'<span class="st '+i[3][0]+'">'+esc(i[3][1])+'</span>':'')+(i[2]?'<span class="pt">'+esc(i[2])+'</span>':'')+'</li>'});
 if(found.length>lrows.length)o+='<li class="more">'+(found.length-lrows.length)+' more: type more letters</li>';
 lul.innerHTML=found.length?o:'<li class="more">'+lk.none+'</li>';lpick(0)}
function lpick(n){var e=lul.querySelector('li.act');if(e)e.classList.remove('act');lat=n;e=lul.children[n];
 if(e&&lrows[n]){e.classList.add('act');e.scrollIntoView({block:'nearest'})}}
function lclose(){lch.hidden=true;if(back&&back!=document.body&&back.focus)back.focus();else lin.blur();back=null}
function lgo(n){var h=lrows[n],c=lk;if(h){lclose();c.go(h[3])}}
lin.addEventListener('input',lfill);
lin.addEventListener('keydown',function(e){var k=e.key;
 if(k=='Escape'){e.preventDefault();lclose()}
 else if(k=='Enter'){e.preventDefault();lgo(lat)}
 else if((k=='ArrowDown'||k=='ArrowUp')&&!e.altKey&&lrows.length){e.preventDefault();
  lpick((lat+(k=='ArrowDown'?1:lrows.length-1))%lrows.length)}});
lch.addEventListener('mousedown',function(e){if(e.target!=lin)e.preventDefault()});
lch.addEventListener('click',function(e){var li=e.target.closest('li[data-n]');
 if(li)lgo(+li.getAttribute('data-n'));else if(!e.target.closest('.lb'))lclose()});
var blocks={ph:'Lookup program blocks...',none:'No object found',go:go,
 load:function(){return {s:src,row:function(k){return info[k]}}}};
if(o.lookup)blocks.ph=o.lookup+'...';
var help={ph:'Keys...',none:'No key found',go:function(x){if(!x.when||x.when())x.run()},
 load:function(){return {s:source(keys.map(function(x){return x.text}),null,keys.slice()),row:function(k){return ['key',keys[k].show,'']}}}};
function combo(e){var k=e.key||'',m=e.ctrlKey||e.metaKey;if(k.length==1)k=k.toLowerCase();
 return (m?'Ctrl+':'')+(e.altKey?'Alt+':'')+(e.shiftKey&&(m||e.altKey||k.length>1)?'Shift+':'')+k}
function key(x){keys.push(x);keys.sort(function(a,b){return a.o-b.o})}
document.addEventListener('keydown',function(e){if(e.defaultPrevented||typing(e.target)||!lch.hidden)return;var c=combo(e);
 for(var j=0;j<keys.length;j++){var x=keys[j];if(x.keys.indexOf(c)>=0&&(!x.when||x.when())){e.preventDefault();x.run();return}}});
function fold(k){var b=r.querySelector('section.blk.on .bh .fa button:nth-child('+(k+1)+')');if(b)b.click()}
key({o:1,show:'Ctrl+B',text:'Hide or show the project tree',keys:['Ctrl+b'],run:function(){off(!r.classList.contains('rail-off'))}});
key({o:2,show:'Alt+Up',text:'Previous object',keys:['Alt+ArrowUp'],run:function(){step(-1)}});
key({o:3,show:'Alt+Down',text:'Next object',keys:['Alt+ArrowDown'],run:function(){step(1)}});
if(!app){key({o:4,show:'C',text:'Collapse every network of this object',keys:['c'],run:function(){fold(0)}});
key({o:5,show:'E',text:'Expand every network of this object',keys:['e'],run:function(){fold(1)}});
key({o:8,show:'T',text:'Back to top',keys:['t'],run:function(){var f=r.querySelector('.fcs');
 if(f&&!f.hidden)((f.ldiffFrame&&f.ldiffFrame())||f).scrollTo({top:0,behavior:'smooth'});else if(top)top.click()}})}
var kl={o:9,show:'Ctrl+K or /',text:'Lookup program blocks',keys:['Ctrl+k','/'],run:function(){lookup(blocks)}};
if(o.lookup)kl.text=o.lookup;key(kl);
key({o:11,show:'?',text:'This list of keys',keys:['?'],run:function(){lookup(help)}});
key({o:12,show:'Esc',text:'Close the lookup or the focus, clear the search',keys:[],run:function(){}});
if(top)top.title+=' (T)';
if(!app){r.classList.add('one');r.classList.remove('wait')}r.classList.toggle('rail-off',keep()=='off');
if(!app)show(find(location.hash)||first());
r.ldiffOpen=go;r.ldiffKey=key;r.ldiffLookup=lookup;r.ldiffSource=source;r.ldiffSelect=show;r.ldiffReindex=index}

