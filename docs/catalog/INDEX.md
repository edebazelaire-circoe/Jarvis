# Model catalog implementation index

| Responsibility | Module / evidence |
|---|---|
| Provider-neutral schema, opaque keys, sourced claims, availability states | `jarvis/domain/catalog.py` |
| Strict optional metadata registry and existing pricing adapters | `jarvis/runtime/catalog_metadata.py` |
| Provider snapshot freshness and shared sub-agent/voice assembly | `jarvis/runtime/catalog_view.py::CatalogViewService` |
| Canonical read-only HTTP projection | `jarvis/runtime/control_center.py::catalog_view` (`GET /api/catalog`) |
| Live provider discovery and disk cache | `jarvis/runtime/model_catalog.py::ModelCatalog` |
| CLI installation/version evidence | `jarvis/runtime/cli_catalog.py` |
| Voice adapter/capability evidence | `jarvis/runtime/voice_capabilities.py::VoiceCapabilityRegistry` |
| Availability, stale/saved, metadata, pricing, role and key regressions | `tests/unit/test_catalog_view.py` |
| Cross-view stale routing and HTTP endpoint regressions | `tests/unit/test_routing_hook.py`, `tests/unit/test_settings_endpoints.py` |
| Field semantics, merge rules, integration boundary | `docs/catalog/view-model.md` |
| Shared search/filter/sort/compare rendering and accessible states | `jarvis/runtime/control_center_catalog.js`, `docs/catalog/table-component.md` |
| Production-module frontend regressions and five-state fixture | `tests/unit/test_control_center_catalog_ui.py` |

`CatalogViewService` and `/api/catalog` are read-only. They do not route work,
persist settings, install software, or accept model requests.

`JarvisCatalog` is also presentation-only. Agent/CLI and Voice choose columns
and role inputs while reusing the same filtering, comparison and rendering
path. Availability and action authority stay in the backend envelope.
