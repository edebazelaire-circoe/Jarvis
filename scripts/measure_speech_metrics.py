#!/usr/bin/env python3
"""Métriques de présentation de la parole (Slice 06), lues dans le journal Core.

    python scripts/measure_speech_metrics.py --db data/state/jarvis.sqlite3 --snapshot --baseline
    python scripts/measure_speech_metrics.py --db data/state/jarvis.sqlite3 --snapshot \
        --window apres=2026-10-01T09:00Z..2026-10-01T10:00Z --baseline --trace runtime/trace.jsonl

Lecture seule. Définitions : docs/OPERATIONS.md « Speech presentation metrics » ;
implémentation : jarvis/testlab/speech_metrics.py.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.testlab.speech_metrics import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
