# Target Architecture

## 1. Canonical Settings registry

Introduce one canonical frontend registry for Settings navigation. It defines exactly six category IDs and allows feature modules to register sections under those categories.

Suggested stable category IDs:

- `voice_audio`
- `agents_models`
- `memory_knowledge`
- `interface_interactions`
- `connections`
- `advanced_diagnostics`

The user-facing French labels are presentation metadata; IDs remain ASCII and stable.

A section registration should minimally provide:

- stable `id`;
- destination `category`;
- label and optional description;
- order/group metadata;
- mount/render callback;
- cleanup/destroy callback when stateful;
- optional dirty-state/save policy;
- optional advanced badge or restart semantics;
- optional legacy tab aliases.

The registry must reject duplicate IDs and unknown categories. Feature modules may register sections; they may not add top-level categories.

## 2. Settings shell ownership

The shell owns:

- opening/closing Settings;
- six-category navigation;
- category landing/section navigation;
- focus management and keyboard escape behavior;
- controller cleanup on section/category changes;
- global dirty-state warnings when relevant;
- shared spacing, typography, cards, badges, notices and responsive rules;
- legacy tab alias normalization during migration.

Feature modules continue to own their business validation and data-loading behavior.

## 3. Data ownership stays where it is

The UI reorganization must not create shadow schemas.

- Voice fields remain server-described by the Voice settings schema/capability registries.
- Memory fields remain server-described by `memory_settings.py`.
- Agent/CLI values remain described by agent/routing/CLI metadata and model catalogs.
- Credentials remain in the credential store and never return secret values.
- Appearance/scene-view preferences remain localStorage/browser-owned where they already are.
- Bare Hands runtime/settings continue to use their existing contracts and bounds.
- Wake-word persistence and restart semantics remain in the wake-word settings contract.
- Sub-agent roles and Work Methods remain sourced from their canonical APIs/registries.

## 4. Separation of ordinary settings and operator tooling

`Avance & diagnostic` is structured into explicit groups rather than one long page:

- **Architecture & compatibility** - Voice architecture, compatibility stacks, orchestration invariants.
- **Prompts & instructions** - prompt workbench and advanced agent instruction editing where appropriate.
- **Runtime & CLI** - CLI command/path, permission mode, low-level routing configuration and probes.
- **Diagnostics** - Voice/wake/credential/model/runtime diagnostics and read-only state.
- **Labs & test tools** - scene test gate, Bare Hands benchmark/recording and other explicitly experimental operator tools.

## 5. Single canonical editable home

A persisted setting must not have two editable controls after migration. If another page needs context, it links to or deep-opens the canonical section.

The known example is `wake_toggle`: it is persisted in the shortcut registry, so its canonical editor becomes `Interface & interactions > Raccourcis`. Voice may show its effective key as read-only context and provide a link, but not a second editor.

## 6. Legacy compatibility

During rollout, supported old programmatic tab IDs must resolve to the new destination rather than fail silently. Compatibility is explicit and tested. The aliases are removed only when repository callers and durable docs no longer rely on them.

## 7. Controller lifecycle

Stateful modules such as model catalogs, sub-agent settings, memory views, wake-word settings and Bare Hands surfaces must expose or preserve destroy/cleanup semantics. The shell must not leave timers, in-flight requests, event handlers, or stale controllers alive when switching sections.
