"""Versioned, allow-listed Sing-box 1.14 options shared with the editor."""
import copy
import re
from urllib.parse import urlsplit


def field(key, label, kind="text", **kwargs):
    return dict(key=key, label=label, kind=kind, **kwargs)


def choice(key, label, values, **kwargs):
    return field(key, label, "select", choices=values, **kwargs)


QUIC = [field("idle_timeout", "Idle timeout", hint="For example 30s; blank uses the core default"),
        field("keep_alive_period", "Keep-alive period", hint="For example 15s"),
        field("stream_receive_window", "Stream receive window", "memory", hint="For example 8 MB"),
        field("connection_receive_window", "Connection receive window", "memory", hint="For example 20 MB"),
        field("max_concurrent_streams", "Maximum concurrent streams", "number", minimum=1, maximum=1000000),
        field("initial_packet_size", "Initial packet size", "number", minimum=1200, maximum=65527),
        field("disable_path_mtu_discovery", "Disable path MTU discovery", "checkbox")]
SERVER = {
    "vless": [choice("flow", "VLESS flow", ["", "xtls-rprx-vision"], hint="Vision requires TLS 1.3 over plain TCP and cannot use multiplex.")],
    "vmess": [field("alter_id", "Alter ID", "number", minimum=0, maximum=1, hint="0 uses AEAD (recommended); 1 enables the legacy protocol.")],
    "trojan": [field("fallback.server", "Fallback server", hint="Optional destination for unauthenticated TLS traffic"),
               field("fallback.server_port", "Fallback port", "number", minimum=1, maximum=65535),
               field("fallback_for_alpn", "Fallback destinations by ALPN", "json", hint='Optional JSON object, e.g. {"http/1.1":{"server":"127.0.0.1","server_port":8080}}')],
    "hysteria2": [choice("obfs.type", "Obfuscation", ["", "salamander", "gecko"]),
                  field("obfs.password", "Obfuscation password", "password", when="obfs.type"),
                  field("obfs.min_packet_size", "Gecko minimum packet size", "number", minimum=1, maximum=65527, when="obfs.type=gecko", hint="Default: 512 bytes"),
                  field("obfs.max_packet_size", "Gecko maximum packet size", "number", minimum=1, maximum=65527, when="obfs.type=gecko", hint="Default: 1200 bytes"),
                  field("up_mbps", "Server upload limit (Mbps)", "number", minimum=1, maximum=1000000, hint="Total inbound bandwidth; blank is unlimited."),
                  field("down_mbps", "Server download limit (Mbps)", "number", minimum=1, maximum=1000000),
                  field("ignore_client_bandwidth", "Ignore client bandwidth hints", "checkbox", hint="With server limits, requires Hysteria congestion control; without limits, requests BBR."),
                  choice("bbr_profile", "BBR profile", ["", "conservative", "standard", "aggressive"]),
                  choice("masquerade.type", "Masquerade response", ["", "proxy", "string"]),
                  field("masquerade.url", "Masquerade proxy URL", when="masquerade.type=proxy", hint="For example https://example.com"),
                  field("masquerade.rewrite_host", "Rewrite the proxy Host header", "checkbox", when="masquerade.type=proxy"),
                  field("masquerade.status_code", "Response status code", "number", minimum=100, maximum=599, default=200, when="masquerade.type=string"),
                  field("masquerade.content", "Response body", "textarea", when="masquerade.type=string"),
                  field("masquerade.headers", "Response headers", "json", when="masquerade.type=string")],
    "tuic": [choice("congestion_control", "Congestion control", ["", "cubic", "new_reno", "bbr"]),
             field("auth_timeout", "Authentication timeout", hint="Default: 3s"),
             field("heartbeat", "Heartbeat interval", hint="Default: 10s"),
             field("zero_rtt_handshake", "Allow 0-RTT handshake", "checkbox", hint="Faster reconnects allow replay risk. Disabled by default.")],
    "anytls": [field("padding_scheme", "Padding scheme", "lines", hint="One padding rule per line; blank uses the official default.")]
}
CLIENT = {
    "vless": [choice("packet_encoding", "UDP packet encoding", ["", "xudp", "packetaddr"])],
    "vmess": [choice("security", "Encryption", ["auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero"]),
              field("global_padding", "Global padding", "checkbox"),
              field("authenticated_length", "Authenticated length", "checkbox", default=True),
              choice("packet_encoding", "UDP packet encoding", ["", "xudp", "packetaddr"])],
    "trojan": [],
    "hysteria2": [field("disable_chrome_parrot", "Disable Chrome QUIC fingerprint", "checkbox", hint="Leave disabled for the default Chrome handshake.")],
    "tuic": [choice("udp_relay_mode", "UDP relay mode", ["", "native", "quic"]),
             field("udp_over_stream", "UDP over a QUIC stream", "checkbox", hint="Requires the relay mode above to be left at default.")],
    "anytls": [field("idle_session_check_interval", "Idle session check interval", hint="Default: 30s"),
               field("idle_session_timeout", "Idle session timeout", hint="Default: 30s"),
               field("min_idle_session", "Minimum idle sessions", "number", minimum=0, maximum=10000)]
}
LISTEN = [field("tcp_fast_open", "TCP Fast Open", "checkbox"),
          field("tcp_multi_path", "Multipath TCP", "checkbox"),
          field("disable_tcp_keep_alive", "Disable TCP keep-alive", "checkbox"),
          field("tcp_keep_alive", "TCP keep-alive delay", hint="Default: 5m"),
          field("tcp_keep_alive_interval", "TCP keep-alive interval", hint="Default: 75s"),
          field("udp_fragment", "Allow UDP fragmentation", "checkbox"),
          field("udp_timeout", "UDP session timeout", hint="Default: 5m")]
