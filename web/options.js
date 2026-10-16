'use strict';

function optionValue(obj,key) { return key.split('.').reduce((value,part)=>value?.[part],obj); }
function optionFields(fields,values,prefix) {
 return fields.map(f=>{
  const name=prefix+'.'+f.key,value=optionValue(values,f.key)??f.default;
  const hint=f.hint?`<small class="field-hint">${e(f.hint)}</small>`:'';
  const when=f.when?` data-when="${e(prefix+'.'+f.when)}"`:'';
  let input;
  if(f.kind==='checkbox') input=`<input type="checkbox" name="${e(name)}" ${checked(value)}><span>${e(f.label)}${hint}</span>`;
  else if(f.kind==='select') input=`${e(f.label)}<select name="${e(name)}">${f.choices.map(v=>`<option value="${e(v)}" ${String(v)===String(value??'')?'selected':''}>${e(v||'Default / disabled')}</option>`).join('')}</select>${hint}`;
  else if(['lines','json','textarea'].includes(f.kind)) input=`${e(f.label)}<textarea name="${e(name)}" dir="ltr" rows="3">${e(f.kind==='lines'?(value||[]).join('\n'):f.kind==='json'&&value?JSON.stringify(value,null,2):value||'')}</textarea>${hint}`;
  else input=`${e(f.label)}<input name="${e(name)}" type="${f.kind==='password'?'password':f.kind==='number'?'number':'text'}" value="${e(value??'')}" ${f.kind==='number'?`min="${f.minimum}" max="${f.maximum}" step="1"`:''} dir="ltr" autocomplete="off">${hint}`;
  return `<label class="${f.kind==='checkbox'?'check-field':f.kind==='lines'||f.kind==='json'||f.kind==='textarea'?'full':''}"${when}>${input}</label>`;
 }).join('');
}
function optionSection(title,fields,values,prefix,open=false) {
 if(!fields.length)return '';
 return `<details class="option-section" ${open?'open':''}><summary>${e(title)}</summary><div class="form-grid">${optionFields(fields,values,prefix)}</div></details>`;
}
function readOptions(form,prefix,fields) {
 const result={};
 for(const f of fields) {
  const input=form.elements.namedItem(prefix+'.'+f.key);
  if(!input||input.disabled)continue;
  let value=input.type==='checkbox'?input.checked:input.value.trim();
  if(value==='')continue;
  if(f.kind==='number'||f.kind==='select'&&f.choices.some(v=>typeof v==='number'))value=Number(value);
  if(f.kind==='lines')value=value.split('\n').map(v=>v.trim()).filter(Boolean);
  if(f.kind==='json') {try{value=JSON.parse(value);}catch{throw new Error(f.label+' must contain valid JSON.');}}
  let node=result;const parts=f.key.split('.');
  for(const part of parts.slice(0,-1))node=node[part]??=( {} );
  node[parts.at(-1)]=value;
 }
 return result;
}
function syncOptionFields(form) {
 for(const label of $$('[data-when]',form)) {
  const [key,expected]=label.dataset.when.split('='),input=form.elements.namedItem(key);
  const value=input?.type==='checkbox'?input.checked:input?.value;
  const visible=expected?value===expected:Boolean(value);
  label.hidden=!visible;
  $$('input,select,textarea',label).forEach(control=>control.disabled=!visible);
 }
}
function tlsBehavior(item={}) {
 return `<div class="form-grid tls-behavior">${optionFields(optionSchema.tls.filter(f=>f.key==='insecure'),item,'tls')}</div>`+
  optionSection('More TLS settings',optionSchema.tls.filter(f=>f.key!=='insecure'),item,'tls');
}
