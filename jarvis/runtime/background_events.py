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
Il ne parle pas, ne déclenche aucun travail, ne persiste rien et ne juge pas :
il classe par catégorie et compte ce qui n'a pas été vu. Il n'est pas non plus
la source de vérité de l'état du travail — c'est `WorkStateStore` — seulement
la trace de ce qui *vient d'arriver*, pour qu'un coup d'œil suffise.

Pureté
------
`BackgroundEventLedger` ne fait aucune entrée-sortie et n'a aucune horloge
implicite : l'appelant fournit l'horodatage. Toute la lecture de fichier est
isolée dans `TraceFollower`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

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

    def to_payload(self) -> dict[str, Any]:
        payload = {"seq": self.seq, "ts": self.ts, "category": self.category,
                   "kind": self.kind, "label": self.label, "detail": self.detail,
                   "task_id": self.task_id}
        if self.attention is not None:
            payload["attention"] = self.attention
        return payload


@dataclass(slots=True)
class BackgroundEventLedger:
    """Ce qui s'est passé derrière, compté jusqu'à ce qu'on l'ait vu."""

    entries: list[BackgroundEvent] = field(default_factory=list)
    seq: int = 0
    acknowledged: int = 0

    def observe(self, kind: str, message: str, *, level: str = "info",
                data: dict[str, Any] | None = None, ts: str = "") -> BackgroundEvent | None:
        """Classer un événement du journal ; rend l'entrée retenue, s'il y en a une."""

        fields = dict(data or {})
        category = _classify(kind, fields)
        if category is None:
            return None
        self.seq += 1
        attention = _attention_payload(fields) if kind == ATTENTION_RAISED_KIND else None
        entry = BackgroundEvent(
            seq=self.seq,
            ts=ts,
            category=category,
            kind=kind,
            label=(message or kind)[:MAX_LABEL],
            detail=(_attention_detail(attention) if attention is not None else
                    str(fields.get("description") or fields.get("error_class")
                        or fields.get("reason") or fields.get("status") or ""))[:MAX_LABEL],
            task_id=str(fields.get("task_id") or "")[:MAX_LABEL],
            attention=attention,
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
    """

    path: Path
    offset: int = -1

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
            return []
        if self.offset < 0:
            self.offset = size
            return []
        if size < self.offset:
            self.offset = 0  # Trace repartie de zéro.
        if size == self.offset:
            return []
        try:
            with self.path.open("rb") as handle:
                if self.offset > 0:
                    handle.seek(self.offset - 1)
                    if handle.read(1) != b"\n":
                        # Le fichier n'est plus celui qu'on lisait : resynchroniser.
                        self.offset = 0
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
        return list(_decode(chunk[:cut]))


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


def follow(ledger: BackgroundEventLedger, follower: TraceFollower) -> int:
    """Verser dans le registre ce que la trace a produit depuis le dernier appel.

    Rend le nombre d'entrées retenues. Une entrée illisible ou hors table est
    ignorée sans bruit : le registre signale du travail, pas la santé du
    fichier de trace.
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
        )
        kept += entry is not None
    return kept
