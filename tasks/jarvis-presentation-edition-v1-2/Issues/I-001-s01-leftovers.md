# I-001 — Restes de la Slice 01 (QA du 2026-10-27)

- **m1/m2 (à faire dans la Slice 02)** : figer par des tests le refus du hook pour un appel nommé `Task` (`routing_hook.py:648`) et pour les variantes `[coder]` sans profil, `[CODER]`, `[ coder ]`, marqueur dans le prompt seulement, `[éphémère]` en tête. Le code les refuse déjà ; seul le filet de tests manque.
- **m3 (accepté)** : un profil `[code]` sans rôle ou un rôle inconnu passe le hook sans refus ni trace ; le sous-agent reste sans Bash/Write/Edit. Conforme au périmètre (refus des rôles, la barrière reste celle des outils).
- **m4 (accepté, à documenter)** : édition illisible → le hook laisse passer ; Core et le lanceur de la CLI refusent alors de démarrer. Documenter ce choix dans `docs/product-capabilities.md` (Slice 02).
- **Slice 06** : `coder` reste listé en presentation dans l'onglet Sous-agents, sans mention « indisponible ». → **Fait (Slice 06, `95d069a7`)** : `edition_unavailable` dans `GET /api/subagent-roles` (code `role_unavailable_in_edition`, celui du hook) ; ligne, fiche et synthèse disent « Indisponible dans cette édition » ; `full` inchangé. À vérifier par la QA de la Slice 06.
- **Slice 02** : mettre à jour la section « Real traces » de `docs/product-capabilities.md`.
- Coût observé : environ 0,22 $ par premier tour du cerveau en presentation.
