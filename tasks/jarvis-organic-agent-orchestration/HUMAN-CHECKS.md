# Recette humaine — jarvis-organic-agent-orchestration

Liste consolidée des vérifications humaines de toutes les Slices. **Aucune n'est passée** : chacune reste `pending` dans le `human-validation.json` de sa Slice jusqu'à ce que vous l'exécutiez vous-même. Preuves de référence (captures, traces) : `slices/<slice>/evidence/`.

## Avant de commencer

1. Fusionner la branche `task/jarvis-organic-agent-orchestration` dans `main` (votre décision).
2. Redémarrer complètement JARVIS vous-même (`project jarvis restart`). Au démarrage, Core migre `jarvis.sqlite3` v9 → v10 → v11 (une seule sauvegarde `jarvis.sqlite3.v9.bak`) et `scene.sqlite3` v1 → v2 (sauvegarde `scene.sqlite3.v1.bak`). Retour arrière : `docs/OPERATIONS.md`.
3. Ouvrir une **nouvelle conversation** : le prompt du cerveau a changé.

| Check | Slice | Résumé |
|---|---|---|
| HV-ORG-05-01 | 05 | Run one clearly trivial action and confirm JARVIS does not artificially expand it into a t… |
| HV-ORG-06-01 | 06 | Inspect a real Adversary run and confirm participants are competing producers defending di… |
| HV-ORG-06-02 | 06 | Inspect a real QA run and confirm the Quality Analyst is reviewing existing work asymmetri… |
| HV-ORG-06-03 | 06 | Open a collaboration record and confirm it contains deliberate messages/decisions but no p… |
| HV-ORG-07-01 | 07 | Give a vague creation request, answer Interviewer questions while background research runs… |
| HV-ORG-07-02 | 07 | Give a clear direct bug/fix request and confirm no mandatory Interviewer ceremony is inser… |
| HV-ORG-08-01 | 08 | Complete a non-ephemeral multi-agent mission, restart isolated Core, and confirm actual ro… |
| HV-ORG-08-02 | 08 | Complete a trivial ephemeral task and confirm no persistent constellation/history star rem… |
| HV-ORG-09-01 | 09 | At a glance identify at least Developer, Web Research, Document Research and QA roles in o… |
| HV-ORG-09-02 | 09 | Distinguish Delegation, Communication, Adversary, QA and Handoff links visually; confirm A… |
| HV-ORG-09-03 | 09 | Click/focus the Communication relation message affordance and verify the correct readable … |
| HV-ORG-09-04 | 09 | Observe a mission evolve and confirm only actual agents/relations appear; no speculative f… |
| HV-ORG-09-05 | 09 | At 200% zoom and a dense graph, confirm role labels, relation affordances and shell contro… |
| HV-ORG-10-01 | 10 | Open Settings > agent roles and confirm the role catalogue is visually structured, readabl… |
| HV-ORG-10-02 | 10 | Inspect a role and verify mission, skills/loadout, capabilities and Work Methods are under… |
| HV-ORG-11-01 | 11 | Ask for a serious comparative research result and verify JARVIS delivers a polished struct… |
| HV-ORG-11-02 | 11 | Ask for a trivial short result and confirm JARVIS does not force an unnecessary heavy repo… |
| HV-ORG-12-01 | 12 | Promote a real Work Method candidate yourself from Settings > Sous-agents and confirm noth… |
| HV-ORG-13-01 | 13 | End-to-end: start from a code mission that organically requires research, a competing alte… |
| HV-ORG-13-02 | 13 | After mission completion, confirm non-ephemeral history remains inspectable while ephemera… |
| HV-ORG-13-03 | 13 | Review one multi-day/long-running style simulated mission and confirm nested Mission Owner… |
| HV-ORG-13-04 | 13 | Review final representative report/comparison artifacts and approve visual/presentation qu… |

### HV-ORG-05-01 — Slice 05-orchestration-runtime-tools

- [ ] **À vérifier** : Run one clearly trivial action and confirm JARVIS does not artificially expand it into a team solely because orchestration tools exist.

