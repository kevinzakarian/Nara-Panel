# Verification — NARA 0.11.0 · 2026-10-18

Release validation is in progress on this development branch. The preceding complete Python run passed **335 tests without skips**, with Sing-box 1.14.3 and Caddy 2.4.6/2.6.2. The final additional client-access/SMTP and quota-isolation checks passed **21 tests**; the browser suite passed **157 tests**. A final full run and fresh AMD64/ARM64/systemd/migration checks will be recorded before publishing this release.

New coverage includes per-account Routing/DNS behavior against real core traffic, quota-driven removal of scoped listeners, public portal isolation/revocation/origin checks, Telegram pairing/replay/ownership, SMTP template injection/expansion bounds, real loopback implicit TLS and STARTTLS delivery with inline QR MIME, independent QR decoding, and SSRF/private-redirect defenses. No real customer email, Telegram message or production-server migration was sent.

The exact 1.14.3 schema remains pinned. Runtime requirements remain grpcio only; QR generation uses a locally vendored MIT encoder and Python standard library.
