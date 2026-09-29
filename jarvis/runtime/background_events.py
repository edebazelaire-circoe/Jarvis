"""Registre des événements d'arrière-plan à signaler discrètement.

Pourquoi
--------
Le 16/09/2026, deux demandes vocales sont mortes sans un mot : la console de
debug a arrêté l'agent, ses sous-agents avec, et rien — ni voix, ni écran — ne
l'a dit. Le retour vocal est traité ailleurs (`WorkAttentionPolicy` réveille le
cerveau, qui choisit ses mots). Ce module tient l'autre moitié, celle qui
n'interrompt pas : ce qui s'est passé derrière, compté et lisible dans le
Control Center (pastilles rondes de l'interface principale), avec un signal sonore bref quand le compte monte.

Ce qu'il est
------------
Un tampon borné, purement en mémoire, alimenté par la **trace d'exécution**.
JARVIS tourne en trois processus (UI, voix, Core) qui écrivent tous dans le
même `runtime/trace.jsonl` : c'est déjà leur bus commun, et le suivre est le
seul moyen de voir d'un même point l'échec d'un sous-agent (processus UI), le
réveil du cerveau (Core) et une erreur non prononcée (voix). Accrocher les
journaux un par un n'en aurait montré qu'un tiers.

La lecture est incrémentale (`TraceFollower`) : la trace pèse plusieurs
mégaoctets et un sondage d'interface ne doit pas la relire en entier.

Ce qu'il n'est pas
------------------
Il ne parle pas, ne déclenche aucun travail et ne juge pas : il classe par
catégorie et compte ce qui n'a pas été vu. Il n'est pas non plus la source de
vérité de l'état du travail — c'est `WorkStateStore` — seulement la trace de
ce qui *vient d'arriver*, pour qu'un coup d'œil suffise.

Boards (handoff board-session, Slice 07)
----------------------------------------
Chaque entrée porte le `board_id` de sa source quand la trace le nomme : les
agents du pool écrivent sous un journal lié `{board_id, jarvis_session_id}`
(`RuntimeJournal.bind`), et Core estampille ses diagnostics qui nomment une
`conversation_id` (`jarvis/core/board_attribution.py`). À défaut, `follow`
accepte un résolveur `conversation_id -> board_id` (le pool du Control
Center). Le registre reste **global** : une alerte d'un Board inactif est
visible depuis n'importe quel Board, et n'entre jamais dans le contexte du
cerveau (ce module n'écrit que vers l'écran).

Absence et redémarrage
----------------------
`BackgroundEventStore` persiste entrées, curseur d'acquittement et position
du `TraceFollower` dans `runtime/background-events.json` (borné à
`MAX_ENTRIES`, écriture atomique). Un non-lu survit donc au redémarrage du
Control Center et à une nouvelle Session, et ce que la trace a reçu pendant
que le Control Center était arrêté est rattrapé depuis la position gardée.

Pureté
------
`BackgroundEventLedger` ne fait aucune entrée-sortie et n'a aucune horloge
implicite : l'appelant fournit l'horodatage. La lecture de la trace est isolée
dans `TraceFollower`, la persistance dans `BackgroundEventStore`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from jarvis.domain.presentation_attention import (
    ATTENTION_RAISED_KIND,
    BAND_HIGH,
    BAND_MODERATE,
    MAX_ATTENTION_EVIDENCE,
)

#: Entrées gardées. Assez pour couvrir une séance de travail, trop peu pour
#: devenir un historique — la trace complète reste dans `trace.jsonl`.
MAX_ENTRIES = 60

#: Longueur retenue d'un libellé : de quoi reconnaître l'événement dans une
#: liste, pas de quoi y lire un rapport.
MAX_LABEL = 200

#: Catégories, du plus urgent au moins urgent. L'ordre compte : c'est celui du
#: résumé que lit le badge.
FAILED = "failed"
ATTENTION = "attention"
DONE = "done"
SAID = "said"
CATEGORIES = (FAILED, ATTENTION, DONE, SAID)

#: Statuts de sous-tâche qui valent un échec à signaler. `interrupted` en fait
#: partie : c'est exactement ce qui est arrivé aux deux demandes perdues.
_FAILED_TASK_STATUSES = frozenset({"failed", "killed", "interrupted", "stopped"})

#: Longueur retenue d'une référence recopiée d'un point d'attention. La trace
#: est un fichier que n'importe quoi peut écrire : rien de ce qui en sort n'est
#: cru sur parole, tout est retaillé ici.
MAX_ATTENTION_FIELD = 300

#: Bandes de confiance admises. Une valeur hors table devient la plus prudente :
#: afficher « élevée » sur une donnée qu'on ne reconnaît pas serait la seule
#: erreur coûteuse des deux.
_ATTENTION_BANDS = (BAND_HIGH, BAND_MODERATE)

#: Le détail affiché à côté d'un point d'attention, composé de **données
#: typées** : un compte de sources et une bande. Jamais une phrase venue de la
#: salle — la trace n'en transporte pas, et cette ligne est ce qui le rend
#: visible plutôt que promis.
_ATTENTION_BAND_WORDS = {BAND_HIGH: "confiance élevée", BAND_MODERATE: "confiance moyenne"}

#: Parole retenue par la porte de Core parce que son Board n'a pas la parole
#: (`jarvis/core/brain_service.py`, `BRAIN_SPEECH_WITHHELD_KIND`). Recopié ici
#: plutôt qu'importé : ce module lit la trace, il ne dépend pas de Core.
SPEECH_WITHHELD_KIND = "core.brain.speech_withheld_inactive_board"

#: Ce que la porte retenait, dit en mots fixes (champ `origin` de la trace).
_WITHHELD_ORIGINS = {
    "speech": "réponse retenue",
    "notice": "relais retenu",
    "outcome_selection": "résultat retenu",
    "work_wake": "réveil retenu",
}

#: Longueur retenue d'un identifiant ou d'un titre de Board recopié de la trace.
MAX_BOARD_ID = 64
MAX_BOARD_TITLE = 120

#: Points d'attention remis d'un coup à l'avertissement flottant. Trois : au
#: delà ce n'est plus discret, c'est un panneau — et D11 demande de la
#: discrétion.
MAX_ATTENTION_DIGEST = 3


def _text(value: object, limit: int = MAX_ATTENTION_FIELD) -> str:
    """Une chaîne bornée, quoi que la trace ait contenu."""

    return "" if value is None else str(value)[:limit]


def _attention_payload(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Extraire la charge utile typée d'un point d'attention. Ne lève jamais.

    **Rien de ce qui vient de la trace n'est cru.** Ce fichier est écrit par
    trois processus et peut être édité à la main ; une ligne malformée doit
    produire un événement pauvre, jamais une exception qui viderait le badge de
    toute la séance. Chaque champ est donc retaillé, chaque liste bornée, et
    une bande inconnue retombe sur la plus prudente.

    Rend `None` si l'essentiel manque : sans identifiant ni catégorie, il n'y a
    pas d'avertissement à montrer — l'événement reste compté dans la pastille.
    """

    attention_id = _text(fields.get("attention_id"), 64)
    category = _text(fields.get("category"), 64)
    if not attention_id or not category:
        return None
    band = _text(fields.get("band"), 16)
    # Ni `severity` ni `resource_ids` ne traversent : la carte n'en dessine
    # rien. `severity_for` reste, côté Core, parce que la gravité sert à la
    # coalescence du magasin — mais la transporter jusqu'au navigateur pour
    # qu'il la jette était du câblage mort.
    evidence: list[dict[str, str]] = []
    raw = fields.get("evidence")
    if isinstance(raw, list):
        for piece in raw[:MAX_ATTENTION_EVIDENCE]:
            if not isinstance(piece, dict):
                continue
            evidence.append({
                "source_id": _text(piece.get("source_id"), 64),
                "locator": _text(piece.get("locator")),
                "title": _text(piece.get("title")),
                "resource_id": _text(piece.get("resource_id"), 64),
            })
    return {
        "attention_id": attention_id,
        "category": category,
        "band": band if band in _ATTENTION_BANDS else BAND_MODERATE,
        "claim_id": _text(fields.get("claim_id"), 64),
        "topic_id": _text(fields.get("topic_id"), 64),
        "source_count": _count(fields.get("source_count"), len(evidence)),
        "evidence": evidence,
    }


