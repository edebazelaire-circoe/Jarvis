# Réglages : inventaire essentiel / avancé-support (édition Presentation)

**Statut :** contrat, niveau 2 (inventaire et règles) ; implémentation `jarvis/runtime/control_center_settings_registry.js`
(`product`, `support`, `categoriesFor`, `sectionHidden`) et conformance `tests/unit/test_product_edition_ui_js.py`,
`tests/unit/test_novice_settings_browser.py`.
**Introduit :** tâche `jarvis-presentation-edition-v1-2`, Slice 06 (décision du 2026-10-26 « Full Settings retained ») :
on ne supprime aucun réglage ; on simplifie le parcours ordinaire par **priorisation** et **divulgation progressive**.

## Règles

1. Aucun réglage n'est retiré du registre ni de la page : chaque section reste enregistrée et testée
   (`test_every_registered_section_stays_reachable`, en `presentation` avec le mode support et en `full`).
2. Une page **essentielle** se voit dans le hub de l'édition produit, avec un libellé sans jargon (`product.label`) et
   dans l'ordre du parcours (`product.order`) : Personnalisation, Connexions, Mémoire, Raccourcis clavier.
3. Une page **avancée/support** reste atteignable sans mode développeur : les catégories `support` (Architecture &
   Agents, Avancé & Diagnostics) s'ouvrent par le mode support ([support-mode.md](support-mode.md)), étiquetées
   « Support » ; une page de support le dit en tête. Les codes bruts (`voice_provider_key_missing`,
   `role_unavailable_in_edition`…) restent dans ces pages et dans les détails, jamais dans le libellé principal.
4. Deux sections **développeur** de catégories produit restent réservées à `JARVIS_DEVELOPER_MODE=1`, comme depuis la
   Slice 08 V1 : Bare Hands (expérimental) et Plugins MCP. Le mode support ne les ouvre pas.
5. En `full`, rien ne change : six catégories, libellés et ordre d'avant, aucune bande « Aide et assistance ».

## Inventaire (2026-10-27)

| Catégorie (`id`) | Libellé `full` → `presentation` | Section (`id`) | Contenu | Classe | En `presentation` |
| --- | --- | --- | --- | --- | --- |
| `voice_audio` | Personnalisation → Personnalisation | page Personnalisation | voix et langue de transcription, longueur et ton des réponses, préférences rapides, rappels | essentiel | hub, 1er |
| | | `theme_scene` | thème, scène visuelle | essentiel | montré |
| | | `agent_behavior` | comportement (absorbé par la page) | essentiel | montré |
| | | `conversation` | mode de conversation, vérification du locuteur | avancé | montré |
| | | `voice_output` | voix & transcription (moteur, modèle de transcription) | avancé, support terrain | montré |
| | | `microphone_sound` | micro, périphérique, son | avancé, support terrain | montré |
| | | `turns_interruptions` | tours, silence, interruptions | avancé | montré |
| | | `wake_word` | mot d'éveil, moteur présent ou non | avancé | montré |
| `connections` | Plugins & MCP → Connexions | `providers` | clés des fournisseurs (jamais une valeur) | essentiel | hub, 2e |
| | | `mcp_plugins` | plugins MCP | développeur | mode développeur seulement |
| `memory_knowledge` | Mémoire & Connaissances → Mémoire | `recall` | mémoire, rappel, recherche sémantique, consolidation | avancé | hub, 3e |
| | | `knowledge_sources` | sources de connaissances | avancé | montré |
| | | `memory_center` | Memory Center | avancé | montré |
| `interface_interactions` | Interface & Interactions → Raccourcis clavier | `shortcuts` | raccourcis (seul éditeur) | essentiel | hub, 4e |
| | | `bare_hands` | Bare Hands | développeur | mode développeur seulement |
| `agents_models` | Architecture & Agents | `architecture` | graphe des cerveaux, fenêtre d'un cerveau | support | mode support |
| | | `subagents` | rôles, modèles ; `coder` « Indisponible dans cette édition » | support | mode support |
| `advanced_diagnostics` | Avancé & Diagnostics | `architecture_compat` | architecture vocale, piles historiques | support | mode support |
| | | `memory_advanced` | délai de rappel, sidecar | support | mode support |
| | | `prompts` | atelier des prompts, prompt effectif | support | mode support |
| | | `runtime_cli` | commande, permissions, routage bas niveau | support | mode support |
| | | `diagnostics` | état constaté, lecture seule | support | mode support |
| | | `scene_gate` | porte de test de la scène | support | mode support |
| | | `work_methods` | Work Methods apprises | support | mode support |
| | | `barehands_lab` | Bare Hands · essais | support | mode support |

Hors Réglages, mêmes règles : le lanceur garde Trace, Test Lab, MCP et Prefabs pour le mode développeur
([../control-center-shell.md](../control-center-shell.md) › *Product edition UI*).

## Parcours principal (édition Presentation)

Choisir ou reprendre un projet (carte Board, Board Présentation seul créable, Assistant et Réunion « Bientôt
disponible ») → parler ou écrire (chat ; ligne **Voix** de l'accueil et d'Aide et assistance : Coupée / En veille / En
conversation, même projection que l'interrupteur de la roue) → Dossier et recherches → créer, éditer, présenter,
exporter (accueil des présentations, [../presentation-studio.md](../presentation-studio.md) › *Presentation home*).
Les Réglages ne sont pas sur ce chemin : le hub dit l'essentiel d'abord et regroupe l'aide en bas.
