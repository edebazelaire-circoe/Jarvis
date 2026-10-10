# Authoring planner - real-model traces, Remotion scenes (release gate re-run, Slice 15)

Real Claude (`sonnet`) through the CLI, the real prompt program (planner `presentation_studio.authoring.planner`, content fingerprint `1c3275b6255d913d...`), the real MCP servers, an isolated Core. Synthetic briefs. Redacted: ids are aliases, tool arguments' texts are `<text>`; scene titles and final answers are quoted.

Total cost: $0.45, 12 tool calls over 3 scenarios.

| Scenario | Workflow | Tool calls | Draft calls | Gate rounds to delivered | Refused rounds | Question turns / budget | Scenes | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rich-brief | directed | 4 | 1 | 1 | 0 | 0 / 3 | [6] | $0.19 |
| vague-exploratory | exploratory | 4 | 1 | 1 | 0 | 0 / 1 | [3, 3, 3, 3, 3] | $0.19 |
| one-shot-report | one_shot | 4 | 1 | 1 | 0 | 0 / 0 | [1] | $0.07 |

## rich-brief

User: "Prépare-moi une présentation de 6 scènes, 5 minutes, pour la direction commerciale, sur les résultats du troisième trimestre : chiffre d'affaires en hausse de 1" - 5 model turns, 39990 ms, $0.190

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:Agent", "max_results": 3}` | ok / None |
| 2 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_draft_assemble", "max_results": 3}` | ok / None |
| 3 | presentation_inspect | `{"target": "draft_guide"}` | ok / silent |
| 4 | presentation_draft_assemble | `{"brief": {"title": "<text>", "workflow": "directed", "purpose": "Présenter les résultats du troisième trimestre et obtenir une décision sur le budget de recrut` | delivered / say |
- draft `presentation_draft_assemble`: status delivered, stage complete, failures [], warnings []

Final answer (834 chars): La présentation est créée : six scènes, cinq minutes, sans parole de ma part, c'est vous qui présentez. J'ai ajouté une phrase de déclenchement par scène pour vous suivre. Je n'ai pas pu confier le travail à un sous-agent, je l'ai donc fait moi-même.

Voici l'enchaînement :
1. Couverture.
2. Le chiffre d'affaires, avec le « +12 % » en grand.
3. La marge stable et les trois lancements tenus.
4. Les

Engine `remotion`, 6/6 scenes are Remotion sources (TSX lines [17, 17, 20, 20, 20, 17], reads theme [True, True, True, True, True, True], reads frame [True, True, True, True, True, True], hard-coded words [0, 0, 0, 0, 0, 0], colour literals [0, 0, 0, 0, 0, 0]).
Stored (live): 6 scenes, words per scene [11, 13, 19, 15, 22, 7], 6 score items, 6 cues (6 armable), presenters ['user'], art direction `generated (fallback)`; titles: Résultats du troisième trimestre; Chiffre d'affaires en hausse de 12 %; Marge stable et trois lancements tenus; Deux risques à surveiller; Décision sur le budget de recrutement; Questions et décision
Pre-existing presentations untouched: True; archive calls: 0; scenes with TODO: 0.


## vague-exploratory

User: "Je ne sais pas trop ce que je veux. Propose-moi plusieurs directions visuelles très différentes pour présenter ma start-up de livraison de repas à vélo. Donne-m" - 2 model turns, 9169 ms, $0.022

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:Agent", "max_results": 1}` | ok / None |

Final answer (1278 chars): Je n'ai pas d'outil pour lancer un sous-agent ici, donc je te donne les directions à l'oral, sans rien construire pour l'instant.

Première direction, l'énergie urbaine : fond sombre, néons vifs, mouvement rapide et gros chiffres. On y sent la vitesse de la ville et du vélo, pour un public investisseur ou jeune.

Deuxième direction, le frais du marché : couleurs chaudes, textures de papier, photos

User: "Crée-les dans le studio pour que je puisse les comparer." - 4 model turns, 38148 ms, $0.163

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_draft_assemble", "max_results": 2}` | ok / None |
| 2 | presentation_inspect | `{"target": "draft_guide", "kind": "exploratory"}` | ok / silent |
| 3 | presentation_draft_assemble | `{"brief": {"title": "<text>", "workflow": "exploratory", "purpose": "Choisir une direction visuelle pour présenter la start-up", "audience": "Moi", "tone": ["in` | delivered / say |
- draft `presentation_draft_assemble`: status delivered, stage complete, failures [], warnings []

Final answer (498 chars): C'est créé : j'ai mis cinq directions dans le studio, avec trois scènes chacune. Elles racontent la même histoire : la livraison de repas à vélo, le zéro émission et les restaurants partenaires.

Il y a le marché chaleureux, l'énergie urbaine, l'affiche rétro, le minimalisme écolo et la carte joyeuse. Pour la carte, j'ai gardé l'esprit joyeux et coloré, mais ce n'est pas encore une vraie carte ani

Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [15, 18, 14], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas livrés à vélo; Zéro émission, vraiment rapide; Des restaurants partenaires
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [15, 18, 14], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas livrés à vélo; Zéro émission, vraiment rapide; Des restaurants partenaires
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [15, 18, 14], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas livrés à vélo; Zéro émission, vraiment rapide; Des restaurants partenaires
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [15, 18, 14], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas livrés à vélo; Zéro émission, vraiment rapide; Des restaurants partenaires
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [15, 18, 14], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas livrés à vélo; Zéro émission, vraiment rapide; Des restaurants partenaires
Pre-existing presentations untouched: True; archive calls: 0; scenes with TODO: 0.


## one-shot-report

User: "Fais-moi tout de suite une présentation d'une seule diapositive qui affiche le résultat : le dossier Contrats compte 42 fichiers, soit 30 documents, 10 tableurs" - 5 model turns, 15423 ms, $0.074

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:Agent", "max_results": 1}` | ok / None |
| 2 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_draft_assemble", "max_results": 2}` | ok / None |
| 3 | presentation_inspect | `{"target": "draft_guide"}` | ok / silent |
| 4 | presentation_draft_assemble | `{"brief": {"title": "<text>", "workflow": "one_shot", "purpose": "Afficher le nombre de fichiers du dossier Contrats et leur répartition", "audience": "Moi", "d` | delivered / say |
- draft `presentation_draft_assemble`: status delivered, stage complete, failures [], warnings []

Final answer (345 chars): C'est fait : la présentation d'une seule diapositive est créée. Elle affiche un grand « 42 » avec la répartition : 30 documents, 10 tableurs et 2 présentations. Je n'avais pas d'outil pour la déléguer à un sous-agent, donc je l'ai construite moi-même. Les couleurs viennent d'une direction artistique générée par défaut, faute de charte trouvée.

Engine `remotion`, 1/1 scenes are Remotion sources (TSX lines [17], reads theme [True], reads frame [True], hard-coded words [0], colour literals [0]).
Stored (live): 1 scenes, words per scene [15], 1 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated (fallback)`; titles: Dossier Contrats
Pre-existing presentations untouched: True; archive calls: 0; scenes with TODO: 0.