MULTIPLEX = [field("enabled", "Enable multiplex", "checkbox"),
             field("padding", "Require multiplex padding", "checkbox", when="enabled"),
             choice("protocol", "Client multiplex protocol", ["", "h2mux", "smux", "yamux"], when="enabled"),
             field("max_streams", "Maximum client streams per connection", "number", minimum=1, maximum=1000000, when="enabled")]
TRANSPORT = {
    "tcp": [], "quic": [],
    "ws": [field("headers", "Headers", "json"), field("max_early_data", "Maximum early data (bytes)", "number", minimum=0, maximum=1048576),
           field("early_data_header_name", "Early data header", hint="For Xray compatibility: Sec-WebSocket-Protocol")],
    "grpc": [field("idle_timeout", "Idle timeout"), field("ping_timeout", "Ping timeout"), field("permit_without_stream", "Keep alive without active streams", "checkbox")],
    "http": [field("host", "Host names", "lines"), field("method", "HTTP method"), field("headers", "Headers", "json"),
             field("idle_timeout", "Idle timeout"), field("ping_timeout", "Ping timeout")],
    "httpupgrade": [field("host", "Host name"), field("headers", "Headers", "json")]
}
TLS = [field("insecure", "Allow insecure (client)", "checkbox", hint="Clients accept any server certificate. Applies to subscriptions and downloaded configurations."),
       field("disable_sni", "Disable SNI (client)", "checkbox"), field("alpn", "ALPN protocols", "lines", hint="One per line, e.g. h3 or h2. Blank uses protocol defaults."),
       choice("min_version", "Minimum TLS version", ["", "1.2", "1.3"]),
       choice("max_version", "Maximum TLS version", ["", "1.2", "1.3"]),
       field("handshake_timeout", "TLS handshake timeout", hint="For example 10s")]
DNS = [choice("strategy", "Address preference", ["", "prefer_ipv4", "prefer_ipv6", "ipv4_only", "ipv6_only"]),
       field("disable_cache", "Disable DNS cache", "checkbox"),
       field("disable_expire", "Keep expired DNS cache entries", "checkbox"),
       field("independent_cache", "Separate cache for each resolver", "checkbox"),
       field("cache_capacity", "DNS cache capacity", "number", minimum=1024, maximum=10000000),
       field("reverse_mapping", "Reverse mapping", "checkbox")]
DNS_RULE = [field("invert", "Invert this match", "checkbox"),
            choice("ip_version", "Query address family", ["", 4, 6]),
            field("disable_cache", "Disable cache for this rule", "checkbox"),
            field("rewrite_ttl", "Rewrite TTL (seconds)", "number", minimum=0, maximum=4294967295),
            choice("strategy", "Address preference", ["", "prefer_ipv4", "prefer_ipv6", "ipv4_only", "ipv6_only"])]


def schema():
    return dict(server=SERVER, client=CLIENT, listen=LISTEN, multiplex=MULTIPLEX,
                transport=TRANSPORT, tls=TLS, quic=QUIC, dns=DNS, dns_rule=DNS_RULE, version="1.14.3")


def get(obj, key, default=None):
    for part in key.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return default
        obj = obj[part]
    return obj


def check(ok, message):
    if not ok:
        raise ValueError(message)


