# Remotion agent tools - real-model traces (Slice 21)

Real Claude (`sonnet`) through the CLI, the real prompt program (`conversation_display_studio_session`, Remotion block 1568 chars), the real `jarvis-display` / `jarvis-presentation` / `jarvis-remotion` servers, an isolated Core. The Remotion capability routes are a SCRIPTED stub (no local capability store in the harness Core); presentations, edits, source requests and the engine view are the real Core. The turn attestation is answered by a stand-in Control Center per scenario. Redacted: ids are aliases, arguments' texts are `<text>`; final answers are quoted.

Total cost: $0.08, 2 tool calls over 1 scenarios.

## install-addressed (attested user turn: True, capability at start: not_installed)

User: "Installe Remotion." - 3 model turns, 9159 ms, $0.081

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-remotion__remotion_setup,mcp__jarvis-remotion__remotion_status", "max_results": 2}` | ok / None |
| 2 | remotion:remotion_setup | `{"op": "install", "user_request": "Installe Remotion."}` | installing / say |

Final answer (274 chars): L'installation de Remotion est lancée, mais elle n'est pas terminée. Son état est « en cours d'installation » et elle est fixée sur la version 4.0.0. Tu peux la suivre dans la carte Remotion. Si tu veux, je relirai l'état plus tard pour vérifier qu'elle s'est bien terminée.

Capability requests seen by the stub: [{'method': 'GET', 'path': '/v1/local-capabilities/remotion', 'body_keys': None}, {'method': 'POST', 'path': '/v1/local-capabilities/remotion/install', 'body_keys': None}]

Capability at end: installing; render job: None; attestation reads: 1; engines at end: {'default': 'remotion', 'presentations': ['remotion']}

