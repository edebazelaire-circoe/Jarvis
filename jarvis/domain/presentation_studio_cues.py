"""Presentation Studio : le suiveur de cues, partie pure (handoff jarvis-interactive-presentation-studio, Slice 13).

Un appariement **conservateur** entre ce que la salle dit (une énonciation ambiante, déjà transcrite) et l'ensemble
**fini** de cues armées que Core a remis (`presentation_studio_armed_set`). Le contrat d'autorité est R5 : la parole
ambiante ne peut satisfaire qu'une cue **déjà armée** dans la partition ; la seule sortie est `CueMatch(cue_id,
generation, evidence)` ; l'action liée est résolue par Core depuis la partition stockée, jamais ici.

Ce module n'a **aucune sortie texte** : ni transcription, ni phrase, ni extrait. `CueEvidence` porte un identifiant
d'énonciation, deux positions de caractères et le nom de la règle. Un test structurel interdit qu'un champ `str` autre
qu'un identifiant s'y glisse (comme `FREE_TEXT_FIELDS` dans la partition).

## Quand une cue tire (toutes les conditions)

1. exactement **une** cue armée est touchée par l'énonciation (deux cues touchées, ou une phrase que plusieurs cues
   armées partagent : `AMBIGUOUS`, rien ne tire, l'issue est enregistrée) ;
2. la touche suit une règle de la configuration : `whole_phrase` (la phrase entière, jetons contigus), `ordered_tokens`
   (phrase d'au moins 3 jetons, tous présents dans l'ordre, au plus 1 jeton inséré entre deux, 2 au total, jamais une
   négation) ou `fuzzy_phrase` (phrase d'au moins 16 caractères, un seul jeton de 6 lettres ou plus à une édition
   près, même première lettre : une faute de transcription, jamais un homophone court) ;
3. l'appariement se fait sur le texte **normalisé** (NFKC, casefold, accents retirés, ponctuation, apostrophes et
   traits d'union = séparateurs) et **à la frontière des jetons** : jamais une sous-chaîne dans un mot ;
4. le contexte n'annule pas la touche : citation (`« »`, guillemets, « je dis », « l'expression »), négation ou
   hypothèse juste avant (« ne », « pas », « si »), question (`?`, « est-ce que », « pourquoi »...), et la touche doit
   être **ancrée** : au plus 3 jetons avant ou 3 jetons après elle dans sa phrase (une phrase de cue se dit comme une
   indication de scène, pas au milieu d'un propos). Une cue d'un seul mot exige une phrase d'au plus 3 jetons ;
5. la cue n'a pas déjà tiré dans cette génération, ni dans la fenêtre de refroidissement de la cue, et aucune cue n'a
   tiré depuis moins de `min_interval_s` ;
6. elle respecte l'ordre : une cue ne tire pas avant une cue **plus tôt** dans l'ensemble armé qui n'a pas tiré
   (`allow_skip_ahead` faux par défaut ; Core n'arme aujourd'hui que la cue de l'item suivant, `ARM_LOOKAHEAD` = 1).

Les étiquettes sémantiques de l'ensemble armé sont portées pour mémoire et **jamais appariées** : relier une phrase à
une étiquette demanderait un classifieur, donc un modèle qui lit la salle ; ce n'est pas le rôle de ce module.

Pur : aucune E/S, aucune horloge (l'appelant passe des secondes monotones), aucun import de cerveau, d'outil ou de scène.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from jarvis.domain.presentation_studio_armed_set import MAX_ARMED_CUES
from jarvis.domain.presentation_studio_score import CUE_ID, MAX_PHRASE_CHARS, MAX_PHRASES

#: Une énonciation plus longue est coupée avant l'appariement (la lane ambiante borne déjà à 600 caractères).
MAX_UTTERANCE_CHARS = 2000
MAX_SEMANTICS = 4
#: An opaque counter id (`amb-000005`, `utt-12`): a short lowercase prefix, a dash, at most 16 hex digits. It is set by the
#: lane, never derived from speech; `CueMatcher.consider` replaces any other shape by a hash OF THE ID (never of the text).
_UTTERANCE_ID = re.compile(r"[a-z]{1,8}-[0-9a-f]{1,16}\Z")
_WORD = re.compile(r"[^\W_]+")
_SENTENCE_END = ".?!…;\n"
#: A clause also ends at a comma, a colon, a parenthesis or a dash: the anchoring budget is counted inside the clause.
_CLAUSE_END = ".?!…;\n,:()—–"
_OPEN_QUOTES, _CLOSE_QUOTES = "«“", "»”"

#: Marqueurs de citation : la phrase de cue est *mentionnée*, pas dite (jetons repliés).
QUOTE_MARKERS = frozenset({
    "dis", "dit", "dite", "dites", "disais", "disait", "disent", "dire", "disant", "ecrit", "ecrire", "ecris",
    "ecrivez", "expression", "phrase", "formule", "mot", "mots", "citation", "cite", "citer", "prononce",
    "prononcer", "repete", "repeter", "taper", "tape",
})
#: Dans les 3 jetons qui précèdent la touche : négation ou hypothèse (la phrase n'est pas un ordre de scène).
HEDGES_BEFORE = frozenset({
    "ne", "n", "pas", "jamais", "non", "sans", "avant", "interdit",
    # a clause that introduces the phrase instead of being it: modal / desire / expectation frames and purpose
    "faut", "va", "vais", "veux", "veut", "voulez", "voudrais", "voudrait", "aimerais", "aimerait", "attend", "attends",
    "attendons", "pour", "que", "qu", "afin", "pense", "crois", "propose", "souhaite", "essaie", "peut", "pourrait",
    "doit", "dois", "devrait", "devons", "faudrait", "puis", "ensuite",
})
#: Anywhere earlier in the same sentence: the phrase sits inside a conditional or temporal clause.
SUBORDINATORS = frozenset({"si", "quand", "lorsque", "puisque", "parce", "tandis", "pendant", "sauf"})
#: Within 3 tokens AFTER the phrase (a comma does not stop the look): a retraction or a postponement.
HEDGES_AFTER = frozenset({"non", "pas", "attends", "attendez", "attend", "plus", "jamais", "mais", "sauf", "finalement",
                          "enfin", "sinon", "peut", "attention", "stop", "minute", "seconde", "demain"})
#: Discourse words around a stage direction. They do not count against the anchoring budget (outside the matched phrase).
FILLERS = frozenset({"bon", "alors", "voila", "donc", "ok", "okay", "eh", "ben", "bien", "et", "maintenant", "merci",
                     "s", "il", "vous", "te", "plait", "svp", "allez", "hop", "voyons", "tres", "a", "tous", "toutes"})
#: Insérés dans une touche `ordered_tokens` : refusés (une négation ne se glisse pas dans une phrase de cue).
NEGATIONS = frozenset({"ne", "n", "pas", "jamais", "non", "sans", "plus", "aucun", "rien"})
#: Ouverture de phrase interrogative (hors `est-ce`, traité à part).
QUESTION_OPENERS = frozenset({"pourquoi", "comment", "combien"})


class MatchRule(StrEnum):
    WHOLE_PHRASE = "whole_phrase"
    ORDERED_TOKENS = "ordered_tokens"
    FUZZY_PHRASE = "fuzzy_phrase"


class Verdict(StrEnum):
    """L'issue d'une énonciation. Une seule, `FIRE`, produit un `CueMatch`."""

    FIRE = "fire"
    NO_ARMED = "no_armed"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    QUOTED = "quoted"
    HEDGED = "hedged"
    QUESTION = "question"
    NOT_ANCHORED = "not_anchored"
    ORDER_BLOCKED = "order_blocked"
    ALREADY_FIRED = "already_fired"
    COOLDOWN = "cooldown"


@dataclass(frozen=True, slots=True)
class CueEvidence:
    """Ce qui permet de retrouver *où* sans rien dire de *quoi* : id d'énonciation, positions, règle."""

    utterance_id: str
    start: int
    end: int
    rule: MatchRule

    def __post_init__(self) -> None:
        if not isinstance(self.utterance_id, str) or not _UTTERANCE_ID.match(self.utterance_id):
            raise ValueError("evidence needs a bounded utterance id")
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end <= MAX_UTTERANCE_CHARS:
            raise ValueError("evidence offsets must be integers with 0 <= start < end")
        if not isinstance(self.rule, MatchRule):
            raise ValueError("evidence rule must be a MatchRule")


