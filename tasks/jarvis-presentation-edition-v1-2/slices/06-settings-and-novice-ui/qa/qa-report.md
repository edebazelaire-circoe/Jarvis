# QA — Slice 06 `06-settings-and-novice-ui` (V1.2)

- **Date :** 2026-10-27. **Code relu :** branche `task/jarvis-presentation-edition-v1-2` @ `261d8698` (Slice : `c2a1ff6e..bd2530c2`, intégration `2aeaea06`, `8a8a5b13`).
- **Capacités :** `qa-verification`, `code-review`, `runtime-validation`, `impeccable` (critique UX).
- **Coût cerveau :** 0 $ (aucun tour ; le cerveau confiné du bac a démarré à vide, sans requête).
- **Preuves :** `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s06qa\evidence\`
  (`shots\` captures, `drive-*.json` relevés du navigateur, `brain-argv-*.txt`, `settings_on|off.json`, `roles_on|off.json`,
  `dossier-i004.json`, `scene-present-i004.txt`, `sandbox\` bases avec `-wal`/`-shm`, journaux et traces copiés avant suppression du bac) ;
  scripts dans `..\tools\`.

## Verdict : **PASS avec réserves**

0 bloquant, 0 majeur, 6 mineurs. Aucun réglage n'est supprimé. Le mode support n'élargit aucune capacité, ni en code ni en
réel. Le parcours novice tient à 1366×768 et à 1920×1080. En `full`, la page est identique au pixel près à la base
`c2a1ff6e`. Les mineurs sont des incohérences de libellé et deux trous de tests.

## Findings

### Mineurs
- **m1 — La fiche `coder` se contredit en presentation.** `jarvis/runtime/control_center_subagents_settings.js:742-743` :
  la puce « Indisponible dans cette édition » s'affiche à côté de « Proposé au cerveau » et de « Proposé aux agents »,
  toutes deux en vert. La synthèse (`:345-356`) affiche aussi « 7 Sous-agents actifs sur 7 » et « 7/7 Rôles lançables »,
  alors que l'avis dit « Jarvis ne lance jamais ce rôle ici ». Preuve : `shots\pres-subagents-coder-1920x1080.png`,
  `drive-pres.json` › `stats`. Correctif suggéré : quand `edition_unavailable` est présent, masquer les puces « Proposé »
  (ou les neutraliser) et retirer le rôle des compteurs actifs et lançables.
- **m2 — Trou de test sur la non-élévation des capacités.** `tests/unit/test_support_mode.py:108` vérifie deux choses :
  `edition_capabilities()` et `cli_args`, qui sont statiques, et une recherche du mot `support_mode`. Une mutation
  `settings.get("support" + "_mode")` dans `agent_settings.resolve_agent_settings`, qui lève le verrou du mode de permission
  quand le mode support est actif, **survit** (18/18 verts). Le test devrait comparer
  `resolve_agent_execution(settings)` avec le mode support coupé puis activé.
- **m3 — Trou de test sur la projection.** `test_support_mode.py:89` ne cherche qu'une clé nommée `support_mode`. Une
  mutation qui expose `support_mode.inspect()` sous la clé `"support"` dans `_settings_payload` **survit**. C'est sans
  effet en écriture, mais le contrat « absent de la projection » n'est pas tenu par le test.
- **m4 — Texte inexact du lien profond.** `jarvis/runtime/control_center.html:7019` : la note dit « Activez-le
  ci-dessous » alors que l'interrupteur est **au-dessus** de la note (`shots\pres-deep-link-needs-support-1366x768.png`).
  De plus, le focus programmatique sur l'interrupteur ne montre aucun anneau visible au chargement.
- **m5 — Voix « Indisponible » avec le bouton « Couper la voix ».** Ligne Voix du hub et de l'accueil : la préférence
  est `sleep`, l'état `degraded` (clé absente). Pour une personne non technique, couper une voix déjà indisponible est
  déroutant. Le message explique bien la cause et renvoie à Connexions. Cohérent avec la projection, à revoir pour le
  libellé (`shots\pres-hub-1366x768.png`).
- **m6 — Icône de la carte « Raccourcis clavier ».** Elle garde l'écran de « Interface & Interactions » au lieu d'un
  clavier. Cosmétique.

### Observations (hors périmètre ou déjà déclarées)
- Au premier lancement, la fenêtre de préparation passe devant le hub et devant un lien profond. Dans ce cas, Espace
  active l'interrupteur placé **derrière** la fenêtre modale. C'est un comportement existant, déclaré par l'implémentation.
- `POST /api/support-mode` sans en-tête `Origin` est accepté, comme les autres routes de réglages : un processus local
  peut basculer la navigation, sans aucun effet sur les capacités.
- L'accueil garde les abréviations `CNV`, `AGT` et `ERR` en haut à droite (comportement antérieur).
- L'en-tête YAML d'une recherche de 15 sources occupe tout le premier écran du Dossier ; `break-all` coupe les mots.

## Vérifié OK
1. **Aucun réglage supprimé.** Le diff ne retire aucun enregistrement. Vrai navigateur, base `c2a1ff6e` comparée à HEAD :
   - presentation sans support : mêmes 12 sections atteignables qu'avant ;
   - presentation avec support : 22 sections, plus Architecture & Agents et Avancé & Diagnostics ;
   - `bare_hands` et `mcp_plugins` restent réservés au mode développeur, avant comme après ;
   - `full` : navigation identique et 24/24 sections. Seul `microphone_sound` montre plus de contenu à HEAD (rien en moins).
2. **Mode support, côté API et persistance.**
   - `GET`/`POST` relus correctement.
   - Six corps invalides refusés en 400 `support_mode_bad_payload`, avec l'en-tête.
   - Origine étrangère, autre port local, `null` ou `Sec-Fetch-Site: cross-site` : refus 403.
   - Valeurs illisibles écrites à la main dans le fichier : lues comme coupé, avec le bon `problem` (trois codes) ;
     l'interrupteur les réécrit.
   - Persistance constatée après un redémarrage complet du bac.
   - Le battement porte le bloc.
3. **Aucune capacité de plus.**
   - argv du cerveau confiné **identique** avant et après activation du mode support, Core redémarré entre les deux
     (`brain-argv-pres2-support-{off,on}.txt`).
   - `GET /api/settings` et `GET /api/subagent-roles` identiques à l'octet, mode support activé ou coupé.
   - Le mode support n'a aucun effet en `full` (diff pixel nul, hors pastille d'erreurs).
4. **Parcours novice, captures 1366×768 et 1920×1080.**
   - Hub : 4 cartes sans jargon, dans l'ordre du parcours.
   - Bande d'aide entière dans le premier écran à 1366×768 (bas à 718 px sur 768, sans défilement).
   - Tab boucle dans le hub, avec un anneau visible sur chaque arrêt.
   - `prefers-reduced-motion` : transitions à 0 s.
   - Contraste lisible (textes de #a9c2cf à #d8edf7 sur fond quasi noir).
   - Voix : projection serveur réelle (« Indisponible », `voice_provider_key_missing`) ; mutation de l'état optimiste tuée.
   - « Signaler un problème » : hub fermé, panneau de la Slice 07 ouvert, seul `GET /api/support/preview` appelé, **aucun
     POST ni paquet** sur disque.
   - Board : Assistant et Réunion « Bientôt disponible », aucune requête au clic.
   - Lien profond `#settings/diagnostics` : hub, focus sur l'interrupteur, Espace, puis Diagnostics avec l'avis de support.
   - `#settings/bare_hands`, `#settings/mcp_plugins` et une cible inconnue n'ouvrent rien de caché.
