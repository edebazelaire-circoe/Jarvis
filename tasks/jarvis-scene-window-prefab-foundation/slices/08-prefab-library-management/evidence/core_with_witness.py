"""Core de la preuve navigateur S08 : le vrai Core, plus une édition de base faite par la vraie porte.

Pourquoi ce lanceur et pas `python -m jarvis core` : la vue doit montrer un
prefab de base « modifié à votre demande » avec vos mots cités. La porte
`PrefabService.edit_base` exige un témoin — les mots exacts dans un tour
utilisateur enregistré dans les Conversation Events depuis moins de 30 min.
Sans micro ni cerveau, ce lanceur enregistre ce tour comme le fait
l'admission vocale (`build_conversation_event`, producteur
`PRODUCER_VOICE_ADMISSION`, le même chemin que `tests/unit/test_display_mcp_prefabs.py`),
puis appelle la route réelle `POST /v1/prefabs/jarvis.table/base-edits`
(acteur `brain`, jeton porteur). La porte n'est PAS affaiblie : sans ce tour,
Core refuse (`base_edit_unconfirmed`).

Le reste est le Core de `jarvis.app._run_core_v2`, réduit : même
`V2Settings` (variables d'environnement), même jeton, même serveur.

Usage (scratch neuf, jamais 17653) :
  JARVIS_DATA_ROOT=… JARVIS_RUNTIME_DIR=… JARVIS_CORE_PORT=18993 python core_with_witness.py
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import aiohttp

import jarvis
from jarvis.app import _write_session_token
from jarvis.core.conversation_event_emitter import PRODUCER_VOICE_ADMISSION, build_conversation_event
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_events import ConversationEventType
from jarvis.domain.v2 import utc_now
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.journal import RuntimeJournal
from jarvis.security.session_token import generate_session_token
from jarvis.v2_config import V2Settings

USER_WORDS = "Jarvis, modifie le prefab de base tableau : accent orange par défaut, s'il te plaît."


def table_candidate() -> dict:
    folder = Path(jarvis.__file__).parent / "prefabs" / "base" / "jarvis.table" / "1"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    edited = copy.deepcopy(manifest)
    edited["inputs"]["props"]["properties"]["accent"]["default"] = "#ff9b45"
    return {"manifest": edited, "template": (folder / "template.html").read_text(encoding="utf-8"),
            "style": (folder / "style.css").read_text(encoding="utf-8"),
            "behavior": (folder / "behavior.js").read_text(encoding="utf-8")}


async def main() -> None:
    settings = V2Settings.load()
    token = generate_session_token()
    _write_session_token(settings.token_file, token)
    core = JarvisCoreApplication(data_root=settings.data_root, diagnostics=RuntimeJournal(settings.runtime_root))
    server = LocalProtocolServer(core, host=settings.core_host, port=settings.core_port, token=token)
    await core.start()
    await server.start()
    print(f"Jarvis Core (S08 proof) ready on http://{settings.core_host}:{settings.core_port}", flush=True)
    event = build_conversation_event(
        ConversationEventType.USER_TRANSCRIPT_ACCEPTED, producer=PRODUCER_VOICE_ADMISSION,
        conversation_id="conv-s08", source_ids=("s08-turn",), occurred_at=utc_now(),
        correlation_id="corr-s08", turn_id="turn-s08", content=USER_WORDS)
    await core.conversation_event_emitter.append_now([event])
    url = f"http://{settings.core_host}:{settings.core_port}/v1/prefabs/jarvis.table/base-edits"
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as http:
        async with http.post(url, json={"actor": "brain", "candidate": table_candidate(), "user_request": USER_WORDS,
                                        "confirmed_by_user": True}) as response:
            print(f"base-edit jarvis.table -> HTTP {response.status} {await response.text()}", flush=True)
    try:
        await core.wait()
    finally:
        await server.stop()
        await core.stop()
        settings.token_file.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
