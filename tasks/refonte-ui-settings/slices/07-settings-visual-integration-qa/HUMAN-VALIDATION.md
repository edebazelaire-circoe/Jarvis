# Validation humaine — refonte des Réglages (Slice 07, convergence)

Checks : `HV-SETTINGS-FINAL-001` (les cinq paires maquette ↔ capture, un seul système visuel) et
`HV-SETTINGS-FINAL-002` (parcours dans l'application, réactivité, cohérence). Branche `task/refonte-ui-settings`.

Les captures finales sont produites par `tests/unit/test_settings_page_layout_browser.py`
(`test_final_captures_of_the_five_views_have_no_horizontal_overflow`, Control Center isolé, données de test
déterministes : faux Core mémoire `_memory_center_fixture.py`, journal d'architecture figé) avec
`JARVIS_BROWSER_SHOTS=<dossier>`. Les captures de l'essai réel (vrai Core en bac à sable) sont dans `evidence/reel/`.

## 1. Paires maquette ↔ capture (tailles exactes des maquettes)

| Vue | Maquette | Capture finale | Largeur étroite (1280×800) |
| --- | --- | --- | --- |
| Personnalisation | `../../references/ui/01-personnalisation.png` (1672×941) | `evidence/personnalisation-1672x941.jpg` | `evidence/personnalisation-1280x800.jpg` |
| Architecture & Agents › Sous-agents | `../../references/ui/02-architecture-agents-subagents.png` (1254×1254) | `evidence/sous-agents-1254x1254.jpg` | `evidence/sous-agents-1280x800.jpg` |
| Architecture & Agents › Architecture (fenêtre du cerveau ouverte) | `../../references/ui/03-architecture-agents-architecture.png` (1254×1254) | `evidence/architecture-1254x1254.jpg` | `evidence/architecture-1280x800.jpg` |
| Mémoire & Connaissances › Mémoire | `../../references/ui/04-memory-settings.png` (1254×1254) | `evidence/memoire-1254x1254.jpg` | `evidence/memoire-1280x800.jpg` |
| Mémoire & Connaissances › Memory Center | `../../references/ui/05-memory-center.png` (1254×1254) | `evidence/memory-center-1254x1254.jpg` | `evidence/memory-center-1280x800.jpg` |

Aucun débordement horizontal de la page ni d'un conteneur des Réglages sur ces dix captures (mesure `OVERFLOW`,
assertion du test), console vide.

Essai réel (vrai Core en bac à sable, données réelles) : `evidence/reel/perso-profils.jpg`,
`evidence/reel/architecture-fenetre-1254.jpg`, `evidence/reel/sous-agents-1254.jpg`, `evidence/reel/memoire-1254.jpg`,
`evidence/reel/memory-center-1254.jpg`, `evidence/reel/memory-center-rappel-1254.jpg` (candidat accepté puis retrouvé
par le test de rappel) ; script et journal : `evidence/reel/sandbox_s07.py`, `evidence/reel/sandbox-log.txt`.

## 2. Ce qui rend les cinq vues cohérentes

- **Une seule présentation de page** pour les trois catégories des maquettes : × rond en haut à gauche, fil d'Ariane
  « JARVIS › Paramètres » (Paramètres ramène au hub), grand titre léger, phrase, filet, puis onglets de page
  (pictogramme + libellé, onglet actif en verre lumineux). Plus de rail des catégories sur ces pages. Personnalisation
  garde sa page propre ; Architecture & Agents et Mémoire & Connaissances sont le même shell présenté en page pleine
  (`docs/settings/settings-shell.md` § 1 bis). Interface & Interactions, Plugins & MCP et Avancé & Diagnostics gardent
  le shell à rail (hors maquettes).
- **Un seul jeu de primitives** : panneaux verre `.set-panel`, médaillons, onglets `.set-tab`, interrupteurs, curseurs,
  cartes de choix, pastilles, badges, boutons et champs de la fondation (Slice 01) sur les cinq vues ; Mémoire et
  Memory Center y ont migré à cette Slice (ils avaient leurs propres cartes, interrupteurs et onglets).
- **Une seule zone de défilement par page** : Personnalisation défile en entier ; Architecture & Agents et Mémoire &
  Connaissances gardent leur en-tête et leurs onglets en place, seul le contenu défile ; aucun défilement horizontal.
- **Couches** : × au-dessus du contenu qui défile, fenêtre du cerveau ouverte sous les onglets et le ×, menus et
  panneaux flottants au registre des couches (`test_control_center_shell_layers.py` vert).

## 3. Écarts restants voulus (faute de donnée ou d'action réelle)

Rien n'est affiché qui ne soit réellement appliqué ou mesuré ; ces éléments des maquettes n'ont pas de donnée derrière.

| Vue | Écart | Pourquoi |
| --- | --- | --- |
| Toutes (sauf Personnalisation) | pas d'avatar en haut à droite | aucune donnée de profil réelle hors de Personnalisation |
| Personnalisation | pas de bouton Écouter, de volume, de débit, de « Ton général », d'« Humour », de « Comportement global », de préréglages Technique/Créatif, de quatre interrupteurs de proactivité, de descriptions de voix, de profils prédéfinis | aucun réglage serveur (`docs/settings/personalization-page.md` § 2) |
| Sous-agents | pas d'onglet « Brains », pas de « 98 % », de Priorité, d'« Ajouter un sous-agent », d'interrupteurs de politique, de coût/délai/créativité/collaboration, de logos de modèles, de pictogrammes d'outils | décision de la tâche (pas d'onglet Brains) et aucune donnée (`docs/settings/architecture-agents.md` § 1) |
| Architecture | pas de latence moyenne, requêtes/min, presets charger/sauvegarder, puces de responsabilités, filtre « Tous les modules », pause du journal, curseur continu de délégation | aucune donnée ni action ; la délégation a 5 niveaux (`docs/settings/architecture-tab.md` § 3) |
| Mémoire | pas de profil de rappel Rapide/Équilibré/Approfondi ; curseur à 10 et non 20 ; ligne « Portées » remplacée par « Mémoire privée » | aucun réglage derrière un profil (preset décoratif interdit) ; borne servie ; donnée réelle (`docs/settings/memory.md`) |
| Memory Center | pas de « taux de rappel », de rétention en %, de cases de sélection multiple | aucune mesure ni action groupée côté Core |
| Memory Center | test de rappel limité à 10 souvenirs ; libellés des niveaux, rétentions et types écrits dans le navigateur | servir ces bornes et libellés demande un changement de contrat serveur (laissé hors de cette Slice) |
| Mémoire (1254×1254) | colonnes déséquilibrées (la colonne de droite, qui porte en plus le résumé et l’appel au Memory Center, descend plus bas que la gauche) ; l'appel au Memory Center et la bande Avancé passent sous le pli | coût de l'en-tête fixe (décision n° 2 du § 4) : environ 300 px pris par le fil d'Ariane, le titre et les onglets ; les cartes gardent leur contenu réel plutôt qu'un résumé tronqué |
| Architecture (fenêtre du cerveau) | la fenêtre flottante chevauche le bas des cartes et le centre du canevas | règle de placement de la Slice 04 : elle s'ouvre du côté de son nœud qui a le plus de place, sous les onglets et le × (`architecturePanelZone`) ; elle ne couvre jamais le titre ni l'onglet actif. Lié à la décision n° 2 (l'en-tête fixe réduit la hauteur disponible) |
| Sous-agents (1254×1254) | synthèse en 2×2 au lieu d'une ligne de 4 ; la matrice de routage et les règles globales passent sous le pli | largeur utile après marges et en-tête fixe (décision n° 2) ; les tuiles restent lisibles plutôt que tassées sur une ligne |
| Plugins & MCP | interrupteur `.mcpp-switch` hors fondation | vue hors maquettes, contrat de feuille épinglé par ses tests ; sa migration serait une refonte de Plugins & MCP |

## 4. Décisions à faire valider par le Human

1. **Mise en page unique** (agent 0, LOG du 2026-10-24) : Architecture & Agents et Mémoire & Connaissances en page
   pleine sans rail ; changer de catégorie passe par « Paramètres » (le hub). Les trois autres catégories gardent le
   rail. À confirmer, ou étendre la page pleine aux trois autres.
2. **Défilement** : sur Architecture & Agents et Mémoire & Connaissances, l'en-tête (fil d'Ariane, titre, phrase) et
   les onglets restent en place et seul le contenu défile — sinon la fenêtre flottante d'un cerveau, fixe, recouvrait
   le titre et les onglets après défilement. Coût : à 1280×800, l'en-tête occupe environ 300 px. Alternatives : en-tête
   compact ou page entière qui défile avec une fenêtre du cerveau qui suit son nœud (changement du module S04).
3. **Pas d'onglet Brains** (Architecture & Agents) : un cerveau se configure dans sa fenêtre flottante (décision de la
   tâche, rappelée).
4. **Mémoire** : pas de profil de rappel décoratif ; maximum du curseur = borne servie (10) ; « Portées » remplacée
   par « Mémoire privée » ; `semantic_retrieval` et `consolidation` deviennent des alias de l'onglet Mémoire ;
   réglages d'opérateur (délai du rappel, sidecar Tencent) dans Avancé › Mémoire.
5. **Memory Center** : une seule maison, l'onglet des Réglages ; le bouton de Sessions & Boards y mène. Décision de
   candidat confirmée dans la carte puis envoyée de façon optimiste (refus : la carte revient avec la raison).
6. **Personnalisation** : écarts listés au § 3 (pas de contrôle sans réglage réel).
7. **Plugins & MCP** : interrupteur laissé hors fondation (§ 3).

## 5. Parcours à refaire dans l'application (HV-SETTINGS-FINAL-002)

Après redémarrage de JARVIS par vous (aucune migration de base dans cette tâche) :

1. Réglages (bouton ou `s`) → hub → Personnalisation : profil (ouvrir, Échap), un préréglage, « Paramètres » → hub.
2. Hub → Architecture & Agents : onglet Architecture, « … » sur Core Brain → Configurer : la fenêtre s'ouvre à côté du
   nœud, sous les onglets ; Échap la ferme, Échap suivant ferme les Réglages. Onglet Sous-agents : tableau de bord.
3. Hub → Mémoire & Connaissances : Mémoire, Connaissances, Memory Center (une note, un candidat Accepter → Confirmer,
   Test de rappel avec Entrée).
4. Liens : « Ouvrir les paramètres avancés » (le rail revient dans Avancé), Sessions & Boards › Memory Center.
5. Fenêtre plus étroite (1280×800 ou zoom 125 %) : pas de défilement horizontal, onglets qui passent à la ligne.
