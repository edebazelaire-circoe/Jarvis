# Slice 10 — contre-relecture de la reprise QA

Revue : 2026-10-27, agent de contre-relecture (qa-verification, code-review). Diff relu : `75921f58..79eca5bb`
(`8968850c`, `63697cfa`, `79eca5bb`). Aucun code produit modifié ; aucun JARVIS, installeur ni build lancé ; le Core
127.77.0.1:17653 n'a pas été touché. Les mutations ont été faites sur une copie jetable (`git archive` de `HEAD`) sous
`C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\s10cr\`,
qui a été supprimée ensuite. Les preuves y restent : `mutate.py`, `mutations-1.txt`, `mutations-2.txt`, `probe_m2.py`,
`ps-run-2.log` et `gate-release.json`.

## Verdict recommandé

**FAIL** : 0 bloquant, 2 majeurs et 4 mineurs. B1, M1, R2, R3, m1, m2, m3, m5, m7 (pour la révision), m9, m10, R1 et
la lenteur du masquage sont réellement corrigés, et 22 mutations sur 23 sont tuées. Deux points restent toutefois en
défaut. M2 se contourne avec un `.env` ordinaire. La porte `release` est rouge par intermittence à `HEAD`, sur un
test qui n'est pas listé. Les deux corrections sont courtes. La décision revient au PM.

## Constats

### MAJEUR

**X1 — M2 se contourne : un jeton suivi d'un commentaire dans `.env` sort en clair dans le paquet de support.**
`jarvis/runtime/support_bundle.py:149-170` (`env_items`) réécrit un analyseur de `.env`, alors que
`jarvis/environment.py:25` (`parse_environment_lines`) se déclare « Seul parseur `.env` de JARVIS ». Cette copie ne
retire ni le commentaire ` #…` d'une valeur sans guillemets, ni ce qui suit le guillemet fermant. Elle ne retire pas
non plus la marque d'ordre des octets (BOM), puisqu'elle lit en `utf-8` et non en `utf-8-sig`.
- Scénario : `INFOMANIAK_TOKEN=Zq7Xv2Lm9Pw4Rt8Ks1Hd6Fn3 # jeton pro`. JARVIS charge `Zq7Xv2…`, mais le masqueur reçoit
  `Zq7Xv2… # jeton pro`, que les journaux ne contiennent jamais.
- Preuve (`probe_m2.py`) : avec un commentaire après une valeur sans guillemets, la sonde affiche `LEAK` ; avec
  `'…' # jeton`, elle affiche aussi `LEAK` ; une valeur simple est bien masquée. Avec un BOM, la clé
  `\ufeffINFOMANIAK_TOKEN` apparaît dans `config-keys.json`.
- Correction : passer par `parse_environment_lines` (en `utf-8-sig`, et en ne gardant que les noms si le fichier est
  illisible), plus un cas de test avec un commentaire.

