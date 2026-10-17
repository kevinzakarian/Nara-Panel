"""Versioned automation API, sharing the browser's validation/apply transaction."""
import copy
import json
import re
import time
import uuid
from urllib.parse import parse_qs,urlsplit
from . import __version__,api_keys,native,clients,notifications
from .config import require,build_config,client_config,eligible

RESOURCES={'clients':'clients','groups':'client_groups','inbounds':'inbounds','tls':'tls',
 'dns/servers':'dns_servers','dns/rules':'dns_rules','rule-sets':'rule_sets','routing/rules':'route_rules',
 'outbounds':'outbounds','endpoints':'endpoints','services':'services','certificate-providers':'certificate_providers',
 'http-clients':'http_clients','network-namespaces':'network_namespaces'}
OPTIONS=('log','dns','ntp','certificate','route','experimental')
SECRET_NAMES={'password','passwords','uuid','token','tokens','auth','auth_str','authorization','cookie','headers','key','private_key',
              'private_keys','secret_key','preshared_key','pre_shared_key','license','secret','access_key_secret','api_key','api_token','mac_key','client_secret'}


class Fault(ValueError):
    def __init__(self,status,code,message):self.status,self.code,self.message=status,code,message


def visible(value,secrets=False):
    if secrets:return copy.deepcopy(value)
    if isinstance(value,dict):
        return {k:visible(v) for k,v in value.items() if k.lower() not in SECRET_NAMES and
                not any(k.lower().endswith(suffix) for suffix in ('_password','_token','_secret','_private_key'))}
    if isinstance(value,list):return [visible(v) for v in value]
    if isinstance(value,str) and 'PRIVATE KEY-----' in value:return '[redacted]'
    return value


def merge_patch(previous,patch):
    if not isinstance(patch,dict):return copy.deepcopy(patch)
    result=copy.deepcopy(previous) if isinstance(previous,dict) else {}
    for key,value in patch.items():
        if value is None:result.pop(key,None)
        else:result[key]=merge_patch(result.get(key),value)
    return result