### HV-ORG-06-01 — Slice 06-relations-runtime-communication

- [ ] **À vérifier** : Inspect a real Adversary run and confirm participants are competing producers defending different work, not one producer plus reviewer.

### HV-ORG-06-02 — Slice 06-relations-runtime-communication

- [ ] **À vérifier** : Inspect a real QA run and confirm the Quality Analyst is reviewing existing work asymmetrically.

### HV-ORG-06-03 — Slice 06-relations-runtime-communication

- [ ] **À vérifier** : Open a collaboration record and confirm it contains deliberate messages/decisions but no private reasoning/thinking transcript.

### HV-ORG-07-01 — Slice 07-interviewer-background-coordination

- [ ] **À vérifier** : Give a vague creation request, answer Interviewer questions while background research runs, and confirm interaction remains responsive and later questions can use returned evidence.

**Préparation**

Après redémarrage de JARVIS par vous, à la voix : « J'aimerais organiser une petite fête de quartier cet été, quelque chose de convivial qui rassemble vraiment les voisins, en m'inspirant de ce qui a bien marché ailleurs. » Attendu : réponse immédiate d'une phrase, Intervieweur seul lancé ; à sa première question, une recherche part en parallèle ; répondez pendant qu'elle tourne ; une question ou le cahier des charges suivant reprend une trouvaille ; après « PRÊT », le cerveau demande votre accord et ne lance rien sans votre oui. Trace d'essai (sonnet, Chat) : C:/Projects/jarvis/orch/tasks/jarvis-organic-agent-orchestration/slices/07-interviewer-background-coordination/evidence/final-p-c.txt.

**Écarts résiduels connus**

- Longueur orale de sonnet : relais de fin mesuré à quatre phrases (borne : trois), réponse de lancement à deux phrases (borne : une) ; écoutez si c'est acceptable à la voix.
- Premier tour du cas B : 10,4 s avec sonnet (un seul appel Agent, aucun autre outil) ; dites si l'attente est acceptable.

### HV-ORG-07-02 — Slice 07-interviewer-background-coordination

- [ ] **À vérifier** : Give a clear direct bug/fix request and confirm no mandatory Interviewer ceremony is inserted.

**Préparation**

Dites « Il y a un bug dans <fichier> : <constat>. Corrigez-le. » Attendu : un seul agent Développement, aucune question d'Intervieweur, le résultat annoncé à la fin. Puis « Corrigez la coquille du titre de <fichier> » : tâche éphémère discrète, rien d'annoncé quand elle réussit. Traces : C:/Projects/jarvis/orch/tasks/jarvis-organic-agent-orchestration/slices/07-interviewer-background-coordination/evidence/run-haiku-a.txt, C:/Projects/jarvis/orch/tasks/jarvis-organic-agent-orchestration/slices/07-interviewer-background-coordination/evidence/final-h-d.txt.

**Écarts résiduels connus**

- Haiku, éphémère : il a encore promis « je vous confirme dès qu'elle est vérifiée » et annoncé la réussite, malgré la règle ; vérifiez avec votre modèle du cerveau.
- Haiku : recommandation rendue en Markdown gras et sans dire que le détail est à l'écran ; lancement en trois phrases.
- Haiku et [web-research] : avec le renvoi généré, « lequel me conseillez-vous » (Free/Orange/Bouygues) part bien en [general] [research-lead] (final-h-d.txt) ; une formulation sans « comparer » ni « conseiller » peut encore partir en recherche web (rework-h-d.txt, écrans 27 pouces).

### HV-ORG-08-01 — Slice 08-scene-projection-role-relations

- [ ] **À vérifier** : Complete a non-ephemeral multi-agent mission, restart isolated Core, and confirm actual role/relation history reappears without invented live status.

### HV-ORG-08-02 — Slice 08-scene-projection-role-relations

- [ ] **À vérifier** : Complete a trivial ephemeral task and confirm no persistent constellation/history star remains afterward.

### HV-ORG-09-01 — Slice 09-task-graph-ui

