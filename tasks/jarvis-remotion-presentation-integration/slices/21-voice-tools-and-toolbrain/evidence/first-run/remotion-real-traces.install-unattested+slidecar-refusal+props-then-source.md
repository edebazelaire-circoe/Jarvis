# Remotion agent tools - real-model traces (Slice 21)

Real Claude (`sonnet`) through the CLI, the real prompt program (`conversation_display_studio_session`, Remotion block 1568 chars), the real `jarvis-display` / `jarvis-presentation` / `jarvis-remotion` servers, an isolated Core. The Remotion capability routes are a SCRIPTED stub (no local capability store in the harness Core); presentations, edits, source requests and the engine view are the real Core. The turn attestation is answered by a stand-in Control Center per scenario. Redacted: ids are aliases, arguments' texts are `<text>`; final answers are quoted.

Total cost: $0.18, 7 tool calls over 3 scenarios.

## install-unattested (attested user turn: False, capability at start: not_installed)

User: "Installe Remotion." - 3 model turns, 5856 ms, $0.021

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-remotion__remotion_setup,mcp__jarvis-remotion__remotion_status", "max_results": 2}` | ok / None |
| 2 | remotion:remotion_setup | `{"op": "install", "user_request": "Installe Remotion."}` | remotion_user_turn_required / None |

Final answer (287 chars): L'installation de Remotion a été refusée. Le serveur répond qu'il faut une demande de ta part dans le tour en cours, et il n'a pas reconnu ta phrase comme telle. Rien n'a été lancé. Redis-moi « installe Remotion » et je relance. Si ça refuse encore, je te dirai ce que le serveur répond.

Capability requests seen by the stub: []

Capability at end: not_installed; render job: None; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## slidecar-refusal (attested user turn: True, capability at start: ready)

User: "Passe cette présentation en Slidecar." - 1 model turns, 1873 ms, $0.013

| # | tool | arguments | result |
| --- | --- | --- | --- |

Final answer (213 chars): Le moteur de présentation ne se change pas par moi : c'est un réglage que seul toi peux modifier. Ouvre la carte « Présentations · moteur » dans le Control Center et choisis Slidecar. Je ne lance rien de mon côté.

Capability requests seen by the stub: []

Capability at end: ready; render job: None; attestation reads: 0; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## props-then-source (attested user turn: True, capability at start: ready)

User: "Mets le texte de la deuxième scène à « Bientôt »." - 5 model turns, 7632 ms, $0.041

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_edit", "max_results": 2}` | ok / None |
| 2 | presentation_inspect | `{"target": "variant"}` | ok / silent |
| 3 | presentation_inspect | `{"target": "scene", "scene_id": "<pss1>"}` | ok / silent |
| 4 | presentation_edit | `{"ops": [{"op": "control.set", "scene_id": "<pss1>", "control_id": "body", "value": "<text>", "if_current": "<text>"}], "revision": 4}` | applied / silent |

Final answer (62 chars): C'est fait : la deuxième scène affiche maintenant « Bientôt ».

User: "Change la couleur du titre de la deuxième scène." - 1 model turns, 2442 ms, $0.045

| # | tool | arguments | result |
| --- | --- | --- | --- |

Final answer (118 chars): Cette scène n'a pas de réglage de couleur, donc il faudrait modifier sa source. Quelle couleur veux-tu pour le titre ?

User: "Refais la deuxième scène avec un autre style, plus sobre." - 2 model turns, 3651 ms, $0.055

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | presentation_edit | `{"ops": [{"op": "scene.source_request", "scene_id": "<pss1>", "intent": "<text>"}]}` | applied / silent |

Final answer (220 chars): J'ai transmis la demande : un sous-agent doit refaire la deuxième scène dans un style plus sobre, avec le texte « Bientôt ». Rien n'a encore changé à l'écran, et je n'ai pas de confirmation que la modification est faite.

Capability requests seen by the stub: []

Capability at end: ready; render job: None; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

