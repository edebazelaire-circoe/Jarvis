"""Filtres de surface appliqués à un transcript avant qu'il ne devienne un tour.

Le mode continu écoute en permanence. Tout ce que le VAD du fournisseur
découpe n'est pas une demande : un bruit de bureau transcrit en russe, une
formule de sous-titrage inventée sur du silence, ou JARVIS lui-même, repris par
le micro. Ces trois cas ne relèvent pas de l'intention — que seul le cerveau
juge (Décision 44) — mais de l'audition : ce ne sont pas des propos de
l'utilisateur. La surface les écarte donc avant tout envoi, et le dit au
journal.

Les filtres sont volontairement étroits. Écarter à tort une vraie phrase est
pire que de laisser passer un bruit, que le cerveau peut encore récuser.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections import deque
from collections.abc import Callable

# Formules que les modèles de transcription produisent sur du silence ou du
# bruit : elles viennent des sous-titres de leur corpus d'entraînement, jamais
# de l'utilisateur. Comparées sur la forme normalisée (minuscules, sans accents
# ni ponctuation).
HALLUCINATED_PHRASES: tuple[str, ...] = (
    "sous titres realises par la communaute d amara org",
    "sous titres realises para la communaute d amara org",
    "sous titrage societe radio canada",
    "sous titrage st 501",
    "sous titrage st501",
    "merci d avoir regarde cette video",
    "merci d avoir regarde",
    "abonnez vous",
    "n oubliez pas de vous abonner",
    "sous titres par",
    "thank you for watching",
    "thanks for watching",
    "subtitles by the amara org community",
)

# Hésitations isolées : un segment qui ne contient que cela n'est pas un tour.
FILLERS = frozenset({"euh", "heu", "hum", "hmm", "hmmm", "mmh", "mh", "mhm", "mm", "mmm", "ah", "oh",
                     "bah", "ben", "hein", "pfff", "pff"})

# Formules polies que les modèles de transcription produisent aussi sur l'écho
# des haut-parleurs — elles viennent du même corpus de sous-titres que
# `HALLUCINATED_PHRASES`, mais sont trop courantes pour être écartées dans le
# silence. Elles ne comptent donc que sur un segment capté par-dessus la voix de
# JARVIS (`near_playback`) : un « Merci. » dit quand il se tait reste un propos.
PLAYBACK_HALLUCINATIONS: frozenset[str] = frozenset({
    "merci", "merci beaucoup", "merci bien", "merci a tous", "merci a vous",
    "merci de votre attention", "bonjour", "bonjour a tous", "bonjour a toutes et a tous",
    "bonsoir", "bonsoir a tous", "salut a tous", "au revoir", "a bientot", "a tres bientot",
    "a la prochaine", "bonne journee", "bonne soiree", "bonne nuit",
    "musique", "generique", "applaudissements", "rires", "c est parti", "voila", "et voila",
})

# Mots dont une vraie interruption d'un ou deux mots est faite : une réponse,
# un ordre d'arrêt, une relance. Il en suffit d'**un** pour que le segment
# reste un propos — « non arrête », « stop ça », « continue là » passent.
# Par-dessus la voix de JARVIS, un segment aussi court qui n'en contient aucun
# est de l'écho résiduel : le micro ambiant reprend les haut-parleurs et le
# modèle écrit une phrase brève sans rapport avec ce qui a été dit
# (« La plateforme. », poste réel du 18/09/2026).
SHORT_INTERRUPTION_WORDS: frozenset[str] = frozenset({
    "oui", "ouais", "non", "si", "ok", "okay", "accord", "exact", "exactement",
    "stop", "arrete", "arretez", "arreter", "annule", "annulez", "coupe",
    "attends", "attendez", "patiente", "chut", "tais", "taisez", "silence",
    "pardon", "quoi", "comment", "pourquoi", "qui", "quand", "hein",
    "continue", "continuez", "vas", "allez", "alors", "apres", "ensuite",
    "repete", "repetez", "redis", "reprends", "explique", "detaille",
    "fort", "vite", "lentement", "francais", "anglais",
    "parfait", "super", "genial", "nickel", "bravo", "faux", "erreur",
    "sais", "vois", "compris", "attendu", "ecoute", "ecoutez", "regarde",
})

#: Au-delà, un segment porte assez de mots pour qu'un reste d'écho ne passe
#: plus pour une consigne : seule `PLAYBACK_HALLUCINATIONS` s'applique encore.
MAX_ECHO_WORDS = 2

_WORD = re.compile(r"[a-z0-9']+")


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces simples."""

    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_WORD.findall(stripped.replace("'", " ")))


