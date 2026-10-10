# Authoring planner - real-model traces, Remotion scenes (release gate re-run, Slice 15)

Real Claude (`sonnet`) through the CLI, the real prompt program (planner `presentation_studio.authoring.planner`, content fingerprint `e9661305d6a8834c...`), the real MCP servers, an isolated Core. Synthetic briefs. Redacted: ids are aliases, tool arguments' texts are `<text>`; scene titles and final answers are quoted.

Total cost: $0.37, 10 tool calls over 3 scenarios.

| Scenario | Workflow | Tool calls | Draft calls | Gate rounds to delivered | Refused rounds | Question turns / budget | Scenes | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rich-brief | directed | 3 | 1 | 1 | 0 | 0 / 3 | [6] | $0.13 |
| vague-exploratory | exploratory | 4 | 1 | 1 | 0 | 0 / 1 | [3, 3, 3, 3, 3] | $0.18 |
| one-shot-report | one_shot | 3 | 1 | 1 | 0 | 0 / 0 | [1] | $0.07 |

## rich-brief

User: "Prépare-moi une présentation de 6 scènes, 5 minutes, pour la direction commerciale, sur les résultats du troisième trimestre : chiffre d'affaires en hausse de 1" - 4 model turns, 37928 ms, $0.129

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_draft_assemble,mcp__jarvis-presentation__presentation_dr` | ok / None |
| 2 | presentation_inspect | `{"target": "draft_guide"}` | ok / silent |
| 3 | presentation_draft_assemble | `{"brief": {"title": "<text>", "workflow": "directed", "purpose": "Présenter les résultats du T3 à la direction commerciale et obtenir une décision sur le budget` | delivered / say |
- draft `presentation_draft_assemble`: status delivered, stage complete, failures [], warnings []

Final answer (707 chars): La présentation est créée : 6 scènes pour 5 minutes, et le contrôle qualité est passé sans erreur ni avertissement. Elle suit cet ordre : ouverture, chiffre d'affaires à plus 12 %, marge stable et trois lancements tenus, les deux risques, la décision sur le budget de recrutement, puis les questions.

C'est vous qui présentez, donc je reste silencieux. Chaque scène a une phrase de déclenchement que

Engine `remotion`, 6/6 scenes are Remotion sources (TSX lines [17, 17, 20, 20, 17, 17], reads theme [True, True, True, True, True, True], reads frame [True, True, True, True, True, True], hard-coded words [0, 0, 0, 0, 0, 0], colour literals [0, 0, 0, 0, 0, 0]).
Stored (live): 6 scenes, words per scene [10, 14, 15, 15, 11, 8], 6 score items, 6 cues (6 armable), presenters ['user'], art direction `generated (fallback)`; titles: Ouverture du trimestre; Chiffre d'affaires; Marge et lancements; Deux risques; Décision attendue; Clôture
Pre-existing presentations untouched: True; archive calls: 0; scenes with TODO: 0.


## vague-exploratory

User: "Je ne sais pas trop ce que je veux. Propose-moi plusieurs directions visuelles très différentes pour présenter ma start-up de livraison de repas à vélo. Donne-m" - 2 model turns, 8925 ms, $0.020

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:Agent", "max_results": 3}` | ok / None |

Final answer (1177 chars): Je n'ai pas pu lancer de sous-agent de fond ici, donc je ne fabrique pas encore la présentation. Voici déjà cinq directions très différentes, à l'oral.

Un : Néon nocturne. Fond noir, traînées lumineuses de vélo dans la ville, couleurs électriques. Un style énergique et urbain, pour une start-up qui joue la vitesse.

Deux : Papier et marché. Tons crème, textures de papier, illustrations dessinées 

User: "Crée-les dans le studio pour que je puisse les comparer." - 4 model turns, 37074 ms, $0.159

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_draft_assemble", "max_results": 3}` | ok / None |
| 2 | presentation_inspect | `{"target": "draft_guide", "kind": "exploratory"}` | ok / silent |
| 3 | presentation_draft_assemble | `{"brief": {"title": "<text>", "workflow": "exploratory", "purpose": "Choisir une direction visuelle pour présenter la start-up", "audience": "Investisseurs et p` | delivered / say |
- draft `presentation_draft_assemble`: status delivered, stage complete, failures [], warnings []

Final answer (694 chars): C'est fait : les cinq directions sont dans le studio, chacune sur le même mini-récit de trois scènes (la promesse, l'avantage, la suite). Elles s'appellent Papier et marché, Néon nocturne, Éditorial et données, Minimalisme écolo et Pop et couleurs. Le contrôle qualité est passé sans erreur ni avertissement.

Trois choses à savoir. J'ai supposé que tu présentes à des investisseurs, et je n'ai pas i

Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [14, 14, 13], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas frais, livrés à vélo; Rapide et sans émission; Rejoignez la tournée
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [14, 14, 13], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas frais, livrés à vélo; Rapide et sans émission; Rejoignez la tournée
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [14, 14, 13], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas frais, livrés à vélo; Rapide et sans émission; Rejoignez la tournée
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [14, 14, 13], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas frais, livrés à vélo; Rapide et sans émission; Rejoignez la tournée
Engine `remotion`, 3/3 scenes are Remotion sources (TSX lines [17, 17, 17], reads theme [True, True, True], reads frame [True, True, True], hard-coded words [0, 0, 0], colour literals [0, 0, 0]).
Stored (live): 3 scenes, words per scene [14, 14, 13], 3 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated`; titles: Des repas frais, livrés à vélo; Rapide et sans émission; Rejoignez la tournée
Pre-existing presentations untouched: True; archive calls: 0; scenes with TODO: 0.


## one-shot-report

User: "Fais-moi tout de suite une présentation d'une seule diapositive qui affiche le résultat : le dossier Contrats compte 42 fichiers, soit 30 documents, 10 tableurs" - 4 model turns, 14337 ms, $0.066

| # | tool | arguments | result |
| --- | --- | --- | --- |
| 1 | ToolSearch | `{"query": "select:mcp__jarvis-presentation__presentation_inspect,mcp__jarvis-presentation__presentation_draft_assemble", "max_results": 2}` | ok / None |
| 2 | presentation_inspect | `{"target": "draft_guide"}` | ok / silent |
| 3 | presentation_draft_assemble | `{"brief": {"title": "<text>", "workflow": "one_shot", "purpose": "Afficher le résultat du comptage des fichiers du dossier Contrats", "audience": "Moi", "durati` | delivered / say |
- draft `presentation_draft_assemble`: status delivered, stage complete, failures [], warnings []

Final answer (320 chars): C'est fait. La diapositive affiche « 42 fichiers » en grand, avec « 30 documents, 10 tableurs et 2 présentations » en dessous. Je n'avais pas d'outil pour la déléguer, donc je l'ai créée moi-même. Elle a passé le contrôle sans avertissement. Je n'ai trouvé aucune charte graphique, donc elle utilise le style par défaut.

Engine `remotion`, 1/1 scenes are Remotion sources (TSX lines [17], reads theme [True], reads frame [True], hard-coded words [0], colour literals [0]).
Stored (live): 1 scenes, words per scene [9], 1 score items, 0 cues (0 armable), presenters ['jarvis'], art direction `generated (fallback)`; titles: Dossier Contrats : 42 fichiers
Pre-existing presentations untouched: True; archive calls: 0; scenes with TODO: 0.

