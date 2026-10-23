# LOG

## 2026-10-23 - Slice 00 (agent 0)

- Handoff récupéré du Drive `to-do` (dossier `1_HQwjp8KNxpB52xxtU4e4-W8S9mk7O2U`) et déballé ici. Pas de
  `docs/workflows/AGENT_TASK_LIFECYCLE.md` dans le dépôt : repli sur les ids Drive et la base `main` de la
  mémoire projet. Déplacement Drive to-do → current à faire par le Human (le MCP ne déplace pas).
- Branche `task/jarvis-architecture-agents-settings-editor` depuis `main` @ `ad1e7f4d`, worktree `../arch`.
- Audit aveugle de `main` (deux explorations en lecture seule) : `docs/10-slice00-audit.md`.
- Readiness : **READY**, corrections C1-C10. L'ancienne S04 de `jarvis-settings-ui-reorganization` est déjà
  livrée (`b0b53b51`) : rien à bloquer, la Slice 07 la remplace.
- Task Type : `waived-by-agent-0` (précédents orchestration et settings-ui-reorganization).
- Dispatch en deux vagues (≤ 3 agents) : A = 01, 03, 04 ; B = 02, 05, 06.

## 2026-10-23 - Slice 07 (agent d'implémentation)

- Worktree `C:\Projects\jarvis\arch-s07`, branche `task/jarvis-architecture-agents-settings-editor-s07` (Slices 01 à 06
  fusionnées ; `main` n'a pas bougé depuis `ad1e7f4d`, rien à fusionner).
- Montage serveur (`ControlCenter._install_architecture_services`), règle unique de bascule de Voice
  (`voice_switch.plan_voice_switch`), fournisseurs réels de catalogue et de candidats, crochet `after_settings_write`.
- Page à deux onglets (sections `architecture`, `subagents`) ; `main_agent` / `subagent_models` retirés en alias ;
  technique du CLI, mode Auto / Dupliqué et inventaire dans Avancé › Runtime & CLI.
- I-001 : sort de chaque point consigné dans `Issues/I-001-polish-for-s07.md` (S01-1, S01-3, S01-4 reportés en S08).
- Preuves en bac à sable (ports 27653/27654) : `slices/07-settings-integration-and-legacy-migration/EVIDENCE.md`.
- Note de remplacement écrite dans `tasks/jarvis-settings-ui-reorganization/LOG.md`.
