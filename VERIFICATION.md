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
