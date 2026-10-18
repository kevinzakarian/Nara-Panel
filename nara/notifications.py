"""Opt-in Telegram notifications, persisted outbox and low-frequency health checks."""
import datetime as dt
import json
import re
import sqlite3
import time
from urllib import error, request

EVENTS={
 'panel_started':('🚀','Panel started'), 'core_up':('🟢','Core is running'), 'core_down':('🔴','Core stopped'),
 'login':('🔐','Administrator signed in'), 'login_failed':('🛡️','Sign-in attempt rejected'),
 'admin_changed':('🔑','Administrator security changed'), 'api_key':('🔌','API access changed'),
 'clients_created':('👥','Clients created'), 'clients_updated':('✏️','Clients updated'), 'clients_deleted':('🗑️','Clients deleted'),
 'config_saved':('✅','Configuration applied'), 'apply_failed':('⚠️','Configuration rejected'),
 'quota_warning':('📊','Traffic allowance is running low'), 'quota_reached':('⛔','Traffic allowance reached'),
 'expiry_warning':('⏳','Account expires soon'), 'expired':('⌛','Account expired'),
 'resource_alert':('🚨','Server resource alert'), 'resource_recovery':('🌿','Server resources recovered'),
 'daily_summary':('📬','Your daily NARA overview'), 'test':('🎉','NARA notifications are connected')}


def settings(store):
    return {'enabled':False,'bot_token':'','chat_id':'','events':[x for x in EVENTS if x!='test'],
            'summary_hour':9,**(store.get('telegram') or {})}


def public_settings(store):
    value=settings(store);value['token_configured']=bool(value.pop('bot_token',''))
    value['delivery']=store.get('telegram_delivery',{})
    with store.connect() as db:
        value['recent']=[{'event':r[0],'created':r[1],'status':r[2],'attempts':r[3]} for r in
                         db.execute('SELECT event,created,status,attempts FROM notifications ORDER BY id DESC LIMIT 10')]
    return value


def validate_settings(data, previous):
    if not isinstance(data,dict):raise ValueError('Invalid Telegram settings')
    value={**previous,**{k:v for k,v in data.items() if k in ('enabled','chat_id','events','summary_hour')}}
    if data.get('bot_token'):value['bot_token']=data['bot_token']
    if data.get('clear_token') is True:value['bot_token']=''
    if type(value['enabled']) is not bool:raise ValueError('Invalid notification enabled state')
    if not isinstance(value['events'],list) or len(value['events'])>len(EVENTS) or any(x not in EVENTS or x=='test' for x in value['events']):raise ValueError('Choose supported notification events')
    if type(value['summary_hour']) is not int or not 0<=value['summary_hour']<=23:raise ValueError('Choose a daily summary hour from 0 to 23 UTC')
    token=value.get('bot_token','');chat=value.get('chat_id','')
    if not isinstance(token,str) or token and not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{20,100}',token):raise ValueError('Enter a valid BotFather bot token')
    if not isinstance(chat,str) or chat and not re.fullmatch(r'-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31}',chat):raise ValueError('Enter a numeric Chat ID or @channel username')
    if value['enabled'] and not (token and chat):raise ValueError('Bot token and Chat ID are required before enabling notifications')
    return value


def enqueue(store, event, detail='', dedupe=None, window=900):
    value=settings(store)
    if not value['enabled'] or event not in EVENTS or event!='test' and event not in value['events']:return False
    now=time.time()
    # Details are constructed from explicit, non-secret fields by each caller.
    payload={'detail':str(detail)[:1800]}
    with store.connect() as db:
        if dedupe:
            key='notice:'+dedupe
            row=db.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            if row and now-float(json.loads(row[0]))<window:return False
            db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,json.dumps(now)))
        db.execute('INSERT INTO notifications(event,payload,created,available) VALUES(?,?,?,?)',(event,json.dumps(payload),now,now))
        db.execute('DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications ORDER BY id DESC LIMIT 500)')
    store.notification_wakeup.set()
    return True


def emit(store,event,detail='',dedupe=None,window=900):
    try:return enqueue(store,event,detail,dedupe,window)
    except (sqlite3.Error,OSError):return False


class DeliveryError(ValueError):
    def __init__(self,message,retry_after=0):super().__init__(message);self.retry_after=retry_after


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None


