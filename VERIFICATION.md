# Verification — 2026-10-16

Verified locally on macOS, using Python 3.9.6 and a native build of Sing-box 1.14.3 with `with_quic,with_v2ray_api`. Production installation targets Python 3.10+ on Linux.

**49 automated tests passed** in the complete suite, including the original protocol/accounting tests and additional installation/custom-webPath tests. Coverage includes random mixed-case eight-letter defaults, default port 10000, custom values, re-prompting invalid/reserved/occupied ports, preserving existing entry defaults, path injection rejection, case-sensitive prefix routing, prefixed UI/assets/API/subscriptions, root-route isolation, path-scoped login/logout cookies, and all earlier authentication, configuration, TLS, expiry, quota, persistence, and rollback checks.

Real core integration passed for **VLESS, VMess, Trojan, Hysteria2, TUIC, and AnyTLS**, transferring HTTP payloads through a loopback client and server and checking per-user upload/download counters. Restart persistence without double counting, DNS hostname bootstrap through the client system resolver, expiry enforcement, periodic quota enforcement, and rollback after a port bind failure also passed. No host routes, firewall, or system DNS were changed.

Browser checks verified English/LTR sign-in, one-click self-signed generation, inbound creation, client creation with an assigned inbound and 10 GiB allowance, settings save, and applying the configuration to a real local core. Desktop (1440 px) and mobile (390 px) layouts were inspected; the mobile page had a 390 px viewport and 390 px document width. Screenshots show an isolated local test account. Linux-only measurements remain unavailable in this macOS preview.

JavaScript syntax, Python compilation, and shell script syntax checks passed. No Persian UI/error strings remain in the application source; Persian documentation is separate.

The one-line installer supports Debian 12+/Ubuntu 22.04+ on amd64/arm64, retrieves a verified isolated Go toolchain, builds the feature-enabled core, and configures a systemd service. Shell syntax was checked. Official Go 1.27.2 Linux archive SHA-256 values were checked against the official download manifest.

The actual interactive configuration helper was also run in a controlling terminal with two empty answers: it produced a mixed-case eight-letter webPath, port 10000, and a mode-0600 environment file in an isolated temporary directory.

**Not verified:** executing the full bootstrap as root on Linux, actual Linux installation/systemd behavior, Docker image build/runtime, and real Linux `/proc` measurements. Docker was unavailable on the development host. No remote server credentials or address were supplied. The deployment files are prepared, but no remote deployment is claimed.
