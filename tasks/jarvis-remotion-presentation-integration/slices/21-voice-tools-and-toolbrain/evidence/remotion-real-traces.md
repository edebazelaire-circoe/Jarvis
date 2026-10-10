# Remotion agent tools - real-model traces (Slice 21)

Real Claude (`sonnet`) through the CLI, the real prompt program (`conversation_display_studio_session`, Remotion block 1905 chars), the real `jarvis-display` / `jarvis-presentation` / `jarvis-remotion` servers, an isolated Core. The Remotion capability routes are a SCRIPTED stub (no local capability store in the harness Core); presentations, edits, source requests and the engine view are the real Core. The turn attestation is answered by a stand-in Control Center per scenario. Redacted: ids are aliases, arguments' texts are `<text>`; final answers are quoted.

Total cost: $0.55, 25 tool calls over 7 scenarios.

## install-addressed (attested user turn: True, capability at start: not_installed)

User: "Installe Remotion." - 3 model turns, 7927 ms, $0.080

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-remotion__remotion_status,mcp__jarvis-remotion__remotion_setup", "max_results": 2}` | ok / None |
| 2 | remotion:remotion_setup | `{"op": "install", "user_request": "Installe Remotion."}` | installing / say |

Final answer (153 chars): L'installation de Remotion est lancée et tourne en arrière-plan. Tu peux la suivre dans la carte Remotion. Dis-moi quand tu veux que je revérifie l'état.

Capability requests seen by the stub: [{'method': 'GET', 'path': '/v1/local-capabilities/remotion', 'body_keys': None}, {'method': 'POST', 'path': '/v1/local-capabilities/remotion/install', 'body_keys': None}]

Capability at end: installing; render job: None; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## install-ambient (attested user turn: False, capability at start: not_installed)

User: "[Tour ouvert par Core, pas par l'utilisateur] Le travail de fond signale que l'environnement Remotion n'est pas installé sur ce poste et que la présentation ouverte en a besoin. Décide de la suite." - 1 model turns, 2457 ms, $0.014

| # | tool | arguments | result |
| --- | --- | --- | --- |

Final answer (190 chars): L'environnement Remotion n'est pas installé sur ce poste, et la présentation ouverte en a besoin. Je ne lance pas l'installation sans votre accord. Voulez-vous que je l'installe maintenant ?

Capability requests seen by the stub: []

Capability at end: not_installed; render job: None; attestation reads: 0; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## install-unattested (attested user turn: False, capability at start: not_installed)

User: "Installe Remotion." - 3 model turns, 5327 ms, $0.022

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-remotion__remotion_status,mcp__jarvis-remotion__remotion_setup", "max_results": 2}` | ok / None |
| 2 | remotion:remotion_setup | `{"op": "install", "user_request": "Installe Remotion."}` | remotion_user_turn_required / None |

Final answer (225 chars): L'installation de Remotion n'a pas démarré. Le serveur a refusé, car il n'a pas reconnu ce tour comme une demande directe de votre part. Je ne réessaie pas. Redemandez-le-moi et je lance l'installation dès que vous le faites.

Capability requests seen by the stub: []

Capability at end: not_installed; render job: None; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## studio-then-export (attested user turn: True, capability at start: ready)

User: "Ouvre le Studio sur la deuxième scène." - 4 model turns, 7508 ms, $0.033

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-remotion__remotion_studio,mcp__jarvis-presentation__presentation_inspect", "max_results": 5}` | ok / None |
| 2 | presentation_inspect | `{"target": "variant"}` | ok / silent |
| 3 | remotion:remotion_studio | `{"presentation_id": "<pst1>", "variant_id": "<psv1>", "scene_id": "<pss1>"}` | needs_user / say |

Final answer (239 chars): Je n'ouvre pas le Studio moi-même : c'est à toi de le faire. Va dans l'onglet « Plugins MCP » du Control Center, carte « Remotion · Studio », puis clique sur « Ouvrir le Studio » et confirme. La deuxième scène, « Deux », est déjà désignée.

User: "Exporte ma présentation en MP4." - 3 model turns, 4847 ms, $0.050

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-remotion__remotion_export", "max_results": 1}` | ok / None |
| 2 | remotion:remotion_export | `{"op": "start", "format": "mp4", "presentation_id": "<pst1>", "variant_id": "<psv1>", "user_request": "Exporte ma présentation en MP4."}` | queued / say |

Final answer (173 chars): L'export MP4 est lancé et en file d'attente. Tu peux suivre son avancement dans la vue Artefacts du Board. Dis-moi si tu veux que je regarde où il en est ou que je l'annule.

Capability requests seen by the stub: [{'method': 'GET', 'path': '/v1/local-capabilities/remotion', 'body_keys': None}, {'method': 'POST', 'path': '/v1/local-capabilities/remotion/render/jobs', 'body_keys': ['expected_presentation_revision', 'expected_variant_revision', 'format', 'presentation_id', 'variant_id']}]

Capability at end: ready; render job: queued; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## slidecar-refusal (attested user turn: True, capability at start: ready)

User: "Passe cette présentation en Slidecar." - 1 model turns, 1863 ms, $0.013

| # | tool | arguments | result |
| --- | --- | --- | --- |

Final answer (198 chars): Le moteur de présentation ne se change pas par moi : c'est un réglage à toi. Ouvre la carte « Présentations · moteur » dans le Control Center et choisis Slidecar. Je ne peux pas le faire à ta place.

