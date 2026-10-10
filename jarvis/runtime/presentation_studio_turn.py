"""L'origine d'un démarrage de lecture vient du tour réel, jamais d'un argument d'outil (jarvis-interactive-presentation-studio, Slice 21).

Condition d'entrée de la Slice 14 : Core accepte un démarrage `actor: brain` avec `origin: explicit_user_request` et il change alors le
mode d'interaction. Le serveur MCP `jarvis-presentation` ne l'écrit donc **jamais** de lui-même ni d'après un argument du modèle : un modèle
qui pourrait l'écrire changerait le mode de l'utilisateur sur la foi d'un texte lu dans un fichier.

Ce qui peut l'attester, c'est le Control Center : c'est lui qui sert chaque tour du cerveau (`agent_ask`) et qui voit le contexte que Core y
joint (`addressing`, `source`). Ce module ne tient qu'un compteur : **un tour de l'utilisateur, adressé, est-il en vol en ce moment ?**
Un tour que Core ouvre seul (`source: system`, réveil de travail de fond, rappel d'agenda), ou dont le contexte dit qu'il n'est pas adressé, ne
compte pas. Une demande sans contexte (panneau du navigateur, passerelle) est une saisie de l'utilisateur et compte.

`GET /api/presentation-studio/agent/turn` répond `{"ok": true, "addressed_user_turn": bool}`. Le préfixe `/api/presentation-studio` est gardé
(`READ_GUARDED_ROUTES`) : un cadre de prefab ne le lit pas. **Limite assumée** : l'attestation dit qu'un tour de l'utilisateur est en cours, pas que
la phrase demandait de présenter ; la consigne du cerveau (démarrer seulement sur demande explicite) et la confirmation de l'utilisateur au
besoin portent le reste. Rien du contenu du tour n'est lu ni gardé ici.
"""

from __future__ import annotations

from typing import Any, Mapping

from aiohttp import web

from jarvis.domain.v2 import AddressingDecision

TURN_ROUTE = "/api/presentation-studio/agent/turn"


def is_addressed_user_turn(context: object) -> bool:
    """Le contexte d'un tour (celui que Core joint) décrit-il un tour adressé de l'utilisateur ?"""

    if context is None:
        return True  # saisie directe (panneau, passerelle) : une demande de l'utilisateur
    if not isinstance(context, Mapping):
        return False
    if str(context.get("source") or "") == "system":
        return False
    return str(context.get("addressing") or AddressingDecision.ADDRESSED.value) == AddressingDecision.ADDRESSED.value


class AddressedTurnTracker:
    """Combien de tours adressés de l'utilisateur sont en vol (jamais leur contenu)."""

    def __init__(self) -> None:
        self._open = 0

    def begin(self, context: object) -> bool:
        """À appeler quand un tour part ; rend vrai s'il compte (à rendre à `end`)."""

        counted = is_addressed_user_turn(context)
        if counted:
            self._open += 1
        return counted

    def end(self, counted: bool) -> None:
        if counted and self._open > 0:
            self._open -= 1

    @property
    def addressed_user_turn(self) -> bool:
        return self._open > 0

    async def turn(self, request: web.Request) -> web.Response:
        del request
        return web.json_response({"ok": True, "addressed_user_turn": self.addressed_user_turn})

    def routes(self) -> list[Any]:
        return [web.get(TURN_ROUTE, self.turn)]


__all__ = ["AddressedTurnTracker", "TURN_ROUTE", "is_addressed_user_turn"]
