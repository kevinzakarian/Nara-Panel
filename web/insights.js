'use strict';
function trafficAllowanceCard(compact=false){
 const t=dashboard.traffic;if(!t)return '';
 const limit=t.settings.monthly_bytes,used=t.cycle.used,percent=limit?100*used/limit:0;
 return `<section class="card section-gap allowance-card"><div class="card-header"><div><span class="section-kicker">SERVER ALLOWANCE</span><h2>Monthly server traffic</h2><p>${e(t.interface||'Waiting for network interface')} · ${e(t.settings.count==='both'?'Upload + download':t.settings.count==='upload'?'Upload only':'Download only')} · resets on day ${t.settings.reset_day}</p></div>${badge(t.available?'Tracking':'Unavailable',t.available?'green':'orange')}</div><div class="card-body"><div class="allowance-value"><b>${e(size(used))}</b><span>${limit?'of '+e(size(limit)):'No monthly limit set'}</span><strong>${limit?percent.toFixed(1)+'%':''}</strong></div><progress class="allowance-progress" value="${Math.min(100,percent)}" max="100" aria-label="Monthly traffic allowance used"></progress><div class="allowance-meta"><span>Tracked since ${date(t.cycle.since)} · ${time(t.cycle.since)}</span><span>Next reset ${date(t.cycle.end)}</span></div><p class="note">Host interface counters; provider billing can differ. No traffic is estimated before tracking began.</p>${compact?'':`<div class="inline-buttons">${btn('Reset monthly counter','insights-reset-cycle','refresh','sm')}${btn('History','insights-chart','traffic','sm','data-kind="server" data-id="host"')}</div>`}</div></section>`;
}
function trafficNumber(label,name,value,hint=''){
 const maximum=name==='reset_day'?31:name==='duration_minutes'?1440:['traffic_percent','cpu_percent','memory_percent','disk_percent'].includes(name)?100:10000000;
 return field(label,name,value,'number',hint).replace('type="number"',`type="number" required min="${name==='reset_day'||name==='duration_minutes'?1:0}" max="${maximum}" step="${['monthly_gib','bandwidth_mbps'].includes(name)?'any':1}"`);
}
function renderTrafficSettings(embedded=false){
 const t=dashboard.traffic;if(!t)return '';const s=t.settings;
 return `<section class="card section-gap"><div class="card-header"><div><span class="section-kicker">SERVER TRAFFIC</span><h2>Traffic allowance & accounting</h2><p>Provider billing and panel traffic use independent counters</p></div></div><div class="card-body preference-fields">${trafficAllowanceCard()}<${embedded?'div':'form'} ${embedded?'':'id="traffic-settings-form"'} class="preference-fields"><div class="form-grid">${trafficNumber('Monthly allowance (GiB)','monthly_gib',s.monthly_bytes/1024**3,'0 means no allowance limit. 1 GiB = 1024³ bytes.')}${selectField('Monthly reset day','reset_day',Array.from({length:31},(_,i)=>[String(i+1),String(i+1)]),String(s.reset_day))}${selectField('Network interface','interface',[['','Automatic · default route'],...t.interfaces.map(x=>[x,x])],s.interface)}${selectField('Provider counts','count',[['both','Upload + download'],['upload','Upload only'],['download','Download only']],s.count)}</div><p class="note">The panel time zone controls the reset date. Days 29–31 use the last day of shorter months. Changing interface establishes a fresh hardware baseline. Changing the reset day starts a newly observed billing period.</p>${embedded?'':'<button class="btn primary" type="submit">Save traffic settings</button>'}</${embedded?'div':'form'}><div class="traffic-accounting"><h3>Panel traffic accounting</h3><div class="allowance-value"><b>${e(size(t.panel_bytes))}</b></div><p class="note">Resetting this display retains client quota usage, historical charts, host lifetime counters and the monthly server counter.</p>${btn('Reset panel display counter','insights-reset-panel','refresh','sm')}</div><a class="text-link" href="#notifications">Configure Telegram traffic and resource alerts →</a></div></section>`;
}
function renderAlertThresholds(){
 const s=dashboard.traffic?.settings;if(!s)return '';
 return `<section class="card"><div class="card-header"><div><span class="section-kicker">SERVER HEALTH</span><h2>Telegram alert thresholds</h2><p>Choose when sustained resource usage becomes an incident</p></div></div><form id="traffic-alert-form" class="card-body preference-fields"><div class="form-grid">${trafficNumber('Monthly traffic warning (%)','traffic_percent',s.traffic_percent,'0 disables this warning.')}${trafficNumber('Sustained duration (minutes)','duration_minutes',s.duration_minutes,'CPU, memory, disk and bandwidth must stay above their thresholds this long.')}${trafficNumber('CPU (%)','cpu_percent',s.cpu_percent)}${trafficNumber('Memory (%)','memory_percent',s.memory_percent)}${trafficNumber('Disk (%)','disk_percent',s.disk_percent)}${trafficNumber('Network throughput (Mbps)','bandwidth_mbps',s.bandwidth_mbps,'Upload + download speed. 0 disables the bandwidth alert.')}</div><p class="note">0 disables a threshold. One alert per incident; recovery requires one minute below 90% of the threshold. Missing samples break the sustained interval. Enable Server health events and Telegram delivery above.</p><button class="btn primary" type="submit">Save alert thresholds</button></form></section>`;
}
function trafficChartMarkup(data){
 const points=data.points||[],up=points.reduce((s,p)=>s+p.upload,0),down=points.reduce((s,p)=>s+p.download,0);
 if(!data.recording_since)return '<p class="note">No recorded history yet. Traffic is collected from this version onward.</p>';
 const max=Math.max(1,...points.map(p=>p.upload+p.download)),width=640,height=150,gap=2,bar=width/Math.max(1,points.length);
 return `<div class="chart-totals"><div><span><i class="legend-dot green"></i>Upload</span><b>${e(size(up))}</b></div><div><span><i class="legend-dot"></i>Download</span><b>${e(size(down))}</b></div></div><div class="history-chart"><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Traffic per interval, upload and download"><path d="M0 149H640 M0 75H640" stroke="var(--border)"/>${points.map((p,i)=>{const u=p.upload/max*140,d=p.download/max*140;return `<g><title>${e(date(p.at)+' '+time(p.at)+' · Upload '+size(p.upload)+' · Download '+size(p.download))}</title><rect x="${(i*bar).toFixed(2)}" y="${height-d}" width="${Math.max(.7,bar-gap).toFixed(2)}" height="${d.toFixed(2)}" rx="1" fill="var(--chart-accent,var(--accent))"/><rect x="${(i*bar).toFixed(2)}" y="${height-d-u}" width="${Math.max(.7,bar-gap).toFixed(2)}" height="${u.toFixed(2)}" rx="1" fill="var(--chart-upload)"/></g>`}).join('')}</svg></div><div class="chart-labels"><span>${date(data.start)} · ${time(data.start)}</span><span>${date(data.end)} · ${time(data.end)}</span></div><p class="note">Recorded since ${date(data.recording_since)} · ${time(data.recording_since)}. Historical usage survives client quota resets. Hover over a bar for interval totals.</p>`;
}
async function openTrafficChart(kind,id){
 const item=(kind==='client'?state.clients:kind==='inbound'?state.inbounds:[]).find(x=>x.id===id);
 openModal('Traffic history',item?.name||item?.tag||'Server interface',`<div class="chart-controls">${selectField('Time range','history_range',[['6h','Last 6 hours'],['24h','Last 24 hours'],['week','This week'],['month','This month'],['3months','Last 90 days']],'24h')}</div><div id="history-result" role="status">Loading recorded traffic…</div>`);
 const form=$('#modal-form');let sequence=0;
 async function update(){const number=++sequence;const box=$('#history-result',form);box.textContent='Loading recorded traffic…';try{const data=await api('traffic?kind='+encodeURIComponent(kind)+'&id='+encodeURIComponent(id)+'&range='+encodeURIComponent(form.elements.history_range.value));if(form.isConnected&&number===sequence)box.innerHTML=trafficChartMarkup(data);}catch(error){if(form.isConnected&&number===sequence)box.textContent=error.message;}}
 form.elements.history_range.onchange=update;await update();
}
async function showConfigLinks(id){
 const client=state.clients.find(x=>x.id===id);if(!client)throw Error('Client no longer exists.');
 const result=await api('client-links/'+encodeURIComponent(id));
 openModal(e(client.name)+' · Config links','Protocol share links contain credentials. Keep them private.',(result.links.length?result.links.map((row,i)=>`<label>${e(row.name)} · ${e(protocolLabel(row.protocol))}<textarea readonly class="config-share-link" id="config-share-${i}">${e(row.url)}</textarea></label><button class="btn sm" type="button" data-action="insights-copy-config" data-id="${i}">${icon('code')}Copy config link</button>`).join('<br>'):'<p class="note">Set the public server address and assign an enabled inbound to generate config links.</p>')+'<p class="note">Some apps cannot represent every advanced option or certificate in a protocol URI. The Sing-box JSON subscription preserves the complete profile.</p>');
}
function trafficSettingsValues(form){
 const f=new FormData(form),s={...dashboard.traffic.settings};
 for(const name of ['reset_day','traffic_percent','cpu_percent','memory_percent','disk_percent','duration_minutes','bandwidth_mbps'])if(f.has(name))s[name]=Number(f.get(name));
 if(f.has('monthly_gib')){const amount=Number(f.get('monthly_gib'));if(!Number.isFinite(amount)||amount<0)throw Error('Enter a valid monthly allowance.');s.monthly_bytes=Math.round(amount*1024**3);}
 for(const key of ['interface','count'])if(f.has(key))s[key]=f.get(key);
 return s;
}
async function saveTrafficSettings(form){
 const settings=trafficSettingsValues(form);await api('traffic/settings',{settings,scope:form.id==='traffic-alert-form'?'alerts':'allowance'});dashboard.traffic.settings=settings;toast('Traffic alert settings saved.');
}
async function handleInsights(action,target){
 if(action==='insights-chart')return openTrafficChart(target.dataset.kind,target.dataset.id);
 if(action==='insights-links')return showConfigLinks(target.dataset.id);
 if(action==='insights-copy-config'){
  const input=$('#config-share-'+target.dataset.id);let copied=false;
  if(navigator.clipboard?.writeText){try{await navigator.clipboard.writeText(input.value);copied=true;}catch{}}
  if(!copied){input.focus();input.select();try{copied=Boolean(document.execCommand?.('copy'));}catch{}}
  if(!copied)throw Error('Select and copy the config link shown above.');toast('Config link copied.');return;
 }
 if(action.startsWith('insights-reset-')){const kind=action==='insights-reset-cycle'?'cycle':'panel';return confirmAction(kind==='cycle'?'Reset monthly counter':'Reset panel display counter','Start this counter at zero now? Client quota usage and historical charts are retained.',async()=>{await api('traffic/reset',{kind});await load();toast('Counter reset.');});}
 if(action==='insights-export-csv'){
  const ids=selectedClients.size?[...selectedClients]:filteredClients().map(x=>x.id);
  return notificationVerification('Export clients','Export '+ids.length+' client(s). The CSV contains private subscription links and credentials.',async form=>{const result=await api('clients-csv',{...Object.fromEntries(new FormData(form)),ids});download('nara-clients.csv',result.csv,'text/csv;charset=utf-8');toast('Client CSV downloaded.');},'Download private CSV');
 }
}