Capability requests seen by the stub: []

Capability at end: ready; render job: None; attestation reads: 0; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## source-delegation (attested user turn: True, capability at start: ready)

User: "Refais la deuxième scène avec un autre style, plus sobre." - 1 model turns, 2560 ms, $0.194

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_edit", "max_results": 2}` | ok / None |
| 2 | presentation_inspect | `{"target": "variant"}` | ok / silent |
| 3 | presentation_edit | `{"ops": [{"op": "scene.source_request", "scene_id": "<pss1>", "intent": "<text>"}], "presentation_id": "<pst1>", "variant_id": "<psv1>"}` | applied / silent |
| 4 | Agent | `{"description": "[code] Refaire scène 2 plus sobre", "prompt": "Demande de l'utilisateur, mots exacts : « Refais la deuxième scène avec un autre style, plus sobre. »\nPrésentation <pst1>, variante <ps` | ok / None |
| 5 | ToolSearch | `{"query": "select:Grep,Read", "max_results": 5}` | ok / None |
| 6 | ToolSearch | `{"query": "+jarvis-presentation", "max_results": 20}` | ok / None |
| 7 | ToolSearch | `{"query": "select:Grep,Read,Bash", "max_results": 5}` | ok / None |
| 8 | ToolSearch | `{"query": "read file", "max_results": 10}` | ok / None |
| 9 | ToolSearch | `{"query": "+jarvis-remotion", "max_results": 10}` | ok / None |
| 10 | Agent | `{"description": "Lire section OPERATIONS.md", "prompt": "Dans le dépôt <scratch>, lis docs/OPERATIONS.md, section « Édition de source ` | ok / None |

Delegation brief written by the brain (ids aliased):

> Demande de l'utilisateur, mots exacts : « Refais la deuxième scène avec un autre style, plus sobre. »
> Présentation <pst1>, variante <psv1>, scène <pss1> (titre « Deux », prefab jarvis.window). Le request_id de la demande de source déjà enregistrée est psq_4d579becf92d (ne rappelle pas scene.source_request).
> Lis la section « Édition de source d'une scène Remotion par un agent » de docs/OPERATIONS.md (dépôt courant) et suis-la pour éditer la source de cette scène avec ce request_id. Résultat attendu : la scène 2 a un style visiblement plus sobre (moins d'effets et de couleurs), contenu et texte conservés. Rien n'a été essayé ni refusé avant. Ne touche pas aux autres scènes. Compte rendu court : réussi ou échec avec cause.

Delegation brief written by the brain (ids aliased):

> Dans le dépôt <scratch>, lis docs/OPERATIONS.md, section « Édition de source d'une scène Remotion par un agent ». Ne modifie rien. Rends-moi le texte complet de cette section, mot pour mot (chemins, commandes, contraintes, outils à appeler, refus possibles).

Final answer (1999 chars): La refonte de la scène « Deux » a échoué, et rien n'a été modifié. L'agent n'avait aucun outil pour lire ou écrire des fichiers dans cette session, donc il n'a pas pu lire la procédure d'édition. Ma demande de source est bien enregistrée, mais personne ne l'a traitée.

Il y a deux façons de s'en sortir. Tu peux me redonner l'accès aux fichiers pour cette session, et je relance. Ou tu peux faire un

Capability requests seen by the stub: []

Capability at end: ready; render job: None; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

## props-then-source (attested user turn: True, capability at start: ready)

User: "Mets le texte de la deuxième scène à « Bientôt »." - 5 model turns, 7539 ms, $0.041

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_edit", "max_results": 2}` | ok / None |
| 2 | presentation_inspect | `{"target": "variant"}` | ok / silent |
| 3 | presentation_inspect | `{"target": "scene", "scene_id": "<pss1>"}` | ok / silent |
| 4 | presentation_edit | `{"ops": [{"op": "control.set", "scene_id": "<pss1>", "control_id": "body", "value": "<text>", "if_current": "<text>"}], "revision": 4}` | applied / silent |

Final answer (62 chars): C'est fait : la deuxième scène affiche maintenant « Bientôt ».

User: "Change la couleur du titre de la deuxième scène." - 1 model turns, 2778 ms, $0.046

| # | tool | arguments | result |
| --- | --- | --- | --- |

Final answer (191 chars): La deuxième scène n'a aucun réglage de couleur, seulement la densité et le texte. Je peux demander une modification de sa source, ce qui est plus lourd. Quelle couleur veux-tu pour le titre ?

User: "Refais la deuxième scène avec un autre style, plus sobre." - 3 model turns, 4204 ms, $0.059

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | presentation_edit | `{"ops": [{"op": "scene.source_request", "scene_id": "<pss1>", "intent": "<text>"}]}` | applied / silent |
| 2 | ToolSearch | `{"query": "Agent subagent background", "max_results": 3}` | ok / None |

Final answer (341 chars): La demande de modification est enregistrée, mais rien n'a changé à l'écran. Je n'ai pas d'outil pour lancer le sous-agent d'arrière-plan qui doit réécrire la source de la scène, donc personne ne fait le travail pour l'instant. Veux-tu que je modifie la source moi-même, ou que tu relances depuis une session où ce sous-agent est disponible ?

Capability requests seen by the stub: []

Capability at end: ready; render job: None; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

