"""Jeux d'essai synthétiques redistribuables pour le banc d'essai du locuteur (tâche 09).

Tout est généré à la demande sur le poste, jamais versionné : voix de synthèse
Windows (OneCore via WinRT, plus les voix SAPI que OneCore n'a pas), bruit rose,
clics de clavier, chocs sur le bureau, réverbération simple. Le résultat est un
dossier de WAV 16 kHz et un manifeste prêt pour
`benchmark_speaker_verification.py run`.

Ces voix ne prouvent rien pour les seuils de production : deux voix de synthèse
se séparent bien plus facilement que deux personnes réelles. Elles servent à
vérifier le banc, à comparer grossièrement les moteurs et à repérer une
régression ; la tâche 14 refait la mesure sur la voix du propriétaire.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable, Sequence
import wave

import numpy as np

from jarvis.audio.owner_verifier import resample
from jarvis.audio.speaker_benchmark import BenchmarkError

RATE = 16_000
#: Niveau nominal d'une voix (RMS des trames voisées), en dB pleine échelle.
SPEECH_RMS_DB = -20.0

ENROLL_TEXT = (
    "Bonjour, je m'appelle comme tous les matins devant mon ordinateur. Aujourd'hui je voudrais faire le point "
    "sur les dossiers en cours, relire les messages importants et préparer la réunion de cet après-midi avec "
    "l'équipe. Il faudra aussi vérifier le budget du trimestre, appeler le fournisseur pour la livraison du "
    "matériel et réserver une salle pour jeudi. Pendant ce temps, le soleil entre par la fenêtre, quelqu'un "
    "prépare du café dans la cuisine et le téléphone sonne de temps en temps. Je parle d'une voix naturelle, "
    "parfois un peu plus vite, parfois plus lentement, comme dans une vraie journée de travail."
)
TEST_SENTENCES = (
    "Peux-tu me rappeler d'appeler le garage demain matin avant dix heures ?",
    "Ouvre le dernier rapport financier et résume-moi les trois points principaux.",
    "Est-ce que la livraison du bureau est bien arrivée, ou faut-il relancer le transporteur ?",
    "Ajoute une réunion avec Claire vendredi à quinze heures, dans la petite salle.",
    "Je voudrais savoir combien de temps il reste avant la fin de la compilation.",
    "Arrête la lecture, s'il te plaît, et note plutôt ce que je vais te dicter.",
    "Quelle est la météo prévue pour ce week-end à Lyon et à Marseille ?",
    "Envoie un message à l'équipe pour dire que la démonstration est repoussée à lundi.",
)
#: Débit de parole OneCore (1 = normal) par phrase : un peu de variabilité intra-locuteur.
_RATES = (1.0, 0.9, 1.15, 1.0, 1.05, 0.95, 1.1, 1.0)

_TTS_SCRIPT = r"""
param([string]$Mode, [string]$JobsPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$onecore = @()
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
  $null = [Windows.Storage.Streams.DataReader,Windows.Storage.Streams,ContentType=WindowsRuntime]
  $onecore = @([Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices)
} catch { $onecore = @() }
$sapi = @((New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo })
if ($Mode -eq 'list') {
  $out = @()
  foreach ($v in $onecore) { $out += [pscustomobject]@{ engine = 'onecore'; name = $v.DisplayName; lang = $v.Language; gender = [string]$v.Gender } }
  foreach ($v in $sapi) { $out += [pscustomobject]@{ engine = 'sapi'; name = $v.Name; lang = $v.Culture.Name; gender = [string]$v.Gender } }
  ConvertTo-Json -InputObject @($out) -Compress
  exit 0
}
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$jobs = Get-Content -Raw -Encoding UTF8 $JobsPath | ConvertFrom-Json
foreach ($job in $jobs) {
  if ($job.engine -eq 'onecore') {
    $synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
    $synth.Voice = @($onecore | Where-Object { $_.DisplayName -eq $job.voice })[0]
    $synth.Options.SpeakingRate = [double]$job.rate
    $stream = Await ($synth.SynthesizeTextToStreamAsync($job.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $size = [uint32]$stream.Size
    $null = Await ($reader.LoadAsync($size)) ([uint32])
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes($job.out, $bytes)
    $reader.Dispose(); $stream.Dispose(); $synth.Dispose()
  } else {
    $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.SelectVoice($job.voice); $s.Rate = [int][math]::Round(([double]$job.rate - 1.0) * 10)
    $s.SetOutputToWaveFile($job.out, $fmt); $s.Speak($job.text); $s.Dispose()
  }
}
"""


class FixtureError(BenchmarkError):
    """Synthèse vocale indisponible ou insuffisante sur ce poste."""


@dataclass(frozen=True, slots=True)
class Voice:
    """Une voix de synthèse installée, identifiée par un nom court (le « locuteur »)."""

    key: str
    engine: str
    name: str
    lang: str
    gender: str

    def payload(self) -> dict[str, str]:
        return {"key": self.key, "engine": self.engine, "name": self.name, "lang": self.lang, "gender": self.gender}


def _voice_key(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w and w.lower() not in {"microsoft", "desktop"}]
    return (words[0] if words else name).lower()


def select_voices(listed: Sequence[dict[str, str]]) -> list[Voice]:
    """Une voix par locuteur : OneCore d'abord ; une voix SAPI seulement si OneCore n'a pas ce locuteur.

    « Microsoft Hortense Desktop » (SAPI) et « Microsoft Hortense » (OneCore)
    sont le même locuteur : les compter deux fois fausserait les imposteurs.
    """

    voices: dict[str, Voice] = {}
    for engine in ("onecore", "sapi"):
        for item in listed:
            if item.get("engine") != engine:
                continue
            key = _voice_key(str(item.get("name", "")))
            if key and key not in voices:
                voices[key] = Voice(key, engine, str(item["name"]), str(item.get("lang", "")), str(item.get("gender", "")))
    return list(voices.values())


def _powershell(script: Path, *args: str, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def list_voices(workdir: Path) -> list[dict[str, str]]:
    """Voix installées (OneCore et SAPI) ; `FixtureError` hors Windows ou sans synthèse."""

    if sys.platform != "win32":
        raise FixtureError("tts_unavailable", "La synthèse vocale des jeux d'essai utilise Windows (OneCore / SAPI).")
    script = Path(workdir) / "tts.ps1"
    script.write_text(_TTS_SCRIPT, encoding="utf-8-sig")
    try:
        completed = _powershell(script, "list", "", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FixtureError("tts_unavailable", f"PowerShell indisponible : {exc}") from None
    if completed.returncode != 0:
        raise FixtureError("tts_unavailable", f"Liste des voix impossible : {completed.stderr.strip()[-400:]}")
    try:
        listed = json.loads(completed.stdout.strip() or "[]")
    except ValueError:
        raise FixtureError("tts_unavailable", f"Réponse illisible : {completed.stdout[:200]!r}") from None
    return listed if isinstance(listed, list) else [listed]


def synthesize(jobs: Sequence[dict[str, object]], workdir: Path, *, timeout: float = 900.0) -> None:
    script = Path(workdir) / "tts.ps1"
    script.write_text(_TTS_SCRIPT, encoding="utf-8-sig")
    jobs_file = Path(workdir) / "jobs.json"
    jobs_file.write_text(json.dumps(list(jobs), ensure_ascii=False), encoding="utf-8")
    completed = _powershell(script, "synth", str(jobs_file), timeout=timeout)
    missing = [str(job["out"]) for job in jobs if not Path(str(job["out"])).is_file()]
    if completed.returncode != 0 or missing:
        raise FixtureError("tts_failed", f"Synthèse incomplète ({len(missing)} fichier(s)) : {completed.stderr.strip()[-400:]}")


# -- signaux ------------------------------------------------------------------------------


def _read(path: Path) -> np.ndarray:
    from jarvis.runtime.owner_voice import read_wav

    samples, rate = read_wav(path)
    return resample(samples, rate, RATE)


def write_wav(path: Path, samples: np.ndarray, rate: int = RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def _samples(ms: float) -> int:
    return int(round(RATE * ms / 1000.0))


def _db(value: float) -> float:
    return float(10.0 ** (value / 20.0))


def prepare_utterance(samples: np.ndarray, *, rms_db: float = SPEECH_RMS_DB, hop_ms: int = 100) -> np.ndarray:
    """Retirer les silences de bord, régler le niveau de parole, arrondir à la fenêtre de 100 ms."""

    frame = _samples(10)
    count = samples.size // frame
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: count * frame].reshape(count, frame).astype(np.float64)
    levels = 10.0 * np.log10(np.mean(frames**2, axis=1) + 1e-12)
    voiced = np.flatnonzero(levels > max(-50.0, float(levels.max()) - 40.0))
    if voiced.size == 0:
        return np.zeros(0, dtype=np.float32)
    trimmed = samples[voiced[0] * frame : (voiced[-1] + 1) * frame].astype(np.float64)
    rms = float(np.sqrt(np.mean(frames[voiced] ** 2)))
    trimmed *= _db(rms_db) / max(rms, 1e-9)
    peak = float(np.max(np.abs(trimmed)))
    if peak > 0.95:
        trimmed *= 0.95 / peak
    hop = _samples(hop_ms)
    padded = np.zeros(-(-trimmed.size // hop) * hop, dtype=np.float32)
    padded[: trimmed.size] = trimmed
    return padded


def pink_noise(rng: np.random.Generator, ms: float, rms_db: float) -> np.ndarray:
    count = _samples(ms)
    spectrum = np.fft.rfft(rng.standard_normal(count))
    freqs = np.fft.rfftfreq(count, 1.0 / RATE)
    spectrum[1:] /= np.sqrt(freqs[1:])
    spectrum[0] = 0.0
    noise = np.fft.irfft(spectrum, n=count)
    noise *= _db(rms_db) / max(float(np.sqrt(np.mean(noise**2))), 1e-12)
    return noise.astype(np.float32)


def keyboard_click(rng: np.random.Generator) -> np.ndarray:
    """Frappe de clavier : salve de bruit très brève, amortie, dominée par les aigus."""

    count = _samples(rng.uniform(8, 20))
    t = np.arange(count) / RATE
    burst = rng.standard_normal(count) * np.exp(-t / rng.uniform(0.002, 0.004))
    burst = np.diff(burst, prepend=0.0)
    return (burst * rng.uniform(0.2, 0.5) / max(float(np.max(np.abs(burst))), 1e-9)).astype(np.float32)


def desk_impact(rng: np.random.Generator) -> np.ndarray:
    """Choc sur le bureau : graves amortis plus un peu de bruit."""

    count = _samples(rng.uniform(60, 120))
    t = np.arange(count) / RATE
    tone = sum(np.sin(2 * np.pi * rng.uniform(70, 220) * t + rng.uniform(0, np.pi)) for _ in range(3))
    thump = (tone + 0.5 * rng.standard_normal(count)) * np.exp(-t / rng.uniform(0.015, 0.035))
    return (thump * rng.uniform(0.4, 0.8) / max(float(np.max(np.abs(thump))), 1e-9)).astype(np.float32)


def transients(rng: np.random.Generator, ms: float) -> np.ndarray:
    """Rafales de frappe (90 à 250 ms entre touches) entrecoupées de chocs et de pauses."""

    out = np.zeros(_samples(ms), dtype=np.float32)
    cursor = rng.uniform(100, 400)
    while cursor < ms - 150:
        burst_end = min(ms - 150, cursor + rng.uniform(1200, 3000))
        while cursor < burst_end:
            click = keyboard_click(rng)
            start = _samples(cursor)
            out[start : start + click.size] += click[: max(0, out.size - start)]
            cursor += rng.uniform(90, 250)
        if rng.uniform() < 0.7 and cursor < ms - 200:
            hit = desk_impact(rng)
            start = _samples(cursor)
            out[start : start + hit.size] += hit[: max(0, out.size - start)]
        cursor += rng.uniform(400, 1200)
    return out


def reverberate(rng: np.random.Generator, samples: np.ndarray, *, rt60_s: float = 0.35) -> np.ndarray:
    """Réverbération synthétique (bruit amorti) : un micro « loin » de la bouche."""

    count = _samples(rt60_s * 1000)
    t = np.arange(count) / RATE
    ir = rng.standard_normal(count) * np.exp(-6.9 * t / rt60_s) * 0.25
    ir[0] = 1.0
    size = samples.size + count - 1
    wet = np.fft.irfft(np.fft.rfft(samples, size) * np.fft.rfft(ir, size), size)[: samples.size]
    return (wet * np.sqrt(np.mean(samples**2)) / max(float(np.sqrt(np.mean(wet**2))), 1e-12)).astype(np.float32)


class _Mix:
    """Piste de scénario : on y pose des sons à des instants donnés, étiquetés ou non."""

    def __init__(self) -> None:
        self.audio = np.zeros(0, dtype=np.float32)
        self.intervals: list[dict[str, object]] = []

    @property
    def end_ms(self) -> int:
        return int(self.audio.size * 1000 // RATE)

    def place(self, signal: np.ndarray, start_ms: int, label: str | None = None, speaker: str | None = None) -> int:
        start = _samples(start_ms)
        end = start + signal.size
        if end > self.audio.size:
            self.audio = np.concatenate([self.audio, np.zeros(end - self.audio.size, dtype=np.float32)])
        self.audio[start:end] += signal
        end_ms = int(round(end * 1000 / RATE))
        if label:
            self.intervals.append({"start_ms": int(start_ms), "end_ms": end_ms, "label": label, **({"speaker": speaker} if speaker else {})})
        return end_ms

    def pad(self, ms: int) -> None:
        self.audio = np.concatenate([self.audio, np.zeros(_samples(ms), dtype=np.float32)])


# -- scénarios -----------------------------------------------------------------------------

#: Scénarios générés par propriétaire, avec leur lien au jeu recommandé (docs 04 du handoff).
SCENARIOS: dict[str, str] = {
    "owner_alone": "docs04#1 quiet owner, two sentences separated by silence",
    "owner_quiet": "level: owner 12 dB quieter",
    "owner_far": "distance: owner 18 dB quieter + synthetic room reverberation",
    "non_owner_conversation": "docs04#4 several non-owners converse, no owner",
    "non_owner_far": "distance: one non-owner 12 dB quieter + reverberation, no owner",
    "non_owner_then_owner": "docs04#5 owner answers right after a non-owner, no silence",
    "owner_then_non_owner": "transition: a non-owner speaks right after the owner, no silence",
    "overlap_1s": "docs04#6 owner starts 1 s before the end of a non-owner sentence (mixed)",
    "overlap_2s": "docs04#6 owner starts 2 s before the end of a non-owner sentence (mixed)",
    "overlap_3s": "docs04#6 owner starts 3 s before the end of a non-owner sentence (mixed)",
    "keyboard_desk": "docs04#7 keyboard bursts and desk impacts only",
    "owner_with_keyboard": "docs04#7 typing before and during owner speech",
    "low_noise": "low-level pink noise (-50 dBFS) under noise-only, owner and non-owner parts",
}


def build_scenario(kind: str, owner: str, impostors: Sequence[str], utter: Callable[[str, int], np.ndarray], rng: np.random.Generator) -> _Mix:
    """Construire un scénario ; `utter(voix, phrase)` rend une phrase préparée."""

    mix = _Mix()
    imp = [impostors[i % len(impostors)] for i in range(4)]
    if kind in {"owner_alone", "owner_quiet", "owner_far"}:
        gain = {"owner_alone": 0.0, "owner_quiet": -12.0, "owner_far": -18.0}[kind]
        first, second = {"owner_alone": (0, 1), "owner_quiet": (2, 3), "owner_far": (4, 6)}[kind]
        cursor = 1000
        for sentence in (first, second):
            speech = utter(owner, sentence) * _db(gain)
            if kind == "owner_far":
                speech = reverberate(rng, speech)
            cursor = mix.place(speech, cursor, "owner", owner) + 2000
        mix.pad(1000)
    elif kind == "non_owner_conversation":
        cursor = 500
        for index, (speaker, sentence) in enumerate(((imp[0], 0), (imp[1], 1), (imp[0], 2), (imp[2], 3))):
            cursor = mix.place(utter(speaker, sentence), cursor, "non_owner", speaker) + (300 if index % 2 == 0 else 200)
        mix.pad(700)
    elif kind == "non_owner_far":
        speech = reverberate(rng, np.concatenate([utter(imp[3], 3), utter(imp[3], 4)]) * _db(-12.0))
        mix.place(speech, 500, "non_owner", imp[3])
        mix.pad(1000)
    elif kind == "non_owner_then_owner":
        end = mix.place(utter(imp[1], 5), 500, "non_owner", imp[1])
        mix.place(utter(owner, 6), end, "owner", owner)
        mix.pad(1000)
    elif kind == "owner_then_non_owner":
        end = mix.place(utter(owner, 7), 500, "owner", owner)
        mix.place(utter(imp[2], 6), end, "non_owner", imp[2])
        mix.pad(1000)
    elif kind.startswith("overlap_"):
        overlap_ms = int(kind.split("_")[1].rstrip("s")) * 1000
        speaker = imp[int(overlap_ms / 1000) % 4]
        other = np.concatenate([utter(speaker, 0), utter(speaker, 1)])
        other_end = mix.place(other, 500, "non_owner", speaker)
        mine = np.concatenate([utter(owner, 2), utter(owner, 3)])
        mix.place(mine, other_end - overlap_ms, "owner", owner)
        mix.pad(1000)
    elif kind == "keyboard_desk":
        floor = pink_noise(rng, 10_000, -62.0)
        mix.place(floor + transients(rng, 10_000), 0, "noise")
    elif kind == "owner_with_keyboard":
        speech = utter(owner, 4)
        typing_ms = 3000
        mix.place(transients(rng, typing_ms), 0, "noise")
        speech_start = typing_ms + 1500
        end = mix.place(speech, speech_start, "owner", owner)
        mix.place(transients(rng, end - speech_start), speech_start)
        mix.pad(1000)
    elif kind == "low_noise":
        end = mix.place(utter(owner, 5), 3000, "owner", owner)
        end = mix.place(utter(imp[0], 7), end + 1500, "non_owner", imp[0])
        mix.pad(1000)
        # Bruit sous tout le fichier ; seule la partie sans parole est étiquetée « noise ».
        mix.place(pink_noise(rng, mix.end_ms, -50.0), 0)
        mix.intervals.append({"start_ms": 0, "end_ms": 3000, "label": "noise"})
    else:
        raise ValueError(f"unknown scenario kind {kind!r}")
    return mix


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tts_name(voice: Voice, text_id: str, text: str, rate: float) -> str:
    """Nom du fichier de synthèse : le texte, le débit et la voix y laissent leur empreinte (cache sûr)."""

    digest = hashlib.sha256(f"{voice.engine}|{voice.name}|{rate}|{text}".encode("utf-8")).hexdigest()[:8]
    return f"{voice.key}-{text_id}-{digest}.wav"


def generate_synthetic(
    out_dir: Path,
    *,
    owners: int = 3,
    seed: int = 20260911,
    max_voices: int | None = None,
    voice_keys: Sequence[str] | None = None,
    only: Sequence[str] | None = None,
    engines: Sequence[dict[str, object]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Synthétiser les voix, assembler les scénarios et écrire `manifest.json` ; rend son chemin.

    Propriétaires : d'abord les voix françaises (le propriétaire parle
    français), à tour de rôle ; tous les autres locuteurs sont ses imposteurs.
    """

    say = progress or (lambda message: None)
    out_dir = Path(out_dir)
    kinds = [kind for kind in SCENARIOS if only is None or kind in set(only)]
    if not kinds:
        raise FixtureError("fixture_invalid", f"Aucun scénario connu dans {list(only or [])} ({', '.join(SCENARIOS)}).")
    with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as tmp:
        voices = select_voices(list_voices(Path(tmp)))
        if voice_keys:
            by_key = {v.key: v for v in voices}
            absent = [key for key in voice_keys if key not in by_key]
            if absent:
                raise FixtureError("tts_voice_missing", f"Voix absente(s) : {absent} (installées : {sorted(by_key)}).")
            voices = [by_key[key] for key in voice_keys]
        if max_voices is not None:
            french = [v for v in voices if v.lang.lower().startswith("fr")]
            voices = (french + [v for v in voices if v not in french])[: max(2, int(max_voices))]
        if len(voices) < 2:
            raise FixtureError("tts_not_enough_voices", f"Au moins deux voix de synthèse sont nécessaires ({len(voices)} trouvée(s)).")
        ranked = sorted(voices, key=lambda v: (not v.lang.lower().startswith("fr"), v.key))
        owner_voices = ranked[: max(1, min(int(owners), len(voices) - 1))]
        tts_dir = out_dir / "tts"
        tts_dir.mkdir(parents=True, exist_ok=True)
        jobs: list[dict[str, object]] = []
        for voice in voices:
            texts = [(f"s{index}", sentence, _RATES[index]) for index, sentence in enumerate(TEST_SENTENCES)]
            if voice in owner_voices:
                texts.append(("enroll", ENROLL_TEXT, 1.0))
            for text_id, text, rate in texts:
                target = tts_dir / _tts_name(voice, text_id, text, rate)
                if not target.is_file():
                    jobs.append({"engine": voice.engine, "voice": voice.name, "text": text, "rate": rate, "out": str(target)})
        if jobs:
            say(f"Synthèse de {len(jobs)} phrase(s) avec {len(voices)} voix…")
            synthesize(jobs, Path(tmp))
    cache: dict[tuple[str, int], np.ndarray] = {}
    by_key = {voice.key: voice for voice in voices}

    def utter(speaker: str, sentence: int) -> np.ndarray:
        key = (speaker, sentence)
        if key not in cache:
            name = _tts_name(by_key[speaker], f"s{sentence}", TEST_SENTENCES[sentence], _RATES[sentence])
            cache[key] = prepare_utterance(_read(tts_dir / name))
        return cache[key]

    scenarios: list[dict[str, object]] = []
    for owner_index, owner in enumerate(owner_voices):
        impostors = [v.key for v in voices if v.key != owner.key]
        rotated = impostors[owner_index % len(impostors) :] + impostors[: owner_index % len(impostors)]
        for kind_index, kind in enumerate(kinds):
            rng = np.random.default_rng(seed + 1000 * owner_index + kind_index)
            mix = build_scenario(kind, owner.key, rotated, utter, rng)
            path = out_dir / "scenarios" / owner.key / f"{kind}.wav"
            write_wav(path, mix.audio)
            scenarios.append(
                {
                    "name": f"{owner.key}.{kind}",
                    "profile": owner.key,
                    "audio": path.relative_to(out_dir).as_posix(),
                    "sha256": _sha256(path),
                    "tags": [kind.split("_")[0] if kind.startswith("overlap") else kind],
                    "notes": SCENARIOS[kind],
                    "intervals": mix.intervals,
                }
            )
        say(f"Propriétaire {owner.key} : {len(kinds)} scénario(s)")
    manifest = {
        "schema": "jarvis.speaker_benchmark.manifest",
        "schema_version": 1,
        "name": "synthetic",
        "evidence": "synthetic",
        "notes": (
            f"Generated {_dt.date.today().isoformat()} by generate-synthetic (seed {seed}) from Windows TTS voices: "
            + ", ".join(f"{v.key} ({v.engine}, {v.lang}, {v.gender})" for v in voices)
            + ". Owners in turn: " + ", ".join(v.key for v in owner_voices)
            + ". Every voice reads French text. NOT evidence for production thresholds."
        ),
        "profiles": {v.key: {"enroll": [f"tts/{_tts_name(v, 'enroll', ENROLL_TEXT, 1.0)}"]} for v in owner_voices},
        "engines": list(engines) if engines is not None else [
            {"name": "campplus-zh-en-advanced", "kind": "sherpa-onnx", "model": "campplus-zh-en-advanced"}
        ],
        "scenarios": scenarios,
    }
    (out_dir / "voices.json").write_text(json.dumps([v.payload() for v in voices], indent=2), encoding="utf-8")
    target = out_dir / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