def validate_options(values, fields, label):
    check(isinstance(values, dict), label + " must be an object")
    allowed = {}
    for f in fields:
        node = allowed
        parts = f["key"].split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None
        value = get(values, f["key"])
        if value is None:
            continue
        kind = f["kind"]
        error = "Invalid " + f["label"].lower()
        if kind == "checkbox":
            check(type(value) is bool, error)
        elif kind == "number":
            check(type(value) is int and f["minimum"] <= value <= f["maximum"], error)
        elif kind == "select":
            check(value in f["choices"], error)
        elif kind == "lines":
            check(isinstance(value, list) and len(value) <= 100 and all(isinstance(x, str) and 0 < len(x) <= 2048 for x in value), error)
        elif kind == "json":
            check(isinstance(value, dict) and len(value) <= 100, error)
        else:
            check(isinstance(value, str) and len(value) <= (16384 if kind == "textarea" else 2048), error)
            check("\0" not in value and (kind == "textarea" or not any(c in value for c in "\r\n")), error)
            if value and (f["key"].endswith(("timeout", "interval", "period", "keep_alive")) or "_timeout" in f["key"]):
                check(bool(re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?(?:ns|us|µs|ms|s|m|h))+", value)), error + "; use a duration such as 30s or 5m")
            if value and kind == "memory":
                check(bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?\s*(?:B|KB|MB|GB|KiB|MiB|GiB)", value, re.I)), error)
    def walk(obj, tree):
        for key, value in obj.items():
            check(key in tree, "Unsupported " + label + " field: " + str(key))
            if tree[key] is not None:
                check(isinstance(value, dict), "Invalid " + label + " object")
                walk(value, tree[key])
    walk(values, allowed)


def validate_inbound(i):
    protocol, kind = i["type"], i.get("transport", "tcp")
    server = i.get("server_options", {})
    client = i.get("client_options", {})
    validate_options(server, SERVER[protocol] + (QUIC if protocol in ("hysteria2", "tuic") else []), "protocol")
    validate_options(client, CLIENT[protocol], "client")
    validate_options(i.get("listen_options", {}), LISTEN, "listen")
    validate_options(i.get("multiplex", {}), MULTIPLEX if protocol in ("vless", "vmess", "trojan") else [], "multiplex")
    validate_options(i.get("transport_options", {}), TRANSPORT[kind], "transport")
    if get(server, "flow"):
        check(bool(i.get("tls_id")) and kind == "tcp", "VLESS Vision requires TLS over plain TCP")
        check(not get(i, "multiplex.enabled", False), "VLESS Vision cannot use multiplex")
    if get(server, "obfs"):
        check(get(server, "obfs.type") in ("salamander", "gecko") and bool(get(server, "obfs.password")), "Choose an obfuscation type and password")
        if get(server, "obfs.type") == "gecko":
            check(get(server, "obfs.min_packet_size", 512) <= get(server, "obfs.max_packet_size", 1200), "Gecko minimum packet size exceeds the maximum")
        else:
            check(not any(k in server["obfs"] for k in ("min_packet_size", "max_packet_size")), "Packet size options require Gecko obfuscation")
    if protocol == "hysteria2":
        check(bool(server.get("up_mbps")) == bool(server.get("down_mbps")), "Set both Hysteria2 bandwidth limits or leave both blank")
        masquerade = server.get("masquerade", {})
        if masquerade:
            check(masquerade.get("type") in ("proxy", "string"), "Choose a masquerade response type")
            if masquerade["type"] == "proxy":
                u = urlsplit(masquerade.get("url", ""))
                check(u.scheme in ("http", "https") and u.hostname and not u.username, "Masquerade proxy must be an HTTP(S) URL")
            if "headers" in masquerade:
                validate_headers(masquerade["headers"])
    if protocol == "trojan":
        for dest in [server["fallback"]] if "fallback" in server else []:
            validate_destination(dest)
        for alpn, dest in server.get("fallback_for_alpn", {}).items():
            check(isinstance(alpn, str) and 0 < len(alpn) <= 255, "Invalid fallback ALPN")
            validate_destination(dest)
        check(kind == "tcp" or not (server.get("fallback") or server.get("fallback_for_alpn")), "Trojan fallback requires plain TCP transport")
    if protocol == "tuic":
        check(not (client.get("udp_over_stream") and client.get("udp_relay_mode")), "UDP over stream conflicts with the explicit UDP relay mode")
    if kind == "quic":
        check(bool(i.get("tls_id")), "QUIC transport requires TLS")
    if "headers" in i.get("transport_options", {}):
        validate_headers(i["transport_options"]["headers"])


def validate_headers(headers):
    check(all(isinstance(k, str) and bool(re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", k)) and
              (isinstance(v, str) or isinstance(v, list) and all(isinstance(x, str) for x in v)) and
              not any("\r" in x or "\n" in x for x in ([v] if isinstance(v, str) else v))
              for k, v in headers.items()), "Invalid HTTP headers")


def validate_destination(dest):
    from .config import host, integer
    check(isinstance(dest, dict) and set(dest) == {"server", "server_port"}, "Fallback requires a server and port")
    host(dest["server"])
    integer(dest["server_port"], 1, 65535, "Fallback port")


def server_options(i):
    return {k: copy.deepcopy(v) for k, v in i.get("server_options", {}).items() if k not in ("flow", "alter_id")}


def client_options(i):
    s = i.get("server_options", {})
    both = {"vless": ("flow",), "vmess": ("alter_id",), "trojan": (),
            "hysteria2": ("obfs", "bbr_profile"),
            "tuic": ("congestion_control", "zero_rtt_handshake", "heartbeat"), "anytls": ()}
    result = {k: copy.deepcopy(s[k]) for k in both[i["type"]] if k in s}
    if i["type"] == "hysteria2":
        if s.get("up_mbps"):
            result.update(up_mbps=s["down_mbps"], down_mbps=s["up_mbps"])
    result.update(copy.deepcopy(i.get("client_options", {})))
    return result


def tls_options(t, client=False):
    keys = ("alpn", "min_version", "max_version", "handshake_timeout") + (("insecure", "disable_sni") if client else ())
    return {k: copy.deepcopy(t[k]) for k in keys if t.get(k)}
