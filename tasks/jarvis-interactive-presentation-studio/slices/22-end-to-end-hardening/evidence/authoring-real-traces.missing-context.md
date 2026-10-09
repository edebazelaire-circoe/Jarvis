# Authoring planner - real-model traces (Slice 22 release gate)

Real Claude (`sonnet`) through the CLI, the real prompt program (planner `presentation_studio.authoring.planner`, content fingerprint `ce625d3d9d1db844...`), the real MCP servers, an isolated Core. Synthetic briefs. Redacted: ids are aliases, tool arguments' texts are `<text>`; scene titles and final answers are quoted.

Total cost: $0.12, 5 tool calls over 1 scenarios.

| Scenario | Workflow | Tool calls | Draft calls | Gate rounds to delivered | Refused rounds | Question turns / budget | Scenes | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| missing-context | directed | 5 | 1 | 1 | 0 | 1 / 3 | [6] | $0.12 |

## missing-context

User: "Fais-moi une présentation." - 1 model turns, 3350 ms, $0.015

| # | tool | arguments | result |
| --- | --- | --- | --- |

Final answer (127 chars): Volontiers. Sur quel sujet, et pour quel public ? Sans précision, je pars sur un exposé de cinq minutes pour un public général.

User: "C'est pour l'équipe produit, sur le lancement de notre application mobile, quatre minutes, et c'est moi qui présente." - 6 model turns, 30967 ms, $0.108

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_draft_assemble,mcp__jarvis-presentation__presentation_dr` | ok / None |
| 2 | ToolSearch | `{"query": "Agent subagent background", "max_results": 3}` | ok / None |
| 3 | presentation_inspect | `{"target": "draft_guide"}` | ok / silent |
| 4 | presentation_inspect | `{"target": "overview"}` | ok / silent |
| 5 | presentation_draft_assemble | `{"brief": {"title": "<text>", "workflow": "directed", "purpose": "Présenter à l'équipe produit le lancement de notre application mobile", "audience": "Équipe pr` | delivered / say |
- draft `presentation_draft_assemble`: status delivered, stage complete, failures [], warnings []

Final answer (600 chars): C'est fait : la présentation de quatre minutes est créée, avec six scènes. Elles couvrent l'ouverture, les objectifs, l'apport pour les utilisateurs, le plan de lancement progressif, les risques et ce que vous attendez de l'équipe produit. Comme c'est vous qui présentez, je reste muet. Chaque scène a une note d'intention et des phrases de déclenchement. Je n'avais aucun document de départ, donc l'

Stored (live): 6 scenes, words per scene [20, 22, 23, 22, 21, 22], 6 score items, 6 cues (6 armable), presenters ['user'], art direction `generated (fallback)`; titles: Le lancement de notre application mobile; Ce que nous visons avec ce lancement; Ce que l'application apporte aux utilisateurs; Un plan de lancement progressif; Risques et points de vigilance; Ce que nous attendons de l'équipe produit
Pre-existing presentations untouched: True; archive calls: 0; scenes with TODO: 0.

