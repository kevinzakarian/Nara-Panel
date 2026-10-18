const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const fixture=JSON.parse(execFileSync(process.env.NARA_TEST_PYTHON||'python3',['-c','import json; from nara import options,native; from nara.config import initial_state; print(json.dumps(dict(options=options.schema(),catalog=native.payload(),state=initial_state())))'],{env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
function app(patch={}){
 const dom=new JSDOM('<div id="content"></div><dialog id="modal"><div id="modal-body"></div></dialog><div id="toasts"></div>',{runScripts:'outside-only',url:'http://localhost:10000/Test/#routing'}),w=dom.window;
 w.structuredClone=value=>JSON.parse(JSON.stringify(value));
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const source=fs.readFileSync('web/app.js','utf8');
 w.eval(['web/account.js','web/integrations.js','web/clients.js','web/dns-presets.js','web/core-editor.js','web/options.js','web/routing.js'].map(p=>fs.readFileSync(p,'utf8')).join('\n')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.TestApp={setup(value,patch){optionSchema=value.options;coreCatalog=value.catalog;state={...value.state,...patch};CoreSchema.configure(coreCatalog);load=async()=>{}},editRouteRule,editRouteDestination,editRouteSet,editRouteDefaults,handleRouting,saveWith(handler){saveRecord=handler},apiWith(handler){api=handler},render(tab='route_rules'){routingTab=tab;$('#content').innerHTML=renderRouting()},submit(){return modalSubmit($('#modal-form'))}};`);
 w.TestApp.setup(JSON.parse(JSON.stringify(fixture)),patch);
 let saved;w.TestApp.saveWith(async(collection,record)=>{saved={collection,record:JSON.parse(JSON.stringify(record))}});
 const form=()=>w.document.querySelector('#modal-form'),el=name=>form().elements.namedItem(name);
 const change=(name,value)=>{const input=el(name);if(input instanceof w.RadioNodeList){[...input].find(x=>x.value===value).checked=true;[...input].find(x=>x.value===value).dispatchEvent(new w.Event('change',{bubbles:true}));}else{input.value=value;input.dispatchEvent(new w.Event('change',{bubbles:true}));}};
 const control=(key,section='match')=>w.document.querySelector('#native-rule-'+section+' > .schema-fields > [data-core-field="'+key+'"] [data-core-native-lines],#native-rule-'+section+' > .schema-fields > [data-core-field="'+key+'"] [data-core-input],#native-rule-'+section+' > .schema-fields > [data-core-field="'+key+'"] [data-core-union],#native-rule-'+section+' > .schema-fields > [data-core-field="'+key+'"] [data-core-lines]');
 return {w,el,change,form,control,saved:()=>saved,plain:value=>JSON.parse(JSON.stringify(value)),close:()=>w.close()};
}
test('native rule fields preserve domain lists and native source conditions',async()=>{const f=app({inbounds:[{tag:'vpn'}]});try{f.w.TestApp.editRouteRule();assert.equal(f.el('native_rule_type').value,'default');assert.equal(f.el('match_kind'),null);f.control('domain_suffix').value='example.com\nexample.org';f.control('inbound').value='vpn';f.control('network').value='udp';f.change('native_rule_action','reject');await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,{domain_suffix:['example.com','example.org'],inbound:['vpn'],network:['udp'],action:'reject'});assert.equal(f.saved().record.enabled,true);}finally{f.close()}});

test('native action changes remove obsolete action fields and keep independent matches',async()=>{const f=app();try{f.w.TestApp.editRouteRule({}, {domain_suffix:['old.example'],action:'route',outbound:'direct'});f.control('port').value='53';f.control('port_range').value='8000:9000';f.change('native_rule_action','hijack-dns');await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,{domain_suffix:['old.example'],port:[53],port_range:['8000:9000'],action:'hijack-dns'});}finally{f.close()}});

test('native catch-all is allowed and typed port lists honor schema bounds including zero',async()=>{const f=app();try{f.w.TestApp.editRouteRule();f.change('native_rule_action','reject');await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,{action:'reject'});f.control('port').value='0\n65535';await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config.port,[0,65535]);for(const value of ['65536','abc','-1']){f.control('port').value=value;await assert.rejects(f.w.TestApp.submit(),/Invalid value for port/);}}finally{f.close()}});

test('native source references retain scalar or array form and disabled metadata',async()=>{const item={id:'r',label:'Scope',enabled:false,mode:'native',config:{inbound:'one',action:'sniff'}};const f=app({inbounds:[{tag:'one'}]});try{f.w.TestApp.editRouteRule(item);await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,item.config);assert.equal(f.saved().record.enabled,false);assert.equal(f.saved().record.id,'r');}finally{f.close()}});

test('logical rules round trip nested match fields and all top-level action options in the native form',async()=>{const item={id:'r',enabled:false,label:'Complex',config:{type:'logical',mode:'and',rules:[{domain_suffix:['example.com']},{network:['udp'],invert:true}],action:'route',outbound:'direct',udp_timeout:'2m',tls_fragment:true}};const f=app();try{f.w.TestApp.editRouteRule(item);assert.equal(f.el('native_rule_type').value,'logical');assert.equal(f.el('route_json'),null);f.el('display_name').value='Renamed';await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,item.config);assert.equal(f.saved().record.label,'Renamed');assert.equal(f.saved().record.enabled,false);}finally{f.close()}});

test('native form and JSON preserve current edits and record metadata',async()=>{const f=app();try{f.w.TestApp.editRouteRule();f.el('display_name').value='Work';f.el('native_enabled').checked=false;f.control('domain').value='work.example';f.control('outbound','action').value='direct';f.w.document.querySelector('#native-rule-json').click();assert.deepEqual(JSON.parse(f.el('route_json').value),{domain:['work.example'],outbound:'direct',action:'route'});f.w.document.querySelector('#route-guided').click();await f.w.TestApp.submit();assert.equal(f.saved().record.label,'Work');assert.equal(f.saved().record.enabled,false);assert.deepEqual(f.saved().record.config,{domain:['work.example'],outbound:'direct',action:'route'});}finally{f.close()}});

test('rule list shows actual values, execution order, hidden policy and fallback',()=>{
 const f=app({route_rules:[{id:'1',label:'Stop all',config:{action:'reject'}},{id:'2',label:'Later',config:{domain_suffix:['example.com'],action:'route',outbound:'direct'}},{id:'3',enabled:false,config:{action:'sniff'}}]});try{f.w.TestApp.render();const d=f.w.document;assert.match(d.querySelector('.route-rule-list').textContent,/example.com/);assert.match(d.querySelector('.route-warning').textContent,/earlier rule handles all/);assert.match(d.querySelector('.route-policy').textContent,/blocked before all rules/);assert.match(d.querySelector('.route-fallback').textContent,/Everything else/);assert.ok(d.querySelector('[data-direction=up]').disabled);assert.ok([...d.querySelectorAll('[data-direction=down]')].at(-1).disabled);assert.equal(d.querySelector('[data-id="3"][role=switch]').getAttribute('aria-checked'),'false');}finally{f.close()}
});
test('non-final catch-all detection does not mark later rules unreachable; content is escaped',()=>{
 const f=app({route_rules:[{id:'1',config:{action:'sniff'}},{id:'2',label:'<img src=x onerror=alert(1)>',config:{domain_suffix:['<script>'],action:'reject'}}]});try{f.w.TestApp.render();assert.equal(f.w.document.querySelector('.route-warning'),null);assert.equal(f.w.document.querySelector('.route-rule img'),null);assert.match(f.w.document.querySelector('.route-rule-list').textContent,/<script>/);}finally{f.close()}
});
test('move down and toggle use revision-checked saves, retaining advanced config',async()=>{
 const row={id:'r',label:'A',config:{type:'logical',mode:'or',rules:[{port:[443]}],action:'reject',method:'drop'}};
 const f=app({revision:12,route_rules:[row]});try{let call;f.w.TestApp.apiWith(async(path,body)=>{call={path,body:f.plain(body)}});await f.w.TestApp.handleRouting('route-move',{dataset:{id:'r',direction:'down'}});assert.deepEqual(call,{path:'reorder-rules',body:{revision:12,collection:'route_rules',id:'r',direction:'down'}});await f.w.TestApp.handleRouting('route-toggle',{dataset:{id:'r'}});assert.deepEqual(f.saved().record,{...row,enabled:false});}finally{f.close()}
});
test('default destination save preserves specialized route options and object resolver',async()=>{
 const route={final:'direct',default_domain_resolver:{server:'bootstrap',strategy:'ipv4_only'},default_interface:'eth1',default_mark:12};
 const f=app({core_options:{route},outbounds:[{tag:'upstream',config:{type:'socks',tag:'upstream'}}]});try{let call;f.w.TestApp.apiWith(async(path,body)=>{call={path,body:f.plain(body)}});f.w.TestApp.editRouteDefaults();f.change('final','upstream');await f.w.TestApp.submit();assert.deepEqual(call.body.options,{...route,final:'upstream'});}finally{f.close()}
});
test('destination editor creates a simple authenticated TLS proxy with no nested editor',async()=>{
 const f=app();try{f.w.TestApp.editRouteDestination();assert.equal(f.el('destination_type').value,'');f.el('tag').value='upstream';f.change('destination_type','http');f.el('server').value='proxy.example.com';f.el('server_port').value='8443';f.el('username').value='user';f.el('password').value='  keep spaces  ';f.el('tls_enabled').checked=true;f.el('tls_server_name').value='proxy.example.com';await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,{type:'http',tag:'upstream',server:'proxy.example.com',server_port:8443,username:'user',password:'  keep spaces  ',tls:{enabled:true,server_name:'proxy.example.com'}});assert.equal(f.w.document.querySelector('[data-core-add]'),null);}finally{f.close()}
});
test('destination groups exclude self and reject an unselected default',async()=>{
 const item={id:'g',config:{type:'selector',tag:'group',outbounds:['direct'],default:'direct'}};
 const f=app({outbounds:[item,{tag:'other',config:{type:'direct',tag:'other'}}]});try{f.w.TestApp.editRouteDestination(item);assert.equal([...f.el('group_member')].some(x=>x.value==='group'),false);f.change('group_default','other');await assert.rejects(f.w.TestApp.submit(),/selected group member/);assert.equal(f.saved(),undefined);}finally{f.close()}
});
test('advanced destinations preserve transports, credentials and TLS trust fields',async()=>{
 const item={id:'o',config:{type:'vless',tag:'chain',server:'proxy.example.com',server_port:443,uuid:'example',transport:{type:'ws',path:'/private'},tls:{enabled:true,certificate:['DEMO CERT'],server_name:'proxy.example.com'}}};
 const f=app();try{f.w.TestApp.editRouteDestination(item);assert.ok(f.el('route_json'));await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,item.config);}finally{f.close()}
});
test('rule set form swaps source type without stale URL or path fields',async()=>{
 const f=app();try{f.w.TestApp.editRouteSet({id:'s',config:{type:'remote',tag:'shared',url:'https://example.com/list.srs',format:'binary',update_interval:'1d'}});f.change('set_type','inline');f.el('rules').value='[{"domain_suffix":["example.org"]}]';await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,{type:'inline',tag:'shared',rules:[{domain_suffix:['example.org']}]});}finally{f.close()}
});
test('rule set shortcut retains its native rule_set reference',async()=>{const f=app({rule_sets:[{config:{type:'inline',tag:'shared',rules:[]}}]});try{await f.w.TestApp.handleRouting('route-use-set',{dataset:{id:'shared'}});await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,{rule_set:['shared'],action:'route',outbound:'direct'});}finally{f.close()}});

test('specialized process and logical conditions show their actual matches rather than all traffic',()=>{
 const f=app({route_rules:[{id:'1',config:{process_name:['curl'],action:'reject'}},{id:'2',config:{type:'logical',mode:'or',rules:[{domain_suffix:['example.org']},{port:[443]}],action:'route',outbound:'direct'}}]});try{f.w.TestApp.render();const text=f.w.document.querySelector('.route-rule-list').textContent;assert.match(text,/Process Name: curl/);assert.match(text,/Domain suffix: example.org OR Destination port: 443/);assert.doesNotMatch(text,/All traffic/);}finally{f.close()}
});

test('native domain_regex keeps commas inside quantifiers',async()=>{const f=app();try{f.w.TestApp.editRouteRule();f.change('native_rule_action','reject');f.control('domain_regex').value='^cdn[0-9]{1,3}\\.example$\n^other\\.example$';await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config.domain_regex,['^cdn[0-9]{1,3}\\.example$','^other\\.example$']);}finally{f.close()}});

test('anonymous SOCKS has no unsupported TLS option or mandatory password',async()=>{
 const f=app();try{f.w.TestApp.editRouteDestination();f.el('tag').value='anonymous';f.change('destination_type','socks');f.el('server').value='127.0.0.1';assert.equal(f.el('server_port').value,'1080');assert.equal(f.el('tls_enabled'),null);assert.equal(f.el('password').required,false);assert.equal(f.form().checkValidity(),true);await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,{type:'socks',tag:'anonymous',server:'127.0.0.1',server_port:1080});}finally{f.close()}
});
test('shared list advanced options survive JSON edits and guided return',async()=>{
 const item={id:'s',config:{type:'remote',tag:'shared',url:'https://example.com/list.srs',format:'binary',http_client:'fetcher'}};
 const f=app();try{f.w.TestApp.editRouteSet(item);assert.ok(f.el('route_json'));f.w.document.querySelector('#route-guided').click();assert.ok(f.el('route_json'));await f.w.TestApp.submit();assert.deepEqual(f.saved().record.config,item.config);}finally{f.close()}
});

test('managed DNS forwarding is visible ahead of private-network protection',()=>{
 const f=app({inbounds:[{tag:'managed',type:'hysteria2'}],settings:{...fixture.state.settings,dns_final:'dns-google'}});try{f.w.TestApp.render();const policies=f.w.document.querySelectorAll('.route-policy');assert.match(policies[0].textContent,/Managed client DNS/);assert.match(policies[0].textContent,/dns-google/);assert.match(policies[1].textContent,/Private network protection/);}finally{f.close()}
});
