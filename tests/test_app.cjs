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
 w.eval(fs.readFileSync('web/core-editor.js','utf8')+'\n'+fs.readFileSync('web/options.js','utf8')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.TestApp={setup(value){optionSchema=value.options;coreCatalog=value.catalog;state=value.state;CoreSchema.configure(coreCatalog)},editInbound};`);
 w.TestApp.setup(fixture);
 return {w,dom,close(){w.close()}};
}
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
