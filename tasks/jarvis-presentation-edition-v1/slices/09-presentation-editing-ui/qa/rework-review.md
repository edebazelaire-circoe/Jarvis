# Slice 09 — QA contre-vérification de la reprise (revue de code + essai réel)

Date : 2026-10-27. Relu : `448c055c` et `a2b1d650` au-dessus de `e31d5cec` (branche `task/jarvis-presentation-edition-v1-s09`,
worktree `pev1e`). Aucun code produit modifié. Preuves : scratchpad de la session
`C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\s09cc\`
(`evidence/c*.png|json|txt`, plans `plans/c*.json`, lanceur `launch.ps1`, `assemble.py`, journaux `logs/`, bases `db-copies/`).

## Résumé

La reprise tient ce qu'elle annonce sur l'essentiel : une saisie n'est plus perdue ni écrite sur une autre scène quand Variantes change de
scène (B1 rejoué en vrai, mutation tuée), Core arrêté garde la saisie et l'enregistre seul au retour, une variante « Nouvelle variante… »
s'exporte, l'image et le PDF d'une scène choisie sont non vides, la règle de l'image représentative est la même dans la page et dans
Core (test de parité, mutation tuée) et « Lire » repart du début de la scène. La porte de rédaction ne bloque aucun deck existant du JARVIS
quotidien (`full`) : elle ne joue qu'à l'assemblage d'un nouveau brouillon natif.

Un défaut nouveau, introduit par la file de déplacement : après un déplacement retenu (Core injoignable), l'enregistrement automatique au
retour de Core fait bien avancer l'éditeur, mais la ligne d'état « L'éditeur reste sur la scène 2… Votre saisie n'est pas enregistrée »
reste affichée indéfiniment sur la scène 3, alors que la valeur est enregistrée (MAJEUR, non bloquant, correctif de quelques lignes).

**Verdict recommandé : PASS** (aucun bloquant) ; je recommande de corriger M1 avant la validation Human (le scénario HV « Core arrêté » le
montre à coup sûr).

## Périmètre relu

- Inspecteur : `requestMove` / `runMove` / `settleDrafts` / `resumeMove`, `closeByUser`, `keepUnsaved` / `retryUnsaved`, garde de scène
  dans la file d'écritures, `runHistory` (attente de la file, focus), `sayEdited(…, bring)`, `renderContext` (région vivante), `histNote`.
- Variantes : `bring` seulement pour annuler / rétablir, `rest` / `RESTLESS`, `restMsOf`, `opener`, texte « Core est injoignable »,
  `presentation_render_snapshot_invalid`, événement `jarvis:presentation-render-finished`.
- Hôte de prefab et séquenceur : `representativeFrame`, `restFrame`, `hold()` ; scène Remotion : phrase produit sans route ni code.
- Sessions & Boards : choix de scène (`master.stills`), état `scenes` / `choose`, bouton de copie gardé, relecture `renders-changed`.
- Core : `still_scenes`, `representative_frame`, gel sans lignée (`sources: []`), porte `NATIVE_REQUIRED`, guide natif et `NATIVE_LOOP`.
- Docs (`presentation-studio.md`, `remotion-render.md`, `presentation-production.md`, `export.md`, `presentation-artifacts.md`), I-008,
  `human-validation.json`, entrée « Slice 09, reprise QA » du LOG.

## Preuves exécutées par moi

### Tests (`.venv` du dépôt principal, depuis `pev1e`, avant-plan, par lots)

| Lot | Résultat |
| --- | --- |
| rédaction native, playbooks, `test_confined_prompts.py`, rendu maître, export après édition, image représentative, brouillons, relecture Variantes, Remotion Studio JS, espace de travail JS, entrées maître JS, séquençage continu, inspecteur JS | 225 passés |
| rendu (service, domaine, routes, docs), artefacts (+docs), rédaction (service, porte, guide, plancher, docs, remotion, reprise, boucle native, politique), import Remotion (+service, docs) | 798 passés |
| `test_presentation_editing_ui_browser.py` | 6 passés |
| navigateur inspecteur + explorateur + `test_workspace_presentations_browser.py` | 36 passés |
| navigateur Variantes transport / contrôles / entrées maître / Remotion Studio + rail | 47 passés, 9 ignorés (runtime Remotion non fourni au banc) |

Aucun des échecs connus listés n'est apparu dans ces lots ; l'intermittent `[800x600]` de l'explorateur est passé.

### Mutations (copie `git archive a2b1d650` au scratchpad, jamais dans le worktree ; copie supprimée ensuite)

| # | Mutation | Tuée par |
| --- | --- | --- |
| M1 | `NATIVE_REQUIRED` neutralisé dans `Rule.level` | `test_a_native_scene_without_a_content_control_is_refused…` (2 échecs) |
| M2 | gel : lignée `sources` gardée | `test_a_branch_made_by_new_variant_exports_like_the_active_one` |
| M3 | `runMove` sans `settleDrafts` | 2 tests `test_presentation_editing_drafts_js.py` + B1 navigateur |
| M4 | Variantes ramenée à chaque sauvegarde (`bring` ignoré) | 2 tests `test_presentation_editing_ui_browser.py` |
| M5 | `Math.round` → `Math.floor` dans `representativeFrame` | `test_page_and_core_choose_the_same_representative_frame` |

### Hygiène

`git ls-files --eol` sur les 37 fichiers texte modifiés : tous `i/lf w/lf`. Aucun caractère de contrôle (hors tabulation / fin de ligne),
aucun `\r`.

### Essai réel (bac à sable, aucun tour payant du cerveau)

Archives `git archive e31d5cec` (code d'avant) et `a2b1d650` sous `%TEMP%\s09cc-*`, `python -m jarvis core|control-center` avec le
`.venv` du dépôt principal, ports 41653-41656, `VISUALIZER_ENABLED=0`, `JARVIS_OPEN_BROWSER=0`, `JARVIS_EXPORT_ROOT=%TEMP%\s09cc-export`,
Chrome sans tête (CDP 9497, harnais `cdp.mjs` repris de la QA précédente). Remotion installé depuis la page (POST même origine, prêt).

1. **Deck ancien** : avec le code d'avant (`e31d5cec`, édition `full`), l'exemple natif du guide d'alors (3 scènes, AUCUN réglage) est
   livré (`c01-old-native.txt`, 201 `delivered`). Puis passage au nouveau code sur la même racine de données.
2. **Porte** (nouveau code) : le même brouillon sans réglage est refusé en `presentation` (`c02`) ET en `full` (`c14`) : 400
   `presentation_studio_draft_refused`, un `scene_no_controls` par scène avec ce qu'il faut ajouter ; l'exemple natif du nouveau guide
   (3 scènes, titre / ligne / accent) et un deck guidé de 4 scènes sont livrés.
3. **B1** (`c03`) : titre de la scène 1 sélectionné, texte tapé sans relâcher, ▶ dans Variantes. Au passage à la scène 2 : « Saisie
   enregistrée sur la scène 1 « Ouverture du sujet » · l'éditeur montre maintenant la scène 2 « Le coeur du sujet » », curseur sur le titre
   de l'éditeur (`H2#jviTitle`), champ = valeur de la scène 2, Variantes reste sur la scène 2 (pas ramenée). Core : scène 1 = texte tapé,
   scène 2 et 3 intactes.
