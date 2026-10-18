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

## Build download resilience and server information (0.4.1)

The full release suite passed **162 Python tests without skips**. After refining
minimal-Linux/ARM identification and cancellation cleanup, **12 targeted build and
hardware tests passed**, including new hostname fallback, ARM lscpu model lookup,
and termination of the owned compiler process on interruption. **49 Node.js tests
passed**, including distinct escaped IPv4/IPv6/CPU-model Overview rows and the
unavailable/unassigned states. The dashboard API exposes all three metrics under
both root and custom panel paths.

The actual updated build script completed for the native Darwin target and for
**Linux amd64** with the upstream standard capabilities plus V2Ray accounting and
purego on Linux. Its separate dependency resolution, readonly module graph,
`go mod verify`, reduced-parallelism compilation and Linux Cronet-library copy all
completed. The Linux ELF and matching library were checked as artifacts; the ELF
was not executed on this macOS host. An additional **fresh-cache download of the
exact reported nftables pseudo-version** succeeded through the official Go proxy
and checksum database. Its module/archive hashes matched the pinned core go.sum.
This establishes dependency availability here, not connectivity on the user's
failing servers; the original final error after `go: downloading` was not supplied.

Real subprocess tests simulated transient timeouts followed by recovery, exhausted
retries, compiler/memory errors, checksum failures and cancellation. Retries retain
logs/cache and remain bounded; checksum failures stop without retrying or disabling
verification. Full Linux apt/systemd installation, a real out-of-memory event and
Docker build/runtime were not executed. Docker now includes the build helper's
Python dependency and the iproute2 runtime dependency.

Metrics tests used x86/ARM CPU and Linux interface fixtures, including multiple
addresses, duplicate removal, private/global ordering, loopback/link-local filtering,
tentative/deprecated IPv6, a missing family, missing tools and a one-minute refresh.
No public IP lookup service is contacted. Browser inspection used the isolated
macOS preview and real CPU model, showed its own labeled row, and recorded no
console warnings/errors. The screenshot correctly shows unavailable Linux address
discovery on macOS rather than invented IP values. No production server was changed.

Shell/JavaScript syntax, source packaging, version consistency, private build-log
permissions and archive contents were checked. Credentials/databases and Go caches
are excluded from the source package.

## Legacy uninstall compatibility (0.4.2)

All **30 maintenance tests passed**, including four new regressions for an older
installation without access-broker/HTTPS units, a real disable failure, a systemd
inspection failure and an active unit with a missing file. Missing inactive units
are skipped using LoadState; installed units still require successful disable/stop
before application deletion. Genuine systemd errors remain actionable and preserve
application/data files. Existing keep-data, purge, backup and other-site isolation
tests passed. Tests use temporary layouts and mocked systemctl; no real server
uninstall was performed. The user's supplied output reports a completed purge;
its missing-unit messages came from optional units absent on that installation.

Version consistency, source packaging and whitespace checks passed. No new browser
check was needed because this change affects terminal maintenance only.


## Prebuilt core installation (0.5.0)

The full local regression suite passed **181 Python tests without skips**; all
**49 Node.js tests passed**. The 12 prebuilt-core tests cover pinned archive and
payload hashes, architecture/provenance checks, unsafe archive entries, missing
files, fixed HTTPS download targets, packaging notices, and installer failure
before stopping an existing service. Tests confirm neither Go nor Git is invoked
by dependency preparation/download failure. Diagnostic output is restricted to
fixed category labels and integer counts; private logs/configurations are not
published.

