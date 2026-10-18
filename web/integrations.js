'use strict';
let apiKeyData=null,telegramData=null;
const integrationLoading=new Set();
function integrationLoad(kind,force=false){
 if(integrationLoading.has(kind))return;
 if(!force&&(kind==='api'?apiKeyData:telegramData))return;
 integrationLoading.add(kind);const session=csrf;
 api(kind==='api'?'api-keys':'telegram').then(value=>{if(session!==csrf)return;if(kind==='api')apiKeyData=value;else telegramData=value;}).catch(error=>{if(session!==csrf)return;if(kind==='api')apiKeyData={keys:[],scopes:{},error:error.message};else telegramData={error:error.message};}).finally(()=>{integrationLoading.delete(kind);if(session===csrf&&page===(kind==='api'?'api':'notifications'))render();});
}
function renderAPI(){
 if(!apiKeyData){integrationLoad('api');return heading()+'<p class="note">Loading API access…</p>';}
 const base=new URL('api/v1/',location.href.split('#')[0]).href;
 return heading(btn('Create API key','integration-key-new','key','primary'))+`<section class="card"><div class="card-header"><div><h2>Connect another program to NARA</h2><p>An API lets scripts or other apps manage this panel without using the browser.</p></div>${icon('code')}</div><div class="card-body"><ol class="api-steps"><li>Create a key with only the permissions your program needs.</li><li>Copy it once and store it privately. Keys can be revoked at any time.</li><li>Send requests to this address with the key in the Authorization header.</li></ol><code class="secret-output">${e(base)}</code><p class="note">Use HTTPS for remote automation. A key is a credential: do not put it in a URL or share it with clients.</p><div class="inline-buttons">${btn('API guide & examples','integration-api-guide','code')}${btn('Download OpenAPI','integration-openapi','download')}${btn('Refresh','integration-api-refresh','refresh')}</div>${apiKeyData.error?`<p class="error-text">${e(apiKeyData.error)}</p>`:''}</div></section><section class="card section-gap"><div class="card-header"><div><h2>Your API keys</h2><p>Only the key name and access details remain visible after creation.</p></div></div>${apiKeyData.keys.length?`<div class="table-wrap"><table><thead><tr><th>Name</th><th>Permissions</th><th>Expires</th><th>Last used</th><th>Status</th><th></th></tr></thead><tbody>${apiKeyData.keys.map(row=>`<tr><td><b>${e(row.name)}</b></td><td>${row.scopes.map(scope=>badge(scope,'blue')).join(' ')}</td><td>${date(row.expires)}</td><td>${row.last_used?e(date(row.last_used))+' · '+e(time(row.last_used)):'Never'}</td><td>${badge(row.revoked?'Revoked':row.expires<=Date.now()/1000?'Expired':'Active',row.revoked?'':row.expires<=Date.now()/1000?'orange':'green')}</td><td>${row.revoked?'':rowBtn('Revoke API key','integration-key-revoke','trash',row.id)}</td></tr>`).join('')}</tbody></table></div>`:empty('No API keys yet','Create a read-only key to start exploring your panel API.','integration-key-new','Create API key','key')}</section>`;
}
function createAPIKey(){
 openModal('Create API key','The complete key is shown once after creation.',`<div class="form-grid">${field('Key name','name','','text','For example: billing integration or server dashboard.')}${selectField('Expires after','days',[[7,'7 days'],[30,'30 days'],[90,'90 days'],[365,'365 days']],90)}</div><fieldset class="route-scope"><legend>Permissions</legend>${Object.entries(apiKeyData.scopes).map(([scope,label])=>`<label class="check-field"><input type="checkbox" name="scope" value="${e(scope)}" ${checked(scope==='read')}><span><b>${e(scope)}</b><small class="field-hint">${e(label)}</small></span></label>`).join('')}</fieldset>${adminReauth()}`,async form=>{
  const f=new FormData(form),result=await api('api-keys/create',{...Object.fromEntries(f),scopes:f.getAll('scope'),days:Number(f.get('days'))});integrationLoad('api',true);
  openModal('Copy your API key','This is the only time the complete key is shown.',`<div class="hint-box">Save this key privately. Anyone holding it has the selected permissions until it expires or is revoked.</div><pre class="secret-output">${e(result.key)}</pre><button type="button" class="btn" id="copy-api-key">${icon('key')}Copy key</button><p class="note">${e(result.scopes.join(' · '))} · Expires ${date(result.expires)}</p>`);
  $('#copy-api-key').onclick=async()=>{await navigator.clipboard.writeText(result.key);toast('API key copied.');};return false;
 });requireAdminInputs($('#modal-form'));$('#modal-form').elements.name.required=true;
}
function revokeAPIKey(id){
 const row=apiKeyData.keys.find(key=>key.id===id);openModal('Revoke API key',e(row?.name||''),'<p>Programs using this key will lose access immediately.</p>'+adminReauth(),async form=>{await api('api-keys/revoke',{...Object.fromEntries(new FormData(form)),id});integrationLoad('api',true);toast('API key revoked.');},'Revoke key');requireAdminInputs($('#modal-form'));
}
function showAPIGuide(){
 const base=new URL('api/v1/',location.href.split('#')[0]).href;
 const curl=`curl -H 'Authorization: Bearer YOUR_API_KEY' '${base}status'`;
 const create=`curl -X POST '${base}clients' \\\n  -H 'Authorization: Bearer YOUR_API_KEY' \\\n  -H 'Content-Type: application/json' \\\n  -H 'If-Match: CURRENT_REVISION' \\\n  -d '{"inbound_ids":["INBOUND_ID"],"quota_bytes":10737418240}'`;
 openModal('API guide','Start with a read-only key and a status request.',`<h3>1. Read panel status</h3><pre class="secret-output">${e(curl)}</pre><p class="note">Replace YOUR_API_KEY with your private key. The response includes the current revision.</p><h3>2. Read or manage resources</h3><div class="table-wrap"><table><thead><tr><th>Endpoint</th><th>Purpose</th></tr></thead><tbody>${[['clients','Client accounts'],['groups','Client groups'],['inbounds','Inbound connections'],['tls','Certificates'],['dns/servers','DNS resolvers'],['dns/rules','DNS rules'],['routing/rules','Traffic rules'],['outbounds','Destinations'],['endpoints','WireGuard / WARP endpoints'],['rule-sets','Shared lists'],['settings','Connection settings'],['stats','Server metrics and usage'],['core/status','Core status'],['core/options/{section}','Core settings'],['clients/bulk','Bulk client creation'],['clients/actions','Bulk client actions']].map(([path,description])=>`<tr><td><code>${e(path)}</code></td><td>${description}</td></tr>`).join('')}</tbody></table></div><p class="note">GET reads; POST creates; PATCH changes; DELETE removes. Lists support limit/offset. Client lists also support search, group, tag and status. Use Download OpenAPI for every endpoint.</p><h3>3. Example: create a client</h3><pre class="secret-output">${e(create)}</pre><p class="note">Read /state first to find inbound IDs and the revision. A blank name generates ten mixed-case letters. Writes validate and apply automatically. If another change has happened, HTTP 409 asks your program to read the latest revision.</p><h3>Bulk naming</h3><pre class="secret-output">${e(JSON.stringify({revision:12,count:20,pattern:'Team-{n:03}',start:1,defaults:{inbound_ids:['INBOUND_ID'],quota_bytes:10737418240,group_ids:['GROUP_ID']}},null,2))}</pre><p class="note">POST this shape to clients/bulk/preview, inspect the result, then POST its preview_id and the same revision to clients/bulk. Direct creation without a preview is also supported. Templates accept {n}, {n:03}, {random} and {group}.</p><p class="note">API keys cannot change administrator credentials, 2FA, Telegram credentials or other API keys. Those actions require a browser session and current-password verification.</p>`);
}
function renderNotifications(){
 if(!telegramData){integrationLoad('telegram');return heading()+'<p class="note">Loading notification settings…</p>';}
 const t=telegramData;
 if(t.error)return heading()+`<p class="error-text">${e(t.error)}</p>`+btn('Retry','integration-telegram-refresh','refresh');
 const categories=[
  ['Service & security',['panel_started','core_up','core_down','login','login_failed','admin_changed','api_key','config_saved','apply_failed']],
  ['Clients & traffic',['clients_created','clients_updated','clients_deleted','quota_warning','quota_reached','expiry_warning','expired']],
  ['Server & summaries',['resource_alert','resource_recovery','daily_summary']]
 ];
 return heading(btn('Send test message','integration-telegram-test','check','',t.enabled?'':'disabled'))+`
 <section class="card notification-setup">
  <div class="card-header"><div><h2>Connect your Telegram bot</h2><p>Set up the connection, then choose which updates to receive.</p></div>${badge(t.enabled?'Enabled':'Not enabled',t.enabled?'green':'')}</div>
  <div class="card-body"><details class="setup-help"><summary>How to get a bot token and Chat ID</summary><ol class="api-steps"><li>Create a bot with <a class="text-link" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">@BotFather</a> and copy its token.</li><li>Start your bot in Telegram, then use Find recent bot chats to choose a destination. For a channel, give the bot permission to post.</li><li>Enable notifications, save your choices and send a test message.</li></ol></details></div>
 </section>
 <section class="card section-gap">
  <div class="card-header"><div><h2>Notification preferences</h2><p>Saved only after administrator verification</p></div></div>
  <form id="telegram-form" class="card-body">
   <div class="form-grid">${field('Bot token','bot_token','','password',t.token_configured?'A token is stored. Leave blank to keep it.':'Paste the token from BotFather.')}${field('Chat ID or @channel','chat_id',t.chat_id||'','text','Find your private/group Chat ID below, or enter a channel username.')}</div>
   <div class="inline-buttons notification-tools"><button type="button" class="btn" data-action="integration-telegram-check">${icon('check')}Test bot</button><button type="button" class="btn" data-action="integration-telegram-chats">${icon('clients')}Find recent bot chats</button></div>
   <p class="note">These buttons use the token above, or the saved token when blank. Each asks for your current NARA administrator password${adminProfile.two_factor?' and a fresh verification code':''} in a separate window.</p>
   <div id="telegram-connection" role="status"></div><div id="telegram-chats"></div>
   <div class="notification-schedule"><label class="check-field"><input name="enabled" type="checkbox" ${checked(t.enabled)}>Enable Telegram notifications</label>${selectField('Daily summary time (UTC)','summary_hour',Array.from({length:24},(_,hour)=>[hour,String(hour).padStart(2,'0')+':00 UTC']),t.summary_hour??9)}</div>
   <div class="notification-groups">${categories.map(([title,events])=>`<fieldset class="route-scope"><legend>${title}</legend>${events.map(event=>`<label class="check-field"><input name="event" type="checkbox" value="${event}" ${checked(t.events?.includes(event))}>${e(t.event_labels[event]||event)}</label>`).join('')}</fieldset>`).join('')}</div>
   <p class="note">Quota alerts begin at 80%; expiry alerts begin 24 hours before expiry. Resource alerts require sustained usage at or above 90%. Messages exclude passwords, API keys, private keys and subscription links.</p>
   <div class="form-save-bar"><p>Saving requires your current administrator password${adminProfile.two_factor?' and a fresh verification code':''}.</p><button class="btn primary" type="submit">${icon('check')}Save notifications</button></div>
  </form>
 </section>
 <section class="card section-gap"><div class="card-header"><div><h2>Delivery status</h2><p>Queued messages and recent attempts</p></div>${btn('Refresh','integration-telegram-refresh','refresh','sm')}</div><div class="card-body">
  ${t.delivery?.at?`<p>${badge(t.delivery.ok?'Delivered':'Needs attention',t.delivery.ok?'green':'orange')} ${e(t.delivery.message)} · ${e(time(t.delivery.at))}</p>`:'<p class="note">No delivery attempts yet. Save and enable notifications to send a test message.</p>'}
  <p class="note">Temporary failures retry automatically. Notifications cannot report a complete server/panel outage while this panel is offline.</p>
  ${t.recent?.length?`<div class="table-wrap"><table><thead><tr><th>Event</th><th>Time</th><th>Status</th></tr></thead><tbody>${t.recent.map(row=>`<tr><td>${e(t.event_labels[row.event]||'Test notification')}</td><td>${e(time(row.created))}</td><td>${badge(row.status,row.status==='sent'?'green':row.status==='failed'?'red':'')}</td></tr>`).join('')}</tbody></table></div>`:''}
 </div></section>`;
}
function notificationPreferences(form){
 const f=new FormData(form);
 return {enabled:form.elements.enabled.checked,bot_token:String(f.get('bot_token')||'').trim(),chat_id:String(f.get('chat_id')||'').trim(),events:f.getAll('event'),summary_hour:Number(f.get('summary_hour'))};
}
function notificationVerification(title,description,run,label){
 openModal(title,description,`<p class="note">Enter your current NARA administrator password. This is the password you use to sign in to this panel.</p>${adminReauth()}`,run,label);
 requireAdminInputs($('#modal-form'));
}
function saveTelegram(form){
 const settings=notificationPreferences(form);
 notificationVerification('Save notification preferences','Confirm the bot destination and event choices.',async auth=>{
  await api('telegram',{...Object.fromEntries(new FormData(auth)),settings});
  integrationLoad('telegram',true);toast('Notification preferences saved.');
 },'Save notifications');
}
function testTelegram(){
 notificationVerification('Send a test message','Queues a message to your saved Telegram destination.',async form=>{
  await api('telegram/test',Object.fromEntries(new FormData(form)));
  toast('Test message queued. Refresh delivery status shortly.');integrationLoad('telegram',true);
 },'Send test message');
}
function notificationToken(form){
 const token=String(form.elements.bot_token.value||'').trim();
 if(!token&&!telegramData?.token_configured)throw Error('Enter a bot token first.');
 return token;
}
function checkTelegramBot(){
 const parent=$('#telegram-form'),token=notificationToken(parent);
 notificationVerification('Test bot connection','Checks the bot token with Telegram. No message is sent and your preferences are not saved.',async form=>{
  const result=await api('telegram/check',{...Object.fromEntries(new FormData(form)),bot_token:token});
  if(parent.isConnected)$('#telegram-connection').innerHTML=`<div class="hint-box success">${icon('check')}Connected to <b>@${e(result.bot.username)}</b>${result.bot.name?' · '+e(result.bot.name):''}</div>`;
  toast('Bot connection verified.');
 },'Test bot');
}
async function handleIntegration(action,target){
 if(action==='integration-key-new')return createAPIKey();
 if(action==='integration-key-revoke')return revokeAPIKey(target.dataset.id);
 if(action==='integration-api-guide')return showAPIGuide();
 if(action==='integration-openapi'){download('nara-openapi.json',await api('openapi'));return;}
 if(action==='integration-api-refresh')return integrationLoad('api',true);
 if(action==='integration-telegram-refresh')return integrationLoad('telegram',true);
 if(action==='integration-telegram-chats')return findTelegramChats();
 if(action==='integration-telegram-check')return checkTelegramBot();
 if(action==='integration-telegram-chat'){const form=$('#telegram-form');form.elements.chat_id.value=target.dataset.id;toast('Chat selected. Save your notification preferences.');return;}
 if(action==='integration-telegram-test')return testTelegram();
}

function findTelegramChats(){
 const parent=$('#telegram-form'),token=notificationToken(parent);
 notificationVerification('Find recent bot chats','Reads recent chat IDs from your bot. Start the bot in Telegram first. Your preferences are not saved.',async form=>{
  const result=await api('telegram/chats',{...Object.fromEntries(new FormData(form)),bot_token:token});
  if(!parent.isConnected)return;
  $('#telegram-chats').innerHTML=result.chats.length?`<div class="hint-box">Choose a destination, then save preferences.</div><div class="inline-buttons section-gap">${result.chats.map(chat=>btn(e(chat.name)+' · '+e(chat.id),'integration-telegram-chat','clients','sm',`data-id="${e(chat.id)}"`)).join('')}</div>`:'<p class="note">No recent chats found. Send a message to your bot in Telegram, then try again. You can also enter a Chat ID manually.</p>';
 },'Find chats');
}