def words(text: str) -> list[str]:
    return normalize(text).split()


def _latin_share(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for char in letters if "LATIN" in unicodedata.name(char, ""))
    return latin / len(letters)


def noise_reason(text: str, *, near_playback: bool = False) -> str | None:
    """Dire pourquoi un transcript n'est pas un propos de l'utilisateur, ou None.

    - `no_letters` : rien à lire (ponctuation, chiffres isolés, vide).
    - `foreign_script` : majorité de lettres non latines. La transcription est
      réglée en français ; « директор » sur un bruit de bureau est une
      hallucination, pas une phrase russe.
    - `hallucination` : formule de sous-titrage connue.
    - `filler` : hésitation isolée.

    `near_playback` — le segment chevauche la parole de JARVIS, ou la suit de
    peu — ajoute deux raisons, et elles ne valent que là : sans casque, le micro
    ambiant reprend les haut-parleurs, et ce que le modèle écrit sur ce reste
    d'écho est court et poli, jamais une consigne.

    - `playback_hallucination` : formule de politesse de `PLAYBACK_HALLUCINATIONS`.
    - `residual_echo` : au plus `MAX_ECHO_WORDS` mots, dont aucun de
      `SHORT_INTERRUPTION_WORDS`.

    Le nom prononcé l'emporte sur les deux : « Stop Jarvis » reste un propos.
    """

    stripped = (text or "").strip()
    if not any(char.isalpha() for char in stripped):
        return "no_letters"
    if _latin_share(stripped) < 0.5:
        return "foreign_script"
    normalized = normalize(stripped)
    if not normalized:
        return "no_letters"
    if any(normalized == phrase or normalized.startswith(phrase + " ") for phrase in HALLUCINATED_PHRASES):
        return "hallucination"
    tokens = normalized.split()
    if all(token in FILLERS for token in tokens):
        return "filler"
    if not near_playback or mentions_jarvis(stripped):
        return None
    if any(token in SHORT_INTERRUPTION_WORDS for token in tokens):
        return None
    if normalized in PLAYBACK_HALLUCINATIONS:
        return "playback_hallucination"
    if len(tokens) <= MAX_ECHO_WORDS:
        return "residual_echo"
    return None


def mentions_jarvis(text: str) -> bool:
    """Le nom est prononcé, où que ce soit dans la phrase (« merci Jarvis »)."""

    return "jarvis" in words(text)


# Verbes qui ouvrent une consigne à l'impératif (« Regarde dans mon Drive… »,
# « Vérifie les commits »), sous leur forme normalisée.
IMPERATIVE_OPENERS = frozenset(
    {
        "regarde", "regardez", "dis", "dites", "donne", "donnez", "montre", "montrez", "ouvre", "ouvrez",
        "ferme", "fermez", "lance", "lancez", "cherche", "cherchez", "trouve", "trouvez", "verifie",
        "verifiez", "lis", "lisez", "relis", "ecris", "ecrivez", "envoie", "envoyez", "rappelle",
        "rappelez", "ajoute", "ajoutez", "cree", "creez", "supprime", "supprimez", "mets", "mettez",
        "fais", "faites", "explique", "expliquez", "resume", "resumez", "calcule", "calculez", "traduis",
        "traduisez", "arrete", "arretez", "affiche", "affichez", "note", "notez", "programme",
        "programmez", "planifie", "planifiez", "annule", "annulez", "pousse", "poussez", "commite",
        "corrige", "corrigez", "prepare", "preparez", "analyse", "analysez", "compare", "comparez",
        "peux", "pourrais", "pouvez", "pourriez", "aide", "aidez",
    }
)

# Tournures qui s'adressent à l'assistant où qu'elles soient dans la phrase.
REQUEST_PHRASES: tuple[str, ...] = (
    "peux tu", "pourrais tu", "pouvez vous", "pourriez vous", "est ce que tu", "est ce que vous",
    "dis moi", "dites moi", "donne moi", "donnez moi", "montre moi", "montrez moi", "rappelle moi",
    "rappelez moi", "aide moi", "aidez moi", "j aimerais que tu", "j aimerais que vous",
    "je voudrais que tu", "je voudrais que vous", "il faut que tu", "il faut que vous",
)


def looks_like_request(text: str) -> bool:
    """La phrase a la forme d'une consigne donnée à l'assistant.

    Indice de forme, pas d'intention : « il faudrait que quelqu'un rappelle le
    client » (troisième personne) n'en est pas une, « regarde dans mon Drive le
    fichier des comptes » en est une, quelle que soit sa longueur.
    """

    tokens = words(text)
    if not tokens:
        return False
    if tokens[0] in IMPERATIVE_OPENERS:
        return True
    padded = " " + " ".join(tokens) + " "
    return any(f" {phrase} " in padded for phrase in REQUEST_PHRASES)


