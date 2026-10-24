# Target Architecture

## Existing ownership boundaries

### Domain/settings

`jarvis/domain/memory_settings.py` owns Memory settings vocabulary and loadout rule structure.

### Runtime settings

`jarvis/runtime/memory_settings.py` owns validation, effective/stored values, environment precedence, compatibility downgrades and schema description.

### Memory runtime

`jarvis/core/memory_wiring.py`, `memory_hybrid.py` and the adapters own lexical/semantic/Tencent runtime composition.

### Loadouts

`jarvis/core/loadout_resolver.py` owns effective agent knowledge visibility. UI must edit policy, not reproduce resolution logic.

### Memory Center

`jarvis/runtime/control_center_memory.js` consumes `/api/memory/*`. Candidate decision is the only owner write in that workspace.

## Target UI modules

Prefer separate UI ownership before convergence:

- memory preference surface;
- knowledge/loadout surface;
- Memory Center surface;
- Advanced memory diagnostics surface.

Shared top-level navigation/mount wiring is deferred to Slice 05 to reduce parallel hot-file collisions.

## Data truth rules

- server schema owns ranges/options;
- runtime status owns availability;
- settings state owns requested preference;
- loadout resolver owns effective agent access;
- canonical note APIs own note content and metadata;
- UI never infers unavailable providers as active.

## Restart semantics

Semantic/Tencent settings that only apply at Core restart must retain truthful restart-required messaging. Recall budgets and knowledge toggles that apply next turn should not be presented as restart-required.
