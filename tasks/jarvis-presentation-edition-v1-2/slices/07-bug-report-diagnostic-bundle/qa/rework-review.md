# Contre-relecture de la reprise QA — Slice 07 « Signaler un problème »

- Date : 2026-10-27 · Agent de contre-relecture (skills `qa-verification`, `code-review`) · niveau **critique** (secrets)
- Diff relu : `7a3cbb20..48670291` (`eefbd016`, `48670291`), worktree `pev12c` en lecture seule ; mutations sur une
  copie `git archive` (`%TEMP%\v12s07cr\src`)
- Sondes et sorties : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s07cr\`
  (`probe_redact.*`, `probe_fp.*`, `probe_snap.*`, `probe_real*.txt`, `probe_bundle.*`, `mutate.py`, `mutations.txt`)
- Canaris neufs (`CRZ…`, `CRS…`, `CRB…`, `Dev…`) : aucun n'est repris de la QA ni de la reprise. Aucun JARVIS lancé,
  aucun MAPI, aucun cerveau payant (0 $).

## Verdict : **FAIL**

Les findings de la QA sont corrigés pour leurs formes testées : B1 (JSON imbriqué, clés `NOM=` / `NOM:`), M1, M2, M3,
m1 à m5. En revanche, la forme **PowerShell** de la même fuite B1 (`$env:NOM="valeur"`) passe en clair dans la base,
la description, `report.md` et **le prompt envoyé au modèle**. Le correctif tient en une ligne.

## Findings

### Bloquant

**B1' — `$env:NOM_SECRET="…"` (PowerShell) n'est jamais masqué, y compris dans le prompt.**
`jarvis/domain/diagnostic_redaction.py:81` (`_NAMED_VALUE`) : le préfixe accepte `export ` mais pas `$env:`. La
correspondance démarre sur `env`, prend `:` pour séparateur et `OPENAI_API_KEY=` pour valeur, puis la rend intacte
(`env` n'est pas sensible). Elle a pourtant consommé le nom, qui n'est donc jamais réexaminé. `_CREDENTIAL_PAIR` ne
prend pas le relais (`_` devant `api_key`).
- Sonde : `$env:OPENAI_API_KEY="CRZ62…"`, `$env:DEEPGRAM_API_KEY = "CRZ63…"`, `$env:GITHUB_TOKEN=CRZ64…` →
  **LEAK** en `text` et en `cell` (`probe_redact.txt`).
- Paquet complet (`probe_bundle.txt`) : canari `ps` présent dans `context/description.txt`, `report.md`,
  `state/jarvis.sqlite3` et **dans le prompt**.
- C'est l'équivalent Windows exact du scénario B1 (`export ELEVENLABS_API_KEY=…`), sur le poste cible.
- Correctif suggéré : préfixe `((?:export\s+|\$env:|set\s+"?)?)`, plus un canari `$env:` dans `test_support_report_qa.py`.

### Majeur

**M-a — Les paires `{"name": "<NOM_SECRET>", "value": "…"}` passent en clair.**
`diagnostic_redaction.py:158-175` (`deep`) n'examine que la clé de chaque valeur. Un tableau de variables
d'environnement, des en-têtes HAR ou une configuration MCP/Docker (`[{"name":"X-Api-Key","value":…}]`,
`[{"key":"DB_PASSWORD","value":…}]`) laisse donc passer la valeur, dans une cellule comme en texte libre (4 canaris
LEAK dans `probe_redact.txt`, et `pairs` LEAK dans `state/jarvis.sqlite3` du paquet complet). Correctif suggéré : dans
`deep`, quand un objet a `name`/`key` sensible et une chaîne sous `value`, masquer `value`.

### Mineurs

- **m-a — Faux positifs sur les identifiants `*_key`.** `KEY` seul suffit (`:70`). Sur une COPIE de la vraie base
  (`jarvis.sqlite3.v9.bak`, 18,6 Mo), 422 cellules ont perdu des identifiants utiles au diagnostic :
  `supersedes_key` (279), `output_key` (87), `idempotency_key` (55), `credential_ref` (1). Le texte
  `KeyError: 'board_id'`, `Primary key: board_id`, `"key": "ui.theme"` et `"signature": "def run(...)"` sont masqués
  aussi (`probe_fp.txt`). En revanche, `token_count`, `max_tokens`, `input_tokens`, les ids, horodatages et chemins
  restent lisibles. Suggestion : ne retenir `KEY` que précédé d'un mot de secret (`API`, `ACCESS`, `PRIVATE`,
  `SECRET`, `SESSION`, `SUBSCRIPTION`…) ou nu ; ajouter `IDEMPOTENCY`, `SUPERSEDES`, `OUTPUT`, `SORT`, `PARTITION`,
  `PRIMARY`, `CACHE`, `REF` aux mots descriptifs ; exclure les noms finissant par `Error`.
- **m-b — Durée.** Copie réelle de 18,6 Mo : 30,1 s contre 14,5 s avant la reprise (×2). Base synthétique de 62 Mo,
  proche de `MAX_DATABASE_BYTES` : 158 s pour le seul masquage. Avec la seconde base et le rapport IA, l'échéance de
  l'interface (`CREATE_DEADLINE_MS = 210000`) peut être dépassée sur ce poste. Le compteur `text_values_masked` vaut
  8 647, mais seulement 422 cellules sont réellement masquées : les autres sont du JSON reformaté par `json.dumps`
  (`support_snapshot.py:165`). Le chiffre est trompeur et chaque cellule est réécrite pour rien.
