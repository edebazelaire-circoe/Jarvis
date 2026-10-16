"""Cibles de capture : `GET /v1/captures/targets` (Core) et `GET /api/captures/targets` (relais).

Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 04 ; architecture
résolue §5 (D6). Contrat : `docs/capture.md` › *HTTP API* et *Interface*.
Ce qui doit tenir :

- écran : `default` (l'écran principal) puis chaque **autre** écran
  `displayN`, dans l'ordre de la source (`order_displays`) ; `display1`, qui
  est le principal, n'est pas rendu une seconde fois ;
- audio : `default` (le réglage de Voice, libellé du nom résolu), puis les
  autres entrées de l'API hôte par défaut, jeton tiré du **nom** (stable
  quand l'index PortAudio dérive) et accepté au démarrage ;
- énumération illisible : `default` seul, `code: targets_unreadable`, ligne
  `core.capture.targets_unreadable` — jamais une page d'erreur ; un canal sans
  source : `available: false` et le code du refus ;
- le relais rend la réponse de Core telle quelle et refuse une origine
  étrangère (lecture gardée).
"""

from __future__ import annotations

import pytest

from jarvis.adapters.screen_capture import ScreenCaptureSources
from jarvis.adapters.sounddevice_recording import AudioRecordingSources, input_token
from jarvis.adapters.windows_display import Display, order_displays
from jarvis.domain._checks import TOKEN as DEVICE_TOKEN
from jarvis.domain.capture import CaptureChannel, CaptureError, CaptureErrorCode
from jarvis.ports.capture import CaptureTarget
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_capture_api_protocol import core

SCREEN, AUDIO = CaptureChannel.SCREEN, CaptureChannel.AUDIO


class Displays:
    def __init__(self, displays: list[Display]) -> None:
        self.current = displays

    def displays(self) -> list[Display]:
        return list(self.current)

    def grab(self, token: str):  # noqa: ANN201 - jamais appelé ici
        raise AssertionError("une lecture des cibles ne prend jamais d'image")


