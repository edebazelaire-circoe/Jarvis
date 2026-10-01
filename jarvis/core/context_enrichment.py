"""Worker d'enrichissement du Context actif (handoff session-context-recording, Slice 08).

Possédé par Core, indépendant du cerveau de conversation et du mode
d'interaction. Il lit le **ledger d'activité canonique** de la Session ouverte
(`ArtifactService.activity`, curseur `after_seq`), transforme la nouvelle
preuve (segments de transcription, captures d'écran, enregistrements, trous)
en lignes compactes référencées, et fait réécrire par un modèle sans outil le
`summary.md` **entier** du Context actif à partir du résumé précédent et de
cette preuve. `summary.md` est une projection révisable (un point ouvert peut
devenir réglé) ; la preuve brute n'est jamais réécrite (D07, D08).

Contrat : `docs/session-context.md` › *Enrichment worker*. Points tenus ici :

- **Déclenchement** : sondage du ledger toutes les `poll_interval_s` (une
  requête SQL bornée) ou `wake()` ; une preuve nouvelle ouvre une attente
  (`debounce_s` de calme, au plus `max_delay_s` depuis la première), et deux
  tours de modèle sont espacés d'au moins `min_interval_s`. Un arriéré plein
  (`MAX_BATCH_EVENTS`) part sans attendre le calme.
- **Contre-pression** : tout ce qui est arrivé depuis le curseur est
  coalescé en un tour ; un tour prend au plus `MAX_BATCH_EVENTS` événements
  et `MAX_EVIDENCE_BYTES` de preuve, le reste attend le tour suivant. L'état
  courant est borné (`summary.md` ≤ `MAX_SUMMARY_BYTES`), l'entrée du modèle
  aussi (`MAX_PROMPT_BYTES`).
- **Curseur** : `.jarvis-enrichment.json` dans le dossier du Context, écrit
  **après** `summary.md`, sous le verrou des transitions et seulement si le
  Context est encore actif (`SessionManager.write_active_context_files`). Une
  mort entre les deux rejoue le même lot : le modèle réécrit le résumé borné
  depuis un résumé qui contient déjà cette preuve, sans accumulation.
- **Frontière de Context** (D05) : seules les preuves survenues pendant que le
  Context était actif comptent (marche du ledger sur `context.*`) ; un
  Context devenu dormant n'est plus écrit, même au milieu d'un tour.
- **Sans fournisseur** : état `unavailable` (`enrichment_provider_unavailable`),
  aucun plantage, le curseur n'avance pas.
- **Journal** : identifiants, comptes, tailles, coût — jamais le texte de la
  salle (D17, même règle que les profils restreints du CLI).

Reprise QA (Slice 08) :

- l'état actif du Context au curseur est **dérivé du ledger**
  (`context_periods.active_at`), jamais supposé : une période dormante plus
  longue qu'une page n'entre plus dans le résumé du Context réactivé ;
- les descriptions de captures comptent **dans** le budget de preuve ; un lot
  trop gros est raccourci (moins d'événements), jamais refusé ;
- les fichiers à écrire sont vérifiés (chemin Windows) **avant** l'appel payé ;
  un tour payé puis non écrit **garde sa sortie en mémoire** : seule
  l'écriture est retentée (même backoff), sans nouvel appel ; si elle échoue
  encore `WRITE_RETRY_WINDOW_S` après le premier échec, la sortie est
  abandonnée et le lot passe `stuck` : plus d'appel au modèle avant un
  changement de Context ou de modèle, ou `STUCK_COOLDOWN_S` (reprise QA
  mineure : un verrou de fichier de quelques minutes ne gèle plus summary.md
  une heure) ;
- un curseur au-delà de la fin du ledger (base restaurée) est dit une fois et
  ramené à la fin du ledger : la preuve déjà résumée n'est pas repayée ;
- `enabled=False` (`JARVIS_CONTEXT_ENRICHMENT=0`) : état `disabled`, aucun sondage.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
import json
import time
from typing import Any

from jarvis.core import context_periods
from jarvis.domain.artifacts import Artifact, ArtifactErrorCode, ArtifactError, ArtifactKind, ArtifactRelationKind, ArtifactState
from jarvis.domain.context_enrichment_prompt import (
    DESCRIBE_INSTRUCTIONS, PROMPT_CLOSE, PROMPT_OPEN, SUMMARY_INSTRUCTIONS, TARGET_SUMMARY_BYTES,  # noqa: F401
    defang_delimiters,
)
from jarvis.domain.session_activity import ActivityEvent, ActivityKind, ActivityQuery
from jarvis.domain.v2 import utc_now
from jarvis.ports.context_enrichment import (
    MODEL_EMPTY, MODEL_FAILED, MODEL_TIMEOUT, MODEL_UNAVAILABLE, ContextEnrichmentModel, EnrichmentImage,
    EnrichmentModelError, EnrichmentReply,
)
from jarvis.ports.session_context import ContextWorkspaceError
from jarvis.ports.v2 import DiagnosticSink

#: Fichiers gérés par Jarvis dans le dossier du Context (mêmes noms que l'adaptateur).
SUMMARY_FILE = "summary.md"
CURSOR_FILE = ".jarvis-enrichment.json"
CURSOR_VERSION = 1
#: `summary.md` : même borne que le bloc du tour (`MAX_BRAIN_CONTEXT_SUMMARY_BYTES`).
MAX_SUMMARY_BYTES = 2_048
#: Événements lus par tour (= limite d'une page du ledger).
MAX_BATCH_EVENTS = 200
#: Preuve textuelle par tour ; une ligne seule est coupée à `MAX_LINE_CHARS`.
MAX_EVIDENCE_BYTES = 8_000
MAX_LINE_CHARS = 1_200
#: Entrée totale du modèle (consigne + résumé + preuve), vérifiée avant l'appel.
MAX_PROMPT_BYTES = 12_288
#: Descriptions de captures d'écran par tour : jamais plus, le reste passe sans.
MAX_DESCRIPTIONS_PER_ROUND = 2
#: Image envoyée telle quelle (pas de redimensionnement sans dépendance) ; au-delà : non décrite.
MAX_IMAGE_BYTES = 3_500_000
MAX_DESCRIPTION_CHARS = 600
DESCRIPTION_SOURCE = "enrichment"
DESCRIPTION_SUFFIX = "_desc"

DEFAULT_POLL_INTERVAL_S = 5.0
#: Cadence (décision PM, coût) : 45 s de calme, au plus 120 s après la première preuve,
#: au moins 90 s entre deux tours -> au plus 40 tours/h, ≈ 0,36 $/h au pire avec haiku sans réflexion
#: (cache de 5 min, voir docs/OPERATIONS.md).
DEFAULT_DEBOUNCE_S = 45.0
DEFAULT_MAX_DELAY_S = 120.0
DEFAULT_MIN_INTERVAL_S = 90.0
DEFAULT_TIMEOUT_S = 120.0
#: Reprise après un échec de tour (modèle, écriture) : 30 s, 2 min, 10 min.
FAILURE_BACKOFF_S = (30.0, 120.0, 600.0)
#: Un tour payé non écrit : sa sortie est gardée et seule l'écriture est retentée (backoff
#: `FAILURE_BACKOFF_S`) ; un échec encore à ce délai du premier -> sortie abandonnée, `stuck`.
#: 15 min couvrent un verrou de fichier passager (antivirus, synchro, éditeur) ; au-delà, panne durable.
WRITE_RETRY_WINDOW_S = 900.0
#: Un lot `stuck` est retenté une fois après ce délai (au plus un appel payé par heure).
STUCK_COOLDOWN_S = 3_600.0
STUCK_CODE = "enrichment_round_stuck"
DISABLED_CODE = "enrichment_disabled"

#: Consigne du résumé (registre de prompts) ; `INSTRUCTIONS` reste l'ancien nom.
INSTRUCTIONS = SUMMARY_INSTRUCTIONS

_RELEVANT = (ActivityKind.TRANSCRIPT_SEGMENT_CREATED, ActivityKind.ARTIFACT_FINALIZED, ActivityKind.CAPTURE_STARTED,
             ActivityKind.CAPTURE_STOPPED, ActivityKind.CAPTURE_GAP)


@dataclass(frozen=True, slots=True)
class EnrichmentCursor:
    context_id: str
    after_seq: int
    rounds: int = 0
    #: Le Context était-il actif juste après `after_seq` ? Mémoire seulement (dérivé du
    #: ledger au chargement, `context_periods.active_at`), jamais écrit dans le fichier.
    active: bool = True

    def to_text(self, *, now: datetime) -> str:
        return json.dumps({"version": CURSOR_VERSION, "context_id": self.context_id, "after_seq": self.after_seq,
                           "rounds": self.rounds, "updated_at": now.isoformat()}, ensure_ascii=False) + "\n"

    @classmethod
    def parse(cls, text: str, context_id: str) -> EnrichmentCursor | None:
        """Le curseur du fichier, ou `None` s'il est absent, d'un autre Context ou hors contrat."""

        try:
            value = json.loads(text)
        except ValueError:
            return None
        if (not isinstance(value, dict) or value.get("version") != CURSOR_VERSION
                or value.get("context_id") != context_id):
            return None
        after, rounds = value.get("after_seq"), value.get("rounds", 0)
        if type(after) is not int or after < 0 or type(rounds) is not int or rounds < 0:
            return None
        return cls(context_id, after, rounds)


@dataclass(slots=True)
class _Pending:
    context_id: str
    first_seen: float
    last_change: float
    newest_seq: int


@dataclass(slots=True)
class _Unwritten:
    """Sortie payée d'un tour dont l'écriture a échoué : rejouée sans rappeler le modèle."""

    context_id: str
    cursor: EnrichmentCursor
    batch: EvidenceBatch
    summary: str
    reply: EnrichmentReply
    first_failed_at: float
    attempts: int = 1


@dataclass(slots=True)
class _Shot:
    artifact: Artifact
    index: int


@dataclass(slots=True)
class EvidenceBatch:
    """Lot d'un tour : lignes de preuve (ordre du ledger) et `last_seq` = dernier événement couvert."""

    lines: list[str] = field(default_factory=list)
    last_seq: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    shots: list[_Shot] = field(default_factory=list)
    bytes: int = 0
    #: `seq` de l'événement de chaque ligne (même ordre que `lines`) : raccourcir le lot.
    line_seqs: list[int] = field(default_factory=list)
    #: État actif du Context juste après `last_seq` (curseur suivant).
    active: bool = True

    def count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def add(self, line: str, seq: int) -> None:
        self.lines.append(line)
        self.line_seqs.append(seq)
        self.bytes += len(line.encode("utf-8")) + 1

    def append_to(self, index: int, suffix: str) -> None:
        self.lines[index] += suffix
        self.bytes += len(suffix.encode("utf-8"))

    def shrink_to(self, limit: int) -> bool:
        """Garde les premières lignes qui tiennent dans `limit` octets (au moins une) ; le reste,
        et les événements depuis la première ligne retirée, attendent le tour suivant. Rend `True`
        si le lot a été raccourci."""

        size, keep = 0, 0
        for line in self.lines:
            cost = len(line.encode("utf-8")) + 1
            if keep and size + cost > limit:
                break
            size, keep = size + cost, keep + 1
        if keep >= len(self.lines):
            return False
        # Une ligne n'est produite que pendant que le Context est actif, et son
        # événement ne change pas cet état : juste avant elle, il était actif.
        self.last_seq, self.active = self.line_seqs[keep] - 1, True
        del self.lines[keep:], self.line_seqs[keep:]
        self.shots = [shot for shot in self.shots if shot.index < keep]
        self.bytes = size
        return True


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clip_lines_bytes(text: str, limit: int) -> tuple[str, bool]:
    """Le plus long préfixe de lignes entières qui tient dans `limit` octets (au moins un caractère entier)."""

    data = text.encode("utf-8")
    if len(data) <= limit:
        return text, False
    kept: list[str] = []
    size = 0
    for line in text.splitlines():
        cost = len(line.encode("utf-8")) + 1
        if size + cost > limit:
            break
        kept.append(line)
        size += cost
    if not kept:
        return data[:limit].decode("utf-8", errors="ignore"), True
    return "\n".join(kept), True


