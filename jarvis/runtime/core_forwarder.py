"""Relais bornés d'un processus client vers Core, par lots et depuis leur propre tâche.

Deux relais partagent ce socle : l'état des sous-tâches
(`work_ingress.WorkIngressForwarder`, `POST /v1/work/observations`) et les
Conversation Events des processus Voice et Control Center
(`conversation_event_forwarder.ConversationEventForwarder`,
`POST /v1/conversation-events`). Leur file diffère — observations coalescées
par tâche d'un côté, faits en ajout seul de l'autre —, pas leur façon de
joindre Core :

- l'entrée est synchrone et appartient au relais concret : ni attente, ni
  réseau, ni exception de transport sur le chemin qui l'appelle ;
- une tâche vide la file : attente d'un réveil (ou d'une sonde de repos),
  regroupement pendant `flush_interval_s`, envoi, puis délai croissant
  (`retry_min_s` → `retry_max_s`) tant que Core est injoignable ;
- un refus de Core (`CoreBatchRejected`, 4xx) abandonne le lot : le rejouer à
  l'identique ne servirait à rien. Consigné une fois par série ;
- une indisponibilité (Core arrêté, 503, jeton périmé, réseau) garde le lot.
  Consignée une fois, puis la reprise une fois ;
- l'arrêt (`aclose`) annule la tâche, tente un dernier envoi borné par
  `close_timeout_s`, puis ferme le transport.

`CoreLoopbackTransport` relit le jeton de session à chaque (re)connexion : Core
en écrit un neuf à chaque démarrage, et peut démarrer après ce processus.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from jarvis.protocol.client import LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal


class CoreBatchRejected(RuntimeError):
    """Core a refusé le lot (400) : le rejouer à l'identique ne servirait à rien."""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} caractères)"


class CoreLoopbackTransport:
    """Session vers Core par la boucle locale, jeton relu à chaque (re)connexion."""

    def __init__(self, *, host: str, port: int, token_file: Path) -> None:
        self.host = host
        self.port = port
        self.token_file = Path(token_file)
        self._client: LocalCoreClient | None = None

    def _connect(self) -> LocalCoreClient:
        if self._client is None:
            try:
                token = self.token_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConnectionError("Core session token is unavailable; is `jarvis core` running?") from exc
            if not token:
                raise ConnectionError("Core session token is empty")
            self._client = LocalCoreClient(host=self.host, port=self.port, token=token)
        return self._client

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.close()


class CoreBatchForwarder:
    """Boucle d'envoi commune : réveil, regroupement, envoi, délai croissant, arrêt borné.

    Le relais concret fournit sa file (`pending_count`, `flush`), ses données
    de journal (`_report_data`) et ses libellés (`*_KIND`, `*_MESSAGE`).
    `idle_interval_s` arme une sonde de repos (`_on_idle`) ; None attend
    indéfiniment le prochain réveil.
    """

    TASK_NAME = "jarvis-core-forwarder"
    UNAVAILABLE_KIND = "core_forwarder.unavailable"
    UNAVAILABLE_MESSAGE = "Core injoignable : l'envoi attend."
    RESTORED_KIND = "core_forwarder.restored"
    RESTORED_MESSAGE = "Core joint : l'envoi reprend."
    REJECTED_KIND = "core_forwarder.rejected"
    REJECTED_MESSAGE = "Core a refusé un lot : lot abandonné."

    def __init__(
        self,
        *,
        transport: Any,
        journal: RuntimeJournal | None,
        flush_interval_s: float,
        retry_min_s: float,
        retry_max_s: float,
        close_timeout_s: float,
        idle_interval_s: float | None,
    ) -> None:
        self.transport = transport
        self.journal = journal
        self.flush_interval_s = flush_interval_s
        self.retry_min_s = retry_min_s
        self.retry_max_s = retry_max_s
        self.close_timeout_s = close_timeout_s
        self.idle_interval_s = idle_interval_s
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._unavailable = False
        self._rejected = False

    @property
    def pending_count(self) -> int:
        raise NotImplementedError

    # ------------------------------------------------------------ cycle

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run(), name=self.TASK_NAME)

    async def aclose(self) -> None:
        """Arrêter l'envoi, après une dernière tentative bornée."""

        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.pending_count:
            try:
                await asyncio.wait_for(self.flush(), timeout=self.close_timeout_s)
            except Exception:  # noqa: BLE001 - délai compris : l'arrêt ne reste jamais bloqué
                pass
        self._after_close()
        try:
            await self.transport.close()
        except Exception:  # noqa: BLE001
            pass

    def _after_close(self) -> None:
        """Ce qui reste en file après le dernier envoi : au relais concret d'en rendre compte."""

    async def _run(self) -> None:
        backoff = self.retry_min_s
        while True:
            try:
                if not self.pending_count:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=self.idle_interval_s)
                    except TimeoutError:
                        # Rien n'a bougé : sonde de repos du relais concret.
                        self._on_idle()
                        if not self.pending_count:
                            continue
                # Regroupe une rafale d'événements en un lot, et borne le débit
                # vers Core à un envoi par intervalle.
                await asyncio.sleep(self.flush_interval_s)
                if await self.flush():
                    backoff = self.retry_min_s
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - la tâche d'envoi ne meurt jamais
                self._report_unavailable(exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.retry_max_s)

    async def flush(self) -> bool:
        """Envoyer ce qui attend ; faux si Core est injoignable."""

        raise NotImplementedError

    def _on_idle(self) -> None:
        """Sonde de repos (`idle_interval_s` écoulé sans réveil)."""

    # --------------------------------------------------------- diagnostic

    def _note_accepted(self) -> None:
        """Un lot accepté : la panne est finie, et la série de refus est close."""

        if self._unavailable:
            self._unavailable = False
            self._report(self.RESTORED_KIND, self.RESTORED_MESSAGE, "info")
        self._rejected = False

    def _report_rejected(self, exc: Exception) -> None:
        """Consigner un refus une fois par série : le journal écrit sur disque.

        Un Core d'une autre version refuse chaque lot ; sans cette garde, la
        boucle d'envoi écrirait deux lignes par seconde depuis la boucle
        d'événements. Les compteurs du relais, eux, comptent tout.
        """

        if self._rejected:
            return
        self._rejected = True
        self._report(self.REJECTED_KIND, self.REJECTED_MESSAGE, "error", exc)

    def _report_unavailable(self, exc: Exception) -> None:
        if self._unavailable:
            return
        self._unavailable = True
        self._report(self.UNAVAILABLE_KIND, self.UNAVAILABLE_MESSAGE, "warning", exc)

    def _report_data(self) -> dict[str, Any]:
        return {"pending": self.pending_count}

    def _report(self, kind: str, message: str, level: str, exc: Exception | None = None,
                extra: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        data: dict[str, Any] = {**self._report_data(), **(extra or {})}
        if exc is not None:
            data.update(exception_type=type(exc).__name__, error=_truncate(str(exc), 200))
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001 - un journal indisponible n'arrête pas l'envoi
            self._on_report_failure()

    def _on_report_failure(self) -> None:
        """Journal en panne : le relais concret peut le compter (jamais relevé)."""
