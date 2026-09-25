# ISSUE-02 — Deux tests de prompt en retard sur le produit

Découvert en Slice 00 (2026-09-25), hors périmètre.

- `test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` attend `--append-system-prompt == BRAIN_SYSTEM_PROMPT` ; le prompt inclut désormais `BRAIN_SETTINGS_PROMPT` (`claude_local.py:157-171`).
- `test_barehands_tutorial_retired_js.py::test_the_brain_is_told_the_tutorial_tool_is_deprecated_and_opens_calibration` cherche « l'interrupteur est à lui » ; le prompt dit « il est à toi comme à lui » (`claude_local.py:147`).

Le produit a changé volontairement ; les tests sont à mettre à jour.
