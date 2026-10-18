"""Opt-in SMTP delivery and a private-chat bot with one-use account pairing."""
import datetime as dt
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
import hashlib
import html
import json
import re
import secrets
import smtplib
import ssl
import string
import struct
import time
import zlib
from . import client_portal, notifications
from .config import host, require

DEFAULT_TEMPLATE={'id':'service','name':'Service access','subject':'Your NARA service · {username}',
 'body':'Hello {username},\n\nYour private service page:\n{portal_url}\n\nTraffic remaining: {remaining_traffic}\nService remaining: {remaining_time}\nExpires: {expires}\n\nKeep all connection links and QR codes private.', 'include_qr':True}
FIELDS={'username','portal_url','subscription_url','sing_box_url','config_links','used_traffic','remaining_traffic','total_traffic','expires','remaining_time'}


def settings(store):
    return {'smtp_enabled':False,'host':'','port':587,'security':'starttls','username':'','password':'','from_email':'','from_name':'NARA','reply_to':'',
            'bot_enabled':False,'bot_username':'','bot_fingerprint':'','templates':[dict(DEFAULT_TEMPLATE)],**(store.get('client_delivery') or {})}


def public_settings(store):
    value=settings(store);value['password_configured']=bool(value.pop('password',''))
    value['bot_token_configured']=bool(notifications.settings(store)['bot_token'])
    value['bot_status']=store.get('client_bot_status',{})
    with store.connect() as db:
        value['recent']=[{'channel':row[0],'created':row[1],'status':row[2],'error':row[3]} for row in db.execute('SELECT channel,created,status,error FROM client_messages ORDER BY id DESC LIMIT 10')]
    value['placeholders']=sorted(FIELDS)
    return value


def check_template(text):
    try:
        for _,field,fmt,conversion in string.Formatter().parse(text):
            require(field is None or field in FIELDS and not fmt and conversion is None,'Use only supported email template placeholders, without formatting or attributes')
    except ValueError:
        raise ValueError('Invalid email template placeholder') from None