[Native release build 39005303415](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39005303415)
built the exact upstream 1.14.3 commit on native Ubuntu amd64 and arm64 runners.
Both ran **24 real-core/auto-apply integration tests successfully**, loaded the
matching Cronet shared library, and published the archives together in
[core-v1.14.3-nara.1](https://github.com/kevinzakarian/Nara-Panel/releases/tag/core-v1.14.3-nara.1).
Both archive SHA-256 values match the published SHA256SUMS and GitHub asset digests.
The actual installer downloader also downloaded and verified both architectures
on the development host without executing the Linux ELF files there.

[Go-free verification 39005476018](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39005476018)
passed on **both architectures** inside `python:3.12-slim-bookworm` containers.
The jobs explicitly assert that Go and Git are absent, obtain source through
checkout's archive fallback, download the actual public core release, validate
its pinned hashes/metadata/ELF, load Cronet, then pass the same **24 integration
tests** with real proxy connections, traffic accounting and automatic apply.

The Linux checks exposed fixture assumptions: the DoH fixture now serves
persistent HTTP/1.1 responses, and Hysteria 1 loopback tests use a bandwidth
appropriate to microsecond RTT because upstream Brutal derives its congestion
window from bandwidth times RTT. Both plain and obfuscated Hysteria 1 transfers
pass in the Go-free jobs, alongside Hysteria2 Salamander/Gecko and the other
covered protocols. These changes affect test fixtures only; generated user
profiles and upstream core source remain unchanged. Full payload-length checks
and traffic counters remain required.

Server installation, manager full upgrade and Docker build stages now download
prepared binaries with no source-build fallback. Failed downloads/integrity
checks occur before stopping the installed service. The build script/toolchain
is retained for maintainers and GitHub runners only. Shell syntax, version
consistency, whitespace and source archive contents were checked. Full apt/systemd
installation on a production server and a complete Docker image build were not
performed; native Ubuntu and minimal Debian runtime checks above were executed.

## DNS bootstrap and installation credentials (0.5.1)

The full suite passed **196 Python tests without skips** and **50 Node.js tests**.
After the final database-owner safeguard, all **11 credential/summary tests**
passed again. Shell/JavaScript syntax and whitespace checks passed.

The supplied UI error was generic; the original resolver settings/private server
log were not available. A new HTTPS resolver with `server: dns.google` and no
`domain_resolver` reproduced the exact core rejection path (missing domain
resolver). The new form visibly seeds the existing default DNS as its bootstrap.
Real-core API tests verify missing-bootstrap and URL-in-Server errors return
specific messages and preserve saved/active state, while the corrected hostname
resolver saves and starts successfully. UDP/TCP/TLS/HTTPS/QUIC/HTTP3 validation,
IP-only resolvers, object-form bootstrap settings, invalid references, self
references and detoured domains are covered. Existing cycle checks remain active.

Credential tests cover a prompted custom username, explicit username, Enter's
admin default, reprompting invalid interactive input, confirmation failures,
case-sensitive custom-name login/session identity, and retaining the name during
password reset. New names are validated; existing names remain preserved when
resetting only a password. The sign-in form no longer pre-fills admin.

Terminal stream tests verify distinct cyan URL, green username and yellow new
password output, NO_COLOR/plain output, HTTPS public URLs, IPv6 brackets, and
escaped terminal controls. A newly chosen password is handed off in an exclusive
0600 file inside a private temporary /run directory. The success summary reads it
only after readiness/HTTPS/subscription checks, writes the password only to the
controlling terminal, deletes the handoff, and never prints hashes or passwords
into redirected stdout. The shell trap also removes the directory on failures.
Existing installations show the retained username and an unchanged-password
notice. The summary uses the existing database-owner helper rather than opening
service SQLite/WAL files as root; delegation is tested.

Both Linux amd64 and arm64 jobs passed **36 tests each**, covering real core
traffic, DNS saves, automatic apply and installation credential flows, in
[Go-free verification 39007779691](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39007779691).
The pinned compatible core release is reused. Full root apt/systemd installation
on a production host was not performed; installer rollback, credential flows and
terminal rendering were tested using isolated layouts/streams.

## Pasted IP resolver addresses and displayed form values (0.5.2)

The supplied private-log excerpt identifies DNS server index 1 and the core
message `missing domain resolver for domain server address` on NARA 0.5.0. A
UDP record with `server: 8.8.8.8` and `server_port: 53` passes the core check, API save and activation.
Adding leading/trailing whitespace or a newline to the IP reproduces exactly that
core message: the core classifies the untrimmed string as a domain. The original
submitted payload was not available, so whitespace versus a stale form value or
another hostname resolver cannot be established for the user's host.

Remote DNS addresses are now trimmed at the API/model boundary and during
validation/config generation, covering both native and legacy records. This is
limited to the Server field of UDP/TCP/TLS/HTTPS/QUIC/HTTP3 records; headers,
credentials, PEM data and other options are preserved. Native DNS field errors
include the affected tag. A genuine hostname still needs a separate resolver;
IP-only records do not require one.

The form now synchronizes changed displayed controls before saving and before
structural changes, covering autofill/input methods that omit an input event.
Unchanged values retain their original representation, including CRLF data.
The UI regression changes HTTPS to UDP after a silent address edit, adds port 53,
and checks the actual save payload is exactly `8.8.8.8`, with no stale TLS/DoH
options. Tests also cover a silent edit after a normal input event and restoring
the original value.

All **53 Node.js tests** and **14 targeted Python tests** passed. Real API/core
regressions save a pasted `8.8.8.8` containing spaces/tabs/CRLF, without a bootstrap,
in native and legacy modes, and verify normalized saved/active state and a running
core. Existing hostname validation and rollback checks remain active. Full host
installation and the user's private configuration were not accessed.

The complete local suite subsequently passed **199 Python tests with no skips**.
Both native Linux amd64 and arm64 jobs passed **37 tests each** without Go or
Git using the actual published prebuilt core in
[run 39008747429](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39008747429).


## Guided routing workflow (0.6.0) — 2026-10-17

The full local suite passed **202 Python tests without skips** on Python 3.12 with the real native Sing-box 1.14.3 core and Caddy 2.4.6/2.6.2. **72 Node.js tests passed**, including 19 new routing UI tests. The new HTTP integration saves a proxy destination, inline shared set and guided rule payloads; moves a rule down, disables it, changes the final destination and object-form domain resolver, and inspects the actual active core config. Private-network blocking remains first, disabled rules are omitted, and deleting a referenced default destination is rejected without changing the saved/active state. API tests exercise both directions, list boundaries, unknown IDs/directions, stale revisions and custom-webPath asset serving.

UI tests cover match/action/scope generation, list validation, numeric port ranges, regular expressions containing commas, stale hidden-field removal, guided/JSON round trips, full preservation of logical rules/transports/TLS trust fields and advanced shared sets, action-specific ordering warnings, escaped labels, readable specialized condition summaries, group membership, object resolver preservation and revision-checked controls. Anonymous SOCKS does not require credentials or expose unsupported TLS fields. Proxy passwords retain surrounding whitespace.

An isolated loopback preview exercised the actual browser and core: creating a domain block, moving its priority, and creating a port-53 DNS handling rule all saved and applied successfully. Desktop 1440 px and phone 390 × 844 layouts were inspected. The phone document width was 390 px; the rule dialog measured 352 px with 350 px scroll content. The new screenshot contains only demonstration names/domains and an isolated preview account. No production server was accessed or host routing/firewall/DNS changed. The existing schema, records and advanced JSON retain all supported specialized 1.14.3 options; common forms add no migration of existing settings.

GitHub Actions [run 39054711600](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39054711600) passed on native Ubuntu 24.04 amd64 and arm64 runners in a minimal Python Debian container with no Go or Git installed. Both architectures downloaded the existing public verified core and passed all **38 real-core/auto-apply/credential tests**, including the new routing workflow. The verified implementation commit is `65cfb38`; the subsequent commit adds only this verification record and the rule-form screenshot/documentation. Full root installation/systemd and a user's remote server are not claimed by these checks.


## Native client controls and panel-backed DNS (0.6.1) — 2026-10-17

The full local suite passed **207 Python tests without skips** using the native 1.14.3 core and both Caddy versions; **73 Node.js tests passed**. The exported complete VPN profiles pass the core check for all six managed account protocols. The final client-readiness helper was rechecked with both mode/selection persistence and DNS-policy tests after adding controller readiness checks.

Real loopback tests cover authenticated client DNS forwarding for VLESS, VMess, Trojan, Hysteria2, TUIC and AnyTLS, with private-network blocking enabled. A Hysteria2 profile receives answers from resolver A, then resolver B after the panel default changes, and then a resolver selected by a server DNS rule. The exported profile stays unchanged; each server core restart is followed by reconnecting that same profile, so the test does not claim uninterrupted QUIC sessions or zero-downtime DNS changes. All resolver endpoints are local fixtures; no public DNS provider or production account is used.

A second real-core test verifies Rule-mode local traffic bypassing the server, Global-mode traffic reaching the server and incrementing accounting, and Direct mode bypassing it. The selected backup outbound and Direct mode persist after restarting the client. Direct-mode DNS reaches the local fixture resolver without using the proxy resolver. A temporary loopback Clash controller is used only by this test to exercise the manager; exported profiles contain no REST controller address. Their native app controls use the Clash mode rules and TUN `platform.http_proxy` fields. DNS interception stays ahead of mode routing. Cache databases and test logs stay inside temporary private directories.

Unit tests verify the DNS bridge is restricted to the sentinel address, port 53 and managed authenticated inbounds; it precedes private-address blocking and disappears when there is no active managed listener. Resolver credentials/options and private server file paths are not exported, the input state is not mutated, and managed outbound tags remain collision-free. Routing shows the managed DNS policy before traffic protection. The change does not open a DNS listener or alter the host's routing/firewall/system DNS during these checks.

The UI contract was reviewed against official [TUN HTTP proxy fields](https://sing-box.sagernet.org/configuration/inbound/tun/#platformhttp_proxy), [Clash mode documentation](https://sing-box.sagernet.org/configuration/experimental/clash-api/#default_mode), [1.14.3 mode calculation](https://github.com/SagerNet/sing-box/blob/v1.14.3/experimental/clashmode/mode_list.go), and the official Apple app's platform/dashboard code. The actual SFM/SFA device UI and VPN extension were **not** run in this verification; app UI/override preferences can affect which cards appear. Existing remote/local profiles must be refreshed/reimported after upgrading, then reconnected. GitHub Actions [run 39058174074](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39058174074) passed on native Ubuntu 24.04 amd64 and arm64 runners in a minimal Go-free/Git-free Python container: **41 integration tests passed on each architecture** with the existing public prebuilt 1.14.3 core. The verified implementation commit is `1a501a3`. The subsequent verification commit also strengthens the existing privacy regression with a fake resolver authorization header and private CA path; that final unit test passed locally. No actual user credentials or remote client logs were published.


## Independent IP-address DNS resolvers (0.6.2) — 2026-10-17

New resolver forms no longer preselect a Domain Resolver for their default IP-address server. DNS normalization strips unused `domain_resolver` from IPv4/IPv6 remote server records, both native and legacy, without mutating the input. Saved/active models are normalized when read, so references auto-filled by older versions disappear from the UI and cannot block deleting an otherwise unused bootstrap resolver. Core generation and cycle detection use the same normalization. Hostname dependencies, cycle checks, default resolver requirements and other real references remain validated. TLS SNI/certificate options and non-DNS settings are preserved.

The real-core HTTP API regression loads an old model containing unused bootstrap references, deletes bootstrap, and verifies the remaining model is applied with the core running. It then adds a genuine hostname dependency and confirms deletion is rejected without replacing the saved model or stopping the core. Unit coverage includes IPv4/IPv6 and native/legacy records. The UI regression verifies an independent new IP resolver and explicit selection of a Domain Resolver for a hostname. Tests use temporary private data and loopback services; no production server, host routes, or host DNS are changed.

Local verification: **209 Python tests passed** with the real bundled 1.14.3 core and the existing Caddy test binaries; no skips. **73 Node.js tests passed**. Full local validation completed before publication.

GitHub Actions [run 39059484389](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39059484389) passed on native Ubuntu 24.04 amd64 and arm64, using the existing public prebuilt 1.14.3 core in a Go-free/Git-free runtime container. Both architecture checks passed all 42 integration tests, including the bootstrap deletion regression. Implementation commit: `2336fa7`; this follow-up changes verification documentation only.


## DNS resolver form layout (0.6.3) — 2026-10-17

DNS resolver editing uses a guided layout over the existing exact 1.14.3 schema. Tag, resolver type, Server and Server Port are permanent controls; remote DNS ports use editable defaults (UDP/TCP 53, TLS/QUIC 853, HTTPS/HTTP3 443). Switching type updates a standard default port while retaining a custom port. Incompatible transport fields are removed when changing type. The HTTPS path, hostname resolver and TLS controls appear where applicable; display name/status and specialized settings are separate from the primary connection fields. DNS Advanced uses opt-in controls with no Add option dropdown. Configured TLS trust, client keys, resolver objects, headers and custom options are preserved.

**78 Node.js tests passed**, including visible/protected essential fields, invalid/empty/fractional/out-of-range ports, silent field edits, custom-port retention, protocol-specific defaults, advanced removal, preserved trust/authentication fields, all 15 DNS types, optional resolver clearing and maintaining the expanded Advanced section. **73 targeted Python tests passed** (`tests.test_native`, `tests.test_api`, `tests.test_auto_apply`), using the real bundled 1.14.3 core for auto-apply integration. Backend/core code and the bundled core are unchanged from 0.6.2; the complete Python suite and native Linux verification were not repeated for this UI change.

The actual page was reviewed through the browser at 1440×1000 and 390×844. Mobile DOM checks show no horizontal overflow in the dialog, a present port input, no Add option controls and no field-remove controls. [Desktop DNS form](screenshots/dns-resolver-0.6.3.jpg) shows only demonstration resolver data; it is not a production panel capture. Preview state was stored in a temporary private directory, and no host DNS, routes, firewall or production account was changed. Port defaults were checked against official UDP, TLS, QUIC and HTTPS DNS documentation.


## DNS provider templates and panel-entry checks (0.6.4) — 2026-10-17

The guided DNS form offers Google, Cloudflare, Quad9, AdGuard, OpenDNS and NextDNS templates with supported protocol choices. All generated presets use IP endpoints with encrypted TLS server names kept separately, so no bootstrap dependency is created. NextDNS requires a six-hex-character Profile ID and maps it to the HTTPS path or TLS/QUIC SNI. Custom retains all 15 resolver types. Changing providers fills their connection settings; protocol changes preserve custom ports and advanced TLS trust fields. JSON imports return to Custom mode to retain arbitrary configurations. Existing record tags are preserved; automatic tags update only while choosing providers for a new record.

The release-check worker and day interval were removed. Authenticated browser boot sends one CSRF-protected POST to `/api/check-updates`, which starts a bounded one-shot thread. A shared checker merges concurrent in-flight entries; a later entry checks again even within the same day. Login and dashboard access do not wait for GitHub. Dashboard polling reads persisted results only. Failed component checks retain their last successful version/timestamp and an error; no credentials, database contents or account data are sent. The Overview status remains, with its daily schedule text removed.

**85 Node.js tests passed**. Coverage includes provider/protocol constraints, all 23 generated combinations, NextDNS ID validation and silent edits, automatic/new versus existing tags, Custom round trips, preservation of trust fields, update status, and one check trigger per authenticated browser boot even when the trigger endpoint fails. API tests exercise login/CSRF protection, no checks on dashboard refresh, nonblocking in-flight reads, duplicate request coalescing and a fresh later check. Update unit tests verify no daily cache suppression, independent component failure and stable-release filtering.

All **23 generated provider/protocol server configurations passed `sing-box check`** with the bundled 1.14.3 core. This validates the configuration shape, not a public DNS exchange with every provider; automated transport tests continue to use local fixtures. No real NextDNS account/profile or production account was used.

The actual browser preview was reviewed at 1440×1000 and 390×844. NextDNS showed its profile input and the three expected encrypted protocols; the mobile dialog had no horizontal overflow. The Overview showed release status without the 24-hour line after entry. [DNS provider preview](screenshots/dns-presets-0.6.4.jpg) contains demonstration data only.

Provider source references: [Google secure transports](https://developers.google.com/speed/public-dns/docs/secure-transports), [Cloudflare encryption](https://developers.cloudflare.com/1.1.1.1/encryption/), [Quad9 services](https://docs.quad9.net/services/), [AdGuard public providers](https://adguard-dns.io/kb/general/dns-providers/), [Cisco OpenDNS encrypted endpoint](https://blogs.cisco.com/security/cisco-interop-discovery-of-designated-resolvers-protocol-implemented), [NextDNS endpoints](https://my.nextdns.io/start) and [NextDNS bootstrap IP](https://github.com/nextdns/nextdns/wiki/Configuration). These are a curated set of documented presets; Custom also supports additional transports and resolver variants.

Full local verification: **211 Python tests passed**, with the bundled 1.14.3 core and existing real-Caddy fixtures; no skips. **85 Node.js tests passed** after the final tag-preservation and JSON-import regressions. No production server was accessed or modified.


## Simplified DNS resolver window (0.6.5) — 2026-10-17

Resolver type now lives inside the DNS provider box, using the same schema-driven control and provider-specific choices. Its events are forwarded to the original editor, so defaults, custom ports and protocol-specific fields keep their existing behavior. Display name and enabled status are directly in the main form. The DNS resolver form omits Advanced/TLS Advanced and JSON view rather than hiding existing configuration values in editable JSON. Stored specialized settings remain in the model and are preserved when saving visible fields. Other native editors keep their existing JSON controls.

The provider box displays a live resolver URL/endpoint and the actual connection address. Core Server remains a plain IP/hostname; HTTPS Path and TLS server name stay separate as required by the 1.14.3 format. Full URLs entered into Server get an actionable validation error. Endpoint display follows protocol, TLS name, port and path, supports IPv6 brackets, and does not fetch or execute URLs.

**87 Node.js tests passed**, covering the relocated protocol control, absence of Advanced/JSON in the actual form, visible display-name metadata, endpoint updates, protocol switches, invalid full-URL input, custom ports, existing account tags, NextDNS IDs and retained TLS trust/headers/client keys. The 15-type round-trip test runs in the simplified mode, preserving specialized fields even when those fields are not rendered. Existing schema-editor tests cover the generic mode used elsewhere.

The actual browser page was reviewed at 1440×1000 and 390×844. DOM checks confirm Resolver type inside the provider box, Display name outside collapsed details, zero DNS Advanced sections, no JSON viewer and no horizontal overflow at the mobile width. [Simplified DNS window](screenshots/dns-simple-0.6.5.jpg) shows demonstration resolver data only. Backend/core configuration generation and bundled Sing-box 1.14.3 are unchanged.

The Server/Port/Path distinction was verified against [official HTTPS DNS fields](https://sing-box.sagernet.org/configuration/dns/server/https/).

Targeted backend validation: **75 Python tests passed** (`tests.test_native`, `tests.test_api`, `tests.test_auto_apply`) with the real bundled 1.14.3 core for auto-apply integration. The full Python suite and Linux CI were not repeated for this UI-only change. No production server was accessed or modified.


## DNS layout, certificate table and one-click updates (0.6.6) — 2026-10-17

DNS Display name and Tag share a desktop row and stack on mobile. The enable checkbox is removed only from the resolver form; new resolvers are active and editing an existing disabled resolver preserves its state. Preset encrypted DNS shows an automatic TLS summary; Custom keeps server name and verification controls, with existing trust material retained in the model. TLS certificate rows include validity, expiry, client verification, assignment count and the existing download/edit/delete actions. The footer places the version beside NARA and its tagline.

**219 Python tests passed**, with the real bundled 1.14.3 core and both existing real-Caddy fixtures, with no skips. **91 Node.js tests passed**. New coverage checks adjacent identity nodes and retained values across redraws, absence of the resolver enable control, disabled-state preservation, automatic TLS, escaped certificate table content/actions, footer content and conditional managed-install update buttons. Browser checks at 1440×1100 and 390×844 confirmed same-row identity on desktop and no horizontal overflow in the mobile DNS form. [DNS layout](screenshots/dns-layout-0.6.6.jpg) and [certificate table](screenshots/tls-table-0.6.6.jpg) show demonstration metadata only.

The authenticated CSRF-protected update endpoint queues only a version number to the existing root maintenance broker. Tests reject commands/URLs/downgrades, extra job fields, archive traversal/symlinks, invalid checksums and dependency changes before execution. They cover private backup creation, fixed installer arguments, manager-lock inheritance, owner-only log permissions, completion/failure reporting and timeout termination allowing the installer's rollback trap. The full suite also exercises the existing updater's readiness-failure rollback in a temporary fake-system fixture. No SSH credentials are collected or stored. No production server was accessed or upgraded; privileged update execution is simulated in these tests.

Panel entry checks now use the latest published stable GitHub release rather than main-branch release.json, matching the update broker's release-only downloads. Pending source changes are not advertised as installable releases.

Native Linux verification [run 39064677799](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39064677799) passed at implementation commit d56b8e7: **48 tests on amd64 and 48 on arm64**, using downloaded compatible 1.14.3 binaries in Go-free/Git-free Python containers. The run includes updater broker fixtures and real proxy/accounting traffic. A separate Ubuntu job passed `systemd-analyze verify` for the panel and maintenance service/path units; it validates unit configuration, and does not perform a live systemd upgrade. The later release-check endpoint/UI-status refinements were checked locally.

Final release-check refinement: **55 targeted Python tests passed** (`tests.test_updates` and `tests.test_api`, including path-prefixed authentication/CSRF checks). **91 Node.js tests passed** again after the manual-install update-status fix; **18 updater/access tests passed** after the maintenance message adjustment.


## Family Safe providers and DNS defaults (0.6.7) — 2026-10-17

Added AdGuard Family Protection, Cloudflare Families, CleanBrowsing Family Filter and OpenDNS FamilyShield presets, with only their supported transports offered. CleanBrowsing has separate HTTPS/TLS hostnames and its `/doh/family-filter/` path; FamilyShield HTTPS uses its dedicated `146.112.41.3` endpoint. Sources are linked in README. The FamilyShield IP was read from a live public DNS lookup for `doh.familyshield.opendns.com`; live HTTPS queries against all four family IPs completed with certificate verification enabled and matching DNS response IDs. These probes validate encrypted endpoints and responses; they do not establish filtering completeness or test every transport.

The provider dropdown is alphabetical with Custom / Manual last. Only empty/new resolver forms default to Cloudflare HTTPS. Display name is initialized from the detected provider; provider changes replace empty or previous automatic names, while custom labels stay unchanged. Existing resolver endpoints and Default DNS settings are preserved.

**94 Node.js tests passed**: all **39 provider/protocol combinations** round-trip through detection, and regressions cover family endpoint details, provider order, Cloudflare defaults, name updates, user-defined names, protocol redraws, Custom mode and existing configurations. The bundled **Sing-box 1.14.3 accepted a configuration containing all 39 presets** with unique tags and an explicit route domain resolver. The DNS form was inspected at 1440×1100 and 390×844 with no mobile horizontal overflow. [Default Cloudflare form](screenshots/dns-providers-0.6.7.jpg) and [family resolver form](screenshots/dns-family-0.6.7.jpg) contain only demonstration data.

Backend behavior and updater implementation are unchanged. The full Python suite and Linux CI from 0.6.6 were not repeated for this DNS UI/preset change. No production server was accessed or modified.


## Owner-safe update backup repair (0.6.8) — 2026-10-18

A real server reported PAM identity-change failures followed by `runuser: cannot set user id: Operation not permitted` during the pre-installation backup. Snapshot creation now uses the existing forked database-owner worker rather than executing runuser and reloading the interpreter. The child clears supplementary groups, sets the database GID/UID, opens the live database read-only and writes a private temporary snapshot in the owner's directory. The parent archives its consistent SQLite backup. The worker is bounded to 120 seconds and reaped on timeout. Symlinks, missing source files and mismatched database ownership are rejected. Existing systemd protections remain in place.

Private update logging begins before backup creation. If backup fails, the installer is never invoked; diagnostics stay in the owner-only server log and the panel receives an actionable summary. Unit regressions cover identity dispatch without runuser, read-only copying, rejected source paths, timeout cleanup and backup-failure logging with no installer execution.

A new disposable GitHub Actions fixture exercises the actual panel API, path-triggered root systemd service and update.sh with a live service-owned WAL database. Only release-network responses use a locally prepared future-version fixture. runuser is deliberately blocked to reproduce the failed dependency; no protection is disabled. The fixture checks preserved accounts, core binary, private backup/WAL contents, reported new version and subsequent writes by the database owner. It uses a stub core and no production data; separate native-core jobs continue checking real proxy traffic.

The service regression reproduced an effective/permitted capability set missing `CAP_SETUID`, even though it remained in the bounding set. The root maintenance unit now explicitly retains `CAP_SETUID` and `CAP_SETGID` through `AmbientCapabilities`, as described in [systemd's capability settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#AmbientCapabilities=). NoNewPrivileges and filesystem/kernel protections stay enabled. The regression also requires the database child to have the owner's UID/GID and zero permitted/effective/ambient capabilities after switching identity.

Final verification: **222 Python tests passed**, including the bundled real 1.14.3 core and both existing Caddy fixtures, with no skips. **94 Node.js tests passed**. After adding operation-specific owner errors, **43 targeted maintenance/updater/access tests passed** again.

[Final Linux run 39066996144](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39066996144), at implementation commit 5244b0a, passed all jobs: **49 tests on amd64 and 49 on arm64** in Go-free/Git-free containers; service-unit validation; and the real path-triggered systemd upgrade fixture. The fixture confirmed a consistent private snapshot of committed WAL data, an authenticated update job, actual updater execution and panel restart, the new reported version, preserved account/core binary, subsequent writes by the database owner, NoNewPrivileges still set and zero remaining database-child capabilities. Earlier service runs reproduced the missing effective CAP_SETUID and failed before installation; the final run passed after explicit identity-capability retention. No production server was accessed or upgraded.

## Guided DNS policies and WARP destinations (0.7.0) — 2026-10-18

**238 Python tests passed without skips** with Python 3.12.14, the bundled real Sing-box 1.14.3 and both Caddy fixtures. **108 Node.js tests passed**. Dependencies are byte-identical to 0.6.8, preserving the panel-only update path.

DNS verification covers readable ordered matches/actions, guided resolver/block/predefined/query-options rules, empty-list protection, query type and source scope, regular-expression commas, advanced logical/response-rule preservation, inactive references, toggles, revision-checked movement, default fallback and the navigation resolver count. Real UDP DNS queries verify resolver selection, NXDOMAIN/custom records, query options, fallback and changed results after reordering a catch-all. The existing resolver form now exposes Detour directly and retains all previous provider/TLS behavior.

WARP tests cover fixed-host HTTPS registration with the public key only, blocked redirects, bounded responses, rate limits and sanitized failures, consent/authentication/CSRF/revision/capability checks, private-key and pre-shared-key redaction, API response conversion including reserved bytes and IPv6, strict port/key validation, concurrent creations/edits, retained registration after failed apply, and recovery after interrupted pending-state cleanup. A real-core API test generates actual WireGuard keys, mocks registration, redirects the test peer to loopback, applies the endpoint and references it from both traffic routing and DNS detours; deletion of a referenced endpoint is rejected without disturbing active settings.

A separate real WireGuard peer on loopback transfers HTTP through a selected endpoint using nonzero reserved bytes. The peer rewrites a documentation-only destination IP to a local HTTP fixture; no host routes, firewall, system DNS or system tunnel are changed. After that peer is stopped, matching traffic fails while unmatched direct traffic still succeeds. This verifies selective user-space tunneling rather than merely accepting JSON.

[Linux run 39069344649](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39069344649), at implementation commit `223bab9a0fbcb53c56cdd45ac35ef38f53578f0a`, passed all jobs: **64 tests on amd64 and 64 on arm64** in Go-free/Git-free containers, service-unit validation and the real path-triggered systemd upgrade fixture. The previous preliminary run was superseded after stricter response-port validation was added.

An isolated browser account was inspected at desktop size and 390×844. Saving a DNS block rule started the actual local core automatically. Mobile viewport and document widths were both 390 px. The WARP dialog and consent link were inspected without accepting terms or submitting registration. [DNS rules](screenshots/dns-rules-0.7.0.jpg), [mobile view](screenshots/dns-rules-mobile-0.7.0.jpg) and [WARP dialog](screenshots/warp-create-0.7.0.jpg) contain demonstration data. The preview server and browser tab were closed afterward.

**No public Cloudflare account was registered and live Cloudflare WARP egress was not tested.** External registration is mocked; its consumer API is undocumented and may reject or rate-limit a server. A successful creation represents registration plus validated configuration apply, not an external connectivity measurement. This limit and the native endpoint import alternative are documented. No production server was accessed or upgraded.


## Administrator, notifications, API and bulk accounts (0.8.0) — 2026-10-18

**270 Python tests passed without skips** using Python 3.12, the bundled real Sing-box 1.14.3 and both existing real-Caddy fixtures. **119 Node.js tests passed**. Python dependencies are unchanged from 0.7.0, keeping the managed panel-only upgrade path available.

New verification covers RFC 6238 known vectors, TOTP replay/window checks, session-bound setup, verified activation and login challenges, hashed single-use recovery codes, session revocation, server-local recovery and retained profile metadata. Avatar tests reject malformed PNGs, bad CRCs, unsupported formats and oversize dimensions. API keys are checked for hash-only storage, expiry, revocation, scope separation and hidden secrets. REST tests exercise Bearer-only authentication, revision conflicts, native CRUD, reference validation, pagination/filtering, private subscription permissions, rate limits and origin rejection.

Bulk tests check mixed-case default naming, constrained pattern parsing, duplicate prevention, private actor/revision-bound previews, independent credentials, group validation, quota floors, unlimited/no-expiry semantics and strict selections. Real-core apply tests create multiple accounts together, reset multiple usage counters in one commit, reject an invalid batch without altering state/counters and reject an API configuration that fails actual core validation. Existing protocol traffic/accounting tests continue to pass.

Telegram tests use mocked HTTPS responses, not a real bot: delivery defaults disabled with all 19 event categories selected; administrator reauthentication; token redaction; destination changes cancel queued events; quota/expiry and daily deduplication; sustained resource alerts/recovery; core transitions; bounded fixed-host transport; sanitized errors, rate limits and retries; chat discovery returns IDs/names without message text. **Live Telegram delivery was not tested and no message was sent to a real destination.** It requires user-provided bot credentials. The in-process worker cannot report a whole-host outage while offline.

An isolated preview with 18 demonstration accounts and the actual local core was inspected at 1280×720 and 390×844. Checks confirmed random ten-letter names, exact bulk previews, disabled save after editing a preview, selection retained across pages, group management, default read-only API permission, all 19 Telegram events selected with delivery disabled, account controls, About and mobile layout. Document and viewport widths were both 390 px. [Administrator](screenshots/account-0.8.0.jpg), [bulk preview](screenshots/clients-bulk-0.8.0.jpg) and [mobile profile](screenshots/account-mobile-0.8.0.jpg) contain demonstration account data. Sensitive credential/2FA changes were verified through isolated backend tests; browser forms were inspected without submitting credentials. No production server was accessed or modified.


[Native Linux run 39072562798](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39072562798), at implementation commit `7ad6f7ba78a9f8cae9b752b75557ff017f7c956d`, passed all jobs: **96 tests on amd64 and 96 on arm64** in Go-free/Git-free Python containers, service-unit validation and the real path-triggered systemd update fixture with a live service-owned WAL database. The archive uses the existing verified updater extraction path; every bundled file was compared with its workspace source, with no private database or cache included.

The disposable core was stopped and restarted explicitly: DOM/computed-style checks showed `status-dot off`, red RGB(240,107,112), and `status-dot on`, green RGB(73,207,137), both with the core-status pulse animation. The preview service/core, temporary private state and agent-created browser tab were closed/removed after review; the viewport override was reset.


## Cross-panel workflow, security and resource review (0.8.1) — 2026-10-18

**280 full-suite Python tests passed without skips** with Python 3.12, the real compatible Sing-box 1.14.3 and both Caddy fixtures. After the legacy token-length compatibility check and fail-closed worker guard were finalized, the **12 dedicated audit regressions passed again**. **127 Node.js tests passed** after the final UI changes. Runtime requirements are byte-identical to 0.8.0; no application dependency or frontend framework was added.

Audit regressions verify explicit administrator verification for Telegram discovery/checking, typed/saved-token support, public-only bot identity, no save/send side effects during connection testing, strict framing/non-finite JSON rejection, URL-safe maintenance IDs, legacy 128-character subscription tokens, exclusive atomic-file publication without following a planted predictable symlink, minute-bounded API metadata writes, eligibility-only idle checks, failed-limit-check shutdown, idle notification waits/wakeups, HTTPS redirect downgrade rejection and bounded/time-limited public connections. Existing full-suite real traffic/accounting tests include expiry/quota enforcement, DNS/routing selection, WireGuard destinations and apply rollback.

Node regressions cover the separate password/2FA dialogs and missing-token feedback, preservation of unsaved preferences, escaped chat/bot names, token test without activation, combined installed/latest/checking/error version display, lighter status refresh, original Settings form revisions, native TLS and accurate inbound states. All prior protocol, DNS, routing, QR and bulk/account UI tests continue passing.

Dependency review: npm audit reported zero advisories; pip-audit reported zero after updating development/bootstrap pip to 26.2.1 (grpcio 1.84.0, typing_extensions 4.16.0 and development PyYAML 6.0.3 were also checked). Bandit's final scan reported no high-severity findings; the four medium flags are intentional all-interface listener/port checks. Other subprocess/test-fixture flags were manually reviewed. Fresh/full installers and Docker builds update pip installation tooling; panel-only updates preserve their existing Python environment. [SECURITY_REVIEW.md](SECURITY_REVIEW.md) records scope, findings and retained trust boundaries. No independent penetration test or upstream binary-source security audit is claimed.

An isolated preview used 18 demonstration accounts and the real local core, with its displayed hostname/addresses anonymized. All main pages were inspected at 1280×720 and 390×844; tables may scroll inside their containers, while page width remained within the viewport. Telegram verification forms were inspected and cancelled; no real token or external message was submitted. [Merged Overview](screenshots/overview-0.8.1.jpg) and [Telegram connection controls](screenshots/notifications-0.8.1.jpg) show the new layouts. External bot transport is mocked in tests, so a real configured bot remains necessary to verify actual delivery. No production server was accessed or upgraded.


Final cleanup: Ruff F rules passed for `nara/` and `scripts/` after removal of six unused imports. **29 targeted Python tests** (credentials, audit regressions and release checks) passed after that cleanup. The mobile notification view was saved in [notifications-mobile-0.8.1.jpg](screenshots/notifications-mobile-0.8.1.jpg); all twelve main pages were inspected at the mobile width. The temporary browser was closed and its viewport restored.
