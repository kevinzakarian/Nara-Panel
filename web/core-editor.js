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
  function draw(){sequence=0;nodes.clear();container.innerHTML=render(raw,value,v=>{value=v},'Configuration',true,0);}
  function render(input,v,set,label,root=false,depth=0,scope=settings.scope||''){
   if(depth>20)return '<p class="note">Nesting limit reached. Use the JSON view for this value.</p>';
   const id=String(sequence++);nodes.set(id,{input,value:v,set,label});
   const all=branches(input),s=choose(input,v),html=[];
   if(root&&settings.collection){const type=v?.type||s.properties?.type?.const||'';const base={inbounds:'inbound/',outbounds:'outbound/',dns_servers:'dns/server/',dns_rules:'dns/rule',route_rules:'route/rule',rule_sets:'rule-set/index',endpoints:'endpoint/',services:'service/',certificate_providers:'certificate-provider/',http_clients:'http-client/',network_namespaces:'network-namespace/'}[settings.collection];scope=base?.endsWith('/')?base+type:base||scope;}
   if(label==='TLS')scope='shared/tls';
   if(all.length>1){
    html.push(`<label class="schema-variant">${e(label)} type<select data-core-variant="${id}">${all.map((b,index)=>{const labels=Object.entries(b.properties||{}).filter(([k,p])=>'const'in p).map(([k,p])=>title(String(p.const)));if(!labels.length&&b.properties?.type?.enum?.[0])labels.push(title(b.properties.type.enum[0]));return `<option value="${index}" ${index===Math.max(0,all.findIndex(x=>compatible(x,v)))?'selected':''}>${e(labels.join(' / ')||'Default')}</option>`}).join('')}</select></label>`);
   }
   const common=`data-core-input="${id}"`;
   if(s.type==='object'||s.properties){
    const props=s.properties||{},obj=v&&typeof v==='object'&&!Array.isArray(v)?v:{},required=s.required||[];
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
   }else if(s.type==='array'){
    const array=Array.isArray(v)?v:v===undefined?[]:[v];
    html.push(`<fieldset class="schema-array"><legend>${e(label)}</legend>`);
    array.forEach((item,index)=>html.push(`<div class="schema-array-item">${render(s.items||{},item,x=>{array[index]=x;set(array)},`${label} ${index+1}`,false,depth+1,scope)}<button type="button" class="schema-remove" aria-label="Remove item ${index+1}" data-core-item-remove="${id}" data-index="${index}">×</button></div>`));
    html.push(`<button type="button" class="btn sm" data-core-item-add="${id}">Add ${e(label)} item</button></fieldset>`);
    if(!Array.isArray(v))set(array);
   }else if(s['x-tag-reference']&&settings.references){const choices=[...new Set([...(settings.references[s['x-tag-reference']]||[]),...(v?[v]:[])])];html.push(`<label>${e(label)}<select ${common}><option value="">Choose…</option>${choices.map(tag=>`<option value="${e(tag)}" ${tag===v?'selected':''}>${e(tag)}</option>`).join('')}</select></label>`);
   }else if(s.enum){html.push(`<label>${e(label)}<select ${common}>${s.enum.map(x=>`<option value="${e(x)}" ${x===v?'selected':''}>${e(catalog.labels?.[x]||String(x))}</option>`).join('')}</select></label>`);
   }else if(s.type==='boolean')html.push(`<label class="check-field"><input type="checkbox" ${common} ${v?'checked':''}><span>${e(label)}</span></label>`);
   else if(['integer','number'].includes(s.type))html.push(`<label>${e(label)}<input type="number" ${common} value="${e(v??'')}" step="${s.type==='integer'?'1':'any'}" ${s.minimum!==undefined?`min="${s.minimum}"`:''} ${s.maximum!==undefined?`max="${s.maximum}"`:''}></label>`);
   else if(s.type==='string'||'const'in s){const secret=/password|private.key|secret|^key$/i.test(label);html.push(`<label>${e(label)}<textarea rows="${String(v||'').includes('\n')?4:1}" ${common} class="${secret?'schema-secret':''}" dir="ltr" autocomplete="off">${e(v??'')}</textarea></label>`);}
   else html.push(`<label>${e(label)} (JSON)<textarea rows="4" data-core-json="${id}" dir="ltr">${e(JSON.stringify(v??null,null,2))}</textarea></label>`);
   const content=html.join('');
   return !root&&(s.type==='object'||s.properties)?`<details class="schema-object" open><summary>${e(label)}</summary>${content}</details>`:content;
  }
  container.addEventListener('input',event=>{
   const input=event.target,id=input.dataset.coreInput,node=nodes.get(id);if(!node)return;
   const s=choose(node.input,node.value);let v=input.type==='checkbox'?input.checked:input.value;
   if(['integer','number'].includes(s.type)){if(v===''){node.set(undefined);return;}v=Number(v);}
   if(s.enum){v=s.enum.find(x=>String(x)===String(v));}
   node.set(v);
  });
  container.addEventListener('change',event=>{
   const el=event.target;
   if(el.dataset.coreVariant!==undefined){const node=nodes.get(el.dataset.coreVariant),next=branches(node.input)[Number(el.value)],old=node.value||{},fresh=seed(next);for(const key of Object.keys(next.properties||{}))if(Object.hasOwn(old,key)&&!('const'in next.properties[key]))fresh[key]=old[key];node.set(fresh);draw();}
   if(el.dataset.coreAdd!==undefined&&el.value){const node=nodes.get(el.dataset.coreAdd),s=choose(node.input,node.value),obj=node.value||{};Object.defineProperty(obj,el.value,{value:seed(s.properties[el.value]),writable:true,enumerable:true,configurable:true});node.set(obj);draw();}
  });
  container.addEventListener('click',event=>{
   const el=event.target.closest('button');if(!el)return;
   if(el.dataset.coreRemove!==undefined){const node=nodes.get(el.dataset.coreRemove),obj=node.value;delete obj[el.dataset.key];node.set(obj);draw();}
   if(el.dataset.coreItemRemove!==undefined){const node=nodes.get(el.dataset.coreItemRemove),array=node.value;array.splice(Number(el.dataset.index),1);node.set(array);draw();}
   if(el.dataset.coreItemAdd!==undefined){const node=nodes.get(el.dataset.coreItemAdd),s=choose(node.input,node.value),array=Array.isArray(node.value)?node.value:[];array.push(seed(s.items||{}));node.set(array);draw();}
   if(el.dataset.coreMapAdd!==undefined){const node=nodes.get(el.dataset.coreMapAdd),key=container.querySelector(`[data-core-map-key="${el.dataset.coreMapAdd}"]`).value.trim();if(!key)return;const obj=node.value||{};Object.defineProperty(obj,key,{value:seed(choose(node.input,obj).additionalProperties===true?{}:choose(node.input,obj).additionalProperties),writable:true,enumerable:true,configurable:true});node.set(obj);draw();}
  });
  draw();
  return {value(){for(const input of container.querySelectorAll('[data-core-json]')){try{nodes.get(input.dataset.coreJson).set(JSON.parse(input.value));}catch{throw new Error('Enter valid JSON for '+nodes.get(input.dataset.coreJson).label);}}return clone(value);},set(next){value=clone(next);draw();}};
 }
 return {configure(value){catalog=value},title,byName,protocolSchema,branches,choose,seed,mount};
})();
