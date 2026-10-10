# Issue 05 - A first save by the new build keeps no backup of the variant it rewrites (found by Slice 22, 2026-10-10)

Measured by `scripts/remotion_migration_probe.py` (`evidence/migration.json`, `first_save_by_new_build`, `saved_document_backups`). Not a regression of a Slice: it
is how the Studio file store has always saved a variant (Slice 02 of this task only added the manifest `.bak`). Nonblocking, but it limits the rollback.

On the first save of a legacy presentation the new build rewrites `presentation.json` as schema 3 and keeps the old bytes as `presentation.json.v2.bak`; it
rewrites the saved **variant** in place at schema 5 (variants gained `at_ms` in Slice 12) and keeps **no** copy of the previous bytes. The build before the
task refuses both files (`presentation_studio_unsupported_schema_version`), so after any save the only way back is a copy of `presentations/` taken before.

Possible follow-up: write `variants/<id>.json.v<N>.bak` on the first rewrite at a new schema version, the way `presentation.json` does, and sweep it with the
other temporaries rules; or document the pre-use copy as a requirement (done in `docs/remotion-integration-release.md`, runbook step 1).

Also noted, not a defect: a database holding `presentation_snapshot` / `presentation_video` / `presentation_still` / `presentation_pdf` rows cannot be queried by
the build before the task (`kind is not a ArtifactKind`); the closed Artifact kind set is the documented reason (`docs/artifacts.md`).
