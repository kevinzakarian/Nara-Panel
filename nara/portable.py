"""Versioned data-only backups; restore retains destination identity and entry URLs."""
import copy
import datetime as dt
import json
from pathlib import Path
import secrets
import time
from . import __version__, notifications, traffic
from .config import require, validate
from .runtime import atomic_write

MAX_BYTES = 12*1024*1024
ADDRESS_FIELDS = ('server_address', 'public_url', 'subscription_url')


def document(store):
    with store.connect() as db:
        state = json.loads(db.execute("SELECT value FROM kv WHERE key='state'").fetchone()[0])
        for key in ADDRESS_FIELDS:
            state['settings'].pop(key, None)
        client_ids={row['id'] for row in state.get('clients',[])}
        totals = {row[0]: {'upload': row[1], 'download': row[2]} for row in db.execute('SELECT id,upload,download FROM traffic') if row[0] in client_ids}
        def value(key, default):
            row = db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default
        return {'format': 'nara-portable', 'schema': 1, 'panel_version': __version__, 'created_at': time.time(),
                'state': state, 'traffic': totals, 'telegram': value('telegram', None),
                'traffic_settings': value('traffic_settings', traffic.DEFAULTS),
                'managed_lifetime': value('managed_lifetime', sum(x['upload']+x['download'] for x in totals.values())),
                'panel_traffic_baseline': value('panel_traffic_baseline', 0)}


def snapshot(store):
    value = document(store)
    encoded = json.dumps(value, ensure_ascii=False).encode()
    require(len(encoded)<=MAX_BYTES, 'Backup exceeds the 12 MiB portable limit')
    directory = store.directory/'backups'
    directory.mkdir(mode=0o700, exist_ok=True); directory.chmod(0o700)
    filename = 'nara-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.json'
    path = directory/filename
    atomic_write(path, encoded.decode()); path.chmod(0o600)
    for old in sorted(directory.glob('nara-*.json'), key=lambda x: x.stat().st_mtime, reverse=True)[10:]:
        if old.is_file() and not old.is_symlink():old.unlink()
    return {'backup': value, 'filename': filename, 'path': str(path), 'size': len(encoded)}


def prepare(value, destination):
    require(isinstance(value, dict) and value.get('format')=='nara-portable' and type(value.get('schema')) is int and value['schema']==1, 'Unsupported NARA backup format')
    require(len(json.dumps(value,ensure_ascii=False).encode())<=MAX_BYTES, 'Backup exceeds the 12 MiB portable limit')
    require(isinstance(value.get('state'), dict), 'Backup has no panel settings')
    state = copy.deepcopy(value['state'])
    require(isinstance(state.get('settings'), dict), 'Backup settings are invalid')
    # The destination determines all three public identities. Never import the source URLs.
    for key in ADDRESS_FIELDS:
        state['settings'][key] = destination['settings'].get(key, '')
    state['revision'] = destination['revision']+1
    validate(state)
    totals = value.get('traffic', {})
    require(isinstance(totals, dict) and len(totals)<=1000, 'Invalid client traffic backup')
    ids = {row['id'] for row in state['clients']}
    totals = {key: row for key, row in totals.items() if key in ids}
    for row in totals.values():
        require(isinstance(row, dict) and set(row)=={'upload','download'} and all(type(x) is int and 0<=x<=10**18 for x in row.values()), 'Invalid traffic counters')
    conf = traffic.validate(value.get('traffic_settings', traffic.DEFAULTS))
    # NIC names and monthly server usage belong to the destination, not the source.
    conf['interface'] = ''
    telegram = value.get('telegram')
    require(telegram is None or isinstance(telegram, dict), 'Invalid Telegram backup settings')
    if telegram is not None:
        telegram = notifications.validate_settings({**telegram, 'enabled': False}, {'bot_token':'','chat_id':'','events':[],'summary_hour':9,'summary_minute':0,'enabled':False})
    for key in ('managed_lifetime','panel_traffic_baseline'):
        require(type(value.get(key,0)) is int and 0<=value.get(key,0)<=10**18, 'Invalid panel traffic baseline')
    return state, totals, conf, telegram


def preview(store, value):
    state, totals, _, _ = prepare(value, store.get('state'))
    return {'clients': len(state['clients']), 'inbounds': len(state['inbounds']), 'dns': len(state['dns_servers']),
            'tls': len(state['tls']), 'created_at': value.get('created_at'), 'panel_version': value.get('panel_version'),
            'retained': ['Destination panel/subscription URLs and server address', 'Administrator, 2FA, API keys and browser sessions', 'Host traffic accounting and chart history'],
            'note': 'Replaces proxy settings and client quota counters. Telegram delivery is disabled until reviewed. Historical charts are not included.'}


def restore(store, runtime, value):
    with runtime.lock:
        state, totals, conf, telegram = prepare(value, store.get('state'))
        # Core validation precedes the backup and every mutation.
        staging, _ = runtime.prepare(state, totals)
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        old_state = store.get('state'); was_running = runtime.running
        before = None
        old_totals = store.totals()
        old_keys = {key: store.get(key) for key in ('traffic_settings','telegram','managed_lifetime','panel_traffic_baseline')}
        try:
            if runtime.running:runtime.stop()
            old_totals=store.totals()  # Includes the final live collection.
            before=snapshot(store)
            with store.connect() as db:
                db.execute('DELETE FROM traffic')
                db.executemany('INSERT INTO traffic VALUES(?,?,?)', [(key, row['upload'], row['download']) for key,row in totals.items()])
                for key, item in {'traffic_settings':conf, 'telegram':telegram if telegram is not None else {**notifications.settings(store),'enabled':False},
                                  'managed_lifetime':value.get('managed_lifetime',0), 'panel_traffic_baseline':value.get('panel_traffic_baseline',0)}.items():
                    if key=='telegram':item={**item,'enabled':False}
                    db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,json.dumps(item)))
                db.execute("UPDATE notifications SET status='cancelled' WHERE status='queued'")
            runtime.apply(state, save=True)
        except Exception:
            with store.connect() as db:
                db.execute('DELETE FROM traffic')
                db.executemany('INSERT INTO traffic VALUES(?,?,?)', [(key,row['upload'],row['download']) for key,row in old_totals.items()])
                for key,item in old_keys.items():
                    if item is None:db.execute('DELETE FROM kv WHERE key=?',(key,))
                    else:db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,json.dumps(item)))
                db.execute("INSERT OR REPLACE INTO kv VALUES('state',?)",(json.dumps(old_state),))
            if was_running:runtime.apply(old_state, save=True)
            raise
        store.audit('Portable backup restored; destination URLs and administrator retained')
        return {'ok':True, 'backup_path':before['path'], 'revision':state['revision']}
