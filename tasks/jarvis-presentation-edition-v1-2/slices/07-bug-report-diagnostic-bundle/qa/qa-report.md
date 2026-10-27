# QA — Slice 07 « Signaler un problème » (paquet de diagnostic)

- Date : 2026-10-27 · Agent QA (skills `qa-verification`, `code-review`, `runtime-validation`) · niveau **critique**
- Code : worktree `pev12c`, branche `wt/v12-s07`, diff `c0dd317d..96d7fe59` (lecture seule ; mutations sur une copie
  `git archive`)
- Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s07qa\`
  (`probe1.txt`, `probe2.txt`, `scripts/`, `ui-*.png`, `ui-run*.json`, `unzipped1/`, `unzipped2/`, `sandbox-evidence/`)

## Verdict : **FAIL** (un bloquant : des secrets sortent en clair dans le zip)

Le flux, le consentement, le confinement, l'instantané SQLite, le rapport IA, l'envoi et la rétention sont solides.
En revanche, la garantie « aucun secret dans le zip » ne tient pas pour les bases copiées : leurs cellules JSON ne
passent que par le masquage texte.

## Findings

### Bloquant

**B1 — Les cellules JSON des bases copiées laissent passer des identifiants nommés.**
Fichiers : `jarvis/runtime/support_snapshot.py:133` (`jv_mask` = `redactor.text` seulement, jamais `structured`),
`jarvis/domain/mcp_plugins.py:590` (`_KEY_START` refuse `_` devant la clé) et `:612` (séparateur `["']?` : pas de `\"`).
Scénarios et preuves :
- JSON imbriqué échappé dans une colonne `data` (forme courante des sorties d'outils :
  `"output": json.dumps(result)`, `openai_realtime.py:617`) : `{"tool_output": "{\"refresh_token\": \"…\"}"}` →
  **en clair** dans `state/jarvis.sqlite3`, aussi bien dans la sonde que dans l'essai réel par l'interface
  (`scan_zip` : `nested LEAK ['state/jarvis.sqlite3']`). Même chose pour `"refreshToken"` et `"access_token"` imbriqués.
- Clés de style variable d'environnement : `{"OPENAI_API_KEY": "…"}`, `{"GITHUB_TOKEN": "…"}` dans une base, et
  `export ELEVENLABS_API_KEY=…` dans la mémoire du Board → **en clair** (probe1, essai réel `env_style LEAK`).
Avant cette Slice, ces contenus n'entraient pas dans le paquet. Correctif suggéré : pour une cellule texte qui
s'analyse comme du JSON, appliquer `redactor.structured` (et recommencer sur les chaînes qui sont elles-mêmes du JSON) ;
accepter une clé `UPPER_SNAKE` qui se termine par `_API_KEY|_TOKEN|_SECRET|_PASSWORD` ; ajouter ces canaris aux tests.

### Majeurs

**M1 — En mode développement, les valeurs du `.env` ne sont pas des secrets connus.**
Fichier : `support_bundle.py:701` (`config_dir=None` hors produit installé, donc `env_items` est vide et le `<dépôt>\.env`
n'est jamais lu). Essai réel : une valeur opaque `QA_SERVICE_TOKEN` recopiée dans la mémoire du Board et dans la
description se retrouve en clair dans `board/memory/summary.md`, `context/description.txt`, dans `report.md`, donc
**dans le prompt envoyé au modèle**, et dans le corps du courriel (`.eml.txt`). Le JARVIS quotidien de l'utilisateur
tourne en mode développement. Le modèle a lui-même signalé « une valeur qui ressemble à un jeton, non masquée ».

**M2 — Aucun masquage sur les noms de fichiers de la mémoire.**
Fichier : `support_snapshot.py:247-248`. Un fichier `sk-ant-api03-….md`, ou un fichier dont le nom contient une
valeur connue du `.env`, apparaît en clair dans les noms des membres du zip et dans `manifest.json` (probe1 :
`filename` et `env_quoted` → `<member name>`, `manifest.json`).

**M3 — Seule la forme PEM `… PRIVATE KEY-----` est reconnue.**
Fichier : `diagnostic_redaction.py:43`. Passent en clair : un bloc `-----BEGIN PGP PRIVATE KEY BLOCK-----`, le corps
d'une clé PuTTY `.ppk` (`Private-Lines:`), et le corps d'une PEM chiffrée à l'ancienne (`Proc-Type:`/`DEK-Info:` : le `-`
de l'en-tête arrête la course après 4 caractères). Les blocs OpenSSH et PKCS#8 sont bien masqués.

### Mineurs

- **m1** : un lien dur dans la mémoire est lu (contenu hors racine copié, masqué) ; `st_nlink > 1` n'est pas refusé
  (`support_snapshot.py:254-269`, probe2 `OUTSIDE content via hardlink: True`).
- **m2** : trous de tests. La mutation « BLOB non vidés » **survit** (`support_snapshot.py:156`). Aucun test ne vérifie
  les pages libérées ni les tables FTS (vérifié à la main : `freelist_count = 0`, FTS supprimée, ancien texte absent).
- **m3** : après une réponse `waiting` (messagerie lente), « Envoyer » reste actif
  (`control_center_support_report.js:231`) ; un second clic lance un second `MAPISendMail` pendant que le premier attend.
- **m4** : pendant la collecte, une copie BRUTE de la base vit sous `runtime\support\.work-*\*.work`. Après un arrêt
  brutal, elle reste jusqu'au paquet suivant plus une heure (`support_routes.py:219`, `support_bundle.py` prune). Rien
  ne restait après mes essais.
- **m5** : la rétention (5 paquets) peut retirer un paquet dont l'envoi a échoué et qui n'a pas encore été enregistré.
  C'est conforme à la règle documentée ; à dire dans l'interface ou dans la documentation.

## Vérifié OK

- **Secrets connus** (installé ou bac) : clé de réglages en clair ou scellée, coffre MCP (lignes supprimées, BLOB
  vidés), `core.token`, `.env` du produit avec guillemets ou commentaire, `Bearer`, `Basic`, `X-Api-Key`, cookie,
  mot de passe d'URL, `ghp_`, `AIza`, `sk-ant`, PEM PKCS#8 et OpenSSH : absents du zip et du prompt. Instantané :
  `freelist_count = 0`, FTS supprimée, BLOB vidés, `integrity_check` ok, `VACUUM INTO` sans ancien octet. Aucun
  temporaire laissé dans `%TEMP%` ni dans `runtime\support`, aucune transcription de la CLI sous `~/.claude/projects`.
- **Confinement** : ids `../state`, `..`, `a/b`, `C:\Windows`, vide, NUL, 129 caractères refusés ; jonction à
  `boards` et dans la mémoire refusées. Source jamais modifiée et aucun fichier créé à côté (WAL sans SHM :
  `immutable`, `-wal` non rejoué, `wal_not_read` dit) ; 3 instantanés pendant des écritures : cohérents.
- **Consentement et routes** : 400 sans consentement (`{}`, `"true"` chaîne) ; 403 pour une origine étrangère, un
  autre port local, `null`, `cross-site`, `same-site`, un Host étranger ; nom de paquet traversant → 400. L'interface
  refuse avant tout appel ; aucun envoi sans clic. Destination définie à un seul endroit, remplaçable puis remise à la
  valeur par défaut (vide) ; adresse invalide → 400. MAPI : `MAPI_DIALOG` toujours présent (brouillon, jamais d'envoi
  silencieux), appel dans un fil, échéance de 30 s, `shield`. Le vrai MAPI n'a pas été appelé.
- **Essai réel** (archive `96d7fe59`, bac `%TEMP%\v12s07qa`, ports 58653-58656, édition `presentation`) : erreur
  contrôlée (`pst_…` tronquée → `core.presentation_studio.unreadable`) ; paquet créé par l'interface headless (fenêtre
  de préparation → aperçu → refus sans consentement → consentement → Envoyer) ; dépôt dans la boîte d'envoi de test ;
  transport `none` → 502 `support_send_unconfigured`, zip conservé, ligne visible dans la vue des erreurs ; Envoyer
  refusé dans l'interface puis enregistrement dans la racine d'export ; téléchargement en `attachment`, `no-store`,
  octets identiques. Manifeste exact (membres et tailles). Rétention : 5 paquets gardés, `.zip.tmp` et `.work-*` vieux
  retirés, fichier étranger conservé.
- **Rapport IA** : ancré (faits cités `[E…]`, `[T…]`, `[H:…]` ; hypothèses avec confiance ; cause non affirmée),
  `unknown_mentions` vide, annexe factuelle présente.
- **Tests** : Slice et voisins 50 + 78 + 41 (navigateur) + 197 = **366 passés**, 0 échec.
- **Mutations** : 8 tuées sur 9. Tuées : PEM, coffre, masquage des bases, consentement serveur, liens suivis, id de
  Board, `VACUUM INTO`, consentement UI. Survivante : BLOB (m2).

## Coût

Deux rapports IA réels : 0,107 $ + 0,114 $ = **0,221 $** (budget 0,30 $), 27 à 30 s chacun.

## Non vérifié

Le vrai `MAPISendMailW` (Outlook classique ou nouvel Outlook : HV-SUPPORT-01). Le produit installé avec le DPAPI
réel (couvert seulement par les tests). macOS. Une base proche de 64 Mio. Les liens symboliques de fichiers : la
création demande un privilège absent ici (le code les refuse par `lstat`).
