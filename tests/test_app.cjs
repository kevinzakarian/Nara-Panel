const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const fixture=JSON.parse(execFileSync(process.env.NARA_TEST_PYTHON||'python3',['-c','import json; from nara import options,native; from nara.config import initial_state; print(json.dumps(dict(options=options.schema(),catalog=native.payload(),state=initial_state())))'],{env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
function app(){
 const dom=new JSDOM('<dialog id="modal"><div id="modal-body"></div></dialog><div id="toasts"></div>',{runScripts:'outside-only',url:'http://panel.example.com:10000/PanelOnly/'}),w=dom.window;
 w.structuredClone=value=>JSON.parse(JSON.stringify(value));
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
 w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const source=fs.readFileSync('web/app.js','utf8');
 w.eval(fs.readFileSync('web/dns-presets.js','utf8')+'\n'+fs.readFileSync('web/core-editor.js','utf8')+'\n'+fs.readFileSync('web/options.js','utf8')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.TestApp={setup(value){optionSchema=value.options;coreCatalog=value.catalog;state=value.state;CoreSchema.configure(coreCatalog)},dashboard(value){dashboard=value;return renderDashboard()},editInbound,editCoreRecord,saveWith(handler){saveRecord=handler},submit(){return modalSubmit($('#modal-form'))},enterWith(handler){api=handler;load=async()=>{};return boot()}};`);
 w.TestApp.setup(fixture);
 return {w,dom,close(){w.close()}};
}
test('new IP resolver is independent and hostname resolver can be explicitly selected',()=>{
 const f=app();try{
  f.w.TestApp.editCoreRecord('dns_servers');
  const document=f.w.document;
  document.querySelector('#core-to-json').click();
  assert.equal(JSON.parse(document.querySelector('#native-json').value).server,'1.1.1.1');
  assert.ok(!Object.hasOwn(JSON.parse(document.querySelector('#native-json').value),'domain_resolver'));
  const server=[...document.querySelectorAll('#native-fields label')].find(label=>label.firstChild?.textContent==='Server').querySelector('textarea');
  server.value='dns.google';server.dispatchEvent(new f.w.Event('input',{bubbles:true}));
  assert.equal(document.querySelector('[data-core-add]'),null);
  const resolver=[...document.querySelectorAll('#native-fields label')].find(label=>label.firstChild?.textContent==='Domain Resolver').querySelector('select');
  resolver.value='bootstrap';resolver.dispatchEvent(new f.w.Event('input',{bubbles:true}));
  document.querySelector('#core-to-json').click();
  const config=JSON.parse(document.querySelector('#native-json').value);
  assert.equal(config.server,'dns.google');assert.equal(config.domain_resolver,'bootstrap');
 }finally{f.close()}
});
test('saving UDP Google DNS uses the visible pasted IP even without an input event',async()=>{
 const f=app();try{
  let saved;
  f.w.TestApp.saveWith(async(collection,record)=>{saved=JSON.parse(JSON.stringify(record))});
  f.w.TestApp.editCoreRecord('dns_servers',{}, {type:'https',tag:'google',server:'dns.google',path:'/dns-query',tls:{enabled:true}});
  const d=f.w.document;
  const control=label=>[...d.querySelectorAll('#native-fields label')].find(node=>node.firstChild?.textContent===label)?.querySelector('textarea,input,select');
  control('Server').value=' \t8.8.8.8\n';
  const variant=d.querySelector('[data-core-variant]');
  variant.value=[...variant.options].find(option=>option.textContent==='UDP').value;
  variant.dispatchEvent(new f.w.Event('change',{bubbles:true}));
  assert.equal(control('Server Port').value,'53');
  control('Server Port').value='53';
  await f.w.TestApp.submit();
  assert.deepEqual(saved.config,{type:'udp',tag:'google',server:'8.8.8.8',server_port:53});
  assert.equal(saved.mode,'native');
 }finally{f.close()}
});
test('DNS port is always visible, essential fields are protected and invalid ports cannot be saved',async()=>{
 const f=app();try{
  let saved;f.w.TestApp.saveWith(async(c,r)=>{saved=r});
  f.w.TestApp.editCoreRecord('dns_servers',{}, {type:'udp',tag:'google',server:'8.8.8.8'});
  const d=f.w.document,control=key=>d.querySelector(`[data-dns-field="${key}"] [data-core-input]`);
  for(const key of ['tag','server','server_port']){assert.ok(control(key).required);assert.equal(d.querySelector(`[data-core-remove][data-key="${key}"]`),null);}
  assert.equal(d.querySelector('[data-core-add]'),null);
  control('server_port').value='5353';await f.w.TestApp.submit();assert.equal(saved.config.server_port,5353);
  for(const invalid of ['','0','65536','53.5']){control('server_port').value=invalid;await assert.rejects(f.w.TestApp.submit(),/Server Port/);}
  control('server_port').value='53';control('server').value=' ';await assert.rejects(f.w.TestApp.submit(),/Server address/);
 }finally{f.close()}
});
test('DNS protocol switching supplies correct ports, preserves a custom port and drops incompatible TLS',()=>{
 const f=app();try{
  f.w.TestApp.editCoreRecord('dns_servers',{}, {type:'udp',tag:'test',server:'8.8.8.8'});
  f.w.document.querySelector('[name=dns_provider]').value='custom';f.w.document.querySelector('[name=dns_provider]').dispatchEvent(new f.w.Event('change'));
  const d=f.w.document,read=()=>{d.querySelector('#core-to-json').click();return JSON.parse(d.querySelector('#native-json').value)};
  const change=name=>{const select=d.querySelector('[data-core-variant]');select.value=[...select.options].find(x=>x.textContent===name).value;select.dispatchEvent(new f.w.Event('change',{bubbles:true}));};
  for(const [name,port] of [['TCP',53],['TLS',853],['QUIC',853],['HTTPS',443],['HTTP/3',443]]){change(name);assert.equal(read().server_port,port);}
  const port=d.querySelector('[data-dns-field="server_port"] input');port.value='8443';change('TLS');assert.equal(read().server_port,8443);
  change('UDP');assert.equal(read().server_port,8443);assert.ok(!Object.hasOwn(read(),'tls'));assert.equal(d.querySelector('[data-dns-field="tls"]'),null);
 }finally{f.close()}
});
test('DNS advanced controls preserve TLS trust, resolver objects and custom settings across edits',async()=>{
 const f=app();try{
  const config={type:'https',tag:'secure',server:'dns.google',server_port:8443,path:'/custom',domain_resolver:{server:'bootstrap',strategy:'ipv4_only',timeout:'3s'},tls:{enabled:true,server_name:'dns.google',certificate:['DEMO CERT'],client_key:['DEMO KEY'],alpn:['h2']},headers:{Authorization:' preserve spaces '},connect_timeout:'5s'};
  let saved;f.w.TestApp.saveWith(async(c,r)=>{saved=JSON.parse(JSON.stringify(r.config))});
  f.w.TestApp.editCoreRecord('dns_servers',{}, config);
  const d=f.w.document;assert.equal(d.querySelector('[data-core-add]'),null);
  d.querySelector('[data-dns-field="server_port"] input').value='9443';await f.w.TestApp.submit();assert.deepEqual(saved,{...config,server_port:9443});
  const toggle=[...d.querySelectorAll('[data-core-toggle]')].find(x=>x.dataset.key==='connect_timeout'&&x.checked);toggle.checked=false;toggle.dispatchEvent(new f.w.Event('change',{bubbles:true}));
  await f.w.TestApp.submit();assert.ok(!Object.hasOwn(saved,'connect_timeout'));assert.deepEqual(saved.tls,config.tls);assert.deepEqual(saved.headers,config.headers);
 }finally{f.close()}
});
test('DNS provider templates fill endpoints and offer only supported protocols while Custom keeps all types',async()=>{
 const f=app();try{
  let saved;f.w.TestApp.saveWith(async(c,r)=>{saved=JSON.parse(JSON.stringify(r.config))});
  f.w.TestApp.editCoreRecord('dns_servers');
  const d=f.w.document,provider=d.querySelector('[name=dns_provider]');
  provider.value='google';provider.dispatchEvent(new f.w.Event('change'));
  assert.equal(d.querySelector('[data-dns-field="server"] textarea').value,'8.8.8.8');
  assert.equal(d.querySelector('[data-dns-field="tag"] textarea').value,'dns-google');
  const protocols=()=>d.querySelector('[data-core-variant]');
  assert.deepEqual([...protocols().options].map(x=>x.textContent),['HTTPS','TCP','TLS','UDP']);
  protocols().value=[...protocols().options].find(x=>x.textContent==='TLS').value;protocols().dispatchEvent(new f.w.Event('change',{bubbles:true}));
  await f.w.TestApp.submit();assert.equal(saved.type,'tls');assert.equal(saved.server_port,853);assert.equal(saved.tls.server_name,'dns.google');assert.ok(!Object.hasOwn(saved,'path'));assert.ok(!Object.hasOwn(saved,'domain_resolver'));
  provider.value='custom';provider.dispatchEvent(new f.w.Event('change'));assert.equal(protocols().options.length,15);await f.w.TestApp.submit();assert.equal(saved.server,'8.8.8.8');
  provider.value='quad9';provider.dispatchEvent(new f.w.Event('change'));assert.equal(d.querySelector('[data-dns-field="tag"] textarea').value,'dns-google');
  d.querySelector('[data-dns-field="tag"] textarea').value='';provider.value='adguard';provider.dispatchEvent(new f.w.Event('change'));assert.equal(d.querySelector('[data-dns-field="tag"] textarea').value,'dns-adguard');
  provider.value='cloudflare';provider.dispatchEvent(new f.w.Event('change'));assert.equal(d.querySelector('[data-dns-field="tag"] textarea').value,'dns-cloudflare');
 }finally{f.close()}
});
test('NextDNS needs a profile and preserves it for HTTPS, TLS and QUIC, including silent ID edits',async()=>{
 const f=app();try{
  let saved;f.w.TestApp.saveWith(async(c,r)=>{saved=JSON.parse(JSON.stringify(r.config))});
  f.w.TestApp.editCoreRecord('dns_servers');const d=f.w.document,provider=d.querySelector('[name=dns_provider]');provider.value='nextdns';provider.dispatchEvent(new f.w.Event('change'));
  assert.equal(d.querySelector('#dns-profile-field').hidden,false);await assert.rejects(f.w.TestApp.submit(),/Profile ID/);
  d.querySelector('[name=dns_profile_id]').value='AB12CD';await f.w.TestApp.submit();assert.equal(saved.path,'/ab12cd');assert.equal(saved.tls.server_name,'dns.nextdns.io');
  for(const type of ['TLS','QUIC']){const protocol=d.querySelector('[data-core-variant]');protocol.value=[...protocol.options].find(x=>x.textContent===type).value;protocol.dispatchEvent(new f.w.Event('change',{bubbles:true}));await f.w.TestApp.submit();assert.equal(saved.tls.server_name,'ab12cd.dns.nextdns.io');assert.equal(saved.server_port,853);assert.ok(!Object.hasOwn(saved,'path'));}
  provider.value='custom';provider.dispatchEvent(new f.w.Event('change'));assert.equal(d.querySelector('[name=dns_profile_id]').disabled,true);
 }finally{f.close()}
});
test('DNS JSON imports leave provider constraints and preserve custom transports; existing tags are never renamed',async()=>{
 const f=app();try{
  let saved;f.w.TestApp.saveWith(async(c,r)=>{saved=JSON.parse(JSON.stringify(r.config))});
  f.w.TestApp.editCoreRecord('dns_servers',{id:'stored',config:{type:'tls',tag:'dns-google',server:'8.8.8.8',server_port:853,tls:{enabled:true,server_name:'dns.google'}}});
  const d=f.w.document,provider=d.querySelector('[name=dns_provider]');provider.value='cloudflare';provider.dispatchEvent(new f.w.Event('change'));await f.w.TestApp.submit();assert.equal(saved.tag,'dns-google');
  const config={type:'h3',tag:'custom-json',server:'192.0.2.1',server_port:8443,path:'/private-dns',tls:{enabled:true,server_name:'resolver.example',certificate:['DEMO CA'],client_key:['DEMO KEY']},headers:{Authorization:' demo only '}};
  d.querySelector('#native-json').value=JSON.stringify(config);d.querySelector('#core-from-json').click();
  assert.equal(provider.value,'custom');assert.equal(d.querySelector('[data-core-variant]').options.length,15);await f.w.TestApp.submit();assert.deepEqual(saved,config);
 }finally{f.close()}
});
test('update status has no daily schedule and displays in-progress checks separately',()=>{
 const f=app();try{
  const data={metrics:{hostname:'demo',platform:'Linux',cpu_count:1,cpu_percent:null,uptime:null,load:[0,0,0],disk_total:1,disk_used:0,samples:[]},core:{running:false,version:'1.14.3'},panel_version:'0.6.4',totals:{},events:[],updates:{checking:true,panel:{},core:{}}};
  const root=f.w.document.createElement('div');root.innerHTML=f.w.TestApp.dashboard(data);
  assert.ok(root.textContent.includes('Checking for updates'));assert.ok(!root.textContent.includes('24 hours'));assert.equal(root.querySelector('[aria-label="Daily update checks"]'),null);
 }finally{f.close()}
});
test('authenticated panel entry triggers both-version checks once per entry and failure does not prevent access',async()=>{
 const f=app();try{
  for(const id of ['login','app','admin-name','login-error']){const el=f.w.document.createElement('div');el.id=id;f.w.document.body.append(el);}
  const calls=[],handler=async(path,body)=>{calls.push({path,body});if(path==='session')return {csrf:'entry-csrf',username:'admin'};if(path==='options')return fixture.options;if(path==='core-schema')return fixture.catalog;if(path==='check-updates')throw new Error('offline');};
  await f.w.TestApp.enterWith(handler);await f.w.TestApp.enterWith(handler);
  assert.equal(calls.filter(x=>x.path==='check-updates').length,2);assert.ok(calls.filter(x=>x.path==='check-updates').every(x=>x.body&&Object.keys(x.body).length===0));
  assert.equal(f.w.document.querySelector('#app').hidden,false);assert.equal(f.w.document.querySelector('#login').hidden,true);
 }finally{f.close()}
});
test('new inbound requires choosing a protocol before saving',()=>{
 const f=app();try{
  f.w.TestApp.editInbound();const document=f.w.document,select=document.querySelector('[name=type]');
  assert.equal(select.value,'');assert.equal(select.selectedOptions[0].textContent,'Choose a protocol');
  assert.ok(document.querySelector('[type=submit]').disabled);
  select.value='anytls';select.dispatchEvent(new f.w.Event('change'));
  assert.equal(document.querySelector('[type=submit]').disabled,false);
  assert.equal(document.querySelector('[name="server.padding_scheme"]').value,fixture.options.server.anytls[0].default.join('\n'));
  assert.equal(document.querySelector('[name="server.padding_scheme"]').value.split('\n').length,9);
 }finally{f.close()}
});
test('editing AnyTLS preserves a deliberately customized padding scheme',()=>{
 const f=app();try{
  f.w.TestApp.editInbound({type:'anytls',server_options:{padding_scheme:['stop=1','0=20-20']}});
  assert.equal(f.w.document.querySelector('[name="server.padding_scheme"]').value,'stop=1\n0=20-20');
 }finally{f.close()}
});
test('standalone AnyTLS starts from the same official padding preset',()=>{
 const f=app();try{
  f.w.TestApp.editInbound({mode:'native'});
  const select=f.w.document.querySelector('[name=type]');select.value='anytls';select.dispatchEvent(new f.w.Event('change'));
  assert.ok(f.w.document.querySelector('#native-fields').textContent.includes('Padding Scheme'));
  assert.ok([...f.w.document.querySelectorAll('#native-fields textarea')].some(input=>input.value==='stop=8'));
 }finally{f.close()}
});

test('overview keeps CPU model and each address family in its own escaped row',()=>{
 const f=app();try{
  const data={metrics:{hostname:'demo',platform:'Linux',cpu_model:'CPU <model>',ipv4:['203.0.113.10'],ipv6:['2001:db8::10','2001:db8::11'],cpu_count:4,cpu_percent:null,uptime:null,load:[0,0,0],disk_total:100,disk_used:10,samples:[]},core:{running:true,version:'sing-box version 1.14.3',active_revision:0},panel_version:'0.4.1',totals:{},events:[]};
  const root=f.w.document.createElement('div');root.innerHTML=f.w.TestApp.dashboard(data);
  const rows=Object.fromEntries([...root.querySelectorAll('.info-row')].map(row=>[row.querySelector('span').textContent,row.querySelector('b').textContent]));
  assert.equal(rows['CPU model'],'CPU <model>');assert.equal(rows.IPv4,'203.0.113.10');assert.equal(rows.IPv6,'2001:db8::102001:db8::11');assert.equal(root.querySelectorAll('model').length,0);
  data.metrics.ipv6=[];root.innerHTML=f.w.TestApp.dashboard(data);assert.ok(root.textContent.includes('Not assigned'));
  data.metrics.ipv6=null;root.innerHTML=f.w.TestApp.dashboard(data);assert.ok(root.textContent.includes('Unavailable'));
 }finally{f.close()}
});
