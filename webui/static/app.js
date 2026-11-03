let selected=null, uploaded=null, busy=false, polling=false, lastError='', lastTransfers={}, lastLinkCounters={}, lastTelemetryAt=Date.now();
const $=id=>document.getElementById(id);
function toast(s){let t=$('toast');t.textContent=s;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}
function fmt(n){if(n<1024)return n+' B';if(n<1048576)return(n/1024).toFixed(1)+' KB';if(n<1073741824)return(n/1048576).toFixed(2)+' MB';return(n/1073741824).toFixed(2)+' GB'}
function duration(s){s=Math.floor(s||0);return String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}
function choose(f){selected=f||null;uploaded=null;$('fileName').textContent=f?f.name+' · '+fmt(f.size):'Up to 1 GB per file';$('sendBtn').disabled=!f||busy}
$('dropzone').addEventListener('click',e=>{if(e.target.tagName!=='INPUT')$('fileInput').click()});$('fileInput').addEventListener('change',e=>{choose(e.target.files[0]);e.target.value=''});['dragover','dragenter'].forEach(x=>$('dropzone').addEventListener(x,e=>{e.preventDefault();$('dropzone').classList.add('drag')}));['dragleave','drop'].forEach(x=>$('dropzone').addEventListener(x,e=>{$('dropzone').classList.remove('drag')}));$('dropzone').addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files.length)choose(e.dataTransfer.files[0])});
async function api(url,body){let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});let j={};try{j=await r.json()}catch(_){}if(!r.ok)throw Error(j.error||'Request failed ('+r.status+')');return j}
async function startNetwork(){try{await api('/api/start',{mode:$('mode').value});toast('Network startup requested');refresh()}catch(e){toast(e.message)}}async function stopNetwork(){try{await api('/api/stop');toast('Network stopped');refresh()}catch(e){toast(e.message)}}
async function controlSwitch(name,action){if(!confirm(`${action==='down'?'Take':'Restore'} ${name}? This changes the live Mininet network.`))return;try{await api(`/api/switch/${name}/${action}`);toast(`${name} ${action==='down'?'taken down':'restored'}`);refresh()}catch(e){toast(e.message)}}
async function controlLink(id,action,label){if(!confirm(`${action==='down'?'Disable':'Enable'} link ${label}?`))return;try{await api('/api/link',{id,action});toast(`Link ${label} ${action==='down'?'disabled':'enabled'}`);refresh()}catch(e){toast(e.message)}}
async function sendFile(){if(!selected||busy)return;busy=true;try{$('sendBtn').disabled=true;$('progressWrap').classList.add('show');$('progressText').textContent='Uploading file to control plane';let fd=new FormData();fd.append('file',selected);let r=await fetch('/api/upload',{method:'POST',body:fd}),j={};try{j=await r.json()}catch(_){}if(!r.ok)throw Error(j.error||'Upload failed ('+r.status+')');uploaded=j;await api('/api/transfer',{path:j.path,server:$('destination').value});$('progressText').textContent='Transferring through Mininet';toast('Transfer started');busy=false;refresh()}catch(e){busy=false;toast(e.message);$('sendBtn').disabled=!selected;$('progressWrap').classList.remove('show')}}