- [ ] **À vérifier** : At a glance identify at least Developer, Web Research, Document Research and QA roles in one populated task graph without opening details.

**Comment**

- **where** : Votre Control Center habituel (http://127.0.0.1:17654/) une fois la branche fusionnée et JARVIS relancé par vous ; ou un bac à sable lancé depuis le worktree (JARVIS_DATA_ROOT et JARVIS_RUNTIME_DIR temporaires, JARVIS_CORE_PORT=27653, JARVIS_UI_PORT=27654, JARVIS_VISUALIZER_ENABLED=0, JARVIS_OPEN_BROWSER=0), page http://127.0.0.1:27654/.
- **steps** : Demandez à Jarvis, par le Chat : « Comparez sérieusement Postgres, SQLite et DuckDB pour un petit outil d'analyse local : mettez trois agents en concurrence, chacun défend une option, faites relire le gagnant par un contrôle qualité, puis recommandez-m'en une. » Attendez que les étoiles apparaissent sur le Board.; Sans survoler ni cliquer, lisez la pastille à gauche de chaque étoile : un pictogramme et un badge (DIR, WEB, DOC, DEV, QA…) dans l'accent du rôle ; l'étoile prend le même accent.; Repérez le responsable de la mission : sa pastille porte un drapeau, un fond plus marqué et l'origine (« · général », « · code »).; Vérifiez qu'au moins quatre rôles se distinguent sans la couleur (pictogramme et lettres différents) : développement (DEV), recherche web (WEB), recherche documentaire (DOC), contrôle qualité (QA). Si votre mission n'a pas fait travailler un développeur, comparez avec la capture de référence.; Passez au thème Cosmos (Réglages > Apparence) et vérifiez que les pastilles restent lisibles.
- **expected** : Chaque étoile d'agent dit son rôle d'un coup d'œil (pictogramme + badge + accent), le responsable se repère à son drapeau, rien n'exige d'ouvrir un détail.
- **reference_captures** : evidence/sandbox-01-graph-circuit.png; evidence/sandbox-02-graph-cosmos.png; evidence/test-01-roles-relations-circuit.png; evidence/test-02-roles-relations-cosmos.png
- **note** : Captures sandbox : la mission « Comparer Postgres, SQLite, DuckDB » est entièrement réelle (cerveau sonnet : Mission Owner, trois recherches web en confrontation, un contrôle qualité). La mission « Choisir une base de données » est semée par les vraies routes de Core avec les vrais faits du hook, pour réunir DEV, DOC, un échange, une délégation et un relais (voir LOG.md).

### HV-ORG-09-02 — Slice 09-task-graph-ui

- [ ] **À vérifier** : Distinguish Delegation, Communication, Adversary, QA and Handoff links visually; confirm Adversary and QA cannot be confused.

**Comment**

- **where** : Même écran que HV-ORG-09-01.
- **steps** : Repérez les cinq figures : délégation = trait plein avec flèche pleine vers celui qui reçoit la sous-mission, pastille ronde à l'arborescence ; contrôle qualité = tirets avec chevron ouvert vers le travail relu, pastille carrée à la loupe ; relais = perles avec double chevron vers le successeur, pastille allongée « » » ; confrontation = double rail sans flèche entre les concurrents, pastille au double bord et aux lames croisées ; échange entre agents = trait fin sans flèche, pastille en bulle.; Comparez la confrontation et le contrôle qualité : trait (double rail plein / tirets), bout (aucun / chevron), pastille (lames croisées / loupe), couleur (corail / vert) — quatre différences, la couleur n'est pas la seule.; Comparez une confrontation close et un contrôle qualité clos : chacun garde sa forme (double bord / carré arrondi simple) ; l'état clos se lit à l'opacité et à la petite coche, jamais à un pointillé.; Survolez ou passez le focus clavier sur une pastille : son nom dit la nature, qui agit sur qui et l'état (par exemple « Contrôle qualité : … relit … · close, remarques »).; Activez les couleurs forcées de Windows (contraste élevé) : les figures restent distinctes par le trait, le bout et la forme de la pastille.
- **expected** : Les cinq relations se reconnaissent sans légende, la confrontation (concurrence entre pairs) et le contrôle qualité (relecture dirigée) ne se confondent jamais.
- **reference_captures** : evidence/sandbox-01-graph-circuit.png; evidence/sandbox-08-forced-colours.png; evidence/test-01-roles-relations-circuit.png; evidence/test-10-forced-colours.png

### HV-ORG-09-03 — Slice 09-task-graph-ui

- [ ] **À vérifier** : Click/focus the Communication relation message affordance and verify the correct readable relation board opens and keyboard navigation works.

**Comment**

- **where** : Même écran, avec une mission qui a un échange entre agents (pastille en bulle). Si votre mission n'en a pas, utilisez le bac à sable décrit dans LOG.md (Slice 09).
- **steps** : Cliquez la pastille en bulle : le panneau « Tableau · Échange entre agents » s'ouvre à droite avec l'objet de l'échange, la mission (objectif, origine, état), les participants (rôle, position, statut) et les messages dans l'ordre, chacun avec son type, son auteur et l'heure.; Fermez (×), puis au clavier : Tab jusqu'aux pastilles (un seul arrêt), flèches pour passer de l'une à l'autre, Entrée sur la bulle. Le titre du tableau prend le focus.; Tab jusqu'au premier message, puis flèches haut et bas, Début, Fin : le focus passe d'un message à l'autre et reste visible.; Laissez le tableau ouvert pendant que les agents publient : un nouveau message s'ajoute dans les 5 s sans déplacer votre focus.; Ouvrez une pastille, puis une autre aussitôt (avant que la première ait fini de lire) : le tableau montre la seconde relation, jamais un « chargement » qui ne finit pas ; une lecture sans réponse finit en erreur avec « Réessayer » après 15 s.; Échap ferme le tableau et rend le focus à la pastille. Ouvrez aussi la pastille d'une confrontation : son tableau dit le gagnant retenu et la conclusion.
- **expected** : La bonne relation s'ouvre, son tableau est lisible (messages délibérés seulement, jamais de raisonnement privé), et tout se fait au clavier.
- **reference_captures** : evidence/sandbox-03-board-keyboard.png; evidence/sandbox-04-board-arrows.png; evidence/sandbox-05-board-adversary.png; evidence/test-03-board-open-keyboard.png; evidence/test-04-board-loading.png; evidence/test-05-board-error.png; evidence/test-06-board-empty.png; evidence/test-11-race-fixed.png; evidence/sandbox-fix-race.png

### HV-ORG-09-04 — Slice 09-task-graph-ui

- [ ] **À vérifier** : Observe a mission evolve and confirm only actual agents/relations appear; no speculative future plan nodes are shown.

**Comment**

- **where** : Même écran, pendant qu'une mission travaille.
- **steps** : Lancez la demande de HV-ORG-09-01 et regardez le Board pendant la mission : une étoile n'apparaît que quand son agent est lancé, un fil et sa pastille seulement quand la relation existe entre deux agents déjà présents.; Vérifiez qu'aucune étoile ni pastille n'annonce une étape à venir (pas de « prochain agent », pas de relation prévue).; À la fin, les étoiles et relations de la mission restent (historique), une relation close a un trait atténué et une pastille atténuée avec une petite coche ; après un relais, le drapeau passe au successeur et le prédécesseur garde son rôle sans drapeau.; Relancez Core (vous) : les étoiles de la mission montrent « état inconnu depuis le redémarrage » (?), jamais « en cours » ; le tableau d'une relation dit « hors du suivi vivant » pour ses participants. Une mission restée ouverte sans agent connu se lit « état inconnu » sur la pastille du responsable après 10 minutes.
- **expected** : Le graphe ne montre que l'exécution réelle, en direct et en historique, sans nœud futur.
- **reference_captures** : evidence/sandbox-live0-graph.png; evidence/sandbox-01-graph-circuit.png; evidence/sandbox-restart-graph.png; evidence/sandbox-restart-board.png; evidence/sandbox-unknown-graph.png; evidence/test-07-live-unknown.png

### HV-ORG-09-05 — Slice 09-task-graph-ui

- [ ] **À vérifier** : At 200% zoom and a dense graph, confirm role labels, relation affordances and shell controls remain usable without major overlap.

**Comment**

- **where** : Même écran, navigateur zoomé à 200 % (Ctrl et +), et un Board qui porte plusieurs missions.
- **steps** : À 200 %, vérifiez que les pastilles de rôle restent lisibles (l'origine du responsable disparaît de la pastille ; elle reste dans le nom et le tableau) et que les pastilles de relation sont plus petites mais cliquables, jamais l'une sur l'autre.; Ouvrez un tableau à 200 % : il prend la largeur de la page, défile, et les commandes du haut (lanceur) restent atteignables.; Avec plusieurs missions sur le Board, vérifiez qu'aucune pastille de relation ne cache une autre pastille et que la carte Board, le Chat et le lanceur restent utilisables.; À 100 %, sur une équipe neuve (lancée après cette version), vérifiez qu'aucune pastille de relation ne couvre une pastille de rôle, l'étiquette du responsable ni une autre pastille. À 200 %, notez ce qui reste (voir residual_gaps).
- **expected** : Rôles, pastilles de relation et commandes de la coque restent utilisables à 200 % et dans un graphe dense, sans chevauchement majeur.
- **reference_captures** : evidence/sandbox-06-zoom200.png; evidence/sandbox-07-zoom200-board.png; evidence/test-08-dense-200pct.png; evidence/test-09-dense-200pct-board.png; evidence/test-12-fresh-team-100pct.png; evidence/sandbox-fix-fresh-team.png
- **residual_gaps** : Une équipe placée avant cette version garde ses places enregistrées : ses pastilles peuvent se recouvrir, rien n'est déplacé.; À 200 % de zoom, la scène se resserre (les unités valent deux fois moins de pixels) alors que pastilles et étiquettes gardent leur taille : une pastille de relation peut couvrir une étiquette ou une pastille de rôle quand ses fils sont plus courts que la pastille ; deux pastilles de relation gardent leur écart.; Gravitation allumée : les pastilles sont recalculées chaque seconde et glissent ; un liseré de 1 à 2 px peut apparaître pendant la glissade (mesuré : ≤ 48 px² dans le test).

### HV-ORG-10-01 — Slice 10-agent-roles-settings-ui

- [ ] **À vérifier** : Open Settings > agent roles and confirm the role catalogue is visually structured, readable and consistent with graph identity rather than a raw wall of prompt text.

**Comment**

- **where** : Votre Control Center habituel (http://127.0.0.1:17654/) une fois la branche fusionnée et JARVIS relancé par vous ; ou un bac à sable lancé depuis le worktree par evidence/sandbox.ps1 (JARVIS_DATA_ROOT et JARVIS_RUNTIME_DIR temporaires, JARVIS_CORE_PORT=28653, JARVIS_UI_PORT=28654, JARVIS_VISUALIZER_ENABLED=0, JARVIS_OPEN_BROWSER=0), page http://127.0.0.1:28654/.
- **steps** : Ouvrez les Réglages (roue d'outils > Paramètres, ou le bouton Réglages), puis l'onglet « Sous-agents », après « Mémoire ».; Vérifiez que la liste montre les 7 rôles, chacun avec un pictogramme, un badge de 2 à 4 lettres (INT, DOC, WEB, DEV, CPT, DIR, QA), son libellé et son marqueur entre crochets.; Vérifiez que deux rôles se distinguent sans la couleur : pictogramme et badge différents.; Parcourez la liste au clavier : Tab jusqu'à la liste, puis flèches haut et bas, Début, Fin ; la fiche suit et le focus reste visible.; Vérifiez qu'aucun texte d'instructions n'est déplié par défaut : il est derrière « Afficher et modifier les instructions (N caractères) ».; Changez de thème (onglet Apparence : Circuit imprimé puis Cosmos) et revenez : l'onglet reste lisible dans les deux.; Rétrécissez la fenêtre à environ 760 px de large : l'onglet « Sous-agents » reste visible dans la barre d'onglets, la liste passe au-dessus de la fiche ; cliquez un rôle : la fiche vient à l'écran, focus sur son titre, et « Revenir à la liste des rôles » ramène à la liste.
- **expected** : Un catalogue structuré et facile à parcourir, une identité (pictogramme, badge, accent) cohérente d'un rôle à l'autre, aucun mur de texte.
- **reference_captures** : evidence/01-catalogue-circuit-research-lead.png; evidence/03-catalogue-cosmos-qa-alias.png; evidence/04-clavier-focus-web-research.png; evidence/09-etroit-760.png; evidence/13-etroit-760-fiche.png; evidence/12-couleurs-forcees-contraste.png
- **note** : Le graphe des tâches ne lit pas encore ces jetons (Slice 08) : la table --role-accent-* de control_center.html est celle qu'il devra reprendre. Le Control Center n'a pas de thème clair : les deux thèmes livrés sont sombres.

### HV-ORG-10-02 — Slice 10-agent-roles-settings-ui

- [ ] **À vérifier** : Inspect a role and verify mission, skills/loadout, capabilities and Work Methods are understandable; unavailable/edit-disabled fields are honestly read-only.

**Comment**

- **where** : Même écran que HV-ORG-10-01.
- **steps** : Choisissez « Direction de recherche » : lisez mission, « Quand l'employer », capacités (Lance des agents : Oui, Mission Owner : Peut porter une mission), savoirs (loadout research) et la note « pas encore proposé au cerveau ».; Dans Work Methods, dépliez « Recherche approfondie » (par défaut, apposée) : principes, critères de qualité, relations à envisager (délégation, contrôle qualité).; Dans « Consigne transmise au sous-agent », vérifiez l'ordre : 1 vos instructions (modifiable), 2 capacités du rôle (générées), 3 Work Method par défaut (non modifiable), avec la mention qu'elle s'ajoute après vos instructions.; Vérifiez que Capacités et Work Methods portent « lecture seule » et n'offrent aucun champ modifiable.; Choisissez « Contrôle qualité » : l'alias [reviewer] est indiqué comme alias historique.; Choisissez « Conceptualisation », dépliez les instructions, modifiez le texte, enregistrez : message « Instructions enregistrées… », étiquette « modifié » dans la liste. Puis « Revenir au défaut » (deux clics) : l'étiquette disparaît.; Facultatif (conflit) : ouvrez le même onglet dans deux fenêtres, enregistrez un texte dans la première, puis un autre dans la seconde sans recharger : la seconde dit que les instructions ont été modifiées ailleurs et garde votre texte dans le champ.
- **expected** : Chaque champ est compréhensible ; seules les instructions sont modifiables et le disent ; la méthode non modifiable est annoncée après elles ; un conflit ne perd pas le texte saisi.
- **reference_captures** : evidence/02-work-method-ouverte-circuit.png; evidence/05-edition-brouillon.png; evidence/06-edition-enregistree.png; evidence/07-conflit-revision.png; evidence/08-instances-fixture.png; evidence/10-erreur-registre.png; evidence/11-reprise-apres-erreur.png
- **note** : 08-instances-fixture.png montre des instances simulées (réponse de /api/agent/tasks remplacée dans la page) : aucune tâche réelle ne tournait dans le bac à sable. Sur votre poste, remettez « Conceptualisation » au défaut après l'essai si vous ne voulez pas garder le texte d'essai.

### HV-ORG-11-01 — Slice 11-output-quality-prefab-delivery

- [ ] **À vérifier** : Ask for a serious comparative research result and verify JARVIS delivers a polished structured comparison/report using appropriate prefab surfaces rather than an ugly raw text dump.

**Comment**

- **where** : Votre JARVIS habituel une fois la branche fusionnée et JARVIS relancé par vous (le hook, la consigne et les outils d'affichage ne changent qu'au redémarrage complet) ; ou le bac à sable evidence/sandbox.py lancé depuis le worktree (Core 29653, Control Center 29654, JARVIS_DATA_ROOT et JARVIS_RUNTIME_DIR temporaires, JARVIS_VISUALIZER_ENABLED=0, JARVIS_OPEN_BROWSER=0, cerveau haiku), page http://127.0.0.1:29654/.
- **steps** : Vérifiez que la scène est allumée (Réglages > Scène) : sans elle, les outils d'affichage ne sont pas déclarés et la restitution passe en Markdown.; Demandez à voix ou dans le chat une comparaison sérieuse confiée à un Mission Owner, par exemple : « Lance un [general] [research-lead] : compare pydantic, attrs et marshmallow sur la performance, l'ergonomie, la validation, l'écosystème et la licence, pour choisir celle de mon prochain service. » (le cerveau ne propose pas encore research-lead de lui-même : Slice 07).; Attendez la fin de la tâche (panneau Agents), puis regardez la scène : une fenêtre « tableau » (jarvis.table) doit porter la comparaison, et, si la recommandation est longue, une fenêtre « document » (jarvis.document) à côté.; Agrandissez chaque fenêtre si besoin : en-têtes lisibles, cellules courtes qui se replient, défilement dans la fenêtre, aucune colonne impossible à lire.; Écoutez ou lisez la réponse du cerveau : elle résume la conclusion en quelques phrases et ne relit pas le tableau.; Demandez ensuite, sans nommer de prefab, un rapport, un état des lieux et un bilan (« Lance un [general] [research-lead] : fais un état des lieux des solutions locales de détection de mot d'éveil ») et vérifiez que chacun arrive dans une fenêtre document structurée (titres, listes, sources ou limites), pas en mur de texte.
- **expected** : Comparaison et rapport livrés dans des surfaces structurées et soignées (tableau, document), que vous jugez agréables à lire ; aucun mur de texte brut à l'écran.
- **reference_captures** : evidence/01-comparaison-table-et-document.png; evidence/02-rapport-document.png; evidence/03-etat-des-lieux-document.png; evidence/04-bilan-document.png
- **note** : Capture de référence : bac à sable du 2026-10-20, fenêtres créées par le Mission Owner (haiku) à leur taille par défaut. La dernière colonne du tableau y est coupée à droite par la largeur par défaut de la fenêtre : dites si c'est acceptable une fois la fenêtre agrandie, ou si la largeur par défaut d'un tableau doit changer (suite hors Slice 11 : nouvelle version du prefab de base ou géométrie conseillée). Reprise QA (2026-10-20, haiku, sans prefab imposé) : rapport, état des lieux et bilan affichés chacun en jarvis.document (3 sur 3).

### HV-ORG-11-02 — Slice 11-output-quality-prefab-delivery

- [ ] **À vérifier** : Ask for a trivial short result and confirm JARVIS does not force an unnecessary heavy report/prefab.

**Comment**

- **where** : Même installation que HV-ORG-11-01.
- **steps** : Posez une question courte : « Combien de fichiers Markdown y a-t-il dans docs/legacy ? » ; la réponse est un nombre, sans fenêtre nouvelle dans la scène.; Confiez une tâche courte à un Mission Owner : « Lance un [code] [coder] qui compte les fichiers Markdown de docs/legacy et me donne le nombre. » ; la réponse reste un nombre, sans fenêtre tableau ni document.; Facultatif, repli : « Lance un [general] [research-lead] : compare VS Code, Zed et Neovim sur dix critères, un seul tableau jarvis.table avec une colonne par critère, n'essaie aucune autre forme d'affichage. » Le tableau est refusé (8 colonnes au plus) : la réponse doit dire que rien n'est affiché, en donner la cause, et livrer la comparaison sous une forme lisible (tableau Markdown dans le chat). Le journal d'exécution (trace.jsonl) garde le refus, display.tool_refused, et display.prefab_fallback.
- **expected** : Une question simple reçoit une réponse simple, sans artefact ; un affichage refusé est dit honnêtement et le contenu arrive quand même sous une forme lisible.
- **reference_captures** : 
- **note** : Trace de référence (bacs à sable du 2026-10-20, haiku) : question directe → « 6 » sans sous-agent ; [code] [coder] → « 6 » et [general] [research-lead] « licence de Kokoro en une phrase » → une phrase, aucun appel d'outil d'affichage (2 sur 2) ; repli : display.tool_refused (prefab_invalid) puis display.prefab_fallback, la note dit l'état réel de l'écran, compte rendu en tableau Markdown avec la cause.

### HV-ORG-12-01 — Slice 12-work-method-learning

- [ ] **À vérifier** : Promote a real Work Method candidate yourself from Settings > Sous-agents and confirm nothing was promoted before your action, the evidence and thresholds are understandable, and the new version is published without rewriting the old one, and that the next sub-agent of that role receives the promoted version.

**Comment**

- **where** : Votre Control Center habituel (http://127.0.0.1:17654/) une fois la branche fusionnée et Core relancé par vous : votre base est en v9, ce seul redémarrage applique v10 puis v11 après UNE sauvegarde jarvis.sqlite3.v9.bak (aucun .v10.bak) ; retour arrière : docs/local-data.md (restaurer .v9.bak, historique et versions promues depuis perdus). Ou un bac à sable lancé depuis le worktree par evidence/sandbox_trial.py (start, seed 3, page http://127.0.0.1:31654/, stop).
- **steps** : Avant toute action, ouvrez GET /api/work-methods : seules les versions livrées (…@1) y figurent.; Ouvrez Réglages > Sous-agents > « Direction de recherche » et lisez le bloc « Approches observées » : statut, raison, comptes (missions closes, bonnes, mauvaises, non notées) et nombre de preuves.; Vérifiez qu'une approche revenue une seule fois, ou sans verdict QA, est « En observation » et n'offre aucun bouton.; Sur une approche « Candidate », cliquez « Promouvoir en <id>@<version> », lisez la confirmation (version publiée, relations, ancienne version non réécrite), puis confirmez.; Vérifiez la notice « Méthode … publiée », le statut « Promue », puis GET /api/work-methods : la nouvelle version est là, l'ancienne aussi, avec provenance promoted, promoted_by user et des evidence_refs (ids de missions et de relations QA).; Lancez ensuite un sous-agent de ce rôle (par exemple « [general] [research-lead] … ») : sa consigne porte « MÉTHODE DE TRAVAIL : … (deep-research@2) » et Réglages > Sous-agents montre la méthode « version promue ».
- **expected** : Aucune promotion sans votre clic confirmé ; les preuves et les seuils se comprennent ; la nouvelle version s'ajoute sans écraser l'ancienne.
- **reference_captures** : evidence/01-candidate.png; evidence/02-confirmation.png; evidence/03-promue.png
- **note** : Une méthode neuve (candidate sans méthode de base) ne se promeut que par l'API et n'est rattachée à aucun rôle (docs/work-methods.md › Application).

### HV-ORG-13-01 — Slice 13-integration-rollout-quality-docs

- [ ] **À vérifier** : End-to-end: start from a code mission that organically requires research, a competing alternative, QA and Handoff; confirm the final graph tells that actual history clearly.

### HV-ORG-13-02 — Slice 13-integration-rollout-quality-docs

- [ ] **À vérifier** : After mission completion, confirm non-ephemeral history remains inspectable while ephemeral one-shot agents are absent.

### HV-ORG-13-03 — Slice 13-integration-rollout-quality-docs

- [ ] **À vérifier** : Review one multi-day/long-running style simulated mission and confirm nested Mission Owners are understandable without presenting Mission Owner as a role.

### HV-ORG-13-04 — Slice 13-integration-rollout-quality-docs

- [ ] **À vérifier** : Review final representative report/comparison artifacts and approve visual/presentation quality.

