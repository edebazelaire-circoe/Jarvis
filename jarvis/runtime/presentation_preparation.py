"""L'exécutant réel d'une préparation spéculative de PRESENTATION.

Slice 11. C'est la réalisation de production du port
`SpeculativePreparationRunner` (Slice 08), qui n'en avait aucune — et c'est
l'endroit où la question laissée ouverte par la Slice 08 est répondue.

## La question du `--tools ""`, et sa réponse

`back_brain` porte déjà un profil d'exécution `speculative_analysis`, et il
lance le CLI avec `--tools ""` — **zéro outil**. C'est juste pour ce qu'il fait
(relire une transcription provisoire) et faux pour D07, qui demande une
recherche. La tentation était d'élargir ce profil-là. Elle est refusée pour
trois raisons, dont la troisième est décisive :

1. il a des consommateurs vivants — `back_brain_worker.py` le choisit pour tout
   job de portée `speculative_analysis`, et `live_delegation.py` emprunte ce
   chemin sur la voie DUPLEX avec une docstring qui dit, mot pour mot,
   *« speculative analysis, no tools »*. Élargir aurait changé leur
   comportement sans qu'ils le demandent ;
2. sa **consigne** interdit explicitement les outils
   (`SPECULATIVE_SYSTEM_PROMPT` : *« do not [...] retrieve external data,
   invoke tools »*), donc un élargissement aurait donné des outils à un modèle
   à qui on dit de ne pas s'en servir ;
3. ce chemin-là est **durable** : un job `speculative_analysis` descend dans
   la table SQLite du back brain et survit au redémarrage. D13 l'interdit à
   une préparation de Presentation.

D'où un **quatrième profil**, `presentation_preparation`, qui garde tout le
durcissement du profil restreint (`--restricted --strict-mcp-config
--safe-mode --no-chrome --disable-slash-commands --permission-prompts none
--no-session-persistence`, aucun hook d'aiguillage, aucun MCP, aucune reprise)
et n'en diffère que par un argument : `--tools`, construit depuis
`SpeculativeGrant.allowed_tools`.

## Ce qui ne passe pas la frontière, et pourquoi c'est dit plutôt que subi

`--tools` ne nomme que des outils **intégrés** au CLI. La table des capacités
accorde aussi `memory_search`, `scene_inspect`, `scene_query`, `scene_get` et
`scene_create_object`, qui sont des outils MCP — et un profil restreint passe
`--strict-mcp-config`, donc aucun serveur MCP n'est monté. Ces noms-là sont
**retirés** de ce qui part au CLI, et le retrait est journalisé par son nom :
une capacité accordée mais inatteignable est exactement le genre de silence qui
fait croire à un défaut de modèle.

Conséquence assumée pour V1, écrite ici pour qu'elle ne se découvre pas à
l'usage : une préparation ne peut pas fouiller la mémoire canonique, et elle ne
peut pas lire la scène. Le **montage** d'un objet masqué, lui, n'est pas touché :
il est fait par le service (`PresentationSpeculativeService._stage`) à partir de
ce que l'exécutant rend, jamais par l'exécutant lui-même.

## La provenance, et pourquoi elle ne peut pas être déclarée

`decide_attention` (Slice 09) refuse un verdict dont la pièce à conviction cite
une source que l'ensemble de travail ne connaît pas — *« un exécutant qui
invente une source ne passe pas »*. Aucun producteur de `PresentationSource`
n'existait dans le dépôt : l'ensemble des sources connues était donc
**toujours vide**, et toute alerte de contradiction aurait été refusée en
`attention_provenance_unknown`, sans qu'aucun test le voie puisque rien ne
câblait la chaîne.

Cet exécutant ferme le trou dans le seul sens qui garde la garantie : il
**range la source** dans l'ensemble de travail (`record_source`) avant de citer
son identifiant. L'identifiant cité est donc celui d'un enregistrement qui
existe, avec son locator ; la provenance reste vérifiée, pas déclarée. Le
modèle ne choisit aucun identifiant : il ne voit que des locators.

De même pour les affirmations : les identifiants de claim sont **donnés** au
modèle, qui ne peut qu'en renvoyer un de la liste. Un identifiant hors liste
est refusé ici, avant le juge.

## Ce qui n'est jamais journalisé

La parole de la salle. Le message envoyé au sous-agent en contient
nécessairement — c'est son sujet — mais aucune ligne de ce module ne porte
`request.text`, ni un énoncé d'affirmation, ni le `reason` d'un verdict. Les
lignes portent des identifiants, des comptes et des codes. C'est la même règle
qu'à la Slice 08 pour `SpeculativeJobKey.value`.

**Et cela ne suffisait pas.** La règle tenait dans ce module et se perdait au
bout du fil : `ClaudeLocalAgent.send()` recopie son entrée dans `agent.input`
pour la console de debug, donc chaque phrase entendue dans la salle partait
dans `runtime/trace.jsonl` — en ajout seul, sans rotation, et hors de portée du
réglage `log_content`, qui gouverne un autre journal. Un profil restreint n'a
pas de console, donc cet écho n'y a aucun lecteur : il est retenu là-bas pour
les deux profils restreints, et `test_le_vrai_sous_agent_ne_recopie_pas_la_parole_de_la_salle`
le conduit avec le **vrai** agent, parce que le test qui le croyait le
conduisait avec un double qui n'a pas de journal du tout.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from jarvis.core.presentation_speculative import (
    MAX_FINDINGS_PER_JOB,
    PreparedFinding,
    SpeculativeOutcome,
    SpeculativeRequest,
)
from jarvis.domain.presentation_attention import (
    MAX_ATTENTION_EVIDENCE,
    AttentionEvidence,
    FactCheckAssessment,
)
from jarvis.domain.presentation_speculative import SpeculativeCapability
from jarvis.domain.presentation_working_set import ClaimStatus, ResourceKind
from jarvis.runtime.claude_local import CLI_GRANTABLE_TOOLS
from jarvis.runtime.journal import RuntimeJournal

__all__ = [
    "PRESENTATION_PREPARATION_KIND",
    "MAX_ANSWER_CHARS",
    "PreparationClaim",
    "PresentationPreparationRunner",
]

#: Préfixe de trace de cet exécutant.
PRESENTATION_PREPARATION_KIND = "presentation.preparation"

#: Réponse retenue du sous-agent. Au-delà, on ne parse pas : un exécutant qui
#: rend 400 kB ne rend pas un objet JSON compact, il rend du bavardage, et
#: `json.loads` sur du bavardage est un coût sans contrepartie.
MAX_ANSWER_CHARS = 16_000

#: Affirmations proposées à la vérification dans un même travail. Le juge n'en
#: retient que deux par remise (`MAX_ATTENTION_PER_BATCH`) ; en proposer
#: davantage ne ferait qu'allonger la consigne.
MAX_CLAIMS_OFFERED = 4

#: Longueurs retenues, avant que les constructeurs du domaine ne se prononcent.
#: Couper ici donne un enregistrement ; laisser passer donnerait un refus.
MAX_LOCATOR_CHARS = 300  # MAX_REFERENCE_CHARS de la Slice 04
MAX_TITLE_CHARS = 120  # MAX_SOURCE_TITLE_CHARS de la Slice 04
MAX_REASON_CHARS = 160

#: Natures de ressource qu'un exécutant peut nommer. `SCENE_OBJECT` en est
#: absent délibérément : c'est le service qui monte un objet de scène, et une
#: découverte qui se déclarerait déjà montée pointerait vers un objet
#: inexistant.
ANSWERABLE_KINDS = {
    "document": ResourceKind.DOCUMENT,
    "url": ResourceKind.WEB_PAGE,
    "web_page": ResourceKind.WEB_PAGE,
    "note": ResourceKind.DOCUMENT,
    "answer": ResourceKind.CHART_DESCRIPTOR,
    "chart_descriptor": ResourceKind.CHART_DESCRIPTOR,
}

#: Verdicts qu'un exécutant peut rendre. `ASSERTED` en est absent : c'est l'état
#: d'une affirmation *avant* vérification, et le rendre serait dire « je n'ai
#: pas cherché » dans un champ qui existe déjà pour cela (`searched`).
ANSWERABLE_VERDICTS = {
    "supported": ClaimStatus.SUPPORTED,
    "contradicted": ClaimStatus.CONTRADICTED,
    "unverifiable": ClaimStatus.UNCERTAIN,
    "uncertain": ClaimStatus.UNCERTAIN,
}


class PreparationError(RuntimeError):
    """L'exécutant n'a pas pu travailler. Code stable, cause conservée."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PreparationClaim:
    """Une affirmation proposée à la vérification : son identifiant et son texte.

    Le texte part au sous-agent ; l'identifiant ne sert qu'au retour. Les deux
    voyagent ensemble pour que le modèle n'ait jamais à en inventer un.
    """

    claim_id: str
    statement: str


