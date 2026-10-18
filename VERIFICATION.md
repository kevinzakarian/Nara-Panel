# Verification — NARA 0.12.0 · 2026-10-18

Final complete validation is in progress. Targeted real-core backend validation passed 50 tests without skips. The new multiple-inbound/account Routing and DNS integration test passed with Sing-box 1.14.3, a second local SOCKS gateway and distinct resolver responses. Frontend verification passed 167 tests without skips before the final DNS label adjustment.

Coverage adds verified numeric Telegram contact persistence/backfill/replay protection, connected portal state/revocation, small byte amounts and refresh before bot replies, source-only multiple-account/inbound forms, consolidated Settings and isolated alert/billing policy saves, escaped email previews with local QR, and real-stage update progress/failure handling. No actual customer email or Telegram message was sent.

The preceding release evidence remains in Git history at tag v0.11.0.
