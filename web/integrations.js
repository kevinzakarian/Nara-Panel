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
 if(!clientDeliveryData)loadClientDelivery();
 if(!telegramData){integrationLoad('telegram');return heading()+'<p class="note">Loading notification settings…</p>';}
 const t=telegramData;
 if(t.error)return heading()+`<p class="error-text">${e(t.error)}</p>`+btn('Retry','integration-telegram-refresh','refresh');
 const categories=[
  ['Service & security',['panel_started','core_up','core_down','login','login_failed','admin_changed','api_key','config_saved','apply_failed']],
  ['Clients & traffic',['clients_created','clients_updated','clients_deleted','quota_warning','quota_reached','expiry_warning','expired']],
  ['Server health',['server_traffic_warning','resource_alert','resource_recovery']]
 ];
 const zone=panelTimeZone();
 return heading(btn('Send test message','integration-telegram-test','check','',t.enabled?'':'disabled'))+`
 <div class="management-layout notifications-layout"><div class="management-stack"><form id="telegram-form" class="management-stack" data-time-zone="${e(zone)}">
  <section class="card"><div class="card-header"><div><span class="section-kicker">01 / CONNECTION</span><h2>Your Telegram bot</h2><p>Choose the bot and chat that receive your updates</p></div>${badge(t.enabled?'Enabled':'Not enabled',t.enabled?'green':'')}</div><div class="card-body preference-fields">
   <details class="setup-help mobile-setup-help"><summary>Need help connecting your bot?</summary><ol class="api-steps"><li>Create a bot with <a class="text-link" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">@BotFather</a> and copy its token.</li><li>Start your bot, then use Find recent bot chats. For a channel, give the bot permission to post.</li><li>Enable notifications, save your choices and send a test message.</li></ol></details>
   <label class="notification-enable check-field"><input name="enabled" type="checkbox" ${checked(t.enabled)}><span><b>Enable Telegram notifications</b><small>Delivery starts after you save your preferences.</small></span></label>
   <div class="form-grid">${field('Bot token','bot_token','','password',t.token_configured?'A token is stored. Leave blank to keep it.':'Paste the token from BotFather.')}${field('Chat ID or @channel','chat_id',t.chat_id||'','text','Your private/group Chat ID or channel username.')}</div>
   <div class="inline-buttons notification-tools"><button type="button" class="btn" data-action="integration-telegram-check">${icon('check')}Test bot</button><button type="button" class="btn" data-action="integration-telegram-chats">${icon('clients')}Find recent bot chats</button><button type="button" class="btn" data-action="delivery-scroll-bot">Client bot commands ↓</button></div>
   <p class="note">Use the token above or the saved token when blank. Each check asks for your current NARA administrator password${adminProfile.two_factor?' and a fresh verification code':''}.</p><div id="telegram-connection" role="status"></div><div id="telegram-chats"></div>
  </div></section>
  <section class="card"><div class="card-header"><div><span class="section-kicker">02 / SCHEDULE</span><h2>Daily summary</h2><p>Your server, clients and traffic in one message</p></div>${icon('clock')}</div><div class="card-body preference-fields"><label class="check-field summary-enable"><input name="event" type="checkbox" value="daily_summary" ${checked(t.events?.includes('daily_summary'))}><span><b>Send a daily summary</b><small class="field-hint">Include a daily overview in your Telegram notifications.</small></span></label><div class="form-grid"><fieldset class="summary-clock"><legend>Daily summary time · 24-hour</legend><div>${selectField('Hour','summary_hour',Array.from({length:24},(_,value)=>[value,String(value).padStart(2,'0')]),t.summary_hour??9)}<span aria-hidden="true">:</span>${selectField('Minute','summary_minute',Array.from({length:60},(_,value)=>[value,String(value).padStart(2,'0')]),t.summary_minute??0)}</div><small class="field-hint" id="summary-clock-preview">${String(t.summary_hour??9).padStart(2,'0')}:${String(t.summary_minute??0).padStart(2,'0')} · ${e(zone)}</small></fieldset><div class="schedule-zone"><span class="section-kicker">PANEL TIME ZONE</span><b>${e(zone)}</b><a class="text-link" href="#settings">Change in Settings →</a></div></div><p class="note" id="summary-schedule-note">${t.events?.includes('daily_summary')?'Sent once per local day at or shortly after your chosen time. If the panel was offline, it catches up later that day.':'Daily summary is off. Your chosen time is saved for when you enable it.'}</p></div></section>
  <section class="card"><div class="card-header"><div><span class="section-kicker">03 / EVENTS</span><h2>What would you like to hear about?</h2><p>Choose the updates that matter to you</p></div><div class="inline-buttons">${btn('Select all','integration-events-all','check','sm','type="button"')}${btn('Clear','integration-events-none','close','sm','type="button"')}</div></div><div class="card-body"><div class="notification-groups">${categories.map(([title,events])=>`<fieldset class="route-scope"><legend>${title}</legend>${events.map(event=>`<label class="check-field"><input name="event" type="checkbox" value="${event}" ${checked(t.events?.includes(event))}>${e(event==='daily_summary'?'Daily summary':t.event_labels[event]||event)}</label>`).join('')}</fieldset>`).join('')}</div><p class="note">Client traffic warnings start at 80%; expiry warnings start 24 hours before expiry. Configure server traffic and sustained resource thresholds in the Server health box on this page.</p></div></section>
  <div class="settings-save"><span>${icon('lock')}Saving requires administrator verification.</span><button class="btn primary" type="submit">${icon('check')}Save notifications</button></div>
 </form>${renderAlertThresholds()}</div><aside class="management-stack" aria-label="Telegram setup and delivery">
 ${renderClientBot()}
  <section class="card telegram-help-card"><div class="card-header"><h2>Getting connected</h2>${icon('notifications')}</div><div class="card-body"><ol class="connection-steps"><li><b>Create your bot</b><p>Open <a class="text-link" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">@BotFather</a> in Telegram and copy its token.</p></li><li><b>Choose a chat</b><p>Start your bot, then find recent bot chats. For a channel, give the bot permission to post.</p></li><li><b>Save & test</b><p>Enable notifications, save your choices, then send a test message.</p></li></ol><p class="note">Messages exclude passwords, API keys, private keys and subscription links.</p></div></section>
  <section class="card"><div class="card-header"><div><h2>Delivery activity</h2><p>Recent messages · ${e(zone)}</p></div>${btn('Refresh','integration-telegram-activity','refresh','sm')}</div><div class="card-body delivery-activity">
   ${telegramActivity(t)}
  </div></section>
 </aside></div>`;
}
function telegramActivity(t){return `   ${t.delivery?.at?`<div class="delivery-last">${badge(t.delivery.ok?'Delivered':'Needs attention',t.delivery.ok?'green':'orange')}<p>${e(t.delivery.message)}</p><small>${e(date(t.delivery.at))} · ${e(time(t.delivery.at))}</small></div>`:'<p class="note">No delivery attempts yet. Save and enable notifications to send a test message.</p>'}
   ${t.recent?.length?`<ul class="delivery-list">${t.recent.map(row=>`<li><div><b>${e(t.event_labels[row.event]||'Test notification')}</b><small>${e(date(row.created))} · ${e(time(row.created))}</small></div>${badge(row.status,row.status==='sent'?'green':row.status==='failed'?'red':'')}</li>`).join('')}</ul>`:''}
   <p class="note">Temporary failures retry automatically. A complete outage can only be reported once the panel is back online.</p>`;}
