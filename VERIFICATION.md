# Verification — 2026-10-16

Version 0.2.0 was verified locally on macOS using **Python 3.12.14**, Python OpenSSL 3.5.8, the OpenSSL 3.6.4 command-line tool, and a native build of Sing-box 1.14.3 with `with_quic,with_v2ray_api`. Production installation targets Python 3.10+ on Linux. Earlier verification used Python 3.9.6; this regression is now exercised on Python 3.12 itself.

**55 automated tests passed without skips on Python 3.12.14** in the complete suite, including the original protocol/accounting tests and additional installation/custom-webPath tests. Coverage includes random mixed-case eight-letter defaults, default port 10000, custom values, re-prompting invalid/reserved/occupied ports, preserving existing entry defaults, path injection rejection, case-sensitive prefix routing, prefixed UI/assets/API/subscriptions, root-route isolation, path-scoped login/logout cookies, and all earlier authentication, configuration, TLS, expiry, quota, persistence, and rollback checks.

The old certificate path was reproduced failing for both an IP and a DNS name with `AttributeError: module ssl has no attribute match_hostname` on Python 3.12. The replacement uses OpenSSL for DNS/IP matching and retains key-pair and expiry validation. New tests cover generated certificates for DNS, IPv4 and IPv6 through both root and custom-webPath APIs, a removed Python SSL helper, mismatched names/keys, a missing OpenSSL executable, and legacy OpenSSL returning zero on a name mismatch. Legacy mismatch behavior is simulated; OpenSSL 1.1.1/3.0 was not installed on the test host.

Real core integration passed for **VLESS, VMess, Trojan, Hysteria2, TUIC, and AnyTLS**, transferring HTTP payloads through a loopback client and server and checking per-user upload/download counters. Restart persistence without double counting, DNS hostname bootstrap through the client system resolver, expiry enforcement, periodic quota enforcement, and rollback after a port bind failure also passed. No host routes, firewall, or system DNS were changed.

Browser checks verified English/LTR sign-in, one-click self-signed generation, inbound creation, client creation with an assigned inbound and 10 GiB allowance, settings save, and applying the configuration to a real local core. Desktop (1440 px) and mobile (390 px) layouts were inspected; the mobile page had a 390 px viewport and 390 px document width. Screenshots show an isolated local test account. Linux-only measurements remain unavailable in this macOS preview.

JavaScript syntax, Python compilation, and shell script syntax checks passed. No Persian UI/error strings remain in the application source; Persian documentation is separate.

The one-line installer supports Debian 12+/Ubuntu 22.04+ on amd64/arm64, retrieves a verified isolated Go toolchain, builds the feature-enabled core, and configures a systemd service. Shell syntax was checked. Official Go 1.27.2 Linux archive SHA-256 values were checked against the official download manifest.

The actual interactive configuration helper was also run in a controlling terminal with two empty answers: it produced a mixed-case eight-letter webPath, port 10000, and a mode-0600 environment file in an isolated temporary directory.

**Not verified:** executing the full bootstrap or application updater as root on Linux, actual Linux installation/systemd behavior, Docker image build/runtime, and real Linux `/proc` measurements. Docker was unavailable on the development host. No remote server credentials or address were supplied. The deployment files are prepared, but no remote deployment is claimed.

## Subscription QR verification (0.1.3)

The complete Python suite again passed all **55 tests without skips**. Static asset tests verify both locally served QR scripts at the root and under a custom webPath. **7 additional Node.js tests passed**, decoding the actual SVG modules with the independent jsQR decoder. They verify exact URLs for configured/custom paths, an origin-only setting, IPv6 with a port, long URLs, legacy root paths, rotated tokens, missing public URL guidance, and graceful handling of over-capacity links.

Browser checks verified the dedicated client QR action and QR in account details. PNG download succeeded; the downloaded 360 × 360 RGBA PNG was independently decoded and matched the exact demonstration subscription URL. The mobile QR dialog fit a 390 × 844 viewport with a document width of 390 px. The screenshot uses only an isolated demonstration account, example.com and a demonstration token. QR encoding uses a bundled MIT-licensed encoder; no external QR endpoint or CDN is used. Node.js and the independent decoder are development-only requirements. The same Linux deployment limitations above apply.

## Automatic apply and configuration review (0.2.0)

**70 Python tests passed without skips**, plus **7 QR decoder tests**. The complete
69-test suite passed, followed by an additional persistence-failure regression and
targeted rechecks after refining Hysteria2 bandwidth and Vision constraints. The HTTP API
integration uses the actual feature-enabled 1.14.3 core, rather than a mock, for
activation on save, account disable/reactivation, failed bind rollback, preserving
saved/active state on failure, failed and successful traffic resets, missing-core
behavior, token rotation without process restart, client-only insecure TLS, and
restoring the previous core/model after a simulated database publication failure.
The general authentication/API unit tests stub core startup; these do not substitute
for the separate real-core save tests.

