# Réglages : Interface & interactions

**Statut :** contrat canonique (niveau 3 : sections enregistrées + tests).
**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 06.
**S'appuie sur :** [`navigation-registry.md`](navigation-registry.md) (catégories, sections, alias),
[`settings-shell.md`](settings-shell.md) (montage, `destroy`, liens internes).

La catégorie `interface_interactions` réunit ce qui règle l'écran et la main : le thème et la scène, toutes les
touches, les préférences ordinaires de Bare Hands. Plus aucun onglet hérité ne la sert : `appearance` et `shortcuts`
ne sont plus dans `TABS`, et aucun module n'ajoute d'onglet (`TABS.push`/`splice` : aucun appelant).

## 1. Sections

| Section | Libellé | Enregistrée par | `save` | Alias |
| --- | --- | --- | --- | --- |
| `theme_scene` (order 10) | Thème & scène visuelle | `control_center_work.js` (`THEME_SCENE_SECTION`) | `self` | `appearance` |
| `shortcuts` (order 20) | Raccourcis | `control_center.html` (`SHORTCUTS_SECTION`) | `self` | — (ID = ancien ID d'onglet) |
| `bare_hands` (order 30) | Bare Hands | `control_center_barehands.js` (`installSettingsSections`) | `self` | ancres `barehandsSettings`, `barehandsCalibration` |

Sous `advanced_diagnostics` (pour la Slice 08) :

| Entrée | Libellé | Enregistrée par | Contenu |
| --- | --- | --- | --- |
| section `barehands_lab` (groupe `labs`, order 60, `save:'self'`, `advanced`) | Bare Hands · essais | `control_center_barehands.js` | lecture de diagnostic à l'écran (`diagnostics`), test (`SECTION.benchmark`), enregistrement de séance (`SECTION.record`) ; ancres `barehandsRecord`, `barehandsBenchmarkSection` |
| partie `barehands` de `diagnostics` (order 40, `registerSettingsDiagnostic`) | Bare Hands | `control_center_barehands.js` | état des fichiers du modèle MediaPipe (pas relu / présent / absent + commande d'installation), dernière commande vocale reçue par la page |

L'onglet `experimental` reste dans `TABS` (déclaré par la page, rangé dans Avancé) : il ne porte plus que la porte de
test de la scène et le redémarrage du cerveau (`control_center_scene_settings.js`), qui déménagent dans Labs à la
Slice 08 ; l'ID disparaîtra alors.

## 2. Propriétaires des réglages (rien ne change de stockage)

| Réglage | Propriétaire, stockage | Application |
| --- | --- | --- |
| Thème (Circuit imprimé / Cosmos) | `JarvisThemeAPI` (`control_center_work.js`), `localStorage` `jarvis.ui.theme` (reprise `omega` → `cosmos`) | immédiate, `activate(id)` ; la carte choisie est marquée en place, le focus reste sur le bouton radio |
| Étoiles et orbites (taille, halo, respiration, gravitation, orbite, fils, tâches éphémères…) | `control_center_scene_page.js` (`window.JarvisSceneViewSettings.mount(slot)`), `localStorage` `JarvisSceneView.KEY` ; « Réinitialiser » | immédiate ; les autres onglets du navigateur suivent par l'événement `storage` |
| Raccourcis (tous ceux de `jarvis/runtime/shortcuts.py`, `wake_toggle` compris) | registre des raccourcis, route des raccourcis du Control Center | chaque touche s'enregistre seule ; portée système : au prochain démarrage de Voice |
| Bare Hands : aperçu de cible, assistance de visée, sensibilité, retour en veille, proposer la calibration, calibrer…, effacer le profil, réinitialiser les réglages | contrats Bare Hands (`control_center_barehands_contracts.js`, bornes `SETTINGS_BOUNDS`), route `barehands_test_mode`, route du profil | à chaud, enregistré immédiatement |
| Bare Hands : lecture de diagnostic à l'écran | idem (clé `diagnostics`) | idem — dans Avancé › Bare Hands · essais |

**Cycle de vie Bare Hands :** aucun contrôle des Réglages n'allume, n'endort ni n'éteint l'outil ; la roue (Sélection)
reste le seul endroit. « Réinitialiser les réglages » reporte `enabled` tel quel.

## 3. Raccourcis : un seul éditeur par touche

- La section rend chaque raccourci du registre, une touche (`button.keycap[data-shortcut]`) par raccourci : c'est
  l'unique éditeur de chacun. Voix & audio › Tours & interruptions montre `wake_toggle` en lecture seule (`kbd`) et
  « Modifier dans Interface & interactions › Raccourcis » (destination servie par `voice_settings_schema.py`,
  `surface.context`).
- Capture : clic sur la touche → « appuyez… » ; Échap annule (la capture prend la touche avant l'Échap du shell : les
  Réglages restent ouverts) ; une touche valide est envoyée, la section est redessinée et le focus revient sur la même
  touche. Quitter la section (ou fermer) annule la capture en cours (`destroy`) ; une réponse arrivée après le départ ne
  redessine rien (`isCurrent`).

## 4. Liens vers ces sections

Le lien de Voix pose le focus sur l'éditeur `[data-shortcut="wake_toggle"]` (`openSettingsLink`,
[`settings-shell.md`](settings-shell.md) § 3). `JarvisBarehands.showSettings(clé)` ouvre l'entrée qui porte la
section demandée (`SECTION_ENTRY` du module, mêmes destinations que `LEGACY_ANCHORS` du registre : un test lie les
deux) et la fait défiler en vue ; une entrée déjà ouverte n'est pas redessinée.

## 5. Tests

- `tests/unit/test_interface_settings_browser.py` (vrai Chrome) : sections, alias, `wake_toggle` éditable une seule
  fois dans toutes les sections, capture/annulation/abandon, lien de Voix → focus sur l'éditeur, liens génériques,
  thème immédiat + persistance + réinitialisation de la scène, enregistrement/réinitialisation Bare Hands sans toucher
  au cycle de vie, débordement aux quatre tailles.
- `tests/unit/test_control_center_appearance.py` (section `theme_scene`), `test_scene_view_prefs.py`,
  `test_barehands_tools_settings_js.py` (entrées enregistrées, plus rien dessiné après `destroy`),
  `test_control_center_settings_registry_js.py` (`SLICE_06_SECTIONS`, aucun injecteur, ancres ↔ `SECTION_ENTRY`).
