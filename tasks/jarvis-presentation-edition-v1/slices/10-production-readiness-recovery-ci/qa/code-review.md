# Slice 10 — QA code review + qa-verification

Revue : 2026-10-27, agent QA (code-review, qa-verification, error-handling). Branche
`task/jarvis-presentation-edition-v1`, worktree `pev1`, commits `79d1c7c5..77ee25e3`. Aucun code produit modifié ;
aucun JARVIS, installeur ni build lancé ; le Core 127.77.0.1:17653 n'a pas été touché. Toutes les mutations ont été
faites sur des copies ou par substitution en mémoire, sous
`C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\qa10\`.

## Verdict recommandé

**FAIL** : 1 bloquant, 2 majeurs, 10 mineurs. Le reste de la Slice est solide : vérificateur, port d'export,
lanceur, sonde de remplacement, procédure de retour arrière et Issues déclarées sont conformes et testés. Les trois
corrections attendues sont courtes. La décision revient au PM.

## Ce qui a été lancé (observé)

| Commande | Résultat |
| --- | --- |
| `python -B scripts/verify_release.py` | `Release verification passed.` (22 s) |
| `pytest test_release_tooling test_support_bundle test_diagnostic_redaction test_v2_architecture test_product_launcher test_product_readiness` | 90 passés |
| `pytest test_release_update_profile test_product_setup test_presentation_render_service test_remotion_isolation test_schema_migrations` | 367 passés |
| `pytest test_brain_cli test_launcher test_data_root test_board_brains_readiness test_presentation_export_after_edit test_product_edition test_product_readiness_js` (édition `full`/dev) | 85 passés |
| `scripts/release_test_gate.py --suite release` | VERT : 29 fichiers, 703 passés, 2 sautés |
| `scripts/release_test_gate.py --suite unit --only` (8 fichiers des échecs listés + export) | VERT : 269 passés, 10 échecs, tous connus |
| Mutations de la porte (12 racines jetables), du vérificateur (22), fuite du paquet de support (1 scénario, 12 aiguilles), WAL en lecture seule (1) | voir les constats |
| `git ls-files --eol` + recherche d'octets de contrôle dans les 41 fichiers à `77ee25e3` | index tout en `i/lf` ; aucun caractère de contrôle (CRLF et mixte seulement dans l'arbre de travail : autocrlf) |

## Constats

### BLOQUANT

**B1 — La porte des tests ignore le code de sortie de pytest : une session interrompue est VERTE, même avec zéro test
lancé.** `scripts/release_test_gate.py:128-133` lit le rapport du greffon et `judge` (`:165-180`) ne regarde jamais
`exitstatus`. Le greffon écrit son rapport dans `pytest_sessionfinish` (`scripts/release_test_gate_plugin.py:32-38`),
ce qui se produit aussi après `KeyboardInterrupt` ou `pytest.exit()` (exitstatus 2).
- Preuve (racines jetables `gate-g1`, `gate-g12`) : un test qui appelle `pytest.exit("stop")`, ou qui lève
  `KeyboardInterrupt`, suivi d'un fichier dont le test échoue sans être listé → `0 passés, 0 en échec`, `VERT`,
  **code de sortie 0**, rapport `"green": true, "passed": 0`. Le témoin (`gate-g3`, échec non listé sans
  interruption) est bien ROUGE, code 1.
- Scénario réel : `tests/unit/test_presentation_studio_variants_service.py:342` lève exprès `KeyboardInterrupt`
  dans le code testé. Si une régression le fait sortir de `pytest.raises` (`:348`), par exemple parce qu'il est levé
  depuis une autre tâche ou un autre appel, pytest arrête la session : le reste de la part ne tourne pas, et la part
  de CI comme `release_info.py` (qui accepte tout verdict `green: true`) déclarent le candidat vert.
- `test_a_pytest_crash_is_a_red_gate_never_a_pass` ne couvre que le rapport absent, pas un rapport écrit après une
  interruption.
- Correction attendue : une porte rouge si `exitstatus` n'est ni 0 ni 1, si `exitstatus` vaut 1 sans aucun échec
  constaté, ou si aucun test n'a passé ; plus un test de régression `pytest.exit` / `KeyboardInterrupt`.

### MAJEUR

**M1 — Les parts navigateur dépasseront très probablement leur `timeout-minutes: 60`, et `package` ne tournera
jamais.** `.github/workflows/ci.yml:85`. La mesure de l'implémentation elle-même
(`scratchpad\s10\gates\browser-1.log`) donne `7 fichiers … 111 passed in 729.00s`, soit environ 1,7 min par fichier.
185 fichiers sur 4 parts font environ 46 fichiers par part, soit environ 80 min, et le LOG annonce 1 à 9 min par
fichier. Une part qui atteint son délai fait échouer le job `browser`. Comme `package` déclare `needs: [static, tests,
browser]` (`:114`), aucun paquet ni artefact de release n'est alors produit : le critère « CI runs and records results
for the release candidate » ne peut pas être atteint avec ce découpage. I-010 point 1 cite bien « la durée des
parts », mais les chiffres sont déjà connus. Recommandation : 10 à 12 parts navigateur, ou un `timeout-minutes`
calé sur la mesure, plus une durée par part écrite dans le rapport de la porte.

**M2 — Le paquet de support ne transmet aucun secret connu au masqueur : une valeur de `config\.env` ou de
`core.token` qui apparaît seule dans un journal est copiée en clair.** `jarvis/runtime/support_bundle.py:149`
construit `DiagnosticRedactor(sources.environ)` sans `known_secrets`, alors que le masqueur le prévoit
(`jarvis/domain/diagnostic_redaction.py:61,66,71`). Preuve (`qa10\bundle_leak.py`) :
`INFOMANIAK_TOKEN=Zq7Xv2Lm9Pw4Rt8Ks1Hd6Fn3` dans `.env` et la ligne `connecting upstream with token
Zq7Xv2Lm9Pw4Rt8Ks1Hd6Fn3` dans `core.log` donnent un `logs/core.log` du zip qui contient la valeur. Il en va de même
pour la valeur de `core.token`. Le masquage par forme ne peut pas reconnaître un jeton opaque (Infomaniak, Circuit
Toolbox, jeton local). Correction attendue : passer les valeurs de `.env` et le contenu de `core.token` en
`known_secrets`, plus un test avec un secret sans forme reconnaissable.

### MINEUR

- **m1 — Une exécution vide n'est pas détectée.** `release_test_gate.py:136-142,178` : un test `failing` listé qui
  est SAUTÉ ne compte pas comme périmé (`gate-g2` : VERT). Le rapport ne compte pas les tests sautés. Sur un runner
  sans Chrome, les tests navigateur se sautent (`pytest.skip("Chrome absent")`, `skipif(CHROME is None…)`) et la part
  reste verte, avec les échecs connus « vus » nulle part. Recommandation : compter `skipped` dans le rapport, et
  rendre la porte rouge si un test `failing` listé n'a pas échoué dans la part qui contient son fichier.
- **m2 — Formes génériques non masquées** (`diagnostic_redaction.py:27-35`, `qa10\leak.py`) :
  `postgres://bob:hunter2hunter2@localhost/db` passe en entier (sans domaine de premier niveau, la règle des adresses
  ne s'applique pas). `https://admin:S3cr3tPass@db.example.com` n'est masqué que par accident (`admin:<email>`). Passent
  aussi `pwd: hunter2`, un secret client Google nu `GOCSPX-…` (client OAuth HV-INSTALL-02), un code d'autorisation
  `code=4/0…` et les clés AWS. Couverts : `sk-…`, `sk-ant-…`, `ghp_`/`github_pat_`, `Bearer`, JWT, `refresh_token`,
  `1//0…`, `password=`, `x-api-key:`, e-mails, `C:\Users\<nom>` (y compris en 8.3 et en JSON échappé), OneDrive.
  Recommandation : une règle `scheme://user:pass@` générique.