5. **Sous-agents.** `coder` « Indisponible dans cette édition », avec le code `role_unavailable_in_edition`, en
   presentation ; normal en `full`.
6. **I-004, en vrai, avec un en-tête de 2 044 octets et 15 sources.**
   - M1 : la fenêtre « Afficher sur le Board » porte le titre `#` et un aperçu qui commence par « ## Résumé ».
   - M2 : titre entier dans le Dossier.
   - M3 : `pre-wrap`/`break-all`, `scrollWidth == clientWidth` à 1440×900.
7. **Tests.**
   - Unitaires et JS : 272 + 178 verts.
   - Navigateur : novice et rapport 13, Sous-agents et roue 14, édition presentation et Boards 33, rail et Dossier 14.
   - Coquille : 69 verts. 5 échecs, tous dans `tests/known_failures.json` (géométrie ×4, `test_reduced_motion` : transitions
     des Boards).
   - **Mutations** : 5 tuées sur 7 (support qui rouvre les sections développeur, support toujours actif, levée du verrou
     de permission en clair, voix optimiste, `edition_unavailable` retiré) ; 2 survivantes (m2, m3).
8. **Nettoyage.** Les processus du bac (34 à 37 par lancement) ont été arrêtés par PID exact après vérification de la
   ligne de commande, sans `/T`. Aucun port 61753-61756 à l'écoute. Bac supprimé après copie des bases. `pev12` propre.
   Le JARVIS vivant n'a pas été lancé (17653 jamais à l'écoute).

## Non vérifié
- Lecteur d'écran réel (rôles ARIA et Tab seulement).
- Voix en Sleep ou Active réels (bac sans clé vocale).
- Envoi réel d'un rapport depuis le hub (le consentement relève de la Slice 07).
- Contraste mesuré selon WCAG sur le fond flouté (seulement les couleurs calculées).
