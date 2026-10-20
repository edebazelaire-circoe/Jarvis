"""Les relais préparés, du Control Center au hook, sans réseau (Slice 06).

Un relais se fait en deux gestes de l'agent qui passe la main :

1. `relation_handoff` (outil MCP) : Core valide le paquet et garde le relais
   préparé ; le Control Center en dépose ici un **billet** :
   `<runtime>/agent-handoffs/<handoff_id>.json`, écrit atomiquement ;
2. l'appel `Agent` du successeur, avec `[relais]` : le hook `PreToolUse`
   (court, hors ligne) **réclame** le billet de son appelant (`claim`) par la
   création exclusive d'un marqueur `<handoff_id>.claim` — deux appels
   simultanés ne réclament jamais le même billet, Windows compris —, puis
   l'efface ; il déclare le successeur Mission Owner de
   la mission reprise (`handoff_id` dans le fait) et appose le paquet sur sa
   consigne.

Un billet ne porte que des identifiants, l'objet du relais et le paquet validé
par Core (texte de collaboration borné, jamais un raisonnement). Borne : au
plus `MAX_FILES` billets. Élagage (`prune`) à l'écriture, à la réclamation et
au relais du Control Center : un billet réclamé ou expiré (`HANDOFF_TTL_S`)
est effacé, un marqueur après `RETENTION_S`. Un billet expiré n'est jamais
réclamé : Core l'a oublié aussi. Un fichier
illisible n'est pas réparé : il est ignoré, puis élagué.

Contrat : `docs/agent-relations.md` §10.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

from jarvis.domain.agent_relations import HandoffPacket, RelationError
from jarvis.domain.relation_runtime import AGENT_REF, HANDOFF_ID_PREFIX, HANDOFF_TTL_S

HANDOFFS_DIR = "agent-handoffs"
MAX_FILES = 64
RETENTION_S = 3_600
MAX_TICKET_BYTES = 32_768
#: Marqueur de réclamation, créé exclusivement (une seule réclamation par billet).
CLAIM_MARKER_SUFFIX = ".claim"
_ID = re.compile(re.escape(HANDOFF_ID_PREFIX) + r"[A-Za-z0-9_-]{8,64}\Z")


class HandoffTicketError(OSError):
    """Billet non écrit (dossier plein, id hors contrat) : le relais préparé ne peut pas être réclamé."""


@dataclass(frozen=True, slots=True)
class HandoffTicket:
    handoff_id: str
    mission_id: str
    predecessor_agent_id: str
    purpose: str
    packet: HandoffPacket
    expires_at_ms: int

    def to_payload(self) -> dict[str, Any]:
        return {"handoff_id": self.handoff_id, "mission_id": self.mission_id,
                "predecessor_agent_id": self.predecessor_agent_id, "purpose": self.purpose,
                "packet": self.packet.to_payload(), "expires_at_ms": self.expires_at_ms}

    @classmethod
    def from_payload(cls, payload: object) -> HandoffTicket:
        if not isinstance(payload, dict) or set(payload) != {"handoff_id", "mission_id", "predecessor_agent_id",
                                                             "purpose", "packet", "expires_at_ms"}:
            raise ValueError("handoff ticket keys are out of contract")
        handoff_id, agent_id = payload["handoff_id"], payload["predecessor_agent_id"]
        if not isinstance(handoff_id, str) or not _ID.fullmatch(handoff_id):
            raise ValueError("handoff_id is out of contract")
        if not isinstance(agent_id, str) or not AGENT_REF.fullmatch(agent_id):
            raise ValueError("predecessor_agent_id is out of contract")
        if not isinstance(payload["mission_id"], str) or not isinstance(payload["purpose"], str):
            raise ValueError("mission_id and purpose are strings")
        expires = payload["expires_at_ms"]
        if not isinstance(expires, int) or isinstance(expires, bool):
            raise ValueError("expires_at_ms is an integer")
        return cls(handoff_id=handoff_id, mission_id=payload["mission_id"], predecessor_agent_id=agent_id,
                   purpose=payload["purpose"], packet=HandoffPacket.from_payload(payload["packet"]),
                   expires_at_ms=expires)


def folder(runtime_root: Path) -> Path:
    return Path(runtime_root) / HANDOFFS_DIR


def _now_ms() -> int:
    return int(time.time() * 1000)


def write_ticket(runtime_root: Path, ticket: HandoffTicket) -> Path:
    """Déposer un billet (Control Center). Lève `HandoffTicketError` ou `OSError` : l'appelant le dit à l'agent."""

    if not _ID.fullmatch(ticket.handoff_id):
        raise HandoffTicketError(f"handoff id {ticket.handoff_id!r} is out of contract")
    target_dir = folder(runtime_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    prune(runtime_root)
    if sum(1 for _ in target_dir.glob("hof_*.json")) >= MAX_FILES:
        raise HandoffTicketError(f"{MAX_FILES} handoff tickets already wait in {target_dir}")
    data = json.dumps(ticket.to_payload(), ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_TICKET_BYTES:
        raise HandoffTicketError(f"handoff ticket exceeds {MAX_TICKET_BYTES} bytes")
    fd, temp = tempfile.mkstemp(prefix=".hof-", suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        target = target_dir / f"{ticket.handoff_id}.json"
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass  # intentional: the temp file may already be gone; the original failure is re-raised just below
        raise
    return target


def _read(path: Path) -> HandoffTicket | None:
    try:
        if path.stat().st_size > MAX_TICKET_BYTES:
            return None
        return HandoffTicket.from_payload(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, RelationError):
        return None  # intentional: an unreadable ticket is never claimed nor repaired; `prune` removes it later


def _marker(path: Path, handoff_id: str) -> Path:
    return path.with_name(f"{handoff_id}{CLAIM_MARKER_SUFFIX}")


def claim(runtime_root: Path, predecessor_agent_id: str, *, now_ms: int | None = None) -> HandoffTicket | None:
    """Réclamer le billet le plus récent, non expiré, préparé par `predecessor_agent_id` (hook). `None` si aucun.

    Une seule réclamation par billet, y compris sous Windows : la réclamation est la **création exclusive** d'un
    marqueur `<handoff_id>.claim` (`O_CREAT | O_EXCL`, atomique sur NTFS comme sur POSIX). Un renommage
    (`os.replace`) ne suffisait pas : sous Windows il écrase une cible existante, et la QA a vu un billet réclamé
    par quatre hooks simultanés. Le billet réclamé est ensuite effacé (son contenu est déjà lu) ; le marqueur reste
    jusqu'à l'élagage, pour qu'un hook en retard qui aurait lu le billet avant l'effacement échoue à son tour.
    Lève `OSError` si le dossier est illisible : le hook le consigne et refuse l'appel `[relais]`.
    """

    target_dir = folder(runtime_root)
    if not target_dir.is_dir():
        return None
    now = _now_ms() if now_ms is None else now_ms
    prune(runtime_root, now_ms=now)
    candidates = []
    for path in target_dir.glob("hof_*.json"):
        ticket = _read(path)
        if (ticket is not None and ticket.predecessor_agent_id == predecessor_agent_id and ticket.expires_at_ms > now
                and not _marker(path, ticket.handoff_id).exists()):
            candidates.append((ticket.expires_at_ms, path, ticket))
    for _expires, path, ticket in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            os.close(os.open(_marker(path, ticket.handoff_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            continue  # intentional: a concurrent hook claimed it first; try the next one
        try:
            path.unlink()
        except OSError:
            pass  # intentional: the marker already makes it claimed; `prune` removes a leftover ticket later
        return ticket
    return None


def prune(runtime_root: Path, *, now_ms: int | None = None) -> int:
    """Effacer les billets expirés ou déjà réclamés, et les marqueurs plus vieux que `RETENTION_S`.

    Appelé à l'écriture et à la réclamation d'un billet, et par le relais du Control Center à chaque élagage de son
    registre (démarrage compris) : un billet réclamé ou expiré ne reste pas sur disque. Rend le nombre effacé.
    """

    target_dir = folder(runtime_root)
    if not target_dir.is_dir():
        return 0
    now = _now_ms() if now_ms is None else now_ms
    old = now / 1000 - RETENTION_S
    removed = 0
    for path in target_dir.iterdir():
        try:
            if path.name.endswith(".json") and path.name.startswith("hof_"):
                ticket = _read(path)
                stale = (ticket is None and path.stat().st_mtime < old) or (
                    ticket is not None and (ticket.expires_at_ms <= now or _marker(path, ticket.handoff_id).exists()))
            else:
                stale = path.stat().st_mtime < old  # marqueurs et temporaires orphelins
            if stale:
                path.unlink()
                removed += 1
        except OSError:
            continue  # intentional: a file another process removes meanwhile is simply gone
    return removed


def expires_at_ms(prepared_ms: int) -> int:
    return prepared_ms + HANDOFF_TTL_S * 1000
