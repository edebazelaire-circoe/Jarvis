# Slice 00 — Readiness (agent 0, 2026-10-14)

## Verdict : `READY`

Base : `origin/main` 664d767b (le même SHA que celui du handoff), branche `task/jarvis-unified-chat-and-board-drop`, worktree `C:/Projects/jarvis/bucd`. Contrat contraignant : `../../docs/06-resolved-architecture.md`.

## Déclaré par le handoff

Statut `planned`, rien d'implémenté, 11 Slices, Task Type non résolu, sept checks HV. La lecture statique du handoff a été faite sur le même SHA que la base.

## Audit aveugle

Fait le 2026-10-14 à 664d767b par un agent Explore, sans lire ce dossier de tâche. Constats indépendants qui modifient le plan :

1. **Aucun état « voix active » côté serveur.** Seul le processus Voice le connaît (`VoiceLifecycleState`, fichiers `runtime/.voice_*`), et Core ne peut pas refuser un envoi sur cette base. → D-VOICE : un état en mémoire, possédé par Core et nourri par des rapports de Voice ; la Slice 04 passe avant la 03.
2. **Chaque résultat Brain part aussi en `brain.speech.requested`.** Il n'existe aucune disposition de sortie par tour, et `BrainTurnSource.TEXT` existe mais n'est utilisé nulle part. → D-NOTTS.
3. **`/api/agent/send` et `/api/agent/ask` contournent les événements canoniques.** L'entrée correcte est `POST /v1/conversations/{id}/brain-turns`, qu'aucun relais du Control Center n'expose aujourd'hui. → D-INGRESS.
4. **Pièces jointes :**
   - aucune route de téléversement n'existe ;
   - le CLI refuse `images=` hors `speculative_analysis` ;
   - le corps d'une requête au Control Center est borné à 1 Mio ;
   - aucune nature d'Artifact ne convient, mais il n'y a pas de `CHECK` SQL, donc pas de migration.
   → D-ATT : les fichiers passent par chemin et `--add-dir`.
5. **Les toasts occupent déjà le coin bas droit**, et le dock est centré à droite. → D-UI.
6. **Les tours `uncertain` émettent aussi `user.transcript.accepted`.** → Ils sont promus seulement quand un message Brain de même corrélation existe, comme le fait `_derive_state`.
7. **Branche concurrente non fusionnée :** `task/transcription-tab-live-refresh` modifie `control_center_timeline.js` et son test d'interface. → Le chat ne touche pas ces fichiers.
8. **Schéma :** `jarvis.sqlite3` est à v8 et `scene.sqlite3` à v1. Le plan vise zéro migration.
9. **Vocabulaire Workspace Task Type :** absent du dépôt.

## Réconciliation avec le handoff

Les niveaux documentaires du handoff sont confirmés, sauf deux :

- la disponibilité Voice/Chat est **L0**, sans propriétaire serveur ;
- la disposition « pas de TTS » est **L0**.

Les révisions sont dans `../../docs/05-documentation-levels.md`. Les 14 écarts entre le handoff et le dépôt sont dans `06-resolved-architecture.md` § « Écarts ».

## Décisions prises par l'agent 0 (autonomie déléguée par l'Humain)

- **D-TT : Task Type levé**, avec la valeur `waived-by-agent-0`, comme sur les handoffs précédents. Chaque Slice a un Work Agent unique.
- **Ordre révisé :** 01 → (02 ∥ 04) → 03 → 05 → 06 → 07 → 07b → 08 → 09 → 10.
- **Découpage :** la Slice 07 est scindée en 07 (backend critique) et 07b (interface).
- **Paliers QA :** les Slices critiques sont 03, 04 et 07, avec au plus 10 mutants chacune ; toutes les autres sont au palier standard.
- **Limite des 8192 caractères :** une réponse Brain plus longue n'est pas enregistrée dans les événements, donc pas affichée au chat. Atténuée par le brief et un état honnête dans l'interface, mais pas levée ici. L'Issue est déposée dans `../../Issues/`.

## Baseline de tests

Mesure en cours à 664d767b, dans le worktree détaché `C:/Projects/jarvis/bucq`, sur `tests/unit` puis `tests/integration`, par lots en avant-plan. Les échecs hérités seront listés ici avant le premier dispatch d'une Slice de code (02 ou 04). La Slice 01 est documentaire et n'en dépend pas.

## Checks humains

HV-JCHAT-00-01 n'est pas déclenché : aucun conflit durable, aucun contrat impossible à déterminer depuis le code.

Le déplacement Drive `to-do` → `current` est demandé à l'Humain, faute d'outil de déplacement.