@dataclass(frozen=True, slots=True)
class CueMatch:
    """La seule sortie du suiveur : une cue armée nommée. Elle n'autorise rien par elle-même (Core juge et résout)."""

    cue_id: str
    generation: int
    evidence: CueEvidence

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.cue_id, str) or not CUE_ID.match(self.cue_id):
            raise ValueError("a cue match names a psc_ cue id")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        if not isinstance(self.evidence, CueEvidence):
            raise ValueError("a cue match carries a CueEvidence")


@dataclass(frozen=True, slots=True)
class CueDecision:
    """L'issue d'une énonciation : un verdict, éventuellement un `CueMatch`, et les ids de cues en cause (ambiguïté)."""

    verdict: Verdict
    match: CueMatch | None = None
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, Verdict):
            raise ValueError("verdict must be a Verdict")
        if (self.verdict is Verdict.FIRE) != (self.match is not None):
            raise ValueError("only FIRE carries a match")
        if not isinstance(self.candidates, tuple) or not all(isinstance(c, str) and CUE_ID.match(c) for c in self.candidates):
            raise ValueError("candidates are cue ids")


@dataclass(frozen=True, slots=True)
class MatcherConfig:
    accepted_rules: frozenset[MatchRule] = frozenset(MatchRule)
    #: Content tokens (not `FILLERS`) allowed before / after the phrase INSIDE ITS CLAUSE.
    before_tokens: int = 1
    after_tokens: int = 1
    #: Content tokens of the WHOLE utterance outside the phrase's sentence-level surroundings: a stage direction is not
    #: buried in a paragraph (a missed cue is recoverable by the keyboard, a false fire is not welcome).
    utterance_before_tokens: int = 6
    utterance_after_tokens: int = 4
    #: A one-word cue needs a sentence of at most this many tokens, all others being fillers.
    single_word_max_tokens: int = 2
    max_gap: int = 1
    max_total_gap: int = 2
    fuzzy_min_chars: int = 16
    fuzzy_min_token_chars: int = 6
    cue_cooldown_s: float = 4.0
    min_interval_s: float = 1.0
    allow_skip_ahead: bool = False


