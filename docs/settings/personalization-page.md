# Réglages : la page Personnalisation

**Statut :** contrat de surface (niveau 3 : routes serveur + tests navigateur).
**Introduit :** refonte des Réglages page par page, 2026-10-23 (première page : Personnalisation).
**S'appuie sur :** [`settings-shell.md`](settings-shell.md) (hub, shell), [`voice-audio.md`](voice-audio.md) (sections
détaillées de `voice_audio`), [`architecture-agents.md`](architecture-agents.md) (préférences de réponse).

La carte **Personnalisation** du hub (`voice_audio`) n'ouvre plus le shell : elle ouvre sa propre page,
`#overlay` › `section#settingsPerso` (`.overlay[data-view=perso]`), dessinée par `control_center_personalization.js`.
Les liens internes et la roue (« Réglages de la voix ») ouvrent toujours le shell directement.

## 1. Composition

- En-tête : × en haut à gauche (ferme tout), fil d'Ariane « JARVIS › Paramètres » (le bouton « Paramètres » ramène
  au hub), titre, phrase, filet. En haut à droite, aligné sur le bord droit de la grille : le **profil actif**
  (avatar rond à anneau de sa teinte, nom, chevron). Aucune citation ni slogan.
- Grille `.perso-grid` de 12 colonnes à gouttière constante, spans entiers, cartes étirées à la hauteur de leur
  rangée : l'enveloppe est un rectangle.

  | Rangée | Cartes (span) |
  | --- | --- |
  | 1 | Voix (5) · Proactivité & rappels (7) |
  | 2 | Personnalité (5) · Préférences rapides (3) · Réglages détaillés (4) |

  Sous 1100 px : deux colonnes (Voix | Proactivité ; Personnalité pleine largeur ; Préférences | Détails) ; sous
  720 px : une colonne. Jamais de défilement horizontal.

## 2. Ce que chaque carte écrit

Rien n'est affiché qui ne soit appliqué. Chaque contrôle s'enregistre dès qu'il change (charge **partielle** de
`POST /api/settings`, jamais le brouillon du shell) ; la carte dit « Enregistrement… », « Enregistré. » ou le refus
du serveur, et un refus remet la valeur enregistrée.

| Carte | Réglage | Application |
| --- | --- | --- |
| Voix | `voice.settings.<pile en service>.voice` (catalogue `voice.stacks`), `…transcription_language` | prochain démarrage de Voice (badge) |
| Personnalité | `cli.behavior.response_verbosity`, `cli.behavior.politeness_formality` (choix fermés `cli.behavior.fields`), `cli.behavior.custom_instructions` (texte ≤ 1000 car., enregistré 1,2 s après la frappe ou à la sortie du champ) | à chaud |
| Préférences rapides | Concis, Détaillé, Équilibré, Formel : chacun écrit un couple verbosité + formalité existant, rien d'autre ; le préréglage qui correspond aux valeurs en vigueur est `aria-pressed=true` | à chaud |
| Proactivité & rappels | `agenda_reminders.*` (interrupteur général, puis délais et heures ; éteint, les champs sont désactivés) | à chaud |
| Réglages détaillés | aucun : une ligne par section enregistrée de `voice_audio` (registre), sauf `agent_behavior` que la page remplace ; un clic ouvre le shell sur la section | — |

Volume, débit de parole et aperçu de la voix ne sont pas affichés : Voice ne sait pas encore les appliquer.

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
- Panneau flottant au clic sur le profil actif (au-dessus de la grille, sans changer sa géométrie) : liste
  (`aria-current` sur l'actif, coche), supprimer (profils inactifs), « Créer un profil » (champ de nom en place).

## 4. Clavier et focus

Tab boucle dans la page (aria-modal). Échap replie d'abord le panneau des profils (focus rendu au bouton du profil),
puis ferme les Réglages. Flèches haut/bas entre les profils du panneau. Raccourcis `ui_settings` / `ui_close` : comme
sur le hub. Focus visible sur chaque contrôle ; mouvement réduit respecté.

## 5. Tests

- `tests/unit/test_personalization_page_browser.py` : vrai Chrome ; enveloppe rectangulaire et pas de débordement de
  420 à 1920 px, aucune citation, profil en haut à droite ; chaque contrôle écrit le vrai réglage (charges
  partielles) ; profils créés, choisis, supprimés ; Échap, fil d'Ariane, ligne des réglages détaillés.
- `tests/unit/test_personalization_profiles.py` : module et route des profils.
- `tests/unit/test_agent_behavior.py` : instructions personnalisées (bornes, forme stockée, composition).
