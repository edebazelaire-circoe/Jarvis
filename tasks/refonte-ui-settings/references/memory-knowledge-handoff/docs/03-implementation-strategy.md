# Implementation Strategy

## Dependency graph

`00 -> {01,02,03,04} -> 05 -> 06`

Slice numbering is for identification only, not a serial execution mandate.

## Initial ready set after READY

### 01 Memory preferences UI

Builds the normal-user Memory tab against current `/api/settings` memory schema/status.

### 02 Knowledge/loadouts UI

Builds source availability and editable loadout policy. It may use fixture/adapters matching existing `memory.loadouts` until shared wiring in Slice 05.

### 03 Memory Center UI

Refactors the dedicated workspace over existing `/api/memory/*` contracts.

### 04 Advanced memory diagnostics

Builds the Advanced destination for Tencent/raw timeout/index health/provenance without changing runtime semantics.

## Shared hot-file policy

Slices 01–04 should avoid all independently rewriting the same Settings shell or `control_center.html`. New modules/adapters are preferred. Slice 05 owns final wiring and legacy cleanup.

## Integration checkpoint

Slice 05 reconciles:

- navigation/tabs;
- one canonical editable home per setting;
- deep links from Memory Center and Advanced;
- existing legacy Memory tab mount compatibility;
- keyboard/accessibility behavior;
- restart notices and source availability.

## Migration

No persistence migration should be introduced unless Slice 00 finds a current-main contract requiring one. Existing `memory` and `memory.loadouts` keys remain canonical.