@dataclass(frozen=True, slots=True)
class ArmedCueTokens:
    cue_id: str
    phrases: tuple[tuple[str, ...], ...]
    semantics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArmedCues:
    """L'ensemble armé tel que Core l'a remis, phrases déjà réduites en jetons repliés."""

    run_id: str | None
    generation: int
    expires_in_s: float
    cues: tuple[ArmedCueTokens, ...] = ()

    @property
    def empty(self) -> bool:
        return self.run_id is None or not self.cues


def fold_token(token: str) -> str:
    """NFKC, casefold, ligatures, accents retirés. Un homographe non latin reste non latin (donc jamais égal)."""

    folded = unicodedata.normalize("NFKC", token).casefold().replace("œ", "oe").replace("æ", "ae")
    return "".join(ch for ch in unicodedata.normalize("NFD", folded) if not unicodedata.combining(ch))


def phrase_tokens(phrase: str) -> tuple[str, ...]:
    return tuple(fold_token(m.group()) for m in _WORD.finditer(phrase))


def parse_armed(raw: object) -> ArmedCues:
    """Lit la réponse de `GET .../playback/armed`. Strict ; l'erreur ne cite jamais une phrase."""

    if not isinstance(raw, Mapping):
        raise ValueError("armed set malformed: not an object")
    run_id, generation, ttl, cues = raw.get("run_id"), raw.get("generation"), raw.get("expires_in_s"), raw.get("cues")
    if run_id is not None and (not isinstance(run_id, str) or not 1 <= len(run_id) <= 64):
        raise ValueError("armed set malformed: run_id")
    if type(generation) is not int or generation < 0:
        raise ValueError("armed set malformed: generation")
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 0 < ttl <= 3600:
        raise ValueError("armed set malformed: expires_in_s")
    if not isinstance(cues, Sequence) or isinstance(cues, (str, bytes)) or len(cues) > MAX_ARMED_CUES:
        raise ValueError("armed set malformed: cues")
    parsed: list[ArmedCueTokens] = []
    for index, entry in enumerate(cues):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("cue_id"), str) or not CUE_ID.match(entry["cue_id"]):
            raise ValueError(f"armed set malformed: cues[{index}].cue_id")
        phrases, semantics = entry.get("phrases"), entry.get("semantics", [])
        if not isinstance(phrases, Sequence) or isinstance(phrases, (str, bytes)) or len(phrases) > MAX_PHRASES \
                or not all(isinstance(p, str) and 0 < len(p) <= MAX_PHRASE_CHARS for p in phrases):
            raise ValueError(f"armed set malformed: cues[{index}].phrases")
        if not isinstance(semantics, Sequence) or isinstance(semantics, (str, bytes)) or len(semantics) > MAX_SEMANTICS \
                or not all(isinstance(s, str) and len(s) <= 40 for s in semantics):
            raise ValueError(f"armed set malformed: cues[{index}].semantics")
        tokens = tuple(dict.fromkeys(t for t in (phrase_tokens(p) for p in phrases) if t))
        parsed.append(ArmedCueTokens(entry["cue_id"], tokens, tuple(semantics)))
    return ArmedCues(run_id, generation, float(ttl), tuple(parsed))


