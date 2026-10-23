# Recette humaine — Architecture & Agents

Tâche `jarvis-architecture-agents-settings-editor`, rédigée à la Slice 08 (2026-10-24) une fois la validation machine
épuisée (`slices/08-final-integration-e2e-qa/EVIDENCE.md`). Ces vérifications portent sur ce qu'un test ne sait pas
juger : lisibilité du graphe, ergonomie de la fenêtre, impression d'ensemble, et l'essai réel sur votre poste. Chaque
check dit quoi faire, ce que vous devez voir et où regarder. Cochez la case quand le résultat est celui attendu ;
sinon notez ce que vous avez vu à côté.

## Avant de commencer

- [ ] **Fusion puis redémarrage, par vous.** La tâche ne change aucun schéma de base (`jarvis.sqlite3`,
  `scene.sqlite3`) : aucune migration. Elle change des modules servis par le Control Center et Core
  (`control_center.py`, `control_center.html`, `routing_hook.py`, `claude_local.py`, `brain_config*.py`,
  `architecture_graph*.py`, `realtime_*.py`…) : redémarrez JARVIS (Core, Control Center, Voice) vous-même une fois la
  branche fusionnée, puis rechargez la page. Aucun agent ne le fera à votre place.
- [ ] Vos réglages ne sont pas réécrits à l'ouverture. De nouveaux fichiers n'apparaissent dans le dossier
  d'exécution de JARVIS que lorsque vous changez quelque chose : `brain-config.json` (tendance de délégation),
  `subagent-role-routing.json` (modèles d'un rôle), `architecture-layout.json` (position des modules),
  `brain-delegation-launched.json` (écrit à chaque lancement du cerveau).

## HV-ARCH-001 — Le graphe se lit comme l'architecture réelle

1. Ouvrez Paramètres › Architecture & Agents › Architecture.
2. Parcourez le graphe sans lire d'aide.

Résultat attendu :
- [ ] Vous reconnaissez votre architecture vocale (Duplex chez vous) : Micro, Voice Brain, Core Brain, Tool Brain,
  Sous-agents, Haut-parleurs, et rien d'autre.
- [ ] Le sens des flèches, les cadenas (liaison obligatoire), les liaisons coupées (pointillés / « désactivée ») et
  l'entrée/sortie audio se comprennent sans explication.
- [ ] Les états sont vrais : Core « Actif » quand Core tourne, Voice actif quand vous parlez avec JARVIS.

Où regarder : le canevas et l'inspecteur à droite (cliquez une étiquette de liaison).

## HV-ARCH-002 — La fenêtre d'un cerveau, au bon endroit

1. Clic droit sur Core Brain (ou bouton « … », ou focus sur le module puis Maj+F10) › « Configurer… ».
2. Déplacez la fenêtre par sa poignée ; parcourez-la au clavier (Tab reste dans la fenêtre) ; fermez par Échap.
3. Rouvrez le menu de Core au clavier (Maj+F10) puis appuyez sur Échap.

Résultat attendu :
- [ ] La fenêtre s'ouvre près du graphe sans couvrir Core, se déplace, et paraît liée au module (pas une page à part) ;
  aucun onglet « Brains » n'existe.
- [ ] Le CLI affiché pour Core est celui qui tourne, **sans** la mention « indisponible » ; Codex apparaît comme choix
  possible s'il est installé.
- [ ] Échap dans la fenêtre la ferme et laisse les Réglages ouverts ; Échap dans le menu du module ferme le menu
  seulement (focus rendu au module) ; une Échap de plus ferme les Réglages.

Où regarder : la fenêtre « Core Brain » (sections Mission, Modèle, Tendance de délégation, Instructions, Connexions).

## HV-ARCH-003 — Rôles des sous-agents compréhensibles, modèles découvrables

1. Onglet Sous-agents. Parcourez les sept rôles (Interviewer, Recherche documentaire, Recherche web,
   Développement, Conceptualisation, Direction de recherche, Contrôle qualité).
2. Sur « Contrôle qualité », ouvrez « Modèles du rôle ».

Résultat attendu :
- [ ] Chaque rôle dit sa mission, quand l'employer, son marqueur ; les instructions sont éditables.
- [ ] Vous trouvez où choisir le modèle d'un rôle, l'ordre de préférence et le repli, et voyez s'il hérite d'un profil.
- [ ] Aucune commande, chemin, permission ni réglage de ton/politesse n'apparaît ici (ils sont dans Avancé ›
  Runtime & CLI et Personnalisation › Comportement).

