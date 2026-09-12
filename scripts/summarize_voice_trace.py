#!/usr/bin/env python3
"""Résumé Solo Owner de `runtime/trace.jsonl` (recette matérielle, tâche 14).

    python scripts/summarize_voice_trace.py runtime/trace.jsonl
    python scripts/summarize_voice_trace.py runtime/trace.jsonl --json --since 2026-09-12

Scalaires seulement : délais de confirmation, latence d'arrêt local, rejeux
tronqués, entrées écartées, refus, état de travail partagé. Jamais de
transcription ni d'empreinte vocale. Procédure : docs/HARDWARE_ACCEPTANCE.md.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.runtime.trace_summary import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
