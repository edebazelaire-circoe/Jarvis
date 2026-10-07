"""Contrôle outillé de HV-WAKEWORD-MIC-01-i : aucun micro ouvert quand `wake_word.enabled=false`.

    python scripts/check_wake_word_disabled.py
    python scripts/check_wake_word_disabled.py --json

Le script compose le mot d'éveil de SIMPLE (`simple_wake_backends`, la fonction
que `jarvis/app.py` appelle) avec le réglage éteint, dans un runtime temporaire,
avec un FAUX `sounddevice` : aucun vrai micro n'est jamais ouvert. Il démarre
chaque détecteur composé, puis lit le registre `jarvis/audio/input_ownership.py`
(compte et étiquettes des propriétaires) et les tentatives d'ouverture du faux
flux. Un cas témoin (openWakeWord allumé, faux moteur) prouve que le compte peut
bouger : sans lui, « 0 » ne démontrerait rien.

Limite (Issue 003, ouverte) : ce script vérifie le CODE de composition avec de
faux flux ; il ne regarde pas le JARVIS vivant, dont le registre n'est pas lisible
au repos. La preuve sur le poste reste la fiche (aucune ligne `wake.*.started`,
page de confidentialité du micro de Windows, `physical_input_owners=1`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIMIT = (
    "Ce contrôle vérifie la composition du code avec de faux flux : il ne regarde pas le JARVIS vivant, "
    "dont le registre des propriétaires n'est pas lisible au repos (Issue 003). Sur le poste, la preuve reste : "
    "aucune ligne wake.own_stream.started / wake.shared_pcm.started dans runtime/trace.jsonl, la page "
    "Confidentialité > Microphone de Windows, et physical_input_owners=1 à l'entrée en PRESENTATION."
)


class FakeStream:
    def __init__(self, kwargs: dict[str, Any]) -> None:
        self.kwargs = kwargs
        self.callback = kwargs.get("callback")

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeSoundDevice:
    """Le module `sounddevice` factice : il compte les ouvertures et n'ouvre rien."""

    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []

    def RawInputStream(self, **kwargs: Any) -> FakeStream:  # noqa: N802 - nom de l'API réelle
        self.attempts.append(kwargs)
        return FakeStream(kwargs)


class FakeEngine:
    """Un moteur de détection qui ne détecte rien (cas témoin)."""

    sample_rate = 16_000
    frame_length = 1280
    last_score = 0.0
    threshold = 0.5

    def process(self, frame: Any) -> bool:  # noqa: ARG002
        return False

    def delete(self) -> None:
        return None


@contextlib.contextmanager
def _isolated(fake: FakeSoundDevice):
    """Faux `sounddevice` et runtime temporaire, remis en état à la sortie."""

    missing = object()
    saved_module = sys.modules.get("sounddevice", missing)
    saved_env = os.environ.get("JARVIS_RUNTIME_DIR")
    sys.modules["sounddevice"] = fake  # type: ignore[assignment]
    with tempfile.TemporaryDirectory(prefix="jarvis-wake-check-") as runtime:
        os.environ["JARVIS_RUNTIME_DIR"] = runtime
        try:
            yield
        finally:
            if saved_env is None:
                os.environ.pop("JARVIS_RUNTIME_DIR", None)
            else:
                os.environ["JARVIS_RUNTIME_DIR"] = saved_env
            if saved_module is missing:
                sys.modules.pop("sounddevice", None)
            else:
                sys.modules["sounddevice"] = saved_module  # type: ignore[assignment]


async def _compose_and_start(block: Any, access_key: str) -> list[Any]:
    """Composer comme `app.py` (sans la touche manuelle) puis démarrer chaque détecteur."""

    from jarvis.runtime import simple_wake_word

    backends = simple_wake_word.simple_wake_backends(
        block=block, access_key=access_key, keyword="jarvis", device=None,
    )
    for backend in backends:
        await backend.start()
    return list(backends)


async def _scenario(name: str, block: Any, *, expect_open: bool, control: bool = False) -> dict[str, Any]:
    from jarvis.audio import input_ownership

    input_ownership.reset_for_test()
    fake = sys.modules["sounddevice"]
    backends: list[Any] = []
    try:
        if control:
            from jarvis.adapters.wakeword_own_stream import OwnStreamWakeWordBackend

            backend = OwnStreamWakeWordBackend(
                engine_factory=FakeEngine, keyword="hey_jarvis", provider="openwakeword", device=None,
            )
            await backend.start()
            backends = [backend]
        else:
            backends = await _compose_and_start(block, "")
        owners = [entry.owner for entry in input_ownership.open_input_streams()]
        attempts = len(fake.attempts)  # type: ignore[attr-defined]
    finally:
        for backend in backends:
            with contextlib.suppress(Exception):
                await backend.close()
        input_ownership.reset_for_test()
        fake.attempts.clear()  # type: ignore[attr-defined]
    opened = bool(owners) or attempts > 0
    return {
        "scenario": name,
        "expect_open": expect_open,
        "detectors_composed": len(backends),
        "owners": len(owners),
        "owner_labels": owners,
        "open_attempts": attempts,
        "ok": opened == expect_open and (len(owners) == (1 if expect_open else 0)),
    }


def run_checks() -> list[dict[str, Any]]:
    from jarvis.runtime import wake_word_settings as wws

    scenarios = [
        ("aucun réglage (défaut du produit)", wws.load({}), False, False),
        ("enabled=false, fournisseur porcupine", wws.WakeWordSettings(enabled=False), False, False),
        ("enabled=false, fournisseur openwakeword",
         wws.WakeWordSettings(enabled=False, provider=wws.PROVIDER_OPENWAKEWORD, keyword="hey_jarvis"), False, False),
        ("cas témoin : détecteur à flux propre démarré (faux moteur)", None, True, True),
    ]
    fake = FakeSoundDevice()
    results: list[dict[str, Any]] = []
    with _isolated(fake):
        for name, block, expect_open, control in scenarios:
            results.append(asyncio.run(_scenario(name, block, expect_open=expect_open, control=control)))
    return results


def render(results: list[dict[str, Any]]) -> str:
    lines = ["Contrôle HV-WAKEWORD-MIC-01-i : aucun micro ouvert quand le mot d'éveil est éteint",
             "Registre lu : jarvis.audio.input_ownership (input_ownership), faux sounddevice, runtime temporaire.", ""]
    for result in results:
        verdict = "OK" if result["ok"] else "DÉFAUT"
        labels = ", ".join(result["owner_labels"]) or "aucun"
        lines.append(f"- {result['scenario']}")
        lines.append(f"    détecteurs composés : {result['detectors_composed']} ; "
                     f"propriétaires du micro : {result['owners']} ({labels}) ; "
                     f"tentatives d'ouverture : {result['open_attempts']} -> {verdict}")
    lines += ["", LIMIT]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aucun micro ouvert quand wake_word.enabled=false (faux flux).")
    parser.add_argument("--json", action="store_true", help="JSON au lieu du texte.")
    args = parser.parse_args(argv)
    results = run_checks()
    ok = all(result["ok"] for result in results)
    if args.json:
        print(json.dumps({"ok": ok, "checks": results, "limit": LIMIT}, ensure_ascii=False, indent=2))
    else:
        print(render(results))
        if not ok:
            print("\nDÉFAUT : un flux est ouvert alors que l'interrupteur est éteint (ou le cas témoin n'ouvre rien).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
