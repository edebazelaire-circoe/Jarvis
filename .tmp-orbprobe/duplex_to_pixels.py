"""Preuve pixel : le vrai chemin duplex jusqu'a l'ecran.

On ne pilote PAS le bus a la main. On joue un fil GPT-Live (deltas d'entree mot
a mot, delegation, blocs audio, puis silence du peripherique) a travers la vraie
facade `LiveFrontendSession`, le vrai `RealtimeConversationBridge` et le vrai
`PersistentVoiceRuntime`. Ce sont eux qui ecrivent `.voice_state`. Un vrai
serveur ai-visualizer lit ce bus, et Chrome headless photographie la face.

Mesure donc la chaine entiere : fournisseur -> facade -> bridge -> runtime ->
bus -> serveur -> pixels.
"""
import asyncio
import json
from pathlib import Path
import sys
import time

REPO = Path(r"D:\Projects\CIRCOE\Jarvis")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from orbshot import analyse, get_state, shoot  # noqa: E402

from jarvis.domain.voice_events import (  # noqa: E402
    AssistantAudioChunk, VoiceDelegationRequested,
)
from jarvis.domain.voice_frontend import VoiceAudioChunk, VoiceCorrelation  # noqa: E402
from tests.integration.test_duplex_orb_states import (  # noqa: E402
    audio_chunk, drain, rig, word,
)

BUS = HERE / "bus"
FACE = "neural"          # la face qui discrimine le mieux (mesure du banc)
PORT = 8799
SIZE = 900
VTB = 4000


def capture(label: str):
    """Photographier la face telle qu'elle est, sans toucher au bus."""

    time.sleep(0.9)  # laisser la face sonder /state et converger ses easings
    png = HERE / "shots" / f"duplex-{label}.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{PORT}/faces/{FACE}/"
    before = get_state(PORT)
    result = shoot(url, str(png), SIZE, VTB, str(HERE / "chrome-profile"))
    after = get_state(PORT)
    row = {
        "etape": label,
        "bus_voice_state": (BUS / ".voice_state").read_text(encoding="utf-8").strip(),
        "waveform_presente": (BUS / ".voice_waveform").exists(),
        "serveur_avant": before.get("state") if isinstance(before, dict) else before,
        "serveur_apres": after.get("state") if isinstance(after, dict) else after,
    }
    if result["rc"] == 0 and png.exists():
        pixels = analyse(str(png), step=2, grid=0)
        row["luminance"] = round(pixels["mean_luma"], 3)
        row["fraction_non_noire"] = round(pixels["nonblack_frac"] * 100, 2)
        row["rgb_non_noir"] = pixels["mean_rgb_nonblack"]
        row["teinte_dominante_deg"] = pixels["dominant_hue_bin_deg"]
    else:
        row["erreur"] = "pas de PNG"
    return row


async def main():
    BUS.mkdir(parents=True, exist_ok=True)
    (BUS / ".voice_waveform").unlink(missing_ok=True)

    frontend, session, bus, runtime, bridge = await rig(BUS)
    rows = []

    # -- 1. Session active, rien d'adresse : la veille.
    rows.append(capture("1-veille"))

    # -- 2. L'utilisateur parle, puis le fournisseur delegue un vrai travail.
    for index, text in enumerate([" Jarvis", ", compare", " les", " prix"], start=1):
        frontend.inject(word(frontend, text, index))
    frontend.inject(frontend.event(
        VoiceDelegationRequested(1), correlation=VoiceCorrelation("live-session")))
    drain(session, frontend)
    for envelope in session._legacy_pending:
        await bridge._handle_event(envelope)
    rows.append(capture("2-reflexion"))

    # -- 3. JARVIS parle : la reponse du cerveau, portee par une demande de
    #       parole (`speech_id`), via la vraie tache de lecture du bridge.
    for _ in range(4):
        frontend.inject(frontend.event(
            AssistantAudioChunk(VoiceAudioChunk(bytes(960))),
            correlation=VoiceCorrelation(
                "live-session", output_id="output-1", speech_id="speech-1")))
    drain(session, frontend)
    bridge._inbox, bridge._playout = asyncio.Queue(), asyncio.Queue()
    player = asyncio.create_task(bridge._play_out())
    try:
        for envelope in session._legacy_pending:
            if envelope.message_type == "realtime.audio":
                bridge._dispatch(envelope)
            else:
                await bridge._handle_event(envelope)
        async with asyncio.timeout(5):
            while (BUS / ".voice_state").read_text(encoding="utf-8").strip() != "speaking":
                await asyncio.sleep(0)
        # Capture SYNCHRONE : la boucle est gelee, donc `_play_out` ne peut pas
        # atteindre la quiescence pendant la photo. On mesure bien la parole.
        rows.append(capture("3-parole"))

        # -- 4. Le peripherique s'est tu. Le fil Live n'enverra jamais de fin
        #       de sortie : seule la quiescence locale peut rendre l'ecran.
        async with asyncio.timeout(10):
            while not bridge._live_output_quiescent:
                await asyncio.sleep(0)
        await asyncio.sleep(0.2)
    finally:
        player.cancel()
    rows.append(capture("4-retour"))

    print(json.dumps(rows, indent=2, ensure_ascii=False))


asyncio.run(main())
