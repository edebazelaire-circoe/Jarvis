"""Boucle de rappels d'agenda de Core (partie vivante ; la règle est dans `jarvis/domain/agenda_reminders.py`).

Deux cadences distinctes :

- la **relecture** de l'agenda (`refresh_minutes`, 10 min par défaut) : un
  appel à l'outil calendrier du plugin, fenêtre de maintenant - 1 h à
  maintenant + 36 h ; le résultat est gardé en cache entre deux relectures ;
- l'**évaluation** (`tick_s`, 30 s) : le plan des étapes échues est recalculé
  sur le cache, donc un rappel à 10 minutes tombe à 30 s près sans marteler
  le fournisseur.

Les réglages sont relus à chaque évaluation (`settings()`), donc un
changement du Control Center agit à chaud ; interrupteur éteint, la boucle ne
lit rien et ne dit rien.

**Mémoire « déjà rappelé »** : un petit fichier JSON dans la racine de
données (`agenda_reminders.json`), pas une base : c'est un cache jetable
(le perdre rejoue au pire un rappel), il n'a ni schéma ni migration. Les
entrées de plus de 3 jours sont élaguées. La clé contient l'heure de début :
un rendez-vous déplacé est rappelé à nouveau.

**Accusé** : l'étape `late` (« en cours / manqué ») se tait si l'utilisateur
a parlé au cerveau depuis le dernier rappel de ce rendez-vous. Une étape n'est
marquée faite que si le tour a bien été ouvert : un rappel refusé (rien
n'écoute, un tour est en vol) est retenté au tour suivant, tant qu'il n'est
pas périmé.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone, tzinfo
import json
from pathlib import Path
from typing import Any

from jarvis.domain.agenda_reminders import (
    AgendaEvent,
    AgendaSettings,
    build_agenda_prompt,
    plan_reminders,
)
from jarvis.ports.v2 import DiagnosticSink

AGENDA_REMINDER_KIND = "core.agenda.reminder"
AGENDA_FETCH_FAILED_KIND = "core.agenda.fetch_failed"
AGENDA_MEMORY_FAILED_KIND = "core.agenda.memory_failed"

DEFAULT_TICK_S = 30.0
FETCH_RETRY_S = 60.0
LOOKBEHIND = timedelta(hours=1)
LOOKAHEAD = timedelta(hours=36)
MEMORY_RETENTION = timedelta(days=3)

Fetch = Callable[[datetime, datetime], Awaitable[list[AgendaEvent]]]
Wake = Callable[[str], Awaitable[bool]]


class AgendaReminderService:
    def __init__(self, *, settings: Callable[[], AgendaSettings], fetch: Fetch, wake: Wake, memory_path: Path,
                 zone: tzinfo, diagnostics: DiagnosticSink, user_turn_at: Callable[[], datetime | None] = lambda: None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), tick_s: float = DEFAULT_TICK_S) -> None:
        self._settings = settings
        self._fetch = fetch
        self._wake = wake
        self._path = Path(memory_path)
        self._zone = zone
        self._diagnostics = diagnostics
        self._user_turn_at = user_turn_at
        self._clock = clock
        self._tick_s = tick_s
        self._events: list[AgendaEvent] = []
        self._next_fetch: datetime | None = None
        self._fetch_failing = False
        self._task: asyncio.Task[None] | None = None
        self._memory: dict[str, str] | None = None

    # ------------------------------------------------------------ cycle de vie

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="jarvis-agenda-reminders")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - la boucle survit à une panne, tracée puis retentée
                self._diagnostics.emit(AGENDA_FETCH_FAILED_KIND, "rappels d'agenda : tour de boucle en échec", level="error",
                                       data={"exception_type": type(exc).__name__, "error": str(exc)[:300]})
            await asyncio.sleep(self._tick_s)

    # ------------------------------------------------------------------ un tour

    async def tick(self) -> int:
        """Une évaluation ; rend le nombre de rappels annoncés (un tour du cerveau les porte tous)."""

        settings = self._settings()
        if not settings.enabled:
            return 0
        now = self._clock()
        await self._refresh(now, settings)
        memory = self._load()
        plan = plan_reminders(self._events, now, settings, self._zone, memory)
        changed = False
        stamp = now.isoformat()
        for key in plan.consume:
            memory[key] = stamp
            changed = True
        announce = []
        last_user = self._user_turn_at()
        for reminder in plan.announce:
            if reminder.stage == "late" and last_user is not None and self._acknowledged(reminder.event, memory, last_user):
                memory[reminder.key] = stamp
                changed = True
                continue
            announce.append(reminder)
        sent = 0
        if announce:
            prompt = build_agenda_prompt(tuple(announce), now, self._zone)
            if await self._wake(prompt):
                for reminder in announce:
                    memory[reminder.key] = stamp
                sent = len(announce)
                changed = True
                self._diagnostics.emit(AGENDA_REMINDER_KIND, "rappel d'agenda confié au cerveau", level="info",
                                       data={"count": sent, "stages": sorted({r.stage for r in announce}),
                                             "event_ids": [r.event.event_id for r in announce]})
        if changed:
            self._save(memory, now)
        return sent

    def _acknowledged(self, event: AgendaEvent, memory: dict[str, str], last_user: datetime) -> bool:
        """L'utilisateur a parlé après le dernier rappel **annoncé** de ce rendez-vous."""

        prefix = f"{event.event_id}|{event.start.isoformat()}|"
        times = []
        for key, value in memory.items():
            if key.startswith(prefix):
                moment = _parse(value)
                if moment is not None:
                    times.append(moment)
        return bool(times) and last_user > max(times)

    async def _refresh(self, now: datetime, settings: AgendaSettings) -> None:
        if self._next_fetch is not None and now < self._next_fetch:
            return
        try:
            self._events = list(await self._fetch(now - LOOKBEHIND, now + LOOKAHEAD))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - agenda injoignable : on garde le cache, on le dit une fois
            self._next_fetch = now + timedelta(seconds=FETCH_RETRY_S)
            if not self._fetch_failing:
                self._diagnostics.emit(AGENDA_FETCH_FAILED_KIND, "agenda illisible : rappels sur le dernier cache connu",
                                       level="warning", data={"exception_type": type(exc).__name__, "error": str(exc)[:300]})
            self._fetch_failing = True
            return
        self._fetch_failing = False
        self._next_fetch = now + timedelta(minutes=settings.refresh_minutes)

    # ------------------------------------------------------------------ mémoire

    def _load(self) -> dict[str, str]:
        if self._memory is None:
            try:
                value = json.loads(self._path.read_text(encoding="utf-8"))
                self._memory = {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}
            except FileNotFoundError:
                self._memory = {}
            except (OSError, ValueError) as exc:
                self._diagnostics.emit(AGENDA_MEMORY_FAILED_KIND, "mémoire des rappels illisible : repart à vide",
                                       level="warning", data={"exception_type": type(exc).__name__})
                self._memory = {}
        return self._memory

    def _save(self, memory: dict[str, str], now: datetime) -> None:
        horizon = now - MEMORY_RETENTION
        for key in [k for k, v in memory.items() if (_parse(v) or now) < horizon]:
            del memory[key]
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(memory, ensure_ascii=False, indent=0), encoding="utf-8")
            temporary.replace(self._path)
        except OSError as exc:
            # Mémoire seule en RAM : au pire un rappel rejoué après redémarrage.
            self._diagnostics.emit(AGENDA_MEMORY_FAILED_KIND, "mémoire des rappels non écrite", level="warning",
                                   data={"exception_type": type(exc).__name__})


def _parse(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def events_from_outcome(outcome: dict[str, Any]) -> list[AgendaEvent]:
    """Événements d'un `ToolCallOutcome` : `structured` s'il y est, sinon le JSON des blocs texte."""

    from jarvis.domain.agenda_reminders import parse_events

    if not outcome.get("ok"):
        raise RuntimeError(f"l'outil calendrier a échoué : {outcome.get('code')}")
    structured = outcome.get("structured")
    if structured is not None:
        events = parse_events(structured)
        if events or structured in ({}, []):
            return events
    text = "".join(str(block.get("text", "")) for block in outcome.get("content", []) if isinstance(block, dict))
    if not text.strip():
        return []
    return parse_events(json.loads(text))