- **m3 — Le contenu de l'utilisateur est filtré par liste noire.** `diagnostic_redaction.py:40-42`,
  `support_bundle.py:177,190`. Le champ `message` de `errors.jsonl`, les clés hors liste (`title`, `query`, `words`…)
  et chaque ligne des journaux `core`/`ui`/`voice` sortent avec seul le masquage des secrets. Preuve : « Plan secret
  de fusion » (titre), « chiffres du trimestre » (`query`), « final transcript: … » (`voice.log`) sont dans le zip.
  Je n'ai trouvé aucun `print` ni `logging` de transcription dans `jarvis/` ; le risque dépend donc des futurs
  journaux. Recommandation : une liste blanche pour `data` (identifiants, codes, compteurs) et un `message` borné.
- **m4 — Le contrôle des primitives d'exécution reste textuel** (`scripts/verify_release.py:211-226`). Il laisse
  passer `from subprocess import run`, `shell = True` (avec espaces), `os.system (`, `os.popen(` et
  `subprocess.check_output(..., shell=1)`. Les aiguilles sont les mêmes qu'avant : ce n'est **pas un affaiblissement**.
  La liste revue est appliquée et sa péremption est détectée (mutation tuée), là où l'ancienne règle échouait déjà
  sur `main`. Elle ne couvre ni `Popen` ni `asyncio.create_subprocess_*`. Recommandation : un contrôle par AST.