4. **Core arrêté** (PID exact) (`c04`, `c05`) : saisie + Entrée → valeur gardée, message produit « Jarvis ne joint pas son moteur
   (Core)… » avec « Réessayer » ; « Scène suivante » dans Variantes → l'éditeur reste sur la scène 2 et le dit, avec « Abandonner ma saisie
   et continuer » ; Variantes passe à la scène 3. Core relancé (`c06`) : valeur enregistrée seule (Core : « Coeur, saisi Core arrete »),
   message de ligne effacé, l'éditeur rejoint la scène 3. **Mais** la ligne d'état « L'éditeur reste sur la scène 2… n'est pas
   enregistrée » reste (`c06`, encore là 8 s plus tard : `c07`) → M1.
5. **Clavier** (`c08`, `c09`) : sous la barre « ↶ Annuler changera la scène 2 « … » (autre scène : elle s'affichera) » ; `aria-description`
   de « Annuler » nomme la scène ; plus d'`aria-haspopup` sur « Modifier ». Entrée sur « Annuler » : la scène 2 revient (éditeur et
   Variantes), « Modification annulée : scène 2 « … » », focus sur « Rétablir » (« Annuler » désactivé : l'anneau ne gardait que ce pas,
   celui de la scène 1 datant d'avant le redémarrage de Core). Échap : l'éditeur se ferme, Variantes reste ouverte, focus sur « Modifier ».
6. **« Nouvelle variante… » puis export** (`c10`) : variante #2 « non active », titre modifié, « « Titre » enregistré · scène 2 « … » »,
   « Exporter la vidéo » → vidéo entière exportée (690 images, 344 Ko) ; l'aperçu montre le titre de la branche.
7. **Image / PDF depuis Sessions & Boards** (`c11`, `c12`) : « Image (PNG) » → « Scène pour l'image » propose les 3 scènes avec leurs
   titres ; scène 2 → PNG 1920×1080 avec le titre édité (`c11-exported-scene2.png`). PDF de la scène 3 → 1 page avec contenu
   (`c12-pdf-page.jpg`). « Enregistrer une copie dans Documents » → `JARVIS_EXPORT_ROOT\Deck natif modifiable - PDF.pdf`, bouton toujours
   présent après la copie.
8. **Image représentative** (`c13`) : au montage, scène 1 visible (pas un cadre vide) avec l'horloge à 0:00 ; scène 3 choisie à l'arrêt :
   contenu visible, horloge 0:16 (début de la scène 3) ; ▶ → 0:17 après 0,7 s : la lecture part du début de la scène.
9. **Trois largeurs** (`c13-d/e/f`) : 1440 (Variantes s'arrête à x=1012, l'éditeur commence à 1012), 1280 (852 / 852), 600 (éditeur de 172 à
   592, couvre Variantes) ; pas de défilement horizontal de la page.
10. **Édition `full`** (`c15`, `c16`) : surfaces développeur visibles, porte « Remotion Studio » visible. Deck ancien sans réglage :
    Variantes le lit et le joue, « Modifier » ouvre l'éditeur avec « Cette scène n'expose aucun réglage. Demandez à Jarvis de proposer des
    réglages, ou de modifier sa source. », export de la vidéo entière réussi (324 Ko). Deck guidé : « Modifier », titre changé,
    « « Titre de la diapositive » enregistré ».

Arrêt par PID exacts et descendants nés après leur démarrage (`stop-tree.ps1`) : Core 24204, 2572, 11036, 25568 ; Control Center 25024,
20396, 21704 ; Chrome 22960 (+ ses processus au profil `s09cc-chrome`). Bases copiées sous `s09cc/db-copies/` puis `%TEMP%\s09cc-*`
supprimés. Disque C : 42 Go libres avant et après. Le Core 127.77.0.1:17653 et les ports 40653-40656 n'ont pas été touchés ; rien lancé
depuis `C:/Projects/jarvis/jarvis`.

## Porte de rédaction : impact sur le JARVIS quotidien (`full`)

- **Decks existants** : jamais re-jugés. `check_first_draft` n'est appelé que par `check` / `assemble` d'un brouillon soumis et par
  `finalize` ; `finalize` construit un brief **guidé** (`draft_from_stored` : `Workflow.DIRECTED`, pas `native`) où `scene_no_controls`
  reste un avertissement. Édition, aperçu, rendu, export d'un deck natif ancien : inchangés (essai 10).
- **Ré-assemblage d'un deck ancien** : oui, il est désormais refusé tant que ses scènes n'exposent pas un contrôle de contenu, dans les
  deux éditions (essais 2 et `c14`). C'est l'effet voulu ; le refus dit exactement quoi ajouter (props avec `default`, lecture
  `props.<name>`, `controls` groupe `content`, couleur `visual`). Le message est destiné au cerveau (anglais technique) ; l'utilisateur
  n'en voit que le relais du cerveau.
- **Autres voies** : le mode guidé (Studio) garde ses niveaux (`native` seulement) ; l'import Remotion (`remotion_import_service`) et
  `presentation_source op write` n'appellent pas la porte ; le brief natif refuse `exploratory` (pas de contournement par le niveau OFF
  d'exploratory) ; aucune recette ni prefab ne passe par un assemblage natif.
- **Consignes confinées** : `test_confined_prompts.py` vert (parité). Budget du playbook auteur : 7 102 caractères mesurés pour 7 400
  permis (avant : ≤ 7 000) ; l'ajout est la seule phrase « MODIFIABLE » de `NATIVE_LOOP` : justifié, marge de ~300.

## Findings

### M1 — MAJEUR (introduit par la reprise) — La ligne « L'éditeur reste sur la scène k… n'est pas enregistrée » survit à l'enregistrement

Scénario : Core injoignable, une valeur tapée, Variantes (ou ‹ ›) change de scène → l'éditeur reste et le dit (correct). Core revient :
`retryUnsaved` enregistre la valeur, `resumeMove` relance la file, l'éditeur passe à la scène demandée. La ligne d'état d'avertissement
n'est jamais effacée : elle affirme « Votre saisie … n'est pas enregistrée » et « L'éditeur reste sur la scène 2 » alors que la ligne de
contexte dit « la scène 3 sur 3 » et que Core a la valeur (`c06`, `c07` + lecture de la variante). Elle masque aussi la confirmation
« « Titre » enregistré » (le chemin de succès n'écrit la ligne que si l'état courant est absent, `ok` ou `info`).

Cause (`control_center_presentation_studio_inspector.js`) : dans `runMove`, quand `hasUnsaved()` est déjà faux à la reprise, `saved`
reste `null` et rien ne remplace l'état `warn` posé par le blocage ; `resumeMove` ne l'efface pas non plus. Le test
`test_core_stopped_keeps_the_typed_value…` vérifie l'enregistrement mais pas la ligne d'état après un déplacement retenu.

Recommandation : effacer (ou remplacer par « Saisie enregistrée sur la scène k… ») l'état du blocage quand la file repart, et l'asserter
dans le test JS de Core arrêté avec un déplacement en attente.

### m1 — MINEUR — Le blocage nomme « une valeur » au lieu du réglage

Même scénario : « Votre saisie (une valeur) n'est pas enregistrée ». `settleDrafts` exclut la session déjà gardée pour Core injoignable
de `items` (`kept` vide, journal `move_held {"kept":[]}`), d'où le repli « une valeur » au lieu de « « Titre » ».

### m2 — MINEUR (doc) — Focus après « Annuler » par Entrée

La doc dit que le focus reste sur « Annuler » « ou le titre quand il n'y a plus rien » ; le code (et l'essai 5) le met sur « Rétablir »
quand « Annuler » se désactive. Le comportement est défendable mais un double Entrée fait alors annuler puis rétablir. Aligner la doc
(ou préférer le titre).

