'use strict';
function renderTransferSettings(){return `<section class="card section-gap"><div class="card-header"><div><span class="section-kicker">BACKUP & TRANSFER</span><h2>Keep your workspace portable</h2><p>Download settings, restore on another server, or use the migration wizard</p></div>${icon('download')}</div><div class="card-body preference-fields"><div class="inline-buttons">${btn('Download backup','transfer-backup','download')}${btn('Restore backup','transfer-restore','refresh')}${btn('Migrate to another server','transfer-migrate','routing')}</div><p class="note">Portable backups include proxy settings, TLS keys, users and quota counters. Restore retains destination addresses, administrator, 2FA and API keys. Telegram stays off until reviewed. Charts and host billing counters belong to their original server.</p><p class="note">Private portable copies: <span class="mono">${e('/var/lib/nara-panel/backups/')}</span> (last 10). Updates also keep a complete server backup in <span class="mono">/var/backups/nara-panel/</span>.</p>${btn('View migration progress','transfer-migration-status','eye','sm')}</div></section>`;}
function createPortableBackup(title='Download private backup',after=null){
 return notificationVerification(title,'The file contains client credentials, bot credentials and TLS private keys. Store it privately.',async form=>{
  const result=await api('backup/create',Object.fromEntries(new FormData(form)),{timeoutMs:120000});
  download(result.filename,result.backup);toast('Private backup download requested. Server copy: '+result.path);
  if(after)await after(result);
 },'Download backup',`<div class="hint-box">Portable backup: <span class="mono">/var/lib/nara-panel/backups/</span><br>Full pre-update server backup: <span class="mono">/var/backups/nara-panel/</span>${after?'<br>Download the backup first, then confirm the update after saving it. Your browser may ask where to save the file.':''}</div>`);
}
function restorePortableBackup(){
 openModal('Restore a portable backup','Your destination administrator and addresses are retained.',`<label>Private NARA backup (.json)<input type="file" name="backup_file" accept=".json,application/json" required></label><p class="note">Up to 12 MiB. Proxy settings and client quota counters are replaced after validation. A private rollback copy is saved first.</p>`,async form=>{
  const file=form.elements.backup_file.files[0];if(!file||file.size>12*1024*1024)throw Error('Choose a NARA JSON backup up to 12 MiB.');
  let backup;try{backup=JSON.parse(await file.text());}catch{throw Error('The selected file is not valid JSON.');}
  const result=await api('backup/preview',{backup},{timeoutMs:30000});
  notificationVerification('Confirm restore','This replaces the destination proxy configuration and clients.',async verification=>{const saved=await api('backup/restore',{backup,...Object.fromEntries(new FormData(verification))},{timeoutMs:180000});telegramData=null;await load();toast('Restored. Previous settings saved: '+saved.backup_path);},'Restore settings',`${field('Destination server IP or domain','server_address',state.settings.server_address||location.hostname.replace(/^\[|\]$/g,''),'text','The connection address for restored clients. Source addresses are never filled from the backup.')}<div class="detail-stats section-gap"><div><small>Clients</small><b>${result.clients}</b></div><div><small>Inbounds</small><b>${result.inbounds}</b></div><div><small>Certificates</small><b>${result.tls}</b></div></div><p class="note">${e(result.note)}</p><ul class="note">${result.retained.map(x=>`<li>Retained: ${e(x)}</li>`).join('')}</ul>`);
 },'Review backup');
}
function migrationWizard(){
 if(!window.isSecureContext)throw Error('Enable panel HTTPS before entering root SSH credentials. Localhost previews are allowed.');
 openModal('Migrate NARA · 1 of 2','A fresh Debian 12+ / Ubuntu 22.04+ server with root SSH access is required.',`<div class="hint-box">The source stays online. The destination must not already contain NARA. Open inbound ports, TCP 80/443/8443 and SSH in its firewall. If using domains, point their A/AAAA records at the destination first. Certificates are publicly logged by the certificate authority.</div><div class="form-grid section-gap">${field('Destination IP','host','','text')}${field('SSH port','ssh_port',22,'number')}${selectField('SSH authentication','auth_mode',[['password','Root password'],['key','Private key']],'password')}${field('SSH password / key passphrase','ssh_password','','password')}${textField('SSH private key (only for key authentication)','ssh_key','','PEM or OpenSSH format. Used for this connection only.','class="full"')}${field('Panel domain (optional)','panel_domain','','text','Blank uses HTTP at the destination IP.')}${field('Subscription domain (optional)','subscription_domain','','text','Blank uses the panel domain. HTTPS subscriptions use port 8443.')}${field('Internal panel port','panel_port',10000,'number')}${field('Internal subscription port','subscription_port',10001,'number')}${field('Panel webPath','web_path',accessSettings.web_path||'/Panel','text')}${field('Subscription subPath','sub_path',accessSettings.sub_path||'/Subscriptions','text')}</div><h3 class="section-gap">Verify this operation</h3>${adminReauth()}`,async form=>{
  const values=Object.fromEntries(new FormData(form));values.ssh_port=Number(values.ssh_port);values.panel_port=Number(values.panel_port);values.subscription_port=Number(values.subscription_port);
  const pin=await api('migration/probe',{host:values.host,ssh_port:values.ssh_port,current:values.current,code:values.code},{timeoutMs:30000});delete values.current;delete values.code;
  notificationVerification('Migrate NARA · 2 of 2','Confirm the host fingerprint from your hosting console before transferring private data.',async verification=>{
   if(!verification.elements.approve_host.checked)throw Error('Verify and approve the SSH fingerprint first.');
   const job=await api('migration/start',{...values,...Object.fromEntries(new FormData(verification)),probe_id:pin.id,fingerprint:pin.fingerprint},{timeoutMs:30000});
   values.ssh_password='';values.ssh_key='';await showMigrationStatus(job);
  },'Start migration',`<div class="hint-box"><b>${e(pin.host)}:${pin.ssh_port}</b><p class="mono fingerprint">${e(pin.fingerprint)}</p><p>Panel: ${e(values.panel_domain||values.host)} · Subscription: ${e(values.subscription_domain||values.panel_domain||values.host)}</p><label class="check-field"><input type="checkbox" name="approve_host" required>I verified this fingerprint using a trusted server console.</label></div><p class="note">Administrator and 2FA, client credentials and quotas are copied over encrypted SSH. API keys and client/inbound chart history are copied; browser sessions and host billing counters are not. Changes and traffic on the source after the snapshot are not synchronized. Do not run both copies indefinitely with the same account allowances.</p>`);
 },'Check SSH host');
 const form=$('#modal-form');requireAdminInputs(form);form.elements.host.required=true;form.elements.ssh_password.autocomplete='off';
 const sync=()=>{const key=form.elements.auth_mode.value==='key';form.elements.ssh_key.closest('label').hidden=!key;form.elements.ssh_key.required=key;form.elements.ssh_password.required=!key;};form.elements.auth_mode.onchange=sync;sync();
}
async function showMigrationStatus(initial=null){
 const job=initial||await api('migration');
 openModal('Migration progress','The source server stays online.',`<div id="migration-progress" role="status"></div>`);
 const box=$('#migration-progress');
 const paint=value=>{box.innerHTML=`${badge(value.status,value.status==='complete'?'green':value.status==='failed'?'red':'orange')}<p class="section-gap">${e(value.stage||'No migration started.')}</p>${value.url?`<p><a class="text-link" target="_blank" rel="noopener noreferrer" href="${e(value.url)}">Open destination panel →</a></p><p class="note">Subscriptions: ${e(value.subscription_url)}<br>Snapshot: ${date(value.snapshot_at)} · ${time(value.snapshot_at)}</p>`:''}`;};paint(job);
 if(job.status!=='running')return;
 while(box.isConnected){await new Promise(resolve=>setTimeout(resolve,2000));if(!box.isConnected)return;try{const current=await api('migration');if(!box.isConnected)return;paint(current);if(current.status!=='running')return;}catch(error){if(box.isConnected)box.textContent=error.message;return;}}
}
async function handleTransfer(action){
 if(action==='transfer-backup')return createPortableBackup();
 if(action==='transfer-restore')return restorePortableBackup();
 if(action==='transfer-migrate')return migrationWizard();
 if(action==='transfer-migration-status')return showMigrationStatus();
}
