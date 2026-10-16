# NARA Panel

An independent English web panel for running **Sing-box on your own Linux server**. Inspired by the NARA OpenWrt project's orange skin, local configuration generation, and validation-before-activation workflow. This is a separate server application; it does not modify the OpenWrt project.

![NARA Panel desktop overview](screenshots/overview-0.3.png)

## Included

- **Overview:** Linux CPU, RAM, disk, load, uptime, hostname, sampled network traffic, client traffic totals, core status, and recent events. Unavailable measurements are shown as unavailable.
- **Inbounds:** all 19 Sing-box 1.14.3 types, including Shadowsocks, ShadowTLS, Hysteria, Snell 5/6, Naive, HTTP/SOCKS, TUN, transparent listeners and Cloudflared. Complete versioned forms include nested protocol/TLS/transport/listen options. Existing VLESS, VMess, Trojan, Hysteria2, TUIC and AnyTLS account management remains available. Standalone listeners manage their own credentials. See the [feature review](FEATURE_REVIEW.md).
- **TLS:** import PEM certificate/key pairs, validate their match and SAN hostname, generate ECDSA self-signed certificates with one action, show expiry, and download the public certificate. Each profile has explicit client **Allow insecure**, SNI suppression, ALPN, TLS versions and handshake timeout.
- **DNS:** all 15 typed resolvers, complete logical/default rules and actions, races/speculation, predefined replies, optimistic/cache controls and local/remote/inline rule sets.
- **Routing:** ordered rules, logical groups, all match/action fields, 20 outbound types, interface/domain defaults and shared rule sets.
- **Core features:** five endpoint types, ten service types, certificate providers, HTTP clients, namespaces, logging, NTP, certificate trust and experimental cache/Clash API settings.
- **Updates:** daily, persisted, read-only checks for panel and stable upstream core releases, shown above a compact version strip in Overview.
- **Clients:** multiple inbound assignments, generated UUID/password, enabled state, expiry, traffic allowance, durable upload/download totals, reset usage, rotate subscription links, JSON configuration download, private Sing-box JSON subscription URLs with usage headers, and locally generated QR codes in official Sing-box remote-profile and direct JSON URL formats, with PNG download.
- **Operations:** SQLite persistence, admin sign-in, password change, logout, server-side sessions, CSRF checks, sign-in throttling, automatic validation/application on save, managed restarts, attempted rollback after startup failure, and systemd installation. Saved and active settings are committed together; invalid changes preserve the previous settings.

The interface defaults to **English and left-to-right**, with a 16 px body/input baseline and larger readable labels and captions. [راهنمای نصب فارسی](INSTALL.fa.md).

## Requirements

- Linux with systemd for direct installation; Python 3.10+, Python venv, OpenSSL 1.1.1+, and CA certificates.
- Sing-box **1.14.3**, built with the **upstream standard capabilities plus `with_v2ray_api`**. Default official release builds do not include V2Ray API. The supplied build script pins the official source commit and uses its Go module checksums. Building requires Go 1.27.1 or a compatible newer toolchain, Git, and Internet access.
- Public server address and open inbound TCP/UDP ports. Panel and subscription URLs support HTTP and HTTPS. The server manager can set up a dedicated HTTPS reverse proxy, or you can use an existing one.

