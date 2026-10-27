# Contre-relecture de la reprise QA de la Slice 03 (`03-research-reuse-freshness-orchestration`)

Diff relu : `c0dd317d..1fa6aa3b` (`7039a66e` code et tests, `1fa6aa3b` docs, LOG et I-003). Worktree `pev12` à `0fa3dec7`. Skills : `qa-verification` et `code-review`. Je n'ai modifié aucun code produit. Je n'ai pas lancé de cerveau ni de JARVIS (coût : 0 $). Le code de Core et du domaine a tourné sur les documents réels du bac QA et sur des fichiers fabriqués.

Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s03cr\`
- `replay.py` et `replay_2026-10-27.txt` : `read_board_memory`, `with_board_research` et `render_board_research` sur une copie de `v12s03qa\board-memory`.
- `probe.py` et `probe.txt` : analyseur, déclencheurs, `matches_topic`.
- `store_probe.py` et `store_probe.txt` : en-têtes longs lus par le vrai `FileBoardMemoryStore`.
- `mutate.py` et `mutations.txt` : mutations jouées sur une archive de HEAD.
- `full-*.json` et `pres-*.txt` : comparaison des prompts.

## Verdict : **FAIL** (reprise courte et ciblée)

B1 et B2 sont corrigés : la preuve est faite sur les documents réels du bac. M3 n'est corrigé qu'en partie. La correction de m4 rouvre la boucle de rafraîchissement de B2 pour toute source dont la vérification échoue durablement, et le document Gamma réel du bac en a une.

## Findings

### F1 — MAJEUR, `blocking` : une source en échec durable met son document en « rafraîchir » à chaque tour, sans fin
- Emplacement : `jarvis/domain/research_freshness.py:335-336` (`if source.failed: return True`) ; consigne `jarvis/domain/subagent_roles.py:670-672` : « garde son ancienne date checked et reçoit | status: failed ». Aucune date de tentative n'est notée, aucun délai avant de réessayer.
- Scénario réel : `gamma-outil.md` du bac cite `https://gamma.app/pricing | checked: 2026-10-27 (échec HTTP 403, non lue)`. Le 27/10, le jour même du rafraîchissement, chaque tour donne `partial_refresh : https://gamma.app/pricing` (`replay_2026-10-27.txt`, 12 demandes sur 12). Le `[web-research]` relancé retombe sur le 403, la consigne fait réécrire `status: failed`, et le tour suivant redemande la même chose (`probe.txt`, `failed_recent` → `partial_refresh`). On retrouve l'effet de B2 (« rafraîchi à chaque tour qui touche le sujet »). Cela contredit aussi l'exemple de `docs/subagent-roles.md:897` (« un document rafraîchi aujourd'hui → `reuse` »).
- Piste : noter la date de la tentative (`tried:`) et ne réessayer qu'après l'âge toléré. D'ici là, signaler la source ratée sans demander de rafraîchissement, comme `old_sources`.

