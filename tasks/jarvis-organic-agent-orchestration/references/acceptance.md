# Critères d'acceptation — preuves (Slice 13, 2026-10-21)

Chaque critère du `README.md` est mis en face de sa preuve. « Tenu » veut dire prouvé par des tests et un essai
réel en bac à sable ; « à valider » renvoie au check humain qui le tranche (`HUMAN-CHECKS.md`). Aucun check humain
n'est passé.

| # | Critère | Preuve | Statut |
|---|---|---|---|
| 1 | Une correction simple tourne comme un seul agent éphémère sans étoile durable | Slice 07 (règle A, éphémère élargie I-004), Slice 08 (aucune ligne de scène tant que `WorkItem.ephemeral`, clôture fusionnée sans étoile), Slice 03 (aucune ligne d'historique) ; essais réels S07 (b), S08 r3 ; `test_scene_role_relations`, `test_mission_history_merged_closure` | Tenu ; HV-ORG-08-02, HV-ORG-05-01 |
| 2 | Une mission complexe grandit en sous-missions possédées localement, sans workflow déclaré | Slice 05 (`[mission]`, parent = mission de l'appelant, propriétaire local, aucun nœud planifié) ; essais S05 (équipe à 3 niveaux), S09 | Tenu ; HV-ORG-13-01, HV-ORG-13-03 |
| 3 | Rôles explicites, immuables par instance, identité visuelle, loadouts/outils | Slice 01 (contrats, triggers d'immuabilité S03), Slice 04 (loadouts, capacités, `can_spawn` mécanique S05), Slices 09/10 (pastilles, onglet Sous-agents) | Tenu ; HV-ORG-09-01, HV-ORG-10-01/02 |
| 4 | Mission Owner récursif, visible, jamais un faux rôle | Slice 01 (statut d'instance), Slice 05 (bloc RESPONSABILITÉ DE MISSION), Slice 08 (`role_ref.mission_owner` = propriétaire courant), Slice 09 (drapeau) | Tenu ; HV-ORG-13-03 |
| 5 | Délégation, Communication, Adversary, QA, Handoff typés avec une sémantique réelle | Slice 02 (contrats), Slice 06 (outils `relation_*`, relais atomique), essais S06/S07/S09 | Tenu ; HV-ORG-06-01..03 |
| 6 | Adversary entre plusieurs producteurs pairs ; QA asymétrique | Slice 02 (positions disjointes, `qa_reviewer_role`), Slice 06 (verdict réservé au relecteur), Slice 07 (consignes distinctes par producteur) ; essais à 3 producteurs (QA S06, S08, S09) | Tenu ; HV-ORG-06-01/02, HV-ORG-09-02 |
| 7 | Tableaux de communication cliquables, sans raisonnement privé | Slice 02/06 (refus des balises et clés privées, lecture restreinte), Slice 09 (pastille-bouton, tableau en lecture seule, clavier), Slice 13 (journal `agent.event` sans texte des relations) | Tenu ; HV-ORG-06-03, HV-ORG-09-03 |
| 8 | Work State reste la vérité vivante ; l'historique ne la contredit pas | Slice 03 (aucune colonne de statut d'exécution, `live_status` jamais deviné, `role_mismatch` signalé), Slice 05 (`live_unknown` dérivé, jamais persisté) | Tenu |
| 9 | La constellation montre l'exécution réelle non éphémère, rôles et relations distingués | Slice 08 (projection depuis `mission_view` seulement, aucun nœud futur), Slice 09 (rendu des cinq relations) | Tenu ; HV-ORG-09-02, HV-ORG-09-04 |
| 10 | Après la fin, l'historique non éphémère reste inspectable ; l'éphémère non | Slices 03/08 ; essais S08 (redémarrage de Core sans statut inventé) ; héritage : étoiles éphémères déjà persistées par la v1 conservées (rien ne permet de les reconnaître), rangées par l'archivage | Tenu avec écart (héritage v1) ; HV-ORG-08-01/02, HV-ORG-13-02 |
| 11 | L'Intervieweur cadre une création floue pendant que la recherche avance ; une tâche claire n'a pas d'interview obligatoire | Slice 07 (cas B échelonné, porte unique `EXECUTION_GATE_RULE`) ; essais sonnet | Tenu avec écarts oraux (longueur des relais de sonnet) ; HV-ORG-07-01/02 |
| 12 | Les Mission Owners jugent les preuves et déclenchent recherche, second regard, QA, Adversary ou relais | Slice 05 (bloc Mission Owner), Slice 06 (`relations_brief`), Slice 07 ; limite connue : un Mission Owner qui fait relire son propre travail ne crée pas toujours de relation QA | Tenu avec écart ; HV-ORG-13-01 |
| 13 | Rapports/comparaisons sérieux sur un prefab soigné ; résultats simples sans artefact lourd | Slice 11 (règle de jugement sur le résultat, repli honnête), Slice 07 (restitution) ; essais 3/3 rapports affichés, 0 artefact pour les demandes simples | Tenu ; HV-ORG-11-01/02, HV-ORG-13-04 |
| 14 | Migration, redémarrage/réconciliation, fournisseur dégradé, compatibilité `coder/reviewer/research`, confidentialité testés | v10 (S03), v11 (S12), scene v2 (S08) répétées sur copie de la base vivante ; équivalence des marqueurs (157 927 cas) ; alias `reviewer` ; mode dégradé ; `docs/OPERATIONS.md` (mise en service, retour arrière) | Tenu |
| 15 | QA indépendante et validation humaine passées | QA indépendante passée pour chaque Slice 00-12 ; Slice 13 : QA à faire ; checks humains : tous `pending` | À valider : QA S13 + `HUMAN-CHECKS.md` |

## Échecs de tests préexistants (présents sur `main` 3351ef59, hors de cette tâche)

`test_brain_capability_parity` (ui_intent_publish), `test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`,
`test_control_center_mcp_api.py` (6), `test_control_center_shell_browser` (5, Boards), `test_scene_group_drag_js::test_the_page_commits_a_group_drag…`,
`test_tool_brain_choices::test_ui_projection_is_consistent_in_the_single_metadata_copy`,
`test_control_center_voice_architecture::test_async_browser_render_does_not_restore_a_previous_panel`,
`test_barehands_interaction_js` (2). Corrigé par la tâche : `test_brain_delegation` (S07), `test_settings_redesign_migration` six_tabs (S10).

Instables sous charge (passent seuls, sur la branche comme sur main) : `test_context_enrichment*`, `test_context_catchup*`,
`test_memory_context` (budget 2000 notes), `test_presentation_studio_engine_human`, `test_presentation_studio_explorer_commands`,
`test_back_brain_worker`, `test_barehands_command_channel`, `test_capture_api_protocol`, `test_wake_word_settings_browser`.