def _three_displays() -> list[Display]:
    # (device, left, top, width, height, primary, dpi) : principal au milieu, un à gauche, un à droite.
    return order_displays([("\\\\.\\DISPLAY2", 1920, 0, 2560, 1440, False, 96),
                           ("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True, 120),
                           ("\\\\.\\DISPLAY3", -1280, 0, 1280, 1024, False, 96)])


class Recorder:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.lines.append((kind, level, dict(data or {})))


# ------------------------------------------------------------------ critères d'acceptation


async def test_targets_list_default_and_displays_in_source_order(tmp_path):
    displays = _three_displays()
    sources = ScreenCaptureSources(displays_factory=lambda: Displays(displays), ffmpeg_locator=lambda: None,
                                   platform_name="nt")
    listed = [t.to_payload() for t in sources.targets(SCREEN)]
    assert listed == [
        {"token": "default", "label": "Écran principal", "primary": True, "width": 1920, "height": 1080},
        {"token": "display2", "label": "Écran 2", "primary": False, "width": 1280, "height": 1024},
        {"token": "display3", "label": "Écran 3", "primary": False, "width": 2560, "height": 1440},
    ]
    # Même ordre que la prise : `display2` est bien l'écran que `displayN` désigne au démarrage.
    assert [d.name for d in displays] == ["display1", "display2", "display3"]
    # Un seul écran : `default` seul (la règle de l'entrée unique côté interface).
    alone = ScreenCaptureSources(displays_factory=lambda: Displays(displays[:1]), ffmpeg_locator=lambda: None,
                                 platform_name="nt")
    assert [t.token for t in alone.targets(SCREEN)] == ["default"]
    # Hors Windows, ou pour un autre canal : le refus de la source, jamais une cible.
    for registry, channel, code in ((ScreenCaptureSources(platform_name="posix"), SCREEN,
                                     CaptureErrorCode.UNSUPPORTED_PLATFORM),
                                    (sources, AUDIO, CaptureErrorCode.UNSUPPORTED_SOURCE)):
        with pytest.raises(CaptureError) as refused:
            registry.targets(channel)
        assert refused.value.code is code
    # Par Core : la même liste, `available`, aucun code.
    async with CaptureStack(tmp_path) as stack:
        stack.core.captures._sources.target_lists[SCREEN] = lambda: sources.targets(SCREEN)
        status, body, _, _ = await core(stack, "GET", "/v1/captures/targets")
        assert status == 200, body
        assert body["screen"] == {"available": True, "devices": listed}
        assert body["audio"]["devices"][0]["token"] == "default"
        assert set(body) == {"audio", "screen"}


def _inputs():
    return {"inputs": [
        {"id": 0, "name": "Microsoft Sound Mapper - Input", "hostapi": "MME"},
        {"id": 1, "name": "Microphone (Realtek(R) Audio)", "hostapi": "MME"},
        {"id": 2, "name": "Casque (USB Headset)", "hostapi": "MME"},
        {"id": 3, "name": "Casque (USB Headset)", "hostapi": "MME"},
        {"id": 7, "name": "Microphone (Realtek(R) Audio)", "hostapi": "Windows WASAPI"},
    ], "defaults": {"input": 1}}


def test_audio_targets_use_name_tokens_and_default_first():
    class Backend:
        def __init__(self) -> None:
            self.device = None

    sources = AudioRecordingSources(configured_device=lambda: None, list_inputs=_inputs, backend_factory=Backend)
    listed = [t.to_payload() for t in sources.targets(AUDIO)]
    # `default` d'abord, nommé d'après l'entrée que Voice utilise ; elle n'est pas répétée dessous.
    assert listed[0] == {"token": "default", "label": "Micro de Voice — Microphone (Realtek(R) Audio)",
                         "default": True}
    # Les autres entrées de l'API hôte par défaut (MME), ordre de la source ; WASAPI exclue (même micro).
    assert [(t["token"], t["label"]) for t in listed[1:]] == [
        ("Microsoft-Sound-Mapper---Input", "Microsoft Sound Mapper - Input"),
        ("Casque-USB-Headset", "Casque (USB Headset)"),
        ("Casque-USB-Headset-2", "Casque (USB Headset)"),
    ]
    for target in listed:
        assert DEVICE_TOKEN.fullmatch(target["token"]) and len(target["token"]) <= 128, target
    # Le jeton est accepté au démarrage et choisit l'index **courant** du nom.
    assert sources.continuous(AUDIO, source=None, device="Casque-USB-Headset-2")._device == 3
    assert sources.continuous(AUDIO, source=None, device="default")._device is None  # réglage de Voice
    assert sources.continuous(AUDIO, source=None, device="2")._device == 2  # index PortAudio, comme avant
    with pytest.raises(CaptureError) as gone:
        sources.continuous(AUDIO, source=None, device="Micro-debranche")
    assert gone.value.code is CaptureErrorCode.SOURCE_UNAVAILABLE
    # Voice réglée sur un nom : `default` le dit, et cette entrée n'est pas répétée.
    named = AudioRecordingSources(configured_device=lambda: "Casque (USB Headset)", list_inputs=_inputs)
    assert named.targets(AUDIO)[0].label == "Micro de Voice — Casque (USB Headset)"
    assert [t.label for t in named.targets(AUDIO)[1:]].count("Casque (USB Headset)") == 1
    # Sans énumération : `default` seul (rien d'inventé).
    bare = AudioRecordingSources(configured_device=lambda: None)
    assert [t.to_payload() for t in bare.targets(AUDIO)] == [{"token": "default", "label": "Micro de Voice",
                                                                "default": True}]
    # Jamais de son système : seules des entrées. L'écran est délégué, sinon refusé.
    with pytest.raises(CaptureError) as refused:
        bare.targets(SCREEN)
    assert refused.value.code is CaptureErrorCode.UNSUPPORTED_SOURCE
    assert [input_token(n) for n in ("default", "42", "((", "Mic\u00e9 1")] == ["input-default", "input-42",
                                                                               "input", "Mic-1"]


async def test_enumeration_failure_returns_default_only_and_journals(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        journal = Recorder()
        stack.core.captures._diagnostics = journal

        def broken() -> list[CaptureTarget]:
            raise OSError("EnumDisplayMonitors failed at C:\\Users\\Jean Dupont\\x")

        registry = stack.core.captures._sources
        registry.target_lists[SCREEN] = broken
        status, body, raw, _ = await core(stack, "GET", "/v1/captures/targets")
        assert status == 200, body
        assert body["screen"] == {"available": True, "code": "targets_unreadable",
                                  "devices": [{"token": "default", "label": "Écran principal", "primary": True}]}
        assert body["audio"]["available"] is True and "code" not in body["audio"]
        assert b"Jean Dupont" not in raw
        line = [entry for entry in journal.lines if entry[0] == "core.capture.targets_unreadable"]
        assert line == [("core.capture.targets_unreadable", "warning", {"channel": "screen", "reason": "OSError"})]
        # Une liste sans `default` en tête n'est pas servie telle quelle non plus.
        registry.target_lists[SCREEN] = lambda: [CaptureTarget(token="display2", label="Écran 2")]
        _, body, _, _ = await core(stack, "GET", "/v1/captures/targets")
        assert body["screen"]["code"] == "targets_unreadable" and len(body["screen"]["devices"]) == 1
        # Aucune source pour le canal : dit tel quel, aucune cible.
        registry.platform_supported = False
        _, body, _, _ = await core(stack, "GET", "/v1/captures/targets")
        assert body["screen"] == {"available": False, "devices": [], "code": "unsupported_platform"}
        # Une lecture des cibles n'ouvre aucune capture.
        assert stack.core.captures.status().captures == ()
        status, body, _, _ = await core(stack, "GET", "/v1/captures/targets?x=1")
        assert (status, body["error"]["code"]) == (400, "invalid_request")


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"},
])
async def test_relay_is_read_guarded(tmp_path, headers):
    async with CaptureStack(tmp_path) as stack:
        status, via_cc, _ = await stack.call("GET", "/api/captures/targets")
        _, direct, _, _ = await core(stack, "GET", "/v1/captures/targets")
        assert status == 200 and via_cc == direct
        status, refused, _ = await stack.call("GET", "/api/captures/targets", headers=headers)
        assert status == 403 and refused["code"] == "forbidden_origin"