def openapi():
    revision={'name':'If-Match','in':'header','description':'Current numeric state revision; alternatively include revision in the JSON body.','required':False,'schema':{'type':'string'}}
    response={'200':{'description':'Success','content':{'application/json':{'schema':{'type':'object'}}}},
              '400':{'description':'Invalid settings; previous state retained'},'401':{'description':'Invalid, expired or revoked key'},
              '403':{'description':'Missing permission'},'409':{'description':'Revision conflict; reload and retry'},'429':{'description':'Rate limited'}}
    paths={}
    def add(path,method,summary,scope,body=False):
        operation={'summary':summary,'description':'Required permission: '+scope,'security':[{'bearerAuth':[]}],'responses':copy.deepcopy(response)}
        if body:
            operation['parameters']=[revision]
            operation['requestBody']={'required':method!='delete','content':{'application/json':{'schema':{'type':'object','additionalProperties':True}}}}
        paths.setdefault(path,{})[method]=operation
    for path,label,scope in [('/status','Panel and core status','read'),('/core/status','Core status','read'),('/stats','Metrics and client traffic totals','read'),
                             ('/state','Full panel model with secrets hidden by default','read'),('/schema','Exact Sing-box JSON schema','read'),
                             ('/openapi.json','This API specification','read'),('/settings','Server connection settings','read'),
                             ('/core/config','Rendered active server configuration','read + secrets:read'),('/updates','Cached release information','read'),
                             ('/panel/access','Panel and subscription entry settings','read'),('/operations/{id}','Update or access-change progress','read')]:
        add(path,'get',label,scope)
    for resource,collection in RESOURCES.items():
        permission='clients:write' if collection in ('clients','client_groups') else 'config:write'
        add('/'+resource,'get','List '+resource+' (limit, offset; clients also support search, group, tag and status)','read')
        paths['/'+resource]['get']['parameters']=[{'name':name,'in':'query','schema':{'type':'integer' if name in ('limit','offset') else 'string'}} for name in ['limit','offset']+(['search','group','tag','status'] if collection=='clients' else [])]
        add('/'+resource,'post','Create '+collection.rstrip('s'),permission,True)
        for method,summary in [('get','Read'),('patch','Update'),('delete','Delete')]:
            add('/'+resource+'/{id}',method,summary+' '+collection.rstrip('s'),'read' if method=='get' else permission,method!='get')
        for method in ('get','patch','delete'):
            paths['/'+resource+'/{id}'][method].setdefault('parameters',[]).append({'name':'id','in':'path','required':True,'schema':{'type':'string'}})
    for path,summary in [('/clients/bulk','Create up to 500 clients with one apply'),('/clients/bulk/preview','Preview generated names and settings'),
                         ('/clients/actions','Apply one action to selected clients'),('/clients/actions/preview','Preview an action without applying')]:
        add(path,'post',summary,'clients:write',True)
    for suffix in ('profile','subscription'):
        add('/clients/{id}/'+suffix,'get','Read private client '+suffix,'read + secrets:read')
        paths['/clients/{id}/'+suffix]['get']['parameters']=[{'name':'id','in':'path','required':True,'schema':{'type':'string'}}]
    for path,scope,summary in [('/core/start','core:control','Start or reapply core'),('/core/stop','core:control','Stop core'),
                               ('/core/check','core:control','Validate settings without changing service state'),
                               ('/tls/self-signed','config:write','Generate and apply a self-signed certificate'),
                               ('/warp','config:write','Provision WARP; explicit accept_terms: true required'),
                               ('/updates/check','core:control','Start a non-blocking release check'),('/panel/update','panel:manage','Queue a verified panel update')]:
        add(path,'post',summary,scope,True)
    add('/panel/access','patch','Change entry paths and ports (uses access revision)','panel:manage',True)
    add('/settings','patch','Merge and apply connection settings','config:write',True)
    for method in ('get','put'):
        add('/core/options/{section}',method,'Read or replace core options','read' if method=='get' else 'config:write',method=='put')
        paths['/core/options/{section}'][method].setdefault('parameters',[]).append({'name':'section','in':'path','required':True,'schema':{'type':'string','enum':list(OPTIONS)}})
    for resource in ('dns/rules','routing/rules','rule-sets'):
        add('/'+resource+'/{id}/move','post','Move an ordered rule up or down','config:write',True)
        paths['/'+resource+'/{id}/move']['post']['parameters'].append({'name':'id','in':'path','required':True,'schema':{'type':'string'}})
    for path,operations in paths.items():
        for operation in operations.values():
            for name in re.findall(r'\{([^}]+)\}',path):
                params=operation.setdefault('parameters',[])
                if not any(p.get('in')=='path' and p.get('name')==name for p in params):
                    params.append({'name':name,'in':'path','required':True,'schema':{'type':'string'}})
    return {'openapi':'3.1.0','info':{'title':'NARA automation API','version':'1.0','description':'Use HTTPS and an expiring scoped Bearer key. Keys never go in URLs. Writes require a current revision and share automatic core validation and rollback. Admin credentials, 2FA and API-key management require browser reauthentication.'},
            'servers':[{'url':'./'}], 'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'nara_…'}}},'paths':paths,
            'x-client-naming':{'default':'10 mixed-case letters','pattern_tokens':['{n}','{n:03}','{random}','{group}'],'maximum_batch':500},
            'x-bulk-operations':['delete','enable','disable','quota_set','quota_add','quota_subtract','expiry_set','expiry_extend','expiry_shorten','groups_set','tags_set','inbounds_set','reset_traffic','rotate_tokens']}


