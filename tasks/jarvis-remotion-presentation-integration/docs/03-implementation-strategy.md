# 03 - Implementation strategy

## Phase A - Wait + independent refresh

Do not edit the active branch. Once original implementer finishes and user/PM supplies stable head: inspect code/tests/docs blind, reconcile open original Slices, update 06 branch compliance matrix, check main merge-base and any read-only PR review. Capture exact SHA and baseline failures. Resolve Task Types, licensing and prerequisites before coding. If branch remains active, mark `HUMAN_DECISION_REQUIRED`/blocked as appropriate.

## Phase B - Lock minimal contracts

Lock PresentationEngine semantic contract, compatibility classifications and user-only experimental selector; local capability/plugin lifecycle vs remote MCP; artifact source and derived identities; safe resource resolutions. Make no source conversion until these are accepted. Use a proof-of-concept on an isolated sample with real Node and browser to validate Player and Studio.

## Phase C - Remotion infrastructure

Install once under a Jarvis-managed versioned runtime/cache. Create per-presentation source folder beneath the canonical data root (but no per-project dependency tree); manage one instance of Studio/bundler with restart/recovery and exclusive access to the allowed root; isolate generated TSX from Jarvis privileges. Expose health and repair. On failure report typed status; do not change engine.

## Phase D - Wire original Presentation domain

Bridge Score/DA/Scene/controls/variant to Remotion compositions and Player; implement variable changes, safe code edits, scene refresh, per-scene state restoration and optional Studio. Preserve existing HTML Sidecar/Slidecar via explicit experiment flag and regression tests.

## Phase E - Artifact UX and reuse

Add source artifact discoverability and Board links, live asset resolution, self-contained frozen export and derivative relations; add marketplace semantic types, stack, params, provenance, templates and explicit promotion/version upgrade in test variants; integrate agent voice tools and Tool Brain routing.

## Phase F - Verify and release

Unit/integration/replay, Windows/local installation and process restart, real browser Studio and Player, concrete voice edit traces, cue/locked timing, export, Board-switch and deleted/changed asset behavior, upgrade/revert, kill/recover, and security review. QA plus focused Human validation. Keep the original branch intact and do not force merges without an explicit execution decision.
