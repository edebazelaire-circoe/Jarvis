# Implementation Log

Reserved for implementation agents. Record durable execution notes, decisions, deviations, validation evidence, and follow-up references here during execution.

## S01 — contrat documentaire (2026-10-03)

- Docs seulement : NEW `docs/prefabs.md` (R1–R6 + R9.1, statut « contract — implemented by Slice NN » par section, seules listes de routes) ; `docs/scene-model.md` §« Prefab windows » + « Decision 1, refined » (R8.8) + note sous *Brain tool mapping* ; `docs/ARCHITECTURE.md` un paragraphe dans §Constellation scene store et §Scene renderer (aucun `/api/prefabs`) ; `docs/SECURITY.md` contrôle 16 « Prefab sandbox (contract) ».
- Langue : anglais, comme `docs/scene-model.md`, `ARCHITECTURE.md`, `SECURITY.md`.
- Faits R0 vérifiés contre le code : aucun contredit. Dérive de lignes seulement : `capture_routes.py` `routes()` 197 (pas 187), `workspace_routes.py` 94 (pas 84), splice `server.py:223-224` (pas 218-219). Les docs citent des symboles, pas ces lignes.
- Précision D-SCENE : la validation porte sur les ops de patch `put_object` (`PatchOpKind.PUT_OBJECT`), donc aussi `attach_artifact`/`attach_signal`, pas seulement `upsert_object`/`patch_object`.
- Note ajoutée (scene-model) : pas de bump ⇒ un Core antérieur à S04 refuse un `scene.sqlite3` portant `prefab` (clé inconnue) — même coût que `annotation`/`source_path` ; downgrade non supporté.
- Validation : `pytest tests/unit/test_documented_routes.py tests/unit/test_v2_architecture.py` → 11 passed ; liens relatifs `.md` des 4 docs vérifiés.
