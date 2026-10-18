const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const fixture=JSON.parse(execFileSync(process.env.NARA_TEST_PYTHON||'python3',['-c','import json;from nara import native,options;from nara.config import initial_state;print(json.dumps(dict(catalog=native.payload(),options=options.schema(),state=initial_state())))']));
function app(){
 const dom=new JSDOM('<dialog id="modal"><div id="modal-body"></div></dialog><div id="toasts"></div>',{runScripts:'outside-only',url:'http://localhost/Test/'}),w=dom.window;
 w.structuredClone=value=>JSON.parse(JSON.stringify(value));w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const source=fs.readFileSync('web/app.js','utf8');w.eval(['core-editor.js','routing.js','dns-rules.js'].map(name=>fs.readFileSync('web/'+name,'utf8')).join('\n')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.testRule={init(f){coreCatalog=f.catalog;optionSchema=f.options;state=f.state;CoreSchema.configure(coreCatalog)},editRouteRule,editDNSRule,nativeRuleSchemas,read(){return document.querySelector('#modal-form').nativeRuleValue()},edit(dns,config){(dns?editDNSRule:editRouteRule)({id:'existing',config})}};`);w.testRule.init(JSON.parse(JSON.stringify(fixture)));
 const section=(kind='match')=>w.document.querySelector('#native-rule-'+kind);
 const row=(key,kind='match')=>section(kind).querySelector(':scope > .schema-fields > [data-core-field="'+key+'"]');
 const field=(key,kind='match',selector='[data-core-native-lines],[data-core-input],[data-core-union]')=>row(key,kind).querySelector(selector);
 const change=(input,value)=>{input.value=value;input.dispatchEvent(new w.Event('change',{bubbles:true}));};
 return {w,section,row,field,change,close:()=>w.close()};
}
test('every supported native default field and action is rendered from the pinned schema',()=>{
 const f=app();try{for(const dns of [false,true]){
  f.w.testRule.edit(dns,{action:'reject'});const definition=fixture.catalog.schema.$defs[dns?'DNSRule':'Rule'];
  assert.deepEqual([...f.section().querySelectorAll(':scope > .schema-fields > [data-core-field]')].map(el=>el.dataset.coreField),Object.keys(definition.oneOf[0].allOf[0].properties).filter(key=>key!=='type'));
  const select=f.w.document.querySelector('[name=native_rule_action]'),actions=fixture.catalog.schema.$defs[dns?'DNSRuleAction':'RuleAction'].oneOf.map(branch=>branch.properties.action.const);
  assert.deepEqual([...select.options].map(option=>option.value),actions);
  for(const action of actions){f.change(select,action);const schemas=f.w.testRule.nativeRuleSchemas(dns,'default',action);assert.deepEqual([...f.section('action').querySelectorAll(':scope > .schema-fields > [data-core-field]')].map(el=>el.dataset.coreField),Object.keys(schemas.options.properties));}
  assert.equal(f.w.document.querySelector('[name=scope_client]'),null);assert.equal(f.w.document.querySelector('[name=match_kind]'),null);assert.equal(f.w.document.querySelector('[name=dns_match]'),null);
 }}finally{f.close();}
});
test('native mixed DNS query types and scalar/array round trips retain JSON types',()=>{
 const f=app();try{const config={query_type:['A',28,'HTTPS'],domain_suffix:'example.com',match_response:false,action:'route',server:'bootstrap',rewrite_ttl:0,disable_cache:false};f.w.testRule.edit(true,config);assert.deepEqual(JSON.parse(JSON.stringify(f.w.testRule.read())),config);f.field('query_type').value='AAAA\n1\nHTTPS';assert.deepEqual(JSON.parse(JSON.stringify(f.w.testRule.read().query_type)),['AAAA',1,'HTTPS']);f.field('query_type').value='not-a-query-type';assert.throws(()=>f.w.testRule.read(),/Invalid value for query_type/);}finally{f.close();}
});
test('match_response can be created as a tag, switched to boolean, and removed',()=>{
 const f=app();try{f.w.testRule.edit(true,{action:'respond'});f.change(f.field('match_response'),'1');let value=f.field('match_response','match','[data-core-input]');assert.ok(value);value.value='evaluated-response';assert.equal(f.w.testRule.read().match_response,'evaluated-response');f.change(f.field('match_response','match','[data-core-union]'),'0');value=f.field('match_response','match','[data-core-input]');f.change(value,'true');assert.equal(f.w.testRule.read().match_response,true);f.change(f.field('match_response','match','[data-core-union]'),'-1');assert.equal(f.w.testRule.read().match_response,undefined);}finally{f.close();}
});
test('logical nesting creates native match-only subrules and survives edits',()=>{
 const f=app();try{f.w.testRule.edit(false,{type:'logical',mode:'or',rules:[{type:'logical',mode:'and',rules:[{port:443},{domain_suffix:['example.com']}],invert:false},{auth_user:['usera']}],action:'reject',no_drop:false});const before=JSON.parse(JSON.stringify(f.w.testRule.read()));assert.equal(before.rules[0].rules[0].port,443);const nested=f.row('rules').querySelectorAll('[data-core-field=action]');assert.equal(nested.length,0);const ports=[...f.row('rules').querySelectorAll('[data-core-field=port] [data-core-native-lines]')];ports[0].value='80\n443';assert.deepEqual(JSON.parse(JSON.stringify(f.w.testRule.read().rules[0].rules[0].port)),[80,443]);}finally{f.close();}
});
test('action and type changes preserve separate drafts and avoid duplicate shared fields',()=>{
 const f=app();try{f.w.testRule.edit(false,{domain:['example.com'],network_type:['wifi'],action:'direct',bind_interface:'eth0'});assert.equal(f.w.document.querySelectorAll('#native-rule-match [data-core-field=network_type],#native-rule-action [data-core-field=network_type]').length,1);const action=f.w.document.querySelector('[name=native_rule_action]');f.change(action,'reject');assert.equal(f.w.testRule.read().bind_interface,undefined);f.change(action,'direct');assert.equal(f.w.testRule.read().bind_interface,'eth0');const type=f.w.document.querySelector('[name=native_rule_type]');f.change(type,'logical');assert.equal(f.w.testRule.read().type,'logical');f.change(type,'default');assert.deepEqual(JSON.parse(JSON.stringify(f.w.testRule.read().domain)),['example.com']);}finally{f.close();}
});
test('required targets follow the official actions and JSON can inspect an incomplete draft',()=>{
 const f=app();try{f.w.testRule.edit(false,{action:'route'});assert.throws(()=>f.w.testRule.read(),/Set outbound/);f.w.document.querySelector('#native-rule-json').click();assert.ok(f.w.document.querySelector('[name=route_json]'));f.w.testRule.edit(true,{action:'evaluate'});assert.throws(()=>f.w.testRule.read(),/Set server/);f.w.testRule.edit(false,{action:'bypass'});assert.deepEqual(JSON.parse(JSON.stringify(f.w.testRule.read())),{action:'bypass'});}finally{f.close();}
});

test('native editor output for every action passes the real pinned core check',{skip:!process.env.SING_BOX_TEST_BINARY},()=>{
 const os=require('node:os'),path=require('node:path'),folder=fs.mkdtempSync(path.join(os.tmpdir(),'nara-native-rules-')),f=app();
 try{
  const traffic=[{action:'route',outbound:'direct',fallback_delay:300},{action:'route-options',override_port:443,tls_fragment:false},{action:'direct',connect_timeout:'1s'},{action:'bypass',outbound:'direct'},{action:'reject',method:'drop'},{action:'hijack-dns',port:53},{action:'sniff',sniffer:['tls','http']},{action:'resolve',server:'bootstrap',strategy:'prefer_ipv4'},{type:'logical',mode:'or',rules:[{domain_suffix:'example.com'},{port:[443]}],action:'route',outbound:'direct'}];
  const dns=[{action:'route',server:'bootstrap',query_type:['A',28]},{action:'evaluate',server:'bootstrap',tag:'next'},{action:'respond',match_response:'checked'},{action:'route-options',rewrite_ttl:0},{action:'reject',method:'drop'},{action:'predefined',rcode:'NOERROR',answer:['example.com. 60 IN A 192.0.2.1']},{type:'logical',mode:'and',rules:[{match_response:true,response_rcode:'NOERROR'},{query_type:'A'}],action:'respond'}];
  for(const [isDNS,cases] of [[false,traffic],[true,dns]])for(const rule of cases){
   f.w.testRule.edit(isDNS,rule);const value=JSON.parse(JSON.stringify(f.w.testRule.read()));assert.deepEqual(value,rule);
   const config={log:{level:'warn'},dns:{servers:[{type:'hosts',tag:'bootstrap',predefined:{'example.com':['192.0.2.1']}}],rules:isDNS?[{action:'evaluate',server:'bootstrap',tag:'checked'},{action:'evaluate',server:'bootstrap'},value]:[]},outbounds:[{type:'direct',tag:'direct'}],route:{rules:isDNS?[]:[value],final:'direct'}};
   const file=path.join(folder,'rule.json');fs.writeFileSync(file,JSON.stringify(config));execFileSync(process.env.SING_BOX_TEST_BINARY,['check','-c',file],{stdio:'pipe'});
  }
 }finally{f.close();fs.rmSync(folder,{recursive:true,force:true});}
});

test('unchanged omitted or empty default type and action fields are preserved',()=>{const f=app();try{for(const config of [{domain:'example.com',outbound:'direct'},{type:'',action:'route',domain_suffix:[],outbound:'direct'}]){f.w.testRule.edit(false,config);assert.deepEqual(JSON.parse(JSON.stringify(f.w.testRule.read())),config);}}finally{f.close();}});
