"""Mesure du coût d'inférence openWakeWord par trame de 80 ms, et de l'effet du rééchantillonnage 24 -> 16 kHz.

Outil de la Slice 01 de `jarvis-wake-word` (décision D7 : `engine.process` sur la
boucle asyncio ou dans un exécuteur). À lancer avec le Python d'un environnement
qui a l'extra `wakeword` (jamais dans l'environnement du JARVIS vivant) :

    python scripts/measure_wakeword_inference.py --install
    python scripts/measure_wakeword_inference.py --reference-wav24k clip.wav

`--install` télécharge les trois modèles du catalogue (action explicite,
SHA-256 vérifié) ; sans lui, le script exige qu'ils soient déjà installés.
Le clip de référence est un enregistrement mono 16 bits à 24 kHz ; il n'est
jamais committé. Rien n'est persisté : le résultat sort en JSON sur stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import wave
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FRAME_SAMPLES = 1280  # 80 ms à 16 kHz
SAMPLE_RATE = 16_000


def load_engine(paths: dict[str, Path]):
    import openwakeword  # noqa: F401 - import paresseux : seul ce script et le moteur de la Slice 02 le font
    from openwakeword.model import Model

    return Model(
        wakeword_models=[str(paths["hey_jarvis"])],
        inference_framework="onnx",
        melspec_model_path=str(paths["melspectrogram"]),
        embedding_model_path=str(paths["embedding"]),
    )


def read_pcm16(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise SystemExit("le clip doit être mono 16 bits")
        return handle.readframes(handle.getnframes()), handle.getframerate()


def frames_of(pcm: bytes):
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16)
    padded = np.concatenate([np.zeros(SAMPLE_RATE, np.int16), samples, np.zeros(SAMPLE_RATE, np.int16)])
    usable = len(padded) - len(padded) % FRAME_SAMPLES
    return [padded[i : i + FRAME_SAMPLES] for i in range(0, usable, FRAME_SAMPLES)]


def peak_score(engine, frames) -> float:
    engine.reset()
    best = 0.0
    for frame in frames:
        scores = engine.predict(frame)
        best = max(best, float(max(scores.values())))
    return best


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def measure_latency(engine, frames, repeat: int) -> dict[str, float]:
    for frame in frames[:50]:  # chauffe : première passes plus lentes (allocation des tampons ONNX)
        engine.predict(frame)
    durations_ms: list[float] = []
    for _ in range(repeat):
        for frame in frames:
            start = time.perf_counter_ns()
            engine.predict(frame)
            durations_ms.append((time.perf_counter_ns() - start) / 1e6)
    return {
        "frames": len(durations_ms),
        "mean_ms": round(statistics.fmean(durations_ms), 3),
        "p50_ms": round(percentile(durations_ms, 0.50), 3),
        "p95_ms": round(percentile(durations_ms, 0.95), 3),
        "p99_ms": round(percentile(durations_ms, 0.99), 3),
        "max_ms": round(max(durations_ms), 3),
        "budget_ms": 80.0,
        "p99_share_of_budget": round(percentile(durations_ms, 0.99) / 80.0, 4),
    }


def resampling_effect(engine, pcm24: bytes):
    """Pic de score sur le même clip : 16 kHz filtré (référence) contre `StreamingPcm16Resampler`."""

    import numpy as np
    from scipy.signal import resample_poly

    from jarvis.audio.resampling import StreamingPcm16Resampler

    samples = np.frombuffer(pcm24, dtype=np.int16)
    reference = np.clip(resample_poly(samples.astype(np.float64), 2, 3), -32768, 32767).astype(np.int16)
    resampler = StreamingPcm16Resampler(source_rate=24_000, target_rate=SAMPLE_RATE)
    block = 480  # 20 ms à 24 kHz : le découpage du hub
    chunks = [resampler.process(pcm24[i : i + block * 2]) for i in range(0, len(pcm24), block * 2)]
    linear = np.frombuffer(b"".join(chunks), dtype=np.int16)
    reference_peak = peak_score(engine, frames_of(reference.tobytes()))
    linear_peak = peak_score(engine, frames_of(linear.tobytes()))
    effect = {
        "reference_filtered_peak": round(reference_peak, 4),
        "streaming_linear_peak": round(linear_peak, 4),
        "delta": round(linear_peak - reference_peak, 4),
    }
    return effect, frames_of(reference.tobytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--install", action="store_true", help="télécharger les modèles manquants (réseau, SHA-256 vérifié)")
    parser.add_argument("--model-dir", type=Path, help="dossier des modèles (défaut : runtime/wake-word/models)")
    parser.add_argument("--frames", type=int, default=1500, help="trames de bruit mesurées par passe")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--reference-wav24k", type=Path, action="append", default=[], help="clip mono 16 bits 24 kHz")
    args = parser.parse_args(argv)

    import numpy as np

    from jarvis.adapters import wakeword_model_catalog as catalog

    paths = catalog.ensure_models(args.model_dir) if args.install else catalog.verified_paths(args.model_dir)
    engine = load_engine(paths)

    rng = np.random.default_rng(1234)
    noise = [rng.normal(0, 1500, FRAME_SAMPLES).astype(np.int16) for _ in range(args.frames)]
    result: dict[str, object] = {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "cpu_count": os.cpu_count(),
        "versions": {
            name: metadata.version(name) for name in ("openwakeword", "onnxruntime", "numpy", "scipy", "scikit-learn")
        },
        "frame": {"samples": FRAME_SAMPLES, "sample_rate": SAMPLE_RATE, "duration_ms": 80},
        "noise_latency": measure_latency(engine, noise, args.repeat),
        "clips": {},
    }
    for clip in args.reference_wav24k:
        pcm, rate = read_pcm16(clip)
        if rate != 24_000:
            raise SystemExit(f"{clip.name} : 24 kHz attendu, {rate} Hz trouvé")
        effect, speech_frames = resampling_effect(engine, pcm)
        entry = {
            "latency_on_speech_frames": measure_latency(engine, speech_frames, max(1, args.repeat * 20)),
            "resampling": effect,
        }
        result["clips"][clip.stem] = entry  # type: ignore[index]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
