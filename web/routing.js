'use strict';
// Task-oriented routing UI. Native records remain the source of truth.
const routeList=value=>value===undefined?[]:Array.isArray(value)?value:[value];
const routeLines=value=>[...new Set(String(value||'').split(/[\n,]+/).map(x=>x.trim()).filter(Boolean))];
const routeNames={domain:'Exact domain',domain_suffix:'Domain suffix',domain_keyword:'Domain keyword',domain_regex:'Domain pattern',ip_cidr:'Destination IP',source_ip_cidr:'Source IP',port:'Destination port',port_range:'Port range',inbound:'Inbound',network:'Network',rule_set:'Rule set',protocol:'Detected protocol',auth_user:'Authenticated account',ip_is_private:'Private destination',source_ip_is_private:'Private source'};
const routeActions={route:['Route traffic','Send through a destination'],reject:['Block traffic','Reject matching connections'],'hijack-dns':['Handle DNS','Use this server’s DNS rules'],sniff:['Detect protocol','Inspect, then continue to the next rule'],resolve:['Resolve domain','Look up the IP, then continue to the next rule']};
function routeTag(row){return row.config?.tag||row.tag||'';}
function routeDestinations(){return [...new Set(['direct',...[...(state.outbounds||[]),...(state.endpoints||[])].filter(x=>x.enabled!==false).map(routeTag).filter(Boolean)])];}
function routeDestinationName(tag){const row=[...(state.outbounds||[]),...(state.endpoints||[])].find(x=>routeTag(x)===tag);return row?.label?row.label+' · '+tag:tag==='direct'?'Direct · '+(row?'custom outbound':'server connection'):tag;}
function routeChoices(name,choices,value,cls=''){return `<div class="route-choices ${cls}">${choices.map(([key,label,help])=>`<label class="route-choice"><input type="radio" name="${name}" value="${e(key)}" ${checked(key===value)}><span><b>${e(label)}</b>${help?`<small>${e(help)}</small>`:''}</span></label>`).join('')}</div>`;}
function routeChecks(name,values,selected){return `<div class="route-checks">${values.map(([value,label])=>`<label><input type="checkbox" name="${name}" value="${e(value)}" ${checked(routeList(selected).includes(value))}>${e(label)}</label>`).join('')}</div>`;}
function routeSection(number,title,help,body){return `<section class="route-form-section"><div class="route-section-title"><span>${number}</span><div><h3>${title}</h3>${help?`<p>${help}</p>`:''}</div></div>${body}</section>`;}
function routeBrief(value){const text=value&&typeof value==='object'&&!Array.isArray(value)?JSON.stringify(value):routeList(value).slice(0,3).join(', ')+(routeList(value).length>3?' +'+(routeList(value).length-3):'');return text.length>220?text.slice(0,220)+'…':text;}
function ruleMatchBrief(key,value){return routeBrief(key==='auth_user'?routeList(value).map(identity=>(state.clients||[]).find(client=>'client-'+client.id===identity)?.name||identity):value);}
function routeMatchEntries(c){
 const actionFields=CoreSchema.choose(CoreSchema.byName('RuleAction'),{...c,action:c.action||'route'}).properties||{};
 return Object.entries(c).filter(([key])=>!['type','invert'].includes(key)&&!Object.hasOwn(actionFields,key));
}
function routeMatchSummary(c,depth=0){
 if(c.type==='logical'){const rules=routeList(c.rules);return `${c.invert?'NOT ':''}${depth>2?(c.mode||'and').toUpperCase()+' group · '+rules.length+' conditions':'('+rules.map(rule=>routeMatchSummary(rule,depth+1)).join(' '+(c.mode||'and').toUpperCase()+' ')+')'}`;}
 const parts=routeMatchEntries(c).map(([k,v])=>`${routeNames[k]||CoreSchema.title(k)}: ${ruleMatchBrief(k,v)}`);
 return (c.invert?'Except · ':'')+(parts.join(' · ')||'All traffic');
}
function routeActionSummary(c){return c.action==='route'||!c.action?'Route → '+routeDestinationName(c.outbound||'(selected by core)'):routeActions[c.action]?.[0]||CoreSchema.title(c.action);}
function routeIsCatchAll(c){return c.type!=='logical'&&!c.invert&&!routeMatchEntries(c).length;}
function routeIsFinal(c){return ['route','reject','hijack-dns','direct','bypass'].includes(c.action||'route');}
function renderRouting(){
 const options=state.core_options.route||{},final=options.final||'direct',resolver=options.default_domain_resolver||state.settings.dns_final;
 const tabs=[['route_rules','Traffic rules'],['outbounds','Destinations'],['rule_sets','Shared rule sets']];
 return heading(btn('Add rule','route-new','plus','primary'))+pendingBanner()+
 `<div class="route-overview"><div><span class="route-eyebrow">DEFAULT DESTINATION</span><b>${e(routeDestinationName(final))}</b><small>Used when no rule chooses a destination.</small></div><div><span class="route-eyebrow">DOMAIN RESOLVER</span><b>${e(typeof resolver==='object'?resolver.server||'Custom resolver':resolver||'DNS default')}</b><small>Resolves destination hostnames on this server.</small></div><div class="route-overview-actions">${btn('Edit defaults','route-defaults','edit','sm')}<button class="text-link" data-action="route-advanced-options">Advanced settings</button></div></div>`+
 `<nav class="tabs route-tabs" aria-label="Routing sections">${tabs.map(([key,label])=>`<button class="tab ${routingTab===key?'active':''}" data-action="core-tab" data-collection="routing" data-id="${key}" ${routingTab===key?'aria-current="page"':''}>${label} ${badge((state[key]||[]).length+(key==='outbounds'?(state.endpoints||[]).filter(x=>x.enabled!==false).length:0))}</button>`).join('')}</nav>`+
 (routingTab==='outbounds'?renderRouteDestinations():routingTab==='rule_sets'?renderRouteSets():renderRouteRules())+
 `<p class="route-footnote">These rules control server traffic. Client DNS uses this server’s DNS settings; Rule / Global / Direct in the app control client routing.</p>`;
}
function renderRouteRules(){
 const rows=state.route_rules||[];
 let shadow=false;
 return `<section class="card route-rules"><div class="card-header"><div><h2>Traffic rules</h2><p>Run from top to bottom. Routing or blocking ends the search; detection and resolution continue.</p></div>${btn('Advanced rule','route-json-new','code','sm')}</div>
 ${state.inbounds.some(row=>row.mode!=='native')?`<div class="route-policy route-dns-policy"><span class="route-order">${icon('dns')}</span><div><b>Managed client DNS</b><p>Default DNS: ${e(state.settings.dns_final)} · Handled before traffic rules.</p></div><a class="text-link" href="#dns">DNS settings</a></div>`:''}
 <div class="route-policy"><span class="route-order">${icon('lock')}</span><div><b>Private network protection</b><p>${state.settings.block_private?'Private destinations are blocked before all rules below.':'Private destinations are allowed unless a rule below blocks them.'}</p></div>${badge(state.settings.block_private?'Block first':'Off',state.settings.block_private?'orange':'')}<a class="text-link" href="#settings">Change</a></div>
 ${rows.length?`<ol class="route-rule-list">${rows.map((row,index)=>{
 const c=legacyCoreConfig('route_rules',row),hidden=shadow&&row.enabled!==false;
 if(row.enabled!==false&&routeIsCatchAll(c)&&routeIsFinal(c))shadow=true;
 return `<li class="route-rule ${row.enabled===false?'is-disabled':''}"><span class="route-order">${index+1}</span><div class="route-rule-content"><div class="route-rule-title"><b>${e(row.label||'Rule '+(index+1))}</b>${badge(routeActionSummary(c),c.action==='reject'?'red':'blue')}</div><p>${e(routeMatchSummary(c))}</p>${hidden?'<small class="route-warning">An earlier rule handles all traffic. Move this rule above it to take effect.</small>':''}</div><div class="route-rule-controls"><button class="route-switch" role="switch" aria-checked="${row.enabled!==false}" aria-label="${row.enabled===false?'Enable':'Disable'} ${e(row.label||'rule '+(index+1))}" data-action="route-toggle" data-id="${e(row.id)}">${row.enabled===false?'Off':'On'}</button><div class="row-actions"><button title="Move up" aria-label="Move rule ${index+1} up" data-action="route-move" data-id="${e(row.id)}" data-direction="up" ${index?'':'disabled'}>↑</button><button title="Move down" aria-label="Move rule ${index+1} down" data-action="route-move" data-id="${e(row.id)}" data-direction="down" ${index<rows.length-1?'':'disabled'}>↓</button>${rowBtn('Edit rule','route-edit','edit',row.id)}${rowBtn('Delete rule','delete','trash',row.id,'route_rules')}</div></div></li>`;
 }).join('')}</ol>`:`<div class="route-empty"><span class="route-empty-icon">${icon('routing')}</span><h3>Give traffic a clear path</h3><p>Block a domain, send selected traffic through another server, or use a shared rule set. Everything else uses your default destination.</p><div class="inline-buttons">${btn('Create your first rule','route-new','plus','primary')}</div></div>`}
 <div class="route-fallback"><span class="route-order">↳</span><div><b>Everything else</b><p>Route → ${e(routeDestinationName(state.core_options.route?.final||'direct'))}</p></div>${btn('Change','route-defaults','edit','sm')}</div></section>`;
}
function routeConfigSummary(c){return c.server?`${c.server}${c.server_port?':'+c.server_port:''}`:c.outbounds?routeList(c.outbounds).join(' → '):c.type==='direct'?'Connect from this server':c.type==='remote'?c.url:c.type==='local'?c.path:c.type==='inline'?routeList(c.rules).length+' inline rules':'Custom configuration';}
function renderRouteDestinations(){
 const rows=state.outbounds||[],customDirect=rows.some(x=>x.enabled!==false&&routeTag(x)==='direct');
 return `<section class="card"><div class="card-header"><div><h2>Destinations</h2><p>Where routed traffic leaves this server. Inbound listeners are entry points, not destinations.</p></div><div class="inline-buttons">${btn('Create WARP','route-warp-new','plus')}${btn('Add destination','route-destination-new','plus','primary')}</div></div><div class="route-destinations">${customDirect?'':'<article class="route-destination"><span class="route-empty-icon">'+icon('traffic')+'</span><div><h3>Direct</h3><p>Connect from this server</p></div>'+badge('Built in','green')+'</article>'}${rows.map(row=>{const c=legacyCoreConfig('outbounds',row);return `<article class="route-destination"><span class="route-empty-icon">${icon('routing')}</span><div><h3>${e(row.label||c.tag)}</h3><p>${e(protocolLabel(c.type))} · ${e(routeConfigSummary(c))}</p><small>${e(c.tag)}${row.enabled===false?' · Disabled':''}</small></div><div class="row-actions">${rowBtn('Edit destination','route-destination-edit','edit',row.id)}${rowBtn('Delete destination','delete','trash',row.id,'outbounds')}</div></article>`}).join('')}${(state.endpoints||[]).filter(x=>x.enabled!==false).map(row=>`<article class="route-destination"><span class="route-empty-icon">${icon('core')}</span><div><h3>${e(row.label||routeTag(row))}</h3><p>${e(protocolLabel(row.config?.type||row.type))} endpoint · ${e(routeTag(row))}</p></div><div class="row-actions">${rowBtn('Use in a traffic rule','route-use-destination','plus',routeTag(row))}${rowBtn('Edit endpoint','core-edit','edit',row.id,'endpoints')}${rowBtn('Delete endpoint','delete','trash',row.id,'endpoints')}</div></article>`).join('')}</div></section>`;
}
function renderRouteSets(){return `<section class="card"><div class="card-header"><div><h2>Shared rule sets</h2><p>Reusable domain and IP lists. Also used by DNS rules; creating a list does not route traffic until a rule uses it.</p></div>${btn('Add rule set','route-set-new','plus','primary')}</div><div class="route-destinations">${(state.rule_sets||[]).map(row=>{const c=legacyCoreConfig('rule_sets',row);return `<article class="route-destination"><span class="route-empty-icon">${icon('code')}</span><div><h3>${e(row.label||c.tag)}</h3><p>${e(CoreSchema.title(c.type))} · ${e(routeConfigSummary(c))}</p><small>${e(c.tag)}${row.enabled===false?' · Disabled':''}</small></div><div class="row-actions">${rowBtn('Use in a rule','route-use-set','plus',c.tag)}${rowBtn('Edit rule set','route-set-edit','edit',row.id)}${rowBtn('Delete rule set','delete','trash',row.id,'rule_sets')}</div></article>`}).join('')||'<div class="route-empty"><h3>Keep reusable lists in one place</h3><p>Add a remote list, a file on this server, or inline rules. Then select it in a traffic rule.</p></div>'}</div></section>`;}
function routeRecord(item,config,form){return {...item,mode:'native',label:form.elements.display_name.value.trim(),enabled:form.elements.native_enabled.checked,config,tag:config.tag||'',type:config.type||''};}
function routeMeta(item){return `<div class="form-grid">${field('Name (optional)','display_name',item.label||'')}<label class="check-field"><input type="checkbox" name="native_enabled" ${checked(item.enabled!==false)}>Enabled</label></div>`;}
function routeJSONEditor(collection,item={},preset,back){
 const config=preset||legacyCoreConfig(collection,item);
 openModal(item.id?'Edit '+(collection==='route_rules'?'advanced rule':collection==='dns_rules'?'advanced DNS rule':coreLabels[collection].toLowerCase()):'New '+(collection==='route_rules'?'advanced rule':collection==='dns_rules'?'advanced DNS rule':coreLabels[collection].toLowerCase()),'Full Sing-box 1.14.3 options. Save validates and applies automatically.',`${routeMeta(item)}<p class="note">${collection==='route_rules'?'Configure logical groups, additional match conditions and specialized actions.':collection==='outbounds'?'Configure transport, TLS, dial options and every field for this outbound type.':collection==='dns_rules'?'Configure logical groups, response evaluation, query options and specialized DNS conditions.':'Configure HTTP clients, initial files and every supported rule set option.'} Existing fields are preserved. Stored private keys are retained when omitted.</p>${textField('Sing-box configuration (JSON object)','route_json',JSON.stringify(config,null,2),'','class="route-json-label"')}${back?'<button type="button" class="text-link" id="route-guided">Return to native form</button>':''}`,async form=>{
  const c=routeParseJSON(form.elements.route_json.value);await saveRecord(collection,routeRecord(item,c,form));
 });
 if(back)$('#route-guided').onclick=()=>{try{const f=$('#modal-form'),c=routeParseJSON(f.elements.route_json.value);back(routeRecord(item,c,f));}catch(err){$('#form-error').textContent=err.message;}};
}
function routeParseJSON(value){let c;try{c=JSON.parse(value);}catch{throw Error('Enter valid JSON.');}if(!c||Array.isArray(c)||typeof c!=='object')throw Error('Configuration must be a JSON object.');return c;}
// Rule vocabulary comes directly from the pinned upstream schema.
function ruleMatchProperties(dns=false){return CoreSchema.byName(dns?'DNSRule':'Rule').oneOf[0].allOf[0].properties;}
function nativeRuleSchemas(dns,type,action){
 const definition=CoreSchema.byName(dns?'DNSRule':'Rule'),branch=definition.oneOf[type==='logical'?1:0].allOf[0];
 const match={...branch,properties:Object.fromEntries(Object.entries(branch.properties).filter(([key])=>key!=='type')),required:(branch.required||[]).filter(key=>key!=='type')};
 const selected=CoreSchema.choose(CoreSchema.byName(dns?'DNSRuleAction':'RuleAction'),{action});
 const options={...selected,properties:Object.fromEntries(Object.entries(selected.properties).filter(([key])=>key!=='action'&&!Object.hasOwn(match.properties,key))),required:[...(selected.required||[]).filter(key=>key!=='action'),...(dns&&['route','evaluate'].includes(action)?['server']:!dns&&action==='route'?['outbound']:[])]};
 return {match,options};
}
function editNativeRule(collection,item={},preset){
 const dns=collection==='dns_rules',original=structuredClone(preset||legacyCoreConfig(collection,item)),initialType=original.type==='logical'?'logical':'default',initialAction=original.action||'route';
 const actions=CoreSchema.branches(CoreSchema.byName(dns?'DNSRuleAction':'RuleAction')).map(schema=>schema.properties.action.const),base=dns?'dns':'route';
 let matchEditor,actionEditor,currentType=initialType,currentAction=initialAction,schemas,unrecognized={};
 const matchDrafts=new Map(),actionDrafts=new Map();let activeTab='match';
 const pick=(config,properties)=>Object.fromEntries(Object.entries(config).filter(([key])=>Object.hasOwn(properties,key)));
 openModal(item.id?(dns?'Edit DNS rule':'Edit traffic rule'):(dns?'New DNS rule':'New traffic rule'),'Native sing-box '+coreCatalog.version+' rule fields. Saving validates and applies automatically.',
 `<div class="native-rule-editor"><p class="note">Fields and values use sing-box names. Leave optional fields unset to use core behavior.</p><div class="form-grid native-rule-selectors">${selectField('type','native_rule_type',[['default','default'],['logical','logical']],initialType)}${selectField('action','native_rule_action',actions.map(action=>[action,action]),initialAction)}</div><nav class="native-rule-tabs" role="tablist" aria-label="Rule fields"><button type="button" role="tab" id="native-match-tab" aria-controls="native-match-panel" data-native-tab="match">Default fields</button><button type="button" role="tab" id="native-action-tab" aria-controls="native-action-panel" data-native-tab="action">Action fields</button></nav><section id="native-match-panel" role="tabpanel" aria-labelledby="native-match-tab" class="native-rule-fields"><h3 id="native-match-title">Default fields</h3><details class="native-rule-help"><summary>Evaluation and matching</summary><p class="note" id="native-rule-behavior"></p><p class="note" id="native-match-help"></p></details><div id="native-rule-match" class="schema-editor"></div></section><section id="native-action-panel" role="tabpanel" aria-labelledby="native-action-tab" class="native-rule-fields" hidden><h3>Action fields</h3><p class="note" id="native-action-help"></p><div id="native-rule-action" class="schema-editor"></div></section><p id="native-rule-unknown" class="note" hidden></p><div class="native-rule-docs"><a class="text-link" href="https://sing-box.sagernet.org/configuration/${base}/rule/" target="_blank" rel="noopener noreferrer">Rule documentation ↗</a><a class="text-link" href="https://sing-box.sagernet.org/configuration/${base}/rule_action/" target="_blank" rel="noopener noreferrer">Action documentation ↗</a><button type="button" class="text-link" id="native-rule-json">Edit JSON</button></div><details class="option-section"><summary>NARA record metadata</summary><p class="note">These labels and the enabled switch belong to the panel; they are not sing-box rule fields.</p>${routeMeta(item)}</details></div>`,async form=>{await saveRecord(collection,routeRecord(item,form.nativeRuleValue(),form));});
 const form=$('#modal-form');
 function showTab(name){activeTab=name;for(const panel of form.querySelectorAll('[role=tabpanel]'))panel.hidden=panel.id!=='native-'+name+'-panel';for(const tab of form.querySelectorAll('[data-native-tab]')){const selected=tab.dataset.nativeTab===name;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;}}
 for(const tab of form.querySelectorAll('[data-native-tab]')){tab.onclick=()=>showTab(tab.dataset.nativeTab);tab.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?'match':event.key==='End'?'action':activeTab==='match'?'action':'match';showTab(next);$('#native-'+next+'-tab',form).focus();}};}
 function mount(config){
  schemas=nativeRuleSchemas(dns,currentType,currentAction);
  const settings={fixed:true,nativeNames:true,nativeUnions:true,references:coreReferences()};
  matchEditor=CoreSchema.mount($('#native-rule-match',form),schemas.match,pick(config,schemas.match.properties),{...settings,scope:base+'/rule'});
  actionEditor=CoreSchema.mount($('#native-rule-action',form),schemas.options,pick(config,schemas.options.properties),{...settings,scope:base+'/rule_action'});
  $('#native-match-title',form).textContent=$('#native-match-tab',form).textContent=currentType==='logical'?'Logical fields':'Default fields';showTab(activeTab);
  $('#native-match-help',form).textContent=currentType==='logical'?'mode combines nested rules using and / or; invert negates the combined result. Nested rules contain match fields, not actions.':'Values in one list match any member. Domain/address predicates share an OR group; destination ports, source addresses and source ports form separate groups. The groups and other fields are combined with AND. An empty default rule matches all requests.';
  if(dns)$('#native-match-help',form).textContent+=' Each nested rule that uses response fields needs its own match_response; a sibling condition does not supply it.';
  $('#native-rule-behavior',form).textContent=dns?'DNS rules are evaluated in order. route, reject, predefined and respond finish evaluation unless race behavior applies. route-options and evaluate continue.':'Traffic rules are evaluated in order. route, direct, bypass, reject and hijack-dns are final actions. route-options, sniff and resolve continue.';
  $('#native-action-help',form).textContent=({route:dns?'server is the required tag of the target DNS resolver.':'outbound is the required tag of the target outbound.',direct:'Use a direct connection with the selected dial fields.',bypass:'Bypass the sing-box routing path where supported by the platform and inbound.','route-options':'Set options and continue to later rules.',reject:'Use the native method and no_drop behavior. no_drop is unavailable with method: drop.','hijack-dns':'Send matching DNS traffic to the core DNS module.',sniff:'Detect a protocol or client type, then continue matching.',resolve:'Resolve the destination domain, then continue matching.',evaluate:'Query a resolver and retain its response for later rules. Only top-level DNS rules may evaluate. Tagged responses use match_response with that tag.',respond:'Return an evaluated response. A preceding top-level evaluate is required; reaching respond without a response fails the request.',predefined:'Return the configured DNS response code and records.'})[currentAction]||'';
  if(dns&&currentType==='logical'&&currentAction==='respond')$('#native-action-help',form).textContent+=' A logical respond rule cannot bind a response tag from its children. Use a default rule for a tagged response.';
  const unknown=$('#native-rule-unknown',form);unknown.hidden=!Object.keys(unrecognized).length;unknown.textContent='Additional stored fields are preserved. Use Edit JSON to inspect them: '+Object.keys(unrecognized).join(', ');
 }
 function read(validate=true){
  const config={...unrecognized,...matchEditor.value(),...actionEditor.value()};
  for(const key of validate?schemas.options.required:[])if(config[key]===undefined||config[key]===''){showTab('action');throw Error('Set '+key+' for action: '+currentAction+'.');}
  if(currentType==='logical'||Object.hasOwn(original,'type')||currentType!==initialType)config.type=currentType===initialType&&Object.hasOwn(original,'type')?original.type:currentType;
  if(Object.hasOwn(original,'action')||!item.id||currentAction!==initialAction)config.action=currentAction;
  return config;
 }
 schemas=nativeRuleSchemas(dns,currentType,currentAction);
 unrecognized=Object.fromEntries(Object.entries(original).filter(([key])=>!['type','action'].includes(key)&&!Object.hasOwn(schemas.match.properties,key)&&!Object.hasOwn(schemas.options.properties,key)));
 mount(original);form.nativeRuleValue=read;
 form.elements.native_rule_type.addEventListener('change',()=>{
  try{const config={...unrecognized,...matchEditor.value(),...actionEditor.value()};matchDrafts.set(currentType,matchEditor.value());currentType=form.elements.native_rule_type.value;const next=nativeRuleSchemas(dns,currentType,currentAction);mount({...pick(config,next.options.properties),...(matchDrafts.get(currentType)||(currentType==='logical'?{mode:'and',rules:[]}:{}))});showTab('match');}
  catch(error){form.elements.native_rule_type.value=currentType;$('#form-error',form).textContent=error.message;}
 });
 form.elements.native_rule_action.addEventListener('change',()=>{
  try{const config={...unrecognized,...matchEditor.value(),...actionEditor.value()};actionDrafts.set(currentAction,actionEditor.value());currentAction=form.elements.native_rule_action.value;const next=nativeRuleSchemas(dns,currentType,currentAction);mount({...pick(config,next.match.properties),...(actionDrafts.get(currentAction)||pick(config,next.options.properties))});showTab('action');}
  catch(error){form.elements.native_rule_action.value=currentAction;$('#form-error',form).textContent=error.message;}
 });
 $('#native-rule-json',form).onclick=()=>{try{routeJSONEditor(collection,routeRecord(item,read(false),form),read(false),collection==='dns_rules'?editDNSRule:editRouteRule);}catch(error){$('#form-error',form).textContent=error.message;}};
}
function editRouteRule(item={},preset){return editNativeRule('route_rules',item,preset);}
function readRouteRule(form){return form.nativeRuleValue();}
function editRouteDefaults(){
 const original=structuredClone(state.core_options.route||{}),resolver=original.default_domain_resolver||state.settings.dns_final;
 openModal('Routing defaults','Choose how traffic leaves when no rule selects a destination.',`<div class="form-grid">${selectField('Default destination','final',routeDestinations().map(x=>[x,routeDestinationName(x)]),original.final||'direct','class="full"')}${typeof resolver==='object'?'<p class="note full">A custom domain resolver is configured. It is preserved here; edit it in Advanced settings.</p>':selectField('Domain resolver','resolver',(state.dns_servers||[]).filter(x=>x.enabled!==false).map(x=>[routeTag(x),routeTag(x)]),resolver,'class="full"')}</div><p class="note">Other routing options stay as configured.</p>`,async form=>{
  const options={...original,final:form.elements.final.value};if(typeof resolver!=='object')options.default_domain_resolver=form.elements.resolver.value;
  await api('core-options',{revision:state.revision,section:'route',options});await load();toast('Routing defaults saved and applied.');
 });
}
function editRouteOptions(){
 const original=structuredClone(state.core_options.route||{});
 openModal('Advanced routing settings','Interfaces, network selection, process discovery and other Sing-box route options.',textField('Route options (JSON object)','route_json',JSON.stringify(original,null,2),'Rules and rule sets are managed in their own sections.','class="route-json-label"'),async form=>{const options=routeParseJSON(form.elements.route_json.value);if('rules' in options||'rule_set' in options)throw Error('Manage rules and rule sets in their own sections.');await api('core-options',{revision:state.revision,section:'route',options});await load();toast('Routing settings saved and applied.');});
}
const routeProxyFields={direct:[],socks:['username','password'],http:['username','password'],shadowsocks:['method','password'],vless:['uuid','flow'],vmess:['uuid','security','alter_id'],trojan:['password'],hysteria2:['password'],anytls:['password'],tuic:['uuid','password','congestion_control'],selector:['outbounds','default'],urltest:['outbounds','url','interval','tolerance']};
function routeGuidedDestination(c){
 if(!Object.hasOwn(routeProxyFields,c.type))return false;
 const keys=['type','tag','server','server_port','tls',...routeProxyFields[c.type]];
 if(!Object.keys(c).every(k=>keys.includes(k)))return false;
 if(c.tls&&!Object.keys(c.tls).every(k=>['enabled','server_name','insecure'].includes(k)))return false;
 return true;
}
function importRouteDestination(item={}){
 openModal('Import external destination','Paste a connection URI, subscription URL or Sing-box JSON. Review the extracted fields before saving.',`${textField('External link or JSON','external_link','','HTTP / HTTPS subscription URLs, Sing-box remote profile links, or individual proxy links.')}<p class="note">Only public subscription hosts can be fetched. Plain HTTP sends the subscription link without encryption. Local files, commands and local resource references are never imported.</p>`,async form=>{
  const session=csrf,result=await api('destination-import',{value:form.elements.external_link.value});if(session!==csrf)return false;
  const show=()=>{openModal('Choose a destination','A subscription may contain several proxies. Import one at a time.',selectField('Destination','import_choice',result.destinations.map((c,index)=>[String(index),c.tag+' · '+protocolLabel(c.type)+' · '+c.server]),'0'),form=>{const config=result.destinations[Number(form.elements.import_choice.value)];editRouteDestination(item,config);return false;},'Review fields');};
  if(result.destinations.length===1){editRouteDestination(item,result.destinations[0]);return false;}show();return false;
 },'Read link');
}
function editRouteDestination(item={},preset){
 const c=preset||legacyCoreConfig('outbounds',item),initial=c.type||'';
 if(initial&&!routeGuidedDestination(c))return preset?editCoreRecord('outbounds',item,c):routeJSONEditor('outbounds',item,c);
 const candidates=routeDestinations().filter(x=>x!==(c.tag||''));
 openModal(item.id?'Edit destination':'Add destination','Connect directly, chain through a proxy server, or group existing destinations.',`<div class="inline-buttons section-gap">${btn('External link','route-destination-import','download','',`data-id="${e(item.id||'')}"`)}</div>`+routeMeta(item)+`<div class="form-grid">${field('Destination tag','tag',c.tag||'','text','A unique name used by traffic rules.')}${selectField('Connection type','destination_type',[['','Choose a connection type'],...coreCatalog.types.outbounds.map(x=>[x,protocolLabel(x)+(Object.hasOwn(routeProxyFields,x)?'':' · Advanced JSON')])],initial)}</div><div id="route-connection-fields"></div><div class="route-editor-footer"><span>Transport, dial options or other advanced settings?</span><button class="text-link" type="button" id="destination-to-json">Edit advanced JSON</button></div>`,async form=>{await saveRecord('outbounds',routeRecord(item,readRouteDestination(form),form));});
 const form=$('#modal-form');form.elements.tag.required=true;form.elements.destination_type.required=true;
 const draw=()=>{
  const type=form.elements.destination_type.value,server=!['direct','selector','urltest',''].includes(type),group=['selector','urltest'].includes(type),keys=routeProxyFields[type];
  if(type&&!keys){const next=CoreSchema.seed(CoreSchema.protocolSchema('Outbound',type));next.tag=form.elements.tag.value;const properties=CoreSchema.protocolSchema('Outbound',type)?.properties||{};if(properties.server)next.server='';if(properties.server_port)next.server_port=443;return routeJSONEditor('outbounds',{...item,label:form.elements.display_name.value,enabled:form.elements.native_enabled.checked},next);}
  const values=type===initial?c:{};
  $('#route-connection-fields').innerHTML=(server?routeSection('1','Proxy server','The address of the upstream server, not the inbound on this panel.',`<div class="form-grid">${field('Server address','server',values.server||'')}${field('Server port','server_port',values.server_port||({socks:1080,http:8080}[type]||443),'number')}${(keys||[]).map(key=>key==='flow'?selectField('VLESS flow','flow',[['','None'],['xtls-rprx-vision','Vision']],values.flow||''):field(CoreSchema.title(key),key,values[key]??(key==='security'?'auto':key==='congestion_control'?'cubic':key==='alter_id'?0:''),key==='password'?'password':key==='alter_id'?'number':'text',key==='method'?'For example: 2022-blake3-aes-128-gcm':'')).join('')}</div>`):'')+
  (group?routeSection('1','Group members','Select destinations that already exist. A group cannot contain itself.',routeChecks('group_member',candidates.map(x=>[x,routeDestinationName(x)]),values.outbounds)+(type==='selector'?selectField('Initially selected destination','group_default',[['','First selected member'],...candidates.map(x=>[x,routeDestinationName(x)])],values.default||''):`<div class="form-grid">${field('Test URL','test_url',values.url||'https://www.gstatic.com/generate_204')}${field('Test interval','test_interval',values.interval||'3m')}${field('Tolerance (ms)','test_tolerance',values.tolerance??50,'number')}</div>`)):'')+
  (server&&CoreSchema.protocolSchema('Outbound',type)?.properties?.tls?routeSection('2','TLS','',`<label class="check-field"><input type="checkbox" name="tls_enabled" ${checked(values.tls?.enabled||['trojan','hysteria2','anytls','tuic'].includes(type))}>Use TLS</label><div id="destination-tls"><div class="form-grid">${field('Server name / SNI','tls_server_name',values.tls?.server_name||'','text','Leave empty to use the server address.')}</div><label class="check-field"><input type="checkbox" name="tls_insecure" ${checked(values.tls?.insecure)}>Allow insecure certificate verification</label></div>`):'')+
  (type==='direct'?'<p class="note">Connect directly from this server. For an ordinary direct route, use the built-in Direct destination.</p>':'');
  for(const key of ['server','server_port','uuid','method',...(['socks','http'].includes(type)?[]:['password'])])if(form.elements[key])form.elements[key].required=true;
  if(form.elements.server_port){form.elements.server_port.min=1;form.elements.server_port.max=65535;}
  const tls=form.elements.tls_enabled;if(tls){if(['trojan','hysteria2','anytls','tuic'].includes(type))tls.disabled=true;const sync=()=>{$('#destination-tls').hidden=!tls.checked};tls.onchange=sync;sync();}
 };
 form.elements.destination_type.addEventListener('change',draw);draw();
 $('#destination-to-json').onclick=()=>{try{const config=readRouteDestination(form);routeJSONEditor('outbounds',routeRecord(item,config,form),config);}catch(err){$('#form-error').textContent=err.message;}};
}
function readRouteDestination(form){
 const f=new FormData(form),type=f.get('destination_type'),tag=String(f.get('tag')||'').trim();
 if(!type||!Object.hasOwn(routeProxyFields,type))throw Error('Choose a connection type.');if(!tag)throw Error('Enter a destination tag.');
 const c={type,tag},keys=routeProxyFields[type];
 if(!['direct','selector','urltest'].includes(type)){
  c.server=String(f.get('server')||'').trim();c.server_port=Number(f.get('server_port'));if(!c.server||c.server_port<1||c.server_port>65535||!Number.isInteger(c.server_port))throw Error('Enter a server address and a port from 1 to 65535.');
  for(const key of keys){const raw=String(f.get(key)||''),value=['password','username'].includes(key)?raw:raw.trim();if(value)c[key]=key==='alter_id'?Number(value):value;}
  if(form.elements.tls_enabled?.checked)c.tls={enabled:true,...(f.get('tls_server_name')?{server_name:String(f.get('tls_server_name')).trim()}:{}),...(form.elements.tls_insecure.checked?{insecure:true}:{})};
 }
 if(['selector','urltest'].includes(type)){
  c.outbounds=f.getAll('group_member');if(!c.outbounds.length)throw Error('Select at least one group member.');
  if(type==='selector'&&f.get('group_default')){if(!c.outbounds.includes(f.get('group_default')))throw Error('The initial destination must be a selected group member.');c.default=f.get('group_default');}
  if(type==='urltest'){c.url=String(f.get('test_url')).trim();c.interval=String(f.get('test_interval')).trim();c.tolerance=Number(f.get('test_tolerance'));}
 }
 return c;
}
function editRouteSet(item={}){
 const c=legacyCoreConfig('rule_sets',item);
 if(Object.keys(c).some(k=>!['type','tag','url','format','update_interval','download_detour','path','rules'].includes(k)))return routeJSONEditor('rule_sets',item,c,editRouteSet);
 openModal(item.id?'Edit shared rule set':'Add shared rule set','Lists can be used by both traffic rules and DNS rules.',routeMeta(item)+field('Rule set tag','tag',c.tag||'')+routeSection('1','Where is the list?', '',routeChoices('set_type',[['remote','Remote URL','Download and refresh a list'],['local','Local file','Read a file on this server'],['inline','Inline rules','Store the rules in this panel']],c.type||'remote'))+
 `<div data-set-type="remote" class="form-grid">${field('List URL','url',c.url||'','url','Use a trusted source for .srs or source JSON lists.','class="full"')}${selectField('Format','remote_format',[['binary','Binary (.srs)'],['source','Source JSON']],c.format||'binary')}${field('Refresh interval','update_interval',c.update_interval||'1d')}${selectField('Download through','download_detour',[['','Core default'],...routeDestinations().map(x=>[x,routeDestinationName(x)])],c.download_detour||'','class="full"')}</div>`+
 `<div data-set-type="local" class="form-grid">${field('Absolute file path','path',c.path||'','text','Must be readable by the panel service.','class="full"')}${selectField('Format','local_format',[['binary','Binary (.srs)'],['source','Source JSON']],c.format||'binary')}</div>`+
 `<div data-set-type="inline">${textField('Headless rules (JSON array)','rules',JSON.stringify(c.rules||[{domain_suffix:['example.com']}],null,2),'Match conditions only; the traffic rule chooses the action.','class="route-json-label"')}</div><div class="route-editor-footer"><span>HTTP clients, initial files or other options?</span><button class="text-link" type="button" id="set-to-json">Edit advanced JSON</button></div>`,async form=>{await saveRecord('rule_sets',routeRecord(item,readRouteSet(form),form));});
 const form=$('#modal-form');form.elements.tag.required=true;const sync=()=>{for(const node of $$('[data-set-type]',form)){node.hidden=node.dataset.setType!==form.elements.set_type.value;for(const input of $$('input,select,textarea',node))input.disabled=node.hidden;}};form.addEventListener('change',sync);sync();
 $('#set-to-json').onclick=()=>{try{const config=readRouteSet(form);routeJSONEditor('rule_sets',routeRecord(item,config,form),config,editRouteSet);}catch(err){$('#form-error').textContent=err.message;}};
}
function readRouteSet(form){
 const f=new FormData(form),config={type:f.get('set_type'),tag:String(f.get('tag')).trim()};if(!config.tag)throw Error('Enter a rule set tag.');
 if(config.type==='inline'){try{config.rules=JSON.parse(f.get('rules'));}catch{throw Error('Enter valid JSON for inline rules.');}if(!Array.isArray(config.rules)||!config.rules.length)throw Error('Inline rules must be a nonempty JSON array.');}
 else{config.format=f.get(config.type+'_format');if(config.type==='remote'){config.url=String(f.get('url')).trim();config.update_interval=String(f.get('update_interval')).trim();if(f.get('download_detour'))config.download_detour=f.get('download_detour');}else config.path=String(f.get('path')).trim();}
 return config;
}
async function handleRouting(action,target){
 if(action==='route-destination-import')return importRouteDestination((state.outbounds||[]).find(row=>row.id===target.dataset.id)||{});
 const id=target.dataset.id,find=collection=>(state[collection]||[]).find(x=>x.id===id);
 if(action==='route-warp-new')return createWARP();
 if(action==='route-use-destination')return editRouteRule({}, {action:'route',outbound:id});
 if(action==='route-new')return editRouteRule();
 if(action==='route-edit')return editRouteRule(find('route_rules'));
 if(action==='route-preset')return editRouteRule({},id==='dns'?{port:[53],action:'hijack-dns'}:{domain_suffix:[],action:'reject'});
 if(action==='route-json-new')return routeJSONEditor('route_rules',{}, {action:'route',outbound:'direct'},editRouteRule);
 if(action==='route-defaults')return editRouteDefaults();
 if(action==='route-advanced-options')return editRouteOptions();
 if(action==='route-destination-new')return editRouteDestination();
 if(action==='route-destination-edit')return editRouteDestination(find('outbounds'));
 if(action==='route-set-new')return editRouteSet();
 if(action==='route-set-edit')return editRouteSet(find('rule_sets'));
 if(action==='route-use-set')return editRouteRule({}, {rule_set:[id],action:'route',outbound:'direct'});
 if(action==='route-toggle'){const row=find('route_rules');await saveRecord('route_rules',{...row,enabled:row.enabled===false});return;}
 if(action==='route-move'){await api('reorder-rules',{revision:state.revision,collection:'route_rules',id,direction:target.dataset.direction});await load();toast('Rule order saved and applied.');return;}
}

function createWARP(){
 openModal('Create Cloudflare WARP','Register a free WARP connection and add it as a routing destination.',`<div class="hint-box">Keys are generated on your server. Only the public key is sent to Cloudflare. Your existing default route stays as configured.</div><p class="confirm-text">After creation, choose WARP in a traffic rule to send selected connections through Cloudflare. Registration and connectivity depend on Cloudflare availability and this server’s network.</p><label class="check-field"><input type="checkbox" name="warp_terms" required><span>I accept <a class="text-link" href="https://www.cloudflare.com/application/terms/" target="_blank" rel="noopener noreferrer">Cloudflare’s consumer terms</a> for this registration.</span></label>`,async form=>{
  if(!form.elements.warp_terms.checked)throw Error('Accept Cloudflare’s consumer terms first.');
  const result=await api('warp',{revision:state.revision,accept_terms:true});routingTab='outbounds';await load();toast('WARP created as '+result.tag+'. Use it as a destination in a traffic rule.');
 },'Create WARP');
}
