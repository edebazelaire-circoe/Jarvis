# I-002 — Page Personnalisation non commitée dans le checkout principal

**Statut :** résolu par agent 0 (reprise comme base de la Slice 02).

Le checkout `C:/Projects/jarvis/jarvis` porte depuis le 2026-10-23 une page Personnalisation non commitée
(`control_center_personalization.js`, `personalization_profiles.py`, `docs/settings/personalization-page.md`,
retouches de `control_center.html/.py`, `agent_behavior.py`, `agenda_reminders.py`, tests). Elle vise déjà la
maquette `01-personnalisation.png` (profils, instructions, préférences rapides). Base identique (`be80ab9b`).

Décision : ce travail est recopié tel quel sur la branche de tâche (commit `S2: base …`), sans toucher au checkout
principal, avant la Slice 01 pour que la fondation consolide aussi les classes `.perso-*`.
Conséquence Human : au merge dans main, les fichiers non commités du checkout principal devront être écartés
(ils sont identiques à la base commitée ; une copie existe aussi au scratchpad `personalization-wip-backup`).
