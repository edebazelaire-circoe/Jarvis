# Mode support des Réglages, Aide et assistance, lien profond

**Statut :** contrat, niveau 3. Implémentation : `jarvis/runtime/support_mode.py` (bloc persisté),
`jarvis/runtime/control_center.py` (`GET/POST /api/support-mode`, `support_mode` du battement `/api/status`),
`jarvis/runtime/control_center_settings_registry.js` (`support:true`, `options.support`), `control_center.html`
(bande « Aide et assistance » du hub, `JarvisSettingsHelp`, lien `#settings/<cible>`). Conformance :
`tests/unit/test_support_mode.py`, `tests/unit/test_product_edition_ui_js.py`, `tests/unit/test_novice_settings_browser.py`.
**Introduit :** `jarvis-presentation-edition-v1-2`, Slice 06 (amendement 06 de la préparation : accès « support » aux
catégories `agents_models` et `advanced_diagnostics` sans le mode développeur complet).

## Ce que c'est

Un interrupteur de **navigation** de l'édition produit. Activé, il montre de nouveau dans le hub et le shell les deux
catégories déclarées `support` au registre (Architecture & Agents, Avancé & Diagnostics), étiquetées « Support ».
Rien d'autre :

| Ne change pas | Pourquoi |
| --- | --- |
| ce que le cerveau et ses sous-agents peuvent appeler | le manifeste `agent_capabilities` ne dépend que de l'édition du processus ; seul `control_center.py` lit le bloc (test `test_support_mode_widens_no_agent_capability`) |
| ce que `jarvis-console` voit ou écrit | le bloc n'est pas dans la projection `GET /api/settings` (test) |
| les types de Board, les connecteurs, `developer_surfaces` | politique de l'édition ([../product-edition.md](../product-edition.md)) |
| les outils Trace, Test Lab, MCP, Prefabs ; Bare Hands, Plugins MCP | réservés à `JARVIS_DEVELOPER_MODE=1` |

En `full` (toutes les surfaces visibles), le mode support n'a aucun effet visible.

## Donnée

Bloc `support_mode` à la racine de `runtime/control-center-settings.json` (aucune table, aucune migration) :
`{"schema_version": 1, "enabled": true|false}`. Absent : coupé. Illisible (pas un objet, autre version, valeur non
booléenne) : coupé, avec `problem` (`support_mode_block_malformed`, `support_mode_stored_version_unreadable`,
`support_mode_value_invalid`), dit dans la bande ; l'interrupteur le réécrit.

- `GET /api/support-mode` → `{"enabled", "problem"}` ; le battement `/api/status` porte le même bloc (`support_mode`).
- `POST /api/support-mode` `{"enabled": bool}` exactement ; refus `support_mode_bad_payload` (400, en-tête
  `X-Jarvis-Error-Code`, journal `support_mode.refused`). Succès : écriture atomique (`_write_settings`, autres clés
  gardées), journal `support_mode.saved {before, after}`, réponse = bloc relu.

## Page

- **Aide et assistance** (bas du hub des Réglages, édition produit seulement) : la ligne **Voix** (état lu sur le
  battement par `JarvisRuntimeWheel.voiceLine()`, bouton = le même geste que l'interrupteur de la roue), **Signaler un
  problème** (branchée sur le panneau de la Slice 07 : le hub se referme puis `JarvisSupportReport.open({reason:
  'settings_hub'})`, [../support-report.md](../support-report.md) ; ligne cachée si le module manque ;
  `JarvisSettingsHelp.setReportAction(fn)` reste le point de branchement), **Mode support** (`role="switch"`,
  `aria-checked` = le fait relu ; une écriture à la fois, 8 s au plus, refus ou silence dits dans la note, rien
  supposé). Journal `[settings] support_mode.requested|saved|failed|state`, `help.voice_toggle`, `help.report_problem`.
- Une page de support ouverte dit en tête qu'elle est visible parce que le mode support est activé, et comment la cacher.
- **Lien profond** : `#settings/<cible>` (catégorie, section ou alias hérité) à la fin de l'adresse du Control Center
  ouvre les Réglages sur la cible. Une cible réservée au support ouvre le hub, met le focus sur l'interrupteur et dit
  « Cette page s'ouvre en mode support » ; l'activer ouvre la page demandée. Une cible inconnue ouvre le hub
  (`[settings] deep_link.unknown`). API : `JarvisSettingsHelp.openDeepLink(cible)`.

## Procédure support (sur le poste de l'utilisateur)

1. Ouvrir JARVIS, puis **Paramètres** (bouton Réglages, roue › Paramètres, ou touche `s`).
2. En bas, **Aide et assistance › Mode support** : l'activer. Architecture & Agents et Avancé & Diagnostics
   apparaissent (étiquette « Support »).
   Raccourci : ajouter `#settings/diagnostics` (ou `#settings/voice_output`, `#settings/prompts`,
   `#settings/runtime_cli`, `#settings/subagents`) à l'adresse du Control Center ; pour une page de support, activer
   l'interrupteur proposé.
3. Transcription, micro, voix : **Personnalisation › Voix & transcription / Micro & son / Tours & interruptions** —
   toujours visibles, sans mode support.
4. Fin du dépannage : couper le mode support (même interrupteur). Rien d'autre n'a changé.

Ce qui demande toujours le mode développeur (`JARVIS_DEVELOPER_MODE=1` au lancement) : Trace, Test Lab, inspecteur MCP,
Prefabs, Bare Hands, Plugins MCP.