## HV-ARCH-004 — Comparaison avec `references/architecture-ui-reference.png`

1. Ouvrez l'onglet Architecture, puis la fenêtre de Core, à côté de la référence.

Résultat attendu :
- [ ] Le graphe réel domine la page ; le style vitré / néon est cohérent avec le reste des Réglages (il est plus sobre
  que la maquette, par choix des jetons de thème).
- [ ] La fenêtre s'intègre proprement ; aucune topologie décorative (pas de cartes « État du système », « Règles »,
  « Actions rapides », journal ou légende inventés).
- [ ] Le rendu vous convient, ou vous notez ce qui manque (ces cartes absentes sont une décision : elles n'ont pas de
  donnée réelle).

Capture machine pour mémoire : `slices/08-final-integration-e2e-qa/evidence/s08-architecture.png`, `s08-core-window.png`.

## HV-ARCH-005 — Comparaison avec `references/subagents-ui-reference.png`

Résultat attendu :
- [ ] La configuration des rôles reste lisible malgré la densité ; les sept rôles affichés sont ceux de JARVIS (pas
  ceux de la maquette).
- [ ] Ni onglet Brains, ni contrôles de personnalité, ni statistiques fictives.

Capture machine : `slices/08-final-integration-e2e-qa/evidence/s08-subagents.png`.

## HV-ARCH-006 — Essai réel : délégation « Jamais » puis « Standard » (votre JARVIS, après redémarrage)

1. Fenêtre de Core › Tendance de délégation › « Jamais » › Appliquer.
2. À la voix ou au chat, demandez un travail qui part d'habitude en sous-agent (par exemple « cherche sur le web les
   horaires du musée d'Orsay »).
3. Remettez « Standard » › Appliquer, puis redemandez la même chose.

Résultat attendu :
- [ ] En « Jamais », JARVIS ne lance aucun sous-agent et le dit franchement (délégation désactivée) ; le graphe montre
  la liaison Core → Sous-agents coupée.
- [ ] Revenu en « Standard », le graphe indique que la remise attend le prochain démarrage du cerveau tant que le CLI
  lancé en « Jamais » tourne ; après un redémarrage de JARVIS, la demande repart en sous-agent comme avant.

Où regarder : la réponse de JARVIS ; la liaison Core → Sous-agents ; le Centre d'état (sous-agents en cours).

## HV-ARCH-007 — Essai réel : modèle d'un rôle (votre JARVIS)

1. Sous-agents › Contrôle qualité › Modèles du rôle : mettez un seul candidat, par exemple Claude Code · un modèle
   Haiku de la liste, enregistrez.
2. Demandez à JARVIS de faire relire quelque chose par un sous-agent de contrôle qualité.

Résultat attendu :
- [ ] Le sous-agent démarre et rend son résultat (avant la Slice 08, un rôle réglé ne démarrait plus du tout).
- [ ] Il tourne sur la **famille** choisie (Haiku). Attention : l'outil Agent du CLI n'accepte qu'une famille
  (haiku, sonnet, opus, fable) ; le CLI choisit la version courante de cette famille, qui peut différer de la version
  exacte affichée dans la liste. Dites si cela vous convient.
- [ ] Les autres rôles n'ont pas changé ; « Restaurer » remet l'héritage.

Où regarder : le détail du sous-agent dans le Centre d'état ; `trace.jsonl` (`agent.routing.decided` : `model`,
`agent_model`) si vous voulez la preuve.

## HV-ARCH-008 — Essai réel : couper la délégation de la voix (votre JARVIS)

1. Architecture : cliquez l'étiquette de la liaison Voice → Core (« requête ») › Désactiver. Voice se relance seul
   (bascule demandée), la conversation continue.
2. Posez une question qui demanderait le cerveau (outil, recherche).
3. Réactivez la liaison.

Résultat attendu :
- [ ] Liaison coupée : la voix répond seule (analyse sans outils) et ne prétend pas avoir lancé de travail.
- [ ] Liaison réactivée : la délégation au cerveau revient après la relance de Voice.
- [ ] La liaison Micro → Voice refuse d'être coupée, avec sa raison.

## Points ouverts à trancher (produit)

- Version exacte ou famille pour le modèle d'un rôle (HV-ARCH-007).
- I-001 S01-1 : faut-il marquer « relance de la voix attendue » sur une liaison vocale quand Voice tourne sur une
  configuration différente pour une autre raison (contredit le contrat actuel) ?
