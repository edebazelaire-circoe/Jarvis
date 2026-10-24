# Réglages : la page Personnalisation

**Statut :** contrat de surface (niveau 3 : routes serveur + tests navigateur).
**Introduit :** refonte des Réglages page par page, 2026-10-23 (première page : Personnalisation) ; maquette 01 et
primitives partagées : Slice 02 de refonte-ui-settings, 2026-10-24.
**S'appuie sur :** [`settings-shell.md`](settings-shell.md) (hub, shell), [`voice-audio.md`](voice-audio.md) (sections
détaillées de `voice_audio`), [`architecture-agents.md`](architecture-agents.md) (préférences de réponse).

La carte **Personnalisation** du hub (`voice_audio`) n'ouvre plus le shell : elle ouvre sa propre page,
`#overlay` › `section#settingsPerso` (`.overlay[data-view=perso]`), dessinée par `control_center_personalization.js`.
Les liens internes et la roue (« Réglages de la voix ») ouvrent toujours le shell directement.

## 1. Composition

Maquette : `tasks/refonte-ui-settings/references/ui/01-personnalisation.png` (1672×941). Depuis la Slice 02 de
refonte-ui-settings (2026-10-24), la page se compose des primitives partagées ([`visual-foundation.md`](visual-foundation.md)) :
vue `.set-view.set-perso` > `.set-page`, en-tête `.set-page-head` (`.set-crumb`, `.set-title`, `.set-lead`, `.set-rule`),
panneaux `JarvisSettingsUI.panel`, lignes `.set-row`, curseurs `range`, interrupteur `toggle`, zone de texte `textarea`,
choix `.set-choice`, panneau flottant `float` + `openFloat`, avatar `medallion`. Le CSS propre à la page (préfixe
`.perso-`, `control_center.html`) ne porte que la composition : colonnes, rangées des curseurs à crans, bouton et liste
des profils. Les anciennes classes doublons (`.perso-card`, `.perso-switch`, `.perso-seg`, `.perso-preset`,
`.perso-avatar`, `.perso-mini`…) sont supprimées ; un test le vérifie.

- En-tête : × en haut à gauche (ferme tout), fil d'Ariane « JARVIS › Paramètres » (le bouton « Paramètres » ramène
  au hub), titre, phrase, filet. Même en-tête, mêmes primitives (`.set-crumb button` compris) que les catégories en
  page pleine du shell, Architecture & Agents et Mémoire & Connaissances ([`settings-shell.md`](settings-shell.md)
  § 1 bis). En haut à droite, aligné sur le bord droit de la grille : le **profil actif**
  (médaillon à la teinte du profil, nom, chevron). Aucune citation ni slogan.
- Grille `.set-grid.perso-grid` de trois colonnes `.set-stack.set-span-4` ; le dernier panneau de chaque colonne
  s'étire, les bas s'alignent (enveloppe rectangulaire) :

  | Colonne | Panneaux |
  | --- | --- |
  | gauche | Voix · Réglages détaillés |
  | centre | Personnalité · Préférences rapides |
  | droite | Proactivité & rappels |

  Page (`.set-page`, 1600 px au plus ici) sous 1240 px : deux colonnes (gauche | centre, puis Proactivité sur toute la
  largeur, ses lignes en deux colonnes quand la place le permet) ; sous 640 px : une colonne. Jamais de défilement
  horizontal. À 1672×941, toute la grille tient dans la fenêtre.

## 2. Ce que chaque panneau écrit

