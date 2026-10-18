# NARA security and resource review — 0.8.1

Review date: **2026-10-18**. Scope: the panel-owned Python service, browser code, installation/upgrade scripts, systemd boundaries and dependency manifests. This is an engineering review with regression tests and dependency/static scans, not an independent penetration test or an audit of the upstream Sing-box/Cronet implementations.

## Findings and changes

| Area | Finding | Resolution |
| --- | --- | --- |
| Telegram workflow | Chat discovery silently read an empty password field far below the button, producing an incorrect-password error. | Discovery, connection testing and saving now each open an explicit, required administrator-password/2FA dialog. Missing bot tokens are caught before reauthentication. Unsaved token input is supported without saving or enabling delivery. |
| Bot testing | The existing delivery test required saved/enabled notifications and did not help validate a token during setup. | **Test bot** performs fixed-host HTTPS [`getMe`](https://core.telegram.org/bots/api#getme), shows only the bot's public name/username and sends no message. **Send test message** continues using the saved destination and private outbox. |
| Concurrent settings edits | Silent refresh could update the model revision while a settings form still contained old values. | Settings forms retain their rendered revision. Conflicting writes are rejected through the existing atomic validation/apply transaction. |
| REST maintenance status | The endpoint matched hexadecimal IDs; the broker generates URL-safe IDs containing capitals, `_` and `-`. | The route accepts the actual 32-character URL-safe format. |
| HTTP resources/framing | Thread-per-connection listeners had no application cap or idle timeout. Duplicate length/transfer-encoding and non-finite JSON were not explicitly rejected. | Each listener has at most 32 active handlers, a 15-second idle socket timeout and a bounded accept queue. JSON bodies require one Content-Length, no Transfer-Encoding, and the existing 1 MiB size limit; NaN/Infinity constants are rejected. |
| Origin/security tokens | Origin checks compared authority alone, and non-ASCII CSRF values could raise a comparison error. | Origins must be valid HTTP(S), match the authority and use HTTPS when secure cookies are required. Security-token comparison uses bytes and returns a normal rejection. |
| File publication | Atomic writes used a predictable temporary filename that could collide or follow a planted symlink. | Private, randomly named, exclusively created sibling files are flushed and atomically replaced, with cleanup on failure. |
| Release transport | Final release URLs were checked for HTTPS, but redirects could downgrade an intermediate request. | Both release check/download paths enforce HTTPS on the initial request and every redirect. Archive checksums and safe extraction remain required. |
| API read confidentiality | Some native service credentials (including Tailscale auth keys and certificate-provider/static keys) were missing from the read-only redaction list. | The list now covers the credential vocabulary from the pinned schema, with an actual API read/secrets-scope regression. Public keys remain readable. Rotate affected native service credentials if they were exposed to an untrusted Read-only integration on an earlier release. |
| API write pressure | Every authenticated request updated last-used metadata. | Last-used timestamps are written at most once per key per minute. Expiry/revocation checks still run on every request. |
| Notification idle work | The disabled/empty worker opened database connections every second. | A wake event handles new queue items/preferences; idle work sleeps up to 30 seconds, with scheduled retries and shutdown wakeup. |
| Core idle work | Every accounting tick rebuilt/validated the full configuration and reread its JSON even when account eligibility was unchanged. | Accounting remains every five seconds; a compact eligibility set triggers rebuilding only when quota/expiry eligibility changes. The baseline comes from the actual generated configuration, preserving expiry boundaries during startup. Zero traffic deltas do not create database writes. |
| Browser refresh | Every five-second tick downloaded state, metrics and entry settings. | Routine refresh fetches metrics/status; the full model is fetched when the active revision changes. Manual refresh/save still reloads all required state. Polling remains suspended for hidden tabs, open dialogs and maintenance. Repeated failure toasts are throttled. |
| UI state/secrets | Closed dialog content and late integration responses could outlive their visible operation/session. | Dialog close clears content/callback/config previews. Late integration cache responses are ignored after a session change. In-flight failures handle detached forms safely. |
| Inbound display | Native TLS could be labeled No TLS; an enabled inbound without eligible accounts could be labeled Active. | Native TLS is recognized. States distinguish Running, Waiting for clients, Core stopped and Disabled; transport labels use WebSocket/gRPC/HTTPUpgrade spelling. |

## Retained security boundaries

Administrator passwords use salted PBKDF2-SHA256 (600,000 rounds); browser sessions and API keys are stored as hashes. CSRF, same-origin checks, throttling and reauthentication remain enforced. TOTP setup verification, replay prevention and hashed single-use recovery codes remain covered by tests. Uploaded avatars stay bounded normalized PNGs with no external image URL or SVG execution. Client credentials remain independently generated; private profiles are bearer secrets. Subscription listeners expose no administration UI/API and retain the full supported 32–128-character legacy token range.

Machine keys retain independent scopes, expiry, revocation and default secret-redacted reads. Configuration writes, including bulk operations, continue using core validation and rollback. Configuration-writing keys are powerful credentials: native Sing-box options can access files/network resources available to the unprivileged core. Root maintenance accepts fixed operations and verified fixed-repository releases; it does not execute arbitrary request commands. No new runtime package or frontend framework was added.

## Dependency/static checks

- `npm audit`: **zero reported advisories** in the current development dependency lockfile. Browser assets do not load packages from a CDN.
- `pip-audit`: current installed `grpcio 1.84.0`, `typing_extensions 4.16.0`, development `PyYAML 6.0.3` and `pip 26.2.1` reported **zero advisories** on the review date.
- The initial scan flagged the old development/bootstrap `pip 25.0.1`. It was upgraded locally. Fresh/full Linux installations and Docker builds now upgrade to `pip>=26.2,<27` before installing the unchanged runtime requirements. Panel-only upgrades preserve their existing Python environment; pip is installation tooling and is not invoked by normal web requests. See [official pip release notes](https://pip.pypa.io/en/stable/news/).
- Bandit findings were triaged against the code. Expected subprocess calls use fixed executables and argument arrays; test-only passwords and verification assertions are fixtures; all-interface binding is the intentional public listener/port-availability check. Traffic SQL now uses fixed whitelisted statements. Release HTTP openings go through the HTTPS-only helper. No finding is being represented as a successful exploit.

A final Ruff F-rule scan passed after six unused imports were removed from panel/maintenance/build helpers.

Actual test counts, native Linux results, browser checks and external-service limits are recorded in [VERIFICATION.md](VERIFICATION.md). Telegram responses are mocked in automated tests; no real bot message or production server change was performed during this review.
