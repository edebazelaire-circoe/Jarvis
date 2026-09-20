# Bare Hands — retrait du tutoriel, et les deux restes de compatibilité

**Introduit :** tâche `jarvis-bare-hands-ui-calibration-refinement`, Slice 07B.
**Décisions :** 10 (« l'entrée Tutoriel séparée est retirée ») et 17 (« le
parcours séparé est retiré ; la calibration enseigne désormais »).
**Architecture :** §9 — « ne jamais garder deux parcours ».

## Ce qui a été retiré, pour de bon

- `jarvis/runtime/control_center_barehands_tutorial.js` — **supprimé** (734
  lignes, dix étapes, machine à états complète). Son insertion dans la page
  servie (`control_center.py`, `control_center.html`) est partie avec lui.
- `startTutorial()`, `tutorialFlow()`, `tutorialObservation()` et
  `markTutorialSeen()` dans `control_center_barehands.js` — supprimés.
- La case « Tutoriel déjà vu » des réglages — supprimée. C'était la dernière
  occurrence visible du mot dans l'interface. La section de lancement était
  partie à la Slice 02 ; le menu du clic droit n'en a jamais eu.

Il n'existe plus **aucun** moyen de construire ou d'ouvrir une surimpression de
tutoriel. Il y a exactement un parcours guidé : la calibration.

## Reste n° 1 — la commande et l'outil `tutorial`

**Ce que c'est.** `tutorial` reste dans le vocabulaire de commandes et
`barehands_tutorial` reste un outil MCP. Les deux ouvrent la **calibration**.

**Pourquoi ce n'est pas une suppression.** Le nom est miroité sous une
assertion de parité qui tourne **au chargement du module** :

| Fichier | Table |
| --- | --- |
| `jarvis/runtime/control_center_barehands_commands.js` | `ENTRY_POINTS`, `COMMANDS` |
| `jarvis/domain/barehands_command.py` | `COMMANDS` |
| `jarvis/runtime/barehands_mcp.py` | `TOOL_NAMES`, `TOOL_COMMANDS` + l'assertion en fin de module |

Retirer le nom est une rupture de contrat coordonnée sur trois fichiers plus
leurs tests, et une désynchronisation fait **échouer l'import** du serveur MCP.
L'alias tient le contrat *et* l'exigence produit — une seule surface visible.

**Comment il reste honnête.** `JarvisBarehands.tutorial()` appelle
`startCalibration()` et décore sa confirmation d'un `reason` :

> « Commande dépréciée : le parcours de tutoriel a été retiré, c'est la
> calibration qui a été ouverte. »

Le canal de commandes recopie ce `reason` dans le reçu (il ne le fabrique pas),
le courtier le renvoie dans le corps 200, et `barehands_mcp` le colle à sa
phrase d'issue. Le cerveau lit donc « Fait. Commande dépréciée : … c'est la
calibration qui a été ouverte. » et ne peut pas annoncer un tutoriel.

**Ses refus gardent le nom de ce qui a refusé** —
`barehands_calibration_disabled`, `barehands_calibration_lifecycle_off`,
`barehands_calibration_no_camera` — parce que c'est la calibration qui a refusé.

**Condition de suppression.** Quand un changement de contrat des commandes Bare
Hands est de toute façon nécessaire pour une autre raison (ajout ou retrait
d'une autre commande, montée de version du canal). Le retrait consiste alors à
supprimer l'entrée des trois tables **dans le même commit**, plus
`JarvisBarehands.tutorial()`, `tutorialState()`, la ligne de routage de
`claude_local.py` et les tests correspondants. Ne pas le faire isolément : le
gain est nul et le risque est un serveur MCP qui n'importe plus.

## Reste n° 2 — le réglage persisté `tutorial_seen` / `tutorialSeen`

**Ce que c'est.** Un booléen dans le fichier de réglages
(`barehands_test_mode.py`, `SCHEMA_VERSION = 2`) et dans le schéma du contrat
JS (`SETTINGS_SCHEMA_VERSION`). **Plus personne ne l'écrit.** Il ne dit plus que
« cet utilisateur avait traversé l'ancien tutoriel avant son retrait », et rien
ne le lit pour décider quoi que ce soit — il ne déclenchait déjà aucun
lancement automatique.

**Pourquoi il est gardé plutôt que migré.** Le supprimer exige de monter
`SCHEMA_VERSION` **et** `SETTINGS_SCHEMA_VERSION` dans le même changement, et
fait refuser `validate()` (`champ inconnu : tutorial_seen`) sur toute
sauvegarde venue d'une page ouverte avant le déploiement. C'est une panne
réelle, à 400, pour gagner un seul booléen inerte. C'est le même arbitrage que
pour la commande, et il tombe du même côté.

**Ce qu'il reste lisible.** `JarvisBarehands.tutorialState()` rend
`{retired:true, replacedBy:'calibration', running:false, seen:<le booléen>}`.
Le membre est gardé parce que la surface est **gelée** ; sa forme change parce
qu'un `installed:false` se lirait comme une panne d'insertion alors que la
vérité est un retrait — « un refus codé plutôt qu'un défaut plausible ».

**Condition de suppression.** À la prochaine montée de `SCHEMA_VERSION` faite
pour une autre raison. Ajouter alors `2` à `MIGRATED_SCHEMA_VERSIONS`, retirer
la clé de `SETTINGS_FLAGS`, `SETTINGS_DEFAULTS`, `SETTINGS_WIRE_KEYS`,
`SETTINGS_DEFAULTS` du contrat JS et de `normalizeSettings`, et laisser la
migration jeter la clé sans le dire à l'utilisateur — elle ne lui apprend plus
rien.
