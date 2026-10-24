# 02 — UI architecture

## Boundary

This task sits on top of the existing Settings registry/controllers/runtime APIs. It changes presentation and view composition; it does not create new sources of truth.

## Layering

1. **Settings shell / routing** — existing category and page routing remains authoritative.
2. **Shared visual system** — reusable tokens/components for glass panels, neon borders, section headers, tabs, stat cards, switches, sliders, tables, badges and floating panels.
3. **Page composition** — each target view owns its layout and maps existing view-model/controller state into the shared visual primitives.
4. **Runtime/data adapters** — existing APIs/controllers continue to supply live values and mutations.
5. **Visual regression harness** — deterministic fixtures/states make screenshot comparison possible without hard-coding production values.

## Shared visual primitives to establish/reuse

- settings page header + breadcrumb + close control;
- optional avatar/profile control;
- segmented/tabs navigation;
- `GlassPanel` / section card;
- icon medallion;
- metric/stat tile;
- labeled row with trailing control;
- status dot/badge;
- neon button variants;
- slider + value presentation;
- toggle switch;
- select/dropdown;
- textarea/instruction field;
- dense table/list shell;
- floating/draggable configuration panel;
- graph node/edge style tokens;
- responsive grid utilities.

Names above are conceptual, not mandatory component names. Reuse the repository's actual component/CSS conventions after the Slice 00 audit.

## State contract

Every visually redesigned control must keep the existing state model:

- loading;
- loaded;
- empty/no data;
- disabled/unavailable;
- validation error;
- network/runtime error;
- optimistic update or pending state where already supported.

Do not style only the happy-path screenshot.
