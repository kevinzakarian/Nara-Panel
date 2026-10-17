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
 w.eval(fs.readFileSync('web/core-editor.js','utf8')+'\n'+fs.readFileSync('web/options.js','utf8')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.TestApp={setup(value){optionSchema=value.options;coreCatalog=value.catalog;state=value.state;CoreSchema.configure(coreCatalog)},dashboard(value){dashboard=value;return renderDashboard()},editInbound,editCoreRecord};`);
 w.TestApp.setup(fixture);
 return {w,dom,close(){w.close()}};
}
test('new resolver visibly selects an existing bootstrap and retains it for hostname input',()=>{
 const f=app();try{
  f.w.TestApp.editCoreRecord('dns_servers');
  const document=f.w.document;
  assert.ok(document.querySelector('#native-fields').textContent.includes('Domain Resolver'));
  assert.ok([...document.querySelectorAll('#native-fields select')].some(select=>select.value==='bootstrap'));
  const server=[...document.querySelectorAll('#native-fields label')].find(label=>label.firstChild?.textContent==='Server').querySelector('textarea');
  server.value='dns.google';server.dispatchEvent(new f.w.Event('input',{bubbles:true}));
  document.querySelector('#core-to-json').click();
  const config=JSON.parse(document.querySelector('#native-json').value);
  assert.equal(config.server,'dns.google');assert.equal(config.domain_resolver,'bootstrap');
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