def call(token,method,payload):
    body=json.dumps(payload).encode()
    req=request.Request('https://api.telegram.org/bot'+token+'/'+method,body,{'Content-Type':'application/json'},method='POST')
    try:
        with request.build_opener(request.ProxyHandler({}),NoRedirect()).open(req,timeout=10) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise DeliveryError('Telegram returned an unexpected response')
            value=json.loads(raw)
            if value.get('ok') is not True:raise DeliveryError('Telegram rejected this request')
            return value.get('result')
    except error.HTTPError as exc:
        code=exc.code; delay=0
        if code==429:
            try:delay=min(3600,max(1,int(json.loads(exc.read(4096)).get('parameters',{}).get('retry_after',60))))
            except (ValueError,TypeError,AttributeError):delay=60
        exc.close()
        message={400:'Check the Chat ID and start the bot first',401:'Bot token is invalid',403:'The bot cannot post to this chat',429:'Telegram rate limit; delivery will retry',409:'This bot uses a webhook. Enter the Chat ID manually or use a dedicated bot'}.get(code,'Telegram is temporarily unavailable')
        raise DeliveryError(message,delay) from None
    except (error.URLError,OSError,ValueError,TypeError,AttributeError) as exc:
        if isinstance(exc,DeliveryError):raise
        raise DeliveryError('Could not reach Telegram; check outbound HTTPS access') from None


def send(token,chat_id,message):
    call(token,'sendMessage',{'chat_id':chat_id,'text':message[:4000],'link_preview_options':{'is_disabled':True}})


def bot_info(token):
    value=call(token,'getMe',{})
    if not isinstance(value,dict) or value.get('is_bot') is not True or not isinstance(value.get('username'),str):
        raise DeliveryError('Telegram returned an unexpected bot identity')
    return {'username':value['username'][:64], 'name':str(value.get('first_name',''))[:128]}


def chats(token):
    value=call(token,'getUpdates',{'limit':20,'timeout':0})
    if not isinstance(value,list):raise DeliveryError('Telegram returned an unexpected chat list')
    result={}
    for item in value:
        if not isinstance(item,dict):continue
        for key in ('message','channel_post','my_chat_member','edited_message'):
            chat=item.get(key,{}).get('chat',{})
            if type(chat.get('id')) is int:
                ident=str(chat['id'])
                result[ident]={'id':ident,'name':str(chat.get('title') or chat.get('first_name') or chat.get('username') or ident)[:128]}
    return list(result.values())


def text(event,payload):
    symbol,title=EVENTS[event]
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d · %H:%M UTC')
    return f'{symbol} NARA · {title}\n\n{payload.get("detail", "")}\n\n{stamp}'.replace('\n\n\n','\n\n')