Actual loopback payload transfers and per-user counters passed for VLESS Vision,
VMess authenticated length/global padding plus padded h2mux, Trojan fallback
configuration, Hysteria2 Salamander and Gecko, TUIC BBR and QUIC relay configuration,
and AnyTLS custom padding/client idle settings. Additional transfers passed for
WebSocket early data, gRPC, HTTP, HTTPUpgrade, and QUIC transports. The core also
rejected invalid padding in an unassigned disabled inbound. DNS cache/rule options
and DoQ/HTTP3 resolver configurations passed core validation; live public DoQ/HTTP3
resolution is not claimed.

Browser verification exercised Hysteria2 creation with obfuscation and assigning it
to the demo account using Save alone. Saved/active revision matched immediately.
TLS generation exposes Allow insecure and the additional ALPN/version controls.
Computed desktop body/input sizes are 16 px, helper text is 14 px, and table text
is 14 px. Browser checks and screenshots use only the isolated local demonstration
store; no production server configuration was changed.

Mobile checks at 390 × 844 confirmed 16 px body/input text, a 390 px document width, and a 352 px inbound dialog. DNS cache capacity was saved through the mobile UI and confirmed in the active model. The desktop layout was inspected at 1280 × 800.

## HTTP subscription QR fix (0.2.1)

**17 Node.js QR/clipboard tests passed**, including independent decoding of HTTP
and HTTPS QR payloads, configured IPv4/IPv6 addresses with ports and webPaths,
blank-public-URL fallback, root and index.html paths, ignoring browser query/hash,
explicit public URL precedence, and clipboard fallback success/failure without the
Clipboard API. **5 targeted Python tests passed** for HTTP/HTTPS URL validation,
saving HTTP public URLs through both root and prefixed APIs, and subscription
headers/revocation through both route forms. Other core behavior was unchanged
from the 0.2.0 verification above.

A browser preview on HTTP with an empty public_url displayed the QR and exact
current host/port/webPath subscription link without the former HTTPS setup gate.
The screenshot uses the isolated demonstration account. The HTTP clipboard fallback
was tested with DOM stubs; the local loopback browser is considered a secure context
and does not exercise that fallback. JavaScript syntax, Python compilation and
source packaging were checked. No remote Linux installation/update is claimed.

## Official Sing-box profile QR fix (0.2.2)

**28 Node.js tests passed.** The rendered SVGs are independently decoded with
jsQR. Both direct JSON URLs and the official remote-profile URI are checked for
HTTP/HTTPS, IPv4/IPv6, ports, custom paths, origin-only settings and long URLs.
Official URI checks round-trip Unicode/reserved characters in account names and
the nested subscription URL. Tests also cover format switching, matching copy and
PNG-source payloads through the real action handlers, HTTP clipboard fallback,
root paths, token rotation, empty public URLs and oversized QR fallback.

**4 targeted Python HTTP tests passed** for locally served assets at root/custom
paths and subscription headers/token revocation under both route forms. Browser
checks on the isolated HTTP demonstration store verified both format options in
the dedicated QR dialog and account details, with no browser errors. At 390 × 844,
the document remains 390 px wide and the 352 px dialog opens with the complete QR
visible; informational dialogs no longer scroll to their first selector on open.
Desktop and mobile screenshots use demonstration credentials only. JavaScript
syntax and source packaging were checked.

The official URI follows the upstream graphical-client remote-profile contract:
https://sing-box.sagernet.org/clients/general/#remote . Actual scanning on a physical
Android/iOS device and installation/updating on a remote Linux server were not
performed. The underlying full JSON profile and server runtime are unchanged.

## Official-app VPN connectivity (0.2.3)

The former client export had only a loopback mixed listener, so it did not capture
traffic in the official apps' VPN mode. Exports/subscriptions now add IPv4/IPv6
TUN, automatic routing/interface detection, port-53 DNS capture, proxied DoH,
a separate direct bootstrap resolver, and timestamped info logs. Managed selector
tags cannot collide with assigned inbound names. No account or TLS setting is
changed by this update.

**77 tests passed without skips in the complete Python 3.12.14 suite**, using the
feature-enabled Sing-box **1.14.3** core. **Two additional API tests passed** after
that run, confirming download/subscription equality at the root and a custom
webPath. **28 Node.js QR tests passed.** Coverage includes validation of the complete
VPN JSON for all six protocols, actual loopback protocol/transport transfers,
certificate verification, accounting, expiry/quota enforcement, automatic apply
and rollback, plus the new VPN routing/DNS structure.

