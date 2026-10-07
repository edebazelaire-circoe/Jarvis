"""Mesure de la capacité de la bibliothèque de prefabs pour les scènes du Studio (Slice 01a).

Deux parties, séparées parce qu'elles n'ont pas le même statut :

- **mesuré** : coût réel d'une publication, taille disque par version, durée du
  démarrage à froid (`PrefabService.start`) et du relistage à chaud
  (`search`, qui rescanne) sur une vraie bibliothèque de fichiers, aux bornes
  actuelles (15 ids x 64 versions ; 512 ids x 1 version ; 64 ids x 64) ;
- **modélisé** : versions par scène pour une répétition, avec et sans
  coalescence. Aucune télémétrie de répétition n'existe (le Studio n'est pas
  livré) : les hypothèses sont des paramètres imprimés, pas des mesures.

Usage : `python scripts/measure_prefab_capacity.py [--json]` (dossiers temporaires seulement).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import tempfile
import time
import tracemalloc
from pathlib import Path

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.prefab import MAX_PREFAB_IDS, MAX_VERSIONS_PER_ID
from tests.fakes.prefabs import candidate, install_version

SCENES = 15


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


async def measure_library(ids: int, versions: int) -> dict[str, float]:
    base = Path(tempfile.mkdtemp(prefix="prefab-capacity-"))
    try:
        package, data = base / "package", base / "data"
        package.mkdir()
        data.mkdir()
        # Peuplement direct (un `save` rescanne toute la bibliotheque : quadratique) puis 10 vrais `save` sur la
        # bibliotheque pleine, pour mesurer le cout d'une publication a cette echelle.
        library_root = data / LIBRARY_DIR
        library_root.mkdir()
        for index in range(ids):
            for version in range(1, versions + 1):
                install_version(library_root, f"presentation-studio.scene{index}", version)
        service = PrefabService(FilePrefabLibrary(package, data))
        await service.start()
        save_times: list[float] = []
        for _ in range(10):
            begin = time.perf_counter()
            await service.save(candidate(id="presentation-studio.probe"), actor="user")
            save_times.append(time.perf_counter() - begin)
        size = _tree_bytes(library_root)
        total = ids * versions + 10
        tracemalloc.start()
        cold_service = PrefabService(FilePrefabLibrary(package, data))
        begin = time.perf_counter()
        await cold_service.start()
        cold = time.perf_counter() - begin
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        begin = time.perf_counter()
        await cold_service.search()
        warm = time.perf_counter() - begin
        return {"ids": ids + 1, "versions_per_id": versions, "total_versions": total,
                "save_ms_mean_on_full_library": round(sum(save_times) / len(save_times) * 1000, 1),
                "disk_kib": round(size / 1024), "disk_kib_per_version": round(size / 1024 / total, 1),
                "cold_start_s": round(cold, 2), "cold_peak_mib": round(peak / 1024 / 1024, 1),
                "warm_relist_s": round(warm, 3)}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def edit_stream(rng: random.Random, edits_per_hour: int, burst_mean: float, burst_gap_s: float) -> list[float]:
    """Instants (s) de `edits_per_hour` éditions de source en rafales : une rafale = quelques retouches à `burst_gap_s`."""

    times: list[float] = []
    clock = 0.0
    while len(times) < edits_per_hour:
        clock += rng.uniform(20, 240)  # réflexion entre deux rafales
        for _ in range(max(1, round(rng.gauss(burst_mean, 1.5)))):
            clock += rng.uniform(0.3, burst_gap_s)
            times.append(clock)
    return times[:edits_per_hour]


def coalesced_count(times: list[float], quiet_s: float, max_wait_s: float) -> int:
    """Versions publiées : une par rafale (silence `quiet_s`) ou au plus tard `max_wait_s` après la première édition."""

    published, start, last = 0, None, None
    for instant in times:
        if start is not None and (instant - last > quiet_s or instant - start > max_wait_s):
            published, start = published + 1, None
        if start is None:
            start = instant
        last = instant
    return published + (1 if start is not None else 0)


def model_rehearsal(quiet_s: float = 2.0, max_wait_s: float = 10.0) -> list[dict[str, float]]:
    rows = []
    for label, edits, burst_mean in (("light", 12, 2.0), ("typical", 45, 3.0), ("heavy", 150, 5.0)):
        rng = random.Random(7)
        stream = edit_stream(rng, edits, burst_mean, burst_gap_s=1.5)
        published = coalesced_count(stream, quiet_s, max_wait_s)
        rows.append({"profile": label, "source_edits_per_scene_hour": edits, "versions_without_coalescing": edits,
                     "versions_with_coalescing": published,
                     "hours_to_fill_64_without": round(MAX_VERSIONS_PER_ID / edits, 2),
                     "hours_to_fill_64_with": round(MAX_VERSIONS_PER_ID / published, 2)})
    return rows


def model_ids(variants: int, forks_fraction: float, local_variants_per_scene: int) -> dict[str, float]:
    """Ids pour une présentation : 1 par scène, + 1 par fork de source (variante ou variante locale qui diverge)."""

    forks = SCENES * (variants - 1) * forks_fraction + SCENES * local_variants_per_scene * forks_fraction
    per_presentation = SCENES + forks
    return {"variants": variants, "forks_fraction": forks_fraction, "local_variants_per_scene": local_variants_per_scene,
            "ids_per_presentation": round(per_presentation, 1),
            "presentations_to_fill_512": round(MAX_PREFAB_IDS / per_presentation, 1)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    measured = [asyncio.run(measure_library(ids, versions)) for ids, versions in
                ((SCENES, MAX_VERSIONS_PER_ID), (MAX_PREFAB_IDS - 1, 1), (96, 16))]
    report = {"measured": measured, "rehearsal_model": model_rehearsal(),
              "id_model": [model_ids(v, f, l) for v, f, l in ((1, 0, 0), (3, 0.3, 1), (5, 1.0, 2), (5, 1.0, 0))]}
    if args.json:
        print(json.dumps(report, indent=2))
        return
    for section, rows in report.items():
        print(f"== {section}")
        for row in rows:
            print("  ", row)


if __name__ == "__main__":
    main()