**X2 — La porte `release` est ROUGE par intermittence à `HEAD` : un test de l'installeur qui n'est pas listé fait la
course avec l'auto-effacement du script de désinstallation.** Le test en cause est
`tests/unit/test_product_setup.py:238-239`. Il attend que le dossier et la clé aient disparu, puis exige aussitôt que
le script `.cmd` n'existe plus. Or le script s'efface en dernier. La reprise a ajouté
`if defined VENDOR rmdir "%VENDOR%"` (`jarvis/product_setup.py:906`) entre ces deux moments, ce qui élargit la
fenêtre (ici `target.parent` s'appelle bien `CIRCOE`).
- Preuve : la porte `--suite release` a donné `719 passés, 1 échec NON listé … ROUGE` (`gate-release.json`). Le
  fichier lancé avec ses voisins a échoué 1 fois sur 2 (`ps-run-2.log` : `assert (not False and not True)`, le `.cmd`
  existe encore). Lancé seul, le test passe 4 fois sur 4.
- Effet : les parts `tests` de la CI, et donc `package` (`needs`), tombent au hasard, comme pour R1.
- Correction : côté test, `wait_until(... and not Path(result["removal_script"]).exists(), 40)`. Le produit n'est pas
  en cause.

### MINEUR

- **x3** — `jarvis/product_setup.py:550-560`. La docstring de `setup_owner_alive` promet « identité inconnue :
  vivant (prudence) », mais `started is None` renvoie `False` (mort). `_windows_open` demande
  `QUERY_INFORMATION | QUERY_LIMITED_INFORMATION` (`process_tree.py:247`) ; ce droit est refusé sur une amorce
  lancée « en tant qu'administrateur ». Une installation ou une désinstallation lancée en même temps la croit alors
  morte, et seule la sonde de renommage protège encore son dossier. Le risque est faible ; il faut aligner le code
  (`OpenProcess` refusé avec un PID existant = vivant) ou la docstring.
- **x4** — La mutation « valeur triviale ou courte acceptée comme secret » (`support_bundle.py:175`) survit. Aucun
  test ne vérifie qu'un réglage ordinaire au nom « sensible » reste lisible : `JARVIS_SESSION_TIMEOUT=100000`,
  `KEYBOARD_LAYOUT=azerty`, `BYPASS_HOST=localhost`. L'effet se limite à un sur-masquage ; jamais tout le texte
  n'est masqué, car le seuil de 6 caractères tient.
- **x5** — Le reste de m7 n'est pas couvert. `release_info.py:177-187` accepte un seul rapport vert, même un `--only`
  d'un fichier : il n'exige pas les suites `unit`, `browser` et `release`, ni le nombre de parts. En CI, `needs` le
  compense. `source_revision` vaut `HEAD`, même sur un arbre de travail modifié (`release_test_gate.py:239`). À
  consigner dans I-010.
- **x6** — Secrets du coffre (hors périmètre littéral de M2). Dans le produit installé, `migrate_env_file`
  (`local_secrets.py:257`) déplace les clés des fournisseurs (Deepgram, Porcupine, Tencent, ElevenLabs…) de `.env`
  vers le coffre DPAPI. Elles ne sont donc plus remises au masqueur. Les formes reconnues (`sk-…`) restent masquées ;
  les jetons opaques ne le sont pas. À consigner dans I-010.

## Vérifié OK

- **B1.** `session_problems` rend la porte rouge dans chacun de ces cas : code de sortie 2/3/4/5 ; code 1 sans échec
  (un échec non listé à côté d'un échec listé est `unknown`) ; `shouldstop` ; nombre exécuté inférieur au nombre
  collecté ; rapport tronqué ou absent ; tout sauté ; erreur de collecte. Par lecture, `pytest.exit(returncode=0)`
  dans le dernier test est attrapé (aucun rapport `call`, donc exécuté < collecté).
- **R2.** `release_info.py` refuse : un installeur d'un autre paquet (manifeste embarqué), un essai fait sur un autre
  installeur, un essai qui a installé un autre paquet, une porte d'une autre révision, une porte rouge, l'absence de
  porte, un `GITHUB_SHA` différent.
- **R3.** Le nettoyage ne touche que des `.jarvis-setup-*` dans le parent de la cible. Il épargne le dossier courant,
  le dossier d'un propriétaire vivant et plus ancien, et un dossier dont un fichier est ouvert. `rmdir` sans `/s`
  laisse la maison hors de portée.
- **m3 et m9.** Liste blanche et `immutable=1`.
- **m10.** Les noms exacts de `docs/release.md` sont suivis par `test_release_update_profile.py`.
- **R1.** Correction du test justifiée (« n’est pas enregistrée » contient « enregistré »). Ajouter `preview_failed`
  au bruit attendu est acceptable, car la route est bloquée exprès. 3 passages sur 3 seul (16 à 26 s).
- **Mutations (23).** G1-G5 (porte et greffon), R1-R4 (`release_info`), P1-P5 (dossiers d'amorce ; P4 rejouée sans
  le test instable de X2), S1-S2 (paquet de support), D1-D2 (masqueur) : toutes tuées. S3 survit (x4).
- **Tests.** Résultats :

  | Lot | Résultat |
  | --- | --- |
  | `release_tooling` + `support_bundle` + `diagnostic_redaction` | 39 passés |
  | `product_setup` + `update_profile` | 37 passés |
  | MCP (domaine, service, API) | 327 passés |
  | Lot édition `full` (lanceur, préparation, `brain_cli`, `data_root`, architecture) | 85 passés |
  | `verify_release.py` | `Release verification passed.` |

- **CI.** 10 parts navigateur en 75 min et 4 parts unitaires en 60 min, bornes tenues par
  `test_every_ci_shard_fits_its_timeout_with_margin`. `needs: [static, tests, browser]`. `contents: read` seul,
  aucun `secrets.`. Toutes les parts `gate-*` sont jointes à `release_info`.
- **Hygiène.** Les 20 fichiers sont en `i/lf`, sans CR ni caractère de contrôle, et tous dans le périmètre de S10.

## Non vérifié

La CI sur un runner GitHub (A12), la suite navigateur complète, le balayage `unit` complet, et un essai réel de
l'installeur. Aucune installation n'a été faite.
