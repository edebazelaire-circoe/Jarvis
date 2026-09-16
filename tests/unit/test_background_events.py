"""Le registre des événements de fond : compter ce qui s'est passé derrière.

Retour utilisateur du 16/09/2026 : deux demandes vocales sont mortes sans un
mot. Le retour vocal est traité par le réveil du cerveau ; ici on prouve
l'autre moitié, celle qui n'interrompt pas — le compte discret et lisible.
"""

from __future__ import annotations

import json

from jarvis.runtime.background_events import (
    ATTENTION,
    DONE,
    FAILED,
    MAX_ENTRIES,
    MAX_READ_BYTES,
    BackgroundEventLedger,
    TraceFollower,
    follow,
)


def emit(ledger: BackgroundEventLedger, kind: str, message: str = "m", **data):
    return ledger.observe(kind, message, data=data, ts="2026-09-16T07:38:57+00:00")


def test_the_incident_of_the_day_is_classified_exactly_as_it_happened():
    """Les trois morts de 07:38:57, telles que la trace les a écrites."""
    ledger = BackgroundEventLedger()

    emit(ledger, "agent.subagent.finished",
         "Sous-agent interrompu après 1 min 28 s (agent principal arrêté) : Git branches vs main status",
         status="interrupted", description="Git branches vs main status")
    emit(ledger, "agent.subagent.finished", "Sous-agent interrompu après 1 s : Note Agar reindex requirement",
         status="interrupted", description="Note Agar reindex requirement")
    emit(ledger, "core.brain.turn_failed", "le backend cerveau a rendu un échec", error="claude_handover")
    emit(ledger, "voice.speech.error_withheld", "Erreur non prononcée", reason="stale_source")
    emit(ledger, "core.brain.woken_by_work", "tour ouvert par un changement de travail de fond", notes=3)

    assert ledger.counts() == {FAILED: 4, ATTENTION: 1}
    assert ledger.unread == 5
    payload = ledger.to_payload()
    # Le plus récent d'abord : c'est l'ordre de lecture d'un panneau.
    assert payload["events"][0]["kind"] == "core.brain.woken_by_work"
    assert payload["events"][-1]["detail"] == "Git branches vs main status"


def test_a_finished_subagent_counts_as_done_and_a_spoken_relay_counts_as_nothing():
    ledger = BackgroundEventLedger()

    emit(ledger, "agent.subagent.finished", "Sous-agent terminé en 12 s : Transcript", status="completed")
    # Déjà entendu : le badge n'a rien à ajouter.
    assert emit(ledger, "agent.unsolicited_result", "Le transcript est prêt.", spoken=True) is None
    # Resté silencieux : à signaler.
    emit(ledger, "agent.unsolicited_result", "Tour spontané, rien à dire", spoken=False)
    # Bruit de fonctionnement : jamais dans le badge.
    for noise in ("voice.state.updated", "agent.event", "voice.ledger.projected", "core.work.attention"):
        assert emit(ledger, noise, "bruit", status="running") is None

    assert ledger.counts() == {DONE: 1, "said": 1}


def test_a_blocked_work_asks_for_attention_but_a_running_one_does_not():
    ledger = BackgroundEventLedger()

    assert emit(ledger, "core.work.attention", "changement", status="interrupted") is None
    emit(ledger, "core.work.attention", "changement", status="blocked")

    assert ledger.counts() == {ATTENTION: 1}


def test_acknowledging_clears_the_count_and_never_rewinds_it():
    ledger = BackgroundEventLedger()
    for index in range(3):
        emit(ledger, "agent.subagent.finished", f"fini {index}", status="completed")

    assert ledger.acknowledge(2) == 2 and ledger.unread == 1
    # Un onglet en retard ne doit pas renvoyer le badge à l'utilisateur.
    assert ledger.acknowledge(1) == 2 and ledger.unread == 1
    # Un accusé au-delà de ce qui existe ne crée pas d'avance.
    assert ledger.acknowledge(99) == 3 and ledger.unread == 0
    emit(ledger, "agent.subagent.finished", "fini 4", status="completed")
    assert ledger.unread == 1


def test_an_entry_pushed_out_by_the_bound_stops_being_counted_as_unread():
    """Sinon le badge afficherait un reste qu'on ne peut plus ouvrir."""
    ledger = BackgroundEventLedger()
    for index in range(MAX_ENTRIES + 10):
        emit(ledger, "agent.subagent.finished", f"fini {index}", status="failed")

    assert len(ledger.entries) == MAX_ENTRIES
    assert ledger.unread == MAX_ENTRIES
    assert ledger.acknowledge() == ledger.seq and ledger.unread == 0


# --------------------------------------------------------------- TraceFollower