### m3 — MINEUR (consigne) — `NATIVE_LOOP` se contredit

« 2) Ecris du React/TSX normal : texte, couleurs et mise en page dans le code » est suivi de « MODIFIABLE : les textes visibles et la
couleur principale … sont des props ». Le tour réel de l'implémenteur a suivi la seconde phrase, mais un auteur peut perdre un aller-retour
d'assemblage. Reformuler le point 2 (« mise en page et couleurs secondaires dans le code »), à budget constant.

### m4 — MINEUR — Le plancher est satisfait par un contrôle mort

`scene_no_controls` natif exige un contrôle du groupe `content`, mais un contrôle dont la prop n'est pas lue par le TSX reste un
avertissement (`tsx_props_unread`, testé par `test_a_dead_control_on_a_native_scene_is_a_warning`) : « Modifier » offrirait alors un
champ qui ne change rien à l'image. À surveiller dans les traces d'auteur ; le passer en erreur pour les contrôles `content` serait le
plancher complet.

## Points vérifiés sans finding

- B1 sans nouvelle course : la file garde la dernière cible (`move.target`), une cible arrivée pendant l'enregistrement est appliquée
  après lui ; garde de scène sur chaque écriture (`commit_scene_moved`) ; annuler attend la file puis lit son pas ; fermer enregistre
  d'abord (« Fermer sans enregistrer » sinon).