const edgeFor=(a,b)=>{const key=[a,b].sort().join('-');return ({'h1-s1':'edge-h1-s1','h2-s1':'edge-h2-s1','s1-s2':'edge-s1-s2','s1-s3':'edge-s1-s3','s2-s4':'edge-s2-s4','s3-s4':'edge-s3-s4','h3-s2':'edge-s2-h3','h4-s4':'edge-s4-h4'})[key]};
function emitPacket(pathId,reverse=false){
 const path=$(pathId),layer=$('trafficParticles');if(!path||!layer)return;
 const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('r','4');dot.setAttribute('class','traffic-particle');layer.appendChild(dot);
 const length=path.getTotalLength(),begin=performance.now(),durationMs=850;
 function frame(now){const t=Math.min(1,(now-begin)/durationMs),point=path.getPointAtLength((reverse?1-t:t)*length);dot.setAttribute('cx',point.x);dot.setAttribute('cy',point.y);dot.style.opacity=String(Math.sin(Math.PI*t));if(t<1)requestAnimationFrame(frame);else dot.remove()}
 requestAnimationFrame(frame);
}
function updateTraffic(links){
 const now=Date.now(),elapsed=Math.max(.25,(now-lastTelemetryAt)/1000);let bytes=0,activity=0;
 // Sample exactly one endpoint per physical link to avoid double-counting.
 const sampled=new Set();
 for(const l of (links||[])){
   if(!l.switch||!l.peer)continue;
   const edge=edgeFor(l.switch,l.peer);if(!edge)continue;
   const inter=l.peer.startsWith('s');
   const canonical=inter?[l.switch,l.peer].sort().join('-'):edge;
   if(sampled.has(canonical))continue;
   // For switch-switch links sample the alphabetically first switch; for host links sample the switch endpoint.
   if(inter&&l.switch!==[l.switch,l.peer].sort()[0])continue;
   sampled.add(canonical);
   const prev=lastLinkCounters[l.id];
   if(prev){
     const rx=Math.max(0,l.rx_bytes-prev.rx),tx=Math.max(0,l.tx_bytes-prev.tx);bytes+=rx+tx;
     // SVG path orientation is host→switch for access links and lower-name switch→higher-name switch for fabric links.
     let txForward;
     if(inter) txForward=(l.switch===[l.switch,l.peer].sort()[0]);
     else txForward=(l.peer==='h3'||l.peer==='h4'); // h1/h2 paths are drawn host→switch, h3/h4 paths switch→host
     if(tx>64){emitPacket(edge,!txForward);activity+=tx}
     if(rx>64){emitPacket(edge,txForward);activity+=rx}
   }
   lastLinkCounters[l.id]={rx:l.rx_bytes,tx:l.tx_bytes};
 }
 lastTelemetryAt=now;const rate=bytes/elapsed;
 $('trafficRate').textContent=fmt(rate)+'/s observed';
 $('trafficState').textContent=activity?'Live packets observed from Mininet counters':'No new packets observed in this sample';
 $('trafficState').classList.toggle('traffic-active',!!activity);
}
function pathText(route,server){if(!route||!route.available)return 'NO ROUTE';return ['h1',...(route.switches||[]),server].join(' → ')}
const SRV={A:{key:'serverA',host:'h3',ep:'10.0.0.3:9000'},B:{key:'serverB',host:'h4',ep:'10.0.0.4:9000'}};
function serverLine(t,k){const p=(t.progress||{})[k]||{},r=(t.result||[]).find(x=>x.endpoint===SRV[k].ep),total=p.total_chunks!=null?p.total_chunks:Math.ceil((t.size||0)/65536),done=p.chunk||0;
 let state=p.state||'waiting',percent=p.percent||0,cls='',label='';
 if(r){state=r.success?'done':'failed';if(r.success)percent=100}
 else if(t.status!=='running'&&state!=='done'){state='failed'}
 if(state==='done'){label='Stored and verified';cls='ok'}else if(state==='failed'){label='Failed'+((r&&r.error)||p.error?': '+esc((r&&r.error)||p.error):'');cls='bad'}
 else if(state==='retrying'){label=`Reconnecting after path change/failure (${p.failures||0}/${p.max_failures||'?'} tries without progress)${p.error?' · '+esc(p.error):''}`;cls='warn'}
 else if(state==='connecting'){label='Connecting…';cls='warn'}else if(state==='sending'){label='Sending'+(p.last_ack_age!=null?'':'');cls=''}else label='Waiting to start';
 const route=t.routes&&t.routes[SRV[k].key];
 return `<div class="transfer-detail ${cls}"><div class="detail-top"><b>Server ${k} · ${esc(t.filename)}</b><span>${state==='done'?total:done}/${total} chunks · ${Number(percent).toFixed(1)}%</span></div><div class="detail-bar"><i style="width:${Math.min(100,percent)}%"></i></div><div class="detail-meta"><span class="state-${cls||'run'}">${label}</span><span>Acknowledged: ${fmt(state==='done'?t.size:(p.acknowledged_bytes||0))} / ${fmt(t.size)}</span><span>Retries: ${p.retries||0}</span></div><div class="detail-route">Path snapshot: ${esc(pathText(route,SRV[k].host))}</div></div>`}
function transferDetails(t){const target=t.server==='A'?['A']:t.server==='B'?['B']:['A','B'];return target.map(k=>serverLine(t,k)).join('')}


