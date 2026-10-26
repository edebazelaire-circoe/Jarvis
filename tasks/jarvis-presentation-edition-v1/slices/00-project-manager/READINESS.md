# Slice 00 — Readiness decision

- Date : 2026-10-26
- Agent 0 (orchestrateur), worktree `C:\Projects\jarvis\pev1`, branche `task/jarvis-presentation-edition-v1`
- `main` / `origin/main` audités : `2d6ca879afac7a0e773598cff0872b4f819fa876` (identique au SHA de création : aucune dérive)

## État : `READY`

Les Slices 01 à 04 (chemin critique d'architecture) sont dispatchables sans décision Human.
Deux entrées externes et trois portes de licence restent ouvertes ; elles sont bornées à
des Slices précis et ne bloquent pas le dispatch (voir « Entrées externes » et « Portes de release »).

## Méthode

Audit à l'aveugle (trois agents de lecture, questions neutres sans les conclusions du handoff),
puis comparaison avec le handoff. Vérifications ciblées par l'agent 0 (connecteurs CIRCOE, CI).

## Constats confirmés (le handoff est juste)

| Sujet | Preuve |
|---|---|
| `BoardKind` assistant/presentation/meeting ; `default` créé en assistant ; Meeting créable et rabattu sur assistant (`meeting_planned`) | `jarvis/domain/workspace_board.py:198-236`, `jarvis/core/board_service.py:298-317,405-431` |
| Aucune notion d'édition produit / entitlement | aucun module ; seule liste blanche = statut READY/PLANNED de `jarvis/domain/interaction_mode.py:151-258` |
| Entrées Board : `POST /v1/boards[/switch]`, relais `/api/boards[/switch]`, MCP `board_create(board_kind: Literal[...])` / `board_switch`, Tool Brain `board_switch`, `/v1/sessions/new`, restauration au démarrage | `protocol/server.py:226,231`, `runtime/board_routes.py:128-194`, `runtime/workspace_mcp.py:651-705`, `runtime/mcp_results.py:260`, `runtime/tool_brain_decider.py:160`, `core/session_manager.py:435-478`, `board_service.py:386-403` |
| Claude `bypassPermissions` par défaut, **sans `--tools` ni `--strict-mcp-config`** : Bash/Write/Edit + MCP personnels de l'utilisateur chargés | `runtime/agent_settings.py:20`, `runtime/claude_local.py:1247-1282,1627-1630` |
| Codex `danger-full-access` → `--dangerously-bypass-approvals-and-sandbox` | `agent_settings.py:16,40`, `runtime/codex_local.py:271-310` |
| Sous-agents Claude (`Agent`/`Task`) héritent des droits du parent ; jobs Back Brain et self-dev sans restriction | `routing_hook.py:1-23`, `back_brain_worker.py:59-71`, `self_dev.py:293-304` |
| Profils restreints existants réutilisables (`--tools`, `--strict-mcp-config`, `dontAsk`, liste Read/Glob/Grep/WebSearch/WebFetch) | `claude_local.py:379-437,1203-1239` |
| Racine de données par empreinte du dépôt + `JARVIS_DATA_ROOT` + adoption copie-d'abord de `./data` | `jarvis/data_root.py:38-190` |
| `CONTEXT_GLOBAL` sous la racine, injecté au prompt et en `--add-dir` ; protection = « jamais re-semé » seulement | `adapters/global_context.py:21-207`, `runtime/prompt_catalog.py:224` |
| Défenses chemin/jonction/reparse dans Board memory et Context workspace | `adapters/board_memory_store.py`, `adapters/context_workspace.py`, `safe_folders.py`, `safe_tree.py` |
| Remotion : `npm ci` verrouillé dans la racine, Node cherché sur PATH (≥ 20), pas installé | `adapters/node_capability_runner.py`, `domain/remotion_capability.py:29` |
| `setup.ps1` = bootstrap développeur (venv, `pip install -e`) ; aucun PyInstaller/MSIX/Inno | `setup.ps1`, `scripts/` |
| openWakeWord : modèles CC BY-NC-SA 4.0 (non commercial), téléchargés à la demande | `third_party/README.md`, `wakeword_model_catalog.py:12,47` |
| Secrets MCP scellés DPAPI | `adapters/dpapi_sealer.py`, `docs/SECURITY.md:400-416` |

## Écarts et découvertes (le handoff est amendé)

| # | Constat | Conséquence |
|---|---|---|
| E1 | **Aucun connecteur CIRCOE Mail** (ni Gmail, IMAP, SMTP, Graph). Le seul agenda est `adapters/google_calendar.py` (scope `calendar` complet). | D09 « garder CIRCOE Mail/Calendar » suppose un existant qui n'existe pas. Calendar = adaptateur Google Calendar sur le compte CIRCOE (hypothèse à confirmer). Mail = **nouvelle entrée externe** (fournisseur/protocole/auth), au même titre qu'IGuard, bornée au Slice 05. |
| E2 | Le **dossier runtime** (`JARVIS_RUNTIME_DIR`, défaut `./runtime`) est relatif au répertoire courant, donc au dépôt : `core.token`, `control-center-settings.json`, journaux `trace.jsonl`/`errors.jsonl`, modèles wake-word/locuteur. | Slice 02 couvre aussi le runtime, les journaux et la config, pas seulement `data`. Rien de canonique ni de secret sous Program Files. |
| E3 | **Clés API en clair** dans `runtime/control-center-settings.json` (+ `.env`) ; jetons Google OAuth en fichiers JSON désignés par `.env`. | Slice 05 : déplacer ces secrets vers le coffre DPAPI existant (ou équivalent) pour l'édition produit ; plus de `.env` en usage normal (Slice 07). |
| E4 | Le **cerveau est la CLI Claude Code** (et Codex en option) : ni le handoff ni D11 ne traitent sa fourniture, son épinglage, son authentification par un utilisateur non développeur, ni `--chrome` (Claude in Chrome). | Slice 06 : runtime CLI privé épinglé (ou décision documentée), Slice 07 : connexion du compte/clé fournisseur dans l'onboarding. Slice 04 : Codex non disponible en édition Presentation tant que son confinement n'est pas réel (recommandé). |
| E5 | **Rendu Remotion = Chrome/Edge installé** (jamais téléchargé). | Slice 06 : dépendance système acceptée (Edge présent sur Windows 10/11) ou navigateur privé ; diagnostic dans la matrice Slice 07. |
| E6 | **Licences** : Remotion « Remotion License (company licence may be required) » non évaluée ; FFmpeg de `imageio-ffmpeg` = GPLv3 ; Barehands et ai-visualizer = AGPL-3.0. | Portes de release (Slice 06/10), en plus d'openWakeWord. Recommandation : exclure Barehands/ai-visualizer du paquet Presentation. |
| E7 | `.github/workflows/ci.yml` **existe** (pytest Ubuntu 3.11-3.13 + `scripts/verify_release.py`) ; aucun artefact construit ; `ARTIFACT_INFO.json` périmé (0.1.0-rc1 contre 0.2.0). | Slice 10 étend la CI existante (job Windows + paquet) au lieu d'en créer une ; corrige `ARTIFACT_INFO.json`. |
| E8 | Aucun export PPTX ; PDF = images seulement ; aucune destination « Documents » ; fichiers livrés par flux du relais. | Slice 03 ne promet que les classes existantes (MP4, PNG, PDF image). PPTX hors V1 sauf décision. |
| E9 | Les réglages agents sont **globaux** (même mode de permission pour tous les Boards) ; pas de surcharge par profil. | Slice 04 : le profil produit doit être imposé par l'édition, non par un réglage modifiable dans l'UI. |
| E10 | `side_effect` des outils MCP distants (read/write/destructive) n'est contrôlé à aucun appel. | Slice 05 : politique produit sur les outils distants d'écriture/destructifs. |
| E11 | `docs/settings/INDEX.md:78` dit encore « Brains & Architecture » ; la catégorie s'appelle « Architecture & Agents ». | Non bloquant ; corrigé par Slice 08 s'il touche cette page, sinon Issue. |

## Tâches qui se recoupent (Drive au 2026-10-26)

| Tâche | File | Fichiers chauds | Effet |
|---|---|---|---|
| `refonte-ui-settings` (worktree `rui`, = main `2d6ca879`) | to-do (attend acceptation Human) | `control_center_settings_*`, `control_center.html` | Déjà dans main ; aucun conflit de code tant qu'elle ne bouge plus. Slices 07/08 rafraîchissent avant dispatch. |
| `jarvis-connections-services-mcp-settings-ui` | to-do, non démarrée | Réglages Plugins & MCP, statuts de connexion | Recoupe Slice 05 (statuts connecteurs) et 07. Slice 05 livre des contrats de données ; l'UI de réglages reste à cette tâche. |
| `jarvis-memory-knowledge-settings-ui` | to-do (absorbée par refonte S05/S06) | Mémoire & Connaissances | Aucun recoupement direct. |
| `jarvis-interactive-presentation-studio` | current (ancienne, mergée) | Studio | Aucun travail actif. |

## Task Types

Dispense globale du Human enregistrée le 2026-09-14 (`tasks/jarvis-settings-model-catalog-ux/slices/TODO.md:5`),
appliquée depuis par les tâches suivantes. Tous les `metadata.json` gardent `task_type: null` ; aucune valeur inventée.

## Entrées externes (ne bloquent pas le dispatch)

- **X1 IGuard** : transport, endpoint, auth, inventaire d'outils. Bloque seulement la partie IGuard du Slice 05.
- **X2 CIRCOE Mail** (nouveau, E1) : fournisseur et protocole (Google Workspace/Gmail ? Microsoft 365 ?), mode d'auth. Bloque seulement la partie Mail du Slice 05. Calendar : confirmer que le compte CIRCOE est un Google Workspace.

## Portes de release (bloquent Slice 10/11, pas le dispatch)

- openWakeWord non commercial → F9 / autre chemin d'éveil autorisé tant que non résolu.
- Licence entreprise Remotion à évaluer.
- FFmpeg GPLv3 (`imageio-ffmpeg`) : notices et conformité de redistribution, ou build LGPL.
- Barehands / ai-visualizer AGPL : exclus du paquet Presentation (recommandé).
- Distribution et authentification de la CLI Claude Code (E4) : conditions du fournisseur.
- Identité de signature du code et technologie d'installeur (Slices 06/10).

## Dispatch initial et chemin critique

Chemin critique inchangé : `01 → 02 → 03 → 04 → 06 → 07 → 10 → 11`.

- **Dispatch 1 : Slice 01** seule (un seul writer dans `pev1`, contrat d'édition dont dépendent 02, 04, 05, 08).
- Ensuite 02, puis 03 ; 05 et 08 peuvent partir dès 01 approuvée, chacun dans son propre worktree s'ils tournent en parallèle (≤ 3 agents, machine limitée).
- Contrôle de fraîcheur ciblé contre `origin/main` avant chaque dispatch.
