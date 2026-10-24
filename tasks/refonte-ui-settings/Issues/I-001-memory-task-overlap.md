# I-001 — Slices 05/06 recouvrent la tâche jarvis-memory-knowledge-settings-ui

**Statut :** ouvert, décision d'agent 0 différée au moment de dispatcher 05/06.

La tâche `jarvis-memory-knowledge-settings-ui` (Drive to-do `1zbm7LIAcylvc6m4WSuYSu3RZtd6akKsg`, worktree `memk`,
arrêtée en Slice 00 le 2026-10-24) a pour Slices 01 (préférences mémoire), 03 (Memory Center) et 05 (onglets
Mémoire / Connaissances / Memory Center, Memory Center rapatrié dans les Réglages) exactement les vues des maquettes
`04-memory-settings.png` et `05-memory-center.png`. Son README dit : « The user will attach final visuals
separately » — ce sont ces deux maquettes.

Sur main : pas d'onglets mémoire (5 sections plates `MEMORY_SECTIONS`), Memory Center monté hors Réglages
(`#memoryCenterMount`, fenêtre Sessions & Boards). Mener les deux tâches en parallèle = mêmes fichiers, conflits sûrs.

Décision : 01→04 avancent. Au moment de 05/06, agent 0 vérifie l'état de la tâche mémoire :
- si elle a fusionné ses Slices 01/03/05 → 05/06 deviennent une passe de conformité visuelle sur cette base ;
- si elle n'a pas avancé → 05/06 implémentent la composition visuelle en reprenant ses contrats (README « Locked
  product decisions ») sans dupliquer API ni persistance, et la tâche mémoire est signalée au Human comme recoupée.

## Décision (2026-10-24, sur ordre du Human : « lance la fin de la memory page … en prenant en compte CES visuels »)

La tâche mémoire n'ayant pas avancé, les Slices 05 et 06 sont lancées maintenant, sur la branche
`task/refonte-ui-settings-mem` (worktree `rmem`, depuis `58b38817`), en parallèle de la Slice 01. Elles portent
aussi la partie de la tâche `jarvis-memory-knowledge-settings-ui` qui touche ces deux vues (S01 préférences mémoire,
S03 Memory Center, S05 onglets + Memory Center rapatrié dans les Réglages), en respectant ses « Locked product
decisions » (copie : `references/memory-knowledge-handoff/`). Hors champ ici : éditeur de loadouts (S02), page
Avancé & diagnostic détaillée (S04) — lien seulement. Les maquettes 04 et 05 complètent les explications manquantes.
Convergence avec la fondation S01 : fusion dans `task/refonte-ui-settings` puis adaptation aux primitives partagées.
