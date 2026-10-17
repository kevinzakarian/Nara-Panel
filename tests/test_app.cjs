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
 w.eval(fs.readFileSync('web/core-editor.js','utf8')+'\n'+fs.readFileSync('web/options.js','utf8')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.TestApp={setup(value){optionSchema=value.options;coreCatalog=value.catalog;state=value.state;CoreSchema.configure(coreCatalog)},dashboard(value){dashboard=value;return renderDashboard()},editInbound,editCoreRecord,saveWith(handler){saveRecord=handler},submit(){return modalSubmit($('#modal-form'))}};`);
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