- **m5 — Composants exclus : la correspondance se fait sur le nom exact** (`verify_release.py:271-274`).
  `sherpa_onnx==` (tiret bas) et `onnxruntime-directml==` / `onnxruntime-gpu==` passent ; la casse est gérée. Le risque
  est faible, car le verrou est généré. Recommandation : normaliser les noms selon PEP 503 et chercher le préfixe.
- **m6 — Les actions sont épinglées par étiquette (`@v4`, `@v5`), pas par SHA,** dans le job qui construit
  l'installeur (`ci.yml:40,43,68,75,128,140,152,157`). C'est admis dans `docs/release.md` › *Out of scope*. Le reste
  est correct : `contents: read` seul, aucun `pull_request_target`, aucun secret, donc rien n'est exposé aux PR de
  forks ; le cache de build est revérifié par SHA-256. Il n'y a ni attestation de provenance
  (`attest-build-provenance`) ni signature.
- **m7 — `release_info.py:132` accepte zéro rapport de porte, ou un jeu partiel.** Il n'attend ni les 8 parts ni les
  suites. Les rapports ne portent pas de révision, et `source_revision` n'est pas comparé à `GITHUB_SHA`. En CI, `needs`
  en limite l'effet ; un usage local peut joindre des verdicts périmés.
- **m8 — Matrice Python.** Seule la version 3.14.6 est désormais testée, alors que `pyproject.toml:9` déclare
  `requires-python = ">=3.11"`, qui n'est donc plus vérifié. Ce n'est pas une régression du développement courant :
  le poste et le produit sont en 3.14 sous Windows, et l'ancienne matrice Ubuntu n'avait jamais tourné. L'abandon de
  `-W error::ResourceWarning` est justifié (jamais mesuré), mais rien ne le suit. Recommandation : relever
  `requires-python`, ou garder un job 3.11 léger, et ouvrir un suivi pour `ResourceWarning`.
- **m9 — Le commentaire de `schema_versions` est inexact** (`support_bundle.py:106-110`). Avec un `-wal` présent et
  sans `-shm` (arrêt brutal, copie), `mode=ro` CRÉE un `-shm`. Preuve : `qa10\walro.py`, la base et le `-wal` restent
  identiques à l'octet, aucun rejeu, mais `jarvis.sqlite3-shm` apparaît. Ce n'est pas contraire à `CLAUDE.md` (le
  `-wal` n'est ni rejoué ni supprimé), mais la phrase « rien de nouveau n'est créé » et la ligne « no `-shm` created »
  de la doc sont fausses dans ce cas.
- **m10 — Retour arrière (`docs/release.md` › *Rollback*).** La procédure est conforme à `CLAUDE.md` : base et
  `-wal`/`-shm` mis de côté ensemble, jamais supprimés ; `.bak` copié et non déplacé ; `_backup_before_migration`
  n'écrase jamais un `.bak`. Deux trous subsistent. « rename the old `.v<old>.bak` first » ne dit pas vers quel nom.
  Un deuxième retour arrière vers la même version heurte le nom `<db>.v<new>.before-rollback.bak`, et rien n'est
  prévu.

### Observations

- `ci.yml:23-25` : `cancel-in-progress: true` sur `github.ref` annule aussi un build de release en cours sur `main` à
  chaque nouveau push.
- `support_bundle.py:203-206` : `_cap` coupe en octets, donc éventuellement au milieu d'un caractère UTF-8 ou d'une
  ligne JSON. Avec les bornes actuelles (400 × 2000), le seuil de 1 Mio est rarement atteint. Un `.tmp` reste en
  place si `write_bytes` échoue au milieu.
- Le backslash en tête de `\\?\C:\Users\…` est réduit à un seul après masquage. Sans effet sur la confidentialité.

## Points vérifiés et conformes

- **Échecs connus** : liste explicite et datée (22 `failing`, 3 `intermittent`, `review_by` au 2026-12-31 ou au
  2026-11-30). Il n'y a ni motif ni entrée par fichier ; un `kind` inconnu et une entrée incomplète sont refusés ;
  une entrée orpheline est attrapée par `test_every_known_failure_names_an_existing_test_and_is_dated`. Mutations
  tuées : échec non listé (G3), entrée périmée (G4), `review_by` dépassé (G5), intermittent qui échoue aussi seul
  (G6, relancé exactement 2 fois), erreur d'import (G7), `os._exit` (G11). Un intermittent qui passe à la relance est
  toléré (G10), comme prévu. Les entrées `failing` restent vérifiées test par test : un nouvel échec dans un test
  déjà listé est masqué, une limite inhérente que borne la date `review_by`.
- **Vérificateur** : sur les mutations de capacités et d'édition, 7 sur 7 sont tuées (Bash natif, `PowerShell`
  retiré de la liste de refus, `permission_mode=default`, `--chrome`, Codex, repli sur le PATH, `ffprobe` non
  possédé). Sont tuées aussi : `onnxruntime==` et `MediaPipe==` dans le verrou, la version et le pointeur
  d'`ARTIFACT_INFO`, un nouveau `subprocess.run(`, une entrée périmée. La mutation `developer_surfaces` n'a pas pu
  être injectée (`mappingproxy`) ; c'est couvert par `test_release_tooling.py:60`.
