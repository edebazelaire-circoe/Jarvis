# I-002 - Points non bloquants de la QA S07, à traiter en Slice 08

Source : QA indépendante de la Slice 07 (HEAD `05c9202b`), verdict REWORK léger ; le seul bloquant
(`test_routing_settings_screen.py:226` périmé) est corrigé par agent 0.

1. `syncCoreCliDraft` sans test : changer le CLI dans la fenêtre Core, puis enregistrer Comportement à pied,
   vérifier que `agent_cli` n'a pas bougé.
2. Fenêtre du cerveau, issue inconnue d'un PATCH (délai dépassé) ou réponse sans `config`
   (`control_center_brain_config_panel.js` ~514-529) : le brouillon `/api/settings` peut garder l'ancien CLI.
   Piste : `syncCoreCliDraft` après la relecture pour Core, ou remise à zéro de `SET.data`/`SET.draft`.
3. `_after_brain_settings_write` (`control_center.py` ~1711) lance `_switch_agent` sans l'attendre : deux PATCH
   rapprochés peuvent lancer deux switches.
4. `request_voice_switch` (`architecture_graph.py:491`) renvoie `None` au lieu de lever sur cible non
   résoluble ; seuil de battement 5,0 s dupliqué (`architecture_graph.py:66`, `control_center.py:224`).
5. Limites avouées confirmées : brouillon de la fenêtre perdu au changement d'onglet ; `brain_orchestration`
   possiblement périmé après modification d'Avancé › Architecture vocale dans la même ouverture ; preuve
   du routage par rôle limitée à `role_passthrough` (à prouver avec un candidat disponible en S08).
6. Ancienne tâche Réglages : en-tête « remplacée » dans `slices/04-agents-models-reorganization/SLICE.md` ;
   HV-SETTINGS citant encore « Agent principal ».
7. Reportés d'I-001 : S01-1, S01-3, S01-4.

## Sort de chaque point (Slice 08, 2026-10-24)

| Point | Sort |
| --- | --- |
| 1. `syncCoreCliDraft` sans test | **fait** `8cee2370` : `test_a_core_model_saved_in_its_window_survives_a_footer_save_of_behavior` (vrai Chrome, vrai Control Center isolé : modèle de Core changé dans la fenêtre, puis « Enregistrer » de Comportement ; la charge `/api/settings` porte `cli.settings.claude.model` choisi et le fichier le garde). Mutation : l'appel retiré, le test échoue. |
| 2. Issue inconnue d'un PATCH : brouillon `/api/settings` | **fait** `8cee2370` : après une issue inconnue, la fenêtre relit puis appelle `onReread` (événement `brain-config:reread`) ; une réponse `ok` sans `config` fait relire **avant** `onSaved`. La page aligne son brouillon (`syncCoreCliDraft`) dans les deux cas. Tests node `test_an_unknown_model_outcome_hands_the_reread_config_to_the_host`, `test_a_success_without_config_hands_the_reread_config_to_on_saved` ; doc `docs/settings/brain-config-panel.md`. |
| 3. `_switch_agent` lancé sans être attendu | **fait** `4da489da` : chaque bascule attend le verrou de l'agent (FIFO) puis relit les réglages ; tant qu'une bascule est en file, l'écriture suivante y passe aussi. Test `test_two_close_core_cli_writes_end_on_the_last_saved_cli`. Prouvé en bac à sable : `codex` puis `claude` → `agent.stop → agent.switch codex → agent.start → agent.stop → agent.switch claude → agent.start`. |
| 4. `request_voice_switch` qui rend `None` ; seuil 5,0 s dupliqué | **non traité** : hors du chemin des scénarios (aucun défaut observé en bac à sable) ; reste un point de propreté pour une tâche ultérieure. |
| 5. Limites avouées | brouillon de la fenêtre perdu au changement d'onglet et `brain_orchestration` périmé par Avancé : **inchangés**, documentés (`docs/settings/architecture-agents.md` § 5). Preuve du routage par rôle : **faite** avec un candidat disponible (fixture de catalogue) et le vrai CLI : `agent.routing.decided role_id=qa explicit preferred`, sous-agent exécuté sur `resolvedModel claude-sonnet-5-5` ; elle a révélé le défaut corrigé en `bd9bf358` (le hook écrivait un identifiant que l'outil `Agent` refuse). |
| 6. Ancienne Slice 04 « remplacée », HV-SETTINGS | **fait** `c196a45f` : en-tête « Remplacée » dans `tasks/jarvis-settings-ui-reorganization/slices/04-agents-models-reorganization/SLICE.md`, HV-SETTINGS-003 marqué remplacé (renvoi aux HV-ARCH). |
| 7. Reportés d'I-001 | S01-3 **fait** `f16ebd49` : la preuve de la consigne « voix seule » porte l'empreinte de la consigne (statique, couche) et celle des instructions réellement envoyées. S01-4 **fait** `d310c1b5` : appel halluciné de `back_brain_delegate` sur liaison coupée → `unavailable`, raison `back_brain_delegation_disabled`. S01-1 **non fait, documenté** : marquer `pending` une liaison vocale quand l'écart de Voice est dû à un autre réglage contredirait le contrat écrit (`docs/architecture-graph.md` § 5 : « écart dû à un autre réglage : valeur persistée, sans `pending` ») et ferait clignoter toutes les liaisons vocales à chaque changement de modèle ; décision produit nécessaire. |

Défauts nouveaux trouvés par la campagne finale et corrigés (détail : `slices/08-final-integration-e2e-qa/EVIDENCE.md` § 3) :
famille de modèle dans l'outil `Agent` (S03), Échap du menu d'un nœud qui fermait les Réglages (S07), CLI détecté
refusé dans la fenêtre du cerveau Core (S02).

## Points non bloquants de la QA indépendante S08 (agent 0, 2026-10-24) — suivi après la tâche

- `ui_close` respecte désormais `defaultPrevented` hors des Réglages aussi (menu contextuel des agents, roue de
  capture, HUD Bare Hands, plein écran) : une Échap consommée ne ferme plus le panneau en plus. Plutôt une
  amélioration ; la doc ne le dit que pour les Réglages.
- Fenêtre du cerveau : PATCH réussi sans `config` + relecture ratée → `notify('saved')` avec l'ancienne
  `st.config` (`control_center_brain_config_panel.js` ~530-534). Cas rare.
- `onSaved` : condition `saved.field==='provider'` jamais vraie (l'étape s'appelle `model`). Sans effet.
- Famille vs version exacte du modèle d'un rôle : décision produit (HV-ARCH-007).
