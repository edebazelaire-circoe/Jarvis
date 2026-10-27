# Slice 07 — Notes d'implémentation (2026-10-27)

Agent d'implémentation, worktree `pev12c`, branche `wt/v12-s07` depuis `c0dd317d`. Contrat écrit :
[`docs/support-report.md`](../../../../docs/support-report.md).

## Changements

Le service de la Slice 10 V1 est **étendu**, pas doublé : `support_bundle.collect_bundle` porte un mode complet
(`BundleSources.full`), et la ligne de commande garde son paquet léger.

| Fichier | Rôle |
| --- | --- |
| `jarvis/runtime/support_bundle.py` | `collect_bundle` (mode complet), `Collected` (fichiers, manifeste, preuves, masqueur), `manifest.json` (`jarvis.support-manifest` v1), `write_archive` (zip `x` en temporaire puis `os.replace`), `prune_support_folder` (5 paquets, 30 jours, restes `.zip.tmp` / `.work-*` d'une heure), `--full` / `--description` |
| `jarvis/runtime/support_snapshot.py` (neuf) | instantané SQLite (API de sauvegarde, source `mode=ro`/`immutable=1`, déclencheurs et tables virtuelles retirés, `mcp_credentials` vidé, BLOB vidés, texte masqué, collisions `UNIQUE` gardées distinctes, `VACUUM INTO`, plafond 64 Mio) ; mémoire du Board actif (id validé, `lstat` sur chaque composant, liens/jonctions jamais suivis, binaire / > 1 Mio / budget 16 Mio omis) ; réglages sans clés |
| `jarvis/runtime/support_report.py` (neuf) | preuves masquées, prompt, rapport IA ancré (sections imposées, références, `unknown_mentions`), rapport factuel de repli, annexe factuelle toujours présente |
| `jarvis/runtime/support_send.py` (neuf) | `DEFAULT_SUPPORT_EMAIL` (seule occurrence, testé), `JARVIS_SUPPORT_EMAIL`, réglage `support_email` ; transports `mapi` (brouillon Simple MAPI `MAPISendMailW` avec pièce jointe), `outbox` (destination de test locale), `none` |
| `jarvis/runtime/support_routes.py` (neuf) | service et routes `/api/support/*` du Control Center (aperçu, création consentie, envoi, enregistrement `Documents\Jarvis` par `ExportDestination`, téléchargement, destination) ; journal `support.report.*` |
| `jarvis/runtime/control_center.py` | câblage, préfixe gardé `SUPPORT_ROUTE_PREFIX`, modèle à zéro outil (`CliTextModel`, modèle `fast` du routage) |
| `jarvis/runtime/control_center_support_report.js` (neuf), `control_center.html` | boîte « Signaler un problème » (rang 63) ; bouton dans la vue des erreurs |
| `jarvis/runtime/control_center_product_readiness.js` | « Signaler un problème » au pied de la fenêtre de préparation (I-010 point 3) |
| `jarvis/domain/diagnostic_redaction.py` | bloc PEM de clé privée masqué (forme linéaire, bornée) |
| `jarvis/adapters/memory_extractor_llm.py` | `CliTextModel.last_cost_usd` (lu par le rapport) |
| `scripts/release_test_gate.py` | `test_support_report*.py` dans la suite `release` |
| docs | `docs/support-report.md` (neuf), `docs/release.md` (renvoi, ligne « bouton » retirée des hors-périmètre), `docs/control-center-shell.md` (rang 63) |

**Transport choisi : Simple MAPI** (brouillon dans la messagerie par défaut, zip joint, l'utilisateur relit et envoie
depuis sa messagerie). Aucun secret de plus ; la pièce jointe passe. Le connecteur Mail CIRCOE classe l'envoi
`destructive`, refusé à l'appel en V1, et ne prend pas de fichier local. Sans messagerie déclarée : refus nommé et
enregistrement manuel.

## Preuves

- Tests : `test_support_report.py` (23), `test_support_report_js.py` (3), `test_support_report_browser.py` (3), plus
  le balayage voisin : `test_support_bundle.py`, `test_diagnostic_redaction.py`, `test_release_tooling.py`,
  `test_control_center_relay_whitelist.py`, `test_product_readiness*.py` (dont navigateur),
  `test_memory_consolidation_schema.py`, `test_v2_architecture.py` : **205 passés**. `test_control_center*.py`
  hors navigateur : 762 passés, 6 échecs `test_control_center_mcp_api.py` tous listés dans
  `tests/known_failures.json` (le 7e, `shell_layers`, était le mien : rang 63 enregistré, 12/12 verts).
  `test_control_center_shell_browser.py` : 69 passés, 5 échecs listés. `test_presentation_edition_ui_browser.py` :
  15/15. `test_control_center_timeline_ui.py` : vert (aucun outil ajouté au dock).
- Canaris (clé d'API `sk-ant-…`, jeton OAuth `ya29.…` et `access_token`, bloc PEM, jeton opaque de `.env`, clé scellée
  DPAPI des réglages, identifiant du coffre MCP) : absents de **chaque membre** du zip (octets décompressés, bases
  SQLite comprises) et du prompt du rapport.
- Instantané pendant des écritures (fil qui insère par transaction dans deux tables) : 5 instantanés, comptes
  égaux, `integrity_check` ok, aucun reste `.work`.
- Jonction dans la mémoire et jonction à la place de `memory` : refusées, rien hors racine copié ; ids
  `../state`, `a/b`, `C:\Windows`, vide : refusés.
- **Essai réel** (bac `%TEMP%\v12s07`, archive de `3dcc7036`, édition `presentation`, ports 55653-55656,
  `VISUALIZER_ENABLED=0`, `JARVIS_OPEN_BROWSER=0`, transport `outbox`) : erreur contrôlée réelle (présentation
  `pst_…` tronquée → `core.presentation_studio.unreadable` au journal d'erreurs), canaris semés dans la mémoire du
  Board et les réglages et collés dans la description ; paquet produit **par l'interface** (pied de la fenêtre de
  préparation → aperçu → refus sans consentement → consentement → Envoyer) ; compteur visible ; rapport IA réel en
  58 s, **0,085 $**, `unknown_mentions` vide, faits cités `[E1]…[E3]`, hypothèses marquées avec confiance, aucune
  cause présentée comme fait ; zip ouvert et scanné : **aucun canari** ; dépôt dans la boîte d'envoi de test ;
  enregistrement dans la racine d'export et téléchargement (200, `attachment`) ; création sans consentement par l'API :
  400. Second Control Center en transport `none` : envoi réel refusé 502 `support_send_unconfigured`, zip conservé,
  ligne au journal d'erreurs et visible dans la vue des erreurs ; l'interface refuse « Envoyer » avant tout appel et
  propose « Enregistrer… ». Preuves (zip d'exemple, zip décompressé, captures, journaux, copie des bases du bac) :
  `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s07\`.
  Bac supprimé après copie ; aucun processus du bac ne reste.
- Incident du bac (sans effet hors du bac) : le premier script d'arrêt, voulu pour le seul Control Center, a aussi
  arrêté le Core du bac (variable PowerShell insensible à la casse) ; Core du bac relancé, script corrigé.

## Coût

Un rapport IA réel : 0,085 $ (budget 0,50 $).

## Check Human proposé

**HV-SUPPORT-01** : sur le poste du Human, avec Outlook (ou la messagerie par défaut) configurée, JARVIS en édition
`presentation` sans `JARVIS_SUPPORT_TRANSPORT` : vue des erreurs → « Signaler un problème » → description → cocher →
« Envoyer ». Attendu : un brouillon s'ouvre, adressé à `e.debazelaire@circoe.com`, objet « JARVIS : rapport de
problème (…) », zip joint ; l'envoyer ; vérifier la réception, ouvrir le zip, lire `manifest.json` et `report.md`.
Variante : sans messagerie par défaut, le refus `support_mail_client_missing` est dit et « Enregistrer… » marche.

## Non vérifié

- **Le transport MAPI réel** (`_mapi_send_mail`, `MAPISendMailW`, drapeau non modal puis repli modal) : jamais
  appelé, aucun courriel envoyé (règle de la Slice) ; couvert par un faux `api` seulement. Le comportement de
  « nouvel Outlook » (MAPI simple non pris en charge) est inconnu : à voir au check Human.
- Le produit installé (`%LOCALAPPDATA%\CIRCOE\Jarvis`) : `config\.env` et les clés scellées DPAPI réelles ne sont
  éprouvés que par les tests (le bac est en mode développement, sans `config`).
- macOS : `mapi` n'existe pas ; le transport par défaut y est `none` (enregistrement manuel).
- Un instantané d'une très grosse base (proche de 64 Mio) : durée du masquage non mesurée (bases réelles ~20 Mio).
- La garde `unknown_mentions` ne voit que les codes pointés / `snake_case` et les références ; une cause inventée en
  prose n'est pas détectée mécaniquement (la consigne et l'annexe factuelle restent les garde-fous).
- Hors périmètre, laissé : I-010 point 12 (noms de fichiers dans le texte libre des messages) s'applique aussi au
  paquet complet.