- **Port `jarvis/ports/document_export.py`** : un `Protocol` dans `ports/`. Le cœur `document_export_service.py`
  n'importe plus l'adaptateur. La construction se fait dans la racine de composition `v2_app.py:82`, sous
  l'exception nommée de `test_v2_architecture.py:47-49`. Architecture correcte, et le test d'architecture est vert.
- **Issues** : I-009 point 1 (`probe_swappable` avant la vérification ; état d'opération à côté de la cible, repris
  si la remise en place échoue ; 3 tests), point 2 (`process_ref` et lecteur unique `launcher_alive`, repli sûr sur
  le PID) et point 5 (dernière ligne de `claude auth status` masquée puis bornée, `brain_cli.py:125-128`) : réels.
  I-007 point 2 (`--no-cache-dir`, `build_package.py:254`) et point 3 (attente bornée de `cleanup`, `thread_time`) :
  réels, sans entrée dans la liste. I-002 point 5 : mesure documentée (181 caractères), plausible ; non remesurée ici.
- **Zip du paquet de support** : noms relatifs fixes (`bundle.json`, `config-keys.json`, `logs/*`), aucun chemin
  absolu, aucun `..` ni `:`. Aucune base, ligne SQLite, présentation, valeur `.env` ni message de trace ; nom
  d'utilisateur, e-mail et racine personnelle masqués ; ligne de 5 000 caractères bornée.
- **Migrations** : aucun changement de schéma ; bases de test dans `tmp_path` uniquement.
- **JARVIS quotidien (`full`, dev)** : les changements touchent le lanceur et l'installeur du produit, la préparation
  (`launcher_alive`, aucun `launcher.json` en dev), un type de port et une sous-commande CLI. Les 85 tests de
  l'édition `full` passent ; aucune régression constatée.
- **CI, scripts appelés** : chaque étape appelle un script qui existe et accepte ces arguments (`build --out --cache
  --rev`, `verify <dir>`, `installer --package --out`, `package_smoke --installer --work --report`, `release_info
  --package --installer --smoke-report --out --gate-report`, `release_test_gate --suite --shard --report`).
  `fetch-depth: 0` est nécessaire à `git show`.

## Non vérifié

- Exécution réelle de la CI sur un runner GitHub (A12) : disponibilité de Python 3.14.6 dans `setup-python`, durée
  réelle des parts, Chrome du runner.
- `package_smoke.py` de bout en bout, build, installeur : laissés à l'agent de l'essai réel, seulement lus ici
  (aucun `taskkill`, mises à mort par `process_tree.kill_tree` avec l'heure de création).
- Suites `unit` et `browser` complètes : seuls les lots ci-dessus ont été lancés.
- Reproductibilité de `package_sha256` entre deux machines.