# ------------------------------------------------------------------ tokens and edit distance


@dataclass(frozen=True, slots=True)
class _Tok:
    text: str
    start: int
    end: int


def _tokenise(text: str) -> list[_Tok]:
    return [_Tok(fold_token(m.group()), m.start(), m.end()) for m in _WORD.finditer(text)]


def _close(a: str, b: str) -> bool:
    """Distance d'édition <= 1 (insertion, suppression, substitution, ou transposition adjacente)."""

    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long[i]:
        i += 1
    return short[i:] == long[i + 1:]


@dataclass(frozen=True, slots=True)
class _Hit:
    first: int  # token index in the utterance
    last: int
    rule: MatchRule
    phrase: tuple[str, ...]


def _find(phrase: tuple[str, ...], toks: list[_Tok], config: MatcherConfig) -> _Hit | None:
    m, n = len(phrase), len(toks)
    if not m or n < m:
        return None
    words = [t.text for t in toks]
    if MatchRule.WHOLE_PHRASE in config.accepted_rules:
        for i in range(n - m + 1):
            if words[i:i + m] == list(phrase):
                return _Hit(i, i + m - 1, MatchRule.WHOLE_PHRASE, phrase)
    if MatchRule.ORDERED_TOKENS in config.accepted_rules and m >= 3:
        for i in range(n):
            if words[i] != phrase[0]:
                continue
            prev, gaps, ok = i, 0, True
            for k in range(1, m):
                found = None
                for j in range(prev + 1, min(n, prev + 2 + config.max_gap)):
                    if words[j] == phrase[k]:
                        found = j
                        break
                if found is None or gaps + (found - prev - 1) > config.max_total_gap \
                        or any(w in NEGATIONS or w in QUOTE_MARKERS for w in words[prev + 1:found]):
                    ok = False
                    break
                gaps += found - prev - 1
                prev = found
            if ok and gaps > 0:
                return _Hit(i, prev, MatchRule.ORDERED_TOKENS, phrase)
    if MatchRule.FUZZY_PHRASE in config.accepted_rules and len(" ".join(phrase)) >= config.fuzzy_min_chars:
        for i in range(n - m + 1):
            window = words[i:i + m]
            wrong = [k for k in range(m) if window[k] != phrase[k]]
            if len(wrong) == 1:
                k = wrong[0]
                if len(phrase[k]) >= config.fuzzy_min_token_chars and window[k][:1] == phrase[k][:1] and _close(window[k], phrase[k]):
                    return _Hit(i, i + m - 1, MatchRule.FUZZY_PHRASE, phrase)
    return None


# ------------------------------------------------------------------ context checks