function render(s){let online=s.running;updateTraffic(s.links||[]);$('statusPill').className='pill '+(online?'online':'');$('statusPill').innerHTML='<i></i> '+(s.starting?'STARTING':online?'ONLINE':'OFFLINE');$('sideState').textContent=s.starting?'Starting network':online?'Network online':'Network offline';$('latency').textContent=s.latency_ms==null?'—':s.latency_ms.toFixed(2);$('uptime').textContent=online?duration(s.uptime):'00:00';$('modeTag').textContent=(s.mode||'dynamic').toUpperCase();let count=Object.values(s.flows||{}).reduce((a,b)=>a+b,0);$('flowCount').textContent=count;const ra=s.routes&&s.routes.serverA,rb=s.routes&&s.routes.serverB;$('routeStatus').innerHTML=`<div><b>h1 → Server A</b><span class="${ra&&ra.available?'route-up':'route-down'}">${pathText(ra,'h3')}${ra&&ra.available?` · cost ${ra.cost}`:''}</span></div><div><b>h1 → Server B</b><span class="${rb&&rb.available?'route-up':'route-down'}">${pathText(rb,'h4')}${rb&&rb.available?` · cost ${rb.cost}`:''}</span></div>`;const lm=s.link_metrics||[];$('linkMetricGrid').innerHTML=lm.map(m=>`<div class="link-metric-row ${m.up?'':'metric-down'}"><span><b>${esc(m.link)}</b><small>${m.up?'UP':'DOWN'} · ${m.configured_delay_ms} ms configured delay</small></span><span class="metric-values"><b>${Number(m.utilization_percent||0).toFixed(1)}%</b><small>utilisation</small></span><span class="metric-values"><b>${Number(m.dynamic_cost||0).toFixed(2)}</b><small>dynamic cost</small></span></div>`).join('')||'<div class="metric-empty">Waiting for OpenFlow port statistics…</div>';$('switchGrid').innerHTML=['s1','s2','s3','s4'].map(k=>`<div class="${(s.switches&&s.switches[k]==='down')?'node-down':''}">${k}<b>${s.switches&&s.switches[k]==='down'?'DOWN':(s.flows&&s.flows[k]!=null?s.flows[k]+' rules':'—')}</b></div>`).join('');document.querySelectorAll('.toponode.sw circle').forEach((circle,i)=>{let name='s'+(i+1),down=s.switches&&s.switches[name]==='down';circle.classList.toggle('switch-down',!!down)});for(const l of (s.links||[])){if(l.switch&&l.peer&&l.switch.startsWith('s')&&l.peer.startsWith('s')){let edge=edgeFor(l.switch,l.peer),path=edge&&$(edge);if(path)path.classList.toggle('link-down',!!(s.link_states&&s.link_states[l.id]==='down'))}}$('switchControls').innerHTML=['s1','s2','s3','s4'].map(k=>{let down=s.switches&&s.switches[k]==='down';return `<div class="control-row ${down?'is-down':''}"><span><b>${k}</b><small>${down?'Switch stopped':'Switch operational'}</small></span><button class="mini-btn ${down?'restore':'danger'}" onclick="controlSwitch('${k}','${down?'up':'down'}')">${down?'Bring up':'Take down'}</button></div>`}).join('');let seen=new Set(),inter=(s.links||[]).filter(l=>l.switch&&l.peer&&l.switch.startsWith('s')&&l.peer.startsWith('s'));$('linkControls').innerHTML=inter.filter(l=>{if(seen.has(l.id))return false;seen.add(l.id);return true}).map(l=>{let down=s.link_states&&s.link_states[l.id]==='down';let label=[l.switch,l.peer].sort().join(' ↔ ');return `<div class="control-row ${down?'is-down':''}"><span><b>${label}</b><small>${down?'Link disabled':'Link operational'}</small></span><button class="mini-btn ${down?'restore':'danger'}" onclick="controlLink('${l.id}','${down?'up':'down'}','${label}')">${down?'Enable link':'Disable link'}</button></div>`}).join('')||'<div class="control-row">No inter-switch links available.</div>';let active=(s.transfers||[]).filter(t=>t.status==='running').length;$('active').textContent=active;
for(let k of ['A','B']){let x=s.servers&&s.servers[k],el=$('server'+k);el.textContent=x&&x.running?'ONLINE':'OFFLINE';el.className='server-status '+(x&&x.running?'online':'');$('files'+k).textContent=x&&x.files.length?x.files.length+' stored file(s) · '+x.files.slice(0,2).map(f=>fmt(f.size)).join(', '):'No stored files'}
$('events').innerHTML=(s.events||[]).length?s.events.map(e=>`<div class="event ${e.kind}"><time>${e.time}</time><i class="bullet"></i><span>${esc(e.message)}</span></div>`).join(''):'<div class="empty">No events yet.</div>';
let rows=(s.transfers||[]);$('history').innerHTML=rows.length?rows.map(t=>{let res=t.result||[],mbps=res.length?res.map(x=>`${x.endpoint==='10.0.0.3:9000'?'A':'B'}: ${x.success?(x.throughput_mbps||0).toFixed(2)+' Mbps':'failed'}`).join(' · '):(t.status==='running'?'in progress':'—');return `<tr><td>${esc(t.filename)}</td><td>${esc(t.server)}</td><td>${fmt(t.size)}</td><td><span class="status ${esc(t.status)}">${esc(t.status.toUpperCase())}</span></td><td>${esc(mbps)}</td></tr>`}).join(''):'<tr><td colspan="5" class="empty">No transfers yet. Upload a file to begin.</td></tr>';
const activeTransfer=(s.transfers||[]).find(t=>t.status==='running')||(s.transfers||[])[0];$('chunkDetails').innerHTML=activeTransfer?transferDetails(activeTransfer):'';
if(s.error&&s.error!==lastError){toast(s.error)}lastError=s.error||'';$('mode').disabled=!!(online||s.starting);if(!online&&!s.starting)$('progressWrap').classList.remove('show');if(!busy){$('sendBtn').disabled=!selected||!online;if(active){$('progressWrap').classList.add('show');$('progressText').textContent='Transferring through Mininet'}else $('progressWrap').classList.remove('show')}}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
let refreshing=false;async function refresh(){if(refreshing)return;refreshing=true;try{let r=await fetch('/api/status');render(await r.json())}catch(e){}finally{refreshing=false}}
function poll(){if(polling)return;polling=true;(function tick(){refresh().finally(()=>setTimeout(tick,2500))})()}poll();
