# Task 01 - Pin upstream snapshots and third-party boundaries

## Goal

Rendre reproductible l'integration des projets Jared Rhod et clarifier leur statut de dependances tierces.

## Context

Les projets sont jeunes et evoluent vite. La V1 ne doit jamais dependre implicitement de `main` ni copier du code sans provenance/licence.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- Selectionner/pinner un commit exact pour Barehands et ai-visualizer.
- Etudier Backtalk uniquement pour les morceaux effectivement reutilises.
- Creer manifeste third-party avec repo, commit, licence, mode d'integration.
- Decider submodule/vendor/sibling checkout pour chaque composant.

### Out of Scope
- Pas de modification fonctionnelle des composants.
- Pas de mise a jour automatique.

## Dependencies

Task 00 complete.

## Implementation Steps

1. Resolve exact upstream commits from GitHub.
2. Record checksums/commit IDs.
3. Add `THIRD_PARTY.md` or manifest machine-readable.
4. Add components to `third_party/` using chosen mechanism.
5. Record AGPL implications.
6. Ensure the core build does not silently pull latest main.

## Files Likely Touched

- `third_party/`
- `THIRD_PARTY.md`
- `.gitmodules` or dependency manifest
- `docs/06-upstream-integration-map.md`

## Architecture Constraints

No unpinned network dependency at runtime. Do not mix upstream source into core without explicit provenance.

## Testing Requirements

- Clean checkout can reproduce exact third-party revisions.
- CI/test command verifies expected revision or checksum.
- No CDN dependency is accepted yet; Barehands hardening occurs later.

## Acceptance Criteria

- Exact commits documented.
- Licensing/provenance documented.
- Reproducible third-party checkout works.
- No component tracks `main` implicitly.

## Documentation Updates

Update upstream integration map and third-party manifest.

## Handoff Notes

If legal/licensing constraints forbid source reuse, keep external process boundaries and reimplement only the required protocol under project-owned code.
