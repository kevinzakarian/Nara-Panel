"""Administrator profile and reauthenticated security operations."""
import hashlib
import json
import re
import time
from . import security
from .store import password_matches,password_hash
from .config import require


def verify(store, admin, data, session):
    bucket='reauth:'+hashlib.sha256(session.encode()).hexdigest()
    now=time.time();attempts=[stamp for stamp in store.get(bucket,[]) if now-stamp<300]
    require(len(attempts)<5,'Too many security attempts; wait five minutes')
    attempts.append(now);store.set(bucket,attempts)
    password=data.get('current','')
    require(isinstance(password,str) and len(password)<=256 and password_matches(password,admin['password']), 'Current password is incorrect')
    require(security.verify_factor(admin,data.get('code','')), 'Enter a fresh authenticator code or an unused recovery code')
    store.set('admin',admin)  # Consume a valid factor even if a later operation fails.
    store.set(bucket,[])


def save(store, admin, session=None):
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO kv VALUES('admin',?)",(json.dumps(admin),))
        if session:
            db.execute('DELETE FROM sessions WHERE token!=?',(hashlib.sha256(session.encode()).hexdigest(),))
        else:db.execute('DELETE FROM sessions')


def action(store, path, data, session):
    admin=store.get('admin')
    if path=='avatar':
        admin['avatar']=security.validate_avatar(data.get('avatar'))
        store.set('admin',admin)
        return {'profile':security.public_admin(admin)}
    if path=='credentials':
        username=data.get('username',admin['username']);password=data.get('password','')
        require(isinstance(username,str) and re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',username),'Username must contain 1–64 letters, numbers, dots, underscores, @ or hyphens')
        require(isinstance(password,str) and (not password or 12<=len(password)<=256),'Password must contain 12–256 characters')
        require(password or username!=admin['username'],'Enter a new username or password')
        if password and 'password_confirm' in data:require(password==data['password_confirm'],'New passwords do not match')
        verify(store,admin,data,session)
        admin['username']=username
        if password:admin['password']=password_hash(password)
        admin.pop('totp_pending',None)
        save(store,admin)
        store.audit('Administrator credentials changed; browser sessions revoked')
        return {'ok':True,'signed_out':True}
    if path=='2fa/setup':
        require(not admin.get('totp_secret'),'Two-factor authentication is already enabled')
        verify(store,admin,data,session)
        secret=security.totp_secret()
        admin['totp_pending']={'secret':secret,'expires':time.time()+600,'session':hashlib.sha256(session.encode()).hexdigest()}
        store.set('admin',admin)
        return {'secret':secret,'uri':security.otp_uri(secret,admin['username']),'expires_in':600}
    if path=='2fa/enable':
        require(not admin.get('totp_secret'),'Two-factor authentication is already enabled')
        pending=admin.get('totp_pending',{})
        require(pending.get('expires',0)>time.time() and pending.get('session')==hashlib.sha256(session.encode()).hexdigest(), 'Setup expired or belongs to another session; generate a new setup code')
        require(pending.get('attempts',0)<5,'Too many verification attempts; generate a new setup code')
        verify(store,admin,data,session)
        pending['attempts']=pending.get('attempts',0)+1
        store.set('admin',admin)
        counter=security.totp_counter(pending['secret'],data.get('totp_code',''))
        require(counter is not None,'Verification code is incorrect; check the phone and server clocks')
        codes,hashes=security.recovery_codes()
        admin.update(totp_secret=pending['secret'],totp_last=counter,recovery_hashes=hashes)
        admin.pop('totp_pending',None);save(store,admin,session)
        store.audit('Two-factor authentication enabled; other sessions revoked')
        return {'profile':security.public_admin(admin),'recovery_codes':codes}
    if path in ('2fa/disable','2fa/recovery'):
        require(admin.get('totp_secret'),'Two-factor authentication is not enabled')
        verify(store,admin,data,session)
        codes=[]
        if path=='2fa/disable':
            for name in ('totp_secret','totp_last','totp_pending','recovery_hashes'):admin.pop(name,None)
        else:codes,admin['recovery_hashes']=security.recovery_codes()
        save(store,admin,session)
        store.audit('Two-factor recovery codes regenerated' if codes else 'Two-factor authentication disabled')
        return {'profile':security.public_admin(admin),**({'recovery_codes':codes} if codes else {})}
    raise ValueError('Unknown administrator operation')
