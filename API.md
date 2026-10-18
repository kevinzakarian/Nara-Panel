# NARA automation API v1

An API lets another program read the panel or manage it without clicking the web interface. You do not need an API key for normal panel use. Start with a **Read** key, give each integration its own key and add write permissions only when needed.

## Connection and keys

Open **API access → Create API key**, name the integration, choose permissions and an expiry of 1–365 days (default 90), then confirm your current administrator password and a fresh 2FA/recovery code if enabled. Copy the key immediately; it is displayed once. NARA stores only its SHA-256 hash. Revoke a key from the same page at any time. There can be at most 50 active keys.

The API base address is your **panel** URL followed by `api/v1/`, for example `https://panel.example.com:10000/MyPanel/api/v1/`. The subscription listener does not expose the administration API. Use HTTPS for remote automation. Send the key in the Authorization header; never put it in a URL, browser frontend or shared screenshot. Browser session cookies do not authenticate v1 API requests. Cross-site browser requests are rejected; CORS access is not enabled.

```sh
NARA_API='https://panel.example.com:10000/MyPanel/api/v1'
read -r -s NARA_KEY
curl --fail-with-body -H "Authorization: Bearer $NARA_KEY" "$NARA_API/status"
```

The shell examples assume an already-created key. Replace addresses and IDs with your own. They do not collect SSH credentials.

| Permission | Access |
| --- | --- |
| `read` | Status, metrics and configuration, with credentials hidden |
| `clients:write` | Create/edit/delete clients and groups; bulk operations |
| `config:write` | Inbounds, TLS, DNS, routing, core options, WARP and other native records |
| `core:control` | Check/start/stop the core and request a release check |
| `panel:manage` | Queue a verified panel upgrade and change panel/subscription paths and ports |
| `secrets:read` | Include passwords, UUIDs, private keys, private profiles and subscription links in reads |

Scopes are independent: add `read` when an integration also needs to inspect resources. `secrets:read` requires `read` for GET requests. A write key can change the resources in its scope even without reading their previous secrets. Administrator identity, password, 2FA, API-key management and Telegram credentials require browser reauthentication and are intentionally outside the machine API.

## Revisions, responses and failures

First GET the resource or `/state`. It returns a numeric `revision`, also exposed as a quoted ETag. For configuration writes send that revision in `If-Match: "12"` or the JSON `revision` field. If both are supplied they must agree. A 409 means another change won the race: read again, review the new state and retry. Never retry a creation blindly after an uncertain response; first check whether it succeeded.

Successful reads normally return `{"data": ..., "revision": 12}`. Lists also include `pagination: {total, limit, offset}`. Successful configuration mutations return the new revision and apply status; create responses also include the saved record. Bulk operations return `ids` and `affected`. Preview returns `preview_id`, `count`, `examples` and `expires_in`.

All configuration writes use the panel's validation and automatic core apply. A rejected change preserves previous saved settings and attempts to retain/restore the running core. A batch is one transaction and one apply. Runtime start/stop and maintenance operations have their own explicit behavior; software/entry operations return 202 and an operation ID where applicable.

Errors use `{"error":{"code":"revision_conflict","message":"..."},"request_id":"..."}`. Responses include `X-Request-ID`. Codes include 400 invalid input/validation, 401 missing/expired/revoked key, 403 missing permission, 404 missing resource, 405 unsupported method, 409 stale revision/inactive private profile, 429 rate limit and 500 operation failure. Requests are limited to **120/minute/key**; 429 supplies `Retry-After: 60`. The existing JSON body limit is 1 MiB. Raw core logs and credentials are not returned in generic errors. Public listeners cap concurrent handlers at 32 each and expire idle sockets after 15 seconds; handle temporary connection failures with bounded retries. API last-used metadata has up to one minute of timestamp precision.

## Resource CRUD

These collection paths support `GET` (list) and `POST` (create); `/{id}` supports `GET`, `PATCH` and `DELETE`:

| Path | Write permission |
| --- | --- |
| `/clients`, `/groups` | `clients:write` |
| `/inbounds`, `/tls`, `/dns/servers`, `/dns/rules`, `/rule-sets`, `/routing/rules` | `config:write` |
| `/outbounds`, `/endpoints`, `/services`, `/certificate-providers`, `/http-clients`, `/network-namespaces` | `config:write` |

