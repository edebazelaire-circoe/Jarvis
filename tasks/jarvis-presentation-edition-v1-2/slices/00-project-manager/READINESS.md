# Slice 00 — Verdict de préparation (agent 0, 2026-10-27)

**État : `READY`.** Trois décisions Human sont consignées ; elles ne bloquent pas l'implémentation, seulement les affirmations de livraison (voir « Décisions Human »).

## Base
- `origin/main` = `2d6ca879` (inchangé depuis la création de la tâche).
- Branche `task/jarvis-presentation-edition-v1-2`, worktree `pev12`, partie de la branche de la tâche parente `task/jarvis-presentation-edition-v1` @ `75921f58` (Slices V1 00-09 approuvées, S10 en reprise dans `pev1`, S11 restante). La V1.2 amende la V1 non fusionnée : elle ne peut pas partir de `main` sans réécrire la V1.
- La branche parente sera fusionnée dans celle-ci après l'approbation de la S10 V1, avant toute Slice qui touche ses fichiers (07, 08).
- Repli du cycle de vie : `docs/workflows/AGENT_TASK_LIFECYCLE.md` est absent ; identifiants Drive et branche de base pris dans la mémoire du projet.
- Task Type : `waived-by-agent-0` pour toutes les Slices (précédents `jarvis-organic-agent-orchestration`, `jarvis-settings-ui-reorganization`, `jarvis-architecture-agents-settings-editor`).

## Audit à l'aveugle — constats (références dans le LOG, entrée S0)
1. **Périmètre du cerveau.** Le confinement de la V1 (S04 V1) est réel et appliqué par la CLI : manifeste `jarvis/domain/agent_capabilities.py`, drapeaux `--tools/--allowedTools/--disallowedTools`, prompts dérivés, docs `product-capabilities.md`, `product-connectors.md` au niveau 3. Écarts : un marqueur `[coder]` forgé n'est pas refusé par `routing_hook.py` (seuls les outils manquent au sous-agent) ; `SubagentRole.tools` est descriptif et contredit l'édition (`qa` déclare Bash) ; le prompt confiné affirme que `replace` exige `expected_sha256` alors que Core ne l'impose pas ; le prompt Presentation ne décrit pas le rôle « projet » (recherche, entretien, organisation).
2. **Continuité de projet.** `summary.md` (2 Kio, chaque tour) et `context_summary` (1 500 caractères, chaque tour) existent ; aucun schéma ni règle de mise à jour/reprise.
3. **Recherche.** Rôles `research`/`web-research`/`research-lead`, méthodes `quick/deep/comparative-research` (v1), relations : tout existe. Aucune politique de réutilisation/fraîcheur ; le cas B lance documentaire et web en parallèle. Lacune : une méthode intégrée modifiée sans changer de version change en silence.
4. **Documents de recherche.** Aucune convention `memory/documents/` ; les apports vivent dans `missions/*/mission.md` et `notes/`.
5. **Voix.** Trois machines d'état (processus Voice background/active, canal Core, états affichés). **Ni état OFF ni préférence persistée** : « Passer au chat » est un mute en mémoire. Le lanceur démarre Voice par défaut ; sans clé du fournisseur, Voice plante trois fois puis est abandonnée. **Le paquet presentation n'embarque aucun moteur de mot de réveil** (modèles openWakeWord CC-BY-NC-SA, Porcupine sous conditions commerciales) : réveil par F9 seulement. La page « Mot d'éveil » reste visible sans moteur.
6. **Réglages.** Les pages voix/transcription ne sont pas masquées (bon) ; `agents_models` et `advanced_diagnostics` sont masquées en presentation par `surface:'developer'` — à rendre accessibles autrement (mode support) selon la décision du 2026-10-26 « Full Settings retained ». Aucun interrupteur de voix dans l'interface.
7. **Diagnostic.** `support_bundle.py` (S10 V1, en reprise) : CLI seulement, masquage solide, pas de base SQLite, pas de mémoire de Board, pas de rapport IA, pas de bouton, pas d'envoi.
8. **Plateformes.** Chemins centralisés (`installation.py`, `data_root.py`, `known_folders.py`) ; ~25 sites `windll`, 22 `winreg`, 23 `taskkill`, Job Objects, DPAPI, `csc`, runtimes `.exe` codés en dur ; `build_package.py` et la CI sont Windows uniquement ; la CI n'a jamais tourné sur GitHub.

