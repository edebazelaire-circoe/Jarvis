# Reprise et contrôle qualité — 2026-09-12

**État final : validation logicielle terminée.** 1 891 tests réussis, 4 skips
attendus, vérificateur de release réussi avec warnings bloquants. Smoke Realtime
réel réussi séparément. Voir [FINAL-REPORT.md](FINAL-REPORT.md).
Recette acoustique et accès agenda/rappels restent à valider avant bascule du défaut.

## Périmètre et constat

Demande : orchestrer le handoff slice par slice, déléguer et vérifier les résultats.
Branche inspectée : `main`, HEAD initial `ac69078`. Aucun fichier suivi modifié
au démarrage. Le ZIP fourni est conservé et extrait dans son sous-dossier nommé
`jarvis_realtime_brain_orchestration_handoff`.

Le plan du ZIP précède le code présent : l'architecture a déjà été livrée par
`c172bec`, puis modifiée dans les travaux suivants. Le suivi canonique existe dans
[`docs/handoff-realtime-brain/tasks/TODO.md`](../../docs/handoff-realtime-brain/tasks/TODO.md)
et son rapport dans
[`FINAL-REPORT.md`](../../docs/handoff-realtime-brain/FINAL-REPORT.md).
Ne pas reconstruire les services déjà présents sur la base des cases vierges du ZIP.

Skills lus : `caveman`, `coding-guideline` et ses trois références dans
`C:/Users/Clarice/.codex/skills/`. Aucun `AGENTS.md` trouvé dans ce dépôt.
L'observabilité utilise `RuntimeJournal` selon la décision existante 27 ; ce
projet ne contient pas `observability.cli`/LogBroker.

## Plan adapté

1. Vérifier les slices existantes dans l'ordre, avec tests ciblés et warnings
   traités comme erreurs. Conserver commandes/résultats dans
   `validation-2026-09-12.json`.
2. Deux sous-agents relisent indépendamment Core/protocole et Voice/Realtime.
   Les revues peuvent se dérouler en parallèle ; une seule slice est modifiée
   à la fois. Toute correction exige reproduction, test rouge, correction,
   test vert puis revue de l'orchestrateur.
3. Reprendre les gates suivants après clôture de chaque correction.
4. Exécuter la validation générale et le vérificateur de release ; documenter
   séparément les recettes matérielles/fournisseur et leurs limites.

## Checkpoints

| Slice | État de cette reprise | Preuve / suite |
| --- | --- | --- |
| 00 | Vérification initiale terminée | Baseline V2 : 41 réussites. Une première commande visait un fichier inexistant ; aucun test n'avait tourné, commande corrigée. |
| 01 | Tests et revue validés | 40 réussites, contrats/domaine/frontières |
| 02 | Correction 02R revue et validée | Baseline 36 ; contre-vérification élargie de 02R : 117 réussites. Voir `review-02R.md`. |
| 03 | Tests et revue validés | 17 réussites, protocole |
| 04 | Tests et revue validés | 17 réussites, contrôle Realtime ; smoke réel réussi |
| 05 | Correction 05R revue et validée | Contre-vérification orchestrateur : 133 réussites (LIVE, legacy toggle, réflexes, scheduler, intégration). Voir `review-05R.md`. |
| 06 | Tests et revue validés | 24 réussites, réflexes |
| 07 | Tests et revue validés | 39 réussites, migration backend |
| 08 | Correction revue et validée | 33 tests scheduler ; contre-vérification orchestrateur : 91 réussites (scheduler, LIVE, réflexes, intégration). Voir `review-08.md`. |
| 09 | Correction 09R revue et validée | Contre-vérification orchestrateur : 87 réussites. Intention live/reprise cohérente ; fermeture SQLite vérifiée. Voir `review-09R.md`. |
| 10 | Tests et revue validés | 13 réussites, progrès et état public |
| 11 | Tests ciblés validés | 16 réussites, scénarios intégrés |
| 12 | Validation logicielle terminée | 26 réussites ciblées ; smoke réel réussi ; gate final : 1 891 réussites, 4 skips attendus ; vérificateur de release réussi. |

Revue finale croisée : le sous-agent Voice a également relu les corrections Core
02R/09R écrites par l'autre sous-agent, sans trouver de blocage concret. Aucun
changement de code après validation des quatre corrections.

