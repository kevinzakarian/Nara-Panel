# Verification — NARA 0.11.0 · 2026-10-18

The complete Python suite passed **339 tests without skips** in 436.689 seconds using Python 3.12.14, real Sing-box 1.14.3 and Caddy 2.4.6/2.6.2. The final browser logic suite passed **159 tests without skips** after the overview strip was made a single horizontal row.

New coverage includes per-account Routing/DNS behavior against real core traffic, quota-driven removal of scoped listeners, public portal isolation/revocation/origin checks, Telegram pairing/replay/ownership, SMTP template injection/expansion bounds, real loopback implicit TLS and STARTTLS delivery with inline QR MIME, independent QR decoding, and SSRF/private-redirect defenses. No real customer email, Telegram message or production-server migration was sent.

Native Linux verification is tracked in [run 39133623095](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39133623095), on implementation commit `c995e90e8197ce06c7138b35689cd848605111e1`. All four jobs passed: AMD64 and ARM64 real proxy/accounting checks without Go or Git, systemd maintenance/upgrade with a live WAL database, and fresh-destination SSH migration. Subsequent release changes only compact the frontend version strip and update documentation/screenshots.

Browser verification used a disposable loopback fixture: the unified connection-format/QR dropdown, private service page with balance and remaining time, responsive 390px service page without horizontal overflow, destination-URI extraction into a reviewed form, grouped fixed NTP settings, and the one-line overview version strip. [Overview screenshot](screenshots/overview-0.11.0.png) shows the 1440px desktop view with synthetic account data. Host traffic metrics are unavailable on this macOS preview; native Linux is covered separately.

The exact 1.14.3 schema remains pinned. Runtime requirements remain grpcio only; QR generation uses a locally vendored MIT encoder and Python standard library.
