"""Exact, bundled 1.14.3 configuration vocabulary for complete core editors."""
import copy
import json
from pathlib import Path

VERSION = "1.14.3"
DATA = Path(__file__).with_name("schema")
SCHEMA = json.loads((DATA / "sing-box-1.14.3.schema.json").read_text())
HELP = json.loads((DATA / "field-help.json").read_text())
COLLECTIONS = {
    "inbounds": "Inbound", "outbounds": "Outbound", "dns_servers": "DNSServer",
    "dns_rules": "DNSRule", "route_rules": "Rule", "rule_sets": "RuleSet",
    "endpoints": "Endpoint", "services": "Service", "certificate_providers": "CertificateProvider",
    "http_clients": "HTTPClient", "network_namespaces": "NetworkNamespace",
}
EXTRA_COLLECTIONS = tuple(k for k in COLLECTIONS if k not in ("inbounds", "dns_servers", "dns_rules", "rule_sets"))
LABELS = {"vless": "VLESS", "vmess": "VMess", "trojan": "Trojan", "hysteria2": "Hysteria2", "hysteria": "Hysteria",
          "tuic": "TUIC", "anytls": "AnyTLS", "shadowsocks": "Shadowsocks", "shadowtls": "ShadowTLS",
          "snell": "Snell", "naive": "Naive", "tun": "TUN", "socks": "SOCKS", "http": "HTTP",
          "mixed": "Mixed", "direct": "Direct", "redirect": "Redirect", "tproxy": "TProxy", "cloudflared": "Cloudflared"}
LABELS.update({"fakeip":"FakeIP", "h3":"HTTP/3", "https":"HTTPS", "mdns":"mDNS", "openconnect":"OpenConnect",
               "openvpn":"OpenVPN", "wireguard":"WireGuard", "dhcp":"DHCP", "tls":"TLS", "udp":"UDP", "tcp":"TCP", "quic":"QUIC",
               "openvpn-client":"OpenVPN client", "openvpn-server":"OpenVPN server", "urltest":"URLTest", "ssh":"SSH",
               "api":"API", "ccm":"CCM", "ocm":"OCM", "derp":"DERP", "ssm-api":"SSM API",
               "usbip-client":"USB/IP client", "usbip-server":"USB/IP server", "cloudflare-origin-ca":"Cloudflare Origin CA", "acme":"ACME"})


def resolve(schema):
    if "$ref" in schema:
        return SCHEMA["$defs"][schema["$ref"].split("/")[-1]]
    return schema


def variants(schema):
    schema = resolve(schema)
    if "oneOf" in schema:
        return [branch for item in schema["oneOf"] for branch in variants(item)]
    return [schema]


def types(definition):
    result=[]
    for item in variants(SCHEMA["$defs"][definition]):
        field=item.get("properties",{}).get("type",{})
        result.extend([field["const"]] if "const" in field else field.get("enum",[]))
    return list(dict.fromkeys(value for value in result if value))


def payload():
    return {"version": VERSION, "schema": SCHEMA, "help": HELP, "collections": COLLECTIONS,
            "types": {k: types(v) for k, v in COLLECTIONS.items()}, "labels": LABELS}


def record(row):
    return copy.deepcopy(row["config"])


def validate_record(collection, row):
    config = row.get("config")
    if not isinstance(config, dict) or not config:
        raise ValueError("Core settings must be a nonempty object")
    if len(json.dumps(config)) > 500_000:
        raise ValueError("Core settings are too large")
    allowed_types = types(COLLECTIONS[collection])
    if allowed_types and config.get("type") not in allowed_types:
        optional_type = any("type" not in item.get("required",[]) for item in variants(SCHEMA["$defs"][COLLECTIONS[collection]]))
        if config.get("type") not in (None, "") or not optional_type:
            raise ValueError("Unsupported " + collection + " type for Sing-box " + VERSION)
    if config.get("tag", "") != row.get("tag", ""):
        raise ValueError("Core tag does not match the record tag")
    if not isinstance(config.get("tag", ""), str):
        raise ValueError("Core tag must be text")
    if type(row.get("enabled", True)) is not bool:
        raise ValueError("Invalid enabled state")
    if collection == "inbounds":
        import ipaddress
        try:
            public_listener = not ipaddress.ip_address(config.get("listen", "::")).is_loopback
        except ValueError:
            public_listener = True
        kind = config.get("type")
        users = config.get("users", [])
        authenticated = bool(users) or bool(config.get("password") or config.get("auth") or config.get("auth_str"))
        if kind == "shadowsocks" and config.get("method", "none") == "none":
            authenticated = False
        if public_listener and kind in ("http", "mixed", "socks", "shadowsocks", "hysteria", "hysteria2", "naive") and not authenticated:
            if row.get("allow_unauthenticated") is not True:
                raise ValueError("Configure authentication or explicitly allow unauthenticated access for this standalone listener")


SECRET_FIELDS = {"key", "private_key", "private_keys", "secret_key", "preshared_key"}


