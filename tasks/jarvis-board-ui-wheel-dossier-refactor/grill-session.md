# Grill session — reconstructed from the visible design conversation

> **Status:** reconstructed from the current visible conversation, not an external verbatim export. The quoted blocks below preserve the key user wording available to the planner. Where the conversation contained speech-to-text disfluencies, the handoff keeps the intent rather than silently treating every fragment as a technical requirement.

## Starting point: current UI

The user supplied `assets/current-ui-before.png` and identified the current problems:

> “le mode. C'est la sélection du mode. C'est la partie en bas à gauche. C'est la partie en haut à droite.”

> “le mode de parole de Jarvis devrait s'y retrouver [dans la roue] … forcer en fait manuellement par le clic le mode de pensée de Jarvis.”

> “il y a en bas à gauche, il y a un truc avec marqué 52 appels masqués affichés, ça je déteste ce truc, ça doit pas être là.”

> “le bouton en bas à gauche … ne serait plus un mode pour sélectionner si je veux le mode simple présentation réunion, parce qu'en fait maintenant on fonctionne avec des boards.”

> “un board a un type et on ne peut plus switcher de type. Ce n'est pas un board qui passe en mode simple, en mode présentation, en mode autre chose. C'est chaque type de board, chaque board a un type et du coup Jarvis se met dans le type de board dans lequel il est.”

The intended bottom-left control was described as a Board navigation entry:

> “je clique là, nouveau board ou sélectionner un board existant et pourquoi pas quelques boards favoris sur lesquels je veux vite switcher.”

And the user explicitly rejected the old top-left chrome:

> “tout en haut, il y a un outil de sélection de board qui est vraiment mal foutu, donc ça à jarter. Il y a le Voice Cloud Running, pareil, du coup qui est à jarter, qui est à mettre dans le menu.”

## Radial UI exploration

Several generated concepts were reviewed. The preferred reference is preserved as `assets/style-reference-radial-ui.png`.

The user accepted its main direction but corrected its menu behaviour:

> “celle-ci est plutôt bien.”

> “avoir un Jarvis en premier, c'est très bien. Et donc du coup, en le sélectionnant, comme tu le fais, ça développe, mais c'est vraiment parce que je sélectionne que le menu est là.”

> “Faut pas que le menu soit là. C'est parce que je sélectionne qu'il est là. C'est pour ça, vu que t'as un autre menu en dessous, ça pose souci.”

The proposed primary categories were then refined. The user rejected broad catch-all categories:

> “recherche, je suis pas persuadé que ce soit pertinent. Si j'ai une recherche à faire, je la demande directement à Jarvis.”

> “Outils, pareil, je vois pas trop ce que tu veux faire avec des outils.”

and kept Settings:

> “paramètres, j'aime bien. J'aime bien paramètres.”

The resulting target categories are JARVIS / Sélection / Dossier / Capture / Paramètres.

## Capture consolidation

The user explained why the old permanent capture buttons were too fragmented:

> “le vrai actuel, il a quatre boutons, c'est souris, vidéo, capture d'écran et capture audio. Je pense que c'est pas nécessaire.”

> “on va avoir un bouton de capture”

The active state should appear only while recording:

> “quand c'est record la vidéo, ça fait apparaître un bouton rouge en haut à gauche de l'écran de recording”

> “quand c'est un recording audio, ça fait apparaître une boule … qui enregistre.”

The requirement is therefore one Capture category, while preserving simultaneous audio/video capability and backend truth.

## Dossier: the Board's human documentary workspace

The user accepted the label:

> “vas-y, dossier, ça me va très bien.”

The Dossier is not merely a file browser. It is the durable, organized side of Board work:

> “les informations, les artefacts surtout qu'on a à l'écran, on peut vouloir les ranger dans le dossier.”

> “la documentation au final n'est qu'un aspect actif, pas actif. Et du coup, des fois tu peux sortir … plusieurs dossiers. Donc tu peux sortir des dossiers, les afficher à l'écran, puis bon, c'est bon, tu peux les ranger.”

> “c'est ce dossier … comme la sous-interface … c'est l'interface pour visualiser encore mieux les dossiers, donc un côté des dossiers rangés … et d'un autre côté un espace pour les visualiser.”

The user wants a full-screen, polished working surface:

> “on veut, on cherche de l'info, on veut voir des trucs, on veut lire des documents, on veut voir des images, on veut utiliser des trucs.”

and wants Jarvis to navigate it with the human:

> “c'est là où Jarvis doit nous accompagner à la voix dans ce que je veux voir, en fait, dans cet espace.”

The key collaboration intent is that the human can understand and correct the context agents rely on:

> “faut que ce soit moi qui travaille sur le contexte de board, faut pas que ce soit juste que les agents.”

> “c'est un peu en binôme … Ils ont besoin de mettre de la doc. Moi, j'ai besoin un petit peu de voir, de lire, de comprendre et de réajuster pour les aider.”

> “quand je mets une info là-dedans, je sais qu'il y a accès … lui aussi met le truc à jour.”

This is why the Dossier must expose a clean human view over canonical Board memory/artifact data rather than a technical dump.

## Hidden vs archived vs stored

The user explicitly did not want hidden objects to become another permanent junk drawer:

> “les objets masqués ne devraient pas être quelque part rangés dans des dossiers, mais que c'est une section un peu fourre-tout, temporaire en fait, de choses masquées.”

That maps cleanly to the current scene contract: hidden is active/recoverable, archive removes a representation from the active scene while history remains.

`Ranger` therefore means persist/organize the content in Dossier, then remove its visual representation. `Masquer` means temporary invisibility only.

## Follow-up idea: completed task lifecycle

The user deliberately marked this as a scope detour but asked not to lose it:

> “Ce serait pas mal si tu pouvais me mettre un petit end of de côté avec cette idée.”

The idea: on task completion, decide whether the task card still deserves screen space; if useful, produce a notification/result summary/artifact, update memory/Dossier, then archive the completed task in background. Do not generate useless reports for every ephemeral task.

This is preserved in `Issues/task-completion-lifecycle-follow-up.md` and is not part of the core refactor acceptance criteria.

## Final Create Task instruction

The user requested a UI-first implementation handoff and stressed removal as much as addition:

> “c'est une image de référence de style, etc., mais que ce n'est pas à suivre au clé à lettre.”

> “il est très important que le style graphique de la roue soit mis à jour.”

> “porte bien attention sur ce qui doit virer aussi de l'ancien, pas ajouter de nouveau, mais ce qui doit partir de l'ancien, ce qui doit être changé, modifié.”

The user also requested a final human-intent reread/audit. That audit is recorded in `docs/07-human-intent-audit.md`.
