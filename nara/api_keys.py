"""Revocable, expiring, scoped machine credentials; raw keys are returned once."""
import hashlib
import json
import secrets
import time
import uuid
from .config import require

SCOPES={'read':'Read status and configuration (credentials hidden)', 'clients:write':'Create, edit, group and bulk-manage clients',
        'config:write':'Edit inbounds, TLS, DNS, routing and core settings', 'core:control':'Validate, start and stop the core',
        'panel:manage':'Update panel software and change access paths/ports',
        'secrets:read':'Read passwords, private keys, profiles and subscription credentials'}


def listing(store):
    with store.connect() as db:
        return [{'id':r[0],'name':r[1],'scopes':json.loads(r[2]),'created':r[3],'expires':r[4],
                 'last_used':r[5],'revoked':bool(r[6])} for r in db.execute('SELECT id,name,scopes,created,expires,last_used,revoked FROM api_keys ORDER BY created DESC')]


def create(store,data):
    name=data.get('name');scopes=data.get('scopes');days=data.get('days',90)
    require(isinstance(name,str) and 1<=len(name.strip())<=64,'API key name must contain 1–64 characters')
    require(isinstance(scopes,list) and scopes and all(isinstance(x,str) and x in SCOPES for x in scopes),'Choose supported API permissions')
    require(type(days) is int and 1<=days<=365,'API keys must expire in 1–365 days')
    ident=uuid.uuid4().hex;raw='nara_'+secrets.token_urlsafe(32);now=time.time();scopes=sorted(set(scopes))
    with store.connect() as db:
        count=db.execute('SELECT COUNT(*) FROM api_keys WHERE revoked=0 AND expires>?',(now,)).fetchone()[0]
        require(count<50,'Revoke an unused API key first (50 active keys maximum)')
        db.execute('INSERT INTO api_keys(id,hash,name,scopes,created,expires) VALUES(?,?,?,?,?,?)',
                   (ident,hashlib.sha256(raw.encode()).hexdigest(),name.strip(),json.dumps(scopes),now,now+days*86400))
    return {'id':ident,'name':name.strip(),'key':raw,'scopes':scopes,'expires':now+days*86400}


def authenticate(store,authorization):
    if not isinstance(authorization,str) or not authorization.startswith('Bearer nara_') or len(authorization)>128:return None
    raw=authorization[7:]
    with store.connect() as db:
        row=db.execute('SELECT id,name,scopes,expires,revoked FROM api_keys WHERE hash=?',(hashlib.sha256(raw.encode()).hexdigest(),)).fetchone()
        if not row or row[4] or row[3]<=time.time():return None
        db.execute('UPDATE api_keys SET last_used=? WHERE id=?',(time.time(),row[0]))
        return {'id':row[0],'name':row[1],'scopes':json.loads(row[2])}


def revoke(store,ident):
    require(isinstance(ident,str),'Choose an API key')
    with store.connect() as db:
        cursor=db.execute('UPDATE api_keys SET revoked=1 WHERE id=?',(ident,))
        require(cursor.rowcount==1,'API key not found')