The panel owns its Sing-box child process and configuration. Give it separate ports from any existing installation. The installer leaves host firewall, routes, DNS and other Sing-box services untouched. Native TUN/transparent/network-namespace features can change networking when you explicitly configure them and provide the required capabilities; see [host requirements](FEATURE_REVIEW.md#builds-and-host-requirements).

## One-line Linux installation

From an interactive SSH session on **Debian 12+ or Ubuntu 22.04+**, on **amd64 or arm64**, run as root:

```sh
curl -fsSL https://raw.githubusercontent.com/kevinzakarian/Nara-Panel/main/install.sh | bash
```

For an account with sudo access, replace the last `bash` with `sudo bash`.

The launcher **first refreshes apt package lists and upgrades installed system packages**, keeping existing package configuration files when a decision is required. This can restart system services. It does not run a distribution release upgrade, remove packages automatically or reboot the server; a pending-reboot notice appears in the menu. It then opens the English **NARA server manager**. Package-update errors stop preparation with an error rather than being reported as success.

Choose **1 — New installation** for a new server or to reinstall previously retained data. For an existing installation, choose **2 — Upgrade panel only** (keep the core) or **3 — Upgrade panel + rebuild bundled compatible core**. Option 3 builds the pinned core supported by this panel, rather than replacing it with an untested release. The verified, isolated Go toolchain is downloaded only when a build is needed. Building can take several minutes; the existing service continues running during the build.

Every question has a bold cyan **[INPUT]** marker, with the default in brackets. Password prompts explain that typing is hidden. `NO_COLOR` or a plain terminal disables ANSI colors while preserving the markers. A new installation asks for:

1. **webPath** — enter a single path segment such as `MyPanel`. Press **Enter** for a cryptographically random **8-letter path containing both uppercase and lowercase letters**, e.g. `/aBcDefGh/`.
2. **Panel port** — press **Enter** for **10000**, or enter another available port. Invalid, reserved, and occupied ports are rejected.
3. **Administrator password** — choose and confirm at least 12 characters. The username is `admin`.

The panel is then reachable at `http://YOUR_SERVER_IP:PORT/webPath/`. The final URL is printed after a readiness check; allow the selected TCP port in your firewall. No administrator password is bundled. The installer does not change firewall rules.

Entry settings are stored with mode 0600 in `/etc/nara-panel.env`. Menu upgrades preserve the existing path/port, administrator, accounts, HTTPS and data without asking for replacement entry values. Failed full upgrades attempt to restore the previous application, virtual environment, core, service and entry settings; a private data backup is created before menu upgrades. A customized path scopes the UI, assets, API, subscription links, and session cookies; it supplements administrator authentication.

For public HTTPS, use **4 — Panel HTTPS / Certificate** in the manager (see below), or configure your own reverse proxy using `deploy/Caddyfile.example`, **preserve the full webPath**, set `NARA_BIND=127.0.0.1` and `NARA_SECURE_COOKIE=1` in `/etc/nara-panel.env`, and restart the service. An existing proxy must forward the chosen internal panel port. The optional Public panel URL setting accepts HTTP or HTTPS, including the webPath; an origin-only value uses the current webPath. If the field is blank, subscription links and QR codes use the current browser address, port and path.

For a manual source installation on other systemd Linux distributions, install Python/venv, Git, a compatible Go toolchain, OpenSSL and CA certificates first, then run:

```sh
sudo sh scripts/install.sh
```

The local installer asks the same entry questions and builds a missing core. You may supply an already compatible binary with `sudo NARA_INSTALL_CORE=/path/to/sing-box sh scripts/install.sh`.

## Installed server manager

After installing or upgrading to 0.3.1, run:

```sh
sudo nara
```

It performs the same initial system-package update, then offers:

| Option | Action |
| --- | --- |
| 1 | New installation / reinstall retained data |
| 2 | Upgrade panel only, preserving the installed core |
| 3 | Upgrade panel and rebuild the bundled compatible core |
| 4 | Panel HTTPS: automatic domain certificate, self-signed domain/IP certificate, PEM import, certificate status |
| 5 | Service status, versions and entry URL |
| 6 / 7 / 8 | Restart / stop / start panel service; stopping also stops its core |
| 9 | Recent panel and dedicated HTTPS service logs |
| 10 | Create a private account/settings/certificate backup |
| 11 | Change administrator password and invalidate admin sessions |
| 12 | Uninstall application while keeping data, or delete its data/settings/certificates |
| 0 | Exit |

Start/restart follows the core’s saved start/stop state. Reinstalling retained data also recreates the dedicated HTTPS service; if its saved certificate cannot be verified, the manager reports that it needs repair through option 4.

Uninstall requires typing an exact confirmation. Both removal modes retain pre-existing backup archives, system packages and service users. They do not remove other Sing-box installations or another web server's configuration. Backups are mode 0600 in `/var/backups/nara-panel` (directory 0700), contain credentials/private keys, and are never uploaded. SQLite's online backup includes committed WAL data; runtime generations and logs are regenerated instead of archived. To restore a NARA-created data backup manually, stop `nara-panel` and `nara-panel-https`, restore the archive's `etc/` and `var/` contents to their original paths with ownership preserved, then reinstall/upgrade through the menu and start the services. App binaries and Python packages are reinstalled, not stored in the data archive.

### Panel HTTPS certificates

The manager uses Caddy from the distribution's apt repositories and its own `nara-panel-https.service`, `/etc/nara-panel/https/` and `/var/lib/nara-panel-https/`. It does not overwrite `/etc/caddy/Caddyfile` or an existing Caddy/Nginx/Apache service. TCP **80 and 443 must be free**; the internal panel port must differ from both. If those ports are already in use, use your existing reverse proxy. UDP 443 remains available for QUIC proxy inbounds. Firewall rules are not changed automatically.

- **Automatic domain certificate:** first point every A/AAAA record to this server and allow inbound TCP 80/443. Caddy obtains a trusted certificate and renews it automatically while the dedicated service runs. The domain is shared with public certificate authorities/transparency logs, as expected for public certificates. See [Caddy's requirements and renewal behavior](https://caddyserver.com/docs/automatic-https).
- **Self-signed domain/IP:** creates an ECDSA certificate with the correct SAN, valid for one year. Devices must explicitly trust its public certificate. The manager does not disable verification or install a local CA into the server trust store. Regenerate before expiry.
- **Import PEM:** reads local absolute paths to a full-chain certificate and matching unencrypted private key, validates hostname/IP, key pairing and expiry, then copies them into the protected HTTPS generation. Re-import after renewal; external source files are not watched.

The proxy preserves the complete webPath and subscription routes. Setup binds the internal panel to `127.0.0.1`, enables Secure cookies and verifies a real HTTPS health request with SNI/hostname validation. Only after verification does it update the Public panel URL. Failure restores the previous entry settings and managed proxy. Panel HTTPS is independent of the certificates attached to Sing-box inbounds.

## Docker alternative

```sh
docker compose build
docker compose run --rm nara python -m nara init
docker compose up -d
```

The container runs unprivileged with a persistent named volume. Set `NARA_WEB_PATH=/YourChosenPath` in its environment if you want a prefix; container setup does not run the interactive Linux installer. Use inbound ports **1024 or above inside the container**. Update Compose port mappings for every inbound. For example, container port 8443 can be published as host port 443; set the inbound's **Public port** to 443 so exports use the correct endpoint. The example publishes TCP 8443 and UDP 8444 on the same numbered host ports; add other mappings as needed. HTTPS reverse proxy setup is separate; `NARA_SECURE_COOKIE=1` expects HTTPS. For initial HTTP tunnel access only, temporarily override it to `0`.

## Updating an installed panel

For application updates with unchanged Python dependencies, run as root:

```sh
curl -fsSL https://raw.githubusercontent.com/kevinzakarian/Nara-Panel/main/update.sh | bash
```

This updates the application and web interface using the installed Sing-box core, preserving the panel port/webPath, administrator, accounts, and saved configuration. It restarts the panel and core, verifies readiness, and attempts to restore the previous application code if startup fails. If dependencies have changed, it stops before applying code and asks you to use the full installer. Docker installations should rebuild the image instead.

Version **0.3.0** adds the complete 1.14.3 configuration workspace, routing, full DNS forms and daily release checks. Existing data is migrated without removing accounts or settings. The app-only updater keeps your current core binary. **For all new build-dependent features, open the one-line manager above and choose option 3**, which rebuilds the complete compatible core and preserves your accounts and entry settings. Docker users should rebuild.

Version **0.3.1** adds the interactive server manager, highlighted terminal input, system-package preparation, protected backups/removal and panel HTTPS setup. The short app-only `update.sh` command remains available; it does not perform the system-package upgrade or open the menu.

The panel only reports available updates; it never installs a newer core automatically. Forms target 1.14.3. Review compatibility before independently moving the core to another version.

## Complete core configuration

In **Inbounds**, use **New inbound** for the existing panel-managed protocols. Choosing another type opens its standalone editor; **Standalone inbound** exposes every type directly. Standalone listeners do not use panel client quotas, expiry, traffic totals or subscriptions. Their users/keys are configured in the listener itself.

Use **Add option** within any object to add a field, including nested TLS/QUIC settings, arrays and maps. Version/action selectors switch the appropriate schema. The JSON view can load and review an entire record. Private keys are hidden in general state responses and retained when omitted during editing. Save checks references, rejects outbound cycles, validates with the core and applies automatically.

**DNS** contains all resolver types, DNS rules, shared rule sets and global DNS settings. **Routing** contains rules, outbounds and routing defaults. **Core features** contains endpoints, services, certificate providers, HTTP clients, namespaces and the remaining root settings. See the [coverage and requirements table](FEATURE_REVIEW.md) for details.

The daily update check runs independently of the browser and core, uses fixed public GitHub endpoints, and persists its cache across restarts. Failed checks show “Update check unavailable”; they do not mean the installed version is current.


## First connection

1. In **Settings**, set the public server domain/IP. Public panel URL is optional and accepts HTTP or HTTPS.
2. In **TLS certificates**, import a trusted certificate or click **Generate self-signed**.
3. In **Inbounds**, create an inbound with a unique port and attach the certificate.
4. In **Clients**, create a client, assign inbounds, and choose allowance/expiry.
5. Every **Save** automatically validates and activates the configuration using the installed core. There is no separate Apply step. Failed validation preserves the working core and previous settings; a startup failure triggers a rollback attempt. Connection changes can briefly disconnect clients.
6. In **Clients**, click **Subscription QR code** to scan or download the subscription QR as a PNG. The QR is also shown in account details alongside **Copy link** and **Download config**. When the public panel URL is blank, the current panel address, port and webPath are used automatically. Client JSON includes an IPv4/IPv6 TUN for VPN mode in the official Sing-box apps, a loopback mixed proxy on port 2080, and a selector of assigned outbounds. The app manages the VPN interface and requests any required operating-system permission.

**After updating from 0.2.2 or earlier, refresh the remote profile in the Sing-box app before reconnecting.** Previously downloaded/local JSON files must be downloaded and imported again. Changing the panel does not update an already imported local file.

Client DNS uses Cloudflare DoH through the selected proxy; a direct 1.1.1.1 UDP resolver bootstraps proxy-server hostnames only. The panel DNS editor configures server-side DNS. Ordinary client traffic stays on the selected proxy. Client logs use info level to expose startup and connection errors. Generated VPN profiles require a Sing-box graphical app or a core with TUN support and the necessary system privileges; command-line proxy-only use must remove the TUN inbound.

By default, self-signed client exports include the public certificate as a trusted certificate. Selecting **Allow insecure (client)** explicitly disables certificate verification in that profile’s client exports; it is disabled by default and never added to the server TLS configuration. Public panel HTTPS and inbound TLS are configured independently.

QR codes contain the private subscription URL, including the account token and webPath. If you access the panel through a local tunnel, set the optional Public panel URL to an address reachable by your clients. Encoding and PNG export happen locally in the browser with a bundled encoder; no external QR service is contacted. **Sing-box app (recommended)** is the default and encodes the [official remote-profile import URI](https://sing-box.sagernet.org/clients/general/#remote), including the account name. Choose **JSON subscription URL** for clients that accept a direct full Sing-box JSON URL, or for manually adding a remote profile. Copy link and Download QR follow the selected format. This does not provide Clash YAML or protocol-link/Base64 subscriptions. Rotating the subscription link produces a new QR code when reopened.

![Subscription QR preview with a demonstration account](screenshots/subscription-qr-formats.png)

## Accounting and operational limits

- Usage is the sum of per-user uplink and downlink payload counters from the core. It is not NIC bandwidth or a billing-grade wire-byte counter. Host network graphs include unrelated host traffic.
- Usage and expiry are checked every **5 seconds**. Crossing a limit rebuilds the running configuration and restarts the whole core, disconnecting all active connections. Enforcement can overshoot within the polling/restart window. Sudden crashes/power loss can lose the most recent uncollected interval; graceful restarts collect first.
- Form edits take effect when **Save** succeeds. Account enable/disable, deletion, quota/expiry edits, usage resets, TLS changes and DNS changes apply automatically. Equivalent server configurations, client-only settings and token rotations avoid unnecessary core restarts. A successful usage reset reactivates an otherwise eligible exhausted account. Rotating a subscription URL does not invalidate already downloaded credentials.
- After **three consecutive failed accounting polls**, the panel stops the core. An unexpected exit is reported and requires **Start core** or a successful settings save; no automatic crash loop is started inside the panel. A normal panel restart restores the last applied configuration if the core had not been explicitly stopped.
- Panel-managed accounts have no live connected-user count, online indicator, per-device/IP/concurrency limit, per-client speed cap or periodic quota renewal. Standalone protocol settings can have additional upstream controls, but they are not panel account limits. Account status means eligible, not currently connected. Protocol-link/Base64 subscriptions remain outside this release.
- Imported certificate profiles are stored and used locally. Renew them by editing their TLS profile, or configure an upstream certificate provider through the full core editor when appropriate. Rule-set downloads are performed by the core; failed core validation/download does not replace the active generation.
- There is one administrator identity. Private keys, client credentials, subscription tokens, and the database must stay private. Core diagnostics live in the private data directory as `core.log`; the UI does not display raw core errors that might contain credentials.
- For a consistent manual backup, stop the panel service and back up the entire `/var/lib/nara-panel` directory including the SQLite database. Restore only to a trusted host with the service stopped. Automatic encrypted backups and multi-server management are outside this release.

## Development and verification

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m nara init
.venv/bin/python -m nara serve --binary "$PWD/dist/sing-box"
```

Open http://127.0.0.1:10000. To test a custom prefix, add `--web-path /AbCdEfGh` and visit http://127.0.0.1:10000/AbCdEfGh/. Linux `/proc` metrics remain unavailable on macOS; the panel does not fill them with demonstration values. Local previews use isolated data; the project ships without accounts or sample client credentials.

```sh
.venv/bin/python -m unittest discover -s tests -t . -v
SING_BOX_TEST_BINARY="$PWD/dist/sing-box" .venv/bin/python -m unittest discover -s tests -t . -v
node --check web/app.js
npm ci --ignore-scripts
npm test
```

Node.js/npm are only used for development QR verification; the installed panel needs neither. QR tests decode the rendered QR with an independent decoder and verify custom paths, IPv6/ports, long links, token rotation, missing public URL behavior, the official import URI with Unicode profile names, format switching, and matching copy/PNG payloads.

Integration tests exercise real loopback transfers for all six protocols, Vision, VMess padding/multiplex, Salamander/Gecko, TUIC congestion settings, AnyTLS padding and every supported V2Ray transport. They also cover automatic HTTP saves, failed-save rollback, usage reset atomicity, inactive inbound checking, DNS options, self-signed TLS verification, accounting, persistence and quota enforcement. They do not change host routes, firewall, or DNS.

Reset administrator access on an installed server:

```sh
cd /opt/nara-panel
sudo -u nara-panel .venv/bin/python -m nara reset-password --data /var/lib/nara-panel --username admin
```

## Upstream references

- [Sing-box configuration](https://sing-box.sagernet.org/configuration/)
- [V2Ray API and required build capability](https://sing-box.sagernet.org/configuration/experimental/v2ray-api/)
- [DNS server configuration](https://sing-box.sagernet.org/configuration/dns/server/)
- [Official source used for the core build](https://github.com/SagerNet/sing-box/tree/v1.14.3)

NARA Panel is independent of SagerNet. Panel code is MIT licensed. Sing-box and third-party dependencies retain their respective licenses; the core is built separately from upstream GPL-licensed source.

## Bundled reference data

The versioned schema and configuration help are under `nara/schema`. Their source,
regeneration command and upstream documentation license are recorded there. The
panel's own code retains its project license; the bundled QR encoder retains its
MIT notice. The build script downloads the pinned upstream core and its separately
licensed runtime dependencies from their official sources.
