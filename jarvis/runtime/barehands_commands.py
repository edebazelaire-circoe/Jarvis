"""Courtier des commandes Bare Hands venues du cerveau (handoff jarvis-bare-hands-v1, Slice 12).

Séquence, calquée sur `jarvis/core/scene_capture.py` (le seul précédent du dépôt
pour « le cerveau demande quelque chose à la page visible ») :

1. le cerveau appelle un outil du serveur MCP `jarvis-barehands`, qui poste
   `POST /api/barehands/commands` ; `request()` crée **une** commande en attente
   (identifiant aléatoire à usage unique, échéance `COMMAND_DEADLINE_S`) et
   réveille le long-poll de la page ;
2. la réponse du long-poll (`GET /api/barehands/commands?wait_s=…`) porte
   `command {id, name, remaining_ms}` ; la page appelle **le point d'entrée que
   le bouton appelle** et poste son reçu (`POST /api/barehands/commands/<id>`) ;
3. `complete()` valide l'identifiant (en attente, non échu) et le reçu, puis rend
   la main à l'appel du cerveau, avec l'issue **que la page a constatée**.

**Une commande, une page.** La remise est exclusive : le premier long-poll qui
la demande l'emporte, les autres ne la voient pas. Deux issues d'échéance, et
elles ne disent pas la même chose — `deliveries` est ce qui les sépare :
personne n'a pris la commande (`deliveries: 0`) est `barehands_no_visible_page` ;
une page l'a prise et n'a pas rendu son reçu (`deliveries: 1`) est
`barehands_command_expired`. Une seconde commande pendant qu'une autre attend :
`barehands_command_busy`.

**Pourquoi le courtier vit ici et non dans Core.** Bare Hands n'existe nulle part
dans Core : ni l'interrupteur, ni les réglages, ni la page qui le fait tourner.
Le Control Center sert la page, tient `barehands_test_mode` et porte déjà
`GET`/`POST /api/barehands`. Faire voyager la commande par Core aurait demandé
des routes `/v1/…`, un client protocolaire et un relais, pour trois sauts de plus
et zéro propriétaire de plus.

**Porte.** Le courtier relit l'interrupteur à chaque demande (`gate`). Éteint,
la commande est refusée (`barehands_disabled`) **avant** toute attente : la page
ne poste pas de long-poll quand Bare Hands est éteint, donc attendre trois
secondes pour conclure « personne » mentirait sur la cause.

Le journal ne porte que des identifiants courts, des noms de commande, des
durées et des codes — jamais de contenu de page ni de parole de l'utilisateur.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import secrets
from typing import Any

from jarvis.domain.barehands_command import (
    COMMAND_BUSY,
    COMMAND_CANCELLED,
    COMMAND_DEADLINE_S,
    COMMAND_DISABLED,
    COMMAND_EXPIRED,
    NO_VISIBLE_PAGE,
    UNKNOWN_COMMAND_ID,
    BarehandsCommandError,
    check_command_id,
    short_id,
)
from jarvis.runtime.journal import RuntimeJournal


@dataclass(slots=True)
class _Pending:
    command_id: str
    name: str
    created: float
    deadline: float
    result: asyncio.Future
    #: **Remise exclusive** : un long-poll l'a emportée, et plus aucun autre ne
    #: la recevra. Ce n'est pas une limite de cadence, c'est une exclusion.
    delivered: bool = False
    deliveries: int = 0
    #: Un reçu valide a pris l'identifiant (posé avant toute attente) : usage unique atomique.
    consumed: bool = False


class BarehandsCommandBroker:
    """Une commande en vol à la fois, bornée dans le temps, rendue à la page visible."""

    def __init__(
        self,
        *,
        journal: RuntimeJournal | None = None,
        gate: Callable[[], bool] | None = None,
        deadline_s: float = COMMAND_DEADLINE_S,
    ) -> None:
        self.journal = journal
        #: Lecture de `barehands_test_mode.enabled`. `None` : porte absente, le
        #: courtier ne devine pas et laisse passer (usage de test uniquement).
        self.gate = gate
        self.deadline_s = deadline_s
        self._pending: _Pending | None = None
        self._wake: asyncio.Event | None = None
        self._closed = False

    # ------------------------------------------------------------ cycle de vie

    def close(self) -> None:
        """Arrêt du Control Center : la commande en attente échoue aussitôt."""

        self._closed = True
        pending, self._pending = self._pending, None
        if pending is not None and not pending.result.done():
            pending.result.set_exception(
                BarehandsCommandError(COMMAND_CANCELLED, "Le Control Center s'arrête : commande abandonnée.", 503,
                                      short_id(pending.command_id))
            )
        self._set_wake()

    def enabled(self) -> bool:
        """L'interrupteur Bare Hands, relu maintenant."""

        if self.gate is None:
            return True
        return bool(self.gate())

    # ------------------------------------------------------------ demande du cerveau

    async def request(self, name: str) -> dict[str, Any]:
        """Créer la commande et attendre le reçu de la page, au plus `deadline_s`.

        Rend le reçu validé, augmenté de `command`, `deliveries` et `duration_ms`.
        Lève `BarehandsCommandError` sur tout refus : jamais un succès par défaut.
        """

        if self._closed:
            raise BarehandsCommandError(COMMAND_CANCELLED, "Le Control Center s'arrête.", 503)
        if not self.enabled():
            self._emit("barehands.command_disabled", f"commande {name} refusée : Bare Hands est éteint",
                       level="warning", data={"code": COMMAND_DISABLED, "command": name})
            raise BarehandsCommandError(
                COMMAND_DISABLED,
                "Bare Hands est éteint : l'utilisateur doit l'allumer dans l'onglet Expérimental "
                "du Control Center avant que la voix puisse le piloter.",
                409,
            )
        if self._pending is not None:
            self._emit("barehands.command_busy", f"commande {name} refusée : une autre est en cours",
                       level="warning", data={"code": COMMAND_BUSY, "command": name,
                                              "pending": short_id(self._pending.command_id),
                                              "pending_command": self._pending.name})
            raise BarehandsCommandError(
                COMMAND_BUSY, "Une commande Bare Hands est déjà en cours : réessaie dans une seconde.", 409
            )
        loop = asyncio.get_running_loop()
        now = loop.time()
        pending = _Pending(secrets.token_urlsafe(24), name, now, now + self.deadline_s, loop.create_future())
        self._pending = pending
        self._emit("barehands.command_requested", f"commande Bare Hands demandée : {name}",
                   data={"command": name, "id": short_id(pending.command_id),
                         "deadline_ms": round(self.deadline_s * 1000), "source": "brain"})
        self._set_wake()
        try:
            receipt = await asyncio.wait_for(asyncio.shield(pending.result), timeout=self.deadline_s)
        except TimeoutError:
            waited = round((loop.time() - now) * 1000)
            # **Qui n'a pas répondu ?** `deliveries` le dit, et c'est la seule
            # chose qui le dise. Zéro : aucun long-poll n'a emporté la commande,
            # donc aucune page visible — la phrase sur la fenêtre est vraie.
            # Un : une page l'a prise et n'a pas rendu son reçu ; dire « aucune
            # page visible » enverrait l'utilisateur chercher une fenêtre qu'il
            # a sous les yeux, souvent avec l'invite caméra ouverte dedans.
            took = pending.deliveries > 0
            code = COMMAND_EXPIRED if took else NO_VISIBLE_PAGE
            self._emit(
                "barehands.command_expired",
                f"commande {name} échue : "
                + ("la page l'a prise et n'a pas répondu" if took else "aucune page visible n'a répondu"),
                level="warning", data={"code": code, "command": name, "id": short_id(pending.command_id),
                                       "deliveries": pending.deliveries, "waited_ms": waited})
            raise BarehandsCommandError(
                code,
                (
                    f"La page du Control Center a bien pris la commande mais n'a pas répondu en "
                    f"{self.deadline_s:g} s : elle est peut-être bloquée sur l'autorisation caméra du "
                    "navigateur. L'issue est inconnue — ne dis ni que c'est fait, ni que ça a échoué : "
                    "demande à l'utilisateur de regarder la fenêtre du Control Center."
                    if took else
                    f"Aucune page visible du Control Center n'a pris la commande en {self.deadline_s:g} s "
                    "(fenêtre fermée, onglet caché, ou page pas encore chargée)."
                ),
                504,
                short_id(pending.command_id),
            ) from None
        except asyncio.CancelledError:
            if not pending.result.done():
                self._emit("barehands.command_abandoned", f"commande {name} abandonnée par l'appelant",
                           level="warning", data={"code": COMMAND_CANCELLED, "command": name,
                                                  "id": short_id(pending.command_id),
                                                  "deliveries": pending.deliveries})
            raise
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.result.done():
                pending.result.cancel()
        duration_ms = round((loop.time() - pending.created) * 1000)
        # `id` : l'identifiant **court**, celui que porte chaque ligne du
        # journal. C'est ce qui permet au serveur MCP de relier son `barehands.tool`
        # aux lignes du courtier autrement que par adjacence de dates.
        answer = {**receipt, "command": name, "id": short_id(pending.command_id),
                  "deliveries": pending.deliveries, "duration_ms": duration_ms}
        if receipt["outcome"] == "refused":
            self._emit("barehands.command_refused", f"commande {name} refusée par la page : {receipt['code']}",
                       level="warning", data={"code": receipt["code"], "command": name,
                                              "id": short_id(pending.command_id), "lifecycle": receipt["lifecycle"],
                                              "reason": receipt["reason"], "duration_ms": duration_ms,
                                              "deliveries": pending.deliveries})
        else:
            self._emit("barehands.command_applied", f"commande {name} {receipt['outcome']} par la page",
                       data={"command": name, "id": short_id(pending.command_id), "outcome": receipt["outcome"],
                             "lifecycle": receipt["lifecycle"], "duration_ms": duration_ms,
                             "deliveries": pending.deliveries})
        return answer

    # ------------------------------------------------------------ long-poll

    def wake_event(self) -> asyncio.Event:
        """Événement levé à la prochaine commande (ou à l'arrêt) ; à prendre avant `deliver()`."""

        if self._wake is None:
            self._wake = asyncio.Event()
        return self._wake

    def _set_wake(self) -> None:
        if self._wake is not None:
            self._wake.set()
        self._wake = None

    def deliver(self) -> dict[str, Any] | None:
        """La commande à joindre à une réponse de long-poll, ou `None`.

        **Remise une fois, à une seule page.** Le premier long-poll qui la
        demande l'emporte ; tout autre reçoit `None` et continue d'attendre,
        sans jamais voir la commande. C'est une exclusion, pas une limite de
        cadence — la nuance a un coût mesuré (QA de la Slice 12) : une fenêtre
        de redistribution d'une seconde sous une échéance de trois en donnait
        jusqu'à **trois** exemplaires, chaque onglet servi appelait le point
        d'entrée, et pour `tutorial`/`calibrate` deux parcours démarraient. Seul
        le premier reçu était accepté, donc le cerveau n'en voyait **qu'un** :
        le double départ n'apparaissait nulle part.

        Ce qui est perdu en échange : une remise qui n'arrive pas à destination
        (connexion coupée entre la réponse et la page) n'est plus rattrapée. Le
        cerveau l'apprend alors pour ce que c'est — `barehands_command_expired`
        avec `deliveries: 1`, « la page l'a prise et n'a pas répondu » — et une
        commande vocale se redemande en une phrase.
        """

        pending = self._pending
        # `consumed` reste testé ici, et ce n'est pas une redondance gratuite :
        # entre le reçu de la page et la reprise de l'appel du cerveau, la
        # commande est encore en place. Les deux gardes répondent à deux
        # questions différentes — « quelqu'un l'a-t-il emportée ? » et
        # « a-t-elle déjà été honorée ? » — et un test neutralise chacune pour
        # prouver que l'autre tient seule.
        if pending is None or pending.delivered or pending.consumed:
            return None
        now = asyncio.get_running_loop().time()
        if now >= pending.deadline:
            return None
        pending.delivered = True
        pending.deliveries += 1
        remaining = max(0, round((pending.deadline - now) * 1000))
        self._emit("barehands.command_delivered", f"commande {pending.name} remise à la page",
                   data={"command": pending.name, "id": short_id(pending.command_id),
                         "deliveries": pending.deliveries, "remaining_ms": remaining})
        return {"id": pending.command_id, "name": pending.name, "remaining_ms": remaining}

    # ------------------------------------------------------------ reçu de la page

    def complete(self, command_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Rendre le reçu de la page à l'appel du cerveau ; rend `{command, id}`.

        `receipt` a déjà traversé `parse_receipt` : la route refuse un reçu mal
        formé avant d'arriver ici, avec son propre code.
        """

        try:
            check_command_id(command_id)
        except BarehandsCommandError:
            # Même route, même classe d'attaque, même visibilité qu'un
            # identifiant bien formé mais inventé : sans cette ligne, un
            # identifiant hors forme repartait en 404 **sans rien laisser dans
            # la trace** (QA de la Slice 12), donc l'attaque la plus grossière
            # était la seule invisible. L'identifiant lui-même n'est pas
            # journalisé : il vient d'un inconnu, sa longueur suffit à la lire.
            self._emit("barehands.receipt_refused", "reçu refusé : identifiant hors forme",
                       level="warning", data={"code": UNKNOWN_COMMAND_ID, "id": None,
                                              "id_chars": len(command_id) if isinstance(command_id, str) else None})
            raise
        pending = self._pending
        if pending is None or pending.command_id != command_id or pending.consumed or pending.result.done():
            self._emit("barehands.receipt_refused", "reçu refusé : commande inconnue ou déjà rendue",
                       level="warning", data={"code": UNKNOWN_COMMAND_ID, "id": short_id(command_id)})
            raise BarehandsCommandError(
                UNKNOWN_COMMAND_ID, "Aucune commande en attente avec cet identifiant (inconnue, déjà rendue ou échue).",
                404, short_id(command_id)
            )
        # Course étroite, et **pas** le chemin du reçu tardif ordinaire : à
        # l'échéance, `request()` retire la commande de la place, si bien qu'un
        # reçu qui arrive après reçoit 404 plus haut. Cette branche ne se joue
        # que dans l'intervalle où l'échéance est passée et où le réveil de
        # `wait_for` n'a pas encore été ordonnancé. La garder est ce qui
        # empêche, là, d'accepter un reçu dont le cerveau n'entendra jamais
        # parler ; un test force l'échéance pour l'atteindre à coup sûr.
        if asyncio.get_running_loop().time() >= pending.deadline:
            self._emit("barehands.receipt_refused", f"reçu refusé : commande {pending.name} échue",
                       level="warning", data={"code": COMMAND_EXPIRED, "command": pending.name,
                                              "id": short_id(command_id)})
            raise BarehandsCommandError(COMMAND_EXPIRED, "Commande échue : trop tard.", 410, short_id(command_id))
        # Usage unique atomique : l'identifiant est pris avant toute reprise de
        # boucle ; un second reçu arrive ici après et reçoit `unknown_command`.
        pending.consumed = True
        if not pending.result.done():
            pending.result.set_result(receipt)
        return {"command": pending.name, "id": command_id}

    # ------------------------------------------------------------ outils

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except OSError:
            pass  # intentional: a full disk must not turn a command the page applied into a failure