def write(path, *payloads) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def trace_entry(kind: str, **data) -> dict:
    return {"ts": "2026-09-16T07:38:57+00:00", "kind": kind, "level": "warning", "message": kind, "data": data}


def test_the_follower_ignores_the_past_and_then_reads_only_what_is_new(tmp_path):
    path = tmp_path / "trace.jsonl"
    write(path, trace_entry("agent.subagent.finished", status="failed"))
    ledger, follower = BackgroundEventLedger(), TraceFollower(path)

    # Premier passage : on se place à la fin. Ouvrir le Control Center ne doit
    # pas signaler d'un coup des événements vieux de plusieurs jours.
    assert follow(ledger, follower) == 0 and ledger.unread == 0

    write(path, trace_entry("agent.subagent.finished", status="interrupted"), trace_entry("voice.state.updated"))
    assert follow(ledger, follower) == 1
    assert follow(ledger, follower) == 0  # Rien de neuf : rien relu.
    assert ledger.counts() == {FAILED: 1}


def test_the_follower_survives_a_truncated_trace_and_a_half_written_line(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    ledger, follower = BackgroundEventLedger(), TraceFollower(path)
    follow(ledger, follower)

    # Ligne encore en cours d'écriture : rien n'est consommé, le curseur attend.
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"ts":"t","kind":"agent.subagent.finished","data":{"status":"fai')
    assert follow(ledger, follower) == 0
    with path.open("a", encoding="utf-8") as handle:
        handle.write('led"}}\n')
    assert follow(ledger, follower) == 1

    # Trace repartie de zéro (redémarrage, rotation) : on relit depuis le début.
    path.write_text("", encoding="utf-8")
    write(path, trace_entry("agent.subagent.finished", status="killed"))
    assert follow(ledger, follower) == 1
    assert ledger.counts() == {FAILED: 2}


def test_a_trace_truncated_then_regrown_past_the_cursor_is_resynchronised(tmp_path):
    """Le piège que la seule comparaison de taille laisse passer.

    Tronquée puis regrossie au-delà du curseur entre deux passages, la trace
    aurait été relue au milieu d'une ligne : l'entrée coupée ne se décode pas,
    et l'événement disparaît sans que rien ne le signale. C'est exactement le
    genre de silence que tout ce travail cherche à supprimer.
    """
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    ledger, follower = BackgroundEventLedger(), TraceFollower(path)
    follow(ledger, follower)

    write(path, trace_entry("agent.subagent.finished", status="failed"))
    assert follow(ledger, follower) == 1
    short_cursor = follower.offset

    # Remplacée par un contenu plus long que le curseur tenu.
    path.write_text("", encoding="utf-8")
    write(path, trace_entry("agent.subagent.finished", status="killed", description="x" * 300))
    assert path.stat().st_size > short_cursor

    assert follow(ledger, follower) == 1
    assert ledger.counts() == {FAILED: 2}


def test_an_unreadable_line_is_skipped_without_stopping_the_follower(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    ledger, follower = BackgroundEventLedger(), TraceFollower(path)
    follow(ledger, follower)

    with path.open("a", encoding="utf-8") as handle:
        handle.write("pas du json\n")
        handle.write("[1,2,3]\n")  # JSON valide mais pas une entrée de journal.
    write(path, trace_entry("agent.subagent.finished", status="failed"))

    assert follow(ledger, follower) == 1
    assert ledger.counts() == {FAILED: 1}


def test_a_missing_trace_is_not_an_error_and_a_giant_line_never_wedges_the_cursor(tmp_path):
    ledger = BackgroundEventLedger()
    assert follow(ledger, TraceFollower(tmp_path / "absent.jsonl")) == 0

    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    follower = TraceFollower(path)
    follow(ledger, follower)
    # Une ligne plus longue que le budget ne tiendra jamais d'un coup : sans
    # avance du curseur, la lecture resterait bloquée dessus pour toujours.
    with path.open("a", encoding="utf-8") as handle:
        handle.write("x" * (MAX_READ_BYTES + 10))
    before = follower.offset
    follow(ledger, follower)
    assert follower.offset > before


def test_a_trace_that_does_not_exist_yet_is_read_in_full_when_it_appears(tmp_path):
    """Le suivi commence à sa création, pas au premier fichier trouvé.

    Fixer le curseur « à la fin » lors du premier passage réussi aurait sauté
    tout ce qui avait été écrit entre-temps — un silence de plus.
    """
    path = tmp_path / "trace.jsonl"
    ledger, follower = BackgroundEventLedger(), TraceFollower(path)
    assert follow(ledger, follower) == 0  # Pas encore de trace.

    write(path, trace_entry("agent.subagent.finished", status="failed"))
    assert follow(ledger, follower) == 1
    assert ledger.counts() == {FAILED: 1}
