const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const fixture=JSON.parse(execFileSync(process.env.NARA_TEST_PYTHON||'python3',['-c','import json; from nara import options,native; from nara.config import initial_state; print(json.dumps(dict(options=options.schema(),catalog=native.payload(),state=initial_state())))'],{env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
function app(patch={}){
 const dom=new JSDOM('<div id="navigation"></div><div id="crumb"></div><div id="content"></div><span id="sidebar-core"></span><div class="core-label"><span class="status-dot"></span></div><span id="updated"></span><div id="admin-name"></div><div data-admin-avatar></div><dialog id="modal"><div id="modal-body"></div></dialog><div id="toasts"></div>',{runScripts:'outside-only',url:'http://localhost:10000/Test/#clients'}),w=dom.window;
 w.structuredClone=v=>JSON.parse(JSON.stringify(v));w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const source=fs.readFileSync('web/app.js','utf8');
 const scripts=['web/dns-presets.js','web/core-editor.js','web/options.js','web/routing.js','web/dns-rules.js','web/account.js','web/integrations.js','web/clients.js','web/insights.js','web/transfer.js'];
 w.eval(scripts.map(p=>fs.readFileSync(p,'utf8')).join('\n')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.TestApp={setup(value,patch){optionSchema=value.options;coreCatalog=value.catalog;state={...value.state,...patch};dashboard={panel_version:'0.8.0',core:{running:true,version:'sing-box version 1.14.3'},metrics:{hostname:'fixture',platform:'Linux'},totals:{}};CoreSchema.configure(coreCatalog);load=async()=>{};render=()=>{}},traffic(value){dashboard.traffic=value},trafficAllowanceCard,renderTrafficSettings,saveTrafficSettings,trafficChartMarkup,updatePanel,migrationWizard,createPortableBackup,renderTransferSettings,handleInsights,apiRequest:api,PanelRequestError,submitPanelForm,notificationSavedMatches,randomClientName,openClientEditor,createClientsBulk,bulkClientActions,previewClientBulk,changeClientControl,readBulkAction,renderClientsWorkspace,handleClients,renderSettings,panelDate,notificationPreferences,updateSummarySchedule,handleIntegration,renderAccount,renderAbout,updateAdminUI,editAdminCredentials,setup2FA,generate2FA,change2FA,handleAdmin,createAPIKey,renderAPI,renderNotifications,saveTelegram,findTelegramChats,checkTelegramBot,testTelegram,showAPIGuide,updateBanner,inboundTLS,inboundStatus,updateData(value){dashboard.updates=value},loadReal:load,select(ids){selectedClients.clear();for(const id of ids)selectedClients.add(id)},selection(){return [...selectedClients]},keyData(v){apiKeyData=v},telegram(v){telegramData=v},downloadWith(fn){download=fn},apiWith(fn){api=fn},saveWith(fn){saveRecord=fn},renderWith(fn){render=fn},submit(){return modalSubmit($('#modal-form'))}};`);
 w.TestApp.setup(JSON.parse(JSON.stringify(fixture)),patch);
 let saved;w.TestApp.saveWith(async(collection,record)=>{saved={collection,record:JSON.parse(JSON.stringify(record))}});
 const form=()=>w.document.querySelector('#modal-form'),el=name=>form().elements.namedItem(name),plain=v=>JSON.parse(JSON.stringify(v));
 const change=(name,value)=>{const input=el(name);input.value=value;input.dispatchEvent(new w.Event('change',{bubbles:true}));};
 return {w,dom,form,el,change,plain,saved:()=>saved,close(){w.close()}};
}
const inbound={id:'in1',tag:'VPN',type:'vless',enabled:true};
function client(id,name,groups=[],tags=[]){return {id,name,group_ids:groups,tags,inbound_ids:['in1'],enabled:true,quota_bytes:1024};}

test('new client names are ten mixed-case letters and existing names are retained',()=>{const f=app({inbounds:[inbound]});try{const values=new Set();for(let i=0;i<100;i++){const value=f.w.TestApp.randomClientName();assert.match(value,/^[a-zA-Z]{10}$/);assert.match(value,/[a-z]/);assert.match(value,/[A-Z]/);values.add(value);}assert.equal(values.size,100);f.w.TestApp.openClientEditor();assert.match(f.el('name').value,/^[a-zA-Z]{10}$/);f.w.TestApp.openClientEditor(client('id','Existing'));assert.equal(f.el('name').value,'Existing');}finally{f.close()}});
test('individual client editor keeps memberships and tags on save',async()=>{const f=app({inbounds:[inbound],client_groups:[{id:'team',name:'Team'}]});try{f.w.TestApp.openClientEditor(client('id','Existing',['team'],['paid']));f.el('tags').value='paid, vip, paid';await f.w.TestApp.submit();assert.deepEqual(f.saved().record.group_ids,['team']);assert.deepEqual(f.saved().record.tags,['paid','vip']);assert.equal(f.saved().record.id,'id');}finally{f.close()}});
test('bulk creation requires a preview and commits only its opaque ID',async()=>{const f=app({inbounds:[inbound],revision:9});try{let call;f.w.TestApp.apiWith(async(path,body)=>{call={path,body:f.plain(body)};return path==='clients-bulk-preview'?{preview_id:'private-preview',count:2,examples:[{name:'Team-001',quota_bytes:0,enabled:true}]}:{ids:['one','two']}});f.w.TestApp.createClientsBulk();assert.equal(f.form().querySelector('[type=submit]').disabled,true);await assert.rejects(f.w.TestApp.submit(),/Preview/);f.el('count').value='2';f.el('pattern').value='Team-{n:03}';f.el('inbound').checked=true;await f.w.TestApp.previewClientBulk('create');assert.equal(call.body.pattern,'Team-{n:03}');assert.deepEqual(call.body.defaults.inbound_ids,['in1']);assert.equal(f.form().querySelector('[type=submit]').disabled,false);await f.w.TestApp.submit();assert.deepEqual(call,{path:'clients-bulk-create',body:{revision:9,preview_id:'private-preview'}});}finally{f.close()}});
test('editing a prepared batch invalidates the preview before another apply',async()=>{const f=app({inbounds:[inbound]});try{f.w.TestApp.apiWith(async()=>({preview_id:'prepared',count:1,examples:[]}));f.w.TestApp.createClientsBulk();await f.w.TestApp.previewClientBulk('create');f.el('count').value='3';f.el('count').dispatchEvent(new f.w.Event('input',{bubbles:true}));assert.equal(f.form().dataset.previewId,undefined);assert.equal(f.form().querySelector('[type=submit]').disabled,true);await assert.rejects(f.w.TestApp.submit(),/Preview/);}finally{f.close()}});
test('selection spans pages and groups select exactly their own clients',async()=>{const rows=Array.from({length:15},(_,i)=>client('c'+i,'Client'+i,i<4?['team']:[]));const f=app({clients:rows,client_groups:[{id:'team',name:'Team'}]});try{f.w.document.querySelector('#content').innerHTML=f.w.TestApp.renderClientsWorkspace();const select=f.w.document.querySelector('#client-select-page');select.checked=true;f.w.TestApp.changeClientControl(select);assert.equal(f.w.TestApp.selection().length,10);await f.w.TestApp.handleClients('clients-select-filtered',{dataset:{}});assert.equal(f.w.TestApp.selection().length,15);await f.w.TestApp.handleClients('clients-group-action',{dataset:{id:'team'}});assert.deepEqual(f.plain(f.w.TestApp.selection()),['c0','c1','c2','c3']);}finally{f.close()}});
test('changing bulk action excludes hidden values and group clearing stays explicit',async()=>{const f=app({clients:[client('c1','Test')],inbounds:[inbound],client_groups:[{id:'team',name:'Team'}]});try{f.w.TestApp.select(['c1']);f.w.TestApp.bulkClientActions();f.change('operation','quota_add');f.el('amount').value='2';assert.equal(f.w.TestApp.readBulkAction(f.form()).value,2*1024**3);f.change('operation','groups_set');assert.deepEqual(f.plain(f.w.TestApp.readBulkAction(f.form())),{revision:0,ids:['c1'],operation:'groups_set',value:[]});f.change('operation','delete');assert.equal(f.w.TestApp.readBulkAction(f.form()).value,undefined);assert.match(f.w.document.querySelector('#bulk-action-note').textContent,/cannot be undone/);}finally{f.close()}});
test('account page offers avatar suggestions and never renders saved security secrets',()=>{const f=app();try{f.w.TestApp.updateAdminUI({username:'<img src=x>',avatar:'ocean',two_factor:true,recovery_remaining:7});const html=f.w.TestApp.renderAccount();f.w.document.querySelector('#content').innerHTML=html;assert.equal(f.w.document.querySelectorAll('.avatar-choice').length,8);assert.match(f.w.document.querySelector('#content').textContent,/7 recovery codes/);assert.equal(f.w.document.querySelector('img[src=x]'),null);assert.match(html,/admin-credentials/);assert.doesNotMatch(html,/Powered by Sing-box/);}finally{f.close()}});
test('2FA wizard does not enable until setup and confirmation and shows local QR only',async()=>{const f=app();try{let calls=[];f.w.NaraQR={svg:uri=>'<svg aria-label="Subscription QR code"><title>'+uri+'</title></svg>'};f.w.TestApp.apiWith(async(path,body)=>{calls.push(path);return {secret:'FIXTURESECRET',uri:'otpauth://totp/NARA?secret=FIXTURESECRET'}});f.w.TestApp.setup2FA();await assert.rejects(f.w.TestApp.submit(),/Generate and scan/);f.el('current').value='fixture-password';await f.w.TestApp.generate2FA();assert.deepEqual(calls,['admin/2fa/setup']);assert.equal(f.el('totp_code').required,true);assert.ok(f.w.document.querySelector('[aria-label="Authenticator setup QR code"]'));}finally{f.close()}});
test('API defaults to read-only and shows a generated key once',async()=>{const f=app();try{f.w.TestApp.keyData({keys:[],scopes:{read:'Read only','clients:write':'Manage clients'}});f.w.TestApp.createAPIKey();assert.equal(f.el('scope')[0].checked,true);assert.equal(f.el('scope')[1].checked,false);let call;f.w.TestApp.apiWith(async(path,body)=>{call={path,body:f.plain(body)};if(path==='api-keys')return {keys:[],scopes:{}};return {key:'nara_FIXTURE_ONLY',scopes:['read'],expires:Date.now()/1000+3600}});f.el('name').value='Script';f.el('current').value='fixture-password';assert.equal(await f.w.TestApp.submit(),false);assert.match(f.w.document.querySelector('#modal-body').textContent,/nara_FIXTURE_ONLY/);assert.ok(f.w.document.querySelector('#copy-api-key'));}finally{f.close()}});
test('notification preferences include all event categories and preserve blank stored token',async()=>{const f=app();try{f.w.TestApp.telegram({enabled:true,token_configured:true,chat_id:'123',summary_hour:9,events:['login','daily_summary'],event_labels:{login:'Signed in',daily_summary:'Daily summary'},recent:[]});f.w.document.querySelector('#content').innerHTML=f.w.TestApp.renderNotifications();const form=f.w.document.querySelector('#telegram-form');assert.equal(form.elements.bot_token.value,'');assert.ok(f.w.document.querySelector('[data-action=integration-telegram-chats]'));let call;f.w.TestApp.apiWith(async(path,body)=>{call={path,body:f.plain(body)};return {}});f.w.TestApp.saveTelegram(form);assert.equal(f.el('current').required,true);f.el('current').value='fixture-password';await f.w.TestApp.submit();assert.deepEqual([...call.body.settings.events].sort(),['daily_summary','login']);assert.equal(call.body.settings.bot_token,'');}finally{f.close()}});
test('API guide uses placeholders and stable versioned paths',()=>{const f=app();try{f.w.TestApp.showAPIGuide();const text=f.w.document.querySelector('#modal-body').textContent;assert.match(text,/http:\/\/localhost:10000\/Test\/api\/v1\/status/);assert.match(text,/YOUR_API_KEY/);assert.match(text,/CURRENT_REVISION/);assert.match(text,/clients\/bulk\/preview/);}finally{f.close()}});


test('Telegram chat lookup explicitly asks for administrator verification and keeps unsaved preferences',async()=>{const f=app();try{
 f.w.TestApp.updateAdminUI({two_factor:true});f.w.TestApp.telegram({enabled:false,token_configured:false,events:[],event_labels:{},recent:[]});
 f.w.document.querySelector('#content').innerHTML=f.w.TestApp.renderNotifications();const parent=f.w.document.querySelector('#telegram-form');parent.elements.bot_token.value='123456:FIXTURE_TOKEN_ONLY';parent.elements.chat_id.value='before';let calls=[];
 f.w.TestApp.apiWith(async(path,body)=>{calls.push({path,body:f.plain(body)});return {chats:[{id:'123',name:'<img src=x onerror=alert(1)>'}]}});
 f.w.TestApp.findTelegramChats();assert.equal(calls.length,0);assert.equal(f.el('current').required,true);assert.equal(f.el('code').required,true);f.el('current').value='real-admin-password';f.el('code').value='123456';await f.w.TestApp.submit();
 assert.deepEqual(calls,[{path:'telegram/chats',body:{current:'real-admin-password',code:'123456',bot_token:'123456:FIXTURE_TOKEN_ONLY'}}]);assert.equal(parent.elements.chat_id.value,'before');assert.equal(f.w.document.querySelector('#telegram-chats img'),null);assert.ok(f.w.document.querySelector('[data-action=integration-telegram-chat]'));
}finally{f.close()}});
test('Test bot checks a typed token without enabling or saving notifications',async()=>{const f=app();try{
 f.w.TestApp.telegram({enabled:false,token_configured:false,events:[],event_labels:{},recent:[]});f.w.document.querySelector('#content').innerHTML=f.w.TestApp.renderNotifications();const parent=f.w.document.querySelector('#telegram-form');parent.elements.bot_token.value='123456:FIXTURE_TOKEN_ONLY';let calls=[];
 f.w.TestApp.apiWith(async(path,body)=>{calls.push({path,body:f.plain(body)});return {bot:{username:'demo_bot',name:'<b>Demo</b>'}}});assert.ok(parent.querySelector('[data-action=integration-telegram-check]'));
 f.w.TestApp.checkTelegramBot();assert.equal(calls.length,0);f.el('current').value='admin-password';await f.w.TestApp.submit();assert.equal(calls[0].path,'telegram/check');assert.equal(parent.elements.enabled.checked,false);assert.match(f.w.document.querySelector('#telegram-connection').textContent,/@demo_bot/);assert.equal(f.w.document.querySelector('#telegram-connection b b'),null);
}finally{f.close()}});
test('overview combines installed versions and update results in one escaped surface',()=>{const f=app();try{
 f.w.TestApp.keyData({});const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.updateBanner();assert.equal(root.querySelectorAll('.release-overview').length,1);assert.equal(root.querySelectorAll('.release-component').length,2);assert.match(root.textContent,/0.8.0/);assert.match(root.textContent,/1.14.3/);assert.match(root.textContent,/Not checked yet/);assert.equal(root.querySelector('.version-strip'),null);
}finally{f.close()}});


test('silent refresh loads only metrics until the active revision changes',async()=>{const f=app();try{
 let calls=[];f.w.TestApp.apiWith(async path=>{calls.push(path);return {panel_version:'0.8.1',core:{running:true,active_revision:0}}});await f.w.TestApp.loadReal(true);assert.deepEqual(calls,['dashboard']);
 calls=[];f.w.TestApp.apiWith(async path=>{calls.push(path);return path==='dashboard'?{panel_version:'0.8.1',core:{running:true,active_revision:1}}:{...fixture.state,revision:1}});await f.w.TestApp.loadReal(true);assert.deepEqual(calls,['dashboard','state']);
}finally{f.close()}});


test('inbound status distinguishes stopped core, waiting accounts and native TLS',()=>{const f=app({inbounds:[inbound]});try{
 assert.match(f.w.TestApp.inboundStatus(inbound),/Waiting for clients/);assert.match(f.w.TestApp.inboundStatus({...inbound,enabled:false}),/Disabled/);assert.match(f.w.TestApp.inboundStatus({...inbound,mode:'native'}),/Running/);
 assert.match(f.w.TestApp.inboundTLS({mode:'native',config:{tls:{enabled:true,server_name:'vpn.example'}}}),/vpn.example/);assert.doesNotMatch(f.w.TestApp.inboundTLS({mode:'native',config:{tls:{enabled:true}}}),/No TLS/);
}finally{f.close()}});
test('release card shows checking, available and failed checks without claiming success',()=>{const f=app();try{
 f.w.TestApp.updateData({checking:true});assert.match(f.w.TestApp.updateBanner(),/Checking for updates/);
 f.w.TestApp.updateData({panel:{available:true,latest:'9.0.0',url:'https:\/\/example.com'},core:{error:'Offline',known:true}});const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.updateBanner();assert.match(root.textContent,/New version 9.0.0/);assert.match(root.textContent,/Update check unavailable/);assert.match(root.textContent,/Last known result is retained/);
}finally{f.close()}});
test('missing bot token is caught before prompting for the administrator password',()=>{const f=app();try{
 f.w.TestApp.telegram({enabled:false,token_configured:false,events:[],event_labels:{},recent:[]});f.w.document.querySelector('#content').innerHTML=f.w.TestApp.renderNotifications();assert.throws(()=>f.w.TestApp.findTelegramChats(),/Enter a bot token/);assert.throws(()=>f.w.TestApp.checkTelegramBot(),/Enter a bot token/);assert.equal(f.form(),null);
}finally{f.close()}});


test('time zone appears in Settings and controls displayed dates without changing the instant',()=>{const f=app({settings:{...fixture.state.settings,time_zone:'Asia/Tehran'},revision:12});try{
 const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderSettings();const form=root.querySelector('#settings-form');assert.equal(form.dataset.revision,'12');assert.equal(form.elements.time_zone.value,'Asia/Tehran');assert.ok(root.querySelector('select[name=time_zone] option[value="UTC"]'));assert.ok(root.querySelector('[data-action=settings-device-zone]'));
 const instant=Date.parse('2026-10-17T21:00:00Z')/1000;assert.equal(f.w.TestApp.panelDate(instant,{year:'numeric',month:'numeric',day:'numeric'}),'10/18/2026');
}finally{f.close()}});
test('daily summary follows the panel zone and stays editable when switched off',async()=>{const f=app({settings:{...fixture.state.settings,time_zone:'Asia/Tehran'}});try{
 f.w.TestApp.telegram({enabled:false,events:['daily_summary'],event_labels:{},summary_hour:9,summary_minute:15,recent:[]});const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderNotifications();const form=root.querySelector('#telegram-form');assert.match(root.textContent,/Asia\/Tehran/);assert.equal(form.elements.summary_hour.value,'9');assert.equal(form.elements.summary_hour.disabled,false);
 await f.w.TestApp.handleIntegration('integration-events-none',{});assert.equal(form.elements.summary_hour.disabled,false);assert.match(root.querySelector('#summary-schedule-note').textContent,/summary is off/);assert.equal(f.w.TestApp.notificationPreferences(form).summary_hour,9);assert.equal(f.w.TestApp.notificationPreferences(form).summary_minute,15);
 await f.w.TestApp.handleIntegration('integration-events-all',{});assert.equal(form.elements.summary_hour.disabled,false);assert.equal(f.w.TestApp.notificationPreferences(form).events.length,20);
}finally{f.close()}});
test('unsupported browser zone falls back to explicitly labelled UTC instead of breaking page rendering',()=>{const f=app({settings:{...fixture.state.settings,time_zone:'Not/AZone'}});try{assert.match(f.w.TestApp.panelDate(1792281600,{hour:'2-digit',minute:'2-digit'}),/UTC$/);}finally{f.close()}});


test('refreshing Telegram delivery preserves unsaved connection, events and schedule',async()=>{const f=app();try{
 f.w.TestApp.telegram({enabled:false,token_configured:false,events:['daily_summary'],event_labels:{},recent:[]});const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderNotifications();const form=root.querySelector('#telegram-form');form.elements.bot_token.value='unsaved-token';form.elements.chat_id.value='unsaved-chat';form.elements.summary_hour.value='17';form.elements.summary_minute.value='45';
 f.w.TestApp.apiWith(async()=>({delivery:{at:1792281600,ok:true,message:'Delivered fixture'},recent:[]}));await f.w.TestApp.handleIntegration('integration-telegram-activity',{});
 assert.equal(root.querySelector('#telegram-form'),form);assert.equal(form.elements.bot_token.value,'unsaved-token');assert.equal(form.elements.chat_id.value,'unsaved-chat');assert.equal(form.elements.summary_hour.value,'17');assert.equal(form.elements.summary_minute.value,'45');assert.ok(form.querySelector('[value=daily_summary]').checked);assert.match(root.querySelector('.delivery-activity').textContent,/Delivered fixture/);
}finally{f.close()}});


test('API reports empty, malformed and unavailable responses without exposing JSON parser failures',async()=>{const f=app();try{
 for(const response of [{ok:true,status:200,raw:''},{ok:true,status:200,raw:'{"ok":'},{ok:false,status:502,raw:'<html>PRIVATE_PROXY_ERROR</html>'}]){
  f.w.fetch=async()=>({...response,text:async()=>response.raw});
  await assert.rejects(f.w.TestApp.apiRequest('telegram',{}),error=>error.uncertain===true&&!/Unexpected|JSON|PRIVATE_PROXY/.test(error.message));
 }
 f.w.fetch=async()=>({ok:false,status:400,text:async()=>JSON.stringify({error:'Current password is incorrect'})});
 await assert.rejects(f.w.TestApp.apiRequest('telegram',{}),/Current password is incorrect/);
}finally{f.close()}});
test('API deadlines cover a stalled response body and never retry a write',async()=>{const f=app();try{
 let calls=0;f.w.fetch=async(url,options)=>{calls++;return {ok:true,status:200,text:()=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('aborted'))))}};
 await assert.rejects(f.w.TestApp.apiRequest('telegram',{}, {timeoutMs:15}),error=>error.uncertain&&/in time/.test(error.message));assert.equal(calls,1);
}finally{f.close()}});
test('clear and select-all saves recover a committed empty response using a read only',async()=>{const f=app();try{
 const saved={enabled:false,token_configured:true,chat_id:'123',summary_hour:9,summary_minute:0,events:[],event_labels:{},recent:[]};f.w.TestApp.telegram(saved);const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderNotifications();const form=root.querySelector('#telegram-form');await f.w.TestApp.handleIntegration('integration-events-all',{});let calls=[];
 f.w.TestApp.apiWith(async(path,body)=>{calls.push({path,body});if(body){saved.events=[...body.settings.events];throw new f.w.TestApp.PanelRequestError('Incomplete response',true)}return saved});
 f.w.TestApp.saveTelegram(form);assert.ok(f.w.document.querySelector('#modal').classList.contains('verification-dialog'));assert.match(f.w.document.querySelector('.verification-review').textContent,/20 selected/);f.el('current').value='fixture-password';await f.w.TestApp.submit();assert.equal(calls.filter(x=>x.body).length,1);assert.equal(calls.filter(x=>!x.body).length,1);assert.equal(saved.events.length,20);assert.match(root.ownerDocument.querySelector('#toasts').textContent,/confirmed after reconnecting/);
}finally{f.close()}});
test('token replacements and mismatching saved settings are never guessed or posted again',async()=>{for(const replacement of [false,true]){const f=app();try{
 f.w.TestApp.telegram({enabled:false,token_configured:true,chat_id:'123',summary_hour:9,events:[],event_labels:{},recent:[]});const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderNotifications();const form=root.querySelector('#telegram-form');await f.w.TestApp.handleIntegration('integration-events-all',{});if(replacement)form.elements.bot_token.value='NEW_PRIVATE_TOKEN';let writes=0,reads=0;
 f.w.TestApp.apiWith(async(path,body)=>{if(body){writes++;throw new f.w.TestApp.PanelRequestError('Incomplete response',true)}reads++;return {enabled:false,chat_id:'123',events:[],summary_hour:9,summary_minute:0}});f.w.TestApp.saveTelegram(form);f.el('current').value='fixture-password';await assert.rejects(f.w.TestApp.submit(),/Incomplete/);assert.equal(writes,1);assert.equal(reads,replacement?0:1);
}finally{f.close()}}});
test('verification unlocks after failure, clears secrets and prevents duplicate submissions',async()=>{const f=app();try{
 f.w.TestApp.telegram({enabled:false,events:[],event_labels:{},recent:[]});const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderNotifications();f.w.TestApp.saveTelegram(root.querySelector('#telegram-form'));const form=f.form();f.el('current').value='fixture-password';let rejectRequest,calls=0;
 f.w.TestApp.apiWith(()=>{calls++;return new Promise((resolve,reject)=>rejectRequest=reject)});
 const event={target:form,preventDefault(){}};const pending=f.w.TestApp.submitPanelForm(event);assert.equal(form.getAttribute('aria-busy'),'true');assert.equal(form.querySelector('[type=submit]').disabled,true);assert.match(form.textContent,/Checking your password/);await f.w.TestApp.submitPanelForm(event);assert.equal(calls,1);
 rejectRequest(Error('Current password is incorrect'));await pending;assert.equal(form.hasAttribute('aria-busy'),false);assert.equal(form.querySelector('[type=submit]').disabled,false);assert.equal(form.elements.current.value,'');assert.match(form.querySelector('#form-error').textContent,/Current password/);assert.equal(form.dataset.submitting,undefined);
 await f.w.TestApp.handleIntegration('integration-password-visibility',form.querySelector('[data-action=integration-password-visibility]'));assert.equal(form.elements.current.type,'text');assert.equal(form.querySelector('[aria-label="Hide password"]').getAttribute('aria-pressed'),'true');
}finally{f.close()}});
test('finishing an older confirmation cannot close a newly opened dialog',async()=>{const f=app();try{
 f.w.TestApp.telegram({enabled:false,events:[],event_labels:{},recent:[]});const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderNotifications();f.w.TestApp.saveTelegram(root.querySelector('#telegram-form'));let resolveRequest;f.w.TestApp.apiWith(()=>new Promise(resolve=>resolveRequest=resolve));const old=f.form();old.elements.current.value='fixture-password';const pending=f.w.TestApp.submitPanelForm({target:old,preventDefault(){}});f.w.TestApp.editAdminCredentials();const replacement=f.form();resolveRequest({ok:true});await pending;assert.equal(f.form(),replacement);assert.equal(f.w.document.querySelector('#modal').open,true);
}finally{f.close()}});


test('summary hour and minute can change and persist while the daily event is off',async()=>{const f=app();try{
 const saved={enabled:false,token_configured:false,events:[],event_labels:{},summary_hour:4,summary_minute:0,recent:[]};f.w.TestApp.telegram(saved);const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderNotifications();const form=root.querySelector('#telegram-form');assert.equal(form.elements.summary_hour.disabled,false);assert.equal(form.elements.summary_minute.disabled,false);form.elements.summary_hour.value='18';form.elements.summary_minute.value='35';f.w.TestApp.updateSummarySchedule();assert.match(root.querySelector('#summary-clock-preview').textContent,/18:35/);
 let body;f.w.TestApp.apiWith(async(path,data)=>{body=f.plain(data);return {ok:true}});f.w.TestApp.saveTelegram(form);f.el('current').value='fixture-password';await f.w.TestApp.submit();assert.equal(body.settings.summary_hour,18);assert.equal(body.settings.summary_minute,35);assert.deepEqual(body.settings.events,[]);
 root.innerHTML=f.w.TestApp.renderNotifications();const reloaded=root.querySelector('#telegram-form');assert.equal(reloaded.elements.summary_hour.value,'18');assert.equal(reloaded.elements.summary_minute.value,'35');assert.equal(reloaded.querySelector('[value=daily_summary]').checked,false);assert.match(root.textContent,/24-hour/);
}finally{f.close()}});

test('an empty initial session response opens sign-in without a misleading expired-session warning',async()=>{const f=app();try{
 f.w.document.body.insertAdjacentHTML('afterbegin','<div id="login" hidden></div><div id="app"></div><p id="login-error"></p>');f.w.fetch=async()=>({ok:false,status:401,text:async()=>''});await assert.rejects(f.w.TestApp.apiRequest('session'),/Please sign in first/);assert.equal(f.w.document.querySelector('#login').hidden,false);assert.equal(f.w.document.querySelector('#app').hidden,true);
}finally{f.close()}});

test('usage settings expose separate billing and display resets with a compact native time zone dropdown',()=>{const f=app();try{
 f.w.TestApp.traffic({settings:{monthly_bytes:1024**4,reset_day:18,interface:'',count:'both',traffic_percent:80,cpu_percent:90,memory_percent:90,disk_percent:90,bandwidth_mbps:100,duration_minutes:5},interfaces:['eth0'],interface:'eth0',available:true,cycle:{used:1024**3,start:1790000000,end:1793000000,since:1790000000},panel_bytes:999});
 const root=f.w.document.querySelector('#content');root.innerHTML=f.w.TestApp.renderSettings();
 assert.equal(root.querySelector('[name=time_zone]').tagName,'SELECT');assert.equal(root.querySelector('datalist'),null);
 assert.ok(root.querySelector('[data-action=insights-reset-cycle]'));assert.ok(root.querySelector('[data-action=insights-reset-panel]'));
 assert.match(root.textContent,/Client quota usage|client quota usage/);assert.ok(root.querySelector('#traffic-settings-form'));
}finally{f.close()}});
test('traffic save submits numeric policy without changing core settings',async()=>{const f=app();try{
 f.w.TestApp.traffic({settings:{monthly_bytes:0,reset_day:1,interface:'',count:'both',traffic_percent:80,cpu_percent:90,memory_percent:90,disk_percent:90,bandwidth_mbps:0,duration_minutes:5},interfaces:[],cycle:{used:0,start:1790000000,end:1793000000,since:1790000000},panel_bytes:0});
 f.w.document.querySelector('#content').innerHTML=f.w.TestApp.renderTrafficSettings();const form=f.w.document.querySelector('#traffic-settings-form');form.elements.monthly_gib.value='2048';form.elements.cpu_percent.value='85';form.elements.bandwidth_mbps.value='2.5';let call;
 f.w.TestApp.apiWith(async(path,body)=>{call={path,body};return {ok:true}});await f.w.TestApp.submitPanelForm({target:form,preventDefault(){}});
 assert.equal(call.path,'traffic/settings');assert.equal(call.body.settings.monthly_bytes,2*1024**4);assert.equal(call.body.settings.cpu_percent,85);assert.equal(call.body.settings.bandwidth_mbps,2.5);assert.equal(form.dataset.submitting,undefined);
}finally{f.close()}});
test('clicking update only opens verified backup confirmation and does not queue an update',()=>{const f=app();try{
 let calls=0;f.w.TestApp.apiWith(async()=>{calls++;throw Error('Must not request an update before confirmation')});f.w.TestApp.updatePanel('9.0.0');
 assert.equal(calls,0);assert.match(f.form().textContent,/Confirm update to NARA 9.0.0/);assert.match(f.form().textContent,/\/var\/backups\/nara-panel/);assert.match(f.form().textContent,/Download backup/);assert.ok(f.form().elements.current.required);
}finally{f.close()}});
test('history charts show observed upload/download totals and never invent a pre-recording series',()=>{const f=app();try{
 assert.match(f.w.TestApp.trafficChartMarkup({points:[],recording_since:null}),/No recorded history/);
 const markup=f.w.TestApp.trafficChartMarkup({recording_since:1790000000,start:1790000000,end:1790000300,points:[{at:1790000000,upload:1024,download:2048}]});
 assert.match(markup,/1.0 KiB/);assert.match(markup,/2.0 KiB/);assert.match(markup,/<svg/);assert.doesNotMatch(markup,/<script|https:\/\//);
}finally{f.close()}});
test('preparing an update downloads a backup before showing its final confirmation',async()=>{const f=app();try{
 const order=[];f.w.TestApp.apiWith(async(path)=>{order.push(path);return {proof:'fixture-proof',filename:'nara-fixture.json',path:'/private/backups/nara-fixture.json',backup:{format:'nara-portable',schema:1}}});
 f.w.TestApp.downloadWith((filename)=>order.push('download:'+filename));
 f.w.TestApp.updatePanel('9.0.0');f.el('current').value='fixture-password';await f.w.TestApp.submit();
 assert.deepEqual(order,['backup/create','download:nara-fixture.json']);assert.match(f.form().textContent,/Backup ready/);assert.match(f.form().textContent,/\/private\/backups\/nara-fixture.json/);assert.ok(f.el('backup_saved').required);
 await assert.rejects(f.w.TestApp.submit(),/Save your backup/);assert.equal(order.length,2);
}finally{f.close()}});
test('migration private key fields disable browser spelling and completion services',()=>{const f=app();try{
 Object.defineProperty(f.w,'isSecureContext',{value:true,configurable:true});f.w.TestApp.migrationWizard();assert.equal(f.el('ssh_key').autocomplete,'off');assert.equal(f.el('ssh_key').spellcheck,false);assert.equal(f.el('ssh_password').autocomplete,'off');assert.match(f.form().textContent,/fresh Debian/);
}finally{f.close()}});