class Worker:
    def __init__(self,store,runtime):
        self.store,self.runtime=store,runtime
        self.last_poll=0;self.previous_core=None;self.resource_samples={};self.resource_alerts=set()
        from .runtime import Metrics
        self.metrics=Metrics()

    def poll(self,now=None,config=None):
        now=time.time() if now is None else now
        config=config or settings(self.store)
        if not config['enabled']:return
        running=self.runtime.running
        if self.previous_core is not None and self.previous_core!=running:
            enqueue(self.store,'core_up' if running else 'core_down','Proxy connections are available.' if running else 'Check Overview and the private core log. Existing settings are retained.')
        self.previous_core=running
        state=self.store.get('state');totals=self.store.totals()
        from .config import expiry,eligible
        for row in state['clients']:
            if not row.get('enabled',True):continue
            usage=totals.get(row['id'],{});used=usage.get('upload',0)+usage.get('download',0);quota=row.get('quota_bytes',0)
            if quota and used>=quota*0.8:
                event='quota_reached' if used>=quota else 'quota_warning'
                enqueue(self.store,event,f'Client: {row["name"]}\nUsed: {used/1024**3:.2f} GiB / {quota/1024**3:.2f} GiB',f'{event}:{row["id"]}:{quota}',86400)
            expires=expiry(row.get('expires_at'))
            if expires and expires-now<=86400:
                event='expired' if expires<=now else 'expiry_warning'
                enqueue(self.store,event,f'Client: {row["name"]}\nExpiry: {dt.datetime.fromtimestamp(expires,dt.timezone.utc).isoformat()}',f'{event}:{row["id"]}:{expires}',86400)
        if 'resource_alert' in config['events'] or 'resource_recovery' in config['events']:
            m=self.metrics.read(self.store.directory)
            values={'CPU':m.get('cpu_percent'),'Memory':100*m['memory_used']/m['memory_total'] if m.get('memory_total') else None,
                    'Disk':100*m['disk_used']/m['disk_total'] if m.get('disk_total') else None}
            for name,value in values.items():
                if value is None:continue
                self.resource_samples[name]=self.resource_samples.get(name,0)+1 if value>=90 else 0
                if self.resource_samples[name]>=3 and name not in self.resource_alerts:
                    enqueue(self.store,'resource_alert',f'{name} usage is {value:.0f}%. Check the server workload and available capacity.',name+':high',3600)
                    self.resource_alerts.add(name)
                elif value<80 and name in self.resource_alerts:
                    enqueue(self.store,'resource_recovery',f'{name} usage returned to {value:.0f}%.',name+':recovered',3600)
                    self.resource_alerts.remove(name)
        utc=dt.datetime.fromtimestamp(now,dt.timezone.utc)
        if utc.hour>=config['summary_hour']:
            active=sum(eligible(row,totals,now) for row in state['clients'])
            used=sum(x.get('upload',0)+x.get('download',0) for x in totals.values())
            enqueue(self.store,'daily_summary',f'Core: {"Running 🟢" if running else "Stopped 🔴"}\nClients: {len(state["clients"])} · Active: {active}\nRecorded traffic: {used/1024**3:.2f} GiB\nYou’re in control. Have a great day!', 'daily:'+utc.date().isoformat(),90000)
        # Deduplication keys are bounded independently of changing client IDs.
        with self.store.connect() as db:
            db.execute("DELETE FROM kv WHERE key LIKE 'notice:%' AND CAST(value AS REAL)<?",(now-7*86400,))

    def deliver(self,config=None):
        config=config or settings(self.store)
        if not config['enabled']:return
        now=time.time()
        if self.store.get('telegram_throttle',0)>now:return
        with self.store.connect() as db:
            row=db.execute("SELECT id,event,payload,attempts FROM notifications WHERE status='queued' AND available<=? AND created>? ORDER BY id LIMIT 1",(now,now-86400)).fetchone()
            db.execute("UPDATE notifications SET status='expired' WHERE status='queued' AND created<=?",(now-86400,))
        if not row:return
        ident,event,payload,attempts=row
        if event!='test' and event not in config['events']:
            with self.store.connect() as db:db.execute("UPDATE notifications SET status='cancelled' WHERE id=?",(ident,))
            return
        try:
            send(config['bot_token'],config['chat_id'],text(event,json.loads(payload)))
            with self.store.connect() as db:db.execute("UPDATE notifications SET status='sent',attempts=attempts+1 WHERE id=?",(ident,))
            self.store.set('telegram_delivery',{'at':now,'ok':True,'message':'Notification delivered'})
        except DeliveryError as exc:
            if exc.retry_after:self.store.set('telegram_throttle',now+exc.retry_after)
            count=attempts+1; delay=max(exc.retry_after,min(1800,30*2**count))
            with self.store.connect() as db:db.execute("UPDATE notifications SET status=?,attempts=?,available=? WHERE id=?",('failed' if count>=6 else 'queued',count,now+delay,ident))
            self.store.set('telegram_delivery',{'at':now,'ok':False,'message':str(exc)})

    def run(self):
        from . import __version__
        emit(self.store,'panel_started','Version '+__version__+' is ready. Your settings and client accounts are available.')
        while not self.runtime.shutdown.is_set():
            self.store.notification_wakeup.clear()
            delay=30
            try:
                now=time.time();config=settings(self.store)
                if config['enabled']:
                    if now-self.last_poll>=30:
                        self.poll(now,config);self.last_poll=now
                    self.deliver(config)
                    with self.store.connect() as db:
                        row=db.execute("SELECT MIN(available) FROM notifications WHERE status='queued'").fetchone()
                    throttle=self.store.get('telegram_throttle',0)
                    due=max(row[0],throttle) if row and row[0] is not None else now+30
                    delay=max(1,min(30,due-time.time(),30-(time.time()-self.last_poll)))
            except Exception:
                # Keep raw exceptions, request URLs, keys and credentials out of logs.
                self.store.set('telegram_delivery',{'at':time.time(),'ok':False,'message':'Notification worker could not complete this check'})
            self.store.notification_wakeup.wait(delay)