function notificationPreferences(form){
 const f=new FormData(form),hour=Number(f.get('summary_hour')),minute=Number(f.get('summary_minute'));
 return {enabled:form.elements.enabled.checked,bot_token:String(f.get('bot_token')||'').trim(),chat_id:String(f.get('chat_id')||'').trim(),events:f.getAll('event'),summary_hour:hour,summary_minute:minute};
}
function updateSummarySchedule(){
 const form=$('#telegram-form');if(!form)return;
 const enabled=[...form.querySelectorAll('[name=event]')].some(input=>input.value==='daily_summary'&&input.checked);
 $('#summary-clock-preview').textContent=String(form.elements.summary_hour.value).padStart(2,'0')+':'+String(form.elements.summary_minute.value).padStart(2,'0')+' · '+form.dataset.timeZone;
 $('#summary-schedule-note').textContent=enabled?'Sent once per local day at or shortly after your chosen time. If the panel was offline, it catches up later that day.':'Daily summary is off. Your chosen time is saved for when you enable it.';
}

function notificationVerification(title,description,run,label,review=''){
 openModal(title,description,`<div class="verification-identity">${adminAvatar(adminProfile.avatar,true)}<span>Signed in as <b>${e(adminProfile.username)}</b></span>${icon('lock')}</div>${review}<div class="verification-fields"><div class="verification-field"><label for="verification-password">Panel password</label><div class="password-control"><input id="verification-password" name="current" type="password" autocomplete="current-password" maxlength="256" required><button type="button" class="icon-btn" data-action="integration-password-visibility" aria-label="Show password" aria-pressed="false">${icon('eye')}</button></div><small class="field-hint">Use the password you sign in to NARA with.</small></div>${adminProfile.two_factor?field('Authenticator or recovery code','code','','text','Use a fresh authenticator code or an unused recovery code.'):''}</div><p class="verification-status" id="verification-status" role="status" aria-live="polite"></p>`,run,label);
 $('#modal').classList.add('verification-dialog');
 const form=$('#modal-form');form.classList.add('verification-form');form.dataset.busyLabel='Verifying…';form.dataset.busyMessage='Checking your password and completing this request…';
 requireAdminInputs(form);
}
function notificationReview(settings){
 const count=settings.events.length,summary=settings.events.includes('daily_summary')?String(settings.summary_hour).padStart(2,'0')+':'+String(settings.summary_minute).padStart(2,'0')+' · '+panelTimeZone():'Off · '+String(settings.summary_hour).padStart(2,'0')+':'+String(settings.summary_minute).padStart(2,'0')+' · '+panelTimeZone();
 return `<dl class="verification-review"><div><dt>Delivery</dt><dd>${badge(settings.enabled?'Enabled':'Disabled',settings.enabled?'green':'')}</dd></div><div><dt>Events</dt><dd>${count} selected</dd></div><div><dt>Destination</dt><dd>${e(settings.chat_id||'Not set')}</dd></div><div><dt>Daily summary</dt><dd>${e(summary)}</dd></div>${settings.bot_token?'<div><dt>Bot token</dt><dd>Replace stored token</dd></div>':''}</dl>`;
}
function notificationSavedMatches(settings,saved){
 return !settings.bot_token&&!!saved&&saved.enabled===settings.enabled&&saved.chat_id===settings.chat_id&&saved.summary_hour===settings.summary_hour&&(saved.summary_minute??0)===settings.summary_minute&&JSON.stringify([...(saved.events||[])].sort())===JSON.stringify([...settings.events].sort())&&(!settings.enabled||saved.token_configured);
}
function saveTelegram(form){
 const settings=notificationPreferences(form);
 if(settings.enabled&&!settings.bot_token&&!telegramData.token_configured)throw Error('Enter a bot token before enabling notifications.');
 if(settings.enabled&&!settings.chat_id)throw Error('Choose a destination Chat ID before enabling notifications.');
 notificationVerification('Save notification preferences','Review your choices, then confirm with your panel password.',async auth=>{
  const session=csrf;let recovered=false;
  try{await api('telegram',{...Object.fromEntries(new FormData(auth)),settings});}
  catch(error){
   if(!error.uncertain||settings.bot_token||session!==csrf)throw error;
   let saved;try{saved=await api('telegram',undefined,{timeoutMs:8000});}catch{throw error;}
   if(!notificationSavedMatches(settings,saved))throw error;
   telegramData=saved;recovered=true;
  }
  if(session!==csrf)return;
  // Update the public cache only. Neither the panel password nor token is retained.
  telegramData={...telegramData,enabled:settings.enabled,chat_id:settings.chat_id,events:settings.events,summary_hour:settings.summary_hour,summary_minute:settings.summary_minute,token_configured:!!settings.bot_token||!!telegramData.token_configured};
  if(page==='notifications')render();
  clientDeliveryData=null;
  toast(recovered?'Saved preferences confirmed after reconnecting.':'Notification preferences saved.');
 },'Confirm & save',notificationReview(settings));
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
 if(action==='integration-telegram-reload'){if($('#modal').open)$('#modal').close();return integrationLoad('telegram',true);}
 if(action==='integration-password-visibility'){const input=$('#modal-form').elements.current,show=input.type==='password';input.type=show?'text':'password';target.setAttribute('aria-label',show?'Hide password':'Show password');target.setAttribute('aria-pressed',String(show));return;}
 if(action==='integration-events-all'||action==='integration-events-none'){for(const input of $$('#telegram-form [name=event]'))input.checked=action==='integration-events-all';updateSummarySchedule();return;}
 if(action==='integration-key-new')return createAPIKey();
 if(action==='integration-key-revoke')return revokeAPIKey(target.dataset.id);
 if(action==='integration-api-guide')return showAPIGuide();
 if(action==='integration-openapi'){download('nara-openapi.json',await api('openapi'));return;}
 if(action==='integration-api-refresh')return integrationLoad('api',true);
 if(action==='integration-telegram-activity'){const container=$('.delivery-activity'),session=csrf,value=await api('telegram');if(session!==csrf||!container?.isConnected)return;telegramData={...telegramData,delivery:value.delivery,recent:value.recent};container.innerHTML=telegramActivity(telegramData);toast('Delivery activity refreshed.');return;}
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

// Client delivery is separate from administrator notification preferences.
let clientDeliveryData=null,clientDeliveryLoading=false;
function loadClientDelivery(force=false){
 if(clientDeliveryLoading||clientDeliveryData&&!force)return;
 const session=csrf;clientDeliveryLoading=true;
 api('client-delivery').then(value=>{if(session===csrf)clientDeliveryData=value;}).catch(error=>{if(session===csrf)clientDeliveryData={error:error.message};}).finally(()=>{clientDeliveryLoading=false;if(session!==csrf)return;if(page==='notifications'&&$('#private-client-bot'))$('#private-client-bot').outerHTML=renderClientBot();else if(['email','notifications'].includes(page))render();});
}
function renderClientBot(){
 const value=clientDeliveryData;if(!value||value.error)return '<section class="card" id="private-client-bot"><div class="card-body"><h2>Private client bot</h2><p class="note">'+e(value?.error||'Loading client bot…')+'</p>'+btn('Retry','delivery-refresh','refresh')+'</div></section>';
 return `<section class="card" id="private-client-bot"><div class="card-header"><div><span class="section-kicker">PRIVATE CLIENT BOT</span><h2>Service access in Telegram</h2><p>Uses the Bot Token saved in Notifications.</p></div>${badge(value.bot_enabled?'Enabled':'Off',value.bot_enabled?'green':'')}</div><div class="card-body preference-fields"><p>Clients connect the bot from their own private service page and press Start. Then /status, /links or their linked username returns only their own service.</p><div class="inline-buttons">${btn(value.bot_enabled?'Disable client bot':'Enable client bot','delivery-bot-toggle','notifications',value.bot_enabled?'':'primary')}${btn('Bot connection','delivery-focus-token','key')}</div>${value.bot_enabled?`<p class="note">@${e(value.bot_username)} · ${value.bot_status?.error?e(value.bot_status.error):'Commands are checked every ten seconds while enabled.'}</p>`:''}<p class="note">Use a dedicated bot without a webhook or another polling server. Administrator alerts remain controlled by Notifications. A username alone is insufficient to prove chat ownership. Pairing records the verified Telegram user ID on the client account.</p></div></section>`;
}
function renderEmail(){
 if(!clientDeliveryData){loadClientDelivery();return heading()+'<p class="note">Loading client delivery…</p>';}
 const value=clientDeliveryData;if(value.error)return heading(btn('Retry','delivery-refresh','refresh'))+`<div class="hint-box error">${e(value.error)}</div>`;
 return heading(btn('Refresh','delivery-refresh','refresh'))+`<div class="management-layout"><div class="management-stack"><section class="card"><div class="card-header"><div><span class="section-kicker">CLIENT EMAIL</span><h2>SMTP connection</h2><p>Send service access from your own email provider.</p></div>${badge(value.smtp_enabled?'Enabled':'Off',value.smtp_enabled?'green':'')}</div><div class="card-body"><form id="email-form"><label class="check-field notification-enable"><input type="checkbox" name="smtp_enabled" ${checked(value.smtp_enabled)}>Enable client email delivery</label><div class="form-grid section-gap">${field('SMTP host','host',value.host,'text','For example smtp.example.com')}${field('Port','port',value.port,'number')}${selectField('Connection security','security',[['starttls','STARTTLS · usually port 587'],['tls','Implicit TLS · usually port 465']],value.security)}${field('SMTP username','username',value.username,'text')}${field(value.password_configured?'SMTP password (saved; leave blank to keep)':'SMTP password','password','','password')}${field('From name','from_name',value.from_name)}${field('From email','from_email',value.from_email,'email')}${field('Reply-to email (optional)','reply_to',value.reply_to,'email')}</div><label class="check-field"><input type="checkbox" name="clear_password">Remove the saved SMTP password</label><div class="form-save-bar"><p>TLS certificates are always verified. Delivery runs in a bounded background queue.</p><button type="submit" class="btn primary">Save SMTP</button></div></form></div></section><section class="card"><div class="card-header"><div><h2>Email templates</h2><p>Plain text with safe placeholders. Connection links and QR images are added automatically.</p></div>${btn('New template','delivery-template-new','plus','sm')}</div><div class="card-body">${value.templates.map(row=>`<div class="preference-row section-gap"><div><b>${e(row.name)}</b><p>${e(row.subject)}</p><small class="muted">${row.include_qr?'Includes QR images':'Links only'}</small></div><div class="inline-buttons">${btn('Preview','delivery-template-preview','eye','sm',`data-id="${e(row.id)}"`)}${btn('Edit','delivery-template-edit','edit','sm',`data-id="${e(row.id)}"`)}${value.templates.length>1?rowBtn('Delete template','delivery-template-delete','trash',row.id):''}</div></div>`).join('')}<p class="note section-gap">Emails include up to 20 connection links and six inline QR images to keep messages small. The private service page includes every connection.</p></div></section></div><aside class="management-stack"><section class="card"><div class="card-header"><h2>Connection check</h2></div><div class="card-body preference-fields"><p class="note">Test TLS negotiation and SMTP login using saved settings. This test sends no email.</p>${btn('Test SMTP connection','delivery-smtp-test','check')}</div></section><section class="card"><div class="card-header"><h2>Send service access</h2></div><div class="card-body preference-fields"><p class="note">Set an email address on the client, then use its email action. Telegram delivery becomes available after the owner pairs their chat. <a class="text-link" href="#notifications">Manage client bot →</a></p><a class="text-link" href="#clients">Open clients →</a><p class="note">The eye icon includes subscription formats, individual connection links and the private service page, each with QR.</p></div></section><section class="card"><div class="card-header"><h2>Recent client deliveries</h2></div><div class="card-body"><ul class="delivery-list">${value.recent.map(row=>`<li><div><b>${e(row.channel==='email'?'Email':'Telegram')}</b><small>${e(date(row.created))} · ${e(time(row.created))}</small>${row.error?`<small>${e(row.error)}</small>`:''}</div>${badge(row.status,row.status==='sent'?'green':row.status==='failed'?'red':'')}</li>`).join('')||'<li class="muted">No client messages yet.</li>'}</ul></div></section></aside></div>`;
}
function confirmDeliverySettings(settings,title='Save client delivery preferences'){
 const session=csrf;notificationVerification(title,'Confirm with your NARA administrator password.',async form=>{await api('client-delivery',{...Object.fromEntries(new FormData(form)),settings});if(session!==csrf)return;loadClientDelivery(true);toast('Client delivery preferences saved.');},'Confirm & save');
}
function saveEmailForm(form){const f=new FormData(form),value=Object.fromEntries(f);value.smtp_enabled=form.elements.smtp_enabled.checked;value.clear_password=form.elements.clear_password.checked;value.port=Number(f.get('port'));if(!Number.isInteger(value.port)||value.port<1||value.port>65535)throw Error('SMTP port must be between 1 and 65535.');if(value.smtp_enabled&&(!value.host.trim()||!value.from_email.trim()))throw Error('Enter an SMTP host and From email before enabling delivery.');confirmDeliverySettings(value,'Save SMTP connection');form.elements.password.value='';}
const emailPreviewQR=new Map();
function emailPreviewHTML(template){
 const values={username:'Example client',portal_url:'https://service.example.com/private/demo/',subscription_url:'https://service.example.com/sub/demo',sing_box_url:'sing-box://import-remote-profile?url=https%3A%2F%2Fservice.example.com%2Fsub%2Fdemo',config_links:'Configuration Link: vless://example@proxy.example.com:443',used_traffic:'2.5 GiB',remaining_traffic:'17.5 GiB',total_traffic:'20 GiB',expires:'2026-12-31 12:00 UTC',remaining_time:'30d 12h 0m'};
 const expand=text=>String(text||'').replace(/\{\{|\}\}|\{([a-z_]+)\}/g,(all,key)=>all==='{{'?'{':all==='}}'?'}':values[key]??all);
 const links=[['Private service page',values.portal_url],['Sing-box app',values.sing_box_url],['JSON subscription',values.subscription_url],['Configuration Link','vless://example@proxy.example.com:443']];
 return `<div class="email-preview"><span class="section-kicker">EXAMPLE PREVIEW · NO EMAIL SENT</span><h3>${e(expand(template.subject))}</h3><pre>${e(expand(template.body))}</pre><div class="email-preview-links">${links.map(([name,url])=>`<div><b>${e(name)}</b><code>${e(url)}</code>${template.include_qr?(emailPreviewQR.has(url)?emailPreviewQR.get(url):(emailPreviewQR.set(url,NaraQR.svg(url)),emailPreviewQR.get(url))):''}</div>`).join('')}</div><p class="note">Example values only. Actual deliveries use this client’s current usage, service time and private links.</p></div>`;
}
function previewEmailTemplate(template){openModal('Email preview','Example service access with your template.',emailPreviewHTML(template));}
function editEmailTemplate(row={}){
 const current=row.id?row:{id:'template-'+randomClientName(),name:'New template',subject:'Your service · {username}',body:'Hello {username},\n\nYour private service page:\n{portal_url}\n\nTraffic remaining: {remaining_traffic}\nService remaining: {remaining_time}',include_qr:true};
 openModal(row.id?'Edit email template':'New email template','Use plain text. All HTML and inserted values are escaped safely.',`<div class="form-grid">${field('Template name','template_name',current.name,'text','','class="full"')}${field('Subject','subject',current.subject,'text','','class="full"')}${textField('Message','body',current.body,'','class="full"')}<label class="check-field full"><input name="include_qr" type="checkbox" ${checked(current.include_qr)}>Include inline QR images</label></div><div id="email-template-preview">${emailPreviewHTML(current)}</div><p class="note">Available placeholders: ${(clientDeliveryData.placeholders||[]).map(key=>'<code>{'+e(key)+'}</code>').join(' · ')}</p>`,form=>{const f=new FormData(form),template={id:current.id,name:f.get('template_name'),subject:f.get('subject'),body:f.get('body'),include_qr:form.elements.include_qr.checked};const templates=clientDeliveryData.templates.filter(row=>row.id!==template.id).concat(template);confirmDeliverySettings({templates},'Save email template');return false;},'Review & save');
 const form=$('#modal-form');form.elements.template_name.maxLength=100;form.elements.subject.maxLength=200;form.elements.body.maxLength=20000;let previewTimer;form.addEventListener('input',()=>{clearTimeout(previewTimer);previewTimer=setTimeout(()=>{if(form.isConnected)$('#email-template-preview',form).innerHTML=emailPreviewHTML({subject:form.elements.subject.value,body:form.elements.body.value,include_qr:form.elements.include_qr.checked});},120);});
}
async function sendClientAccess(channel,id){
 const session=csrf;const client=state.clients.find(row=>row.id===id);if(!client)throw Error('Client no longer exists.');
 if(channel==='email'&&!client.email)throw Error('Edit this client and set an email address first.');
 const config=await api('client-delivery');if(session!==csrf)return;
 openModal('Send service access',e(client.name),`<p>Send private connection access by ${channel==='email'?'email to <b>'+e(client.email)+'</b>':'Telegram to this client’s verified paired chat'}?</p>${channel==='email'?selectField('Email template','template_id',config.templates.map(row=>[row.id,row.name]),config.templates[0].id):'<p class="note">The owner must first pair their chat from the private service page and press Start. A contact username alone is insufficient.</p>'}`,async form=>{await api('client-send',{id,channel,template_id:form.elements.template_id?.value||'service'});toast('Private service access queued for delivery.');},'Send access');
}
async function handleDelivery(action,target){
 const id=target.dataset.id;
 if(action==='delivery-focus-token'){const input=$('#telegram-form [name=bot_token]');input?.scrollIntoView({behavior:'smooth',block:'center'});input?.focus();return;}
 if(action==='delivery-scroll-bot'){$('#private-client-bot')?.scrollIntoView({behavior:'smooth',block:'start'});return;}
 if(action==='delivery-refresh'){loadClientDelivery(true);return;}
 if(action==='delivery-open-notifications'){location.hash='notifications';return;}
 if(action==='delivery-email'||action==='delivery-telegram')return sendClientAccess(action==='delivery-email'?'email':'telegram',id);
 if(action==='delivery-template-preview')return previewEmailTemplate(clientDeliveryData.templates.find(row=>row.id===id));
 if(action==='delivery-template-new')return editEmailTemplate();
 if(action==='delivery-template-edit')return editEmailTemplate(clientDeliveryData.templates.find(row=>row.id===id));
 if(action==='delivery-template-delete')return confirmDeliverySettings({templates:clientDeliveryData.templates.filter(row=>row.id!==id)},'Delete email template');
 if(action==='delivery-bot-toggle')return confirmDeliverySettings({bot_enabled:!clientDeliveryData.bot_enabled},clientDeliveryData.bot_enabled?'Disable client bot':'Enable private client bot');
 if(action==='delivery-smtp-test')return notificationVerification('Test saved SMTP connection','Checks TLS and login without sending a message.',async form=>{await api('client-delivery/test',Object.fromEntries(new FormData(form)));toast('SMTP TLS connection and authentication succeeded.');},'Test connection');
 if(action==='delivery-unpair')return confirmAction('Disconnect client bot','The paired chat will lose access to this account. The owner can pair again from their private page.',async()=>{await api('client-unpair',{id});toast('Client bot disconnected.');},'Disconnect');
}