async def test_a_lister_that_hangs_times_out_to_default_only(tmp_path, monkeypatch):
    """QA S04 P3 : une énumération qui ne rend jamais la main (pilote bloqué)
    s'arrête à `TARGETS_TIMEOUT_S` : `default` seul, `targets_unreadable`,
    raison `timeout` au journal — la route répond, la page ne reste pas en
    « Chargement… »."""

    import threading
    import time

    from jarvis.core import capture_service

    monkeypatch.setattr(capture_service, "TARGETS_TIMEOUT_S", 0.2)
    release = threading.Event()
    async with CaptureStack(tmp_path) as stack:
        journal = Recorder()
        stack.core.captures._diagnostics = journal

        def stuck() -> list[CaptureTarget]:
            release.wait(10)
            return [CaptureTarget(token="default", label="Écran principal")]

        stack.core.captures._sources.target_lists[SCREEN] = stuck
        started = time.monotonic()
        try:
            status, body, _, _ = await core(stack, "GET", "/v1/captures/targets")
        finally:
            release.set()
        assert status == 200, body
        assert time.monotonic() - started < 5
        assert body["screen"] == {"available": True, "code": "targets_unreadable",
                                  "devices": [{"token": "default", "label": "Écran principal", "primary": True}]}
        line = [entry for entry in journal.lines if entry[0] == "core.capture.targets_unreadable"]
        assert line == [("core.capture.targets_unreadable", "warning", {"channel": "screen", "reason": "timeout"})]
