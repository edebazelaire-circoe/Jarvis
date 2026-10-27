# Target architecture

## 1. Product capability boundary
Presentation Edition has one capability policy consumed by prompt/routing/tool exposure and hard enforcement. It permits research/document/connectors/Presentation production while refusing generic development and Jarvis-repository mutation.

Presentation Remotion/prefab authoring is a named bounded capability, not an exception that silently restores Bash/general Write permissions.

## 2. Project continuity
The Board stays the durable owner. No new project table.

Recommended Board memory convention:
```text
memory/
  summary.md                 # automatically hydrated project digest
  documents/
    research/
      <topic>.md             # durable research/source documents
    ...                      # other project documents
  missions/                  # existing organic-agent mission dossiers
```

`summary.md` should remain compact and current. Presentation Edition gives it stable semantic sections such as Finalité, Objectifs, État actuel, Décisions, Questions ouvertes, Prochaines étapes, Documents clés. The exact formatting may evolve, but the brain must be able to resume from it deterministically.

## 3. Research flow
```text
User turn / Interview
        |
        v
Research need detected
        |
        +--> inspect Board memory + Dossier + global knowledge + approved shared sources
        |
        +--> freshness/relevance decision
              | fresh -> reuse
              | partial -> targeted refresh
              | stale/missing -> Research Lead mission
                                      |
                                      +--> documentary agents
                                      +--> web agents
                                      +--> adversary/QA/communication as useful
                                      +--> background completion
                                              |
                                              v
                                 durable Board research document
                                              |
                                              +--> Dossier / later Presentation source
```

The main brain keeps conversing while background agents work. Existing Board-agent/background-work rules remain the runtime owner.

## 4. Research-document ownership
Research outputs are revisable project knowledge, so Board memory/Dossier is the default owner. Registry Artifacts remain evidence/capture objects under the current closed-kind contract. If immutable research snapshots later become a requirement, add a dedicated contract rather than overloading `derived` or inventing an unreviewed `document` kind.

## 5. Voice lifecycle
Application process lifecycle and voice lifecycle are distinct:
- App closed: Core/Control Center/Voice/children stopped.
- App open + Voice Off: no microphone/wake listener; chat available.
- App open + Voice Sleep: wake listener armed; normal idle state.
- App open + Voice Active: active voice session/listening according to the existing interaction-mode contract.

A chat submission does not silently change voice state.

## 6. Settings/UI
Settings remain a complete engineering/support surface. The normal product shell uses progressive disclosure: novice users see the project/presentation path first; advanced/diagnostic controls remain reachable in Settings.

## 7. Diagnostic bundle
A support-report service owns collection, redaction/exclusion, manifesting, ZIP creation and send/fallback. It reads only under the resolved Jarvis data/config roots. It never packages credential vault material, raw bearer tokens or secret-store blobs.

The bundle contains, as available: build/version/platform manifest, health report, recent errors/trace, relevant state databases, Board memory/project documents, sanitized settings/config, crash context and an AI-authored `report.md` grounded in collected diagnostics. Large caches/private runtimes may be omitted with an explicit manifest entry.

## 8. Platform paths
One platform-path service maps logical roots:
- internal application data;
- export root;
- caches/private runtimes;
- logs/diagnostics.

Windows target: `%LOCALAPPDATA%/CIRCOE/Jarvis` + `%USERPROFILE%/Documents/Jarvis` exports.
macOS target: `~/Library/Application Support/CIRCOE/Jarvis` + `~/Documents/Jarvis` exports, with mac-specific cache/runtime locations if justified by packaging.

Do not encode these paths ad hoc across Presentation, Voice, diagnostics and packaging.