def _quoted_regions(text: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    opened: int | None = None
    for pos, ch in enumerate(text):
        if ch in _OPEN_QUOTES or (ch == '"' and opened is None):
            if opened is None:
                opened = pos
        elif ch in _CLOSE_QUOTES or (ch == '"' and opened is not None):
            if opened is not None:
                regions.append((opened, pos))
                opened = None
    if opened is not None:
        regions.append((opened, len(text)))  # an unclosed quote swallows the rest: conservative
    return regions


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int, str]:
    """`(first char, last char exclusive, terminator or '')` of the sentence holding the span."""

    left = max((text.rfind(ch, 0, start) for ch in _SENTENCE_END), default=-1) + 1
    right_candidates = [(text.find(ch, end), ch) for ch in _SENTENCE_END if text.find(ch, end) != -1]
    if not right_candidates:
        return left, len(text), ""
    pos, ch = min(right_candidates)
    return left, pos + 1, ch


def _clause_tokens(text: str, toks: list[_Tok], start: int, end: int) -> tuple[list[_Tok], list[_Tok]]:
    """The tokens before and after the span inside its clause (up to a comma, colon, bracket, dash or sentence end)."""

    left = max((text.rfind(ch, 0, start) for ch in _CLAUSE_END), default=-1) + 1
    rights = [i for i in (text.find(ch, end) for ch in _CLAUSE_END) if i != -1]
    right = min(rights) if rights else len(text)
    return ([t for t in toks if left <= t.start and t.end <= start], [t for t in toks if end <= t.start and t.end <= right])


def _context_verdict(text: str, toks: list[_Tok], hit: _Hit, phrase_len: int, config: MatcherConfig) -> Verdict | None:
    """`None` when the context lets the hit stand; else the verdict that cancels it."""

    start, end = toks[hit.first].start, toks[hit.last].end
    if any(a <= start < b for a, b in _quoted_regions(text)):
        return Verdict.QUOTED
    before = [t.text for t in toks[max(0, hit.first - 4):hit.first]]
    after = [t.text for t in toks[hit.last + 1:hit.last + 3]]
    if any(w in QUOTE_MARKERS for w in before) or any(w in QUOTE_MARKERS for w in after):
        return Verdict.QUOTED
    after_hedge = [t.text for t in toks[hit.last + 1:hit.last + 4]]
    s_start, s_end, terminator = _sentence_bounds(text, start, end)
    inside = [t for t in toks if s_start <= t.start < s_end]
    earlier = [t.text for t in inside if t.end <= start]
    if terminator == "?" or (len(inside) >= 2 and inside[0].text == "est" and inside[1].text == "ce") \
            or (inside and inside[0].text in QUESTION_OPENERS and inside[0].start < start):
        return Verdict.QUESTION
    if any(w in HEDGES_BEFORE for w in before[-3:]) or any(w in SUBORDINATORS for w in earlier)             or any(w in HEDGES_AFTER for w in after_hedge):
        return Verdict.HEDGED
    if phrase_len == 1 and (len(inside) > config.single_word_max_tokens
                            or any(t.text not in FILLERS for t in inside if not (t.start >= start and t.end <= end))):
        return Verdict.NOT_ANCHORED
    if sum(1 for t in toks[:hit.first] if t.text not in FILLERS) > config.utterance_before_tokens             or sum(1 for t in toks[hit.last + 1:] if t.text not in FILLERS) > config.utterance_after_tokens:
        return Verdict.NOT_ANCHORED
    clause_before, clause_after = _clause_tokens(text, toks, start, end)
    if sum(1 for t in clause_before if t.text not in FILLERS) > config.before_tokens             or sum(1 for t in clause_after if t.text not in FILLERS) > config.after_tokens:
        return Verdict.NOT_ANCHORED
    return None


# ------------------------------------------------------------------ the matcher


