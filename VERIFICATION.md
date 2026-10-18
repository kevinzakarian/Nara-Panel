# Verification — NARA 0.12.0 · 2026-10-18

The complete Python suite passed **345 tests without skips** in **280.574 seconds**, using Python 3.12.14, real Sing-box 1.14.3 and Caddy 2.4.6/2.6.2. The final frontend suite passed **168 tests without skips**, including the final portal refresh guard and human-readable account rule summaries.

The multiple-source integration test sends real proxy traffic from two selected accounts across two inbound listeners through a second local SOCKS gateway, verifies its traffic counters, and verifies that an unselected third account retains the direct fallback. The same source lists select a distinct DNS resolver; the third account receives the fallback answer. Tests do not change host routes, DNS or firewall.

New coverage includes verified numeric Telegram contact persistence/backfill/replay protection, connected portal state and bot-change revocation, small byte amounts and refreshed counters before bot replies, source-only multiple-account/inbound forms, consolidated Settings with isolated alert/billing saves, escaped email previews with local QR, and real-stage update progress/failure handling. No actual customer email or Telegram message was sent.

Native Linux verification: [run 39141997408](https://github.com/kevinzakarian/Nara-Panel/actions/runs/39141997408), implementation commit `20d0d71`. All four jobs passed: real-core AMD64 and ARM64 traffic/accounting without Go or Git, systemd maintenance/upgrade with a live WAL database, and fresh-destination SSH migration. Subsequent changes concern frontend refresh guarding and rule summaries, not the tested backend or service implementation.

Browser checks used an isolated loopback fixture with synthetic accounts. A single header Save persisted both the selected time zone and monthly allowance. The Notifications threshold form and private bot are outside the administrator notification form; a CPU threshold save succeeded independently. The 390px Notifications layout had no horizontal overflow. Email preview displayed fictitious substituted values and local QR codes; Email has no private-bot configuration card. A DNS source-only rule saved two selected accounts and an inbound; its final summary showed their display names. The default DNS badge has a measured 10px separation from its label. [Settings screenshot](screenshots/settings-0.12.0.png) and [email preview](screenshots/email-preview-0.12.0.png) record the tested UI.

Runtime requirements remain grpcio only; servers require neither Go nor Node.js. Prior release evidence remains in Git history at tag v0.11.0.