- **m-c — Coût quadratique au-delà de 64 Kio** (`diagnostic_redaction.py:45-48`). Quand les marqueurs de début
  (`-----BEGIN … PRIVATE KEY-----`, `Private-Lines:`) se répètent sans marqueur de fin, chaque départ rebalaye 64 Kio :
  `Private-Lines: ` ×8000 (120 Ko) prend 5,2 s, et 240 Ko 16,4 s. Un fichier de mémoire de 1 Mo prendrait de l'ordre
  de 5 min (extrapolation). Contenu peu réaliste ; une PEM normale ×10 000 (670 Ko) prend 0,39 s. Les autres entrées
  pathologiques (barres obliques inverses, `a=`, crochets, guillemets échappés) restent sous 0,4 s.
- **m-d — Le second envoi reste contournable côté interface** (`control_center_support_report.js:301`, `:433`).
  Taper dans la description, ou fermer puis rouvrir le panneau, remet `waiting` à faux. Un nouveau paquet porte alors
  un autre nom et échappe au 409 du service, qui ne protège que le même paquet : un second `MAPISendMail` peut
  partir pendant que le premier attend.
- **m-e — Hors portée raisonnable, mais non masqués** : URL encodée (`client_secret%3D…`, `access_token%3D…` dans un
  `redirect=`), `setx NOM "valeur"`, valeur YAML en liste sous une clé sensible (`tokens:\n  - …`), base64 d'un JSON
  de secrets. Je ne les tiens pas pour bloquants.
- **m-f — Trous de tests** (mutations survivantes) : extension en majuscules (`.PEM`), découpe camelCase
  (`sessionKey`, `privateKey` en dépendent), `MAX_JSON_DEPTH` réduit à 2 (le 3e niveau reste rattrapé par
  `_ESCAPED_PAIR`), fins collées (`joined`, code redondant).

## Vérifié OK

- **B1** : JSON à 3 niveaux (cellule, ligne de journal, base avec `GITHUB_TOKEN` au 3e niveau), `refreshToken`
  imbriqué, `OPENAI_API_KEY` en JSON, YAML (simple ou entre guillemets), TOML, INI, `set NOM=` et `set "NOM=…"` (cmd),
  `ConnectionString` (`Password=`, `Pwd=`, et en JSON), en-têtes `X-API-KEY`, `x-auth-token`, `PRIVATE-TOKEN`,
  `Ocp-Apim-Subscription-Key` et `authorization: token`, secrets connus imbriqués : tous masqués.
- **FTS** : la table FTS5 qui contient du JSON secret est supprimée, ombres comprises ; canari absent des octets ;
  `freelist_count = 0` ; BLOB vidé ; ligne supprimée absente ; aucun `.work` restant.
- **M1** : `sources_from_environment` en mode développement réel (racine = copie d'archive) rend
  `config_dir = PROJECT_ROOT`. Les 6 canaris du `.env` (BOM, CRLF, guillemets doubles et simples, commentaires,
  `export`, nom non sensible) sont absents du zip et du prompt.
- **M2** : noms de fichier ET de dossier piégés → `masque-<hash>` ; extension gardée.
- **M3** : PEM sans saut de ligne final, CRLF, tronquée, dans du JSON, EC, PKCS#8 chiffrée ; PGP en armure ; PuTTY v3
  (corps, `Private-MAC`, sel Argon2). `ID_RSA.PEM` et `client.Key` sont exclus ; `id_ed25519` (sans extension) est
  copié avec son corps masqué.
- **Mineurs de la QA** : lien dur refusé, 409 sur le même paquet, balayage des `.work-*`, rétention des envois en
  échec. Couverts par les tests, code relu.
- **Tests** (dans `pev12c`) : `test_support_report_qa`, `test_support_report`, `test_support_report_js`,
  `test_support_bundle`, `test_diagnostic_redaction` : 60 passés ; mcp_plugins (domaine, service, store, API),
  `test_release_tooling`, `test_cli_stream_tool_redaction` : 366 passés ; `test_support_report_browser` : 4 passés.
  Aucun échec.
- **Mutations** : 4 tuées sur 8 (clé nommée dans `deep`, récursion JSON, `.env` de développement ignoré, noms non
  masqués) ; 4 survivantes (m-f).
- **Fins de ligne** : 9 fichiers en LF (index et copie de travail), aucun caractère de contrôle, `git diff --check`
  propre.

## Non vérifié

Essai réel par l'interface (couvert par la reprise) ; vrai MAPI ; produit installé avec DPAPI réel ; macOS.

## Résumé

FAIL sur un seul point bloquant, au correctif d'une ligne : `$env:NOM="…"` (PowerShell) fuit jusque dans le prompt.
Un point majeur (les paires `name`/`value`) et des faux positifs sur les identifiants `*_key` sont à traiter
ensemble. Tout le reste de la reprise tient sous des canaris neufs.
