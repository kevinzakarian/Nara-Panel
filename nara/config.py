"""Validated panel model and sing-box configuration generation."""
import copy
import datetime as dt
import ipaddress
import re
import time
from urllib.parse import urlsplit
from . import options, native, timezones

PROTOCOLS = ("vless", "vmess", "trojan", "hysteria2", "tuic", "anytls")
TLS_REQUIRED = ("trojan", "hysteria2", "tuic", "anytls")
COLLECTIONS = ("inbounds", "tls", "dns_servers", "dns_rules", "rule_sets", "clients", "client_groups") + native.EXTRA_COLLECTIONS
REMOTE_DNS_TYPES = ("udp", "tcp", "tls", "https", "quic", "h3")
# An internal authenticated DNS destination; no socket binds this address.
CLIENT_DNS_ADDRESS = "198.18.0.1"


def normalize_dns_record(row):
    clean = dict(row)
    config = clean
    if row.get("mode") == "native":
        if not isinstance(row.get("config"), dict):
            return clean
        config = clean["config"] = dict(row["config"])
    if config.get("type") in REMOTE_DNS_TYPES and isinstance(config.get("server"), str):
        config["server"] = config["server"].strip()
        try:
            ipaddress.ip_address(config["server"])
        except ValueError:
            pass
        else:
            # A literal address never needs a lookup. Older forms populated this
            # field automatically, leaving unused dependencies on deleted tags.
            config.pop("domain_resolver", None)
    return clean


def initial_state():
    return {**{k: [] for k in native.EXTRA_COLLECTIONS}, "core_options": {}, "revision": 0, "inbounds": [], "tls": [], "dns_rules": [], "rule_sets": [],
            "clients": [], "client_groups": [], "dns_servers": [{"id": "bootstrap", "tag": "bootstrap", "type": "udp",
            "server": "1.1.1.1", "port": 53}],
            "settings": {"server_address": "", "public_url": "", "subscription_url": "", "dns_final": "bootstrap",
                         "block_private": True, "time_zone": "UTC", "core_features_enabled": False}}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, label + " is out of range")


def host(value):
    require(isinstance(value, str) and 0 < len(value) <= 253, "Server address is required")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        require(bool(re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value)), "Invalid domain name")


def expiry(value):
    if not value:
        return 0
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "Expiry date must include a timezone")
        return parsed.timestamp()
    except (ValueError, AttributeError):
        raise ValueError("Invalid expiry date")


def eligible(client, totals, now=None):
    used = sum(totals.get(client["id"], {}).get(k, 0) for k in ("upload", "download"))
    return (client.get("enabled", True) and (not expiry(client.get("expires_at")) or
            expiry(client["expires_at"]) > (time.time() if now is None else now)) and
            (not client.get("quota_bytes", 0) or used < client["quota_bytes"]))