Rien n'est affiché qui ne soit appliqué. Chaque contrôle s'enregistre dès qu'il change (charge **partielle** de
`POST /api/settings`, jamais le brouillon du shell) ; le panneau dit « Enregistrement… », « Enregistré. » ou le refus
du serveur, et un refus remet la valeur enregistrée. Toute attente a une échéance de 15 s (`DEADLINE_MS`) : lecture
sans réponse → message + Réessayer ; enregistrement sans réponse → message, puis la page **relit** les réglages
(l'écriture a pu avoir lieu) et le dit.

| Panneau | Réglage | Application |
| --- | --- | --- |
| Voix | `voice.settings.<pile en service>.voice` (catalogue `voice.stacks`), `…transcription_language` | prochain démarrage de Voice (badge) |
| Personnalité | `cli.behavior.response_verbosity`, `cli.behavior.politeness_formality` (choix fermés `cli.behavior.fields`) en curseurs à crans ; `cli.behavior.custom_instructions` (texte ≤ 1000 car., compteur, enregistré 1,2 s après la frappe ou à la sortie du champ) | à chaud |
| Préférences rapides | Concis, Détaillé, Équilibré, Formel : groupe radio `.set-choice` ; chacun écrit un couple verbosité + formalité existant, rien d'autre ; le préréglage qui correspond aux valeurs en vigueur est coché (aucun sinon) | à chaud |
| Proactivité & rappels | `agenda_reminders.*` : interrupteur général (`.set-switch`, « Activés / Coupés »), puis une ligne par délai ou heure ; éteint, les champs sont désactivés | à chaud |
| Réglages détaillés | aucun : une tuile par section enregistrée de `voice_audio` (registre), sauf `agent_behavior` que la page remplace ; un clic ouvre le shell sur la section | — |

**Curseurs à crans.** Un cran = une option du serveur, dans l'ordre servi, « Hériter » exclu (Longueur : Concise —
Équilibrée — Détaillée ; Ton et formalité : Direct — Courtois — Formel). Bornes et cran courant affichés,
`aria-valuetext` = libellé du cran. « Hériter » (aucune consigne) est un bouton à part (icône ↺) ; en « Hériter », le
curseur est neutre au cran médian et le libellé dit « Hériter » ; choisir un cran (souris, flèches, ou clic sur le cran
médian) écrit ce cran. Un texte d'instructions en cours de frappe **ou en cours d'envoi** survit au rendu déclenché par
un autre contrôle (avant la Slice 07, l'ancienne valeur revenait pendant l'envoi puis repartait au serveur à la sortie
du champ) ; un refus de l'envoi, lui, remet la valeur enregistrée. Les aides des rappels sont coupées à deux lignes :
le texte entier est en info-bulle (`title`), et lu en entier par `aria-describedby`. Les tuiles des Réglages détaillés
occupent la hauteur que la colonne donne à leur panneau (jusqu'à 64 px chacune) : plus de vide en bas du panneau.

**Écarts assumés avec la maquette** (aucune donnée côté runtime, rien n'est simulé) : bouton « Écouter », volume et
débit de la voix (Voice ne sait pas les appliquer) ; curseurs « Ton général » et « Humour » (aucun réglage) ; carte
« Comportement global » (Style de réponse = la longueur déjà présente ; Niveau de technicité et Domaines de focus
n'existent pas) : sa place accueille les **Réglages détaillés** ; préréglages « Technique » et « Créatif » (aucun couple
de choix fermés ne les rend fidèlement) remplacés par Équilibré et Formel ; interrupteurs « Suggestions proactives »,
« Automatisations contextuelles », « Analyse du contexte », « Mode discret » (aucune capacité) : la proactivité réelle
est celle des rappels d'agenda ; descriptions de voix (« Claire, naturelle… ») : le catalogue ne donne que des noms ;
profils prédéfinis (Décontracté, Efficace, Analytique) : seuls existent les profils créés par l'utilisateur.

**Instructions personnalisées** (`jarvis/runtime/agent_behavior.py`) : stockées sous `agent_behavior.custom_instructions`
seulement si non vides (le bloc garde sinon sa forme à deux champs) ; ajoutées une fois au bloc
`[Préférences de réponse JARVIS]` comme des préférences de forme, jamais une permission. Exposées à part dans
`cli.behavior.custom_instructions` : `values` et `fields` gardent leur forme figée pour le brouillon du shell.

## 3. Profils

`GET /api/personalization/profiles`, `POST` `{action: select|create|delete, id?, name?, accent?}`
(`jarvis/runtime/personalization_profiles.py`, bloc `personalization_profiles` du fichier de réglages, sans base
SQLite ni migration).

- Un profil porte les préférences de réponse (les trois champs ci-dessus) et la voix de chaque pile. **Le profil
  actif, ce sont les réglages en vigueur** ; les autres gardent l'instantané pris quand on les a quittés.
- Choisir recopie l'instantané du profil choisi dans les réglages, après avoir recopié les réglages en vigueur dans
  le profil quitté ; `voice_restart: true` si la voix change. Créer part des réglages en vigueur et rend le profil
  actif. Le profil actif ne se supprime pas. Au plus 12 profils, noms de 1 à 40 caractères, uniques.
- Sans bloc : un profil implicite « Jarvis Classique » ; lire n'écrit rien. Bloc abîmé : lecture tolérante.
- Refus : 400 et code stable dans `X-Jarvis-Error-Code` (`personalization_profile_unknown`, `_invalid_name`,
  `_duplicate`, `_limit`, `_invalid_accent`, `_active`, `_invalid_action`).
- Panneau flottant `.set-float` (`role=dialog`, ouvert par `openFloat`) au clic sur le profil actif, au-dessus de la
  grille sans changer sa géométrie : liste (`aria-current` sur l'actif, coche), supprimer (profils inactifs), « Créer
  un profil » (champ de nom en place). Le bouton et le panneau sont créés une fois puis mis à jour en place.

## 4. Clavier et focus

Tab boucle dans la page (aria-modal). À l'ouverture du panneau des profils, le focus va sur le profil actif ; Échap
le replie d'abord (focus rendu au bouton du profil, `aria-expanded` à jour), puis ferme les Réglages ; un clic hors du
panneau le replie sans voler le focus. Flèches haut/bas entre les profils du panneau ; flèches gauche/droite sur un
curseur à crans. Raccourcis `ui_settings` / `ui_close` : comme
sur le hub. Focus visible sur chaque contrôle ; mouvement réduit respecté.

## 5. Tests

- `tests/unit/test_personalization_page_browser.py` : vrai Chrome ; enveloppe rectangulaire, colonnes (3/2/1) et pas
  de débordement de 420 à 1920 px, grille entière visible à 1672×941, aucune citation, profil en haut à droite, plus
  aucun doublon `.perso-*` des primitives ; chaque contrôle écrit le vrai réglage (charges partielles) ; curseurs à
  crans (souris, clavier, « Hériter ») ; profils créés, choisis, supprimés ; panneau flottant (focus, Échap, clic
  extérieur), fil d'Ariane, tuile des réglages détaillés ; états erreur, chargement, désactivé ; captures (preuves
  `tasks/refonte-ui-settings/slices/02-personnalisation-ui/evidence/` avec `JARVIS_BROWSER_SHOTS`).
- `tests/unit/test_personalization_profiles.py` : module et route des profils.
- `tests/unit/test_agent_behavior.py` : instructions personnalisées (bornes, forme stockée, composition).