### F2 — MAJEUR, `polish` : M3 n'est corrigé qu'en partie. Il reste des faux positifs sur « à jour » et un rapprochement des sujets par des mots génériques
- `research_freshness.py:100` : « a jour » déclenche toujours, sans l'exclusion propre au deck qui ne vaut que pour « dernier ». Les demandes « Mets à jour la slide sur les outils vidéo », « Fais une mise à jour de la diapo 3 » et « Est-ce que le deck est à jour ? » produisent toutes `('à jour',)` (`probe.txt`). En édition de présentation, c'est la consigne la plus courante.
- `research_freshness.py:173-175` : tout mot de 4 lettres ou plus fait l'affaire, donc « prix » et « outils » rapprochent des documents sans rapport. Le cas exact de M3 reste là : « Quel est le prix actuel de Synthesia en 2026 ? » marque le document Gamma « sujet du tour » et demande de rafraîchir `help.gamma.app/...what-is-gamma` et `wikipedia` (`replay_2026-10-27.txt`). « Mets à jour la slide sur les outils vidéo » fait de même. Le test `derniers modèles d'OpenAI` ne le voit pas, parce qu'il ne partage aucun mot avec la note Gamma.

### Mineurs
- **m1** `research_freshness.py:220` : un horodatage avec millisecondes (`checked: 2026-10-27T11:35:12.450Z`) est pris pour un code HTTP 4xx, et « vidéo » contient « vide ». Les deux sont lus comme une vérification ratée (`probe.txt`, `ts_ms` et `checked_video`).
- **m2** `research_freshness.py:293` et `board_hydration.py:120` : un en-tête **jamais fermé** dans un fichier de plus de 2 Kio est traité comme « trop long ». La décision est prise sur ce qui a été lu, corps compris, et donne `reuse` (`store_probe.txt`, `e-unterminated-big.md`). Le même défaut dans un fichier de moins de 2 Kio donne `freshness_unknown`. Les sources au-delà de 16 Kio ne sont pas jugées. Le cas est documenté et signalé dans le brief.
- **m3** Faux négatifs de `matches_topic` : un sujet court (« IA », « LLM ») ne correspond jamais, et il n'y a pas de synonymes. Faux positifs restants : « dernière chose : … », « en dernier, … », « le dernier mot », « current slide ».
- **m4** Front-matter YAML valide mais inattendu : des sources en mappings imbriqués (`- url:` / `checked:` / `status: failed`) perdent leur date et leur échec, ce qui donne `reuse`. `topic: >` donne le sujet « > ». Le gabarit imposé aux rôles limite le risque.
- **m5** Le cerveau voit toujours « rafraîchir » sur les documents hors sujet (`claude_local.py:276`, inchangé), sans consigne d'agir seulement sur le « sujet du tour ».
- **m6** `research_freshness.py:163` et `:262` contiennent un U+FEFF littéral, invisible (`lstrip("﻿")`). Il existait déjà avant la reprise. Mieux vaut écrire `"\ufeff"`.

## Vérifié OK
- **B1** : l'en-tête réel de 3 907 octets donne `reuse`, avec son sujet et sa date. En-têtes de 3 Kio avec BOM et CRLF : lus. 17 Kio et 30 Kio : `front_matter_too_long` signalé, la date est gardée. Petit en-tête non fermé : `freshness_unknown`.
- **B2** : la publication ne déclenche plus rien. Le document outils (10 sources « déjà anciennes ») donne `reuse` le jour même, y compris avec « derniers ». Un `checked` de source ancien donne `partial`. Une source jamais vérifiée hérite du `checked_at` du document, ce qui est conforme à la doc.
- **M3 (ce qui tient)** : « Modifie la dernière diapo », « la dernière version du deck », « l'année seule » et « maintenant » ne déclenchent plus rien. L'actualité est bornée aux documents `on_topic`. Majuscules, accents et apostrophe typographique sont traités.
- **m5 à m7** : dates entre guillemets, surplus de plus de 8 documents dit au cerveau, tri par sujet puis par récence.
- **Mutations** : 8 sur 8 tuées : échec ignoré, pas de relecture à 16 Kio, actualité appliquée à tous les documents, exclusions du deck retirées, B2 réintroduit, `on_topic` forcé dans Core, `unread` tu, `complete` forcé.
- **`full` à l'octet** : `c0dd317d` et `1fa6aa3b` donnent 185 542 octets identiques (`cmp`). Le prompt du cerveau `presentation` est identique lui aussi.
- **Tests** (`.venv` principal, depuis `pev12`) : fraîcheur, empreinte, continuité, périmètre du cerveau, prompts confinés (144) ; brief, hydratation ×2, session_manager (85) ; board_brains ×5, capacités, parité (125 et 1 échec connu `ui_intent_publish`, inscrit dans `known_failures.json`) ; rôles, routage, méthodes (211). Total : 565 verts, 1 échec connu.
- **Fins de ligne** : les 12 fichiers sont en LF dans l'index (`git ls-files --eol`). Pas de BOM de fichier, pas de caractère de contrôle, `git diff --check` est propre.

## Non vérifié
- Le comportement réel du cerveau devant F1 et F2 (budget 0 $). Seul le bloc produit par Core est prouvé.
- `full` à HEAD `0fa3dec7`, qui inclut la fusion S05 : hors du diff de la reprise.

## Résumé
B1 et B2 sont corrigés et prouvés sur les documents réels. Les tests et le `full` sont intacts, et les mutations sont toutes tuées. Il reste deux défauts à reprendre. F1 : une source en échec durable relance le rafraîchissement à chaque tour, c'est la boucle de B2 par un autre chemin, et elle se produit sur le document Gamma réel. F2 : « à jour » et des mots génériques comme « prix » ou « outils » ramènent les faux positifs de M3, y compris le cas exact du rapport initial.