class EchoGuard:
    """Mémoire courte de ce que JARVIS vient de dire, pour reconnaître son écho.

    Un transcript est tenu pour de l'écho quand presque tous ses mots figurent,
    dans l'ordre, dans une phrase prononcée par JARVIS dans les dernières
    secondes. « Entendu. », « Un instant, un instant. », « Entendu. Oui. » : les
    faux tours du 11 septembre 2026 étaient tous de cette forme.

    La décision reste conditionnée par l'appelant au fait que le segment ait
    été capté pendant ou juste après une parole de JARVIS : hors de cette
    fenêtre, un « oui » qui répète le « Oui. » de JARVIS est une vraie réponse.
    Même dans la fenêtre, un seul mot n'est jamais tenu pour de l'écho : « Oui. »
    répondu aussitôt à « … oui ou non ? » est la réponse la plus naturelle qui
    soit.

    Seul ce qui a été entendu compte : quand l'utilisateur coupe JARVIS, la fin
    de la phrase n'est jamais sortie des haut-parleurs, elle ne peut pas revenir
    en écho (`limit`). Sinon, l'utilisateur qui répond en devançant la fin
    serait pris pour l'écho de ce qu'il n'a pas entendu.
    """

    #: Part des mots entendus qui doivent se retrouver, dans l'ordre, dans ce
    #: que JARVIS a dit. Haute à dessein : une vraie phrase qui reprend deux
    #: mots de JARVIS n'est pas de l'écho.
    MATCH_RATIO = 0.8
    MIN_WORDS = 2

    def __init__(self, *, horizon_s: float = 15.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.horizon_s = horizon_s
        self._clock = clock
        self._spoken: deque[tuple[float, str | None, list[str]]] = deque(maxlen=32)
        self._heard_fraction: dict[str, float] = {}

    def remember(self, text: str, *, key: str | None = None) -> None:
        tokens = words(text)
        if not tokens:
            return
        if key is not None and key in self._heard_fraction:
            tokens = tokens[: int(len(tokens) * self._heard_fraction[key])]
        if tokens:
            self._spoken.append((self._clock(), key, tokens))

    def limit(self, key: str, fraction: float) -> None:
        """Ne garder de la phrase `key` que la part réellement entendue."""

        fraction = max(0.0, min(1.0, fraction))
        self._heard_fraction[key] = fraction
        while len(self._heard_fraction) > 32:
            self._heard_fraction.pop(next(iter(self._heard_fraction)))
        kept: list[tuple[float, str | None, list[str]]] = []
        for at, item_key, tokens in self._spoken:
            if item_key == key:
                tokens = tokens[: int(len(tokens) * fraction)]
            if tokens:
                kept.append((at, item_key, tokens))
        self._spoken = deque(kept, maxlen=self._spoken.maxlen)

    def recent(self) -> list[list[str]]:
        now = self._clock()
        return [tokens for at, _key, tokens in self._spoken if now - at <= self.horizon_s]

    def is_echo(self, text: str) -> bool:
        heard = words(text)
        if len(heard) < self.MIN_WORDS:
            return False
        recent = self.recent()
        if not recent:
            return False
        # Toutes les phrases récentes mises bout à bout : « Entendu. » puis
        # « Oui. » reviennent souvent en un seul segment « Entendu. Oui. ».
        spoken = [token for tokens in recent for token in tokens]
        return _ordered_overlap(heard, spoken) / len(heard) >= self.MATCH_RATIO


def _ordered_overlap(heard: list[str], spoken: list[str]) -> int:
    """Longueur de la plus longue sous-suite commune, tolérante aux mots proches."""

    previous = [0] * (len(spoken) + 1)
    for word in heard:
        current = [0] * (len(spoken) + 1)
        for index, candidate in enumerate(spoken, start=1):
            if _same_word(word, candidate):
                current[index] = previous[index - 1] + 1
            else:
                current[index] = max(previous[index], current[index - 1])
        previous = current
    return previous[-1]


def _same_word(left: str, right: str) -> bool:
    """Égalité, ou mot très proche : « attendu » pour « entendu », une lettre près."""

    if left == right:
        return True
    if min(len(left), len(right)) < 4 or abs(len(left) - len(right)) > 2:
        return False
    return _edit_distance(left, right) <= max(1, min(len(left), len(right)) // 3)


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, start=1):
        current = [i]
        for j, char_right in enumerate(right, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_left != char_right)))
        previous = current
    return previous[-1]
