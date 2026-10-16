# Configuration review — NARA 0.2.0

The editor targets the installed **Sing-box 1.14.3** core. This review uses the
official documentation for the panel's supported features, including the
corresponding outbound fields: a server option is useful only when the exported
client configuration also matches it. The live documentation includes 1.15-only
fields; these are not silently enabled on the pinned 1.14.3 core.

## Supported protocol editors

| Feature | Panel options and behavior | Official reference |
| --- | --- | --- |
| VLESS | UUID managed per client; optional Vision flow applied to server users and client exports; UDP packet encoding. Vision requires TLS 1.3 over plain TCP and excludes multiplex. | [Inbound](https://sing-box.sagernet.org/configuration/inbound/vless/), [outbound](https://sing-box.sagernet.org/configuration/outbound/vless/) |
| VMess | Managed UUID; AEAD / legacy Alter ID; client encryption, global padding, authenticated length, and UDP packet encoding. | [Inbound](https://sing-box.sagernet.org/configuration/inbound/vmess/), [outbound](https://sing-box.sagernet.org/configuration/outbound/vmess/) |
| Trojan | Managed password; fallback server/port and per-ALPN fallback destinations; optional multiplex and transports. | [Inbound](https://sing-box.sagernet.org/configuration/inbound/trojan/), [outbound](https://sing-box.sagernet.org/configuration/outbound/trojan/) |
| Hysteria2 | Salamander and Gecko obfuscation, password and Gecko packet sizes; server upload/download limits; client bandwidth handling; BBR profile; proxy or fixed-response masquerade; QUIC tuning; client Chrome fingerprint option. Obfuscation is copied into every assigned client export. | [Inbound](https://sing-box.sagernet.org/configuration/inbound/hysteria2/), [outbound](https://sing-box.sagernet.org/configuration/outbound/hysteria2/) |
| TUIC | Managed UUID/password; congestion control, authentication timeout, heartbeat, explicit 0-RTT opt-in; QUIC tuning; client UDP relay mode or UDP-over-stream. | [Inbound](https://sing-box.sagernet.org/configuration/inbound/tuic/), [outbound](https://sing-box.sagernet.org/configuration/outbound/tuic/) |
| AnyTLS | Managed password; custom padding scheme; client idle session intervals and minimum idle sessions. | [Inbound](https://sing-box.sagernet.org/configuration/inbound/anytls/), [outbound](https://sing-box.sagernet.org/configuration/outbound/anytls/) |

Hysteria2 bandwidth is an aggregate inbound setting, independent of an account's
traffic allowance. Server upload/download limits are reversed in client exports
to match each peer's direction. Without server bandwidth limits, exports use BBR negotiation. With limits set,
exports include matching client limits even when client bandwidth hints are ignored.
TUIC 0-RTT stays disabled unless explicitly selected; the form explains replay risk.

## Shared settings

| Feature | Panel coverage | Official reference |
| --- | --- | --- |
| TLS | PEM import, self-signed generation, certificate/key/SAN/expiry checks; per-profile **Allow insecure**, client SNI suppression, ALPN, TLS 1.2/1.3 bounds, handshake timeout. `insecure` belongs only in client TLS, never in server TLS. The default still verifies self-signed certificates using the exported public certificate. | [TLS](https://sing-box.sagernet.org/configuration/shared/tls/) |
| Transports | Plain TCP, WebSocket, gRPC, HTTP, HTTPUpgrade, and QUIC for VLESS/VMess/Trojan. Path/service name, headers, host/method, early data, and keep-alive controls where supported. Built-in QUIC protocols show no misleading TCP transport selector. | [V2Ray transport](https://sing-box.sagernet.org/configuration/shared/v2ray-transport/) |
| Multiplex | VLESS/VMess/Trojan; enable, padding, client h2mux/smux/yamux, maximum streams. Server receives only server-supported fields. | [Multiplex](https://sing-box.sagernet.org/configuration/shared/multiplex/) |
| Listener | TCP Fast Open, multipath TCP, keep-alive settings, UDP fragmentation and session timeout. Managed address/ports remain separate. | [Listen fields](https://sing-box.sagernet.org/configuration/shared/listen/) |
| QUIC | Idle timeout, keep-alive period, receive windows, stream count, initial packet size, and path MTU discovery for Hysteria2/TUIC. | [QUIC](https://sing-box.sagernet.org/configuration/shared/quic/), [HTTP2 fields](https://sing-box.sagernet.org/configuration/shared/http2/) |
| DNS | UDP/TCP/DoT/DoH/DoQ/HTTP3/local; bootstrap resolver selection; cache controls, capacity, reverse mapping and IP preference. Rules include domain, suffix, keyword, regex, query type and rule set, inversion, IP version, cache bypass and TTL rewriting. | [DNS](https://sing-box.sagernet.org/configuration/dns/), [servers](https://sing-box.sagernet.org/configuration/dns/server/), [rules](https://sing-box.sagernet.org/configuration/dns/rule/), [actions](https://sing-box.sagernet.org/configuration/dns/rule_action/) |
| Rule sets | Inline JSON and remote HTTPS source/SRS; optional remote update interval. | [Rule sets](https://sing-box.sagernet.org/configuration/rule-set/), [source format](https://sing-box.sagernet.org/configuration/rule-set/source-format/) |
| Accounts | Per-user credentials, expiry, traffic counters and allowance, inbound assignments, JSON downloads, private subscription URL and QR. Statistics continue to use the feature-enabled core. | [V2Ray API](https://sing-box.sagernet.org/configuration/experimental/v2ray-api/) |

## Save and activation

Every configuration save, deletion, certificate generation, rule reorder, usage
reset, and subscription rotation validates and applies automatically. Form edits
are submitted with **Save**; keystrokes alone do not change the running service.
The server validates both server and client configurations with the installed
core, including disabled/unassigned inbounds, without starting those listeners.

Changes that affect the running configuration restart the managed core. Metadata
edits and subscription token rotation keep the current process when the generated
server configuration and certificate material are unchanged. Successful changes
publish saved/active state and any usage reset together in a SQLite transaction.
Failed validation preserves the working core; failed startup attempts to restore
the preceding configuration and retains the previous database settings. Usage
resets take effect only after a successful start.

Old installations may contain saved drafts from 0.1.x. They remain intact during
the code update; the next successful save validates and activates that stored model.
The existing **Start core** control remains for a stopped service.

## Deliberate boundaries

This is a managed editor for six protocols, rather than an unrestricted editor
for every Sing-box feature. Hysteria Realm/NAT traversal, file masquerade, custom
network namespaces/routing marks, TCP Brutal, REALITY/ECH/uTLS, automatic ACME,
mutual TLS, arbitrary outbound routing, logical DNS rule trees and additional
inbound types are not implemented here. They are not presented as working UI
switches. Certificate renewal, Linux socket capabilities and external DNS/network
availability still depend on the host environment. See README for accounting and
operational limits and VERIFICATION for actual test coverage.

## HTTP subscriptions (0.2.1)

Public panel URL is optional and accepts HTTP or HTTPS. When blank, the subscription link and QR use the current browser base URL, preserving the port and exact webPath. An explicit public URL takes precedence; an origin-only URL inherits the current path. This does not change inbound TLS profiles or the configured secure-cookie policy. Copy link includes a fallback for HTTP origins without the Clipboard API.

## QR import formats (0.2.2)

Official Sing-box graphical clients require the [remote-profile import URI](https://sing-box.sagernet.org/clients/general/#remote): `sing-box://import-remote-profile?url=urlEncodedURL#urlEncodedName`. The default QR now uses this scheme with an encoded subscription URL and account name. A second format exposes the direct JSON subscription URL. Both the dedicated dialog and account details offer the selector; copy and PNG download use its current value. This adds no Clash YAML or protocol-link/Base64 endpoint. HTTP and HTTPS subscription URLs are supported in both formats.

## Official-app VPN profile (0.2.3)

Exports and subscriptions now include a dual-stack TUN with automatic routing, strict routing and MTU 1400, in addition to the existing loopback mixed listener. DNS traffic on port 53 is captured; Cloudflare DoH goes through the selected outbound. Proxy-server hostnames use a separate direct UDP bootstrap resolver, and automatic interface detection prevents the proxy socket from routing back into the TUN. Managed selector tags avoid collisions with inbound names. Info-level timestamped logs make startup and connection failures visible.

This follows the upstream [client VPN model](https://sing-box.sagernet.org/manual/proxy/client/#virtual-interface), [TUN fields](https://sing-box.sagernet.org/configuration/inbound/tun/), [typed DoH transport](https://sing-box.sagernet.org/configuration/dns/server/https/) and [route configuration](https://sing-box.sagernet.org/configuration/route/). Refresh existing remote profiles after updating; re-import local JSON files. Server-side DNS settings and inbound TLS/obfuscation credentials retain their existing behavior.