A new integration test exercises Hysteria2 with Salamander and a hostname endpoint:
local UDP bootstrap resolves the node; a SOCKS DNS request on port 53 is captured
and resolved by a local TLS DoH fixture through the Hysteria2 connection, with
nonzero account upload. The loopback harness removes only the TUN inbound before
running and replaces public DNS endpoints with isolated fixtures. Full VPN
profiles are separately checked by the core. No host TUN, firewall, routes or
system DNS are created or modified by tests.

A separate one-off connection through the user-supplied Hysteria2 account fetched
a public HTTP page with **HTTP/1.1 200 OK**. This verifies the supplied endpoint and
credentials from this Mac's network, independently of device VPN integration.
The supplied account was held only in a private temporary directory and removed
after the check; it is not included in source, screenshots, or test fixtures.

Native Android/macOS graphical-app VPN activation and remote Linux update were
not performed. Existing remote profiles must be refreshed; local JSON files must
be downloaded and imported again. Python compilation, JavaScript syntax and source
packaging were checked.

## Full 1.14.3 configuration workspace (0.3.0)

The complete Python 3.12.14 suite passed **105 tests without skips** against a
newly built full-capability Sing-box **1.14.3**. Two subsequent targeted real-core
tests passed for advanced TLS override trust and native DNS/route UDP answering.
Native composition/reference tests were rerun after default-type alias and
cycle-validation refinements. **45 Node.js tests passed**, comprising the existing
28 independently decoded QR tests and 17 schema-form DOM tests with jsdom.

The bundled schema comes from the pinned 1.14.3 binary. Field help was generated
from **121 English configuration documents** at the same source revision. Tests
check all 19 inbound names, all 15 DNS types and every top-level configuration
section. DOM tests preserve nested arrays/maps, false/zero values, logical rules,
Snell versions and private-key data; they exercise add/remove, action switching,
new-record defaults, inline/local/remote rule-set choices and prototype-safe map
keys. General API state redaction and secret retention are tested separately.

Actual loopback transfers passed for the six original managed protocols and the
new standalone HTTP, Mixed, SOCKS, Shadowsocks, Hysteria and Snell 5/6 cases. A
native Direct UDP listener plus routing hijack and a Hosts/DNS rule returned the
expected reserved example address over a real UDP socket. Existing TLS verification,
quota/expiry enforcement, traffic persistence and rollback tests passed. Invalid
outbound references preserve both the saved model and running core. Unknown
references, outbound cycles and recursive rule-set cycles are rejected before core
activation. No host TUN, firewall, routes, system proxy or system DNS were changed.

API tests cover authenticated schema access, root/custom-webPath assets, full DNS
records and settings/default selection, routing order/revision guards, key redaction
and preservation, and cached dashboard update status. Daily-check tests cover
persisted 24-hour caching, independent component failures, preserving previous
results, stable-version comparison, prerelease rejection and response bounds. The
live upstream release metadata contained 168 assets and 285,031 bytes, confirming
that the response limit must exceed 256 KiB; the implementation permits 2 MB.

Browser verification on the isolated demonstration store created and auto-applied
a Shadowsocks listener, an ordered routing rejection, a Hosts resolver/map, a DNS
routing rule and a global DNS timeout. Saved and active revisions matched. The
endpoint and service type menus expose their respective schema variants. Mobile
inspection at **390 × 844** showed a **390 px** document, **352 px** dialog and
**16 px** input text. Desktop inspection used **1280 × 800**. Screenshots contain
only the demonstration store. The compact version/update strips replace the hero,
and the logo shows the full panel version.

After publication, a fresh live check successfully read the public panel manifest
(`0.3.0`) and official stable core release (`1.14.3`). The Overview displayed both
as up to date, and its browser console contained no warnings or errors. The saved
desktop screenshot includes these real check results.

The full standard-capability Darwin core was built and exercised locally. A Linux
amd64 core including Naive outbound/purego was cross-compiled successfully. The
matching pinned `libcronet.so` and license are installed beside the Linux binary;
ELF inspection confirmed standard glibc/libgcc dependencies. Linux execution,
Docker image execution, ARM64 compilation, privileged TUN/namespace/device behavior,
ACME issuance, Tor integration and live third-party endpoint/service accounts were
not tested. Their complete configuration fields are exposed, and host/account
requirements are documented rather than simulated. Native standalone listeners
intentionally do not receive panel-account quotas or subscription export.

JavaScript syntax, Python compilation, shell syntax, whitespace checks and source
packaging were checked. Node/jsdom/jsQR remain development-only dependencies.