def _mmss(ms: object) -> str | None:
    if type(ms) is not int or ms < 0:
        return None
    seconds = ms // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _clock_label(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")


def normalize_summary(text: str) -> tuple[str, bool]:
    """Réponse du modèle -> contenu de `summary.md` : sans clôture de code, borné en lignes entières."""

    body = str(text or "").strip()
    if body.startswith("```"):
        lines = body.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    if not body:
        raise EnrichmentModelError(MODEL_EMPTY, "the model returned an empty summary")
    body, clipped = _clip_lines_bytes(body, MAX_SUMMARY_BYTES - 1)
    return body + "\n", clipped


def build_prompt(previous_summary: str, batch: EvidenceBatch, *, first_seq: int) -> str:
    """Consigne + résumé actuel + preuve, chacun entre délimiteurs ; ceux-ci sont neutralisés dans
    le contenu (`defang_delimiters`) : ni le résumé ni la salle ne ferment un bloc."""

    previous = defang_delimiters(previous_summary.strip()) or "(vide : premier résumé de ce Context)"
    return (f"{INSTRUCTIONS}\n\nRÉSUMÉ ACTUEL :\n{PROMPT_OPEN}\n{previous}\n{PROMPT_CLOSE}\n\n"
            f"NOUVELLES PREUVES (activité {first_seq}..{batch.last_seq}) :\n{PROMPT_OPEN}\n"
            + "\n".join(batch.lines) + f"\n{PROMPT_CLOSE}")


