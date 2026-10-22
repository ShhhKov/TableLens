// This script runs only inside the isolated source frame, never in the editor.
(()=>{
const config=window.__uePreview;let query='',zoom=1,zoomed=false,hand=false,pan=null,timer=null,observer=null;
const compact=text=>text.toLocaleLowerCase().replace(/\s/g,'');
function post(type,data={}){parent.postMessage({type,key:config.key,...data},config.parentOrigin||'*');}
function remote(url){const target=new URL(url,document.baseURI);if(target.origin===config.proxyOrigin)return config.remoteOrigin+target.pathname+target.search+target.hash;return target.href;}
function highlight(){
 if(!document.body)return;observer?.disconnect();
 document.querySelectorAll('mark[data-ue-hit]').forEach(mark=>{mark.replaceWith(document.createTextNode(mark.textContent));});document.body.normalize();
 const needle=compact(query),entries=[];let text='',node;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 if(needle)while(node=walker.nextNode()){if(node.parentElement.closest('script,style,noscript,svg,head,template,textarea'))continue;const positions=[];let normalized='';for(let i=0;i<node.data.length;i++){if(/\s/.test(node.data[i]))continue;for(const char of node.data[i].toLocaleLowerCase()){normalized+=char;positions.push(i);}}if(normalized)entries.push({node,positions,start:text.length,end:text.length+normalized.length});text+=normalized;}
 const matches=[];if(needle)for(let start=0;(start=text.indexOf(needle,start))!==-1;start+=needle.length)matches.push({start,end:start+needle.length});
 for(const entry of entries){const segments=matches.filter(hit=>hit.start<entry.end&&hit.end>entry.start).map(hit=>({start:entry.positions[Math.max(hit.start,entry.start)-entry.start],end:entry.positions[Math.min(hit.end,entry.end)-entry.start-1]+1}));for(const segment of segments.reverse()){const range=document.createRange();range.setStart(entry.node,segment.start);range.setEnd(entry.node,segment.end);const mark=document.createElement('mark');mark.setAttribute('data-ue-hit','');mark.style.cssText='background:#ffe558!important;color:#111!important;outline:2px solid #edaa00!important';range.surroundContents(mark);}}
 const first=document.querySelector('mark[data-ue-hit]');if(first){for(let ancestor=first.parentElement;ancestor&&ancestor!==document.body;ancestor=ancestor.parentElement){if(ancestor.tagName==='DETAILS')ancestor.open=true;if(ancestor.classList.contains('collapse')){ancestor.classList.add('show','in');ancestor.setAttribute('aria-expanded','true');}if(ancestor.hidden)ancestor.hidden=false;if(getComputedStyle(ancestor).display==='none')ancestor.style.display='block';}first.scrollIntoView({block:'center'});}
 post('ue-status',{count:matches.length,url:config.source});observer?.observe(document.body,{childList:true,subtree:true});
}
function schedule(){clearTimeout(timer);timer=setTimeout(highlight,350);}
// Zoom keeps the anchor point (cursor or viewport centre) under the same place.
function setZoom(next,anchor){if(next===zoom&&zoomed)return;const x=Number.isFinite(anchor?.x)?anchor.x:innerWidth/2,y=Number.isFinite(anchor?.y)?anchor.y:innerHeight/2,ratio=next/zoom,left=scrollX,top=scrollY;document.documentElement.style.zoom=next;zoom=next;if(zoomed)scrollTo((left+x)*ratio-x,(top+y)*ratio-y);zoomed=true;}
const handStyle=document.createElement('style');handStyle.textContent='html.ue-hand,html.ue-hand *{cursor:grab!important;user-select:none!important}html.ue-panning,html.ue-panning *{cursor:grabbing!important}';
function setHand(value){hand=value;if(hand&&!handStyle.isConnected)document.documentElement.append(handStyle);document.documentElement.classList.toggle('ue-hand',hand);}
addEventListener('message',event=>{if(event.source!==parent||event.origin!==config.parentOrigin||event.data?.key!==config.key||event.data?.type!=='ue-controls')return;query=event.data.query||'';setHand(!!event.data.hand);setZoom(Number(event.data.zoom)||1,event.data.anchor);if(event.data.search!==false)schedule();});
// Hand mode: drag scrolls the nearest scrollable box; a click without movement still works.
function scroller(node){for(let element=node instanceof Element?node:node?.parentElement;element&&element!==document.body&&element!==document.documentElement;element=element.parentElement){const style=getComputedStyle(element);if((/(auto|scroll)/.test(style.overflowY)&&element.scrollHeight>element.clientHeight)||(/(auto|scroll)/.test(style.overflowX)&&element.scrollWidth>element.clientWidth))return element;}return null;}
addEventListener('pointerdown',event=>{if(!hand||event.button!==0)return;event.preventDefault();event.stopPropagation();const box=scroller(event.target);pan={id:event.pointerId,box,x:event.clientX,y:event.clientY,left:box?box.scrollLeft:scrollX,top:box?box.scrollTop:scrollY,moved:false};document.documentElement.classList.add('ue-panning');},true);
addEventListener('pointermove',event=>{if(pan?.id!==event.pointerId)return;event.stopPropagation();const dx=event.clientX-pan.x,dy=event.clientY-pan.y;// Capture only once dragging starts: capture retargets click away from links.
 if(!pan.moved&&Math.abs(dx)+Math.abs(dy)>3){pan.moved=true;document.documentElement.setPointerCapture?.(event.pointerId);}if(pan.box){pan.box.scrollLeft=pan.left-dx;pan.box.scrollTop=pan.top-dy;}else scrollTo(pan.left-dx,pan.top-dy);},true);
function swallow(event){event.preventDefault();event.stopImmediatePropagation();}
function endPan(event){if(pan?.id!==event.pointerId)return;const moved=pan.moved;pan=null;document.documentElement.classList.remove('ue-panning');if(moved){addEventListener('click',swallow,true);setTimeout(()=>removeEventListener('click',swallow,true));}}
addEventListener('pointerup',endPan,true);addEventListener('pointercancel',endPan,true);
addEventListener('dragstart',event=>{if(hand)event.preventDefault();},true);
addEventListener('wheel',event=>{if(!hand&&!event.ctrlKey)return;event.preventDefault();event.stopPropagation();post('ue-wheel',{delta:event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?400:1),x:event.clientX,y:event.clientY});},{capture:true,passive:false});
document.addEventListener('click',event=>{const link=event.target.closest?.('a');if(!link)return;const href=link.getAttribute('href')||'';if(href.startsWith('#')){if(link.hasAttribute('data-toggle')||link.hasAttribute('data-bs-toggle'))return;event.preventDefault();const id=href.slice(1);if(id){location.hash=id;const target=document.getElementById(decodeURIComponent(id));target?.scrollIntoView({block:'start'});}return;}if(!href||href.startsWith('javascript:')||link.hasAttribute('data-toggle')||link.hasAttribute('data-bs-toggle')||link.hasAttribute('aria-controls'))return;const target=remote(link.href);if(/^https?:\/\//i.test(target)){event.preventDefault();event.stopImmediatePropagation();post('ue-navigate',{url:target});}},true);
window.open=(url)=>{if(url&&navigator.userActivation.isActive)post('ue-navigate',{url:remote(url)});return null;};
document.addEventListener('submit',event=>{const form=event.target;if((form.method||'get').toLowerCase()!=='get')return;event.preventDefault();const target=new URL(remote(form.action||config.source));for(const [key,value] of new FormData(form))if(typeof value==='string')target.searchParams.append(key,value);post('ue-navigate',{url:target.href});},true);
document.addEventListener('DOMContentLoaded',()=>{observer=new MutationObserver(schedule);observer.observe(document.body,{childList:true,subtree:true});post('ue-ready');schedule();});
addEventListener('load',schedule);
})();
