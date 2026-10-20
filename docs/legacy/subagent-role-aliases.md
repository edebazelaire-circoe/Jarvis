# Rôles de sous-agent — l'alias `reviewer` (et les deux rôles désactivés, retirés)

**Introduit :** tâche `jarvis-organic-agent-orchestration`, Slice 01 (2026-10-20).
**Contrat :** [../subagent-roles.md](../subagent-roles.md).

## Reste n° 1 — l'alias `reviewer` -> `qa`

**Ce que c'est.** `subagent_roles.ROLE_ALIASES = {"reviewer": "qa"}`. Le marqueur `[reviewer]` se résout
en rôle `qa` (statut `alias`, marqueur gardé en provenance), et le hook continue de lire
`[code] [reviewer]` comme la clé de loadout `code:reviewer`. Depuis la Slice 04, `qa` est actif : `[reviewer]`
reçoit aussi la méthode du Contrôle qualité (instructions `subagent_role.qa`, capacités, Work Method
`result-review`), et `role_for("reviewer")` rend le rôle `qa`.

**Pourquoi ce n'est pas un renommage.** `reviewer` est un rôle de loadout publié
(`memory_settings.LOADOUT_ROLES`) : des règles `memory.loadouts` enregistrées chez l'utilisateur
(`code:reviewer`, `general:reviewer`), des skills qui listent `reviewer` dans `allowed_profiles` et la règle
du prompt `PROFILE_RULE` (« ajoute [reviewer] ») l'emploient.

**Condition de retrait.** Première moitié remplie par la Slice 07 : `PROFILE_RULE` et les règles du
cerveau enseignent `[qa]`, plus `[reviewer]` (`tests/unit/test_int_role_markers.py`). Reste : une migration
des réglages qui réécrit les clés de loadout `*:reviewer` existantes et les `allowed_profiles` des skills (le
loadout de `qa` est câblé depuis la Slice 04 : `qa` -> `reviewer`), puis le retrait de l'alias et du rôle de
loadout. D'ici là l'alias reste lu (un sous-agent ou une ancienne conversation peut encore l'écrire), et
`tests/unit/test_subagent_roles.py` le garde.

## Reste n° 2 — `research-lead` et `qa` définis mais désactivés (retiré par la Slice 04)

**Retiré le 2026-10-20 (Slice 04).** Les deux rôles sont actifs (`enabled=True`) : annoncés au hook, méthode
apposée, loadout câblé. Ils ne sont pas encore proposés au cerveau (`offered_to_brain=False`) : c'est un
drapeau de contrat, pas un reste de compatibilité, et la Slice 07 le lève avec la règle du cerveau. Le texte
ci-dessous décrit l'état d'avant, gardé pour l'historique.

**Ce que c'était.** Les deux rôles additifs sont dans `ROLES` avec `enabled=False` : instructions éditables au
catalogue des prompts, mais absents de `brain_rules`, sans méthode apposée par le hook, et absents de
`agent_markers.ANNOUNCED_ROLES`. Leur marqueur n'est donc ni consommé ni retiré du libellé, ne masque pas le
rôle ni le loadout de la consigne : `[code] [qa] …` se lit exactement comme avant leur définition. Seul
`resolve_role` direct rend le statut `disabled`.

**Pourquoi.** La Slice 01 fixe le contrat (ids, visuel, capacités) sans changer le comportement vivant du
cerveau ; leur câblage appartient aux Slices 04 (méthode, loadout) et 07 (règles du cerveau).

**Condition de retrait.** Passer `enabled=True` dans la Slice qui les câble, avec ses tests, puis retirer
cette section.
