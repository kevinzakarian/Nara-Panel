'use strict';
// Versioned upstream schema drives every field, including nested records and unions.
const CoreSchema=(()=>{
 let catalog;
 const clone=value=>JSON.parse(JSON.stringify(value));
 const title=key=>(catalog?.labels&&Object.hasOwn(catalog.labels,key)?catalog.labels[key]:null)||({__proto__:null,dns:'DNS',tls:'TLS',ntp:'NTP',http:'HTTP',url:'URL',ip:'IP',uuid:'UUID',alpn:'ALPN',sni:'SNI',quic:'QUIC',tcp:'TCP',udp:'UDP',api:'API',cidr:'CIDR',srs:'SRS',mtu:'MTU',ech:'ECH',reality:'REALITY',utls:'uTLS',dhcp:'DHCP',ssh:'SSH',tuic:'TUIC',vmess:'VMess',vless:'VLESS',hysteria2:'Hysteria2',anytls:'AnyTLS'}[key]||key.replaceAll('-','_').split('_').map(word=>({__proto__:null,dns:'DNS',tls:'TLS',ip:'IP',http:'HTTP',url:'URL',tcp:'TCP',udp:'UDP',api:'API',alpn:'ALPN',sni:'SNI',mtu:'MTU',cidr:'CIDR',id:'ID',ssid:'SSID',bssid:'BSSID',wifi:'Wi-Fi',mac:'MAC',rtt:'RTT',bbr:'BBR'}[word]||word.charAt(0).toUpperCase()+word.slice(1))).join(' '));
 const ref=s=>s?.$ref?catalog.schema.$defs[s.$ref.split('/').at(-1)]:s||{};
 function merge(a,b){return {...a,...b,properties:{...a.properties,...b.properties},required:[...new Set([...(a.required||[]),...(b.required||[])])]};}
 function branches(raw){
  const s=ref(raw);
  if(s.oneOf)return s.oneOf.flatMap(branches);
  if(s.allOf)return s.allOf.reduce((out,part)=>out.flatMap(a=>branches(part).map(b=>merge(a,b))),[{type:'object',properties:{}}]);
  return [s];
 }
 function compatible(s,value){
  if(value!==undefined&&s.type){const kind=Array.isArray(value)?'array':value===null?'null':typeof value;if(s.type==='integer'){if(kind!=='number')return false;}else if(s.type!==kind)return false;}
  if(!value||typeof value!=='object')return true;
  return Object.entries(s.properties||{}).every(([key,p])=>{
   if('const' in p)return !(key in value)||value[key]===p.const;
   if(p.enum&&key in value)return p.enum.includes(value[key]);
   return true;
  });
 }
 function choose(raw,value){
  let s=ref(raw);
  if(s.anyOf){const type=Array.isArray(value)?'array':typeof value;return ref(s.anyOf.find(x=>ref(x).type===type||(ref(x).type==='integer'&&type==='number'&&Number.isInteger(value)))||s.anyOf.find(x=>ref(x).type==='array')||s.anyOf[0]);}
  const list=branches(s);return list.find(x=>compatible(x,value))||list[0];
 }
 function seed(raw){
  const s=choose(raw,undefined);
  if('const' in s)return clone(s.const);
  if(s.default!==undefined)return clone(s.default);
  if(s.enum)return clone(s.enum[0]);
  if(s.type==='object'||s.properties){const v={};for(const k of s.required||[])if(s.properties[k])v[k]=seed(s.properties[k]);for(const [k,p] of Object.entries(s.properties||{}))if('const' in p)v[k]=p.const;if(v.type==='anytls'&&s.properties?.padding_scheme&&catalog.defaults?.anytls_padding)v.padding_scheme=clone(catalog.defaults.anytls_padding);return v;}
  return s.type==='array'?[]:s.type==='boolean'?false:['integer','number'].includes(s.type)?0:'';
 }
 function byName(name){return catalog.schema.$defs[name];}
 function protocolSchema(direction,type){return branches(byName(direction)).find(x=>x.properties?.type?.const===type);}
 function mount(container,raw,initial={},settings={}){
  let value=clone(initial);let sequence=0;const nodes=new Map();
  const dnsPorts={udp:53,tcp:53,tls:853,quic:853,https:443,h3:443};
  const guided=settings.layout==='dns';
  const displayValue=input=>input.type==='checkbox'?input.checked:input.value;
  function draw(){const panels=new Map([...container.querySelectorAll('[data-core-panel]')].map(el=>[el.dataset.corePanel,el.open]));for(const node of settings.preserveNodes||[])node.remove();sequence=0;nodes.clear();container.innerHTML=render(raw,value,v=>{value=v},'Configuration',true,0);for(const node of settings.preserveNodes||[])container.querySelector('[data-dns-field=tag]')?.before(node);if(settings.typeContainer){const type=container.querySelector('[data-core-variant="0"]')?.closest('label');settings.typeContainer.replaceChildren(...(type?[type]:[]));}for(const input of container.querySelectorAll('[data-core-input]'))nodes.get(input.dataset.coreInput).display=displayValue(input);for(const panel of container.querySelectorAll('[data-core-panel]'))if(panels.has(panel.dataset.corePanel))panel.open=panels.get(panel.dataset.corePanel);}
  function dnsObject(s,obj,set,id,label,root,depth,scope,variant=''){
   const props=s.properties||{},required=s.required||[],remote=root&&Object.hasOwn(dnsPorts,obj.type),tls=label==='TLS';
   const basic=(root?['tag',...(remote?['server','server_port','path','domain_resolver']:['interface','endpoint','service','inet4_range','inet6_range','path','predefined']),...(props.tls?['tls']:[])]:tls?(settings.simple?['server_name','insecure']:['enabled','server_name','insecure']):Object.keys(obj));
   if(tls&&settings.simple&&!Object.hasOwn(obj,'enabled'))obj.enabled=true;
   const pinned=[...new Set([...basic,...required])].filter(key=>Object.hasOwn(props,key)&&!('const'in props[key]));
   const defaults={tag:'',server:'',server_port:dnsPorts[obj.type],domain_resolver:'',...(remote?{path:'/dns-query',tls:{enabled:true}}:{}),...(tls?{enabled:true,server_name:'',insecure:false}:{})};
   const essential=new Set(root?['tag',...(remote?['server','server_port']:[]),...(props.tls?['tls']:[])]:tls?['enabled',...required]:required);
   function field(key,optional=false){
    const p=props[key]||{},has=Object.hasOwn(obj,key),item=has?obj[key]:Object.hasOwn(defaults,key)?defaults[key]:seed(p);
    if(!has&&essential.has(key))obj[key]=item;
    if(root&&key==='tls'&&settings.managedTLS)return `<div class="dns-wide dns-tls-summary" data-dns-field="tls">TLS is configured automatically · ${e(item.server_name||obj.server)}${item.insecure?' · Certificate verification disabled':''}</div>`;
    const put=x=>{if(x===undefined||x==='')delete obj[key];else Object.defineProperty(obj,key,{value:x,writable:true,enumerable:true,configurable:true});set(obj)};
    const help=({tag:'Unique name used by DNS rules and the default resolver.',server:'IP address or hostname, without a URL or port.',server_port:'Destination port on the DNS server.',domain_resolver:'Only needed when Server is a hostname. An IP address works independently.',path:remote?'HTTPS request path, usually /dns-query.':null,server_name:tls?'Certificate name / SNI. Leave blank to use the server address.':null,insecure:tls?'Skip certificate verification only when required by your resolver.':null}[key])||(catalog.help._documents?.[scope]?.[key]||catalog.help[key])?.description?.replace(/[`*_#]/g,'').slice(0,200)||'';
    let control=render(p,item,put,title(key),false,depth+1,scope);
    if(essential.has(key)&&['string','integer','number'].includes(choose(p,item).type))control=control.replace('data-core-input=',`required data-core-input=`);
    if(key==='server_port')control=control.replace('min="0"','min="1"');
    return `<div class="dns-field ${['tls','predefined'].includes(key)||(!remote&&key==='path')||(key==='domain_resolver'&&typeof item==='object')?'dns-wide':''}" data-dns-field="${e(key)}">${optional?`<label class="check-field dns-custom"><input type="checkbox" checked data-core-toggle="${id}" data-key="${e(key)}"><span>Custom ${e(title(key))}</span></label>`:''}${control}${help?`<small class="field-hint">${e(help)}</small>`:''}</div>`;
   }
   const extras=Object.keys(props).filter(key=>!pinned.includes(key)&&!('const'in props[key])&&!settings.exclude?.includes(key));
   const configured=extras.filter(key=>Object.hasOwn(obj,key));
   const unknown=Object.keys(obj).filter(key=>!Object.hasOwn(props,key));
   const advanced=!settings.simple&&extras.length?`<details class="dns-advanced" data-core-panel="${id}"><summary>${tls?'Advanced TLS settings':'Advanced settings'}${configured.length?` <span class="badge">${configured.length} configured</span>`:''}</summary><div class="dns-field-grid">${configured.map(key=>field(key,true)).join('')}</div><div class="dns-option-grid">${extras.filter(key=>!Object.hasOwn(obj,key)).map(key=>`<label class="check-field"><input type="checkbox" data-core-toggle="${id}" data-key="${e(key)}"><span>${e(title(key))}</span></label>`).join('')}</div></details>`:'';
   // Unknown future fields stay in the model and can be edited in JSON view.
   return `<div class="dns-field-grid ${root?'dns-root-fields':''}">${pinned.map(key=>field(key)+(key==='tag'?variant:'')).join('')}</div>${advanced}${!settings.simple&&unknown.length?'<p class="note">Additional stored fields are preserved. Use JSON view to edit them.</p>':''}`;
  }
  function render(input,v,set,label,root=false,depth=0,scope=settings.scope||''){
   if(depth>20)return '<p class="note">Nesting limit reached. Use the JSON view for this value.</p>';
   const id=String(sequence++);
   const all=branches(input).filter(branch=>!root||!settings.types||settings.types.includes(branch.properties?.type?.const)),s=choose(input,v),html=[];
   nodes.set(id,{input,value:v,set,label,variants:all,root});
   if(root&&settings.collection){const type=v?.type||s.properties?.type?.const||'';const base={inbounds:'inbound/',outbounds:'outbound/',dns_servers:'dns/server/',dns_rules:'dns/rule',route_rules:'route/rule',rule_sets:'rule-set/index',endpoints:'endpoint/',services:'service/',certificate_providers:'certificate-provider/',http_clients:'http-client/',network_namespaces:'network-namespace/'}[settings.collection];scope=base?.endsWith('/')?base+type:base||scope;}
   if(label==='TLS')scope='shared/tls';
   if(all.length>1){
    html.push(`<label class="schema-variant">${e(guided&&root?'Resolver type':label+' type')}<select data-core-variant="${id}">${all.map((b,index)=>{const labels=Object.entries(b.properties||{}).filter(([k,p])=>'const'in p).map(([k,p])=>title(String(p.const)));if(!labels.length&&b.properties?.type?.enum?.[0])labels.push(title(b.properties.type.enum[0]));return `<option value="${index}" ${index===Math.max(0,all.findIndex(x=>compatible(x,v)))?'selected':''}>${e(labels.join(' / ')||'Default')}</option>`}).join('')}</select></label>`);
   }
   const common=`data-core-input="${id}"`;
   if(s.type==='object'||s.properties){
    const props=s.properties||{},obj=v&&typeof v==='object'&&!Array.isArray(v)?v:{},required=s.required||[];
    if(guided&&!s.additionalProperties){
     for(const [key,p] of Object.entries(props))if('const'in p&&!Object.hasOwn(obj,key))obj[key]=p.const;
     const variant=root&&all.length>1?html.pop():'';
     html.push(dnsObject(s,obj,set,id,label,root,depth,scope,variant));
     if(!v||typeof v!=='object'||Array.isArray(v))set(obj);
    }else{
    const shown=new Set([...Object.keys(obj),...required,...Object.entries(props).filter(([k,p])=>'const'in p).map(([k])=>k)]);
    html.push('<div class="schema-fields">');
    for(const key of shown){
     const rawProperty=Object.hasOwn(props,key)?props[key]:s.additionalProperties,p=rawProperty===true?{}:rawProperty;if(!p||typeof p!=='object')continue;
     const has=Object.hasOwn(obj,key),item=has?obj[key]:seed(p);
     if(!has&&required.includes(key))obj[key]=item;
     if('const'in p){if(!has)obj[key]=p.const;continue;}
     const reference=choose(p,item)['x-tag-reference'];
     const help=reference?'Select a configured '+title(reference).toLowerCase()+'.':(catalog.help._documents?.[scope]?.[key]||catalog.help[key])?.description?.replace(/[`*_#]/g,'').slice(0,250)||'';
     const control=render(p,item,x=>{Object.defineProperty(obj,key,{value:x,writable:true,enumerable:true,configurable:true});set(obj)},Object.hasOwn(props,key)?title(key):key,false,depth+1,scope);
     const remove=required.includes(key)?'':`<button type="button" class="schema-remove" aria-label="Remove ${e(title(key))}" data-core-remove="${id}" data-key="${e(key)}">×</button>`;
     html.push(`<div class="schema-property"><div class="schema-property-control">${control}${help?`<small class="field-hint">${e(help)}</small>`:''}</div>${remove}</div>`);
    }
    const missing=Object.keys(props).filter(k=>!shown.has(k)&&!settings.exclude?.includes(k));
    if(missing.length)html.push(`<label class="schema-add-label">Add option<select data-core-add="${id}" aria-label="Add option to ${e(label)}"><option value="">Choose an option…</option>${missing.map(k=>`<option value="${e(k)}">${e(title(k))}</option>`).join('')}</select></label>`);
    if(s.additionalProperties)html.push(`<div class="schema-map-add"><input data-core-map-key="${id}" aria-label="New key in ${e(label)}" placeholder="New name"><button type="button" class="btn sm" data-core-map-add="${id}">Add entry</button></div>`);
    html.push('</div>');
    if(!v||typeof v!=='object'||Array.isArray(v))set(obj);
    }
   }else if(s.type==='array'){
    const array=Array.isArray(v)?v:v===undefined?[]:[v];
    html.push(`<fieldset class="schema-array"><legend>${e(label)}</legend>`);
    array.forEach((item,index)=>html.push(`<div class="schema-array-item">${render(s.items||{},item,x=>{array[index]=x;set(array)},`${label} ${index+1}`,false,depth+1,scope)}<button type="button" class="schema-remove" aria-label="Remove item ${index+1}" data-core-item-remove="${id}" data-index="${index}">×</button></div>`));
    html.push(`<button type="button" class="btn sm" data-core-item-add="${id}">Add ${e(label)} item</button></fieldset>`);
    if(!Array.isArray(v))set(array);
   }else if(s['x-tag-reference']&&settings.references){const choices=[...new Set([...(settings.references[s['x-tag-reference']]||[]),...(v?[v]:[])])];html.push(`<label>${e(label)}<select ${common}><option value="">${guided?'None / default':'Choose…'}</option>${choices.map(tag=>`<option value="${e(tag)}" ${tag===v?'selected':''}>${e(tag)}</option>`).join('')}</select></label>`);
   }else if(s.enum){html.push(`<label>${e(label)}<select ${common}>${s.enum.map(x=>`<option value="${e(x)}" ${x===v?'selected':''}>${e(catalog.labels?.[x]||String(x))}</option>`).join('')}</select></label>`);
   }else if(s.type==='boolean')html.push(`<label class="check-field"><input type="checkbox" ${common} ${v?'checked':''}><span>${e(label)}</span></label>`);
   else if(['integer','number'].includes(s.type))html.push(`<label>${e(label)}<input type="number" ${common} value="${e(v??'')}" step="${s.type==='integer'?'1':'any'}" ${s.minimum!==undefined?`min="${s.minimum}"`:''} ${s.maximum!==undefined?`max="${s.maximum}"`:''}></label>`);
   else if(s.type==='string'||'const'in s){const secret=/password|private.key|secret|^key$/i.test(label);html.push(`<label>${e(label)}<textarea rows="${String(v||'').includes('\n')?4:1}" ${common} class="${secret?'schema-secret':''}" dir="ltr" autocomplete="off">${e(v??'')}</textarea></label>`);}
   else html.push(`<label>${e(label)} (JSON)<textarea rows="4" data-core-json="${id}" dir="ltr">${e(JSON.stringify(v??null,null,2))}</textarea></label>`);
   const content=html.join('');
   return !root&&(s.type==='object'||s.properties)?`<details class="schema-object" open><summary>${e(label)}</summary>${content}</details>`:content;
  }
  function readInput(input){
   const node=nodes.get(input.dataset.coreInput);if(!node)return;
   node.display=displayValue(input);
   const s=choose(node.input,node.value);let v=input.type==='checkbox'?input.checked:input.value;
   if(['integer','number'].includes(s.type)){if(v===''){node.set(undefined);return;}v=Number(v);}
   if(s.enum){v=s.enum.find(x=>String(x)===String(v));}
   node.set(v);
  }
  // Autofill and some input methods can update controls without an input event.
  // Keep untouched values byte-for-byte; synchronize only changed controls.
  function syncInputs(){for(const input of container.querySelectorAll('[data-core-input]'))if(displayValue(input)!==nodes.get(input.dataset.coreInput).display)readInput(input);}
  container.addEventListener('input',event=>readInput(event.target));
  function change(event){
   const el=event.target;
   syncInputs();
   if(el.dataset.coreVariant!==undefined){const node=nodes.get(el.dataset.coreVariant),next=node.variants[Number(el.value)],old=node.value||{};let fresh=seed(next);for(const key of Object.keys(next.properties||{}))if(Object.hasOwn(old,key)&&!('const'in next.properties[key]))fresh[key]=old[key];if(guided&&node.root&&dnsPorts[fresh.type]&&old.server_port===dnsPorts[old.type])fresh.server_port=dnsPorts[fresh.type];if(node.root&&settings.transformType)fresh=settings.transformType(fresh,old);node.set(fresh);draw();}
   if(el.dataset.coreToggle!==undefined){const node=nodes.get(el.dataset.coreToggle),s=choose(node.input,node.value),obj=node.value||{};if(el.checked)Object.defineProperty(obj,el.dataset.key,{value:seed(s.properties[el.dataset.key]),writable:true,enumerable:true,configurable:true});else delete obj[el.dataset.key];node.set(obj);draw();}
   if(el.dataset.coreAdd!==undefined&&el.value){const node=nodes.get(el.dataset.coreAdd),s=choose(node.input,node.value),obj=node.value||{};Object.defineProperty(obj,el.value,{value:seed(s.properties[el.value]),writable:true,enumerable:true,configurable:true});node.set(obj);draw();}
  }
  container.addEventListener('change',change);
  if(settings.typeContainer)settings.typeContainer.addEventListener('change',change);
  container.addEventListener('click',event=>{
   const el=event.target.closest('button');if(!el)return;
   syncInputs();
   if(el.dataset.coreRemove!==undefined){const node=nodes.get(el.dataset.coreRemove),obj=node.value;delete obj[el.dataset.key];node.set(obj);draw();}
   if(el.dataset.coreItemRemove!==undefined){const node=nodes.get(el.dataset.coreItemRemove),array=node.value;array.splice(Number(el.dataset.index),1);node.set(array);draw();}
   if(el.dataset.coreItemAdd!==undefined){const node=nodes.get(el.dataset.coreItemAdd),s=choose(node.input,node.value),array=Array.isArray(node.value)?node.value:[];array.push(seed(s.items||{}));node.set(array);draw();}
   if(el.dataset.coreMapAdd!==undefined){const node=nodes.get(el.dataset.coreMapAdd),key=container.querySelector(`[data-core-map-key="${el.dataset.coreMapAdd}"]`).value.trim();if(!key)return;const obj=node.value||{};Object.defineProperty(obj,key,{value:seed(choose(node.input,obj).additionalProperties===true?{}:choose(node.input,obj).additionalProperties),writable:true,enumerable:true,configurable:true});node.set(obj);draw();}
  });
  draw();
  return {value(){syncInputs();for(const input of container.querySelectorAll('[data-core-json]')){try{nodes.get(input.dataset.coreJson).set(JSON.parse(input.value));}catch{throw new Error('Enter valid JSON for '+nodes.get(input.dataset.coreJson).label);}}return clone(value);},set(next){value=clone(next);draw();}};
 }
 return {configure(value){catalog=value},title,byName,protocolSchema,branches,choose,seed,mount};
})();
