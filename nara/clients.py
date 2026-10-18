"""Client naming, grouping and atomic bulk-operation planning."""
import copy
import datetime as dt
import re
import secrets
import string
import uuid
from .config import require, integer, expiry

ALPHABET=string.ascii_letters
MAX_BATCH=500


def random_name(existing=()):
    used=set(existing)
    for _ in range(100):
        value=''.join(secrets.choice(ALPHABET) for _ in range(10))
        if any(c.isupper() for c in value) and any(c.islower() for c in value) and value not in used:
            return value
    raise ValueError('Could not generate a unique name; retry')


def new_client(values, existing=()):
    row=copy.deepcopy(values)
    row.update(id=uuid.uuid4().hex,uuid=str(uuid.uuid4()),password=secrets.token_urlsafe(24),token=secrets.token_urlsafe(32))
    row['name']=row.get('name') or random_name(existing)
    for key,value in {'enabled':True,'quota_bytes':0,'expires_at':'','note':'','group_ids':[],'tags':[],'email':'','telegram_id':''}.items():row.setdefault(key,value)
    return row


def template_name(pattern, number, used, group=''):
    require(isinstance(pattern,str) and len(pattern)<=100,'Name pattern must have at most 100 characters')
    require(not re.sub(r'\{(?:n(?::0[1-6])?|random|group)\}', '', pattern).count('{') and
            not re.sub(r'\{(?:n(?::0[1-6])?|random|group)\}', '', pattern).count('}'),
            'Use {n}, {n:03}, {random} or {group} in the name pattern')
    def replace(match):
        value=match[1]
        if value=='random':return random_name(used)
        if value=='group':return group
        return str(number).zfill(int(value.split(':0')[1]) if ':0' in value else 0)
    return re.sub(r'\{(n(?::0[1-6])?|random|group)\}',replace,pattern) if pattern else random_name(used)


def plan_create(state, data):
    count=data.get('count');integer(count,1,MAX_BATCH,'Batch size')
    require(len(state['clients'])+count<=1000,'This panel supports up to 1000 clients')
    start=data.get('start',1);integer(start,0,100000000,'Starting number')
    defaults=data.get('defaults',{})
    require(isinstance(defaults,dict),'Client defaults must be an object')
    allowed={'quota_bytes','expires_at','enabled','inbound_ids','group_ids','tags','note'}
    require(set(defaults)<=allowed,'Unsupported client default')
    groups={row['id']:row['name'] for row in state.get('client_groups',[])}
    group=', '.join(groups.get(value,'') for value in defaults.get('group_ids',[]))
    used={row['name'] for row in state['clients']}; rows=[]
    for number in range(start,start+count):
        name=template_name(data.get('pattern',''),number,used,group)
        require(isinstance(name,str) and 0<len(name)<=100,'Generated names must contain 1–100 characters')
        require(name not in used,'The pattern generates duplicate names. Add {n} or {random}, or change the starting number.')
        used.add(name);rows.append(new_client({**defaults,'name':name}))
    return rows


def selected(state, data):
    ids=data.get('ids')
    require(isinstance(ids,list) and 0<len(ids)<=1000 and all(isinstance(x,str) for x in ids) and len(ids)==len(set(ids)),
            'Select between 1 and 1000 distinct clients')
    rows=[row for row in state['clients'] if row['id'] in set(ids)]
    require(len(rows)==len(ids),'Some selected clients no longer exist; refresh the list')
    return rows


def plan_action(state,data,totals):
    rows=selected(state,data); action=data.get('operation'); value=data.get('value'); reset=[]
    require(action in ('delete','enable','disable','quota_set','quota_add','quota_subtract','expiry_set','expiry_extend','expiry_shorten','groups_set','tags_set','inbounds_set','reset_traffic','rotate_tokens'),'Choose a supported bulk action')
    if action.startswith('quota_'):integer(value,0 if action=='quota_set' else 1,10**18,'Traffic allowance')
    if action in ('expiry_extend','expiry_shorten'):integer(value,1,36500,'Number of days')
    if action=='expiry_set':expiry(value)
    if action in ('groups_set','tags_set','inbounds_set'):require(isinstance(value,list),'Select a list of values')
    for row in rows:
        if action in ('enable','disable'):row['enabled']=action=='enable'
        elif action=='quota_set':row['quota_bytes']=value
        elif action=='quota_add' and row.get('quota_bytes'):row['quota_bytes']+=value
        elif action=='quota_subtract' and row.get('quota_bytes'):row['quota_bytes']=max(1,row['quota_bytes']-value)
        elif action=='expiry_set':row['expires_at']=value or ''
        elif action in ('expiry_extend','expiry_shorten') and row.get('expires_at'):
            before=dt.datetime.fromtimestamp(expiry(row['expires_at']),dt.timezone.utc)
            row['expires_at']=(before+dt.timedelta(days=value*(1 if action=='expiry_extend' else -1))).isoformat()
        elif action=='groups_set':row['group_ids']=value.copy()
        elif action=='tags_set':row['tags']=value.copy()
        elif action=='inbounds_set':row['inbound_ids']=value.copy()
        elif action=='reset_traffic':reset.append(row['id'])
        elif action=='rotate_tokens':row['token']=secrets.token_urlsafe(32)
    if action=='delete':
        ids={row['id'] for row in rows};state['clients']=[row for row in state['clients'] if row['id'] not in ids]
    return rows,reset


def preview(store,state,data,actor,kind):
    import hashlib,json,time
    from .config import validate
    draft=copy.deepcopy(state)
    if kind=='create':
        rows=plan_create(draft,data);draft['clients'].extend(rows)
    else:rows,_=plan_action(draft,data,store.totals())
    validate(draft)
    ident=secrets.token_urlsafe(24);now=time.time()
    payload={'revision':state['revision'],'actor':hashlib.sha256(actor.encode()).hexdigest(),
             'expires':now+600,'kind':kind,'data':data,'rows':rows if kind=='create' else []}
    with store.connect() as db:
        previous=db.execute("SELECT key,value FROM kv WHERE key LIKE 'bulk-preview:%'").fetchall()
        for key,value in sorted(previous,key=lambda pair:json.loads(pair[1]).get('expires',0),reverse=True)[19:]:
            db.execute('DELETE FROM kv WHERE key=?',(key,))
        for key,value in previous:
            if json.loads(value).get('expires',0)<=now:db.execute('DELETE FROM kv WHERE key=?',(key,))
        db.execute('INSERT INTO kv VALUES(?,?)',('bulk-preview:'+ident,json.dumps(payload)))
    return {'preview_id':ident,'count':len(rows),'examples':[{'name':r['name'],'quota_bytes':r.get('quota_bytes',0),
            'expires_at':r.get('expires_at',''),'enabled':r.get('enabled',True)} for r in rows[:10]],'expires_in':600}


def prepared(store,state,data,actor,kind):
    import hashlib,time
    ident=data.get('preview_id')
    require(isinstance(ident,str) and re.fullmatch(r'[A-Za-z0-9_-]{20,64}',ident),'Invalid bulk preview')
    saved=store.get('bulk-preview:'+ident)
    require(saved and saved['expires']>time.time(),'Preview expired; create a new preview')
    require(saved['actor']==hashlib.sha256(actor.encode()).hexdigest() and saved['kind']==kind,'Preview belongs to another session or operation')
    require(saved['revision']==state['revision'],'Settings changed; refresh and preview again')
    return saved
