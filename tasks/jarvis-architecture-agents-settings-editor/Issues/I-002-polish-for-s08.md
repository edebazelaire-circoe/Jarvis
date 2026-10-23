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