Lists accept `limit` (1–250, default 50) and `offset` (default 0). Clients also accept `search` (name/note/tags), `group` (group ID), `tag` and `status` (`all`, `active`, `inactive`, `disabled`, `expired`, `limited`). Fetch all pages before selecting a complete group for a bulk action.

POST/PATCH bodies contain the record fields directly, with an optional `revision`. IDs are assigned by NARA and cannot be changed. PATCH recursively merges objects, replaces arrays and removes a property when its value is null. Omitted credentials remain unchanged through the shared native editor. To remove a secret, use the property's explicit valid replacement supported by its schema. DELETE may have an empty body if If-Match is present. Deleting referenced resources is rejected; deleting a client group detaches its memberships and retains its clients.

Client fields are `name`, `note`, `enabled`, `quota_bytes`, `expires_at`, `inbound_ids`, `group_ids` and `tags`. UUID/password/subscription credentials are generated securely. A blank/omitted name becomes ten random letters containing both cases. `quota_bytes: 0` means unlimited; empty expiry means no expiry. Use ISO 8601 with a timezone for timestamps. Groups have `name` and `description`. Each client supports up to 20 groups, 20 tags of 1–32 characters and a note up to 1000 characters. Group names are unique ignoring case.

```sh
curl --fail-with-body -X POST "$NARA_API/clients"   -H "Authorization: Bearer $NARA_KEY" -H 'Content-Type: application/json'   -H 'If-Match: "12"'   --data '{"inbound_ids":["INBOUND_ID"],"quota_bytes":10737418240,"tags":["monthly"]}'
```

Native records use `{"name":"optional label","enabled":true,"config":{...}}`. The `config` is the exact Sing-box 1.14.3 object; NARA sets `mode: native`. Get `/schema` for the pinned JSON schema or inspect an existing resource. Managed inbounds/TLS profiles retain their panel model, available through `/state`; private fields require the secrets scope. Do not insert native users into a managed account inbound.

```json
{"config":{"type":"udp","tag":"dns-google","server":"8.8.8.8","server_port":53}}
```

The example creates a DNS server; it does not change the default resolver. Use PATCH `/settings` with `{"dns_final":"dns-google"}` to choose it, using the new revision after creation.

## Bulk creation and actions

POST `/clients/bulk/preview`:

```json
{"revision":12,"count":3,"start":1,"pattern":"Team-{n:03}","defaults":{"inbound_ids":["INBOUND_ID"],"quota_bytes":10737418240,"group_ids":["GROUP_ID"],"tags":["monthly"],"enabled":true}}
```

It previews `Team-001` through `Team-003`. Supported tokens: `{n}`, `{n:03}` (zero-padding widths 1–6), `{random}` and `{group}` (selected group names). A blank pattern generates ten mixed-case random letters per client. Duplicate names are rejected. Each client gets independent credentials. Batch size is 1–500, with at most 1000 clients in total.

Apply with POST `/clients/bulk` and `{"revision":12,"preview_id":"RETURNED_ID"}`. The private prepared draft is bound to that API key and revision, expires after ten minutes and preserves the exact previewed random names. Any intervening settings change requires a new preview. Automation may also POST the original count/pattern/defaults body directly without preview.

For existing clients, POST `/clients/actions/preview` then `/clients/actions` with the returned preview ID; or send a direct action:

```json
{"revision":13,"ids":["CLIENT_1","CLIENT_2"],"operation":"quota_add","value":5368709120}
```

| Operation | `value` |
| --- | --- |
| `enable`, `disable`, `delete`, `reset_traffic`, `rotate_tokens` | Omit |
| `quota_set` | Total bytes; 0 makes unlimited |
| `quota_add`, `quota_subtract` | Positive bytes; unlimited accounts remain unlimited; subtraction has a 1-byte floor so it cannot accidentally make finite accounts unlimited |
| `expiry_set` | ISO timestamp or empty string to clear expiry |
| `expiry_extend`, `expiry_shorten` | Positive number of days; no-expiry accounts remain without expiry |
| `groups_set`, `tags_set`, `inbounds_set` | Complete replacement array of group IDs, tag strings or inbound IDs |

Select 1–1000 distinct existing IDs. Deletion removes accounts immediately; reset clears their stored usage; rotate changes subscription tokens and invalidates old links. Preview these changes before applying them. A failed batch keeps all original accounts and counters.

## Additional operations

