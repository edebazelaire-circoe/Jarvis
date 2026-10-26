# I-004 — Slice 05 leftovers (QA 2026-10-26)

Details and evidence: `slices/05-connectors-secrets-and-iguard-hook/NOTES.md` (I-S05-1 to I-S05-6).

1. I-S05-1: the `GOOGLE_API_KEY` / `GEMINI_API_KEY` binding taken over from `.env` depends on line order.
2. I-S05-2: `jarvis/config.py:152` (V1 path) reads `OPENAI_API_KEY` only from the environment, not from the sealed store.
3. I-S05-3: code older than Slice 05 cannot read sealed entries; recovery goes through `python -m jarvis secrets-restore`.
4. I-S05-5: other relays may still render a whitelist refusal as `core_unreachable` (only `board_routes` fixed).
5. **Slices 07/10**: I-S05-6, a silent model switch by the CLI (`model_refusal_fallback`, session scope) that JARVIS does not surface.
6. **Phase B / HV-07-01**: Circuit Toolbox live catalogue and annotations. Fill `ConnectorSpec.tool_side_effects` with one line per tool, with evidence (only `infomaniak.calendar.list_events` = read is attested). Unannotated mail/agenda tools are refused in `presentation` until then.
7. Model-facing messages (framing notice, gateway refusal) use "tu", following the convention of neighbouring messages.
8. A Google token without a `scopes` field (old format) is considered covering.