def _secret(key, value, parent):
    if key == "key":
        text = value if isinstance(value, str) else " ".join(v for v in value if isinstance(v, str)) if isinstance(value, list) else ""
        return parent == "tls" or "PRIVATE KEY-----" in text
    return key in SECRET_FIELDS


def redact(value, parent=""):
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items() if not _secret(k, v, parent)}
    if isinstance(value, list):
        return [redact(v, parent) for v in value]
    return value


def preserve_secrets(value, previous, parent=""):
    """A missing protected key preserves it; deleting its parent removes it."""
    value = copy.deepcopy(value)
    if isinstance(value, dict) and isinstance(previous, dict):
        for key, old in previous.items():
            if _secret(key, old, parent) and key not in value:
                value[key] = copy.deepcopy(old)
            elif key in value:
                value[key] = preserve_secrets(value[key], old, key)
    elif isinstance(value, list) and isinstance(previous, list):
        for index, item in enumerate(value):
            old = previous[index] if index < len(previous) and len(previous) == len(value) else None
            if isinstance(item, dict):
                identity = next((key for key in ("tag", "name", "public_key", "username", "id") if key in item), None)
                if identity:
                    old = next((v for v in previous if isinstance(v, dict) and v.get(identity) == item[identity]), None)
            value[index] = preserve_secrets(item, old, parent)
    return value


def _matches(schema, value):
    schema = resolve(schema)
    if 'allOf' in schema:
        return all(_matches(part,value) for part in schema['allOf'])
    for union in ('oneOf','anyOf'):
        if union in schema:
            return any(_matches(part,value) for part in schema[union])
    kind = schema.get('type')
    if kind == 'object' and not isinstance(value,dict): return False
    if kind == 'array' and not isinstance(value,list): return False
    if kind == 'string' and not isinstance(value,str): return False
    if kind == 'boolean' and type(value) is not bool: return False
    if kind in ('integer','number') and type(value) not in (int,float): return False
    if isinstance(value,dict):
        for key,field in schema.get('properties',{}).items():
            if key in value:
                if 'const' in field and value[key] != field['const']: return False
                if 'enum' in field and value[key] not in field['enum']: return False
    return True


def validate_references(config):
    """The core defers some route lookups until traffic arrives; reject typos now."""
    tags = lambda rows: {r['tag'] for r in rows if r.get('tag')}
    endpoints = tags(config.get('endpoints',[]))
    registry = {
        'inbound': tags(config.get('inbounds',[])) | endpoints,
        'outbound': tags(config.get('outbounds',[])) | endpoints,
        'dns_server': tags(config.get('dns',{}).get('servers',[])),
        'rule_set': tags(config.get('route',{}).get('rule_set',[])),
        'network_namespace': tags(config.get('network_namespaces',[])),
        'http_client': tags(config.get('http_clients',[])),
        'certificate_provider': tags(config.get('certificate_providers',[])),
    }
    forward = [r.get('tag') for r in config.get('outbounds',[])+config.get('endpoints',[]) if r.get('tag')]
    if len(forward) != len(set(forward)):
        raise ValueError('Outbounds and endpoints must have unique tags')
    def walk(raw,value,path):
        schema=resolve(raw)
        if 'allOf' in schema:
            for part in schema['allOf']: walk(part,value,path)
            return
        for union in ('oneOf','anyOf'):
            if union in schema:
                selected=next((part for part in schema[union] if _matches(part,value)),None)
                if selected is not None: walk(selected,value,path)
                return
        reference=schema.get('x-tag-reference')
        if reference and isinstance(value,str) and value and value not in registry[reference]:
            raise ValueError('Unknown '+reference.replace('_',' ')+' reference at '+path+': '+value)
        if isinstance(value,dict):
            for key,item in value.items():
                child=schema.get('properties',{}).get(key)
                if child is None and isinstance(schema.get('additionalProperties'),dict): child=schema['additionalProperties']
                if child is not None: walk(child,item,path+'.'+key)
        elif isinstance(value,list) and isinstance(schema.get('items'),dict):
            for index,item in enumerate(value): walk(schema['items'],item,path+'['+str(index)+']')
    walk(SCHEMA,config,'config')
    def dependencies(value, keys):
        result=set()
        if isinstance(value,dict):
            for key in keys:
                item=value.get(key)
                if isinstance(item,str) and item: result.add(item)
                elif isinstance(item,list): result.update(v for v in item if isinstance(v,str))
            for item in value.values(): result.update(dependencies(item,keys))
        elif isinstance(value,list):
            for item in value: result.update(dependencies(item,keys))
        return result
    def detect_cycles(rows, keys, label):
        graph={row['tag']:dependencies(row,keys) for row in rows if row.get('tag')}
        visited,active=set(),set()
        def visit(tag):
            if tag in active: raise ValueError(label+' dependency cycle: '+tag)
            if tag in visited: return
            active.add(tag)
            for target in graph.get(tag,()): visit(target)
            active.remove(tag);visited.add(tag)
        for tag in graph: visit(tag)
    detect_cycles(config.get('outbounds',[])+config.get('endpoints',[]),('detour','outbounds'),'Outbound')
    detect_cycles(config.get('route',{}).get('rule_set',[]),('rule_set',),'Rule set')