def validate(state):
    require(isinstance(state, dict), "Invalid data structure")
    for collection in COLLECTIONS:
        rows = state.get(collection)
        require(isinstance(rows, list) and len(rows) <= 1000, "Too many records")
        ids = []
        for row in rows:
            require(isinstance(row, dict), "Invalid record")
            require(bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", row.get("id", ""))), "Invalid record ID")
            ids.append(row["id"])
        require(len(ids) == len(set(ids)), "Duplicate record ID")
    require(isinstance(state["settings"].get("core_features_enabled", True), bool), "Invalid Core features visibility")
    tls_ids = {x["id"] for x in state["tls"]}
    inbound_ids = {x["id"] for x in state["inbounds"]}
    dns_tags = {x.get("tag") for x in state["dns_servers"]}
    rs_tags = {x.get("tag") for x in state["rule_sets"]}
    for coll in ("dns_servers", "rule_sets", "inbounds"):
        tags = [x.get("tag", "") for x in state[coll]]
        require(all(isinstance(t, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", t) for t in tags), "Tags may contain letters, numbers, hyphens, and underscores")
        require(len(tags) == len(set(tags)), "Duplicate tag")
    ports = set()
    for i in state["inbounds"]:
        if i.get("mode") == "native":
            native.validate_record("inbounds", i)
            require(i["type"] == i["config"]["type"], "Inbound protocol does not match")
            require(not i.get("tls_id") or i["tls_id"] in tls_ids, "TLS profile not found")
            if i["config"].get("listen_port"):
                integer(i["config"]["listen_port"], 1, 65535, "Port")
                require(i["config"]["listen_port"] not in ports, "Duplicate inbound port")
                ports.add(i["config"]["listen_port"])
            continue
        require(i.get("type") in PROTOCOLS, "Unsupported protocol")
        integer(i.get("port"), 1, 65535, "Port")
        if i.get("public_port"):
            integer(i["public_port"], 1, 65535, "Public port")
        require(type(i.get("enabled", True)) is bool, "Invalid inbound enabled state")
        try:
            ipaddress.ip_address(i.get("listen", "::"))
        except ValueError:
            raise ValueError("Listen must be an IP address")
        # Conservatively reject port reuse even across TCP/UDP and bind addresses.
        require(i["port"] not in ports, "Duplicate inbound port")
        ports.add(i["port"])
        require(not i.get("tls_id") or i["tls_id"] in tls_ids, "TLS profile not found")
        require(i["type"] not in TLS_REQUIRED or i.get("tls_id"), "This protocol requires TLS")
        require(i.get("transport", "tcp") in ("tcp", "ws", "grpc", "http", "httpupgrade", "quic"), "Invalid transport")
        require(i.get("transport", "tcp") == "tcp" or i["type"] in ("vless", "vmess", "trojan"), "Transport is not supported by this protocol")
        require(isinstance(i.get("path", "/"), str) and len(i.get("path", "/")) <= 256, "Invalid transport path")
        options.validate_inbound(i)
        profile = next((t for t in state["tls"] if t["id"] == i.get("tls_id")), {})
        if i["type"] in ("hysteria2", "tuic") or i.get("transport") == "quic" or options.get(i, "server_options.flow"):
            require(profile.get("max_version", "1.3") != "1.2", "QUIC and VLESS Vision require TLS 1.3")
    for t in state["tls"]:
        options.validate_options({k: t[k] for k in (f["key"] for f in options.TLS) if k in t}, options.TLS, "TLS")
        require(not (t.get("min_version") and t.get("max_version")) or t["min_version"] <= t["max_version"], "Minimum TLS version exceeds the maximum")
        host(t.get("server_name"))
        require(t.get("kind") in ("self_signed", "imported"), "Invalid TLS profile type")
        require(isinstance(t.get("certificate"), str) and "BEGIN CERTIFICATE" in t["certificate"], "Certificate is required")
        require(isinstance(t.get("private_key"), str) and "PRIVATE KEY" in t["private_key"], "Private key is required")
    for d in state["dns_servers"]:
        d = normalize_dns_record(d)
        if d.get("mode") == "native":
            native.validate_record("dns_servers", d)
            resolver = d["config"]
            if resolver.get("type") in REMOTE_DNS_TYPES:
                prefix = "DNS resolver " + d["tag"] + ": "
                address = resolver.get("server")
                try:
                    host(address)
                except ValueError:
                    raise ValueError(prefix + "Server must be an IP address or domain without a scheme, port or path. Use Server Port and Path separately.") from None
                if "server_port" in resolver:
                    integer(resolver["server_port"], 0, 65535, "DNS resolver " + d["tag"] + " port")
                bootstrap = resolver.get("domain_resolver")
                bootstrap = bootstrap.get("server") if isinstance(bootstrap, dict) else bootstrap
                if bootstrap:
                    require(bootstrap in dns_tags and bootstrap != d["tag"], prefix + "Choose a separate configured DNS resolver in Domain Resolver (bootstrap).")
                try:
                    ipaddress.ip_address(address)
                except ValueError:
                    require(bootstrap or resolver.get("detour"), prefix + "A DNS server domain needs a bootstrap resolver. Select Domain Resolver, for example bootstrap, to resolve its address.")
            continue
        require(d.get("type") in ("udp", "tcp", "tls", "https", "quic", "h3", "local"), "Invalid DNS resolver type")
        if d["type"] != "local":
            host(d.get("server"))
            integer(d.get("port", {"udp": 53, "tcp": 53, "tls": 853, "https": 443, "quic": 853, "h3": 443}[d["type"]]), 1, 65535, "DNS port")
            try:
                ipaddress.ip_address(d["server"])
            except ValueError:
                require(d.get("domain_resolver") in dns_tags and d.get("domain_resolver") != d["tag"], "Select a separate bootstrap resolver for this DNS hostname")
    # Reject resolver dependency cycles before sing-box sees them.
    dependencies = {}
    for d in state["dns_servers"]:
        d = normalize_dns_record(d)
        resolver = d.get("config", {}).get("domain_resolver") if d.get("mode") == "native" else d.get("domain_resolver")
        dependencies[d["tag"]] = resolver.get("server") if isinstance(resolver, dict) else resolver
    for tag in dependencies:
        seen = set()
        while tag:
            require(tag not in seen, "DNS resolver dependency cycle")
            seen.add(tag)
            tag = dependencies.get(tag)
    require(state["settings"].get("dns_final") in dns_tags, "A default DNS resolver is required")
    options.validate_options(state["settings"].get("dns_options", {}), options.DNS, "DNS")
    for r in state["rule_sets"]:
        if r.get("mode") == "native":
            native.validate_record("rule_sets", r)
            continue
        if r.get("update_interval"):
            options.validate_options({"update_interval": r["update_interval"]}, [options.field("update_interval", "Rule set update interval")], "rule set")
        require(r.get("type") in ("inline", "remote"), "Invalid rule set type")
        if r["type"] == "remote":
            u = urlsplit(r.get("url", ""))
            require(u.scheme == "https" and bool(u.hostname) and not u.username, "Rule set URL must use HTTPS")
            require(r.get("format") in ("source", "binary"), "Invalid rule set format")
        else:
            require(isinstance(r.get("rules"), list) and bool(r["rules"]), "Inline rule set requires a nonempty rules array")
    for r in state["dns_rules"]:
        if r.get("mode") == "native":
            native.validate_record("dns_rules", r)
            continue
        options.validate_options(r.get("options", {}), options.DNS_RULE, "DNS rule")
        if r.get("action") == "reject":
            require(not any(k in r.get("options", {}) for k in ("disable_cache", "rewrite_ttl", "strategy")), "DNS response options require a route action")
        require(r.get("match") in ("domain", "domain_suffix", "domain_keyword", "domain_regex", "query_type", "rule_set"), "Invalid DNS match type")
        require(isinstance(r.get("values"), list) and bool(r["values"]) and all(isinstance(v, str) and v for v in r["values"]), "Rule values are required")
        require(r.get("action") in ("route", "reject"), "Invalid DNS action")
        if r["action"] == "route":
            require(r.get("server") in dns_tags, "Rule resolver not found")
        if r["match"] == "rule_set":
            require(set(r["values"]) <= rs_tags, "Rule set not found")
    groups = state.get("client_groups", [])
    group_ids = {group["id"] for group in groups}
    group_names = []
    for group in groups:
        require(isinstance(group.get("name"), str) and 1 <= len(group["name"].strip()) <= 64, "Group name must contain 1–64 characters")
        require(isinstance(group.get("description", ""), str) and len(group.get("description", "")) <= 500, "Group description is too long")
        group_names.append(group["name"].strip().casefold())
    require(len(group_names) == len(set(group_names)), "Group names must be unique")
    for c in state["clients"]:
        from .client_portal import contact
        contact(c.get("email", ""), "email")
        contact(c.get("telegram_id", ""), "telegram")
        require(isinstance(c.get("group_ids", []), list) and len(c.get("group_ids", [])) <= 20 and all(isinstance(x, str) for x in c.get("group_ids", [])) and set(c.get("group_ids", [])) <= group_ids, "Choose up to 20 valid client groups")
        require(isinstance(c.get("tags", []), list) and len(c.get("tags", [])) <= 20 and all(isinstance(x, str) and 1 <= len(x) <= 32 for x in c.get("tags", [])), "Use up to 20 tags of 1–32 characters")
        require(isinstance(c.get("note", ""), str) and len(c.get("note", "")) <= 1000, "Client note is too long")
        require(type(c.get("enabled", True)) is bool, "Invalid client enabled state")
        require(isinstance(c.get("name"), str) and 0 < len(c["name"]) <= 100, "Client name is required")
        integer(c.get("quota_bytes", 0), 0, 10**18, "Traffic allowance")
        expiry(c.get("expires_at"))
        require(isinstance(c.get("inbound_ids"), list) and bool(c["inbound_ids"]) and set(c["inbound_ids"]) <= inbound_ids, "Assign at least one valid inbound to the client")
        require(all(i.get("mode") != "native" for i in state["inbounds"] if i["id"] in c["inbound_ids"]), "Standalone inbounds manage their own credentials and cannot use panel account quotas")
        import uuid
        try:
            uuid.UUID(c.get("uuid", ""))
        except (ValueError, AttributeError):
            raise ValueError("Invalid UUID")
        require(isinstance(c.get("password"), str) and 12 <= len(c["password"]) <= 256, "Client password must contain at least 12 characters")
        require(bool(re.fullmatch(r"[A-Za-z0-9_-]{32,128}", c.get("token", ""))), "Invalid subscription token")
    for k in ("server_address", "public_url", "subscription_url"):
        value = state["settings"].get(k, "")
        require(isinstance(value, str) and len(value.encode("utf-8")) <= 2048 and not any(ord(char)<33 or ord(char)==127 for char in value), "Public addresses must contain at most 2048 bytes without spaces or control characters")
        if value and k == "server_address":
            host(value)
        elif value:
            u = urlsplit(value)
            require(u.scheme in ("http", "https") and u.hostname and u.username is None and u.password is None
                    and not u.query and not u.fragment and (u.port is None or 1 <= u.port <= 65535),
                    "Public URL must use HTTP or HTTPS without credentials, a query, or a fragment")
    timezones.zone(timezones.name(state))
    require(type(state["settings"].get("block_private")) is bool, "Invalid private network setting")
    require(isinstance(state.get("core_options", {}), dict), "Invalid core options")
    require(set(state.get("core_options", {})) <= {"log", "dns", "ntp", "certificate", "route", "experimental"}, "Unsupported core options section")
    for key in native.EXTRA_COLLECTIONS:
        tags = []
        for row in state.get(key, []):
            native.validate_record(key, row)
            if row.get("tag"):
                tags.append(row["tag"])
        require(len(tags) == len(set(tags)), "Duplicate " + key + " tag")


def user_entry(c, protocol, inbound=None):
    user = {"name": "client-" + c["id"]}
    if protocol in ("vless", "vmess", "tuic"):
        user["uuid"] = c["uuid"]
    if protocol in ("trojan", "hysteria2", "tuic", "anytls"):
        user["password"] = c["password"]
    settings = (inbound or {}).get("server_options", {})
    if protocol == "vless" and settings.get("flow"):
        user["flow"] = settings["flow"]
    if protocol == "vmess":
        user["alterId"] = settings.get("alter_id", 0)
    return user


def transport(inbound):
    kind = inbound.get("transport", "tcp")
    if kind == "tcp":
        return None
    obj = {"type": kind, **copy.deepcopy(inbound.get("transport_options", {}))}
    if kind == "grpc":
        obj["service_name"] = inbound.get("path", "nara").lstrip("/")
    elif kind != "quic":
        obj["path"] = inbound.get("path", "/")
    return obj


def build_config(state, totals, cert_dir, stats_port=10085, check_all=False):
    validate(state)
    tls = {t["id"]: t for t in state["tls"]}
    clients = [c for c in state["clients"] if check_all or eligible(c, totals)]
    inbounds = []
    managed_dns_tags = []
    for i in state["inbounds"]:
        if i.get("mode") == "native":
            if check_all or i.get("enabled", True):
                obj = native.record(i)
                if i.get("tls_id"):
                    t = tls[i["tls_id"]]
                    obj["tls"] = {"enabled": True, "server_name": t["server_name"],
                                  "certificate_path": str(cert_dir / (t["id"] + ".crt")),
                                  "key_path": str(cert_dir / (t["id"] + ".key")),
                                  **options.tls_options(t), **obj.get("tls", {})}
                inbounds.append(obj)
            continue
        users = [user_entry(c, i["type"], i) for c in clients if i["id"] in c["inbound_ids"]]
        if check_all and not users:
            users = [user_entry({"id": "validation", "uuid": "00000000-0000-4000-8000-000000000001", "password": "validation-only-not-a-real-user"}, i["type"], i)]
        if not check_all and (not i.get("enabled", True) or not users):
            continue  # Never start an unauthenticated listener when users=[] means no auth.
        obj = {"type": i["type"], "tag": i["tag"], "listen": i.get("listen", "::"),
               "listen_port": i["port"], "users": users}
        obj.update(copy.deepcopy(i.get("listen_options", {})))
        obj.update(options.server_options(i))
        if i.get("multiplex", {}).get("enabled"):
            obj["multiplex"] = {k: v for k, v in i["multiplex"].items() if k in ("enabled", "padding")}
        if i.get("tls_id"):
            t = tls[i["tls_id"]]
            obj["tls"] = {"enabled": True, "server_name": t["server_name"],
                          "certificate_path": str(cert_dir / (t["id"] + ".crt")),
                          "key_path": str(cert_dir / (t["id"] + ".key"))}
            obj["tls"].update(options.tls_options(t))
            if i["type"] == "tuic" and not obj["tls"].get("alpn"):
                obj["tls"]["alpn"] = ["h3"]
        tr = transport(i)
        if tr:
            obj["transport"] = tr
        extras = copy.deepcopy(i.get("extra_options", {}))
        require(isinstance(extras, dict) and not set(extras) & {"type", "tag", "listen", "listen_port", "users"}, "Managed inbound identity and users cannot be overridden")
        for key, value in extras.items():
            if isinstance(value, dict) and isinstance(obj.get(key), dict):
                obj[key].update(value)
            else:
                obj[key] = value
        inbounds.append(obj)
        managed_dns_tags.append(obj["tag"])
    # Handle only the managed client DNS sentinel, before private-IP blocking.
    # This keeps all resolver settings, rules and private credentials on the server.
    dns_bridge = ([{"inbound": managed_dns_tags, "ip_cidr": [CLIENT_DNS_ADDRESS + "/32"],
                    "port": 53, "action": "hijack-dns"}] if managed_dns_tags else [])
    servers = []
    for d in state["dns_servers"]:
        if not check_all and not d.get("enabled", True):
            continue
        d = normalize_dns_record(d)
        if d.get("mode") == "native":
            servers.append(native.record(d))
            continue
        obj = {k: d[k] for k in ("type", "tag", "server", "domain_resolver", "path") if d.get(k)}
        if d.get("port") and d["type"] != "local":
            obj["server_port"] = d["port"]
        if d["type"] in ("tls", "https", "quic", "h3"):
            obj["tls"] = {"enabled": True}
            if d.get("server_name"):
                obj["tls"]["server_name"] = d["server_name"]
        servers.append(obj)
    rules = []
    for r in state["dns_rules"]:
        if not check_all and not r.get("enabled", True):
            continue
        if r.get("mode") == "native":
            rules.append(native.record(r))
            continue
        obj = {r["match"]: r["values"], "action": r["action"]}
        if r["action"] == "route":
            obj["server"] = r["server"]
        obj.update(copy.deepcopy(r.get("options", {})))
        rules.append(obj)
    sets = [native.record(r) if r.get("mode") == "native" else {k: copy.deepcopy(v) for k, v in r.items() if k in ("type", "tag", "url", "format", "rules", "update_interval")}
            for r in state["rule_sets"] if check_all or r.get("enabled", True)]
    config = {"log": {"level": "warn", "timestamp": True}, "dns": {"servers": servers,
            "rules": rules, "final": state["settings"]["dns_final"], **state["settings"].get("dns_options", {})}, "inbounds": inbounds,
            "outbounds": [{"type": "direct", "tag": "direct"}],
            "route": {"rules": dns_bridge + ([{"ip_is_private": True, "action": "reject"}] if state["settings"]["block_private"] else []),
                      "rule_set": sets, "final": "direct", "default_domain_resolver": state["settings"]["dns_final"]},
            "experimental": {"v2ray_api": {"listen": "127.0.0.1:" + str(stats_port),
                             "stats": {"enabled": True, "inbounds": [i["tag"] for i in inbounds], "users": ["client-" + c["id"] for c in clients]}}}}
    core = copy.deepcopy(state.get("core_options", {}))
    for key, value in core.items():
        require(isinstance(value, dict), key + " settings must be an object")
        if key == "dns":
            require(not set(value) & {"servers", "rules", "final"}, "Use the DNS editor for resolvers, rules and default resolver")
        if key == "route":
            require(not set(value) & {"rules", "rule_set"}, "Use Routing and Rule sets to edit ordered rules")
        if key == "experimental":
            require("v2ray_api" not in value, "The panel manages the private traffic accounting API")
        config[key] = {**config.get(key, {}), **value}
    config["route"]["rules"] += [native.record(r) for r in state.get("route_rules", []) if check_all or r.get("enabled", True)]
    custom_outbounds = [native.record(r) for r in state.get("outbounds", []) if check_all or r.get("enabled", True)]
    if any(o.get("tag") == "direct" for o in custom_outbounds):
        config["outbounds"] = custom_outbounds
    else:
        config["outbounds"] += custom_outbounds
    for key in ("endpoints", "services", "certificate_providers", "http_clients", "network_namespaces"):
        if state.get(key):
            config[key] = [native.record(r) for r in state[key] if check_all or r.get("enabled", True)]
    native.validate_references(config, {row.get("tag", "") for row in state["inbounds"]+state.get("endpoints", [])})
    return config


def client_config(state, c, totals):
    require(eligible(c, totals), "Account is disabled, expired, or has reached its traffic limit")
    address = state["settings"].get("server_address")
    require(address, "Set the public server address in Settings first")
    tls = {t["id"]: t for t in state["tls"]}
    outbounds = []
    for i in state["inbounds"]:
        if i.get("mode") == "native" or i["id"] not in c["inbound_ids"] or not i.get("enabled", True):
            continue
        obj = {"type": i["type"], "tag": i["tag"], "server": address, "server_port": i.get("public_port") or i["port"]}
        obj.update({k: v for k, v in user_entry(c, i["type"]).items() if k not in ("name", "alterId")})
        obj.update(options.client_options(i))
        if i.get("multiplex", {}).get("enabled"):
            obj["multiplex"] = copy.deepcopy(i["multiplex"])
        if i["type"] == "vmess":
            obj.setdefault("security", "auto")
        if i.get("tls_id"):
            t = tls[i["tls_id"]]
            obj["tls"] = {"enabled": True, "server_name": t["server_name"]}
            obj["tls"].update(options.tls_options(t, client=True))
            if t["kind"] == "self_signed" and not t.get("insecure"):
                obj["tls"]["certificate"] = [t["certificate"]]
            if i["type"] == "tuic" and not obj["tls"].get("alpn"):
                obj["tls"]["alpn"] = ["h3"]
        tr = transport(i)
        if tr:
            obj["transport"] = tr
        client_extra = copy.deepcopy(i.get("extra_client_options", {}))
        require(isinstance(client_extra, dict) and not set(client_extra) & {"type", "tag", "server", "server_port", "uuid", "password"}, "Managed client credentials and server cannot be overridden")
        for key, value in client_extra.items():
            if isinstance(value, dict) and isinstance(obj.get(key), dict):
                obj[key].update(value)
            else:
                obj[key] = value
        if i.get("tls_id"):
            profile = tls[i["tls_id"]]
            effective_tls = obj.get("tls", {})
            if profile["kind"] == "self_signed" and effective_tls.get("enabled") and not effective_tls.get("insecure"):
                effective_tls.setdefault("certificate", [profile["certificate"]])
        outbounds.append(obj)
    require(bool(outbounds), "No enabled inbound is assigned to this client")
    tags = [o["tag"] for o in outbounds]
    # Inbound names become outbound tags. Allocate managed tags without colliding
    # with user-defined names such as "proxy".
    used_tags = set(tags)
    def managed_tag(base):
        tag, suffix = base, 2
        while tag in used_tags:
            tag, suffix = f"{base}-{suffix}", suffix + 1
        used_tags.add(tag)
        return tag
    proxy_tag = managed_tag("proxy")
    direct_tag = managed_tag("direct")
    return {
        "log": {"level": "info", "timestamp": True},
        "dns": {
            "servers": [
                # Resolve only the proxy hostname locally to avoid a bootstrap loop.
                {"type": "local", "tag": "bootstrap"},
                # The authenticated server intercepts this sentinel and applies
                # its current Default DNS and DNS rules; no provider is hardcoded.
                {"type": "tcp", "tag": "remote", "server": CLIENT_DNS_ADDRESS,
                 "server_port": 53, "detour": proxy_tag},
            ],
            "rules": [{"clash_mode": "Direct", "action": "route", "server": "bootstrap"}],
            "final": "remote", "strategy": "prefer_ipv4",
        },
        "inbounds": [
            {"type": "mixed", "tag": "local", "listen": "127.0.0.1", "listen_port": 2080},
            {"type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
             "mtu": 1400, "auto_route": True, "strict_route": True,
             "platform": {"http_proxy": {"enabled": True, "server": "127.0.0.1", "server_port": 2080}}},
        ],
        "outbounds": [{"type": "selector", "tag": proxy_tag, "outbounds": tags, "default": tags[0]}]
                     + outbounds + [{"type": "direct", "tag": direct_tag}],
        "route": {
            "rules": [{"port": 53, "action": "hijack-dns"},
                      {"clash_mode": "Direct", "action": "route", "outbound": direct_tag},
                      {"clash_mode": "Global", "action": "route", "outbound": proxy_tag},
                      {"ip_is_private": True, "action": "route", "outbound": direct_tag}],
            "final": proxy_tag, "auto_detect_interface": True,
            "default_domain_resolver": {"server": "bootstrap", "strategy": "prefer_ipv4"},
        },
        # Native app controls use these mode names and the TUN HTTP proxy fields;
        # no external REST controller or additional listening port is exported.
        "experimental": {"clash_api": {"default_mode": "Rule"},
                         "cache_file": {"enabled": True, "cache_id": "nara-" + c["id"]}},
    }
