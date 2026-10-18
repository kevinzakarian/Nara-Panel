# Verification — NARA 0.14.0 · 2026-10-18

Verification is in progress for the final implementation. Frontend checks exercise all native rule fields/actions, typed scalar/list round trips, searchable choices, custom identities and numeric DNS query types, safe action remounting, all three appearance palettes, device preference changes and live client badges. Real-core tests cover traffic forwarding/accounting, an authenticated open connection, exclusion after closing it, and rejection of invalid private monitor credentials.

Browser verification uses disposable loopback services and synthetic accounts. The update-available banner in screenshots is simulated fixture data. No production server, customer account or external notification is modified. Screenshots show real panel rendering rather than the earlier generated concepts.

Final test totals and native Linux CI evidence will be recorded before publication.
