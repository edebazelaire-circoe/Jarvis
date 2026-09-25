# Execution log

Reserved for implementation agents. Record durable discoveries, decisions, migrations, QA evidence, benchmark baselines, and handoff notes during execution. Do not treat planning text as evidence of completed work.

## 2026-09-25 — Slice 00 (agent 0)

- Handoff mirrored from Drive `to-do` (folder `1utiHn6KP4UKY1XBRNrikLIreJH9k8ZtO`), 45 files, sizes identical, 23 JSON parse. Drive `Issues/` holds a duplicate `README.md` (identical content).
- Uncommitted user-feedback fixes found on `main` preserved as `fix/barehands-retours-2026-09-25` @ `5ee06d7`; task branch based on it (READINESS D0). `main` untouched.
- Baseline at `5ee06d7`: 8478 passed / 9 failed / 4 skipped over 275 unit files. Inherited failures listed in READINESS §2 — hand this list to every implementer as "not yours".
- Decisions by agent 0 (Human delegated autonomy): Task Type waiver; calibration agent = existing brain in a per-turn calibration mode with always-declared, session-refusing `calibration_*` tools (D1); trial manager lives in the page, transport extended in Slice 06 (D2); `jitterPx`/`reachNorm`/slop ratio moved to Slice 04 (D4); strictly sequential Slices (§5); HV checks batched for close-out.
- Issues filed: ISSUE-01 (scene group drag ReferenceError), ISSUE-02 (two stale prompt tests).
- Readiness: **READY**.

## 2026-09-25 — Slice 01 (implémenteur)

- Contrats canoniques, sans changement de conduite ni d'UI : § 12 de `control_center_barehands_contracts.js` (métriques, `SESSION_EVENT`, `createPinchEpisode`, `createFalseEvent`, `TRIAL_KEYS` + `validateTrialPatch`, `createUserFeedback`, `createEvidence` / `createHypothesis` / `createTrialOutcome`, `createBenchmarkPlan` / `createBenchmarkResult` / `benchmarkComparable`, `DATA_RETENTION`, `checkSchema`) ; § 2 bis de `control_center_barehands_recorder.js` (`readSessionSample`, `validateSessionSample` = point fixe des listes blanches `BLANK_*` existantes, ajouté au balayage `assertDerivedOnly`).
- Doc : `docs/barehands-contracts.md` § 17, décisions 34 à 42 (34 télémétrie, 35 épisode, 36 négatifs, 37 retour, 38 preuve/hypothèse/issue, 39 patch d'essai + « pas de lecteur, pas de calibration », 40 banc, 41 rétention, 42 pas de miroir Python).
- D5 fermé : `releaseDeltaRatio` documenté au § 5 ; plage `travelSlopNorm` 0,002 – 0,014 au § 10 (code vérifié : `HAND_BOUNDS` et `normalizeHandProfile`) ; aide MCP de `sensitivity` corrigée (`settings_mcp.py`).
- D4 rendu exécutable : `jitterPx` a `reader: null`, absent de `TRIAL_ADVERTISED_KEYS`, refusé par `validateTrialPatch` (`barehands_trial_key_not_wired`) ; `reachNorm` hors table (non scalaire). Les brancher ou les retirer reste Slice 04.
- Écarts assumés : invariants `clickSlopPx ≤ dragSlopPx` et `targetZonePx ≤ targetZoneHoldPx` (égalité permise, comme `options()`), pas `<` ; `assistance` (réglage) est la clé d'essai du rayon, pas `targetAssistPx` ; `sensitivity` n'est pas une clé d'essai ; aucun miroir Python (décision 42) — parité tenue par test sur `HAND_BOUNDS`.
- Tests : nouveau `tests/unit/test_barehands_adaptive_contracts_js.py` (15). Bare Hands `test_barehands_*.py` : avant 528 passés / 3 échecs hérités (531) ; après 543 passés / 3 échecs hérités (546), en 3 lots au premier plan. `test_settings_mcp.py` + `test_control_center*.py` : 367 passés.

## 2026-09-25 — Slice 01, reprise après QA (implémenteur)

- MAJEUR 1-2 : lectures par propriété **propre** partout au § 12 (`hasOwn`/`ownValue`) et dans `compareShape` de l'enregistreur ; `{toString:1}`, `constructor`, `valueOf`, `hasOwnProperty`, `__defineGetter__`, `isPrototypeOf`, `__proto__` refusés par le patch d'essai, l'échantillon de séance (enveloppe et événement), le jeu de mesures, le banc et la preuve (test dédié).
- MAJEUR 3 : l'issue d'essai de l'agent ne porte plus de nombres (`comparisons` + `beforeRefs`/`afterRefs`) ; `createMeasurementSet` / `aggregateMetric` / `computeTrialDeltas` / `resolveTrialOutcome` chiffrent de façon déterministe ; références qui se recouvrent refusées (`barehands_trial_refs_overlap`), verdict contredit refusé (`barehands_trial_verdict_contradicted`). `createTrialDelta` supprimé ; `rate` retiré des résumés.
- MINEURS : événements `pointing_intent_start/_end`, `pointer_shown/_hidden`, faux événement `unintended_pointer`, métrique `unintended_pointer_rate` (banc `no_click_tracking`, dimension `false_positive_resistance`) ; règle d'extension explicite ; `exerciseRef`/`trialRef` sur l'épisode ; bornes de valeur par métrique (latences négatives, comptes entiers, `perTrial` ≤ essais), `runAt`, `trialRef`, `profileFingerprint` sur le résultat de banc ; `REPLAY_METRIC_EQUIVALENTS` (3 correspondances) et quantile unique (`R.quantile === C.quantile`) ; ancre `releaseRatio < wakeGapMin` ; plafonds (3 catégories de retour, 32 éléments par liste d'image de séance, historique 3 000 avec `createSessionHistory`) ; aide `sensitivity` exacte avec `travelSlopNorm` calibré.
- Reportés à la Slice 04 (consigne d'agent 0) : constante `wakeHoldMs` du HUD, masquage des essais `pressRatio` par les seuils par main, compositions `sensitivity`/`travelSlopNorm` qui sortent des bornes d'essai, taille du fichier de contrats.
- Tests : `test_barehands_adaptive_contracts_js.py` 15 → 22. Bare Hands : 550 passés / 3 échecs hérités (553), 3 lots au premier plan ; `test_settings_mcp.py` 13 passés.