- `bring` : seule une annulation / un rétablissement ramène Variantes ; une sauvegarde relit toujours le graphe et l'aperçu (test
  `test_variants_reads_core_after_edit_js.py`, mutation M4) — pas d'effet de bord vu en essai (Variantes jamais ramenée, aperçu relu).
- Gel : `sources` vidé seulement dans la copie figée, l'index vivant garde la lignée (test) ; exports MP4 actif, branche et deck ancien,
  PNG et PDF tous réussis.
- Parité de l'image représentative : même formule (arrondi au demi supérieur, milieu `floor`, borne), cas testés de part et d'autre.
- Textes produit : plus de texte de transport dans Variantes ; phrase produit pour le moteur absent en édition produit ; refus
  `snapshot_invalid` en français.

## Flagged (hors reprise ou à décider)

- **Avis de Variantes « Core ne répond plus… » persistant** après le retour de Core, à travers une création de variante et un export
  réussis (`c10`) : comportement d'avant (la reprise n'a changé que le texte) ; il faut cliquer × ou « Relire ».
- **Rail « Vidéo de… En cours »** alors que l'export était fini (`c10`), « Prêt » plus tard (`c13-a`) : décalage de relève, à confirmer.
- **Jargon** : la ligne d'un rendu image affiche « scène pss_604563c21abd » (`c11-b`) ; à joindre à I-008 n° 3 avec « DA · RÉV. 1 »,
  « GÉNÉRÉE / REPLI », « Fallback - Corporate calm · secours » (revus à l'écran).
- **Copies figées d'avant le correctif** : une copie d'une variante à lignée gelée avant `448c055c` garde ses `sources` et reste refusée
  au rendu (message français, sans « Réessayer ») ; il faut regeler. Déduit du code, non éprouvé.
- **600 × 800** : une barre de défilement horizontale apparaît au bas du panneau de l'éditeur (`c13-f`), la page ne défile pas.
- **Parité fps non entier** : la page retombe sur 30 i/s si `fps` n'est pas entier, Core prend `target.fps` tel quel ; sans effet pour
  les compositions entières actuelles.

## Non vérifié

- Tour réel du cerveau (exclu par la consigne ; celui de l'implémenteur est dans ses preuves `s09rw/`).
- Remotion Studio réellement démarré en `full` (I-008 n° 5) ; lecteur d'écran réel (seuls les attributs ARIA sont lus).
- Le PDF copié vers `JARVIS_EXPORT_ROOT` a été supprimé avec le bac à sable ; sa page est conservée en image (`c12-pdf-page.jpg`).
- Navigateur `test_presentation_studio_reload*`, `test_remotion_*realpage*`, tests `*_real` (runtime Remotion de banc non fourni).

## Recommandations au PM

1. Corriger M1 (et m1 au passage) avec son test avant la validation Human ; le reste peut rejoindre I-008.
2. Ajouter à I-008 : m2, m3, m4 et les points « Flagged » jargon et copies figées anciennes.
3. Aucun redémarrage du JARVIS vivant n'est nécessaire pour ce que j'ai relu au-delà de ce que le LOG annonce (JS au prochain chargement,
   Core au prochain démarrage) ; pas de migration.