def validate(data, previous=None):
    require(isinstance(data,dict),'Invalid client delivery settings')
    previous=previous or {'smtp_enabled':False,'host':'','port':587,'security':'starttls','username':'','password':'','from_email':'','from_name':'NARA','reply_to':'','bot_enabled':False,'bot_username':'','bot_fingerprint':'','templates':[dict(DEFAULT_TEMPLATE)]}
    value={**previous,**{key:data[key] for key in ('smtp_enabled','host','port','security','username','from_email','from_name','reply_to','bot_enabled','templates') if key in data}}
    if data.get('password'):value['password']=data['password']
    if data.get('clear_password') is True:value['password']=''
    for key in ('smtp_enabled','bot_enabled'):require(type(value[key]) is bool,'Invalid delivery enabled state')
    for key in ('host','username','password','from_email','from_name','reply_to'):
        require(isinstance(value[key],str) and len(value[key])<=1024 and not any(ord(c)<32 or ord(c)==127 for c in value[key]),'Invalid SMTP field')
    require(type(value['port']) is int and 1<=value['port']<=65535,'SMTP port must be between 1 and 65535')
    require(value['security'] in ('starttls','tls'),'Use STARTTLS or implicit TLS; plaintext SMTP is not supported')
    if value['host']:host(value['host'])
    client_portal.contact(value['from_email'],'email');client_portal.contact(value['reply_to'],'email')
    if value['smtp_enabled']:require(bool(value['host'] and value['from_email']),'SMTP host and From email are required')
    templates=value['templates'];require(isinstance(templates,list) and 1<=len(templates)<=20,'Define 1–20 email templates')
    ids=[]
    for row in templates:
        require(isinstance(row,dict) and set(row)<={'id','name','subject','body','include_qr'},'Invalid email template')
        require(bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',row.get('id',''))),'Invalid email template ID')
        for key,maximum in (('name',100),('subject',200),('body',20000)):
            require(isinstance(row.get(key),str) and 0<len(row[key])<=maximum,'Invalid email template '+key)
        require(not any(ord(c)<32 for c in row['subject']+row['name']),'Email headers must not contain line breaks')
        require(type(row.get('include_qr')) is bool,'Invalid QR template option')
        check_template(row['subject']);check_template(row['body']);ids.append(row['id'])
    require(len(ids)==len(set(ids)),'Email template IDs must be unique')
    return value


def save(store,data):
    previous=settings(store);value=validate(data,previous)
    if value['bot_enabled'] and (not previous['bot_enabled'] or not value.get('bot_username') or value.get('bot_fingerprint')!=bot_hash(store)):
        token=notifications.settings(store)['bot_token'];require(bool(token),'Set your Telegram Bot Token in Notifications first')
        info=notifications.bot_info(token)
        webhook=notifications.call(token,'getWebhookInfo',{})
        require(isinstance(webhook,dict) and not webhook.get('url'),'This bot has a webhook. Use a dedicated bot or remove its webhook yourself before enabling client commands')
        value['bot_username']=info['username'];value['bot_fingerprint']=bot_hash(store)
    elif not value['bot_enabled']:value['bot_username']=''
    store.set('client_delivery',value)
    with store.connect() as db:
        if not value['smtp_enabled']:db.execute("UPDATE client_messages SET status='cancelled' WHERE channel='email' AND status='queued'")
        if not value['bot_enabled']:db.execute("UPDATE client_messages SET status='cancelled' WHERE channel='telegram' AND status='queued'")
    store.client_delivery_wakeup.set()
    store.audit('Client email and bot preferences updated')
    return {'ok':True}


def smtp_connect(value):
    context=ssl.create_default_context()
    try:
        connection=smtplib.SMTP_SSL(value['host'],value['port'],timeout=12,context=context) if value['security']=='tls' else smtplib.SMTP(value['host'],value['port'],timeout=12)
        try:
            connection.ehlo()
            if value['security']=='starttls':connection.starttls(context=context);connection.ehlo()
            if value['username']:connection.login(value['username'],value['password'])
            return connection
        except Exception:
            connection.close();raise
    except (OSError,smtplib.SMTPException):
        raise ValueError('SMTP connection failed. Check host, TLS mode, certificate and credentials') from None


def test_smtp(store):
    value=settings(store);require(value['smtp_enabled'],'Save and enable SMTP first')
    connection=smtp_connect(value)
    connection.close()
    return {'ok':True}


def amount(value):
    if value is None:return 'Unlimited'
    if not value:return '0 B'
    units=('B','KiB','MiB','GiB','TiB','PiB');index=0
    while value>=1024 and index<len(units)-1:value/=1024;index+=1
    return (f'{value:.3f}'.rstrip('0').rstrip('.') if index else str(int(value)))+' '+units[index]


def duration(seconds):
    if seconds is None:return 'Unlimited'
    seconds=max(0,int(seconds));days,seconds=divmod(seconds,86400);hours,seconds=divmod(seconds,3600)
    return (str(days)+'d ' if days else '')+str(hours)+'h '+str(seconds//60)+'m'


def variables(model):
    return {'username':model['name'],'portal_url':model['portal_url'],'subscription_url':model['links'][1]['url'],'sing_box_url':model['links'][0]['url'],
            'config_links':'\n'.join(row['name']+': '+row['url'] for row in model['links'][2:22]),'used_traffic':amount(model['used']),
            'remaining_traffic':amount(model['remaining']),'total_traffic':amount(model['quota']) if model['quota'] else 'Unlimited',
            'expires':dt.datetime.fromtimestamp(model['expires_at'],dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if model['expires_at'] else 'Never',
            'remaining_time':duration(model['remaining_seconds'])}


def qr_png(text):
    from .vendor.qrcodegen import QrCode
    require(len(text.encode())<=2048,'Connection link is too long for email QR')
    qr=QrCode.encode_text(text,QrCode.Ecc.MEDIUM);scale=4;size=(qr.get_size()+8)*scale
    rows=[]
    for y in range(size):
        line=bytes(0 if qr.get_module(x//scale-4,y//scale-4) else 255 for x in range(size))
        rows.append(b'\0'+line)
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',size,size,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')


def format_template(text,args,limit):
    parts=[];length=0
    for literal,field,fmt,conversion in string.Formatter().parse(text):
        require(field is None or field in FIELDS and not fmt and conversion is None,'Invalid email template placeholder')
        for part in (literal,args[field] if field else ''):
            length+=len(part);require(length<=limit,'Rendered email template is too large')
            parts.append(part)
    return ''.join(parts)


def email_message(value,recipient,template,model):
    args=variables(model);message=EmailMessage();subject=format_template(template['subject'],args,300)
    require(not any(ord(c)<32 for c in subject),'Rendered subject contains a control character')
    message['Subject']=subject[:300];message['From']=formataddr((value['from_name'],value['from_email']));message['To']=recipient
    message['Date']=dt.datetime.now(dt.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %z');message['Message-ID']=make_msgid()
    if value['reply_to']:message['Reply-To']=value['reply_to']
    body=format_template(template['body'],args,128000);message.set_content(body+'\n\n'+ '\n'.join(row['name']+': '+row['url'] for row in model['links'][:20]))
    content=['<html><body style="font:16px/1.7 sans-serif;color:#263b40"><h2>NARA</h2><p>'+html.escape(body).replace('\n','<br>')+'</p><p><a href="'+html.escape(model['portal_url'],quote=True)+'">Open your private service page</a></p>']
    images=[]
    for index,row in enumerate(model['links'][:20]):
        content.append('<h3>'+html.escape(row['name'])+'</h3><p><a href="'+html.escape(row['url'],quote=True)+'">'+html.escape(row['url'])+'</a></p>')
        if template['include_qr'] and index<6 and len(row['url'].encode())<=2048:
            cid='nara-connection-'+str(index);images.append((cid,qr_png(row['url'])))
            content.append('<img width="240" alt="Private connection QR" src="cid:'+cid+'">')
    if len(model['links'])>20:content.append('<p>All other connection links are available on your private service page.</p>')
    content.append('<p>Keep these credentials private.</p></body></html>')
    message.add_alternative(''.join(content),subtype='html')
    for cid,png in images:message.get_payload()[-1].add_related(png,maintype='image',subtype='png',cid='<'+cid+'>',filename=cid+'.png',disposition='inline')
    return message


def bot_hash(store):return hashlib.sha256(notifications.settings(store)['bot_token'].encode()).hexdigest()


def binding(store,client):
    with store.connect() as db:row=db.execute('SELECT chat_id,bot_hash,capability FROM client_bot_bindings WHERE client_id=?',(client['id'],)).fetchone()
    return row[0] if row and row[1]==bot_hash(store) and secrets.compare_digest(row[2],client_portal.token(client)) else None


def pair(store,client):
    value=settings(store);require(value['bot_enabled'] and value['bot_username'] and value.get('bot_fingerprint')==bot_hash(store),'Client bot is not enabled')
    nonce=secrets.token_urlsafe(32);now=time.time()
    with store.connect() as db:
        db.execute('DELETE FROM client_bot_pairs WHERE expires<? OR client_id=?',(now,client['id']))
        valid=[row['id'] for row in store.get('state')['clients']]
        if valid:db.execute('DELETE FROM client_bot_bindings WHERE client_id NOT IN ('+','.join('?' for _ in valid)+')',valid)
        db.execute('INSERT INTO client_bot_pairs VALUES(?,?,?,?,?)',(hashlib.sha256(nonce.encode()).hexdigest(),client['id'],client_portal.token(client),bot_hash(store),now+600))
    return {'url':'https://t.me/'+value['bot_username']+'?start='+nonce,'expires':now+600}


def unpair(store,client_id):
    with store.connect() as db:
        db.execute('DELETE FROM client_bot_bindings WHERE client_id=?',(client_id,));db.execute('DELETE FROM client_bot_pairs WHERE client_id=?',(client_id,))
        db.execute("UPDATE client_messages SET status='cancelled' WHERE client_id=? AND channel='telegram' AND status='queued'",(client_id,))


def enqueue(store,client,channel,template_id='service'):
    require(channel in ('email','telegram'),'Choose email or Telegram')
    value=settings(store)
    if channel=='email':
        require(value['smtp_enabled'],'Configure and enable SMTP in Email first');recipient=client_portal.contact(client.get('email',''),'email');require(bool(recipient),'Set an email address for this client first')
        require(any(row['id']==template_id for row in value['templates']),'Choose a saved email template')
    else:
        require(value['bot_enabled'],'Enable client bot commands in Email first');recipient=binding(store,client)
        require(bool(recipient),'The client must securely pair the bot from their private service page and press Start first')
    now=time.time()
    with store.connect() as db:
        require(not db.execute("SELECT 1 FROM client_messages WHERE client_id=? AND channel=? AND created>?",(client['id'],channel,now-30)).fetchone(),'Wait 30 seconds before sending to this client again')
        require(db.execute("SELECT COUNT(*) FROM client_messages WHERE status='queued'").fetchone()[0]<200,'Delivery queue is full; try again later')
        db.execute('INSERT INTO client_messages(client_id,channel,recipient,template_id,created,available) VALUES(?,?,?,?,?,?)',(client['id'],channel,recipient,template_id,now,now))
        db.execute("DELETE FROM client_messages WHERE status!='queued' AND id NOT IN (SELECT id FROM client_messages ORDER BY id DESC LIMIT 500)")
    store.client_delivery_wakeup.set()
    return {'ok':True,'queued':True}


def service_text(model,links=False):
    values=variables(model)
    body='📊 '+model['name']+' · '+model['status']+'\nTraffic used: '+values['used_traffic']+'\nTraffic remaining: '+values['remaining_traffic']+'\nService remaining: '+values['remaining_time']+'\nExpires: '+values['expires']+'\n\nYour private service page:\n'+model['portal_url']
    if links:
        for row in model['links']:
            extra='\n\n'+row['name']+':\n'+row['url']
            if len((body+extra).encode('utf-16-le'))//2>3500:break
            body+=extra
        body+='\n\nAll links and QR formats are on your private service page.'
    return body



class Worker:
    def __init__(self,store,runtime,access):
        self.store,self.runtime,self.access=store,runtime,access
        self.last_poll=0;self.poll_wait=10;self.chat_times={}
        self.sync_contacts()

    def sync_contacts(self):
        # Also repairs contacts for accounts paired before this version.
        with self.runtime.lock:
            state=self.store.get('state');fingerprint=bot_hash(self.store)
            with self.store.connect() as db:
                bindings={row[0]:(row[1],row[2]) for row in db.execute('SELECT client_id,chat_id,capability FROM client_bot_bindings WHERE bot_hash=?',(fingerprint,))}
                changed={client['id']:bindings[client['id']][0] for client in state['clients'] if client['id'] in bindings and secrets.compare_digest(bindings[client['id']][1],client_portal.token(client)) and client.get('telegram_id')!=bindings[client['id']][0]}
                if not changed:return
                previous=state['revision'];state['revision']+=1
                for client in state['clients']:
                    if client['id'] in changed:client['telegram_id']=changed[client['id']]
                db.execute("UPDATE kv SET value=? WHERE key='state'",(json.dumps(state),))
                active=self.store.get('active')
                if active:
                    for client in active['clients']:
                        if client['id'] in changed:client['telegram_id']=changed[client['id']]
                    if active['revision']==previous:active['revision']=state['revision']
                    db.execute("UPDATE kv SET value=? WHERE key='active'",(json.dumps(active),))
            if active:self.runtime.active=active

    def model(self,state,client,totals=None):
        # Public connection URLs come only from saved access settings, never a bot message.
        info=self.access.info();address=(info.get('public_host') or state['settings'].get('server_address') or 'localhost').strip('[]')
        current='http://'+('['+address+']' if ':' in address else address)+'/'
        return client_portal.data(state,self.access,current,client,self.runtime.traffic_totals(refresh=True) if totals is None else totals)

    def process_update(self,update):
        message=update.get('message',{}) if isinstance(update,dict) else {};chat=message.get('chat',{});sender=message.get('from',{})
        if chat.get('type')!='private' or type(chat.get('id')) is not int or chat['id']<=0 or chat['id']!=sender.get('id') or sender.get('is_bot') or message.get('forward_origin'):return
        if not isinstance(message.get('date'),int) or not time.time()-900<=message['date']<=time.time()+60:return
        text=message.get('text','');require(isinstance(text,str),'Invalid bot text')
        if len(text)>512:return
        chat_id=str(chat['id']);now=time.time()
        if len(self.chat_times)>=2048:
            self.chat_times={key:at for key,at in self.chat_times.items() if now-at<60}
            if chat_id not in self.chat_times and len(self.chat_times)>=2048:return
        if now-self.chat_times.get(chat_id,0)<3:return
        self.chat_times[chat_id]=now
        token=notifications.settings(self.store)['bot_token'];state=self.store.get('state')
        qr_model=None
        command,_,argument=text.strip().partition(' ');command=command.split('@',1)[0];argument=argument.strip()
        reply='Open your private NARA service page and choose Connect Telegram, then press Start. After pairing, use /status, /links or /unlink. A username alone cannot grant account access.'
        if command=='/start' and re.fullmatch(r'[A-Za-z0-9_-]{43}',argument):
            with self.runtime.lock, self.store.connect() as db:
                state=self.store.get('state')
                nonce=hashlib.sha256(argument.encode()).hexdigest()
                row=db.execute('SELECT client_id,capability,bot_hash FROM client_bot_pairs WHERE token_hash=? AND expires>?',(nonce,now)).fetchone()
                client=next((c for c in state['clients'] if row and c['id']==row[0]),None)
                if client and row[2]==bot_hash(self.store) and secrets.compare_digest(row[1],client_portal.token(client)):
                    # A pair can be consumed once, even with concurrent update delivery.
                    deleted=db.execute('DELETE FROM client_bot_pairs WHERE token_hash=?',(nonce,)).rowcount
                    if deleted:
                        db.execute('INSERT OR REPLACE INTO client_bot_bindings VALUES(?,?,?,?,?)',(client['id'],chat_id,row[2],row[1],now))
                        # Verified Telegram sender ID is contact metadata, never an auth credential.
                        previous_revision=state['revision'];client['telegram_id']=chat_id;state['revision']+=1
                        db.execute("UPDATE kv SET value=? WHERE key='state'",(json.dumps(state),))
                        active_row=db.execute("SELECT value FROM kv WHERE key='active'").fetchone()
                        active=json.loads(active_row[0]) if active_row else None
                        if active:
                            for item in active['clients']:
                                if item['id']==client['id']:item['telegram_id']=chat_id
                            if active['revision']==previous_revision:active['revision']=state['revision']
                            db.execute("UPDATE kv SET value=? WHERE key='active'",(json.dumps(active),))
                            self.runtime.active=active
                        reply='✅ Your service is connected. Use /status for traffic and time, /links for connection access, or /unlink to disconnect this chat.'
        else:
            with self.store.connect() as db:records={row[0]:row[1] for row in db.execute('SELECT client_id,capability FROM client_bot_bindings WHERE chat_id=? AND bot_hash=?',(chat_id,bot_hash(self.store)))}
            owned=[client for client in state['clients'] if client['id'] in records and secrets.compare_digest(records[client['id']],client_portal.token(client))]
            if argument and text.startswith('/'):owned=[client for client in owned if client['name']==argument]
            if command=='/unlink':
                for client in owned:unpair(self.store,client['id'])
                reply='This chat is disconnected from the selected service accounts.'
            elif command in ('/status','/links') or not text.startswith('/'):
                if not text.startswith('/'):owned=[client for client in owned if client['name']==text.strip()]
                if owned:
                    totals=self.runtime.traffic_totals(refresh=True);models=[self.model(state,client,totals) for client in owned[:5]]
                    parts=[]
                    for model in models:
                        part=service_text(model,command=='/links')
                        if parts and len(('\n\n'.join(parts+[part])).encode('utf-16-le'))//2>3500:break
                        parts.append(part)
                    reply='\n\n'.join(parts)
                    if len(parts)<len(owned):reply+='\n\nFor another linked service, send /status USERNAME or /links USERNAME.'
                    if command=='/links':qr_model=models[0]
        notifications.send(token,chat_id,reply)
        if qr_model:notifications.send_photo(token,chat_id,qr_png(qr_model['portal_url']))
    def remember_chats(self,update):
        chats=self.store.get('client_bot_chats',[])
        for kind in ('message','edited_message','channel_post','my_chat_member'):
            source=update.get(kind,{})
            chat=source.get('chat',{}) if isinstance(source,dict) else {}
            if type(chat.get('id')) is not int:continue
            ident=str(chat['id']);chats=[row for row in chats if row.get('id')!=ident]
            chats.append({'id':ident,'name':str(chat.get('title') or chat.get('first_name') or chat.get('username') or ident)[:128]})
        self.store.set('client_bot_chats',chats[-20:])

    def poll(self):
        value=settings(self.store)
        if not value['bot_enabled'] or value.get('bot_fingerprint')!=bot_hash(self.store):return
        token=notifications.settings(self.store)['bot_token'];fingerprint=bot_hash(self.store)
        previous=self.store.get('client_bot_offset',{});offset=previous.get('offset',0) if previous.get('bot_hash')==fingerprint else 0
        updates=notifications.call(token,'getUpdates',{'offset':offset,'limit':20,'timeout':0,'allowed_updates':['message','edited_message','channel_post','my_chat_member']})
        require(isinstance(updates,list),'Unexpected bot updates')
        for update in updates:
            if not isinstance(update,dict) or type(update.get('update_id')) is not int:continue
            try:self.remember_chats(update);self.process_update(update)
            finally:
                offset=max(offset,update['update_id']+1);self.store.set('client_bot_offset',{'bot_hash':fingerprint,'offset':offset})
        self.bot_status(True)

    def deliver(self):
        now=time.time();value=settings(self.store)
        with self.store.connect() as db:
            db.execute("UPDATE client_messages SET status='expired' WHERE status='queued' AND created<?",(now-86400,))
            row=db.execute("SELECT id,client_id,channel,recipient,template_id,attempts,stage FROM client_messages WHERE status='queued' AND available<=? ORDER BY id LIMIT 1",(now,)).fetchone()
        if not row:return
        ident,client_id,channel,recipient,template_id,attempts,stage=row;state=self.store.get('state');client=next((c for c in state['clients'] if c['id']==client_id),None)
        valid=client and (value['smtp_enabled'] and client.get('email')==recipient if channel=='email' else value['bot_enabled'] and binding(self.store,client)==recipient)
        if not valid:
            with self.store.connect() as db:db.execute("UPDATE client_messages SET status='cancelled' WHERE id=?",(ident,))
            return
        try:
            model=self.model(state,client)
            if channel=='email':
                template=next((row for row in value['templates'] if row['id']==template_id),None);require(template is not None,'Saved template was removed')
                message=email_message(value,recipient,template,model);connection=smtp_connect(value)
                try:connection.send_message(message,from_addr=value['from_email'],to_addrs=[recipient])
                finally:connection.close()
            else:
                token=notifications.settings(self.store)['bot_token']
                if stage==0:
                    notifications.send(token,recipient,service_text(model,True))
                    with self.store.connect() as db:db.execute('UPDATE client_messages SET stage=1 WHERE id=?',(ident,))
                notifications.send_photo(token,recipient,qr_png(model['portal_url']))
            with self.store.connect() as db:db.execute("UPDATE client_messages SET status='sent',attempts=attempts+1,error='' WHERE id=? AND status='queued'",(ident,))
        except (ValueError,OSError,smtplib.SMTPException):
            with self.store.connect() as db:db.execute("UPDATE client_messages SET status=?,attempts=attempts+1,available=?,error=? WHERE id=? AND status='queued'",('failed' if attempts>=2 else 'queued',now+60*2**attempts,'Delivery failed; check SMTP or bot settings and recipient access',ident))

    def bot_status(self,ok):
        previous=self.store.get('client_bot_status',{});now=time.time()
        if previous.get('ok')!=ok or now-previous.get('checked_at',0)>60:
            self.store.set('client_bot_status',{'ok':ok,'checked_at':now,**({} if ok else {'error':'Bot commands unavailable. Check token, webhook and whether another server is polling this bot.'})})

    def run(self):
        while not self.runtime.shutdown.is_set():
            self.store.client_delivery_wakeup.clear();active=False
            try:
                value=settings(self.store);active=value['smtp_enabled'] or value['bot_enabled']
                if active:self.deliver()
                if value['bot_enabled'] and time.monotonic()-self.last_poll>=self.poll_wait:
                    self.last_poll=time.monotonic()
                    try:self.poll();self.poll_wait=10
                    except ValueError:self.bot_status(False);self.poll_wait=min(300,self.poll_wait*2)
            except Exception:
                # Never include SMTP credentials, connection URLs or message text in logs.
                pass
            self.store.client_delivery_wakeup.wait(3 if active else 60)
