"""Credential-bearing share links and spreadsheet-safe CSV exports."""
import base64
import csv
import io
import json
import time
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from .config import client_config, expiry, require


def links(state, client, totals):
    if not state['settings'].get('server_address') or not any(row.get('mode')!='native' and row.get('enabled',True) and row['id'] in client.get('inbound_ids',[]) for row in state['inbounds']):
        return []
    # Administrators may export disabled, expired or exhausted accounts. Generating
    # a share link never re-enables the account or bypasses subscription eligibility.
    candidate={**client,'enabled':True,'expires_at':'','quota_bytes':0}
    config = client_config(state, candidate, {})
    result = []
    for item in config['outbounds']:
        protocol = item['type']
        if protocol not in ('vless','vmess','trojan','hysteria2','tuic','anytls'):
            continue
        tls = item.get('tls', {})
        transport = item.get('transport', {})
        server = item['server']; port = item['server_port']; tag = item['tag']
        host = '['+server+']' if ':' in server else server
        query = {}
        if tls.get('enabled'):
            query['security']='tls'
            if tls.get('server_name'):query['sni']=tls['server_name']
            if tls.get('insecure'):query['allowInsecure']='1'
            if tls.get('alpn'):query['alpn']=','.join(tls['alpn'])
        if transport:
            query['type']=transport['type']
            if transport.get('path'):query['path']=transport['path']
            if transport.get('headers',{}).get('Host'):query['host']=transport['headers']['Host']
            if transport.get('service_name'):query['serviceName']=transport['service_name']
        if protocol=='vmess':
            vmess={'v':'2','ps':tag,'add':server,'port':str(port),'id':item['uuid'],'aid':'0',
                   'scy':item.get('security','auto'),'net':transport.get('type','tcp'),'type':'none',
                   'host':query.get('host',''),'path':query.get('path',query.get('serviceName','')),
                   'tls':'tls' if tls.get('enabled') else '', 'sni':tls.get('server_name',''),
                   'alpn':query.get('alpn',''), 'allowInsecure':bool(tls.get('insecure'))}
            uri='vmess://'+base64.b64encode(json.dumps(vmess,separators=(',',':')).encode()).decode()
        else:
            auth = item.get('uuid','') if protocol in ('vless','tuic') else item.get('password','')
            if protocol=='tuic':auth+=':'+item['password']
            if item.get('flow'):query['flow']=item['flow']
            if protocol=='vless':query['encryption']='none'
            if protocol=='hysteria2':
                if tls.get('insecure'):query['insecure']='1'
                if item.get('obfs'):
                    query.update(obfs=item['obfs']['type'], **{'obfs-password':item['obfs']['password']})
            if protocol=='tuic':
                for key in ('congestion_control','udp_relay_mode'):
                    if item.get(key):query[key]=item[key]
            uri=protocol+'://'+quote(auth,safe=':')+'@'+host+':'+str(port)+('?' + urlencode(query) if query else '')+'#'+quote(tag,safe='')
        result.append({'name':tag,'protocol':protocol,'url':uri})
    return result


def subscription_base(state, access, current):
    conf=state['settings']; info=access.info()
    custom=conf.get('subscription_url','').strip()
    if custom:
        parsed=urlsplit(custom)
        base=custom.rstrip('/') if parsed.path not in ('','/') else custom.rstrip('/')+info['sub_path']
    else:
        parsed=urlsplit(conf.get('public_url') or current)
        host=info.get('subscription_host') or info.get('public_host') or parsed.hostname
        require(bool(host), 'Set the public subscription address first')
        host='['+host+']' if ':' in host else host
        base=info.get('subscription_scheme','http')+'://'+host+':'+str(info['subscription_port'])+info['sub_path']
    return base.rstrip('/')


def safe_cell(value):
    value=str(value)
    # Excel/LibreOffice formulas can start after leading whitespace or controls.
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t','\r','\n')):
        value="'"+value
    return value


def export(store, access, current, ids=None):
    state=store.get('state'); totals=store.totals()
    require(ids is None or isinstance(ids,list) and len(ids)<=1000 and all(isinstance(x,str) for x in ids),'Invalid export selection')
    chosen=set(ids) if ids is not None else None
    output=io.StringIO(newline='');writer=csv.writer(output)
    writer.writerow(['Username','Subscription link','JSON subscription link','Config links','Remaining months (30 days)','Total allowance (GiB; 0=unlimited)'])
    base=subscription_base(state,access,current)
    for client in state['clients']:
        if chosen is not None and client['id'] not in chosen:continue
        url=base+'/'+quote(client['token'],safe='')
        remote='sing-box://import-remote-profile?url='+quote(url,safe='')+'#'+quote(client['name'],safe='')
        remaining=round(max(0,expiry(client.get('expires_at'))-time.time())/(30*86400),3) if client.get('expires_at') else 'Unlimited'
        configs='\n'.join(item['url'] for item in links(state,client,totals))
        writer.writerow([safe_cell(x) for x in (client['name'],remote,url,configs,remaining,client.get('quota_bytes',0)/1024**3)])
    return output.getvalue()
