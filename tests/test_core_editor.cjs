const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const schema=JSON.parse(fs.readFileSync(path.join(root,'nara/schema/sing-box-1.14.3.schema.json'),'utf8'));
const help=JSON.parse(fs.readFileSync(path.join(root,'nara/schema/field-help.json'),'utf8'));
function fixture(definition,value,settings={}){
 const dom=new JSDOM('<div id="form"></div>',{runScripts:'outside-only'}),w=dom.window;
 w.e=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 w.eval(fs.readFileSync(path.join(root,'web/core-editor.js'),'utf8')+'\nglobalThis.TestCoreSchema=CoreSchema;');
 w.TestCoreSchema.configure({schema,help,labels:{vmess:'VMess',shadowtls:'ShadowTLS',socks:'SOCKS',tun:'TUN'}});
 const host=w.document.querySelector('#form'),form=w.TestCoreSchema.mount(host,w.TestCoreSchema.byName(definition),value,settings);
 return {w,host,form,finish(){w.close()},change(selector,value){const el=host.querySelector(selector);assert.ok(el,selector);el.value=value;el.dispatchEvent(new w.Event('change',{bubbles:true}));},input(label,value){const el=[...host.querySelectorAll('label')].find(l=>l.firstChild?.textContent===label)?.querySelector('textarea,input,select');assert.ok(el,label);el.value=value;el.dispatchEvent(new w.Event('input',{bubbles:true}));},value(){return JSON.parse(JSON.stringify(form.value()))}};
}
for(const [def,value] of [
 ['Inbound',{type:'hysteria2',tag:'h2',listen:'127.0.0.1',listen_port:18444,obfs:{type:'salamander',password:'fixture'},users:[{name:'demo',password:'fixture'}],tls:{enabled:true,server_name:'vpn.example.com'}}],
 ['Inbound',{type:'snell',version:6,tag:'snell',psk:'fixture',mode:'unshaped'}],
 ['Outbound',{type:'vmess',tag:'remote',server:'vpn.example.com',server_port:443,uuid:'00000000-0000-4000-8000-000000000001',authenticated_length:false}],
 ['DNSServer',{type:'hosts',tag:'hosts',predefined:{'example.com':['192.0.2.1','2001:db8::1']}}],
 ['DNSRule',{type:'logical',mode:'or',rules:[{domain_suffix:['example.com']},{query_type:['A','AAAA']}],action:'predefined',rcode:'NOERROR',answer:['example.com. 60 IN A 192.0.2.1']}],
 ['Rule',{type:'logical',mode:'and',rules:[{network:'tcp'},{port:443}],action:'reject',method:'drop',no_drop:false}],
 ['Endpoint',{type:'wireguard',tag:'wg',address:['10.0.0.1/32'],private_key:'fixture',peers:[{address:'192.0.2.1',port:51820,public_key:'fixture',allowed_ips:['0.0.0.0/0']}]}],
 ['Service',{type:'oom-killer',tag:'oom',enabled:true}],
 ['RouteOptions',{auto_detect_interface:false,default_mark:0,final:'direct'}]
]){
 test(`schema form preserves complete ${def} ${value.type||''} data`,()=>{
  const f=fixture(def,value);try{assert.deepEqual(f.value(),value);}finally{f.finish()}
 });
}
test('protocol choices retain official capitalization and Snell versions',()=>{
 const f=fixture('Inbound',{type:'snell',version:6,tag:'demo'});
 try{
  const select=f.host.querySelector('[data-core-variant]');
  assert.equal(select.selectedOptions[0].textContent,'Snell / 6');
  const options=[...select.options].map(o=>o.textContent);
  for(const name of ['VMess','ShadowTLS','SOCKS','TUN'])assert.ok(options.includes(name),name);
 }finally{f.finish()}
});
test('adding, editing and removing nested array items changes actual output',()=>{
 const f=fixture('DNSRule',{action:'route',server:'bootstrap'});
 try{
  f.change('[data-core-add]','domain_suffix');
  f.host.querySelector('[data-core-item-add]').click();
  f.input('Domain Suffix 1','example.com');
  assert.deepEqual(f.value().domain_suffix,['example.com']);
  f.host.querySelector('[data-core-item-remove]').click();
  assert.deepEqual(f.value().domain_suffix,[]);
  [...f.host.querySelectorAll('[data-core-remove]')].find(el=>el.dataset.key==='domain_suffix').click();
  assert.ok(!Object.hasOwn(f.value(),'domain_suffix'));
 }finally{f.finish()}
});
test('changing action drops incompatible options and preserves compatible matches',()=>{
 const f=fixture('Rule',{action:'route',outbound:'direct',domain_suffix:['example.com']});
 try{
  const select=f.host.querySelector('[data-core-variant]');
  const option=[...select.options].find(o=>o.textContent==='Reject');
  f.change('[data-core-variant]',option.value);
  assert.equal(f.value().action,'reject');
  assert.ok(!Object.hasOwn(f.value(),'outbound'));
  assert.deepEqual(f.value().domain_suffix,['example.com']);
 }finally{f.finish()}
});
test('field labels escape injected data and documentation is protocol scoped',()=>{
 const value={type:'http',tag:'<img src=x onerror=alert(1)>',listen:'127.0.0.1',listen_port:8080};
 const f=fixture('Inbound',value,{collection:'inbounds'});
 try{assert.equal(f.host.querySelectorAll('img').length,0);assert.ok(!f.host.textContent.includes('gRPC API listening'));assert.deepEqual(f.value(),value);}finally{f.finish()}
});

test('new Snell forms choose the correct protocol and seed the required version',()=>{
 const f=fixture('Inbound',{type:'snell',tag:'demo',listen:'127.0.0.1',listen_port:18445});
 try{assert.equal(f.host.querySelector('[data-core-variant]').selectedOptions[0].textContent,'Snell / 5');assert.equal(f.value().version,5);assert.equal(f.value().type,'snell');}finally{f.finish()}
});

test('new DNS and rule records start empty so protocol defaults are applied',()=>{
 const f=fixture('Inbound',{type:'vless',tag:'test'});
 try{
  const source=fs.readFileSync(path.join(root,'web/app.js'),'utf8');
  f.w.eval(source.slice(0,source.indexOf("document.addEventListener('click'"))+'\nglobalThis.testLegacyCoreConfig=legacyCoreConfig;');
  for(const collection of ['dns_servers','dns_rules','rule_sets','outbounds'])assert.deepEqual(JSON.parse(JSON.stringify(f.w.testLegacyCoreConfig(collection,{}))),{});
 }finally{f.finish()}
});

test('arbitrary map names remain data without changing object prototypes',()=>{
 const f=fixture('DNSServer',{type:'hosts',tag:'hosts',predefined:{}});
 try{
  const input=f.host.querySelector('[data-core-map-key]');input.value='__proto__';
  f.host.querySelector('[data-core-map-add]').click();
  assert.ok(Object.hasOwn(f.value().predefined,'__proto__'));
  assert.equal({}.polluted,undefined);
 }finally{f.finish()}
});

test('rule-set variants clearly identify inline, local and remote formats',()=>{
 const f=fixture('RuleSet',{type:'inline',tag:'domains',rules:[]});
 try{assert.deepEqual([...f.host.querySelector('[data-core-variant]').options].map(o=>o.textContent),['Inline','Local','Remote']);}finally{f.finish()}
});