class CueMatcher:
    """Décide, énonciation par énonciation. L'état ne contient que des ids, des générations et des instants."""

    def __init__(self, config: MatcherConfig | None = None) -> None:
        self.config = config or MatcherConfig()
        self._armed: ArmedCues | None = None
        self._fired: set[tuple[int, str]] = set()
        self._fired_at: dict[str, float] = {}
        self._last_fire_s: float | None = None

    @property
    def armed(self) -> ArmedCues | None:
        return self._armed

    def arm(self, armed: ArmedCues | None) -> None:
        """Installe l'ensemble armé. Un autre run ou une autre génération oublie ce qui avait tiré ; `None` désarme."""

        previous = self._armed
        if armed is None or armed.empty:
            self._armed = None
            return
        if previous is None or previous.run_id != armed.run_id:
            self._fired.clear()
            self._fired_at.clear()
            self._last_fire_s = None
        elif previous.generation != armed.generation:
            self._fired.clear()  # a new generation: the cues armed now have not fired under it
        self._armed = armed

    def retract(self, match: CueMatch) -> None:
        """Le rapport n'a pas abouti (Core injoignable, limite de débit) : la cue peut tirer à nouveau."""

        self._fired.discard((match.generation, match.cue_id))
        self._fired_at.pop(match.cue_id, None)
        self._last_fire_s = None

    def consider(self, utterance_id: str, text: str, now_s: float) -> CueDecision:
        armed = self._armed
        if armed is None:
            return CueDecision(Verdict.NO_ARMED)
        text = text[:MAX_UTTERANCE_CHARS] if isinstance(text, str) else ""
        toks = _tokenise(text)
        if not toks:
            return CueDecision(Verdict.NO_MATCH)
        hits: list[tuple[int, ArmedCueTokens, _Hit]] = []
        for index, cue in enumerate(armed.cues):
            best: _Hit | None = None
            for phrase in cue.phrases:
                found = _find(phrase, toks, self.config)
                if found is not None and (best is None or (found.first, found.rule is not MatchRule.WHOLE_PHRASE) < (best.first, best.rule is not MatchRule.WHOLE_PHRASE)):
                    best = found
            if best is not None:
                hits.append((index, cue, best))
        if not hits:
            return CueDecision(Verdict.NO_MATCH)
        if len(hits) > 1 or self._shared(armed, hits[0][2].phrase):
            return CueDecision(Verdict.AMBIGUOUS, candidates=self._candidates(armed, hits))
        index, cue, hit = hits[0]
        blocked = _context_verdict(text, toks, hit, len(hit.phrase), self.config)
        if blocked is not None:
            return CueDecision(blocked)
        unfired_earlier = [c for c in armed.cues[:index] if (armed.generation, c.cue_id) not in self._fired]
        if unfired_earlier and not self.config.allow_skip_ahead:
            return CueDecision(Verdict.ORDER_BLOCKED)
        if (armed.generation, cue.cue_id) in self._fired:
            return CueDecision(Verdict.ALREADY_FIRED)
        last = self._fired_at.get(cue.cue_id)
        if (last is not None and now_s - last < self.config.cue_cooldown_s) \
                or (self._last_fire_s is not None and now_s - self._last_fire_s < self.config.min_interval_s):
            return CueDecision(Verdict.COOLDOWN)
        if not isinstance(utterance_id, str) or not _UTTERANCE_ID.match(utterance_id):
            utterance_id = f"utt-{hashlib.sha256(str(utterance_id).encode('utf-8', 'replace')).hexdigest()[:12]}"
        match = CueMatch(cue.cue_id, armed.generation,
                         CueEvidence(utterance_id, toks[hit.first].start, toks[hit.last].end, hit.rule))
        self._fired.add((armed.generation, cue.cue_id))
        self._fired_at[cue.cue_id] = now_s
        self._last_fire_s = now_s
        return CueDecision(Verdict.FIRE, match=match)

    @staticmethod
    def _shared(armed: ArmedCues, phrase: tuple[str, ...]) -> bool:
        """Une phrase que plusieurs cues armées portent (même jetons) : jamais un tir."""

        return sum(1 for cue in armed.cues if phrase in cue.phrases) > 1

    @staticmethod
    def _candidates(armed: ArmedCues, hits: list[tuple[int, ArmedCueTokens, _Hit]]) -> tuple[str, ...]:
        ids = {cue.cue_id for _, cue, _ in hits}
        for _, _, hit in hits:
            ids.update(cue.cue_id for cue in armed.cues if hit.phrase in cue.phrases)
        return tuple(sorted(ids))


__all__ = ["ArmedCueTokens", "ArmedCues", "CueDecision", "CueEvidence", "CueMatch", "CueMatcher", "MAX_UTTERANCE_CHARS",
           "MatchRule", "MatcherConfig", "Verdict", "fold_token", "parse_armed", "phrase_tokens"]