| Method/path | Body or behavior |
| --- | --- |
| GET `/status`, `/core/status`, `/stats`, `/state`, `/settings` | Panel/core versions, metrics/traffic totals, model and connection settings; `read` |
| GET `/schema`, `/openapi.json` | Sing-box schema / downloadable OpenAPI 3.1 route specification; `read` |
| GET `/core/config` | Rendered server configuration; `read` + `secrets:read` |
| GET `/clients/{id}/profile` | Active client JSON; `read` + `secrets:read`; inactive profile returns 409 |
| GET `/clients/{id}/subscription` | Private URL and active eligibility; `read` + `secrets:read` |
| PATCH `/settings` | Direct connection-setting fields merged into current settings; `config:write` |
| GET/PUT `/core/options/{section}` | `log`, `dns`, `ntp`, `certificate`, `route`, `experimental`; PUT uses `{"options":{...}}`; DNS additionally uses `default_resolver`; writes need `config:write` |
| POST `/dns/rules/{id}/move`, `/routing/rules/{id}/move`, `/rule-sets/{id}/move` | `{"direction":"up"}` or `"down"`; `config:write` |
| POST `/core/check`, `/core/start`, `/core/stop` | State revision; `core:control`; start applies settings, stop saves stopped intent |
| POST `/tls/self-signed` | `{"name":"label","server_name":"example.com","days":365}` plus revision; `config:write` |
| POST `/warp` | `{"accept_terms":true}` plus revision; `config:write`; registers externally, see WARP terms/limits in README |
| GET `/updates` | Cached stable panel/core release information; `read` |
| POST `/updates/check` | No state revision required; one asynchronous check; `core:control` |
| GET `/panel/access` | Entry values and their separate access revision; `read` |
| PATCH `/panel/access` | `{"revision":ACCESS_REVISION,"values":{...}}`; `panel:manage`; use values from the current access response, not the model revision |
| POST `/panel/update` | `{"version":"0.8.0"}` with a currently eligible stable version; `panel:manage`; no state revision required |
| GET `/operations/{id}` | Access/update maintenance progress by the returned 32-character URL-safe operation ID; `read` |

Entry changes can move the API address and disconnect the requester. Software updates require the managed Linux maintenance service, verified fixed-repository release assets and compatible dependencies; failures are reported in operation status. The API does not upload code or accept arbitrary commands.

## Specifications

The panel's API access page includes a short guide and OpenAPI download. The OpenAPI file describes routes, methods, scopes and revisions; this guide supplies the panel record and bulk body conventions. Native field schemas come from `/schema`. Authentication follows [Bearer token usage (RFC 6750)](https://www.rfc-editor.org/rfc/rfc6750); administrator 2FA uses [TOTP (RFC 6238)](https://www.rfc-editor.org/rfc/rfc6238).


## Panel time zone

`GET /settings` returns `time_zone` (an IANA name; legacy records without it use `UTC`). `PATCH /settings` accepts, for example, `{"revision":12,"time_zone":"Asia/Tehran"}` with the same revision and `config:write` requirements as other settings. The setting controls panel display and Telegram daily summary scheduling. It does not change the OS clock, stored expiry instants or generated Sing-box configuration. Unsupported/malformed zones are rejected atomically. Telegram credentials, events and daily summary hour/minute still require the browser’s administrator verification flow.

### Traffic history and share links (0.10)

`GET /api/v1/stats` also includes independent server allowance and managed display counters in `data.traffic`. `GET /api/v1/traffic?kind=client&id=CLIENT_ID&range=24h` accepts `kind=client|inbound|server` (`id=host` for the server), and `range=6h|24h|week|month|3months`. These endpoints require `read`. Client protocol share links use `GET /api/v1/clients/CLIENT_ID/links` and require both `read` and `secrets:read`.

Portable backup/restore, credential-bearing CSV downloads and SSH migration use the browser administrator workflow with current-password/fresh-2FA verification. Machine API keys do not grant root SSH migration or backup download access.


Client contacts and private service page (0.11.0): client create/patch supports optional `email` and `telegram_id` (`@username` or numeric user ID). Contacts are validated and are not proof of Telegram chat ownership. `GET /api/v1/clients/CLIENT_ID/portal` returns the private service-page URL and requires `read` plus `secrets:read`, like profile and subscription access. Rotating the subscription token also invalidates the derived portal capability and the bot binding. SMTP credentials/templates and client delivery actions remain browser-administrator operations protected by session/CSRF checks; changing delivery settings additionally requires the current password and configured second factor.
