# Shared catalog table

`jarvis/runtime/control_center_catalog.js` is the presentation-only catalog
component shared by future Agent/CLI and Voice settings surfaces. The server
inserts it into the single Control Center document; consumers call
`JarvisCatalog.createCatalogTable(container, options)` and then `load()`.

Required options:

- `surface`: `subagents` or `voice`;
- `role`: an optional role accepted by `GET /api/catalog`;
- `columns`: any ordered subset of `compare`, `model`, `provider`, `roles`,
  `capabilities`, `tags`, `guidance`, `price`, `availability`, and `actions`.

Optional callbacks are `onCompare(keys)` and `onAction(action, item)`. An
action button is rendered only for a bounded action descriptor supplied in the
item's backend `actions` list. The component never fabricates request, install,
selection, or availability operations.

The returned controller owns three named delegated event handlers and at most
one active request. Search input updates only result/summary regions, preserving
the live input node, focus, caret, selection and IME state. Every `load()` or
`refresh()` aborts its predecessor and uses a monotonic generation guard, so an
older response or failure cannot replace newer state even when a custom fetcher
ignores abort. `destroy()` aborts pending work, invalidates generations, removes
all handlers and prevents late promises or public methods from restoring DOM.

## Projection rules

- Search spans label and structured identity plus sourced roles, capabilities,
  tags, description, and recommended uses.
- Multiple choices inside one filter family use OR. Active filter families use
  AND. Provider, role, capability, tag, and backend availability state are
  available as filter families.
- Name and price sorts are stable. Unknown price is always last. Currency/unit
  groups are not converted or compared against one another. Within one
  `million_tokens` group, the display shows input/output prices and sorting uses
  their mean solely as a deterministic comparison key. Minute prices use the
  supplied amount.
- Compare selection is capped (three by default) and checks only the backend
  `availability.selectable` boolean. The component does not derive
  selectability from state names.
- Availability state, reason, and evidence remain visible in their own column.
  Sourced comparison metadata exposes provenance through titles/details. Each
  role chip uses its own `provenance_by_value` sources (including a displayed
  provider/registry union) and falls back to the compatible primary provenance.
- Missing values render as `Inconnu`; they never become zero, free, unsupported,
  or usable.

Loading, request error, missing-credential, empty-inventory, empty-filter and
partial-metadata states have distinct accessible status messages. A
missing-credential notice does not hide inventory rows already returned by the
backend.

## Rendering and accessibility

The renderer uses escaped text for every backend value, labelled search and
filter groups, column headers, model row headers, status live regions, keyboard
focus outlines, and disabled compare controls for non-selectable rows. Under
700 px the table becomes labelled row cards using the same markup and data,
avoiding a separate mobile component.

`tests/unit/test_control_center_catalog_ui.py` executes the production module
with Node against the deterministic five-state fixture in
`tasks/jarvis-settings-model-catalog-ux/slices/04-shared-catalog-table/fixtures/`.
It covers search, multi-filtering, both price directions, unknown-last,
comparison safety, provenance, backend-only actions, escaping, UI states,
responsive markers, script injection, and complete served-page syntax. Fake-DOM
controller tests exercise live typing, deferred response/error races, abort,
destroy, listener removal and destroy/recreate behavior.

## Observability / Test Contract

Projection and rendering are pure and produce no LogBroker event or correlation
ID. Network failures become an in-component error state; recovery is `load()`
or `refresh()`. Provider failures remain owned by the `/api/catalog` boundary
and its existing `provider.models_failed` warning contract. No debug probe,
fallback, new channel, persistence, or raw source payload is introduced.
