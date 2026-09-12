#!/usr/bin/env python3
"""Banc d'essai des vérificateurs de locuteur (Solo Owner, tâche 09).

    python scripts/benchmark_speaker_verification.py generate-synthetic
    python scripts/benchmark_speaker_verification.py models [--download KEY|all]
    python scripts/benchmark_speaker_verification.py run MANIFEST [--sherpa-model downloaded] …

Mode d'emploi et lecture des résultats : docs/SPEAKER_BENCHMARK.md.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.runtime.speaker_benchmark import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