class ContextEnrichmentWorker:
    """Voir l'en-tête du module. `tick()` fait un pas ; `start()`/`close()` la boucle de Core."""

    def __init__(
        self,
        sessions: Any,
        artifacts: Any,
        model: Callable[[], ContextEnrichmentModel | None],
        *,
        diagnostics: DiagnosticSink | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = utc_now,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        debounce_s: float = DEFAULT_DEBOUNCE_S,
        max_delay_s: float = DEFAULT_MAX_DELAY_S,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        failure_backoff_s: tuple[float, ...] = FAILURE_BACKOFF_S,
        enabled: bool = True,
    ) -> None:
        self._sessions = sessions
        self._artifacts = artifacts
        self._model = model
        self._diagnostics = diagnostics
        self._clock = clock
        self._wall = wall_clock
        self.poll_interval_s = poll_interval_s
        self.debounce_s = debounce_s
        self.max_delay_s = max_delay_s
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self._failure_backoff_s = failure_backoff_s
        #: `False` (`JARVIS_CONTEXT_ENRICHMENT=0`) : `disabled`, aucune boucle, aucun sondage.
        self.enabled = enabled
        #: Sortie payée en attente d'écriture (au plus une : celle du lot courant).
        self._unwritten: _Unwritten | None = None
        #: `(context_id, after_seq, modèle, jusqu'à)` d'un lot `stuck`, sinon `None`.
        self._stuck: tuple[str, int, str, float] | None = None
        self._cursors: dict[str, EnrichmentCursor] = {}
        self._pending: _Pending | None = None
        self._last_round_at: float | None = None
        self._backoff_until = 0.0
        self._failures = 0
        self._wake = asyncio.Event()
        #: États dégradés déjà dits (`unavailable`, `no_context`) : dits une fois, pas à chaque sondage.
        self._said_once: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._status: dict[str, Any] = {"state": "stopped", "code": None, "context_id": None, "after_seq": None,
                                        "rounds": 0, "descriptions": 0, "total_cost_usd": 0.0,
                                        "last_cost_usd": None, "last_round_at": None, "model": None}

    # ------------------------------------------------------------ cycle de vie

    def start(self) -> None:
        if not self.enabled:
            self._set(state="disabled", code=DISABLED_CODE)
            self._trace("core.context_enrichment.disabled",
                        "Enrichissement du Context coupé (JARVIS_CONTEXT_ENRICHMENT=0) : summary.md n'est pas tenu",
                        data={"code": DISABLED_CODE}, once="disabled")
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="jarvis-context-enrichment")
            self._set(state="idle")

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._set(state="disabled" if not self.enabled else "stopped")

    def wake(self) -> None:
        """Nouvelle preuve probable (ou changement de Context) : sonder tout de suite."""

        self._wake.set()

    async def on_association_changed(self, reason: str) -> None:
        """Rappel de `SessionManager` : le Context actif a changé ; l'attente en cours est oubliée."""

        self._pending = None
        self._trace("core.context_enrichment.context_changed", "Context actif changé : l'enrichissement suit le nouveau",
                    data={"reason": reason})
        self.wake()

    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: logged with its cause, the loop keeps the worker alive
                self._fail("enrichment_tick_failed", exc)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval_s)
            except asyncio.TimeoutError:
                pass  # argued: the poll interval elapsed, the next tick polls the ledger

    # ------------------------------------------------------------ un pas

    async def tick(self) -> str:
        """Un pas du worker ; rend ce qui s'est passé (`idle`, `waiting`, `round`, `skipped`,
        `unavailable`, `context_switched`, `backoff`, `no_context`, `failed`, `stuck`, `disabled`)."""

        if not self.enabled:
            return "disabled"
        now = self._clock()
        if now < self._backoff_until:
            return "backoff"
        try:
            view = await self._sessions.current_context()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: no open Session/Context; said, retried at the next poll
            self._set(state="idle", code="no_active_context", context_id=None)
            self._trace("core.context_enrichment.no_context", f"Pas de Context actif lisible : {type(exc).__name__}",
                        level="warning", data={"exception_type": type(exc).__name__}, once="no_context")
            return "no_context"
        context = view.context
        if view.workspace_error is not None:
            self._set(state="idle", code=view.workspace_error, context_id=context.context_id)
            return "no_context"
        cursor = await self._cursor_for(view)
        unwritten = self._unwritten
        if unwritten is not None:
            if (unwritten.context_id, unwritten.cursor.after_seq) == (context.context_id, cursor.after_seq):
                return await self._retry_write(view, unwritten)
            self._unwritten = None  # Context ou curseur changé : la sortie gardée ne vaut plus
        events = await self._artifacts.activity(ActivityQuery(
            after_seq=cursor.after_seq, jarvis_session_id=context.jarvis_session_id, limit=MAX_BATCH_EVENTS))
        self._set(context_id=context.context_id, after_seq=cursor.after_seq)
        if not events:
            self._pending = None
            self._set(state="idle", code=None)
            return "idle"
        newest = events[-1].seq
        pending = self._pending
        if pending is None or pending.context_id != context.context_id:
            pending = self._pending = _Pending(context.context_id, now, now, newest)
        elif newest > pending.newest_seq:
            pending.last_change, pending.newest_seq = now, newest
        backlog_full = len(events) >= MAX_BATCH_EVENTS
        due = backlog_full or now - pending.last_change >= self.debounce_s or now - pending.first_seen >= self.max_delay_s
        if due and self._last_round_at is not None and now - self._last_round_at < self.min_interval_s:
            due = False
        if not due:
            self._set(state="waiting", code=None)
            return "waiting"
        batch = await self._collect(events, context.context_id, cursor.active)
        if not batch.lines:
            # Rien d'interprétable (activité de projection, enrichissement…) : le curseur avance seul.
            return await self._commit(view, cursor, batch, summary=None, reply=None)
        model = self._model()
        if model is None:
            self._set(state="unavailable", code=MODEL_UNAVAILABLE)
            self._trace("core.context_enrichment.unavailable",
                        "Aucun modèle d'enrichissement disponible : summary.md n'est pas tenu (la preuve attend)",
                        level="warning", data={"code": MODEL_UNAVAILABLE, "context_id": context.context_id},
                        once="unavailable")
            return "unavailable"
        stuck = self._stuck
        if stuck is not None:
            if stuck[:3] == (context.context_id, cursor.after_seq, model.model) and now < stuck[3]:
                self._set(state="stuck", code=STUCK_CODE)
                return "stuck"
            self._stuck = None  # Context, curseur ou modèle changé, ou délai passé : une tentative
        try:
            # Avant tout appel payé : les fichiers du tour peuvent-ils être écrits (chemin Windows) ?
            self._sessions.check_context_files(view, (SUMMARY_FILE, CURSOR_FILE))
        except ContextWorkspaceError as exc:
            return self._fail(exc.code, exc, context_id=context.context_id)
        self._set(state="running", code=None, model=model.model)
        try:
            if batch.shots:
                await self._describe(model, batch)
            # Descriptions comprises, la preuve tient dans son budget : sinon moins d'événements.
            shrunk = batch.shrink_to(MAX_EVIDENCE_BYTES)
            previous, _ = await asyncio.to_thread(self._sessions.read_context_file, view, SUMMARY_FILE,
                                                  MAX_SUMMARY_BYTES)
            prompt = build_prompt(previous, batch, first_seq=events[0].seq)
            while len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES and len(batch.lines) > 1:
                excess = len(prompt.encode("utf-8")) - MAX_PROMPT_BYTES
                shrunk = batch.shrink_to(max(1, batch.bytes - excess)) or shrunk
                prompt = build_prompt(previous, batch, first_seq=events[0].seq)
            if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:  # une ligne et le résumé bornés : inatteignable
                raise EnrichmentModelError(MODEL_FAILED, f"prompt over {MAX_PROMPT_BYTES} bytes")
            started = self._clock()
            reply = await self._call(model, prompt)
            summary, clipped = normalize_summary(reply.text)
        except asyncio.CancelledError:
            raise
        except (EnrichmentModelError, ContextWorkspaceError, ArtifactError) as exc:
            return self._fail(getattr(exc, "code", MODEL_FAILED), exc, context_id=context.context_id)
        self._last_round_at = self._clock()
        outcome = await self._commit(view, cursor, batch, summary=summary, reply=reply)
        if outcome == "round":
            self._trace("core.context_enrichment.round", "summary.md du Context actif mis à jour",
                        data={"context_id": context.context_id, "jarvis_session_id": context.jarvis_session_id,
                              "from_seq": events[0].seq, "to_seq": batch.last_seq, "events": len(events),
                              "evidence_lines": len(batch.lines), "evidence_bytes": batch.bytes,
                              "batch_shrunk": shrunk,
                              **{f"n_{key}": value for key, value in sorted(batch.counts.items())},
                              "prompt_bytes": len(prompt.encode("utf-8")),
                              "previous_summary_bytes": len(previous.encode("utf-8")),
                              "summary_bytes": len(summary.encode("utf-8")), "summary_clipped": clipped,
                              "model": reply.model, "cost_usd": reply.cost_usd, "duration_ms": reply.duration_ms,
                              **{f"usage_{key}": value for key, value in sorted(reply.usage.items())},
                              "elapsed_s": round(self._clock() - started, 3),
                              "total_cost_usd": round(self._status["total_cost_usd"], 6)})
        return outcome

    async def _call(self, model: ContextEnrichmentModel, prompt: str,
                    images: tuple[EnrichmentImage, ...] = ()) -> EnrichmentReply:
        try:
            # Deuxième garde : l'adaptateur a son propre délai, celui-ci ne peut pas rester bloqué.
            reply = await asyncio.wait_for(model.complete(prompt, timeout_s=self.timeout_s, images=images),
                                           timeout=self.timeout_s * 1.25 + 1.0)
        except asyncio.TimeoutError as exc:
            raise EnrichmentModelError(MODEL_TIMEOUT, f"no answer within {self.timeout_s:.0f} s") from exc
        if reply.cost_usd is not None:
            self._status["total_cost_usd"] = float(self._status["total_cost_usd"]) + float(reply.cost_usd)
            self._status["last_cost_usd"] = reply.cost_usd
        return reply

    async def _commit(self, view: Any, cursor: EnrichmentCursor, batch: EvidenceBatch, *, summary: str | None,
                      reply: EnrichmentReply | None) -> str:
        context_id = view.context.context_id
        advanced = EnrichmentCursor(context_id, batch.last_seq, cursor.rounds + (1 if summary is not None else 0),
                                    active=batch.active)
        files: tuple[tuple[str, str], ...] = ((CURSOR_FILE, advanced.to_text(now=self._wall())),)
        if summary is not None:
            files = ((SUMMARY_FILE, summary),) + files
        try:
            written = await self._sessions.write_active_context_files(context_id, files)
        except ContextWorkspaceError as exc:
            # `summary.md` a pu être écrit sans le curseur : le prochain tour relit le
            # curseur du fichier ; une sortie payée est gardée et seule l'écriture est rejouée.
            self._cursors.pop(context_id, None)
            outcome = self._fail(exc.code, exc, context_id=context_id)
            if summary is not None and reply is not None:
                self._keep_unwritten(context_id, cursor, batch, summary, reply, exc.code)
            return outcome
        self._unwritten = None
        if written is None:
            self._cursors.pop(context_id, None)
            self._pending = None
            self._set(state="idle", code="context_switched")
            self._trace("core.context_enrichment.context_switched",
                        "Context devenu dormant pendant le tour : rien n'y est écrit", level="warning",
                        data={"context_id": context_id, "to_seq": batch.last_seq})
            return "context_switched"
        self._cursors[context_id] = advanced
        self._pending = None
        self._failures = 0
        self._backoff_until = 0.0
        if summary is None:
            self._set(state="idle", code=None, after_seq=advanced.after_seq)
            return "skipped"
        self._set(state="idle", code=None, after_seq=advanced.after_seq, rounds=self._status["rounds"] + 1,
                  last_round_at=self._wall().isoformat(), model=reply.model if reply else None)
        return "round"

    # ------------------------------------------------------------ curseur

    async def _cursor_for(self, view: Any) -> EnrichmentCursor:
        context = view.context
        cached = self._cursors.get(context.context_id)
        if cached is not None:
            return cached
        text = ""
        try:
            text, _ = await asyncio.to_thread(self._sessions.read_context_file, view, CURSOR_FILE, 4_096)
        except ContextWorkspaceError as exc:
            self._trace("core.context_enrichment.cursor_unreadable", f"Curseur illisible : {str(exc)[:200]}",
                        level="warning", data={"context_id": context.context_id, "code": exc.code})
        cursor = EnrichmentCursor.parse(text, context.context_id) if text else None
        if cursor is None:
            if text:
                self._trace("core.context_enrichment.cursor_reset", "Curseur hors contrat : repris à la naissance du Context",
                            level="warning", data={"context_id": context.context_id})
            cursor = EnrichmentCursor(context.context_id, await self._birth_seq(context))
        latest = await self._artifacts.latest_seq()
        if cursor.after_seq > latest:
            # Base restaurée ou remplacée : le résumé couvre déjà ce qui précède. Repris à la fin
            # du ledger (pas à la naissance du Context) pour ne pas repayer une preuve déjà résumée.
            self._trace("core.context_enrichment.cursor_ahead",
                        "Curseur au-delà de la fin du ledger : repris à la fin du ledger", level="warning",
                        data={"context_id": context.context_id, "after_seq": cursor.after_seq, "latest_seq": latest})
            cursor = EnrichmentCursor(context.context_id, latest, cursor.rounds)
        # État actif au curseur, dérivé du ledger : jamais supposé (B1).
        cursor = EnrichmentCursor(cursor.context_id, cursor.after_seq, cursor.rounds, active=await context_periods.active_at(
            self._artifacts, context.jarvis_session_id, context.context_id, cursor.after_seq))
        self._cursors[context.context_id] = cursor
        return cursor

    async def _birth_seq(self, context: Any) -> int:
        """Point de départ d'un Context sans curseur : son `context.created` (rien d'avant ne lui appartient)."""

        born = await self._artifacts.activity(ActivityQuery(
            after_seq=0, context_id=context.context_id, kinds=(ActivityKind.CONTEXT_CREATED,), limit=1))
        return born[0].seq if born else await self._artifacts.latest_seq()

    # ------------------------------------------------------------ preuve

    async def _collect(self, events: tuple[ActivityEvent, ...], context_id: str, active: bool) -> EvidenceBatch:
        """Lignes de preuve des événements survenus pendant que `context_id` était actif, bornées.

        `active` : état du Context juste avant `events[0]` (celui du curseur, dérivé du ledger).
        """

        batch = EvidenceBatch(last_seq=events[0].seq - 1, active=active)
        for event in events:
            line = None
            if event.kind in context_periods.BOUNDARY_KINDS:
                active = context_periods.step(active, event, context_id)
            elif active and event.kind in _RELEVANT:
                line = await self._line(event, batch)
            if line is not None:
                line = _clip(defang_delimiters(line), MAX_LINE_CHARS)
                cost = len(line.encode("utf-8")) + 1
                if batch.lines and batch.bytes + cost > MAX_EVIDENCE_BYTES:
                    if batch.shots and batch.shots[-1].index == len(batch.lines):
                        batch.shots.pop()  # la capture de cette ligne attend le tour suivant
                    break
                batch.add(line, event.seq)
            batch.last_seq, batch.active = event.seq, active
        return batch

    async def _artifact(self, artifact_id: str | None) -> Artifact | None:
        if not artifact_id:
            return None
        try:
            return await self._artifacts.get(artifact_id)
        except ArtifactError as exc:
            if exc.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                return None  # supprimé depuis : la preuve n'existe plus, rien à résumer
            raise

    async def _line(self, event: ActivityEvent, batch: EvidenceBatch) -> str | None:
        at = _clock_label(event.occurred_at)
        first = event.artifact_ids[0] if event.artifact_ids else None
        if event.kind is ActivityKind.TRANSCRIPT_SEGMENT_CREATED:
            segment = await self._artifact(first)
            if segment is None or not (segment.text or "").strip():
                return None
            audio = segment.metadata.get("audio_artifact_id")
            offset = _mmss(segment.metadata.get("start_ms"))
            ref = f"{audio}@{offset}" if isinstance(audio, str) and offset else segment.artifact_id
            batch.count("segments")
            return f"{at} [{ref}] (salle) {segment.text.strip()}"
        if event.kind is ActivityKind.ARTIFACT_FINALIZED:
            artifact_kind = event.data.get("artifact_kind")
            if artifact_kind == ArtifactKind.SCREENSHOT.value:
                shot = await self._artifact(first)
                if shot is None:
                    return None
                batch.count("screenshots")
                if shot.state is ArtifactState.COMPLETE:
                    batch.shots.append(_Shot(shot, len(batch.lines)))
                return f"{at} [{shot.artifact_id}] capture d'écran ({shot.state.value})"
            if artifact_kind in {ArtifactKind.AUDIO_RECORDING.value, ArtifactKind.SCREEN_RECORDING.value}:
                record = await self._artifact(first)
                if record is None:
                    return None
                batch.count("recordings")
                length = _mmss(record.duration_ms)
                what = "enregistrement audio" if artifact_kind == ArtifactKind.AUDIO_RECORDING.value else "enregistrement d'écran"
                return (f"{at} [{record.artifact_id}] {what} terminé ({record.state.value}"
                        + (f", {length}" if length else "") + ")")
            return None
        capture = event.capture_ids[0] if event.capture_ids else "?"
        channel = event.data.get("channel")
        batch.count("captures")
        if event.kind is ActivityKind.CAPTURE_STARTED:
            return f"{at} capture {capture} démarrée" + (f" ({channel})" if channel else "")
        if event.kind is ActivityKind.CAPTURE_STOPPED:
            return f"{at} capture {capture} arrêtée ({event.data.get('state') or '?'})"
        lost = event.data.get("lost_ms")
        return (f"{at} trou dans la capture {capture} ({event.data.get('reason') or '?'}"
                + (f", {lost} ms perdus" if type(lost) is int else "") + ")")

    # ------------------------------------------------------------ captures d'écran

    async def _describe(self, model: ContextEnrichmentModel, batch: EvidenceBatch) -> None:
        """Description courte des captures d'écran du lot (Artifact `description`, `described_from`).

        Id déterministe `<capture>_desc` : un rejeu reprend la description existante, sans nouvel appel.
        """

        described = 0
        for shot in batch.shots:
            artifact = shot.artifact
            description_id = f"{artifact.artifact_id}{DESCRIPTION_SUFFIX}"
            existing = await self._artifact(description_id)
            text, code = (existing.text or "", None) if existing is not None else ("", None)
            if existing is None:
                if not model.supports_images:
                    code = "screenshot_description_unsupported"
                elif described >= MAX_DESCRIPTIONS_PER_ROUND:
                    code = "screenshot_description_deferred_budget"
                else:
                    text, code = await self._describe_one(model, artifact, description_id)
                    described += 1
            if text:
                # Compté dans le budget du lot (`shrink_to` raccourcit ensuite si besoin).
                batch.append_to(shot.index, f" : {_clip(defang_delimiters(text), MAX_DESCRIPTION_CHARS)}")
            elif code is not None:
                self._trace("core.context_enrichment.screenshot_skipped", "Capture d'écran non décrite",
                            level="info" if code.endswith("unsupported") else "warning",
                            data={"artifact_id": artifact.artifact_id, "code": code})

    async def _describe_one(self, model: ContextEnrichmentModel, shot: Artifact,
                            description_id: str) -> tuple[str, str | None]:
        info = self._artifacts.payload_info(shot)
        size = info.final_bytes if info is not None and info.final_bytes is not None else shot.size_bytes
        if not size or size > MAX_IMAGE_BYTES:
            return "", "screenshot_too_large" if size else "screenshot_payload_missing"
        try:
            data = self._artifacts.read_payload(shot, 0, size)
            reply = await self._call(model, DESCRIBE_INSTRUCTIONS,
                                     (EnrichmentImage(shot.mime_type or "image/png", data),))
        except asyncio.CancelledError:
            raise
        except (EnrichmentModelError, ArtifactError, OSError) as exc:
            code = getattr(exc, "code", "screenshot_description_failed")
            self._trace("core.context_enrichment.screenshot_failed", f"Description de capture ratée : {str(exc)[:200]}",
                        level="warning", data={"artifact_id": shot.artifact_id,
                                               "code": str(getattr(code, "value", code))})
            return "", str(getattr(code, "value", code))
        text = _clip(reply.text, MAX_DESCRIPTION_CHARS)
        if not text:
            return "", MODEL_EMPTY
        metadata: dict[str, Any] = {"screenshot_artifact_id": shot.artifact_id, "model": reply.model[:128]}
        if reply.cost_usd is not None:
            metadata["cost_usd"] = float(reply.cost_usd)
        try:
            await self._artifacts.record_text(
                artifact_id=description_id, kind=ArtifactKind.DESCRIPTION, source=DESCRIPTION_SOURCE, text=text,
                jarvis_session_id=shot.jarvis_session_id, context_id=shot.context_id, started_at=shot.started_at,
                ended_at=shot.ended_at, duration_ms=None, metadata=metadata,
                origins=((ArtifactRelationKind.DESCRIBED_FROM, shot.artifact_id),))
        except ArtifactError as exc:
            if exc.code is not ArtifactErrorCode.ARTIFACT_CONFLICT:
                raise
        self._status["descriptions"] = int(self._status["descriptions"]) + 1
        self._trace("core.context_enrichment.screenshot_described", "Capture d'écran décrite",
                    data={"artifact_id": shot.artifact_id, "description_id": description_id,
                          "image_bytes": size, "chars": len(text), "model": reply.model, "cost_usd": reply.cost_usd,
                          "duration_ms": reply.duration_ms})
        return text, None

    # ------------------------------------------------------------ interne

    def _fail(self, code: object, exc: BaseException, *, context_id: str | None = None) -> str:
        code = str(getattr(code, "value", code) or MODEL_FAILED)
        delay = self._failure_backoff_s[min(self._failures, len(self._failure_backoff_s) - 1)]
        self._failures += 1
        self._backoff_until = self._clock() + delay
        self._set(state="backoff", code=code)
        self._trace("core.context_enrichment.failed",
                    f"Tour d'enrichissement raté ({code}) : {type(exc).__name__}: {str(exc)[:300]}",
                    level="error", data={"code": code, "context_id": context_id, "retry_in_s": delay,
                                         "failures": self._failures, "exception_type": type(exc).__name__})
        return "failed"

    async def _retry_write(self, view: Any, unwritten: _Unwritten) -> str:
        """Réécrit la sortie payée gardée, sans appel au modèle (voir `_keep_unwritten`)."""

        self._set(state="running", code=None)
        outcome = await self._commit(view, unwritten.cursor, unwritten.batch, summary=unwritten.summary,
                                     reply=unwritten.reply)
        if outcome == "round":
            self._trace("core.context_enrichment.write_retried",
                        "summary.md écrit à la reprise de l'écriture, sans nouvel appel au modèle",
                        data={"context_id": unwritten.context_id, "to_seq": unwritten.batch.last_seq,
                              "attempts": unwritten.attempts + 1,
                              "elapsed_s": round(self._clock() - unwritten.first_failed_at, 3),
                              "summary_bytes": len(unwritten.summary.encode("utf-8"))})
        return outcome

    def _keep_unwritten(self, context_id: str, cursor: EnrichmentCursor, batch: EvidenceBatch, summary: str,
                        reply: EnrichmentReply, code: object) -> None:
        """Un tour payé dont l'écriture a échoué : la sortie est gardée et seule l'écriture est
        retentée (backoff de `_fail`). Encore en échec `WRITE_RETRY_WINDOW_S` après le premier :
        sortie abandonnée, `stuck` — plus d'appel au modèle (voir `tick`) avant le délai."""

        now = self._clock()
        kept = self._unwritten
        if kept is not None and (kept.context_id, kept.cursor.after_seq) == (context_id, cursor.after_seq):
            kept.attempts += 1
        else:
            kept = self._unwritten = _Unwritten(context_id, cursor, batch, summary, reply, now)
        if now - kept.first_failed_at < WRITE_RETRY_WINDOW_S:
            return
        self._unwritten = None
        self._stuck = (context_id, cursor.after_seq, reply.model, now + STUCK_COOLDOWN_S)
        cause = str(getattr(code, "value", code) or MODEL_FAILED)
        self._set(state="stuck", code=STUCK_CODE)
        self._trace("core.context_enrichment.stuck",
                    f"Lot payé toujours non écrit après {WRITE_RETRY_WINDOW_S / 60:.0f} min ({kept.attempts} "
                    f"essais, {cause}) : plus d'appel au modèle avant un changement de Context ou de modèle, "
                    f"ou {STUCK_COOLDOWN_S / 60:.0f} min",
                    level="error", data={"code": STUCK_CODE, "cause": cause, "context_id": context_id,
                                         "after_seq": cursor.after_seq, "failures": kept.attempts,
                                         "window_s": WRITE_RETRY_WINDOW_S, "retry_in_s": STUCK_COOLDOWN_S})

    def _set(self, **values: Any) -> None:
        self._status.update(values)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None,
               once: str | None = None) -> None:
        if once is not None:
            if once in self._said_once:
                return
            self._said_once.add(once)
        elif kind == "core.context_enrichment.round":
            self._said_once.clear()  # un tour réussi : le prochain état dégradé se redit
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not stop the worker
            pass