def _text(value: object, limit: int) -> str:
    """Une chaîne bornée, sans caractère de contrôle. Jamais `None`."""

    if not isinstance(value, str):
        return ""
    cleaned = "".join(char for char in value if char.isprintable() or char == " ")
    return " ".join(cleaned.split())[:limit]


def _confidence(value: object) -> float:
    """La confiance rendue, ramenée dans [0, 1]. Une valeur illisible vaut 0."""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    return max(0.0, min(1.0, number))


class PresentationPreparationRunner:
    """Un sous-agent Claude borné, par travail. Rend des références, jamais des actes."""

    def __init__(
        self,
        *,
        agent_factory: Callable[[tuple[str, ...]], Any],
        record_source: Callable[[ResourceKind, str, str], str | None],
        claims_for: Callable[[str], Sequence[PreparationClaim]] | None = None,
        journal: RuntimeJournal | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        if not callable(agent_factory) or not callable(record_source):
            raise ValueError("agent_factory and record_source must be callables")
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number")
        self._agent_factory = agent_factory
        self._record_source = record_source
        self._claims_for = claims_for
        self._journal = journal
        self._timeout_s = float(timeout_s)
        #: Comptes, pour `stats()`. Aucun texte, comme partout dans cette voie.
        self.started = 0
        self.answered = 0
        self.unparsable = 0
        self.failed = 0
        self.tools_withheld = 0
        self.sources_recorded = 0
        self.assessments_dropped = 0
        #: Découvertes pour lesquelles un montage a été demandé. Observable
        #: parce que « rien n'est monté » et « rien n'est trouvé » se ressemblent.
        self.staging_requested = 0
        #: Les ensembles d'outils retenus déjà dits. Borné par la table des
        #: capacités : il y a quatre jeux d'outils distincts en tout
        #: (`DISTINCT_TOOL_SETS`), donc cet ensemble ne peut pas grossir.
        self._withheld_said: set[tuple[str, ...]] = set()

    # -- traces -----------------------------------------------------------

    def _trace(self, event: str, message: str, *, level: str = "info", **data: object) -> None:
        if self._journal is None:
            return
        try:
            self._journal.emit(
                f"{PRESENTATION_PREPARATION_KIND}.{event}", message, level=level, data=dict(data),
            )
        except Exception:  # noqa: BLE001
            # Intentionnel, et la même position qu'à la Slice 06 : un journal en
            # panne ne doit pas faire tomber la préparation qu'il observe, et il
            # n'existe aucun second canal vers lequel se rabattre ici.
            pass

    def stats(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "answered": self.answered,
            "unparsable": self.unparsable,
            "failed": self.failed,
            "tools_withheld": self.tools_withheld,
            "sources_recorded": self.sources_recorded,
            "assessments_dropped": self.assessments_dropped,
            "staging_requested": self.staging_requested,
        }

    # -- le port ----------------------------------------------------------

    async def prepare(self, request: SpeculativeRequest) -> SpeculativeOutcome:
        """Lancer un sous-agent borné et rendre ce qu'il a trouvé."""

        tools = self._cli_tools(request)
        if not tools:
            # Un travail sans un seul outil atteignable ne prépare rien. Le dire
            # vaut mieux que de lancer un processus pour qu'il réponde « je n'ai
            # pas d'outils » en quelques centimes.
            self._trace(
                "no_tool", "Aucun outil du CLI n'est accordé : la préparation est abandonnée",
                level="warning", job_id=request.job_id,
                capabilities=sorted(c.value for c in request.grant.capabilities),
            )
            return SpeculativeOutcome()
        agent = self._agent_factory(tools)
        self.started += 1
        self._trace(
            "started", "Préparation lancée dans un sous-agent borné",
            job_id=request.job_id, priority=request.priority.value,
            origin=request.grant.origin.value, tools=list(tools),
        )
        try:
            try:
                await agent.start(resume=False)
            except Exception as exc:
                self.failed += 1
                self._trace(
                    "start_failed", f"Sous-agent de préparation non démarré : {type(exc).__name__}: {exc}",
                    level="error", job_id=request.job_id, code="presentation_preparation_start_failed",
                )
                raise PreparationError("presentation_preparation_start_failed", str(exc)) from exc
            claims = self._claims(request)
            answer = await agent.ask(self._message(request, claims), timeout_s=self._timeout_s)
            if not isinstance(answer, dict) or not answer.get("ok"):
                self.failed += 1
                self._trace(
                    "refused", "Le sous-agent de préparation n'a pas rendu de réponse utilisable",
                    level="error", job_id=request.job_id,
                    code=str((answer or {}).get("code") or "presentation_preparation_no_answer")
                    if isinstance(answer, dict) else "presentation_preparation_no_answer",
                )
                return SpeculativeOutcome()
            self.answered += 1
            return self._outcome(request, str(answer.get("text") or ""), claims)
        finally:
            await self._close(agent, request)

    # -- composition du travail -------------------------------------------

    def _cli_tools(self, request: SpeculativeRequest) -> tuple[str, ...]:
        """Les outils accordés qui sont nommables au CLI. Le reste est dit.

        Intersection avec `CLI_GRANTABLE_TOOLS`, jamais l'inverse : la table des
        capacités reste la seule source de ce qui est accordé, et cette
        fonction ne peut qu'en **retirer**.
        """

        granted = tuple(request.grant.allowed_tools)
        usable = tuple(name for name in granted if name in CLI_GRANTABLE_TOOLS)
        withheld = tuple(name for name in granted if name not in CLI_GRANTABLE_TOOLS)
        if withheld:
            self.tools_withheld += len(withheld)
            # **Une fois par ensemble d'outils**, pas une fois par travail.
            # Le retrait est structurel — tout jeton portant `RESEARCH_SEARCH`
            # porte `memory_search` —, donc le dire à chaque travail met un
            # `warning` par phrase entendue dans la trace de l'opérateur. Une
            # trace lue par personne ne dit plus rien, et la Slice 02 a payé
            # cette leçon sur un avertissement par seconde. Le **compte**
            # reste exact dans `stats()`.
            if withheld not in self._withheld_said:
                self._withheld_said.add(withheld)
                self._trace(
                    "tools_withheld",
                    "Des outils accordés ne sont pas nommables au CLI et ne partent pas",
                    level="warning", job_id=request.job_id, withheld=list(withheld),
                    code="presentation_preparation_tools_unavailable",
                )
        return usable

    def _claims(self, request: SpeculativeRequest) -> tuple[PreparationClaim, ...]:
        """Les affirmations à vérifier, si le jeton ouvre la vérification.

        Lues hors du jeton : un travail sans `FACT_VERIFICATION` n'a rien à
        vérifier, et lui proposer des affirmations l'inviterait à rendre des
        verdicts que le service refuserait ensuite (`may_verify` faux).
        """

        if SpeculativeCapability.FACT_VERIFICATION not in request.grant.capabilities:
            return ()
        if self._claims_for is None:
            return ()
        try:
            offered = tuple(self._claims_for(request.utterance_id))[:MAX_CLAIMS_OFFERED]
        except Exception as exc:  # noqa: BLE001 - une lecture ratée n'annule pas la recherche
            self._trace(
                "claims_unavailable",
                f"Affirmations illisibles : {type(exc).__name__}",
                level="warning", job_id=request.job_id,
            )
            return ()
        return tuple(item for item in offered if isinstance(item, PreparationClaim) and item.claim_id)

    def _message(self, request: SpeculativeRequest, claims: tuple[PreparationClaim, ...]) -> str:
        """Le message du travail. Il porte de la parole, et **le CLI la retient**.

        Cette docstring affirmait « il n'est jamais journalisé » trois lignes
        au-dessus du code qui le rendait faux : `ClaudeLocalAgent.send()`
        recopiait son entrée entière dans `agent.input`, donc chaque phrase
        entendue dans la salle finissait dans `runtime/trace.jsonl`, en ajout
        seul et sans rotation. La retenue est maintenant chez l'agent, pour
        **tous** les profils restreints, et c'est là qu'elle doit être : c'est
        le seul endroit qui voit ce qui part vraiment au journal.

        Ce qui reste vrai ici : rien de ce module n'écrit ce texte nulle part.
        """

        lines = [
            f"Job nature: {request.priority.value}.",
            f"Heard in the room: {request.text}",
        ]
        if claims:
            lines.append(
                "Check these claims. Use the given id verbatim in your answer; "
                "never invent one, and never answer about a claim that is not listed."
            )
            for claim in claims:
                lines.append(f'- id={claim.claim_id} claim="{claim.statement}"')
        else:
            lines.append("No claim is offered for verification: return findings only.")
        return "\n".join(lines)

    async def _close(self, agent: Any, request: SpeculativeRequest) -> None:
        """Fermer le sous-agent, toujours, et dire si la fermeture a échoué.

        Un sous-agent laissé ouvert est un processus CLI de plus sur une machine
        qui en a déjà beaucoup ; la Slice 08 a payé ce point en processus
        orphelins tournant à 5 783 s de CPU.
        """

        closer = getattr(agent, "close_owned", None) or getattr(agent, "close", None)
        if closer is None:
            return
        try:
            result = closer()
            if hasattr(result, "__await__"):
                await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._trace(
                "close_failed", f"Fermeture du sous-agent de préparation en échec : {type(exc).__name__}: {exc}",
                level="error", job_id=request.job_id, code="presentation_preparation_close_failed",
            )

    # -- lecture de la réponse ---------------------------------------------

    def _outcome(
        self, request: SpeculativeRequest, answer: str, claims: tuple[PreparationClaim, ...]
    ) -> SpeculativeOutcome:
        payload = self._payload(request, answer)
        if payload is None:
            return SpeculativeOutcome()
        findings = self._findings(request, payload.get("findings"))
        assessments = self._assessments(request, payload.get("assessments"), claims)
        self._trace(
            "prepared", "Préparation rendue",
            job_id=request.job_id, findings=len(findings), assessments=len(assessments),
        )
        return SpeculativeOutcome(findings=findings, assessments=assessments)

    def _payload(self, request: SpeculativeRequest, answer: str) -> dict[str, Any] | None:
        """Extraire l'objet JSON de la réponse. Une réponse illisible n'est pas une panne."""

        text = answer.strip()
        if len(text) > MAX_ANSWER_CHARS:
            self.unparsable += 1
            self._trace(
                "answer_oversize", "Réponse de préparation trop longue pour être lue",
                level="warning", job_id=request.job_id, chars=len(text),
            )
            return None
        # Un modèle encadre volontiers son JSON d'une clôture Markdown ou d'une
        # phrase. On prend le premier `{` et le dernier `}` plutôt que d'exiger
        # une réponse nue : exiger donnerait un refus pour une réponse juste.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            self.unparsable += 1
            self._trace(
                "answer_unparsable", "Réponse de préparation sans objet JSON",
                level="warning", job_id=request.job_id, chars=len(text),
            )
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except (ValueError, RecursionError):
            self.unparsable += 1
            self._trace(
                "answer_unparsable", "Réponse de préparation illisible",
                level="warning", job_id=request.job_id, chars=len(text),
            )
            return None
        if not isinstance(payload, dict):
            self.unparsable += 1
            self._trace(
                "answer_unparsable", "Réponse de préparation qui n'est pas un objet",
                level="warning", job_id=request.job_id, type=type(payload).__name__,
            )
            return None
        return payload

    def _findings(self, request: SpeculativeRequest, raw: object) -> tuple[PreparedFinding, ...]:
        if not isinstance(raw, list):
            return ()
        # **Le montage, et pourquoi il est décidé ici et pas par le modèle.**
        #
        # `stage_hidden` n'avait aucun producteur de production : la table des
        # capacités le prévoyait, `_show_prepared` savait le révéler, et rien
        # ne le demandait jamais — donc aucune ressource n'était un
        # `SCENE_OBJECT`, donc « montre-moi ça » réchauffait une ressource et
        # **ne dessinait rien**, en journalisant une réutilisation.
        #
        # Le jeton décide, pas le modèle : `may_stage` n'est vrai que pour une
        # préparation demandée par un tour explicite (`REFRESH_CAPABILITIES`
        # porte `DISPLAY_PREPARATION`) ; un jeton ambiant ne peut pas le
        # porter, et ne peut même pas se construire s'il l'essaie. Le modèle
        # n'est pas consulté : `stage_hidden` reçu dans sa réponse reste
        # ignoré, et un test le vérifie.
        #
        # **Une seule** découverte est montée par travail. Le service plafonne
        # à huit objets montés pour toute la séance, et quatre découvertes par
        # travail rempliraient ce budget en deux demandes — pour des écrans que
        # personne n'a demandés. Un tour explicite demande un visuel, pas
        # quatre.
        may_stage = bool(getattr(request.grant, "may_stage", False))
        findings: list[PreparedFinding] = []
        for entry in raw[:MAX_FINDINGS_PER_JOB]:
            if not isinstance(entry, dict):
                continue
            kind = ANSWERABLE_KINDS.get(_text(entry.get("kind"), 32).lower())
            locator = _text(entry.get("locator"), MAX_LOCATOR_CHARS)
            if kind is None or not locator:
                continue
            try:
                findings.append(
                    PreparedFinding(
                        kind=kind,
                        locator=locator,
                        title=_text(entry.get("title"), MAX_TITLE_CHARS),
                        stage_hidden=may_stage and not findings,
                    )
                )
                if findings[-1].stage_hidden:
                    self.staging_requested += 1
            except (TypeError, ValueError):
                self._trace(
                    "finding_refused", "Découverte non constructible",
                    level="warning", job_id=request.job_id,
                )
        return tuple(findings)

    def _assessments(
        self, request: SpeculativeRequest, raw: object, claims: tuple[PreparationClaim, ...]
    ) -> tuple[FactCheckAssessment, ...]:
        if not isinstance(raw, list) or not claims:
            if isinstance(raw, list) and raw and not claims:
                self.assessments_dropped += len(raw)
                self._trace(
                    "assessment_unsolicited",
                    "Des verdicts sont rendus alors qu'aucune affirmation n'était proposée",
                    level="warning", job_id=request.job_id, count=len(raw),
                )
            return ()
        known = {claim.claim_id for claim in claims}
        assessments: list[FactCheckAssessment] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            claim_id = _text(entry.get("id") or entry.get("claim_id"), 64)
            verdict = ANSWERABLE_VERDICTS.get(_text(entry.get("verdict"), 32).lower())
            if claim_id not in known or verdict is None:
                self.assessments_dropped += 1
                self._trace(
                    "assessment_refused",
                    "Verdict écarté : affirmation inconnue ou verdict illisible",
                    level="warning", job_id=request.job_id,
                    known_claim=claim_id in known, has_verdict=verdict is not None,
                )
                continue
            evidence = self._evidence(request, entry)
            try:
                assessments.append(
                    FactCheckAssessment(
                        claim_id=claim_id,
                        verdict=verdict,
                        confidence=_confidence(entry.get("confidence")),
                        evidence=evidence,
                        reason=_text(entry.get("reason") or entry.get("evidence"), MAX_REASON_CHARS),
                        # `searched` est vrai parce que l'exécutant a bien
                        # cherché : il n'est appelé qu'avec des outils. Une
                        # recherche sans résultat rend `unverifiable`, que
                        # `decide_attention` refuse d'alerter — le champ dit
                        # « la recherche a eu lieu », pas « elle a conclu ».
                        searched=True,
                    )
                )
            except (TypeError, ValueError):
                self.assessments_dropped += 1
                self._trace(
                    "assessment_refused", "Verdict non constructible",
                    level="warning", job_id=request.job_id,
                )
        return tuple(assessments)

    def _evidence(self, request: SpeculativeRequest, entry: dict[str, Any]) -> tuple[AttentionEvidence, ...]:
        """Ranger la source citée, puis citer **son** identifiant.

        L'ordre est le sujet : l'enregistrement existe avant que son identifiant
        ne soit cité, donc `decide_attention` vérifie une provenance réelle. Un
        `record_source` qui ne range rien rend `None`, et le verdict part sans
        pièce — il sera refusé par le juge en `attention_no_evidence`, ce qui
        est la bonne fin, pas une exception.
        """

        locator = _text(entry.get("source") or entry.get("locator"), MAX_LOCATOR_CHARS)
        if not locator:
            return ()
        title = _text(entry.get("source_title") or entry.get("title"), MAX_TITLE_CHARS)
        kind = ResourceKind.WEB_PAGE if locator.lower().startswith(("http://", "https://")) else ResourceKind.DOCUMENT
        try:
            source_id = self._record_source(kind, locator, title)
        except Exception as exc:  # noqa: BLE001 - ranger une source ne casse pas le verdict
            self._trace(
                "source_refused", f"Source non rangée : {type(exc).__name__}",
                level="warning", job_id=request.job_id,
            )
            return ()
        if not isinstance(source_id, str) or not source_id:
            return ()
        self.sources_recorded += 1
        try:
            return (AttentionEvidence(source_id=source_id, locator=locator, title=title),)[
                :MAX_ATTENTION_EVIDENCE
            ]
        except (TypeError, ValueError):
            self._trace(
                "evidence_refused", "Pièce à conviction non constructible",
                level="warning", job_id=request.job_id,
            )
            return ()
