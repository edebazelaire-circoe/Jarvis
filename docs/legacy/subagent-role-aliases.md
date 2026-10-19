# Rôles de sous-agent — l'alias `reviewer` et les deux rôles désactivés

**Introduit :** tâche `jarvis-organic-agent-orchestration`, Slice 01 (2026-10-20).
**Contrat :** [../subagent-roles.md](../subagent-roles.md).

## Reste n° 1 — l'alias `reviewer` -> `qa`

**Ce que c'est.** `subagent_roles.ROLE_ALIASES = {"reviewer": "qa"}`. Le marqueur `[reviewer]` se résout
en rôle `qa` (statut `alias`, marqueur gardé en provenance), et le hook continue de lire
`[code] [reviewer]` comme la clé de loadout `code:reviewer`.

**Pourquoi ce n'est pas un renommage.** `reviewer` est un rôle de loadout publié
(`memory_settings.LOADOUT_ROLES`) : des règles `memory.loadouts` enregistrées chez l'utilisateur
(`code:reviewer`, `general:reviewer`), des skills qui listent `reviewer` dans `allowed_profiles` et la règle
du prompt `PROFILE_RULE` (« ajoute [reviewer] ») l'emploient.

**Condition de retrait.** Quand `PROFILE_RULE` et les règles du cerveau enseignent `[qa]` (Slice 07), que
le loadout de `qa` est câblé (Slice 04), et qu'une migration des réglages a réécrit les clés de loadout
`*:reviewer` existantes. D'ici là l'alias reste, et `tests/unit/test_subagent_roles.py` le garde.

## Reste n° 2 — `research-lead` et `qa` définis mais désactivés

**Ce que c'est.** Les deux rôles additifs sont dans `ROLES` avec `enabled=False` : marqueur lu et résolu
(statut `disabled`), instructions éditables au catalogue des prompts, mais absents de `brain_rules` et sans
méthode apposée par le hook.

**Pourquoi.** La Slice 01 fixe le contrat (ids, visuel, capacités) sans changer le comportement vivant du
cerveau ; leur câblage appartient aux Slices 04 (méthode, loadout) et 07 (règles du cerveau).

**Condition de retrait.** Passer `enabled=True` dans la Slice qui les câble, avec ses tests, puis retirer
cette section.
