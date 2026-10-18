"""Bounded, public-network-only destination previews. Importing never applies a config."""
import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from .config import host, require
from . import native

LIMIT = 1024 * 1024
PROTOCOLS = {'vless','vmess','trojan','hysteria2','tuic','anytls','shadowsocks','socks','http'}


def b64(value):
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True).decode('utf-8')
    except (ValueError, UnicodeError):
        raise ValueError('Invalid base64 connection data') from None


def public_addresses(name, port):
    try:
        addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)))
    except OSError:
        raise ValueError('Could not resolve the subscription host') from None
    require(addresses and all(ipaddress.ip_address(x).is_global for x in addresses),
            'External imports must use public Internet addresses; private and local destinations are blocked')
    return addresses


def fetch(url):
    deadline = time.monotonic() + 25
    for _ in range(4):
        parsed = urlsplit(url)
        require(parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment,
                'Use an HTTP or HTTPS subscription URL without user information')
        require(not any(ord(c)<33 or ord(c)==127 for c in url) and len(url)<=8192, 'Invalid subscription URL')
        port = parsed.port or (443 if parsed.scheme=='https' else 80)
        addresses = public_addresses(parsed.hostname, port)
        timeout = min(8, max(.1, deadline-time.monotonic()))
        require(deadline>time.monotonic(), 'Import timed out')
        connection = http.client.HTTPConnection(addresses[0], port, timeout=timeout)
        try:
            # Connect to the vetted IP, then verify TLS against the original DNS name.
            connection.connect()
            if parsed.scheme=='https':
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parsed.hostname)
            authority=('['+parsed.hostname+']' if ':' in parsed.hostname else parsed.hostname)+(':'+str(port) if parsed.port else '')
            connection.request('GET', (parsed.path or '/')+('?' +parsed.query if parsed.query else ''),
                               headers={'Host':authority,'User-Agent':'NARA destination preview','Accept-Encoding':'identity','Accept':'application/json, text/plain'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location');require(bool(location),'Subscription redirect has no destination')
                target=urljoin(url,location)
                require(not (parsed.scheme=='https' and urlsplit(target).scheme!='https'),'HTTPS imports cannot redirect to HTTP')
                url=target
                continue
            require(response.status==200,'Subscription server did not return a profile')
            require(response.getheader('Content-Encoding','identity').lower()=='identity','Compressed subscription responses are not supported')
            size=response.getheader('Content-Length')
            require(size is None or size.isdecimal() and int(size)<=LIMIT,'Subscription is too large')
            chunks=[];count=0
            while True:
                require(time.monotonic()<deadline,'Import timed out')
                connection.sock.settimeout(min(8,max(.1,deadline-time.monotonic()))) if connection.sock else None
                chunk=response.read(min(65536,LIMIT+1-count))
                if not chunk:break
                chunks.append(chunk);count+=len(chunk);require(count<=LIMIT,'Subscription is too large')
            return b''.join(chunks).decode('utf-8-sig')
        except (OSError, http.client.HTTPException, UnicodeError):
            raise ValueError('Could not securely download the subscription; check its address and TLS certificate') from None
        finally:
            connection.close()
    raise ValueError('Too many subscription redirects')


def uri(value):
    parsed=urlsplit(value);kind=parsed.scheme.lower()
    if kind=='hy2':kind='hysteria2'
    if kind=='ss':kind='shadowsocks'
    original_kind=kind
    if kind in ('socks5','socks4'):kind='socks'
    if kind=='https':kind='http'
    require(kind in PROTOCOLS,'Unsupported connection link protocol')
    if kind=='vmess':
        try: data=json.loads(b64(value.split('://',1)[1]))
        except (ValueError, TypeError):raise ValueError('Invalid VMess link') from None
        c={'type':'vmess','tag':data.get('ps') or 'imported-vmess','server':data.get('add'),'server_port':int(data.get('port',443)),
           'uuid':data.get('id'),'security':data.get('scy') or 'auto'}
        require(not int(data.get('aid') or 0),'Legacy VMess alterId is not supported')
        q={'sni':[data.get('sni') or data.get('host') or ''],'security':[data.get('tls') or ''],
           'type':[data.get('net') or 'tcp'],'path':[data.get('path') or ''],'host':[data.get('host') or ''],
           'alpn':[data.get('alpn') or ''],'allowInsecure':['1' if data.get('allowInsecure') in (True,1,'1','true') else '0']}
    else:
        if kind=='shadowsocks' and '@' not in parsed.netloc:
            decoded=b64(parsed.netloc);parsed=urlsplit('ss://'+decoded+parsed.path+('?' +parsed.query if parsed.query else '')+('#'+parsed.fragment if parsed.fragment else ''))
        q=parse_qs(parsed.query,keep_blank_values=True)
        c={'type':kind,'tag':unquote(parsed.fragment) or 'imported-'+kind,'server':parsed.hostname,'server_port':parsed.port or (443 if original_kind=='https' else {'socks':1080,'http':8080}.get(kind,443))}
        auth=unquote(parsed.username or '')
        if kind in ('vless','tuic'):c['uuid']=auth
        if kind=='tuic':c['password']=unquote(parsed.password or '')
        elif kind=='shadowsocks':
            credential=auth+(':'+unquote(parsed.password) if parsed.password is not None else '')
            if ':' not in credential:credential=b64(credential)
            require(':' in credential,'Shadowsocks link needs a method and password')
            c['method'],c['password']=credential.split(':',1)
            require('plugin' not in q,'Shadowsocks plugins need manual review and are not imported')
        elif kind in ('trojan','hysteria2','anytls'):c['password']=auth+(':'+unquote(parsed.password) if parsed.password is not None else '')
        elif kind in ('socks','http'):
            if auth:c['username']=auth
            if parsed.password:c['password']=unquote(parsed.password)
    if original_kind in ('socks4','socks5'):c['version']='4' if original_kind=='socks4' else '5'
    get=lambda key,default='':q.get(key,[default])[0]
    if original_kind=='https' or get('security') in ('tls','reality') or kind in ('trojan','hysteria2','tuic','anytls'):
        c['tls']={'enabled':True}
        if get('sni') or get('peer'):c['tls']['server_name']=get('sni') or get('peer')
        if get('insecure') in ('1','true') or get('allowInsecure') in ('1','true'):c['tls']['insecure']=True
        if get('alpn'):c['tls']['alpn']=get('alpn').split(',')
    if get('security')=='reality':
        require(kind=='vless' and bool(get('pbk')),'REALITY requires a VLESS public key')
        require(bool(re.fullmatch(r'[A-Za-z0-9_-]{43}',get('pbk'))) and bool(re.fullmatch(r'(?:[a-fA-F0-9]{2}){0,8}',get('sid'))),'Invalid REALITY public key or short ID')
        c['tls']['reality']={'enabled':True,'public_key':get('pbk'),'short_id':get('sid')}
    if get('fp') or get('security')=='reality':
        require(kind in ('vless','vmess','trojan'),'uTLS fingerprints apply to TLS-based TCP proxies')
        c.setdefault('tls',{'enabled':True})['utls']={'enabled':True,'fingerprint':get('fp','chrome')}
    transport=get('type','tcp')
    if transport not in ('','tcp','none'):
        require(transport in ('ws','http','httpupgrade','grpc','quic'),'Unsupported transport; use a full Sing-box JSON profile')
        c['transport']={'type':transport}
        if transport=='grpc':
            if get('serviceName') or get('path'):c['transport']['service_name']=get('serviceName') or get('path')
        else:
            if get('path'):c['transport']['path']=get('path')
            if get('host'):c['transport']['headers']={'Host':get('host')}
    if kind=='vless' and get('flow'):c['flow']=get('flow')
    if kind=='hysteria2' and get('obfs'):
        require(get('obfs')=='salamander','Unsupported Hysteria2 obfuscation')
        c['obfs']={'type':'salamander','password':get('obfs-password')}
    if kind=='tuic':
        for key in ('congestion_control','udp_relay_mode'):
            if get(key):c[key]=get(key)
    return c


def safe_config(config):
    require(isinstance(config,dict) and config.get('type') in PROTOCOLS,'Only individual proxy destinations can be imported')
    # Never import executable/file options or references into local panel resources.
    forbidden={'path','key_path','certificate_path','certificate_directory_path','private_key_path','identity_file','script','command',
               'detour','bind_interface','routing_mark','network_namespace','http_client','certificate_provider','download_detour','domain_resolver'}
    def visit(value,parent=''):
        if isinstance(value,dict):
            for key,item in value.items():
                require(isinstance(key,str) and not (key in forbidden and not (key=='path' and parent=='transport')) and not key.endswith('_path'),
                        'Imported profiles cannot reference local files, commands, interfaces or other panel resources')
                visit(item,key)
        elif isinstance(value,list):
            for item in value:visit(item,parent)
    visit(config)
    host(config.get('server',''))
    require(type(config.get('server_port')) is int and 1<=config['server_port']<=65535,'Invalid destination server port')
    tag=re.sub(r'[^a-zA-Z0-9_-]','-',str(config.get('tag') or 'imported'))[:64].strip('-') or 'imported'
    config={**config,'tag':tag}
    native.validate_record('outbounds',{'mode':'native','tag':config['tag'],'config':config})
    return config


def preview(value):
    require(isinstance(value,str) and 0<len(value)<=LIMIT,'Paste a connection link, subscription URL or Sing-box JSON profile')
    value=value.strip()
    if value.startswith('sing-box://import-remote-profile?'):
        value=parse_qs(urlsplit(value).query).get('url',[''])[0]
    if value.startswith(('https://','http://')) and urlsplit(value).username is None:value=fetch(value).strip()
    if value.startswith(('{','[')):
        try:data=json.loads(value)
        except ValueError:raise ValueError('Invalid Sing-box JSON profile') from None
        configs=data.get('outbounds',[data]) if isinstance(data,dict) else data
        require(isinstance(configs,list) and 0<len(configs)<=100,'A profile must contain 1–100 destinations')
        configs=[row for row in configs if isinstance(row,dict) and row.get('type') in PROTOCOLS]
    else:
        if '://' not in value:value=b64(value)
        lines=[x.strip() for x in value.splitlines() if x.strip()]
        require(0<len(lines)<=100,'A subscription must contain 1–100 connection links')
        configs=[uri(line) for line in lines]
    require(bool(configs),'No supported proxy destinations were found')
    result=[];used=set()
    for config in configs:
        clean=safe_config(config);base=clean['tag'];index=2
        while clean['tag'] in used:clean['tag']=base[:58]+'-'+str(index);index+=1
        used.add(clean['tag']);result.append(clean)
    return {'destinations':result}
