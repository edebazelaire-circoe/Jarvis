"""THIRD labelled set (Slice 13 rework): written AFTER the anchoring rule was frozen, to attack it, and never used to tune it.

The rule (budgets, word lists) was derived from the two other corpora (`presentation_studio_cue_corpus.py`, the implementer's
first set, and `presentation_studio_cue_corpus_qa.py`, the reconstruction of the QA's independent set). This set was written
afterwards, trying to find sentences the frozen rule fires on wrongly and stage directions it wrongly drops. It is the nearest
thing to a held-out set that one author can produce; it is still written by the same author, in French only, typed rather than
transcribed. Labels are what a careful human presenter would want.

Same shape as the other fixtures. Armed sets reuse the QA module's (`enchaine`, `diapo`, `go`, `plan`).
"""

from __future__ import annotations

from tests.fakes.presentation_studio_cue_corpus_qa import ARMED_SETS, CUES, armed_payload  # noqa: F401 - the same cue ids

CASES: list[tuple[str, str, str | None, str]] = [
    # ---- plain stage directions: should fire
    ("enchaine", "Bref, on enchaîne.", "E", "positive"),
    ("enchaine", "Merci, on enchaîne.", "E", "positive"),
    ("enchaine", "Ok on enchaine", "E", "positive"),
    ("enchaine", "Voilà. On enchaine.", "E", "positive"),
    ("enchaine", "C'était clair pour tout le monde. On enchaîne.", "E", "positive"),
    ("diapo", "Prochaine diapo s'il vous plaît", "D", "positive"),
    ("diapo", "Eh bien prochaine diapo", "D", "positive"),
    ("diapo", "C'était clair. Prochaine diapo.", "D", "positive"),
    ("diapo", "Prochaine diapo !", "D", "positive"),
    ("go", "Alors, allez !", "W", "positive"),
    ("go", "Allez hop", "W", "positive"),
    ("plan", "Regardons maintenant le plan de financement.", "L", "positive"),
    # ---- stage directions the frozen rule is expected to DROP (honest false negatives)
    ("plan", "Regardons maintenant le plan de financement de l'entreprise.", "L", "positive_with_complement"),
    ("plan", "Bien, regardons maintenant le plan de financement et ensuite les risques.", "L", "positive_with_complement"),
    ("enchaine", "Bon, on enchaîne, et on garde le rythme jusqu'à la pause.", "E", "positive_with_complement"),
    ("diapo", "Prochaine diapo, celle sur les résultats du trimestre.", "D", "positive_with_complement"),
    # ---- ordinary speech that contains the phrase
    ("enchaine", "Franchement ça m'étonne qu'on enchaine", None, "frame"),
    ("enchaine", "Tu veux qu'on enchaîne ?", None, "question"),
    ("enchaine", "Je crois qu'on enchaîne", None, "frame"),
    ("enchaine", "Et si on enchaîne ?", None, "question"),
    ("enchaine", "On enchaîne ou on s'arrête ici ?", None, "question"),
    ("enchaine", "Chaque lundi on enchaîne les réunions", None, "sentence_open_or_close"),
    ("enchaine", "Dans cette équipe on enchaîne", None, "sentence_open_or_close"),
    ("enchaine", "Il va falloir qu'on enchaîne vite", None, "frame"),
    ("enchaine", "Je ne dis pas on enchaîne", None, "quoted"),
    ("enchaine", "Elle a juste dit on enchaîne", None, "quoted"),
    ("diapo", "Il dit toujours prochaine diapo", None, "quoted"),
    ("diapo", "La prochaine diapo", None, "noun_phrase"),
    ("diapo", "La prochaine diapo est sur le budget", None, "noun_phrase"),
    ("diapo", "Voici la prochaine diapo du lot", None, "noun_phrase"),
    ("diapo", "Prochaine diapo ?", None, "question"),
    ("diapo", "Je ne montre pas la prochaine diapo", None, "negated"),
    ("diapo", "Quand arrive la prochaine diapo", None, "noun_phrase"),
    ("go", "Allez salut", None, "one_word"),
    ("go", "Allez les gars", None, "one_word"),
    ("go", "Ils vont aller jusqu'au bout, allez savoir pourquoi", None, "one_word"),
    ("plan", "Le plan de financement est dans le dossier", None, "partial"),
    ("plan", "Regardons maintenant", None, "partial"),
    # ---- an address anywhere
    ("diapo", "Jarvis, prochaine diapo", None, "address_anywhere"),
    ("diapo", "Prochaine diapo Jarvis", None, "address_anywhere"),
    ("enchaine", "Merci Jarvis on enchaîne", None, "address_anywhere"),
    # ---- near misses
    ("enchaine", "On enchaînait déjà hier", None, "near_miss"),
    ("diapo", "Prochaines diapos", None, "near_miss"),
]
