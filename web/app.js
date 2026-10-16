'use strict';
const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];
const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
 dashboard:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
 inbounds:'M4 7h16v5H4z M4 15h16v5H4z M7 9.5h.01 M7 17.5h.01 M12 4V2 M9 4h6',
 tls:'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z M9 12l2 2 4-4',
 dns:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M3 12h18 M12 3c5 5 5 13 0 18 M12 3c-5 5-5 13 0 18',
 clients:'M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M20 21v-3a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8',
 settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3l-1 3-3 1-2 3 2 2-1 3 3 3 3-1 2 2 3-2 1-3 3-1 1-3-2-2 1-3-3-2z',
 refresh:'M20 7v5h-5 M4 17v-5h5 M5 7a8 8 0 0 1 13-2l2 2 M4 17l2 2a8 8 0 0 0 13-2',
 plus:'M12 5v14 M5 12h14', arrow:'M19 12H5 M10 7l-5 5 5 5', close:'M6 6l12 12 M6 18 18 6',
 cpu:'M7 7h10v10H7z M9 3v4 M15 3v4 M9 17v4 M15 17v4 M3 9h4 M3 15h4 M17 9h4 M17 15h4',
 memory:'M3 6h18v12H3z M6 9v3 M10 9v3 M14 9v3 M18 9v3 M6 18v3 M10 18v3 M14 18v3 M18 18v3',
 disk:'M4 4h16v16H4z M4 15h16 M7 17.5h.01 M10 17.5h.01',
 traffic:'M7 3v18 M3 17l4 4 4-4 M17 21V3 M13 7l4-4 4 4',
 download:'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5', edit:'m16 3 5 5-12 12-6 1 1-6z M13 6l5 5',
 qr:'M3 3h6v6H3z M15 3h6v6h-6z M3 15h6v6H3z M15 15h2v2h-2z M19 15h2v6h-6v-2 M5 5h2v2H5z M17 5h2v2h-2z M5 17h2v2H5z',
 trash:'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7',
 search:'M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15 M16 16l5 5',
 check:'M5 12l4 4L19 6', code:'m8 5-6 7 6 7 M16 5l6 7-6 7 M14 3l-4 18',
 clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2',
 lock:'M5 10h14v11H5z M8 10V6a4 4 0 0 1 8 0v4', eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
 power:'M12 2v10 M6 5a9 9 0 1 0 12 0', key:'M8 4a5 5 0 1 0 0 10 5 5 0 0 0 0-10 M12 12l9 9 M17 17l3-3'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.code}"/></svg>`;
const btn = (text, action, symbol = 'plus', cls = '', attrs = '') => `<button class="btn ${cls}" data-action="${action}" ${attrs}>${icon(symbol)}${text}</button>`;
const rowBtn = (title, action, symbol, id, collection='') => `<button title="${e(title)}" aria-label="${e(title)}" data-action="${action}" data-id="${e(id)}" data-collection="${collection}">${icon(symbol)}</button>`;
const titles = {dashboard:'Overview',inbounds:'Inbounds',tls:'TLS certificates',dns:'DNS',clients:'Clients',settings:'Settings'};
const descriptions = {dashboard:'An overview of your server and services, at a glance.',inbounds:'Configure and manage the entry points to your server.',tls:'Secure every connection with the right certificate.',dns:'Manage resolvers, DNS rules, and rule sets in one place.',clients:'Your clients, their traffic, and their access.',settings:'Server preferences and administrator account security.'};
let optionSchema;
let state, dashboard, csrf = '', page = 'dashboard', dnsTab = 'dns_servers', search = '', filter = 'all', pageNumber = 1;
let refreshPending = null, modalSubmit = null, previewConfig = null;
const size = (n, decimals = 1) => {
 if (n === null || n === undefined) return '—';
 if (!n) return '0 B';
 const units = ['B','KiB','MiB','GiB','TiB','PiB']; const i = Math.min(5, Math.floor(Math.log(Math.max(1,n))/Math.log(1024)));
 return `${(n/1024**i).toFixed(i ? decimals : 0)} ${units[i]}`;
};
const num = n => Number(n || 0).toLocaleString('en-US');
const date = value => value ? new Date(typeof value === 'number' ? value*1000 : value).toLocaleDateString('en-US') : 'No expiry';
const time = value => new Date(value*1000).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
const total = c => { const t = dashboard?.totals[c.id] || {}; return (t.upload || 0) + (t.download || 0); };
const status = c => !c.enabled ? ['Disabled',''] : c.expires_at && new Date(c.expires_at) <= new Date() ? ['Expired','red'] : c.quota_bytes && total(c)>=c.quota_bytes ? ['Quota reached','orange'] : ['Active','green'];
const badge = (text, color='') => `<span class="badge ${color}">${e(text)}</span>`;
const checked = value => value ? 'checked' : '';

async function api(path, body) {
 const response = await fetch('api/' + path,{method:body ? 'POST':'GET', headers:body ? {'Content-Type':'application/json','X-CSRF-Token':csrf} : {},body:body ? JSON.stringify(body):undefined,credentials:'same-origin'});
 const result = await response.json();
 if (!response.ok) {
  if (response.status === 401 && path !== 'login') showLogin();
  throw new Error(result.error || 'Could not connect to the server');
 }
 return result;
}
function toast(message, error=false) { const node=document.createElement('div');node.className='toast'+(error?' error':'');node.textContent=message;$('#toasts').append(node);setTimeout(()=>node.remove(),6500); }
function showLogin() { $('#login').hidden=false;$('#app').hidden=true;csrf=''; }
async function boot() {
 try { const session=await api('session');optionSchema=await api('options');csrf=session.csrf;$('#admin-name').textContent=session.username;await load();$('#login').hidden=true;$('#app').hidden=false; }
 catch(err) { showLogin();if (err.message !== 'Please sign in first') $('#login-error').textContent=err.message; }
}
async function load(silent=false) {
 if(refreshPending){await refreshPending;if(silent)return;}
 refreshPending=(async()=>{
  [state,dashboard]=await Promise.all([api('state'),api('dashboard')]);
  $('#sidebar-host').textContent=dashboard.metrics.hostname;
  $('#sidebar-core').textContent=dashboard.core.running?'Core is running':'Core is stopped';
  $('.core-label .status-dot').classList.toggle('on',dashboard.core.running);
  $('#updated').textContent='Updated at '+new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
  if (!silent || page==='dashboard') render(); else renderNav();
 })();
 try{await refreshPending;}finally{refreshPending=null;}
}

