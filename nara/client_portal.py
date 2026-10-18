"""Read-only, per-account capabilities; no administrator session or API is exposed."""
import hashlib
import hmac
import re
import time
from urllib.parse import quote
from . import client_links
from .config import eligible, expiry, require


def token(client):
    # Domain-separated from the random subscription credential. Rotating the
    # subscription revokes the portal and outstanding bot pairing capabilities.
    return hmac.new(client['token'].encode(), b'nara-client-portal-v1', hashlib.sha256).hexdigest()


def find(state, capability):
    if not isinstance(capability,str) or not re.fullmatch(r'[a-f0-9]{64}', capability):return None
    return next((row for row in state['clients'] if hmac.compare_digest(token(row),capability)),None)


def url(state, access, current, client):
    return client_links.subscription_base(state,access,current)+'/portal/'+token(client)+'/'


def data(state, access, current, client, totals):
    usage=totals.get(client['id'],{});upload=usage.get('upload',0);download=usage.get('download',0)
    used=upload+download;quota=client.get('quota_bytes',0);end=expiry(client.get('expires_at'))
    now=time.time()
    status='Disabled' if not client.get('enabled',True) else 'Expired' if end and end<=now else 'Traffic limit reached' if quota and used>=quota else 'Active'
    json_url=client_links.subscription_base(state,access,current)+'/'+quote(client['token'],safe='')
    links=[{'name':'Sing-box app · remote profile','protocol':'subscription','url':'sing-box://import-remote-profile?url='+quote(json_url,safe='')+'#'+quote(client['name'],safe='')},
           {'name':'JSON subscription URL','protocol':'json','url':json_url},*client_links.links(state,client,totals)]
    return {'name':client['name'],'status':status,'enabled':eligible(client,totals),'upload':upload,'download':download,'used':used,
            'quota':quota,'remaining':max(0,quota-used) if quota else None,'expires_at':end or None,
            'remaining_seconds':max(0,end-now) if end else None,'links':links,'portal_url':url(state,access,current,client)}


def contact(value, kind):
    require(isinstance(value,str),'Invalid client contact')
    require(not any(ord(char)<32 or ord(char)==127 for char in value),'Client contacts must not contain control characters')
    value=value.strip()
    if kind=='email':
        require(not value or len(value)<=254 and bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",value)) and '..' not in value,
                'Enter a valid email address without spaces or line breaks')
    else:
        require(not value or bool(re.fullmatch(r'(?:@[A-Za-z][A-Za-z0-9_]{4,31}|[1-9][0-9]{0,19})',value)),
                'Telegram contact must be an @username or a numeric user ID; delivery needs verified bot pairing')
    return value