## Interactive Linux management and panel HTTPS (0.3.1)

The full regression suite passed **127 tests without skips** against the full
Sing-box 1.14.3 binary and official Caddy 2.4.6/2.6.2 binaries. After the final
maintenance refinements, **31 installer/maintenance tests passed**, including
new controlling-terminal and PEM validation cases. The existing **45 Node tests**
passed again. Python compilation, shell syntax, source packaging and whitespace
checks also passed.

Both official Caddy binaries were downloaded into a temporary directory and
verified against the publisher's SHA-512 checksums. Generated automatic-certificate
configurations were adapted by each binary. For real proxy tests, each version
served a generated ECDSA certificate on an ephemeral loopback TCP port, forwarded
the complete webPath to an actual NARA HTTP handler, returned a verified TLS health
response, allowed administrator sign-in with a Secure/path-scoped cookie, served
authenticated state, and rejected paths outside the panel prefix. A final real-proxy
run also passed domain and reserved-public-IP cases on both versions. IP clients
send no SNI; generated IP sites set `default_sni` so certificate selection works
through loopback/NAT while retaining hostname/IP verification. No public ACME
request, host trust-store modification or privileged 80/443 listener was used.

Tests verify system package command order and failure propagation, ANSI/NO_COLOR
input labels, `/dev/tty` interaction when stdin is piped, invalid-menu recovery,
SQLite online backup with committed WAL data, private archive permissions,
keep-data/purge boundaries, refusing removal when a service cannot stop, automatic
URL/cookie/bind changes, retained HTTPS service reconstruction, and restoring the
prior environment/proxy/public URL on certificate or post-change startup failure.
An execution of the actual shell installer, with filesystem paths mapped to a
temporary fixture and OS commands replaced with test doubles, failed at readiness
and restored the original application, core, virtual environment, service, manager
command and entry settings.

Local integration ran on macOS. Actual Linux apt upgrades, distribution package
installation, systemd sandbox/capabilities, account creation/removal, production
ACME issuance/renewal, and a remote-server deployment were not performed. These
require a Linux target and, for public issuance, a configured domain and reachable
TCP 80/443. No user's server settings were changed during development.

## Independent subscription access and entry settings (0.4.0)

The release suite passed **152 Python tests without skips**, followed by an
additional regression confirming that upgrades from a single-site Caddy 2.4
installation persist its legacy syntax mode for future entry changes. **48 Node.js
tests passed**, including protocol selection, managed/standalone AnyTLS padding,
independently decoded QR payloads and subscription URL construction.

Real HTTP handlers verified independent subscription serving, identical exported
VPN JSON, traffic headers, revocation, authenticated/CSRF-protected entry changes,
and rejection of panel/login/admin routes on the subscription port. Actual Caddy
**2.4.6 and 2.6.2** ran dual-port HTTPS tests against the real panel/subscription
handlers: both domains and IP/no-SNI cases passed certificate verification. The
subscription HTTPS port served an actual generated profile and no admin assets.
The complete feature-enabled Sing-box 1.14.3 core passed the existing real traffic,
accounting, DNS/routing, auto-apply and rollback integrations, including AnyTLS.

Access broker tests verify four-field validation, revision checks, exclusive private
requests, occupied/saved inbound ports, port swaps, rollback of environment and
both URL models, separate HTTPS public/backend ports, maintenance rejection, and
request/result symlink safety. Maintenance and installer tests also cover previous
manager behavior and old HTTPS migration. These systemd/installation tests use
isolated fixtures or command mocks; they do not execute real systemd on Linux.

The actual installer helper ran in a controlling terminal with four empty answers:
it generated distinct mixed-case eight-letter webPath/subPath values and selected
10000/10001. Its temporary environment file had mode 0600. Shell/JavaScript syntax,
source packaging and archive contents were checked.

Browser checks used an isolated local store, demonstration certificate/account and
the real compatible core. They verified the blank protocol chooser, disabled Save,
automatically displayed nine-line AnyTLS padding, removed sidebar hostname box,
and all four Settings fields. Saving changed the actual preview from panel
2095/AbCdEfGh + subscription 2096/JkLmNoPq to panel 2097/NewPanelAb + subscription
2098/ClientFeed. The browser reconnected, signed in again, and displayed an official
Sing-box QR URI containing only the new independent subscription address. The
preview runner simulated systemctl solely for its own subprocesses; configuration
and data stayed under /private/tmp. No browser console warnings/errors remained.
The Settings screenshot contains only this demonstration environment.

**Not verified:** a root installation/upgrade on a real Linux host, production
systemd broker behavior, firewall reachability, public ACME issuance/renewal or a
Docker build/runtime. No production server was accessed or changed.
