# Shared model catalog view model

## Purpose

`CatalogViewService` projects existing provider, CLI and voice-registry evidence
into one schema for sub-agent and voice comparison surfaces. It is presentation
data, not routing authority. Existing routing policy and voice validators remain
the execution authorities.

Envelope:

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-14T12:00:00+00:00",
  "surface": "subagents",
  "role": "subagent",
  "sources": [],
  "items": []
}
```

Each item exposes an opaque deterministic `key`, structured `identity`, `kind`,
label, sourced roles/capabilities/comparison claims, explicit availability, and
`actions`. Consumers must never parse `key`; provider/model IDs can contain
colons, slashes or other delimiters.

## Availability states

| State | Meaning | Selectable |
|---|---|---:|
| `usable` | Runtime path is ready and current provider/account evidence lists exact model. | yes |
| `configured_unverified` | Runtime path exists, but default model, authentication or provider evidence was not invoked/current. | no |
| `available_not_configured` | Current provider evidence lists model, but required CLI/adapter is absent or not ready. | no |
| `unavailable` | A current negative fact exists: unavailable CLI/account, or fresh provider list omits saved/registered model. | no |
| `unknown` | Evidence cannot establish availability or wiring. | no |

`selectable` is derived, never supplied by curated metadata. Only `usable` is
selectable in this comparison contract. Existing saved settings may still be
shown by their owning settings API; this view does not delete or rewrite them.

### Sub-agent matrix

- CLI detected + exact model in live/fresh account catalog -> `usable`.
- CLI missing + exact model in live/fresh account catalog ->
  `available_not_configured`.
- CLI detected + default CLI model -> `configured_unverified`; `--version` does
  not prove CLI authentication or which default model an invocation will use.
- Saved model absent from live/fresh account catalog -> `unavailable`.
- Saved model absent from stale/missing catalog -> `configured_unverified` when
  CLI exists, otherwise `unavailable` because CLI absence itself is current.
- In Auto, only a candidate belonging to the active host CLI can be selectable.
  The current verified hook exists on Claude. Codex exposes no equivalent
  background sub-agent boundary, so Codex candidates remain non-selectable even
  when its executable and provider model are both present.

### Voice matrix

- Ready canonical adapter + exact model in live/fresh provider catalog ->
  `usable`.
- Ready adapter + stale/missing provider evidence -> `configured_unverified`.
- Provider model without ready canonical adapter ->
  `available_not_configured` when provider evidence is current.
- Registered model omitted by current provider evidence, or registry account
  state `unavailable` -> `unavailable`.
- Non-ready registry entry with stale/missing provider evidence -> `unknown`.

## Provenance and freshness

Every non-null comparison claim is a `SourcedValue`:

```json
{
  "value": ["semantic"],
  "provenance": {
    "source_id": "cli_registry:claude",
    "kind": "runtime_registry",
    "reference": "jarvis.runtime.cli_catalog.AGENT_CLIS",
    "observed_at": "2026-09-14T12:00:00+00:00",
    "updated_at": null,
    "freshness": "fresh",
    "status_code": "ok"
  }
}
```

List-valued claims may additionally carry `provenance_by_value`, keyed by every
exact value. Role unions use it to keep provider classifier and runtime registry
evidence distinct. A saved model absent from provider discovery retains its
`subagent` and `text` roles, but both are attributed only to routing settings;
it never borrows live provider provenance. `provenance` remains the compatible
primary source for older consumers.

Freshness values:

- `live`: provider response measured now within catalog TTL;
- `fresh`: cached provider response still within TTL, or current shipped runtime
  registry evidence;
- `stale`: cache timestamp exceeds TTL;
- `unknown`: missing, invalid or implausibly future timestamp, failed discovery,
  or otherwise insufficient evidence.

Stale evidence may keep a known item visible. It never proves current
usability, and omission from a stale list never proves model removal. Curated
metadata cannot modify availability, selectability, roles or runtime
capabilities.

`status_code` is `ok` for successful sources and carries bounded stable source
outcomes such as `stale`, `catalog_no_key` or `catalog_unreachable`. Therefore
even an empty catalog can explain why no item is verified, without exposing a
credential, key hint or raw provider payload.

## Pricing and qualitative metadata

No pricing, benchmark rank, quality score, latency score, tag, description or
recommendation is bundled by this Slice. Unknown fields are JSON `null`.

Optional reviewed metadata enters only through `CatalogMetadataRegistry`.
Every claim requires provenance. Pricing additionally must pass existing strict
`PricingMetadata` or `TokenPricingMetadata` parsing, match exact model ID, carry
source and timezone-aware effective date, and use one normalized unit:

- `million_tokens` with input/output prices;
- `minute` with amount per minute.

Invalid or unsourced raw pricing is `null`; it is never partially rendered.

## Request/add boundary

No request, installation or integration sink exists in current runtime.
Consequently every item returns `"actions": []`. A later implementation may
advertise request/add only after adding a real injected sink with a durable
outcome and tests. A local placeholder, unconsumed JSON request, link inferred
from provider identity, or fabricated `requestable` state is forbidden.

## Integration contract

`GET /api/catalog?surface=subagents|voice&role=<role>&refresh=<bool>` is the
canonical read-only endpoint. Control Center passes complete provider envelopes
(`source`, `fetched_at`, `status_code`, safe model list), current CLI probes,
saved structured `CandidateRef` values, and `VoiceCapabilityRegistry` into one
`CatalogViewService` projection. Legacy `/api/models` and
`/api/routing/candidates` remain available as compatibility endpoints.

Roles are allowlisted by surface. `subagents` accepts `subagent` or `text`;
`voice` accepts `text`, `realtime`, `duplex`, `transcription`, `speech`,
`analysis`, `conversation`, or an omitted role for the full voice inventory.
Unknown, misspelled, or cross-surface roles return
`catalog_role_invalid` (HTTP 400).

Runtime `routing_hook` remains execution authority, but shares
`ProviderCatalogSnapshot.current_models()` eligibility: stale/failed provider
evidence cannot become an explicit usable or forced routing candidate. Legacy
`/api/routing/candidates` uses the same eligibility and keeps saved stale
choices visible with an explicit non-verified reason.

## Observability / Test Contract

Catalog domain, metadata registry and assembly service are pure and perform no
I/O. Normal projection and validation emit no journal event, need no correlation
ID, create no temporary probe, and introduce no permanent channel. Provider
failures at the HTTP boundary reuse `provider.models_failed` at warning level,
with provider and stable code only; response remains HTTP 200 with honest
unknown/stale evidence. Recovery is a later successful fetch or explicit
`refresh=true`. Cache fallback is credential-bound by an opaque fingerprint;
neither that fingerprint nor a key hint enters endpoint payloads or logs. No
secret, temporary probe, or new channel is introduced.

Regression contract lives in `tests/unit/test_catalog_view.py`,
`tests/unit/test_routing_hook.py`, and `tests/unit/test_settings_endpoints.py`:
deterministic keys, immutable sourced claims, full availability matrices,
fresh/stale/unknown timestamps, cross-view routing eligibility, role/surface
filtering, endpoint refresh/errors, source privacy, strict pricing, and empty
actions.