## Réconciliation avec la tâche parente V1
| V1.2 | Recoupement V1 | Décision |
|---|---|---|
| 01 | S04 V1 (confinement, approuvée) | **Amende** S04 V1 : pas de seconde politique ; corrige les quatre écarts ci-dessus et ajoute le rôle « projet » au prompt. |
| 02-04 | aucun | Nouveau travail, sur la mémoire de Board existante. |
| 05 | S07 V1 (lanceur, approuvée) | Amende le lanceur : démarrage de Voice conditionné à la préférence et à la clé, état dégradé visible. |
| 06 | S08 V1 (UI des types indisponibles, approuvée) ; `refonte-ui-settings` (déjà dans `main` `2d6ca879`, donc dans cette branche) | **Amende** la décision V1 de masquer `agents_models`/`advanced_diagnostics` : accès par un mode support, pas suppression. |
| 07 | S10 V1 (`support_bundle.py`, en reprise) | **Étend** le service S10 ; ne démarre qu'après approbation S10 et fusion de la branche parente. |
| 08 | S06/S07/S10 V1 (paquet, installeur, CI Windows) | Démarre après la fusion de la branche parente ; adaptateurs, pas de branche Mac. |
| 09 | S11 V1 (acceptation Windows) | 09 V1.2 et S11 V1 seront menées ensemble sur le même candidat, si le calendrier le permet. |

Tâches dans la file to-do qui recoupent : `jarvis-connections-services-mcp-settings-ui` et `jarvis-memory-knowledge-settings-ui` (non démarrées ; la seconde est absorbée par `refonte-ui-settings` I-001). Fichiers chauds partagés avec 06 : `control_center_settings_registry.js`, `control_center.html`. Aucun travail concurrent en cours sur ces fichiers.

## Amendements des Slices
- **01** : réduite au delta ci-dessus (refus dur des rôles non offerts dans le hook, outils de rôle adaptés à l'édition, alignement prompt/serveur de `expected_sha256` — l'exiger côté serveur pour `replace` si aucun appelant de `full` ne casse, sinon corriger le prompt —, prompt du rôle « projet Presentation », codes de refus stables). Trace réelle du cerveau exigée, budget ≤ 1,50 $.
- **05** : « Sleep, mot de réveil armé » = Voice en `background` avec le réveil disponible (F9 ; voix si un moteur licencié est configuré). Ajoute une préférence persistée Off, un Voice non démarré quand Off ou sans clé (état dégradé visible au lieu de la boucle de plantages), un interrupteur dans l'interface, une page « Mot d'éveil » consciente de l'édition.
- **06** : ajoute l'accès « support » aux catégories `agents_models`/`advanced_diagnostics` sans le mode développeur complet.
- **07** : envoi automatique seulement vers une destination configurée ; sans destination, enregistrement manuel. Le rapport IA ne voit que des preuves masquées.
- **08** : périmètre réduit faute de Mac et d'identifiants : adaptateurs de plateforme, carte des chemins macOS testée, job CI macOS écrit (exécution dès que le Human pousse), plan de paquet macOS ; **aucune affirmation de support macOS**.

## Décisions Human (non bloquantes pour l'implémentation)
- **HD-V12-01 Mot de réveil livrable** : clé commerciale Porcupine, modèle entraîné sous licence, ou F9 seul en V1.2.
- **HD-V12-02 Destination des rapports de support** : adresse/canal à configurer ; d'ici là, enregistrement manuel.
- **HD-V12-03 macOS** : accès à un Mac réel et identifiants de signature/notarisation ; push de la branche pour exécuter la CI.
- Externe déjà connu : contrat IGuard (`contract_pending`).

## Premier envoi
- **01** maintenant (pas de fichier commun avec la reprise S10 V1).
- Puis 02 → 03 → 04 en série ; 05 en parallèle de 02 si la limite de trois agents le permet ; 06 après 05 ; 07 et 08 après la fusion de la branche parente approuvée.