function renderNav() {
 $('#navigation').innerHTML=Object.keys(titles).map(key=>`<a href="#${key}" class="nav-item ${page===key?'active':''}" ${page===key?'aria-current="page"':''}>${icon(key)}<span>${titles[key]}</span>${['inbounds','clients','tls'].includes(key)?`<span class="nav-count">${state[key].length}</span>`:''}</a>`).join('');
}
function heading(actions='') {return `<div class="page-heading"><div><h1>${titles[page]}</h1><p>${descriptions[page]}</p></div><div class="heading-actions">${actions}</div></div>`;}
function pendingBanner() {return `<div class="auto-apply-note">${icon('check')}<span>Auto apply is on. Saving validates and activates changes. Connection changes may briefly reconnect clients.</span></div>`;}

function empty(title,text,action,button='Add your first item',symbol='plus') {return `<div class="empty-state"><div class="empty-icon">${icon(symbol)}</div><h3>${title}</h3><p>${text}</p>${action?btn(button,action):''}</div>`;}
function render() {
 if (!state || !dashboard) return;
 page=Object.hasOwn(titles,location.hash.slice(1))?location.hash.slice(1):'dashboard';
 renderNav();$('#crumb').textContent=titles[page];document.title=titles[page]+' · NARA';
 $('#content').innerHTML=({dashboard:renderDashboard,inbounds:renderInbounds,tls:renderTLS,dns:renderDNS,clients:renderClients,settings:renderSettings}[page])();
}
function metric(label,value,symbol,color,foot) {return `<article class="stat-card"><div class="stat-head">${label}<span class="stat-symbol ${color}">${icon(symbol)}</span></div><div class="stat-number">${value}</div><div class="stat-foot">${foot}</div></article>`;}
function renderDashboard() {
 const m=dashboard.metrics,c=dashboard.core,active=state.clients.filter(x=>status(x)[0]==='Active').length;
 const allUsage=Object.values(dashboard.totals).reduce((sum,t)=>sum+t.upload+t.download,0);
 const runningInbounds=state.inbounds.filter(i=>i.enabled&&state.clients.some(x=>status(x)[0]==='Active'&&x.inbound_ids.includes(i.id))).length;
 return heading(btn('Server config','config','code')+(dashboard.core.running?'':btn('Start core','apply','power','primary')))+
 `<section class="hero"><div class="hero-copy"><span class="eyebrow">NARA / YOUR SERVER, YOUR RULES</span><h2>${c.running?'Your server is ready to connect.':'Your network. Your rules.'}</h2><p>${c.running?'Everything you need to manage connections, clients, and server resources.':'Create a certificate, add an inbound, and connect your first client.'}</p></div><div class="hero-status">${icon('inbounds')}<div><b>${c.running?'Sing-box Running':'Sing-box Stopped'}</b><small>${e(c.version || 'CORE NOT INSTALLED')}</small></div></div></section>`+
 (c.error?`<div class="hint-box error">${e(c.error)}</div>`:'')+
 (c.stats_error?`<div class="hint-box error">${e(c.stats_error)}</div>`:'')+
 `<div class="stats-grid">${metric('Active clients',num(active)+` <small>/ ${num(state.clients.length)}</small>`,'clients','green',`<b>${num(state.clients.length-active)}</b> disabled or limited accounts`)}${metric('Total client traffic',e(size(allUsage)),'traffic','blue',c.last_stats?'Last collected: '+time(c.last_stats):'Waiting for core traffic statistics')}${metric('Ready inbounds',num(runningInbounds)+` <small>/ ${num(state.inbounds.length)}</small>`,'inbounds','purple',c.running?'Enabled with eligible clients':'Save settings or start the core')}${metric('Server uptime',m.uptime===null?'—':`${Math.floor(m.uptime/86400)} <small>days</small> ${Math.floor(m.uptime%86400/3600)} <small>hours</small>`,'clock','',e(m.hostname))}</div>`+
 `<div class="grid-2"><section class="card"><div class="card-header"><div><h2>Server traffic</h2><p>All network interfaces, excluding loopback</p></div>${badge('Last 10 minutes')}</div><div class="chart-totals"><div><span><i class="legend-dot"></i>Download</span><b>${e(size(m.rx_rate))}<small> /s</small></b></div><div><span><i class="legend-dot green"></i>Upload</span><b>${e(size(m.tx_rate))}<small> /s</small></b></div></div><div class="network-chart">${chart(m.samples)}</div></section>
 <section class="card"><div class="card-header"><div><h2>Server resources</h2><p>Live hardware utilization</p></div>${icon('cpu')}</div><div class="card-body">${resource('CPU',m.cpu_percent,'cpu',`${num(m.cpu_count)} cores · Load ${m.load.map(x=>x.toFixed(2)).join(' / ')}`)}${resource('Memory',m.memory_total?100*m.memory_used/m.memory_total:null,'memory',size(m.memory_used)+' of '+size(m.memory_total))}${resource('Disk storage',100*m.disk_used/m.disk_total,'disk',size(m.disk_used)+' of '+size(m.disk_total))}</div><div class="resource-footer"><span>Operating system</span><b>${e(m.platform)}</b></div></section></div>`+
 (!state.clients.length?`<section class="card section-gap"><div class="card-header"><div><h2>Your first connection in three steps</h2><p>Set up your server</p></div>${badge('Get started','orange')}</div><div class="steps">${[['01','TLS certificate','Generate in one click','tls'],['02','New Inbound','Choose protocol and port','inbounds'],['03','Create client','Set traffic and expiry','clients']].map(s=>`<a class="step" href="#${s[3]}"><span>${s[0]}</span><div><b>${s[1]}</b><small>${s[2]}</small></div></a>`).join('')}</div></section>`:'')+
 `<section class="card"><div class="card-header"><div><h2>Your clients</h2><p>Recent accounts and their traffic usage</p></div><a class="text-link" href="#clients">View all →</a></div>${clientTable(state.clients.slice(-4).reverse(),true)}</section>`+
 `<div class="bottom-grid"><section class="card"><div class="card-header"><h2>Recent activity</h2>${icon('clock')}</div><div class="card-body">${dashboard.events.length?dashboard.events.slice(0,5).map(x=>`<div class="event"><span class="event-dot"></span><span>${e(x.message)}</span><time>${date(x.at)} · ${time(x.at)}</time></div>`).join(''):'<p class="note">No events recorded yet.</p>'}</div></section><section class="card"><div class="card-header"><h2>Service information</h2>${badge(c.running?'Running':'Stopped',c.running?'green':'')}</div><div class="card-body">${info('Hostname',e(m.hostname))}${info('Core version',e(c.version||'Not installed'))}${info('Active configuration revision',c.active_revision===null?'Not applied yet':num(c.active_revision))}${info('Saved revision',num(state.revision))}</div></section></div>`;
}
function info(label,value){return `<div class="info-row"><span>${label}</span><b>${value}</b></div>`;}
function resource(label,value,symbol,hint){return `<div class="resource"><div class="resource-head">${icon(symbol)}${label}<b>${value===null?'—':value.toFixed(1)+'%'}</b></div><progress max="100" value="${value===null?0:Math.min(100,value)}" aria-label="${label}"></progress><small>${e(hint)}</small></div>`;}
function chart(samples) {
 if (!samples || samples.length<2) return `<div class="chart-empty">${icon('traffic')}<span>${dashboard.metrics.platform==='Linux'?'Collecting traffic samples…':'Live traffic metrics are available when running on Linux.'}</span></div>`;
 const max=Math.max(1024,...samples.flatMap(s=>[s.rx,s.tx])),w=600,h=110;
 const path=key=>samples.map((s,i)=>`${i?'L':'M'}${(i*w/(samples.length-1)).toFixed(1)},${(h-s[key]/max*(h-10)).toFixed(1)}`).join(' ');
 return `<svg viewBox="0 0 600 110" preserveAspectRatio="none" role="img" aria-label="Server upload and download traffic"><defs><linearGradient id="trafficFill" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#e8ad86" stop-opacity=".22"/><stop offset="1" stop-color="#e8ad86" stop-opacity="0"/></linearGradient></defs>${[10,40,75,109].map(y=>`<path d="M0 ${y}H600" stroke="#f0f3f4" fill="none"/>`).join('')}<path d="${path('rx')} L600,110 L0,110Z" fill="url(#trafficFill)"/><path d="${path('rx')}" stroke="#e0a17c" stroke-width="2" fill="none" vector-effect="non-scaling-stroke"/><path d="${path('tx')}" stroke="#8bb6a7" stroke-width="1.8" fill="none" vector-effect="non-scaling-stroke"/></svg><div class="chart-labels"><span>${time(samples[0].at)}</span><span>${time(samples.at(-1).at)}</span></div>`;
}
function renderInbounds() {
 return heading(btn('New inbound','new-inbound','plus','primary'))+pendingBanner()+`<section class="card"><div class="card-header"><div><h2>Connection endpoints</h2><p>VLESS · VMess · Trojan · Hysteria2 · TUIC · AnyTLS</p></div>${badge(num(state.inbounds.length)+' Inbound')}</div>${state.inbounds.length?`<div class="table-wrap"><table><thead><tr><th>Name / tag</th><th>Protocol</th><th>Listen address</th><th>TLS</th><th>Clients</th><th>Status</th><th>Actions</th></tr></thead><tbody>${state.inbounds.map(i=>`<tr><td><b class="mono">${e(i.tag)}</b><small class="path-cell">${e(['hysteria2','tuic'].includes(i.type)||i.transport==='quic'?'QUIC / UDP':i.transport?.toUpperCase()||'TCP')} ${!['hysteria2','tuic','anytls'].includes(i.type)&&!['tcp','quic'].includes(i.transport||'tcp')?e(i.path||''):''}</small></td><td>${badge(i.type.toUpperCase(),'blue')}</td><td class="mono">${e(i.listen)}:${i.port}</td><td>${i.tls_id?`<span class="tls-tag">${icon('lock')}${e(state.tls.find(t=>t.id===i.tls_id)?.server_name||'')}</span>`:badge('No TLS','orange')}</td><td>${num(state.clients.filter(c=>c.inbound_ids.includes(i.id)).length)}</td><td>${badge(i.enabled?'Active':'Disabled',i.enabled?'green':'')}</td><td><div class="row-actions">${rowBtn('Edit','edit','edit',i.id,'inbounds')}${rowBtn('Delete','delete','trash',i.id,'inbounds')}</div></td></tr>`).join('')}</tbody></table></div>`:empty('Add your first inbound','Choose a protocol, port, and certificate. Clients connect to your server through this inbound.','new-inbound','Add Inbound','inbounds')}</section>`+
 `<div class="hint-box section-gap">Open UDP ports for Hysteria2, TUIC, and QUIC transport; open TCP ports for other connections in your server firewall. Inbounds without eligible clients will not start.</div>`;
}
function renderTLS() {
 return heading(btn('Import certificate','import-tls','download')+btn('Generate self-signed','self-signed','plus','primary'))+pendingBanner()+
 `<div class="hint-box">Generate a certificate in one click. Each TLS profile controls verification, ALPN, and TLS versions in client exports.</div>`+
 (state.tls.length?`<div class="cards-grid">${state.tls.map(t=>`<article class="card certificate-card"><div class="cert-icon">${icon('tls')}</div><h3>${e(t.name||t.server_name)}</h3><span class="mono">${e(t.server_name)}</span><div class="cert-details"><span>Certificate type ${badge(t.kind==='self_signed'?'Self-signed':'Imported',t.kind==='self_signed'?'orange':'green')}</span><span>Client verification ${badge(t.insecure?'Allow insecure':'Verified',t.insecure?'orange':'green')}</span><span>Expires <b>${date(t.expires)}</b></span><span>Assigned to <b>${num(state.inbounds.filter(i=>i.tls_id===t.id).length)} Inbound</b></span></div><div class="cert-footer">${badge(t.expires>Date.now()/1000?'Valid':'Expired',t.expires>Date.now()/1000?'green':'red')}<div class="row-actions">${rowBtn('Download certificate','download-cert','download',t.id)}${rowBtn('Edit certificate','edit','edit',t.id,'tls')}${rowBtn('Delete','delete','trash',t.id,'tls')}</div></div></article>`).join('')}</div>`:`<section class="card">${empty('Start with a secure connection','Import your own certificate or generate a self-signed certificate in one click.','self-signed','Generate certificate','tls')}</section>`);
}
function renderDNS() {
 const labels={dns_servers:'Resolvers',dns_rules:'DNS rules',rule_sets:'Rule sets'};
 return heading(btn('Add '+({dns_servers:'Resolver',dns_rules:'Rule',rule_sets:'Rule Set'}[dnsTab]),'new-dns','plus','primary'))+pendingBanner()+
 `<div class="tabs">${Object.entries(labels).map(([key,label])=>`<button class="tab ${dnsTab===key?'active':''}" data-action="dns-tab" data-id="${key}">${label} ${badge(num(state[key].length))}</button>`).join('')}</div>`+
 `<section class="card"><div class="card-header"><div><h2>${labels[dnsTab]}</h2><p>${dnsTab==='dns_servers'?'Default DNS: '+e(state.settings.dns_final):dnsTab==='dns_rules'?'Rules are evaluated in order, from top to bottom.':'Reusable domain lists for DNS rules'}</p></div>${icon('dns')}</div>${dnsTable()}</section>`;
}
function dnsTable() {
 const rows=state[dnsTab];if (!rows.length) return empty('Nothing here yet','Combine resolvers and domain lists with your own matching rules.','new-dns','Add new item','dns');
 const headers=dnsTab==='dns_servers'?['Tag','Type','Server','Port','Bootstrap','Actions']:dnsTab==='dns_rules'?['Match type','Values','Action','Resolver','Order / actions']:['Tag','Type','Source','Format','Actions'];
 return `<div class="table-wrap"><table><thead><tr>${headers.map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.map((r,index)=>`<tr>${dnsTab==='dns_servers'?`<td class="mono">${e(r.tag)} ${state.settings.dns_final===r.tag?badge('Default','green'):''}</td><td>${badge(r.type.toUpperCase(),'blue')}</td><td class="mono">${e(r.server||'System')}</td><td class="mono">${r.port||'—'}</td><td class="mono">${e(r.domain_resolver||'—')}</td>`:dnsTab==='dns_rules'?`<td class="mono">${e(r.match)}</td><td class="mono truncate" title="${e(r.values.join(', '))}">${e(r.values.join(', '))}</td><td>${badge(r.action,r.action==='reject'?'red':'green')}</td><td class="mono">${e(r.server||'—')}</td>`:`<td class="mono">${e(r.tag)}</td><td>${badge(r.type,'blue')}</td><td class="mono truncate" title="${e(r.url||'')}">${e(r.url||num(r.rules?.length)+' inline rules')}</td><td>${e(r.format||'JSON')}</td>`}<td><div class="row-actions">${dnsTab==='dns_rules'?`<span class="muted">${num(index+1)}</span>${rowBtn('Move up','move-rule','arrow',r.id)}`:''}${rowBtn('Edit','edit','edit',r.id,dnsTab)}${rowBtn('Delete','delete','trash',r.id,dnsTab)}</div></td></tr>`).join('')}</tbody></table></div>`;
}
function clientTable(clients,compact=false) {
 if (!clients.length) return empty('No clients to display','Create an account, assign inbounds, and set a traffic allowance and expiry date.','new-client','Create client','clients');
 return `<div class="table-wrap"><table><thead><tr><th>Client</th><th>Status</th><th>Usage / allowance</th><th>Expires</th>${compact?'':'<th>Inbounds</th>'}<th>Actions</th></tr></thead><tbody>${clients.map(c=>`<tr><td><div class="name-cell"><span class="client-avatar">${e(c.name.slice(0,2).toUpperCase())}</span><div><b>${e(c.name)}</b><small>${e(c.note||c.id.slice(0,8))}</small></div></div></td><td>${badge(...status(c))}</td><td><div class="usage"><small>${e(size(total(c)))} / ${c.quota_bytes?e(size(c.quota_bytes)):'∞'}</small><progress max="100" value="${c.quota_bytes?Math.min(100,total(c)/c.quota_bytes*100):0}" aria-label="Client usage"></progress></div></td><td>${date(c.expires_at)}</td>${compact?'':`<td>${c.inbound_ids.map(id=>badge(state.inbounds.find(i=>i.id===id)?.tag||id,'blue')).join(' ')}</td>`}<td><div class="row-actions">${rowBtn('Details & subscription','client-details','eye',c.id)}${rowBtn('Subscription QR code','subscription-qr','qr',c.id)}${rowBtn('Edit','edit','edit',c.id,'clients')}${rowBtn('Download config','export','download',c.id)}${compact?'':rowBtn('Delete','delete','trash',c.id,'clients')}</div></td></tr>`).join('')}</tbody></table></div>`;
}
function renderClients() {
 const filtered=state.clients.filter(c=>(c.name+' '+(c.note||'')).toLowerCase().includes(search.toLowerCase())&&(filter==='all'||(filter==='active'?(status(c)[0]==='Active'):(status(c)[0]!=='Active'))));
 const pages=Math.max(1,Math.ceil(filtered.length/10));pageNumber=Math.min(pageNumber,pages);
 return heading(btn('New client','new-client','plus','primary'))+pendingBanner()+`<div class="toolbar"><div class="search">${icon('search')}<input id="client-search" placeholder="Search clients…" value="${e(search)}" aria-label="Search clients"></div><select id="client-filter" aria-label="Filter clients"><option value="all" ${filter==='all'?'selected':''}>All clients</option><option value="active" ${filter==='active'?'selected':''}>Active clients</option><option value="inactive" ${filter==='inactive'?'selected':''}>Disabled & limited</option></select><span class="count">${num(filtered.length)} clients</span></div><section class="card">${clientTable(filtered.slice((pageNumber-1)*10,pageNumber*10))}<div class="table-foot"><span>${num(filtered.length)} clients · page ${num(pageNumber)} of ${num(pages)}</span><div class="pagination"><button data-action="page" data-id="${Math.max(1,pageNumber-1)}" aria-label="Previous page">→</button><button class="active">${num(pageNumber)}</button><button data-action="page" data-id="${Math.min(pages,pageNumber+1)}" aria-label="Next page">←</button></div></div></section>`;
}
function renderSettings() {
 return heading()+pendingBanner()+`<div class="settings-grid"><section class="card"><div class="card-header"><div><h2>Connection settings</h2><p>Used in client configurations and subscription links</p></div>${icon('settings')}</div><form id="settings-form" class="card-body"><label>Public server IP or domain<input name="server_address" dir="ltr" placeholder="vpn.example.com" value="${e(state.settings.server_address)}"><small class="field-hint">The address clients connect to, without a scheme or port.</small></label><label>Public panel HTTPS URL<input name="public_url" dir="ltr" placeholder="https://panel.example.com" value="${e(state.settings.public_url)}"><small class="field-hint">The base URL for subscriptions, served behind an HTTPS reverse proxy.</small></label>${selectField('Default DNS','dns_final',state.dns_servers.map(d=>[d.tag,d.tag]),state.settings.dns_final)}${optionSection('DNS cache and address preferences',optionSchema.dns,state.settings.dns_options||{},'dns')}<label class="check-field"><input name="block_private" type="checkbox" ${checked(state.settings.block_private)}>Block client access to private network IP addresses</label><button class="btn primary" type="submit">${icon('check')}Save settings</button></form></section><div><section class="card section-gap"><div class="card-header"><div><h2>Service controls</h2><p>Validate, start, and stop the core</p></div>${icon('power')}</div><div class="card-body"><div class="inline-buttons">${btn('Validate','check','tls')}${btn('Start core','apply','power','primary')}${btn('Stop','stop','power','danger')}</div><p class="note">Settings apply automatically when saved. Use Start core after an intentional stop or unexpected exit.</p></div></section><section class="card"><div class="card-header"><h2>Account security</h2>${icon('lock')}</div><div class="card-body"><p class="note">Changing your password signs out all administrator sessions.</p>${btn('Change password','change-password','key')}</div></section></div></div>`;
}
function field(label,name,value='',type='text',hint='',extra='') {return `<label ${extra}>${label}<input name="${name}" type="${type}" value="${e(value)}" ${type!=='checkbox'?'dir="auto"':''}>${hint?`<small class="field-hint">${hint}</small>`:''}</label>`;}
function selectField(label,name,options,value='',extra=''){return `<label ${extra}>${label}<select name="${name}">${options.map(([v,t])=>`<option value="${e(v)}" ${v===value?'selected':''}>${e(t)}</option>`).join('')}</select></label>`;}
function textField(label,name,value='',hint='',extra=''){return `<label ${extra}>${label}<textarea name="${name}" dir="ltr">${e(value)}</textarea>${hint?`<small class="field-hint">${hint}</small>`:''}</label>`;}
function openModal(title,subtitle,content,submit=null,submitLabel='Save') {
 modalSubmit=submit;$('#modal-body').innerHTML=`<form id="modal-form"><div class="modal-head"><div><h2>${title}</h2><p>${subtitle}</p></div><button class="icon-btn" type="button" data-action="close" aria-label="Close">${icon('close')}</button></div><div class="modal-content">${content}</div><p class="error-text form-error" id="form-error" role="alert"></p><div class="modal-actions"><button class="btn" type="button" data-action="close">${submit?'Cancel':'Close'}</button>${submit?`<button class="btn primary" type="submit">${submitLabel}</button>`:''}</div></form>`;
 if (!$('#modal').open) $('#modal').showModal();
 setTimeout(()=>$('input:not([type=checkbox]),select,textarea', $('#modal'))?.focus(),30);
}
async function saveRecord(collection,record) {const result=await api('save',{revision:state.revision,collection,record});await load();toast(result.restarted?'Saved and applied. The core is running.':'Saved and applied.');}
function editInbound(item={}) {
 const protocol=item.type||'vless';
 openModal(item.id?'Edit inbound':'New inbound','Changes are checked and applied automatically when you save.',`<div class="form-grid">${field('Name / tag','tag',item.tag||'', 'text','Letters, numbers, hyphens, and underscores')}${selectField('Protocol','type',['vless','vmess','trojan','hysteria2','tuic','anytls'].map(x=>[x,x.toUpperCase()]),protocol)}${field('Port','port',item.port||443,'number')}${field('Public port (optional)','public_port',item.public_port||'','number','For port mappings; blank uses the listen port')}${field('Listen IP','listen',item.listen||'::','text',':: for both IPv4 and IPv6')}${selectField('TLS profile','tls_id',[['','No TLS'],...state.tls.map(t=>[t.id,t.name||t.server_name])],item.tls_id||'')}${selectField('Transport','transport',['tcp','ws','grpc','http','httpupgrade','quic'].map(t=>[t,t==='tcp'?'TCP / default':t.toUpperCase()]),item.transport||'tcp')}${field('Path / service name','path',item.path||'/','text','For WebSocket, HTTP, HTTPUpgrade, or gRPC')}<label class="check-field full"><input name="enabled" type="checkbox" ${checked(item.enabled!==false)}>Enable this inbound</label></div><div id="protocol-fields"></div><div id="transport-fields"></div>${optionSection('Listener settings',optionSchema.listen,item.listen_options||{},'listen')}<div id="multiplex-fields"></div>`,async form=>{
  const d=Object.fromEntries(new FormData(form)),p=d.type;
  const serverFields=[...optionSchema.server[p],...(['hysteria2','tuic'].includes(p)?optionSchema.quic:[])];
  await saveRecord('inbounds',{id:item.id,tag:d.tag,type:p,port:Number(d.port),public_port:Number(d.public_port)||0,listen:d.listen,tls_id:d.tls_id,transport:d.transport||'tcp',path:d.path,enabled:form.elements.enabled.checked,
   server_options:readOptions(form,'server',serverFields),client_options:readOptions(form,'client',optionSchema.client[p]),listen_options:readOptions(form,'listen',optionSchema.listen),multiplex:readOptions(form,'multiplex',optionSchema.multiplex),transport_options:readOptions(form,'transport',optionSchema.transport[d.transport||'tcp'])});
 });
 const form=$('#modal-form'),protocolInput=form.elements.type,transportInput=form.elements.transport;
 function updateTransport() {
  const kind=transportInput.value;
  $('#transport-fields').innerHTML=optionSection('Transport settings',optionSchema.transport[kind],kind===item.transport?item.transport_options||{}:{},'transport',true);
  form.elements.path.closest('label').hidden=['tcp','quic'].includes(kind);
  syncOptionFields(form);
 }
 function updateProtocol() {
  const p=protocolInput.value,values=p===item.type?item.server_options||{}:{},client=p===item.type?item.client_options||{}:{};
  const quic=['hysteria2','tuic'].includes(p),restricted=quic||p==='anytls';
  if(restricted)transportInput.value='tcp';
  transportInput.disabled=restricted;transportInput.closest('label').hidden=restricted;
  $('#protocol-fields').innerHTML=optionSection(p.toUpperCase()+' settings',optionSchema.server[p],values,'server',true)+optionSection('Client connection settings',optionSchema.client[p],client,'client')+(quic?optionSection('QUIC connection settings',optionSchema.quic,values,'server'):'');
  $('#multiplex-fields').innerHTML=restricted?'':optionSection('Multiplex settings',optionSchema.multiplex,p===item.type?item.multiplex||{}:{},'multiplex');
  // Disabled selects do not enter FormData; the submit path defaults to TCP.
  updateTransport();
 }
 protocolInput.addEventListener('change',updateProtocol);transportInput.addEventListener('change',updateTransport);
 form.addEventListener('change',()=>syncOptionFields(form));updateProtocol();
}
function editClient(item={}) {
 if (!state.inbounds.length) {toast('Create an inbound first.',true);location.hash='inbounds';return;}
 const localExpiry=item.expires_at?new Date(new Date(item.expires_at).getTime()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16):'';
 openModal(item.id?'Edit client':'New client','Passwords, UUIDs, and subscription tokens are generated securely.',`<div class="form-grid">${field('Client name','name',item.name||'')}${field('Note','note',item.note||'')}${field('Traffic allowance (GiB)','quota',item.quota_bytes?item.quota_bytes/1024**3:0,'number','0 means unlimited')}${field('Expiry date and time','expires',localExpiry,'datetime-local','Leave blank for no expiry. Uses your browser\'s local time.')}<div class="field full"><span>Assigned inbounds</span><div class="checkbox-list">${state.inbounds.map(i=>`<label><input type="checkbox" name="inbound" value="${e(i.id)}" ${checked(item.inbound_ids?.includes(i.id))}>${e(i.tag)}</label>`).join('')}</div></div><label class="check-field full"><input type="checkbox" name="enabled" ${checked(item.enabled!==false)}>Enable this account</label></div>`,async form=>{
  const f=new FormData(form);const quota=Number(f.get('quota'));if(!Number.isFinite(quota)||quota<0)throw new Error('Invalid traffic allowance');
  await saveRecord('clients',{id:item.id,name:f.get('name'),note:f.get('note'),quota_bytes:Math.round(quota*1024**3),expires_at:f.get('expires')?new Date(f.get('expires')).toISOString():'',inbound_ids:f.getAll('inbound'),enabled:form.elements.enabled.checked});
 });
 $('[name=quota]',$('#modal')).step='any';
}
function editTLS(item={}) {
 openModal(item.id?'Edit certificate':'Import TLS certificate','Changes are checked and applied automatically when you save.',`<div class="form-grid">${field('Profile name','name',item.name||'')}${field('Domain / IP address','server_name',item.server_name||'')}${textField('Certificate (PEM)','certificate',item.certificate||'','The certificate must include the server name in its SAN extension.','class="full"')}${textField('Private key (PEM)','private_key','','Leave blank when editing to keep the existing private key.','class="full"')}</div>${tlsBehavior(item)}`,async form=>{
 const d=Object.fromEntries(new FormData(form));if(!d.private_key)delete d.private_key;
 await saveRecord('tls',{id:item.id,name:d.name,server_name:d.server_name,certificate:d.certificate,...(d.private_key?{private_key:d.private_key}:{}),...readOptions(form,'tls',optionSchema.tls)});
 });
}
function createSelfSigned() {
 openModal('Generate self-signed certificate','Your ECDSA key and certificate are generated on this server.',`<div class="form-grid">${field('Profile name','name','','text','e.g. NARA TLS')}${field('Server domain or IP','server_name',state.settings.server_address)}${field('Validity (days)','days',365,'number')}</div>${tlsBehavior()}`,async form=>{
  const f=new FormData(form);await api('self-signed',{name:f.get('name'),server_name:f.get('server_name'),days:Number(f.get('days')),revision:state.revision,...readOptions(form,'tls',optionSchema.tls)});await load();toast('Certificate generated and applied.');
 },'Generate certificate');
}
function editDNS(collection,item={}) {
 let content;
 if (collection==='dns_servers') content=`${field('Tag','tag',item.tag||'')}${selectField('Resolver type','type',['udp','tcp','tls','https','quic','h3','local'].map(x=>[x,x.toUpperCase()]),item.type||'https')}${field('Server address','server',item.server||'1.1.1.1')}${field('Port','port',item.port||443,'number')}${selectField('Bootstrap resolver','domain_resolver',[['','None (IP address)'],...state.dns_servers.filter(d=>d.id!==item.id).map(d=>[d.tag,d.tag])],item.domain_resolver||'')}${field('TLS server name / SNI','server_name',item.server_name||'')}${field('DoH path','path',item.path||'/dns-query')}`;
 if (collection==='dns_rules') content=`${selectField('Match type','match',['domain','domain_suffix','domain_keyword','domain_regex','query_type','rule_set'].map(x=>[x,x]),item.match||'domain_suffix')}${selectField('Action','action',[['route','Route to resolver'],['reject','Reject / block']],item.action||'route')}${textField('Values (one per line)','values',(item.values||[]).join('\n'),'For query types, enter names such as A, AAAA, or HTTPS.','class="full"')}${selectField('Target resolver','server',state.dns_servers.map(d=>[d.tag,d.tag]),item.server||state.settings.dns_final)}${optionFields(optionSchema.dns_rule,item.options||{},'rule')}`;
 if (collection==='rule_sets') content=`${field('Tag','tag',item.tag||'')}${selectField('Type','type',[['inline','Inline JSON'],['remote','Remote HTTPS']],item.type||'inline')}${field('HTTPS URL','url',item.url||'')}${selectField('Remote file format','format',[['source','Source JSON'],['binary','Binary SRS']],item.format||'source')}${field('Update interval','update_interval',item.update_interval||'','text','Remote files only; for example 24h')}${textField('Inline rules (JSON array)','rules',JSON.stringify(item.rules||[{domain_suffix:['example.com']}],null,2),'Used for inline rule sets.','class="full"')}`;
 openModal(item.id?'Edit DNS':'New '+({dns_servers:'Resolver',dns_rules:'DNS rule',rule_sets:'Rule Set'}[collection]),'Changes are checked and applied automatically when you save.',`<div class="form-grid">${content}</div>`,async form=>{
  const d=Object.fromEntries(new FormData(form));
  if (collection==='dns_servers') {d.port=Number(d.port);if(d.type==='local'){delete d.port;delete d.server;}if(!['https','tls','quic','h3'].includes(d.type))delete d.server_name;if(!['https','h3'].includes(d.type))delete d.path;}
  if (collection==='dns_rules') {d.values=d.values.split('\n').map(x=>x.trim()).filter(Boolean);d.options=readOptions(form,'rule',optionSchema.dns_rule);if(d.action==='reject'){delete d.server;for(const k of ['disable_cache','rewrite_ttl','strategy'])delete d.options[k];}for(const k of Object.keys(d))if(k.startsWith('rule.'))delete d[k];}
  if (collection==='rule_sets') {if(d.type==='inline'){d.rules=JSON.parse(d.rules);delete d.url;delete d.format;delete d.update_interval;}else delete d.rules;}
  // Replace type-specific fields rather than preserving fields from the previous type.
  const clean={...item,...d};if(collection==='rule_sets'){if(d.type==='inline'){delete clean.url;delete clean.format;delete clean.update_interval;}else delete clean.rules;}
  await saveRecord(collection,clean);
 });
  const form=$('#modal-form');
 if(collection==='dns_servers') {
  const sync=()=>{const type=form.elements.type.value;for(const key of ['server','port','domain_resolver','server_name','path']){const show=type!=='local'&&(key!=='server_name'||['tls','https','quic','h3'].includes(type))&&(key!=='path'||['https','h3'].includes(type));form.elements[key].closest('label').hidden=!show;}};
  form.elements.type.addEventListener('change',()=>{form.elements.port.value=({udp:53,tcp:53,tls:853,https:443,quic:853,h3:443,local:53})[form.elements.type.value];sync();});sync();
 }
 if(collection==='dns_rules') {
  const sync=()=>{const route=form.elements.action.value==='route';form.elements.server.closest('label').hidden=!route;for(const key of ['disable_cache','rewrite_ttl','strategy']){const input=form.elements.namedItem('rule.'+key);input.closest('label').hidden=!route;input.disabled=!route;}};
  form.elements.action.addEventListener('change',sync);sync();
 }
 if(collection==='rule_sets') {
  const sync=()=>{const inline=form.elements.type.value==='inline';for(const key of ['url','format','update_interval'])form.elements[key].closest('label').hidden=inline;form.elements.rules.closest('label').hidden=!inline;};form.elements.type.addEventListener('change',sync);sync();
 }
}
function download(name,content,type='application/json') {const blob=new Blob([typeof content==='string'?content:JSON.stringify(content,null,2)],{type});const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
function subscriptionURL(client) {
 const base=new URL(state.settings.public_url);
 if(base.pathname==='/') base.pathname=new URL('.',location.href).pathname;
 return base.href.replace(/\/$/,'')+'/sub/'+client.token;
}
function subscriptionShare(client) {
 if (!state.settings.public_url) return `<p class="note">Set the panel's public HTTPS URL in Settings to generate subscription links and QR codes.</p>${btn('Open settings','subscription-settings','settings','sm')}`;
 const sub=subscriptionURL(client);
 let qr,qrReady=false;
 try { qr=`<div class="subscription-qr">${NaraQR.svg(sub)}</div>`;qrReady=true; }
 catch { qr='<p class="note">This link is too long for a QR code. Copy the subscription link below.</p>'; }
 return `<div class="subscription-share">${qr}<div class="subscription-access"><p class="note">Scan with a client that supports Sing-box JSON subscriptions.</p><div class="subscription-url">${e(sub)}</div><div class="inline-buttons">${btn('Copy link','copy-sub','code','sm',`data-id="${e(client.id)}"`)}${qrReady?btn('Download QR','download-qr','qr','sm',`data-id="${e(client.id)}"`):''}${btn('Download config','export','download','sm',`data-id="${e(client.id)}"`)}</div></div></div>`;
}
function subscriptionQR(id) {
 const client=state.clients.find(c=>c.id===id);
 openModal('Subscription QR code',e(client.name),`${subscriptionShare(client)}<p class="note">Keep this QR code private. Anyone with it can access this account's subscription.</p>`);
}
async function downloadQR(client) {
 const svg=NaraQR.svg(subscriptionURL(client));
 const image=new Image();
 image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);
 await image.decode();
 const canvas=document.createElement('canvas');
 canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
 const context=canvas.getContext('2d');
 if (!context) throw new Error('Could not create the QR image.');
 context.drawImage(image,0,0);
 const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
 if (!blob) throw new Error('Could not download the QR image.');
 const url=URL.createObjectURL(blob),anchor=document.createElement('a');
 anchor.href=url;anchor.download='nara-subscription-'+client.id.slice(0,8)+'.png';anchor.click();
 setTimeout(()=>URL.revokeObjectURL(url),3000);
 toast('Subscription QR code downloaded.');
}
function details(id) {
 const c=state.clients.find(x=>x.id===id);const usage=dashboard.totals[c.id]||{};
 openModal(e(c.name),'Account details and connection access',`<div class="detail-stats"><div><small>Total usage</small><b>${e(size(total(c)))}</b></div><div><small>Remaining traffic</small><b>${c.quota_bytes?e(size(Math.max(0,c.quota_bytes-total(c)))):'∞'}</b></div><div><small>Account status</small><b>${badge(...status(c))}</b></div></div>${info('Upload / download',`<span class="mono">${e(size(usage.upload||0))} / ${e(size(usage.download||0))}</span>`)}${info('Expires',date(c.expires_at))}${info('UUID',`<span class="mono">${e(c.uuid)}</span>`)}${info('Inbounds',c.inbound_ids.map(id=>e(state.inbounds.find(i=>i.id===id)?.tag||id)).join(', '))}<br><h3>Sing-box JSON subscription</h3>${subscriptionShare(c)}<p class="note">Exports use the active configuration. Keep this subscription link private: it contains account credentials.</p><div class="destructive-zone">${btn('Reset usage','reset-traffic','refresh','sm',`data-id="${id}"`)}${btn('Rotate subscription link','rotate-token','key','sm',`data-id="${id}"`)}</div>`);
}
function confirmAction(title,text,run,label='Confirm') {openModal(title,'',`<p class="confirm-text">${e(text)}</p>`,run,label);}
async function handle(action,target) {
 const id=target.dataset.id,collection=target.dataset.collection;
 if(action==='close')return $('#modal').close();
 if(action==='new-inbound')return editInbound();
 if(action==='new-client')return editClient();
 if(action==='self-signed')return createSelfSigned();
 if(action==='import-tls')return editTLS();
 if(action==='new-dns')return editDNS(dnsTab);
 if(action==='dns-tab'){dnsTab=id;return render();}
 if(action==='page'){pageNumber=Number(id);return render();}
 if(action==='edit') {const item=state[collection].find(x=>x.id===id);return collection==='clients'?editClient(item):collection==='inbounds'?editInbound(item):collection==='tls'?editTLS(item):editDNS(collection,item);}
 if(action==='delete')return confirmAction('Delete item','Delete this item? Remove its references from other settings first.',async()=>{await api('delete',{revision:state.revision,collection,id});await load();toast('Deleted and applied.');},'Delete');
 if(action==='apply'){await api('apply',{revision:state.revision});await load();toast('The core is running.');return;}
 if(action==='stop')return confirmAction('Stop Sing-box','All client connections will disconnect. The core will stay stopped until you start it from the panel.',async()=>{await api('stop',{});await load();toast('Core stopped.');},'Stop');
 if(action==='check'){await api('check',{});toast('Configuration validated by the core.');return;}
 if(action==='config'){previewConfig=await api('config');openModal('Server config','Current settings. Contains confidential client credentials.',`<pre class="code">${e(JSON.stringify(previewConfig,null,2))}</pre><p class="note">TLS paths refer to files in the current configuration generation.</p>`);return;}
 if(action==='client-details')return details(id);
 if(action==='subscription-qr')return subscriptionQR(id);
 if(action==='download-qr')return downloadQR(state.clients.find(c=>c.id===id));
 if(action==='subscription-settings'){$('#modal').close();location.hash='settings';return;}
 if(action==='export'){const config=await api('export/'+id);download('nara-'+id.slice(0,8)+'.json',config);toast('Client configuration downloaded.');return;}
 if(action==='download-cert'){const t=state.tls.find(x=>x.id===id);return download(t.server_name+'.crt',t.certificate,'application/x-pem-file');}
 if(action==='copy-sub'){const c=state.clients.find(x=>x.id===id);await navigator.clipboard.writeText(subscriptionURL(c));toast('Subscription link copied.');return;}
 if(action==='rotate-token'||action==='reset-traffic')return confirmAction(action==='rotate-token'?'Rotate subscription link':'Reset traffic usage',action==='rotate-token'?'The previous subscription link will stop working immediately. Previously downloaded configurations remain valid.':'Reset this account\'s traffic usage to zero? The account is reactivated automatically if its other limits allow access.',async()=>{await api(action,{id,revision:state.revision});await load();toast('Done.');});
 if(action==='move-rule'){
  const index=state.dns_rules.findIndex(r=>r.id===id);if(index<=0)return;
  // Explicit ordered update, validated atomically by the server.
  await api('reorder-rules',{revision:state.revision,id});await load();toast('Rule order saved and applied.');return;
 }
 if(action==='change-password')return openModal('Change password','You will need to sign in again after saving.',`<div class="form-grid">${field('Current password','current','','password','','class="full"')}${field('New password','password','','password','At least 12 characters','class="full"')}</div>`,async form=>{await api('password',Object.fromEntries(new FormData(form)));showLogin();toast('Password changed. Please sign in again.');});
}
document.addEventListener('click',async event=>{const target=event.target.closest('[data-action]');if(!target)return;event.preventDefault();target.disabled=true;try{await handle(target.dataset.action,target);}catch(err){toast(err.message,true);}finally{target.disabled=false;}});
document.addEventListener('submit',async event=>{
 const form=event.target;if(!['modal-form','login-form','settings-form'].includes(form.id))return;event.preventDefault();const submit=$('[type=submit]',form),label=submit?.textContent;if(submit){submit.disabled=true;submit.textContent='Saving…';}
 try {
  if(form.id==='login-form'){const result=await api('login',Object.fromEntries(new FormData(form)));csrf=result.csrf;form.elements.password.value='';$('#login-error').textContent='';await boot();}
  else if(form.id==='modal-form'&&modalSubmit){$('#form-error').textContent='';await modalSubmit(form);$('#modal').close();}
  else if(form.id==='settings-form'){const f=new FormData(form);const d={server_address:f.get('server_address'),public_url:f.get('public_url'),dns_final:f.get('dns_final'),block_private:form.elements.block_private.checked,dns_options:readOptions(form,'dns',optionSchema.dns)};await api('settings',{revision:state.revision,settings:d});await load();toast('Settings saved and applied.');}
 }catch(err){if(form.id==='modal-form')$('#form-error').textContent=err.message;else if(form.id==='login-form')$('#login-error').textContent=err.message;else toast(err.message,true);}finally{if(submit){submit.disabled=false;submit.textContent=label;}}
});
document.addEventListener('input',event=>{if(event.target.id==='client-search'){const pos=event.target.selectionStart;search=event.target.value;pageNumber=1;render();const input=$('#client-search');input.focus();input.setSelectionRange(pos,pos);}});
document.addEventListener('change',event=>{if(event.target.id==='client-filter'){filter=event.target.value;pageNumber=1;render();}});
window.addEventListener('hashchange',()=>{search='';filter='all';pageNumber=1;$('.sidebar').classList.remove('open');render();});
$('#refresh').innerHTML=icon('refresh');$('#refresh').addEventListener('click',async()=>{try{await load();toast('Server data refreshed.');}catch(err){toast(err.message,true);}});
$('#logout').addEventListener('click',async()=>{try{await api('logout',{});showLogin();}catch(err){toast(err.message,true);}});
$('#mobile-menu').addEventListener('click',()=>$('.sidebar').classList.toggle('open'));
document.addEventListener('click',event=>{if($('.sidebar').classList.contains('open')&&!event.target.closest('.sidebar,#mobile-menu'))$('.sidebar').classList.remove('open');});
setInterval(()=>{if(csrf&&!document.hidden&&!$('#modal').open)load(true).catch(err=>toast(err.message,true));},5000);
$('#content').innerHTML='<div class="loading"><span class="logo">N</span>Loading your server…</div>';
boot();