def _count(value: object, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return fallback
    return min(value, MAX_ATTENTION_EVIDENCE)


def _attention_detail(attention: dict[str, Any]) -> str:
    """La seconde ligne de l'avertissement, composée de nombres et de mots fixes.

    Elle ne peut transporter aucune parole de la salle : ses deux ingrédients
    sont un compte et une bande, et la bande a déjà été ramenée dans la table.
    """

    count = int(attention.get("source_count") or 0)
    sources = f"{count} source{'s' if count > 1 else ''}" if count else "aucune source citée"
    return f"{sources} · {_ATTENTION_BAND_WORDS.get(str(attention.get('band')), '')}".strip(" ·")


def _classify(kind: str, data: dict[str, Any]) -> str | None:
    """Catégorie d'un événement du journal, ou None s'il n'est pas à signaler.

    Volontairement une table de correspondance et non une heuristique : ce qui
    mérite l'attention de l'utilisateur est une décision de conception, pas une
    déduction sur un nom de canal.
    """

    if kind == "agent.subagent.finished":
        status = str(data.get("status") or "")
        return FAILED if status in _FAILED_TASK_STATUSES else DONE
    if kind in ("agent.unsolicited_failed", "core.brain.turn_failed", "agent.work_state_failed"):
        return FAILED
    if kind == "voice.speech.error_withheld":
        # Une erreur rédigée que l'ordonnanceur n'a pas prononcée : c'est
        # précisément le trou qu'on ne veut plus jamais laisser muet.
        return FAILED
    if kind == "voice.speech.abandoned":
        # Une réponse complète rédigée puis retirée sans avoir été dite. Le
        # retrait est légitime — c'est le cerveau qui l'a décidé — mais
        # l'utilisateur doit pouvoir constater qu'une réponse existait.
        return ATTENTION
    if kind == ATTENTION_RAISED_KIND:
        # Slice 09 : une contradiction vérifiée. Elle arrive déjà jugée — la
        # porte est `decide_attention`, côté Core — et ce registre ne fait que
        # la compter et la rendre lisible. Il ne rejuge rien, et surtout il ne
        # peut rien faire dire à personne : D11 tient plus haut.
        return ATTENTION
    if kind in ("core.brain.woken_by_work", "core.brain.notice_dropped"):
        return ATTENTION
    if kind == SPEECH_WITHHELD_KIND:
        # Slice 07 : un Board inactif avait quelque chose à dire et la porte de
        # Core l'a retenu. Jamais dit à voix haute — c'est tout l'objet de la
        # porte — donc à rendre visible ici, attribué à son Board.
        return ATTENTION
    if kind == "core.work.attention":
        return ATTENTION if data.get("status") == "blocked" else None
    if kind in ("agent.unsolicited_result", "core.brain.notice_relayed"):
        # Un relais effectivement dit n'a pas besoin du badge : l'utilisateur
        # l'a entendu. Seul un relais resté silencieux se signale.
        return None if data.get("spoken") is not False else SAID
    return None


@dataclass(slots=True)
class BackgroundEvent:
    seq: int
    ts: str
    category: str
    kind: str
    label: str
    detail: str
    #: Sous-tâche concernée, quand la trace la nomme : l'interface s'en sert
    #: pour ouvrir directement sa carte dans le panneau Agents.
    task_id: str = ""
    #: Vu individuellement (acquittement par catégorie), en plus du curseur.
    seen: bool = False
    #: Charge utile typée d'un point d'attention de Presentation (Slice 09) :
    #: catégorie, gravité, bande de confiance, pièces. Absente pour tout le
    #: reste. C'est elle qui permet à l'avertissement flottant de montrer des
    #: preuves sans qu'aucune parole de la salle n'ait eu à traverser.
    attention: dict[str, Any] | None = None
    #: Board source (Slice 07), lu dans la trace ; vide quand elle n'en nomme
    #: aucun (événement d'avant les Boards, processus voix).
    board_id: str = ""
    #: Titre du Board pour l'affichage, résolu par le Control Center
    #: (`retitle`) et gardé avec l'entrée : Core arrêté, l'alerte persistée
    #: sait encore d'où elle vient.
    board_title: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload = {"seq": self.seq, "ts": self.ts, "category": self.category,
                   "kind": self.kind, "label": self.label, "detail": self.detail,
                   "task_id": self.task_id, "board_id": self.board_id or None,
                   "board_title": self.board_title or None}
        if self.attention is not None:
            payload["attention"] = self.attention
        return payload

    def to_record(self) -> dict[str, Any]:
        """Forme persistée : la charge utile plus l'état « vu » individuel."""

        return {**self.to_payload(), "seen": self.seen}

    @classmethod
    def from_record(cls, record: object) -> "BackgroundEvent | None":
        """Relire une entrée persistée ; `None` si elle est hors contrat.

        Le fichier peut avoir été édité ou tronqué : rien n'y est cru, chaque
        champ est retaillé comme ceux de la trace.
        """

        if not isinstance(record, dict):
            return None
        seq = record.get("seq")
        category = record.get("category")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1 or category not in CATEGORIES:
            return None
        attention = record.get("attention")
        return cls(
            seq=seq,
            ts=_text(record.get("ts"), 64),
            category=str(category),
            kind=_text(record.get("kind"), MAX_LABEL),
            label=_text(record.get("label"), MAX_LABEL),
            detail=_text(record.get("detail"), MAX_LABEL),
            task_id=_text(record.get("task_id"), MAX_LABEL),
            seen=record.get("seen") is True,
            attention=_attention_payload(attention) if isinstance(attention, dict) else None,
            board_id=_board_id(record.get("board_id")),
            board_title=_text(record.get("board_title"), MAX_BOARD_TITLE),
        )


def _board_id(value: object) -> str:
    """Un identifiant de Board recopié de la trace : chaîne bornée, sinon vide."""

    return value[:MAX_BOARD_ID] if isinstance(value, str) else ""


def _detail(kind: str, fields: dict[str, Any], attention: dict[str, Any] | None) -> str:
    if attention is not None:
        return _attention_detail(attention)
    if kind == SPEECH_WITHHELD_KIND:
        origin = str(fields.get("origin") or "")
        return _WITHHELD_ORIGINS.get(origin, origin)
    return str(fields.get("description") or fields.get("error_class")
               or fields.get("reason") or fields.get("status") or "")


@dataclass(slots=True)
class BackgroundEventLedger:
    """Ce qui s'est passé derrière, compté jusqu'à ce qu'on l'ait vu."""

    entries: list[BackgroundEvent] = field(default_factory=list)
    seq: int = 0
    acknowledged: int = 0
    #: Entrées persistées écartées à la relecture (hors contrat) : dit, jamais tu.
    dropped_entries: int = 0

    def observe(self, kind: str, message: str, *, level: str = "info",
                data: dict[str, Any] | None = None, ts: str = "",
                resolve_board: Callable[[str], str | None] | None = None) -> BackgroundEvent | None:
        """Classer un événement du journal ; rend l'entrée retenue, s'il y en a une.

        Board source : le `board_id` de la ligne ; à défaut, `resolve_board`
        appliqué à sa `conversation_id` (liaisons connues de l'appelant).
        """

        fields = dict(data or {})
        category = _classify(kind, fields)
        if category is None:
            return None
        self.seq += 1
        attention = _attention_payload(fields) if kind == ATTENTION_RAISED_KIND else None
        board_id = _board_id(fields.get("board_id"))
        conversation_id = fields.get("conversation_id")
        if not board_id and resolve_board is not None and isinstance(conversation_id, str) and conversation_id:
            board_id = _board_id(resolve_board(conversation_id))
        entry = BackgroundEvent(
            seq=self.seq,
            ts=ts,
            category=category,
            kind=kind,
            label=(message or kind)[:MAX_LABEL],
            detail=_detail(kind, fields, attention)[:MAX_LABEL],
            task_id=str(fields.get("task_id") or "")[:MAX_LABEL],
            attention=attention,
            board_id=board_id,
        )
        self.entries.append(entry)
        del self.entries[:-MAX_ENTRIES]
        # Une entrée évincée par la borne ne doit pas rester comptée comme non
        # vue : sans cela le badge afficherait un reste qu'on ne peut plus lire.
        oldest = self.entries[0].seq - 1 if self.entries else self.seq
        self.acknowledged = max(self.acknowledged, oldest)
        return entry

    def is_unread(self, entry: BackgroundEvent) -> bool:
        return entry.seq > self.acknowledged and not entry.seen

    @property
    def unread(self) -> int:
        return sum(1 for entry in self.entries if self.is_unread(entry))

    def counts(self) -> dict[str, int]:
        """Non-vus par catégorie ; seules les catégories présentes figurent."""

        tally = {category: 0 for category in CATEGORIES}
        for entry in self.entries:
            if self.is_unread(entry):
                tally[entry.category] += 1
        return {category: count for category, count in tally.items() if count}

    def acknowledge(self, seq: int | None = None, category: str | None = None) -> int:
        """Marquer vu jusqu'à `seq` (tout, par défaut) ; rend le nouveau curseur.

        Un `seq` plus ancien que le curseur ne rembobine rien : deux onglets ne
        doivent pas se renvoyer le badge l'un à l'autre.

        Avec `category`, seules les entrées de cette catégorie sont marquées :
        chaque pastille de l'interface principale s'acquitte seule, sans
        effacer un échec en passant quand on regarde les tâches terminées.
        Le curseur, lui, ne bouge pas.
        """

        target = self.seq if seq is None else int(seq)
        if category is None:
            self.acknowledged = max(self.acknowledged, min(target, self.seq))
            return self.acknowledged
        if category not in CATEGORIES:
            raise ValueError(f"catégorie inconnue : {category}")
        for entry in self.entries:
            if entry.category == category and entry.seq <= target:
                entry.seen = True
        return self.acknowledged

    def attention_digest(self, *, limit: int = MAX_ATTENTION_DIGEST) -> list[dict[str, Any]]:
        """Les points d'attention **non vus**, du plus récent au plus ancien.

        Sert l'avertissement flottant depuis `GET /api/status`, que la page
        sonde déjà une fois par seconde : la surface n'ouvre donc aucun second
        battement, ce que l'absence de couture générique dans cette page (G6)
        rendrait de toute façon coûteux.

        Borné court et volontairement : un avertissement discret montre ce qui
        vient d'arriver, pas un historique. Le reste est dans la pastille, puis
        dans `GET /api/background`.
        """

        bound = max(1, min(int(limit), MAX_ATTENTION_DIGEST))
        out: list[dict[str, Any]] = []
        for entry in reversed(self.entries):
            if entry.attention is None or not self.is_unread(entry):
                continue
            out.append({"seq": entry.seq, "ts": entry.ts, "label": entry.label,
                        "detail": entry.detail, "attention": entry.attention})
            if len(out) >= bound:
                break
        return out

    def retitle(self, titles: dict[str, str]) -> set[str]:
        """Donner à chaque entrée attribuée le titre courant de son Board.

        Un Board renommé est relu sous son nouveau nom ; un Board absent de
        `titles` garde le titre déjà retenu. Rend les `board_id` encore sans
        titre, pour que l'appelant sache s'il doit relire la liste.
        """

        missing: set[str] = set()
        for entry in self.entries:
            if not entry.board_id:
                continue
            title = titles.get(entry.board_id)
            if title:
                entry.board_title = str(title)[:MAX_BOARD_TITLE]
            elif not entry.board_title:
                missing.add(entry.board_id)
        return missing

    def sources(self) -> list[dict[str, Any]]:
        """Non-vus par Board source : `[{board_id, title, counts}]`, plus récent d'abord.

        Sert les pastilles (`/api/status`) : elles disent d'un coup d'œil
        qu'une alerte vient d'un autre Board que celui qu'on regarde.
        """

        rows: dict[str, dict[str, Any]] = {}
        for entry in reversed(self.entries):
            if not entry.board_id or not self.is_unread(entry):
                continue
            row = rows.setdefault(entry.board_id, {"board_id": entry.board_id,
                                                   "title": entry.board_title or None, "counts": {}})
            row["counts"][entry.category] = row["counts"].get(entry.category, 0) + 1
        return list(rows.values())

    def to_record(self) -> dict[str, Any]:
        return {"seq": self.seq, "acknowledged": self.acknowledged,
                "entries": [entry.to_record() for entry in self.entries[-MAX_ENTRIES:]]}

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "BackgroundEventLedger":
        """Relire un registre persisté. Lève `ValueError` si l'en-tête est hors contrat.

        Une entrée isolée illisible est écartée (comptée dans
        `dropped_entries`) ; un en-tête illisible rend tout le fichier suspect.
        """

        seq, acknowledged, raw = record.get("seq"), record.get("acknowledged"), record.get("entries")
        for name, value in (("seq", seq), ("acknowledged", acknowledged)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} hors contrat : {value!r}")
        if not isinstance(raw, list):
            raise ValueError("entries n'est pas une liste")
        kept = raw[-MAX_ENTRIES:]
        entries = [entry for entry in (BackgroundEvent.from_record(item) for item in kept)
                   if entry is not None and entry.seq <= seq]
        entries.sort(key=lambda entry: entry.seq)
        ledger = cls(entries=entries, seq=seq, acknowledged=min(acknowledged, seq))
        ledger.dropped_entries = len(kept) - len(entries)
        return ledger

    def to_payload(self, *, limit: int = MAX_ENTRIES) -> dict[str, Any]:
        recent: Iterable[BackgroundEvent] = self.entries[-max(1, min(limit, MAX_ENTRIES)):]
        return {
            "seq": self.seq,
            "acknowledged": self.acknowledged,
            "unread": self.unread,
            "counts": self.counts(),
            "events": [{**entry.to_payload(), "unread": self.is_unread(entry)}
                       for entry in reversed(list(recent))],
        }


#: Octets lus au plus par passage. Un démarrage sur une trace déjà grosse, ou
#: une rafale, ne doit pas bloquer la boucle de l'interface.
MAX_READ_BYTES = 1 << 20


@dataclass(slots=True)
class TraceFollower:
    """Lecteur incrémental de `trace.jsonl`, tolérant à tout ce qu'un fichier fait.

    Le premier passage ne rejoue rien : il se positionne à la fin. Sans cela,
    ouvrir le Control Center signalerait d'un coup des centaines d'événements
    vieux de plusieurs jours.

    Une trace repartie de zéro (fichier tronqué, ou remplacé au redémarrage)
    est détectée de deux façons. La taille ne suffit pas : tronquée puis
    regrossie au-delà du curseur entre deux passages, la lecture repartirait au
    milieu d'une ligne et perdrait des entrées sans le dire. On vérifie donc
    aussi la **continuité** — l'octet qui précède le curseur doit être un saut
    de ligne — et on resynchronise depuis le début quand il ne l'est pas.

    Une ligne incomplète — le producteur écrit pendant qu'on lit — n'est pas
    consommée : le curseur s'arrête au dernier saut de ligne.

    **Reprise** (Slice 07). Un curseur relu de `background-events.json`
    (`resume`) reprend là où le Control Center s'était arrêté : ce qui a été
    écrit pendant son absence est lu, par tranches de `MAX_READ_BYTES`. Il
    porte l'empreinte de la **première ligne** du fichier qu'il lisait
    (`head`) : une trace remplacée pendant l'absence (supprimée, tournée,
    tronquée puis regrossie) a une autre première ligne, et se relit depuis le
    début au lieu d'être lue à une position qui n'est plus la sienne.
    `resets` compte ces reprises depuis zéro.
    """

    path: Path
    offset: int = -1
    #: Empreinte (sha1) de la première ligne complète du fichier suivi, `""`
    #: tant qu'elle n'est pas connue.
    head: str = ""
    #: Vérifier `head` au prochain passage (curseur relu d'un fichier).
    verify_head: bool = False
    resets: int = 0

    def resume(self, offset: int, head: str) -> None:
        """Reprendre à une position persistée ; vérifiée au prochain `poll`."""

        self.offset = max(0, int(offset))
        self.head = head
        self.verify_head = True

    def _restart(self) -> None:
        self.offset = 0
        self.head = ""
        self.resets += 1

    def poll(self) -> list[dict[str, Any]]:
        """Entrées apparues depuis le dernier appel, au plus `MAX_READ_BYTES`."""

        try:
            size = self.path.stat().st_size
        except OSError:
            # Pas de trace : rien à lire, et rien à ignorer non plus. Le
            # curseur se fixe à zéro pour que le fichier, quand il paraîtra,
            # soit lu en entier — il aura été écrit après le début du suivi.
            # Le laisser à -1 aurait fait « sauter à la fin » d'un fichier déjà
            # rempli entre-temps, et perdre silencieusement son contenu.
            if self.offset < 0:
                self.offset = 0
            if self.verify_head and self.offset > 0:
                self._restart()  # Trace disparue pendant l'absence.
            self.verify_head = False
            return []
        if self.offset < 0:
            self.offset = size
            self.head = _head_of(self.path)
            return []
        if self.verify_head:
            self.verify_head = False
            if self.offset > 0 and self.head != _head_of(self.path):
                self._restart()  # Ce n'est plus le fichier qu'on lisait.
        if size < self.offset:
            self._restart()  # Trace repartie de zéro.
        if size == self.offset:
            return []
        try:
            with self.path.open("rb") as handle:
                if self.offset > 0:
                    handle.seek(self.offset - 1)
                    if handle.read(1) != b"\n":
                        # Le fichier n'est plus celui qu'on lisait : resynchroniser.
                        self._restart()
                        handle.seek(0)
                else:
                    handle.seek(0)
                chunk = handle.read(MAX_READ_BYTES)
        except OSError:
            return []
        cut = chunk.rfind(b"\n")
        if cut < 0:
            # Aucune ligne complète : ne rien consommer, réessayer plus tard.
            # Sauf si le morceau remplit déjà le budget, auquel cas la ligne ne
            # tiendra jamais et l'avancer est le seul moyen de ne pas coincer.
            if len(chunk) >= MAX_READ_BYTES:
                self.offset += len(chunk)
            return []
        self.offset += cut + 1
        if not self.head:
            self.head = _head_of(self.path)
        return list(_decode(chunk[:cut]))


#: Octets lus au plus pour trouver la première ligne d'une trace.
HEAD_BYTES = 4096


def _head_of(path: Path) -> str:
    """Empreinte de la première ligne complète de `path`, `""` si aucune (ou illisible).

    Une trace commence par une ligne horodatée : deux fichiers distincts n'ont
    pas la même. Une première ligne plus longue que `HEAD_BYTES` est prise
    telle quelle sur ses `HEAD_BYTES` premiers octets.
    """

    try:
        with path.open("rb") as handle:
            raw = handle.read(HEAD_BYTES)
    except OSError:
        return ""  # intentional: absent or locked; "" means unknown, never a match
    cut = raw.find(b"\n")
    if cut < 0 and len(raw) < HEAD_BYTES:
        return ""
    return hashlib.sha1(raw[:cut] if cut >= 0 else raw).hexdigest()


def _decode(raw: bytes) -> Iterator[dict[str, Any]]:
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line.decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(payload, dict):
            yield payload


def follow(ledger: BackgroundEventLedger, follower: TraceFollower,
           resolve_board: Callable[[str], str | None] | None = None) -> int:
    """Verser dans le registre ce que la trace a produit depuis le dernier appel.

    Rend le nombre d'entrées retenues. Une entrée illisible ou hors table est
    ignorée sans bruit : le registre signale du travail, pas la santé du
    fichier de trace. `resolve_board` : voir `BackgroundEventLedger.observe`.
    """

    kept = 0
    for payload in follower.poll():
        data = payload.get("data")
        entry = ledger.observe(
            str(payload.get("kind") or ""),
            str(payload.get("message") or ""),
            level=str(payload.get("level") or "info"),
            data=data if isinstance(data, dict) else {},
            ts=str(payload.get("ts") or ""),
            resolve_board=resolve_board,
        )
        kept += entry is not None
    return kept


# ------------------------------------------------------------------ persistance

#: Nom du fichier, sous le dossier runtime du Control Center.
STORE_FILE = "background-events.json"
#: Version du format. Une autre version est traitée comme un fichier illisible.
STORE_VERSION = 1


@dataclass(slots=True)
class StoreLoad:
    """Ce que `BackgroundEventStore.load` a relu, et ce qu'il faut en dire."""

    ledger: BackgroundEventLedger
    follower: TraceFollower
    #: `None`, ou la phrase à montrer : fichier illisible écarté, entrées perdues.
    warning: str | None = None
    #: Où le fichier illisible a été mis de côté, pour l'examen.
    quarantined: Path | None = None
    resumed: bool = False


@dataclass(slots=True)
class BackgroundEventStore:
    """`runtime/background-events.json` : registre, curseur d'acquittement, position dans la trace.

    Format (version 1) :

    ```json
    {"version": 1,
     "ledger": {"seq": 12, "acknowledged": 9, "entries": [<BackgroundEvent.to_record>, ...]},
     "trace": {"offset": 48213, "head": "<sha1 de la première ligne>"}}
    ```

    Borné à `MAX_ENTRIES` entrées. Écriture atomique (fichier temporaire du
    même dossier puis `os.replace`) : un arrêt brutal laisse l'ancien fichier
    ou le nouveau, jamais un mélange. Un fichier illisible n'empêche pas le
    Control Center de démarrer : il est mis de côté
    (`background-events.corrupt.json`), le registre repart vide, et `load`
    rend la phrase à afficher.
    """

    path: Path
    trace_path: Path

    @property
    def quarantine_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".corrupt" + self.path.suffix)

    def load(self) -> StoreLoad:
        """Relire l'état persisté. Ne lève pas."""

        fresh = StoreLoad(BackgroundEventLedger(), TraceFollower(self.trace_path))
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return fresh  # intentional: first run, nothing persisted yet
        except OSError as exc:
            fresh.warning = (f"Notifications d’arrière-plan non relues ({type(exc).__name__}: {exc}) : "
                             "les alertes non lues d’avant le redémarrage ne sont pas affichées.")
            return fresh
        try:
            record = json.loads(raw.decode("utf-8"))
            if not isinstance(record, dict) or record.get("version") != STORE_VERSION:
                raise ValueError(f"version hors contrat : {record.get('version') if isinstance(record, dict) else type(record).__name__}")
            ledger_record, trace = record.get("ledger"), record.get("trace")
            if not isinstance(ledger_record, dict) or not isinstance(trace, dict):
                raise ValueError("ledger ou trace absent")
            ledger = BackgroundEventLedger.from_record(ledger_record)
            offset, head = trace.get("offset"), trace.get("head")
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or not isinstance(head, str):
                raise ValueError(f"position de trace hors contrat : {offset!r}")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            fresh.quarantined = self._quarantine()
            aside = f" Copie mise de côté : {fresh.quarantined.name}." if fresh.quarantined else ""
            fresh.warning = (f"Fichier des notifications d’arrière-plan illisible ({type(exc).__name__}: "
                             f"{str(exc)[:160]}) : repris à vide, les alertes non lues d’avant sont perdues.{aside}")
            return fresh
        follower = TraceFollower(self.trace_path)
        follower.resume(offset, head)
        loaded = StoreLoad(ledger, follower, resumed=True)
        if ledger.dropped_entries:
            loaded.warning = (f"{ledger.dropped_entries} notification(s) d’arrière-plan illisible(s) "
                              "écartée(s) à la relecture.")
        return loaded

    def _quarantine(self) -> Path | None:
        target = self.quarantine_path
        try:
            os.replace(self.path, target)
        except OSError:
            return None  # intentional: the warning already says the file was unreadable; the next save overwrites it
        return target

    def save(self, ledger: BackgroundEventLedger, follower: TraceFollower) -> None:
        """Écrire l'état, atomiquement. Lève `OSError` : l'appelant le dit."""

        record = {"version": STORE_VERSION, "ledger": ledger.to_record(),
                  "trace": {"offset": max(0, follower.offset), "head": follower.head}}
        data = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
