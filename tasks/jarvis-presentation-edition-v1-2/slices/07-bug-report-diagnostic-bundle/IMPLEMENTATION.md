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

## Reprise QA (2026-10-27, après le verdict FAIL de `qa/qa-report.md`)

Commit de code `eefbd016` (plus ces notes). Chaque finding est corrigé ; les canaris et sondes de la QA
(`v12s07qa/scripts/probe_canaries.py`, `probe_confine.py`) sont repris en tests de non-régression dans
`tests/unit/test_support_report_qa.py`.

| Finding | Correctif |
| --- | --- |
| **B1** | `DiagnosticRedactor.cell` / `deep` : une cellule de base ou un fichier de la mémoire qui se lit comme du JSON est masqué en structure, et une chaîne qui est elle-même du JSON est relue et masquée (6 niveaux) ; le contenu reste lisible. Noms sensibles (`sensitive_name`, `named_secret` : mots `TOKEN`, `KEY`, `SECRET`, `PASSWORD`…, fins `…TOKEN`, `…APIKEY`, découpage camelCase) : valeur masquée en JSON, en texte libre (`NOM=`, `export NOM=`, `NOM:`, avec ou sans guillemets) et dans les paires JSON échappées (`\"refresh_token\": \"…\"`, quel que soit le nombre d'échappements). Identifiants et horodatages sous un nom ordinaire restent lisibles. Règle unique, déplacée de `support_bundle.py` vers `diagnostic_redaction.py`. |
| **M1** | En développement, le `.env` du dépôt (`jarvis.environment.PROJECT_ROOT`) alimente le masqueur, en mémoire seulement (`support_bundle._config_dir`). |
| **M2** | Nom de fichier ou de dossier de la mémoire qui porte un secret → `masque-<sha256 10 hex><extension>`, stable, dans les noms des membres et dans `manifest.json`. |
| **M3** | Blocs PGP, PEM chiffrée à l'ancienne (`Proc-Type` / `DEK-Info`), PuTTY (`PuTTY-User-Key-File` / `Private-Lines` jusqu'à `Private-MAC`) et JWT courts masqués ; `.ppk`, `.pem`, `.key`, `.asc`, `.gpg`, `.pgp`, `.p12`, `.pfx`, `.jks`, `.keystore`, `.kdbx`, `.der`, `.p8` jamais inclus (`excluded`, `key_file_never_included`). |
| m1 | Fichier à plus d'un lien dur refusé (`hard_link_not_followed`). |
| m2 | Tests : BLOB hors coffre vidé et page libérée absente (la mutation « BLOB non vidés » est désormais tuée, vérifié), table FTS retirée, `freelist_count = 0`. |
| m3 | Envoi en cours par paquet : un second envoi est refusé (409 `support_send_in_progress`) ; dans l'interface, « En attente de la messagerie… », « Envoyer » désactivé, aucun second appel (test navigateur). |
| m4 | `sweep_work_folders` : tout `.work-*` retiré à l'ouverture du service et avant chaque création (sous le verrou de création). |
| m5 | `.pending-send.json` : un paquet dont l'envoi a échoué est gardé hors de la règle des 5 jusqu'à son enregistrement, son téléchargement ou un envoi réussi, 30 jours au plus ; le message d'échec le dit ; documenté. |

Linéarité : la nouvelle paire échappée était quadratique sur une longue suite de `\` (7 s) ; ancrée par un
lookbehind, le test de linéarité existant repasse.

### Preuves

- Tests : `test_support_report_qa.py` (10), `test_support_report*.py`, `test_support_bundle.py`,
  `test_diagnostic_redaction.py`, `test_release_tooling.py`, `test_control_center_relay_whitelist.py`,
  `test_product_readiness*.py` (dont navigateur), `test_memory_consolidation_schema.py`, `test_v2_architecture.py`,
  `test_control_center_shell_layers.py`, `test_brain_cli.py` : **231 passés**, 0 échec ; navigateur du rapport :
  4/4 (dont l'attente de la messagerie).
- Sondes de la QA rejouées sur le code corrigé : `probe_canaries.py` → `LEAKS: {}` (y compris le titre du Board),
  `prompt leaks: []`, BLOB vidé ; `probe_confine.py` → `OUTSIDE content via hardlink: False`, reste inchangé.
- **Essai réel par l'interface** (archive `eefbd016`, `%TEMP%\v12s07r`, édition `presentation`, ports 55653-55656,
  transport `outbox`), en **mode développement** (`.env` à la racine du code archivé) puis en **mode produit
  simulé** (marqueur `jarvis-product.json` dans le code, `LOCALAPPDATA` du bac, `config\.env` de la maison) :
  17 canaris semés dans la base (JSON imbriqué sur deux niveaux, `refreshToken`, `OPENAI_API_KEY` en JSON,
  `export ELEVENLABS_API_KEY=` collé, `Bearer`, `AIza`, la valeur du `.env`), dans la mémoire (PEM, PGP, PEM chiffrée,
  PuTTY, `password=`, `ghp_`, valeur du `.env`), dans des noms de fichiers (forme `sk-ant-…` et valeur du `.env`),
  un `.ppk`, les réglages et la description ; erreur contrôlée réelle (présentation tronquée). Préparation →
  « Signaler un problème » → refus sans consentement → consentement → Envoyer → rapport IA réel → boîte d'envoi de
  test. Scan complet des deux zips (octets décompressés, noms, bases ouvertes) : **aucun canari** (la seule alerte du
  scanner était son heuristique de fragment : `0123456789abcdef`, la fin d'un canari, est aussi dans l'id de la
  présentation tronquée ; la valeur complète est absente). Noms `masque-….md`, `.ppk` exclu, base sans coffre,
  `freelist 0`, `integrity ok`, `unknown_mentions` vide.
- Preuves (zips, décompressés, captures, journaux, copies des bases des deux bacs, dossiers des sondes) :
  `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s07r\`.
  Bac supprimé après copie ; aucun processus du bac ne reste ; le JARVIS vivant n'a pas été touché.

### Coût

Deux rapports IA réels : 0,097 $ + 0,091 $ = **0,188 $** (budget 0,20 $).

### Non vérifié (inchangé ou nouveau)

- Le vrai MAPI (HV-SUPPORT-01) ; le DPAPI réel du produit installé (le produit simulé du bac n'a pas de clé scellée).
- Un secret sous un nom ordinaire et sans forme reconnaissable (ni connu par `.env`, ni par le coffre) reste lisible :
  limite assumée du masquage par règles.
- Le balayage de `.work-*` à l'ouverture suppose une seule création à la fois sur ce dossier : une commande
  `support-bundle` lancée pendant l'ouverture du Control Center pourrait perdre son dossier de travail (elle échoue
  alors avec sa cause, sans paquet partiel).
