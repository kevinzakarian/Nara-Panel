# Verification — NARA 0.13.0 · 2026-10-18

- **176 frontend tests passed without skips**, including every pinned rule/action field, nested logical rules, typed unions, action/type switching, lossless round trips, required targets and JSON conversion. Editor output for all eight traffic actions, six DNS actions and both logical forms was checked with the real Sing-box 1.14.3 binary (16 configurations).
- **33 targeted Python tests passed without skips**: native-schema coverage and real-core auto-apply behavior. No backend logic changed in this release. The previous full 345-test backend run remains recorded at tag v0.12.0.
- Browser verification used a disposable loopback preview with synthetic accounts and a real core. Native traffic and DNS rules were saved successfully and applied automatically. Horizontal field tabs, native field labels and action-specific targets were visually checked. Screenshots: `screenshots/routing-rule-0.13.0.png` and `screenshots/dns-rule-0.13.0.png`. No live customer configuration was modified.

The real core confirmed that 1.14.3 route-action `fallback_delay` is numeric (not a duration string), that nested DNS response fields need `match_response` on the same child, and that logical `respond` cannot bind a response tag from its children. Forms keep the pinned vocabulary rather than importing newer documentation-only fields.

Fresh native Linux validation will be recorded before publication.
