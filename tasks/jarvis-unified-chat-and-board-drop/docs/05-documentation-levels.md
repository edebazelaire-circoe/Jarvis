# 05 — Niveaux de documentation par concept

Échelle : L0 implicite, L1 nommé, L2 contrat normatif, L3 implémentation/validateur/tests de conformité. **Niveaux initiaux issus d'une lecture statique (2026-10-14, HEAD 664d767) ; Slice 00 les audite indépendamment et peut les réviser.**

| Concept | Initial estimé | Objectif | Source canonique et propriétaire | Slice |
| --- | --- | --- | --- | --- |
| Événements de conversation + transcript debug | L3 | L3 réutilisé sans duplication | `docs/conversation-events.md`, `jarvis/domain/conversation_events.py`, `conversation_transcript.py` | 01–02,05 |
| Session, Board, binding Brain | L3 | L3 respecté et tests canaux | `docs/boards.md`, `docs/session-context.md`, `jarvis/core/session_manager.py` | 01,03–04,09 |
| Admission de tour depuis UI textuelle | L1 (BrainTurn existe), contrat text-only incertain | L2 avant code puis L3 | `jarvis/domain/v2.py`, `jarvis/core/brain_service.py`, `docs/conversation-events.md` | **01 prérequis**,03 |
| Projection simple « utilisateur + Brain » | L0 spécifique chat ; types existants L3 | L2 filtre puis L3 tests | nouveau chapitre `docs/conversation-events.md` et module de projection | **01 prérequis**,02,05 |
| Disponibilité Voice vs Chat | L0 spécifique chat ; interaction-mode L3 mais autre axe | L2 machine d'état puis L3 contrôle | `docs/interaction-mode.md` (distinguer), runtime Voice/Control Center | **01 prérequis**,04 |
| UI panneau chat | L0 | L2 comportement puis L3 composant/tests | `jarvis/runtime/control_center.html` et JS dédié | 01,06 |
| Artifact payload, Board links | L3 | L3 réutilisé/conformité | `docs/artifacts.md`, `docs/boards.md` | 01,07–08 |
| Passage sécurisé d'attachments au Brain | L0/L1 (à vérifier) | L2 contrat de références et droits avant L3 | `docs/artifacts.md`, `docs/session-context.md`, `jarvis/core/artifact_service.py` | **01 prérequis**,07 |
| Dépôt URL/fichier/image sur scène Board | L0 | L2 semantics/ACL puis L3 UI+API tests | `docs/artifacts.md`, `docs/scene-model.md`, `docs/boards.md` | **01 prérequis**,08 |
| Migrations DB/data root | L3 | L3 invariant | `CLAUDE.md`, `docs/local-data.md`, `tests/unit/test_schema_migrations.py` | toutes si schéma |

Aucun concept L0/L1 sans contrat clair ne doit partir en réalisation behavior-heavy. Si le contrat ne peut être tranché à partir du code, PM passe `HUMAN_DECISION_REQUIRED` (une question ciblée) au lieu d'inventer une réponse.
