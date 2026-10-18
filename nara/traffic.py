"""Bounded traffic rollups and independent host/accounting baselines."""
import calendar
import datetime as dt
import json
import math
from pathlib import Path
import re
import time
from . import timezones
from .config import require

DEFAULTS = {'monthly_bytes': 0, 'reset_day': 1, 'interface': '', 'count': 'both',
            'traffic_percent': 80, 'cpu_percent': 90, 'memory_percent': 90,
            'disk_percent': 90, 'bandwidth_mbps': 0, 'duration_minutes': 5}


def settings(store):
    return {**DEFAULTS, **store.get('traffic_settings', {})}


def validate(value):
    require(isinstance(value, dict) and set(value) == set(DEFAULTS), 'Provide all traffic and alert settings')
    for key in ('monthly_bytes', 'reset_day', 'traffic_percent', 'cpu_percent', 'memory_percent', 'disk_percent', 'duration_minutes'):
        require(type(value[key]) is int, 'Invalid ' + key.replace('_', ' '))
    require(0 <= value['monthly_bytes'] <= 10**18, 'Monthly allowance is too large')
    require(1 <= value['reset_day'] <= 31, 'Reset day must be 1–31')
    for key in ('traffic_percent', 'cpu_percent', 'memory_percent', 'disk_percent'):
        require(0 <= value[key] <= 100, 'Alert percentages must be 0–100; 0 disables an alert')
    require(1 <= value['duration_minutes'] <= 1440, 'Sustained duration must be 1–1440 minutes')
    require(type(value['bandwidth_mbps']) in (int, float) and math.isfinite(value['bandwidth_mbps']) and 0 <= value['bandwidth_mbps'] <= 10**7, 'Invalid bandwidth threshold')
    require(isinstance(value['interface'], str) and (not value['interface'] or re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}', value['interface'])), 'Invalid network interface')
    require(value['count'] in ('both', 'upload', 'download'), 'Choose the provider billing direction')
    return dict(value)


def period(now, day, zone):
    local = dt.datetime.fromtimestamp(now, timezones.zone(zone))
    def start(year, month):
        return dt.datetime(year, month, min(day, calendar.monthrange(year, month)[1]), tzinfo=local.tzinfo)
    beginning = start(local.year, local.month)
    if beginning > local:
        month = local.month - 1 or 12
        beginning = start(local.year - (local.month == 1), month)
    month = beginning.month % 12 + 1
    end = start(beginning.year + (beginning.month == 12), month)
    return beginning.timestamp(), end.timestamp()


def interfaces():
    try:
        return sorted(p.name for p in Path('/sys/class/net').iterdir() if p.name != 'lo')
    except OSError:
        return []


def host_counters(interface=''):
    """A single uplink avoids counting proxy/tunnel/veth traffic twice."""
    if not interface:
        try:
            routes = Path('/proc/net/route').read_text().splitlines()[1:]
            choices = [(int(x[6]), x[0]) for row in routes if len(x := row.split()) >= 8 and x[1] == '00000000' and int(x[3], 16) & 1]
            if choices:
                interface = min(choices)[1]
            else:
                rows = [x.split() for x in Path('/proc/net/ipv6_route').read_text().splitlines()]
                interface = next((x[-1] for x in rows if len(x) >= 10 and x[0] == '0'*32 and x[1] == '00' and x[-1] != 'lo'), '')
        except (OSError, ValueError):
            return None
    if not interface or interface not in interfaces():
        return None
    try:
        for line in Path('/proc/net/dev').read_text().splitlines()[2:]:
            name, values = line.split(':', 1)
            if name.strip() == interface:
                fields = values.split()
                return {'interface': interface, 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                        'download': int(fields[0]), 'upload': int(fields[8])}
    except (OSError, ValueError, IndexError):
        pass
    return None


def record(db, kind, ident, upload, download, now):
    if not upload and not download:
        return
    db.execute("INSERT OR IGNORE INTO kv VALUES('traffic_history_since',?)", (json.dumps(now),))
    for step in (300, 3600):
        db.execute('INSERT INTO traffic_history VALUES(?,?,?,?,?,?) ON CONFLICT(kind,id,step,at) DO UPDATE SET upload=upload+excluded.upload,download=download+excluded.download',
                   (kind, ident, step, int(now)//step*step, upload, download))


def sample_host(store, now=None, counters=None):
    now = time.time() if now is None else now
    conf = settings(store)
    counters = host_counters(conf['interface']) if counters is None else counters
    if counters is None:
        return
    beginning, ending = period(now, conf['reset_day'], timezones.name(store.get('state')))
    with store.connect() as db:
        row = db.execute("SELECT value FROM kv WHERE key='host_traffic'").fetchone()
        saved = json.loads(row[0]) if row else {}
        previous = saved.get('counters', {})
        comparable = previous.get('interface') == counters['interface'] and previous.get('boot') == counters['boot']
        deltas = {key: max(0, counters[key] - previous.get(key, counters[key])) if comparable else 0 for key in ('upload', 'download')}
        # First sample and changed interfaces/reboots establish a baseline, never invent downtime traffic.
        total = {key: saved.get('total', {}).get(key, 0) + deltas[key] for key in deltas}
        cycle = saved.get('cycle', {})
        rollover=cycle.get('start') != beginning
        boundary_gap=rollover and now-saved.get('at',now)>30
        if rollover:
            cycle = {'start': beginning, 'end': ending, 'since': now, 'upload': 0, 'download': 0}
        for key in deltas:
            if not boundary_gap:cycle[key] += deltas[key]
        prune_at=saved.get('pruned_at',0)
        elapsed = now - saved.get('at', now)
        rates = {key: deltas[key] / elapsed if comparable and 0 < elapsed <= 30 else None for key in deltas}
        saved = {'counters': counters, 'at': now, 'total': total, 'cycle': cycle,
                 'since': saved.get('since', now), 'rates': rates, 'pruned_at': now if now-prune_at>=3600 else prune_at}
        db.execute("INSERT OR REPLACE INTO kv VALUES('host_traffic',?)", (json.dumps(saved),))
        record(db, 'server', 'host', deltas['upload'], deltas['download'], now)
        if now-prune_at>=3600:
            db.execute('DELETE FROM traffic_history WHERE (step=300 AND at<?) OR (step=3600 AND at<?)', (now-2*86400, now-100*86400))


def summary(store, now=None):
    now = time.time() if now is None else now
    conf = settings(store)
    saved = store.get('host_traffic', {})
    cycle = dict(saved.get('cycle', {}))
    start, end = period(now, conf['reset_day'], timezones.name(store.get('state')))
    if cycle.get('start') != start:
        cycle = {'start': start, 'end': end, 'upload': 0, 'download': 0, 'since': now}
    used = sum(cycle.get(key, 0) for key in ('upload', 'download') if conf['count'] == 'both' or conf['count'] == key)
    totals = store.totals()
    raw = sum(row['upload'] + row['download'] for row in totals.values())
    # Display baseline is independent of per-client quota counters and historical rollups.
    lifetime = store.get('managed_lifetime', 0)
    baseline = store.get('panel_traffic_baseline', 0)
    return {'settings': conf, 'interfaces': interfaces(), 'available': bool(saved) and now-saved.get('at', 0)<30,
            'interface': saved.get('counters', {}).get('interface'), 'cycle': {**cycle, 'used': used},
            'total': saved.get('total', {}), 'rates': saved.get('rates', {}),
            'panel_bytes': max(0, lifetime-baseline), 'client_quota_bytes': raw,
            'since': saved.get('since'), 'panel_reset_at': store.get('panel_traffic_reset_at')}


def reset(store, kind, now=None):
    require(kind in ('cycle', 'panel'), 'Choose cycle or panel accounting reset')
    now = time.time() if now is None else now
    with store.connect() as db:
        if kind == 'cycle':
            row = db.execute("SELECT value FROM kv WHERE key='host_traffic'").fetchone()
            require(row is not None, 'Host traffic is not available yet')
            saved = json.loads(row[0])
            saved['cycle'].update(upload=0, download=0, since=now)
            db.execute("UPDATE kv SET value=? WHERE key='host_traffic'", (json.dumps(saved),))
        else:
            row = db.execute("SELECT value FROM kv WHERE key='managed_lifetime'").fetchone()
            db.execute("INSERT OR REPLACE INTO kv VALUES('panel_traffic_baseline',?)", (row[0] if row else '0',))
            db.execute("INSERT OR REPLACE INTO kv VALUES('panel_traffic_reset_at',?)", (json.dumps(now),))
    store.audit('Monthly traffic baseline reset' if kind == 'cycle' else 'Panel traffic display baseline reset; client quotas retained')


def history(store, kind, ident, window, now=None):
    require(kind in ('client', 'inbound', 'server'), 'Invalid chart type')
    require(isinstance(ident, str) and len(ident) <= 128, 'Invalid chart ID')
    require(window in ('6h', '24h', 'week', 'month', '3months'), 'Choose a supported time range')
    now = time.time() if now is None else now
    local = dt.datetime.fromtimestamp(now, timezones.zone(timezones.name(store.get('state'))))
    if window in ('6h', '24h'):
        start = now - (6 if window == '6h' else 24)*3600
        source, step = 300, (300 if window == '6h' else 900)
    else:
        source = 3600
        if window == 'week':
            start = (local-dt.timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp(); step = 3600
        elif window == 'month':
            start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp(); step = 6*3600
        else:
            start = now-90*86400; step = 86400
    start = int(start)//step*step if window in ('6h','24h','3months') else int(start)
    recorded=store.get('traffic_history_since')
    requested_start=start
    if recorded is not None:start=max(start,int(recorded)//step*step)
    with store.connect() as db:
        rows = db.execute('SELECT ((at - ?) / ?) * ? + ?,SUM(upload),SUM(download) FROM traffic_history WHERE kind=? AND id=? AND step=? AND at>=? AND at<=? GROUP BY 1 ORDER BY 1',
                          (start, step, step, start, kind, ident, source, start, now)).fetchall()
    mapped = {row[0]: row[1:] for row in rows}
    return {'kind': kind, 'id': ident, 'range': window, 'step': step, 'start': start, 'end': now,
            'points': [{'at': at, 'upload': mapped.get(at, (0, 0))[0], 'download': mapped.get(at, (0, 0))[1]} for at in range(start, int(now)+1, step)],
            'recording_since': recorded, 'requested_start': requested_start}