class API:
    def __init__(self,handler,store,runtime,access,updates,metrics,limits,limit_lock):
        self.h,self.store,self.runtime,self.access,self.updates,self.metrics=handler,store,runtime,access,updates,metrics
        self.limits,self.limit_lock=limits,limit_lock

    def need(self,scope):
        if scope not in self.key['scopes']:raise Fault(403,'permission_denied','This key needs the '+scope+' permission')

    def body(self,method):
        if method=='DELETE' and not int(self.h.headers.get('Content-Length','0')):return {}
        return self.h.json_body()

    def revision(self,data,state):
        raw=self.h.headers.get('If-Match')
        if raw:
            raw=raw.strip().strip('"')
            if not raw.isdigit():raise Fault(400,'invalid_revision','If-Match must contain a numeric revision')
            value=int(raw)
            if 'revision' in data and data['revision']!=value:raise Fault(400,'invalid_revision','Body and header revisions differ')
        else:value=data.get('revision')
        if type(value) is not int:raise Fault(400,'revision_required','Read the current revision and include it in If-Match or the JSON body')
        if value!=state['revision']:raise Fault(409,'revision_conflict','Settings changed; read the current state and retry')
        return value

    def handle(self,method,path):
        ident=uuid.uuid4().hex[:16]
        try:
            self.key=api_keys.authenticate(self.store,self.h.headers.get('Authorization',''))
            if not self.key:
                notifications.emit(self.store,'login_failed','A machine API authentication attempt was rejected.','failed-api-auth',900)
                raise Fault(401,'unauthorized','A valid Bearer API key is required')
            self.h.api_identity='api:'+self.key['id']
            self.h.api_actor=self.key['name']
            now=time.time()
            with self.limit_lock:
                for key in list(self.limits):
                    if now-self.limits[key][0]>=60:del self.limits[key]
                bucket=self.limits.setdefault(self.key['id'],[now,0])
                bucket[1]+=1
                if bucket[1]>120:raise Fault(429,'rate_limited','Wait before sending more requests (120 per minute per key)')
            status,result=self.dispatch(method,path)
            headers={'X-Request-ID':ident}
            if isinstance(result,dict) and 'revision' in result:headers['ETag']='"'+str(result['revision'])+'"'
            return self.h.send(status,result,headers=headers)
        except Fault as exc:
            headers={'X-Request-ID':ident}
            if exc.status==401:headers['WWW-Authenticate']='Bearer realm="NARA"'
            if exc.status==429:headers['Retry-After']='60'
            return self.h.send(exc.status,{'error':{'code':exc.code,'message':exc.message},'request_id':ident},headers=headers)
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            if method!='GET':notifications.emit(self.store,'apply_failed','An API change was rejected. Previous settings were retained.','apply-failed',300)
            message=str(exc) if isinstance(exc,ValueError) else 'Invalid data structure'
            conflict='Settings changed' in message
            return self.h.send(409 if conflict else 400,{'error':{'code':'revision_conflict' if conflict else 'invalid_request','message':message},'request_id':ident},headers={'X-Request-ID':ident})
        except Exception:
            return self.h.send(500,{'error':{'code':'operation_failed','message':'Operation failed; existing settings were retained where possible'},'request_id':ident})

    def dispatch(self,method,path):
        state=self.store.get('state');secret='secrets:read' in self.key['scopes']
        query=parse_qs(urlsplit(self.h.path).query,keep_blank_values=True)
        if method=='GET':
            self.need('read')
            if path=='openapi.json':return 200,openapi()
            if path=='schema':return 200,native.SCHEMA
            if path=='state':return 200,{'data':visible(state,secret),'revision':state['revision']}
            if path in ('status','core/status'):return 200,{'data':{'panel_version':__version__,'core':self.runtime.status()},'revision':state['revision']}
            if path=='stats':
                with self.runtime.lock:return 200,{'data':{'metrics':self.metrics.read(self.store.directory),'totals':self.store.totals()},'revision':state['revision']}
            if path=='settings':return 200,{'data':visible(state['settings'],secret),'revision':state['revision']}
            if path=='core/config':
                self.need('secrets:read')
                return 200,{'data':build_config(state,self.store.totals(),self.runtime.run_dir,self.runtime.stats_port),'revision':state['revision']}
            if path=='updates':return 200,{'data':self.updates.status(self.runtime.version())}
            if path=='panel/access':return 200,{'data':self.access.info()}
            if re.fullmatch(r'operations/[a-f0-9]{32}',path):return 200,{'data':self.access.status(path.split('/')[-1])}
            if path.startswith('core/options/') and path.split('/')[-1] in OPTIONS:
                section=path.split('/')[-1]
                return 200,{'data':visible(state.get('core_options',{}).get(section,{}),secret),'revision':state['revision'],**({'default_resolver':state['settings']['dns_final']} if section=='dns' else {})}
            match=re.fullmatch(r'clients/([A-Za-z0-9_-]+)/(?P<kind>profile|subscription)',path)
            if match:
                self.need('secrets:read');client=next((row for row in state['clients'] if row['id']==match[1]),None)
                if not client:raise Fault(404,'not_found','Client not found')
                if match['kind']=='profile':
                    active=self.runtime.active
                    live=next((row for row in (active or {}).get('clients',[]) if row['id']==client['id']),None)
                    if not live:raise Fault(409,'not_active','Client configuration is not active')
                    return 200,{'data':client_config(active,live,self.store.totals()),'revision':state['revision']}
                info=self.access.info();base=state['settings'].get('subscription_url','').strip()
                if not base:
                    host=state['settings'].get('server_address') or urlsplit('//'+self.h.headers.get('Host','')).hostname
                    host='['+host+']' if ':' in host else host
                    base=info.get('subscription_scheme','http')+'://'+host+':'+str(info['subscription_port'])+info['sub_path']+'/'
                return 200,{'data':{'url':base.rstrip('/')+'/'+client['token'],'active':eligible(client,self.store.totals())},'revision':state['revision']}
        for resource,collection in sorted(RESOURCES.items(),key=lambda item:-len(item[0])):
            if path!=resource and not path.startswith(resource+'/'):continue
            suffix=path[len(resource):].strip('/')
            # Reserved operations are handled after collection routing.
            if collection=='clients' and suffix in ('bulk','bulk/preview','actions','actions/preview'):break
            if collection=='tls' and suffix=='self-signed':break
            if suffix.endswith('/move'):
                if method!='POST':raise Fault(405,'method_not_allowed','Use POST to move a rule')
                self.need('config:write');data=self.body(method);revision=self.revision(data,state)
                status,result=self.h.mutate('/api/reorder-rules',{'revision':revision,'collection':collection,'id':suffix[:-5],'direction':data.get('direction')})
                return status,result
            if '/' in suffix:break
            row=next((x for x in state[collection] if x['id']==suffix),None) if suffix else None
            if suffix and not row:raise Fault(404,'not_found','Item not found')
            if method=='GET':
                if row:return 200,{'data':visible(row,secret),'revision':state['revision']}
                rows=state[collection]
                if collection=='clients':
                    search=query.get('search',[''])[0].casefold();group=query.get('group',[''])[0];tag=query.get('tag',[''])[0];status=query.get('status',['all'])[0]
                    if status not in ('all','active','inactive','disabled','expired','limited'):raise Fault(400,'invalid_filter','Choose a supported client status')
                    from .config import expiry
                    totals=self.store.totals()
                    rows=[r for r in rows if (not search or search in (r['name']+' '+r.get('note','')+' '+' '.join(r.get('tags',[]))).casefold()) and
                          (not group or group in r.get('group_ids',[])) and (not tag or tag in r.get('tags',[])) and
                          (status=='all' or status=='active' and eligible(r,totals) or status=='inactive' and not eligible(r,totals) or
                           status=='disabled' and not r.get('enabled',True) or status=='expired' and expiry(r.get('expires_at')) and expiry(r.get('expires_at'))<=time.time() or
                           status=='limited' and r.get('quota_bytes',0)>0 and sum(totals.get(r['id'],{}).values())>=r['quota_bytes'])]
                limit=int(query.get('limit',['50'])[0]);offset=int(query.get('offset',['0'])[0]);require(1<=limit<=250 and offset>=0,'Use limit 1–250 and a nonnegative offset')
                return 200,{'data':visible(rows[offset:offset+limit],secret),'pagination':{'total':len(rows),'limit':limit,'offset':offset},'revision':state['revision']}
            self.need('clients:write' if collection in ('clients','client_groups') else 'config:write')
            data=self.body(method);revision=self.revision(data,state)
            if method=='DELETE' and suffix:
                status,result=self.h.mutate('/api/delete',{'revision':revision,'collection':collection,'id':suffix})
                return status,result
            if method not in ('POST','PATCH') or method=='POST' and suffix or method=='PATCH' and not suffix:raise Fault(405,'method_not_allowed','Use POST to create, PATCH to update, or DELETE to remove an item')
            patch={k:v for k,v in data.items() if k!='revision'}
            require('id' not in patch,'Record IDs cannot be set or changed')
            if collection=='clients':
                require(set(patch)<={'name','note','enabled','quota_bytes','expires_at','inbound_ids','group_ids','tags'},'Unsupported client field')
            if collection=='client_groups':require(set(patch)<={'name','description'},'Unsupported group field')
            record=merge_patch(row,patch) if row else patch
            if collection in native.EXTRA_COLLECTIONS or collection in ('dns_servers','dns_rules','rule_sets') or collection=='inbounds' and 'config' in record:
                require(record.get('mode')=='native' or 'config' in record,'Use a native record with a config object; see /schema')
                record['mode']='native'
            status,result=self.h.mutate('/api/save',{'revision':revision,'collection':collection,'record':record})
            saved=next((x for x in self.store.get('state')[collection] if x['id']==result.get('record_id')),None)
            return 201 if method=='POST' else status,{'data':visible(saved,secret),'revision':result['revision'],'applied':True}
        if method=='GET':raise Fault(404,'not_found','API endpoint not found')
        data=self.body(method)
        if path=='panel/access' and method=='PATCH':
            self.need('panel:manage');info=self.access.info()
            require(data.get('revision')==info['revision'],'Access settings changed; refresh the current access revision')
            current_url=('https' if self.h._secure_cookie else 'http')+'://'+self.h.headers.get('Host','')+self.h._base_path+'/'
            return 202,{'data':self.access.request(data.get('values'),data['revision'],current_url)}
        if path=='panel/update' and method=='POST':
            self.need('panel:manage');result=self.access.request_update(data.get('version'));self.store.audit('Panel update queued through automation API')
            return 202,{'data':result}
        if path=='updates/check' and method=='POST':
            self.need('core:control');return 202,{'started':self.updates.start()}
        revision=self.revision(data,state)
        if path=='settings' and method=='PATCH':
            self.need('config:write');values=merge_patch(state['settings'],{k:v for k,v in data.items() if k!='revision'})
            return self.h.mutate('/api/settings',{'revision':revision,'settings':values})
        if path.startswith('core/options/') and path.split('/')[-1] in OPTIONS and method=='PUT':
            self.need('config:write');return self.h.mutate('/api/core-options',{**data,'revision':revision,'section':path.split('/')[-1]})
        if path in ('core/start','core/stop','core/check') and method=='POST':
            self.need('core:control');return self.h.mutate('/api/'+{'start':'apply','stop':'stop','check':'check'}[path.split('/')[-1]],{'revision':revision})
        if path=='tls/self-signed' and method=='POST':
            self.need('config:write');return self.h.mutate('/api/self-signed',{**data,'revision':revision})
        if path=='warp' and method=='POST':
            self.need('config:write');return 200,self.h.provision_warp({**data,'revision':revision})
        if path in ('clients/bulk','clients/actions','clients/bulk/preview','clients/actions/preview') and method=='POST':
            self.need('clients:write')
            if path.endswith('/preview'):
                return 200,clients.preview(self.store,state,data,self.h.api_identity,'create' if path.startswith('clients/bulk') else 'action')
            return self.h.mutate('/api/clients-bulk-create' if path=='clients/bulk' else '/api/clients-bulk-action',{**data,'revision':revision})
        raise Fault(404,'not_found','API endpoint not found')