## Retours de revue

- **02R — règlement d'échec backend**, délégué après clôture de 08 : un backend
  qui annonce un travail puis lève une exception laisse son identifiant actif.
  Solder les unités possédées par ce tour, sans annuler les jobs indépendants.
- **09 — ordre d'intention** : une promotion tardive de tour incertain ne doit
  pas remplacer une intention plus récente confirmée.
- **09 — fixture SQLite** : le test de parole tronquée dans
  `tests/unit/test_v2_barge_in.py` remplace la variable du dépôt par un dictionnaire
  et ne ferme pas la connexion. Le warning ressort dans un test ultérieur lors
  du ramasse-miettes ; ce n'est pas une panne de ce test ultérieur.
- **05R — commande mute ponctuée** : `Jarvis mute.` et `Jarvis, mute !`
  sont routés au cerveau au lieu de couper Voice. Reproduction par le vrai
  gestionnaire de transcription, sans matériel. Correction dédiée après 02R,
  avant 09 ; reconnaître la commande exacte malgré la ponctuation, sans
  reconnaître comme commande toute phrase qui la mentionne.

La découverte de 02R est arrivée pendant la correction 08 : elle constitue un
retour explicite vers un prérequis, avant de poursuivre 09–12. Aucun code de
deux slices n'est modifié en parallèle.

### 12R — fiabiliser les fixtures du gate global

Le gate complet a terminé en 582,12 s : 1 890 réussites, 4 skips, 1 échec.
Le test de console qui rapporte l'échec n'est pas propriétaire des ressources :
`Stack.close()` de `tests/unit/test_brain_work_context.py` oublie Core et SQLite.
Les six instances du helper fuient jusqu'à un ramasse-miettes ultérieur.
Correction tests seulement, sans masquer les warnings.

Trois tests de rollback (deux dans `tests/unit/test_deployment.py`, un dans
`tests/integration/test_self_development_end_to_end.py`) essaient de réduire
le délai en remplaçant une constante déjà capturée dans un argument par défaut.
La fixture doit passer explicitement son délai court à la vraie méthode testée ;
aucun délai de production ne change. Correction séparée après fermeture SQLite,
puis reprise du vérificateur complet.

Corrections 12R relues : gate ressources/contexte/console = 70 réussites,
déploiement = 20, scénario E2E = 9, tous en mode strict. Voir `review-12R.md`.
Troisième lancement du vérificateur complet après ces corrections, sans exclusion
de test ni suppression de warning : **1 891 passed, 4 skipped in 221.26 s**,
**Release verification passed**, code retour 0. Les skips concernent deux tests
fournisseur opt-in, les signaux POSIX et les liens symboliques indisponibles.
Le smoke Realtime opt-in a été validé séparément.

Invocation stricte du vérificateur : `PYTHONWARNINGS=error` et
`PYTEST_ADDOPTS=-o asyncio_default_fixture_loop_scope=function`. La première
tentative sans portée explicite a échoué avant tout test sur un avertissement de
configuration pytest-asyncio. Les tentatives restent enregistrées dans
`release-validation-2026-09-12.txt`.

## Preuves d'exploitation

- Smoke réel du 12 septembre :
  `tests/integration/test_live_openai.py::test_real_openai_realtime_brain_speech`,
  1 réussite en 3,28 s. Clé résolue par le magasin existant et transmise uniquement
  au sous-processus de test ; aucun réglage persistant changé.
- Résumeur officiel `scripts/summarize_voice_trace.py runtime/trace.jsonl --json
  --since 2026-09-12` : aucun événement retenu, 5 lignes illisibles. Ce journal
  existant ne constitue donc pas une validation matérielle de cette reprise.

## Décisions préexistantes à préserver

Le suivi canonique documente des arbitrages postérieurs au ZIP, dont le backend
Control Center neutre Claude/Codex, le port séparé de contrôle Realtime,
le routage des tours incertains et la portée de la confidentialité (décisions
21–46). Cette reprise ne les annule pas silencieusement. Le mode `legacy`
reste le défaut tant que les gates de déploiement ne sont pas levées.

Les tests avec faux backends ne prouvent pas l'acoustique sur le poste. Aucune
preuve matérielle ne sera déduite de leur réussite.
