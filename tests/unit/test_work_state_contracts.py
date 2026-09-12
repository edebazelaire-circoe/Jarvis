"""Contrats de l'état de travail Core (handoff work-state, tâche 10).

Prouve que les types sont neutres vis-à-vis du fournisseur, bornés, sûrs sur
le fil, et que les règles d'ordre/terminalité sont des fonctions pures que le
futur `WorkStateStore` n'aura qu'à appliquer.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.domain.v2 import jsonable
from jarvis.domain.work_state import (
    ALLOWED_WORK_TRANSITIONS,
    MAX_ACTIVITY_CHARS,
    MAX_ID_CHARS,
    MAX_LABEL_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_WORK_ITEMS,
    TERMINAL_WORK_STATUSES,
    ObservationOutcome,
    WorkItem,
    WorkLink,
    WorkObservation,
    WorkSnapshot,
    WorkStatus,
    apply_observation,
    can_transition,
    clip_text,
)
from jarvis.ports.work_state import WorkObservationSink, WorkStateReader

T0 = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)

# Vocabulaire propre à un fournisseur ou à une trace brute : aucun champ
# normalisé ne doit le porter (docs/04 : « unknown provider fields do not leak
# into domain contracts »).
PROVIDER_MARKERS = ("subagent", "tool_use_id", "prompt", "trace", "raw", "stream", "claude", "codex", "job_id", "task_id")
REASONING_MARKERS = ("thought", "reason", "scratchpad", "chain_of", "internal_monologue", "deliberation")


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def obs(**overrides) -> WorkObservation:
    values = {"source": "claude", "external_id": "task-1", "status": WorkStatus.RUNNING, "observed_at": at(0)}
    values.update(overrides)
    return WorkObservation(**values)


def created(**overrides) -> WorkItem:
    update = apply_observation(None, obs(**overrides), revision=1)
    assert update.outcome is ObservationOutcome.CREATED
    return update.item


# --- statuts et transitions --------------------------------------------------


def test_terminal_statuses_are_explicit_and_have_no_way_out():
    assert TERMINAL_WORK_STATUSES == {
        WorkStatus.COMPLETED,
        WorkStatus.FAILED,
        WorkStatus.CANCELLED,
        WorkStatus.INTERRUPTED,
    }
    for status in WorkStatus:
        assert status.is_terminal is (status in TERMINAL_WORK_STATUSES)
        assert status in ALLOWED_WORK_TRANSITIONS
    for terminal in TERMINAL_WORK_STATUSES:
        assert not any(can_transition(terminal, target) for target in WorkStatus)


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (WorkStatus.PENDING, WorkStatus.RUNNING, True),
        (WorkStatus.PENDING, WorkStatus.COMPLETED, True),
        (WorkStatus.RUNNING, WorkStatus.RUNNING, True),
        (WorkStatus.RUNNING, WorkStatus.BLOCKED, True),
        (WorkStatus.BLOCKED, WorkStatus.RUNNING, True),
        (WorkStatus.BLOCKED, WorkStatus.FAILED, True),
        (WorkStatus.RUNNING, WorkStatus.PENDING, False),
        (WorkStatus.BLOCKED, WorkStatus.PENDING, False),
        (WorkStatus.COMPLETED, WorkStatus.RUNNING, False),
        (WorkStatus.FAILED, WorkStatus.COMPLETED, False),
    ],
)
def test_allowed_transitions(current, target, allowed):
    assert can_transition(current, target) is allowed


# --- validation des types et des bornes --------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"source": ""},
        {"source": "claude code"},
        {"source": "a:b"},
        {"source": "x" * 33},
        {"external_id": ""},
        {"external_id": "  "},
        {"external_id": " task-1"},
        {"external_id": "x" * (MAX_ID_CHARS + 1)},
        {"kind": "sous agent"},
        {"label": "x" * (MAX_LABEL_CHARS + 1)},
        {"label": "deux\nlignes"},
        {"activity": "x" * (MAX_ACTIVITY_CHARS + 1)},
        {"summary": "x" * (MAX_SUMMARY_CHARS + 1)},
        {"observed_at": datetime(2026, 9, 11, 14, 0)},
        {"started_at": at(5)},
        {"parent_external_id": "task-1"},
        {"progress_fraction": -0.01},
        {"progress_fraction": 1.01},
        {"progress_fraction": float("nan")},
        {"tool_uses": -1},
        {"tokens": -5},
        {"error_class": "provider_unavailable"},
        {"status": WorkStatus.COMPLETED, "error_class": "boom"},
        {"status": WorkStatus.FAILED, "error_class": "pas un jeton"},
        {"status": WorkStatus.COMPLETED, "activity": "Read · x.py"},
    ],
)
def test_observation_rejects_invalid_or_unbounded_values(overrides):
    with pytest.raises(ValueError):
        obs(**overrides)


@pytest.mark.parametrize("overrides", [{"work_id": ""}, {"correlation_id": " corr"}, {"work_id": "w" * (MAX_ID_CHARS + 1)}])
def test_link_rejects_blank_or_unbounded_identifiers(overrides):
    # Inconnu s'écrit `None` : une chaîne vide serait un faux rattachement.
    with pytest.raises(ValueError):
        WorkLink(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "running"},
        {"external_id": 42},
        {"progress_fraction": "0.5"},
        {"progress_fraction": True},
        {"tool_uses": True},
        {"tokens": 1.5},
        {"background": "yes"},
        {"observed_at": "2026-09-11T14:00:00+00:00"},
        {"link": {"work_id": "work-1"}},
    ],
)
def test_observation_rejects_wrong_types(overrides):
    with pytest.raises(TypeError):
        obs(**overrides)


def test_summary_may_span_lines_and_summaries_at_the_bound_are_accepted():
    assert obs(summary="ligne 1\nligne 2").summary == "ligne 1\nligne 2"
    assert obs(summary="x" * MAX_SUMMARY_CHARS, progress_fraction=1).progress_fraction == 1


def test_clip_text_respects_the_bound_and_flattens_single_line_fields():
    clipped = clip_text("x" * 500, MAX_LABEL_CHARS)
    assert len(clipped) == MAX_LABEL_CHARS and clipped.endswith("…")
    assert clip_text("  Agent ·\n  lire\tle fichier\x00 ", 80) == "Agent · lire le fichier"
    assert clip_text("a\nb", 80, single_line=False) == "a\nb"
    assert obs(label=clip_text("a\nb" * 200, MAX_LABEL_CHARS)).label


@pytest.mark.parametrize(
    "overrides",
    [
        {"revision": 0},
        {"ended_at": at(10)},
        {"status": WorkStatus.COMPLETED},
        {"updated_at": at(-1)},
        {"status": WorkStatus.COMPLETED, "ended_at": at(-1)},
    ],
)
def test_item_enforces_revision_and_terminal_timestamps(overrides):
    values = {
        "source": "jobs",
        "external_id": "job-1",
        "status": WorkStatus.RUNNING,
        "revision": 1,
        "started_at": at(0),
        "updated_at": at(0),
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        WorkItem(**values)


def test_snapshot_is_bounded_unique_and_never_older_than_its_items():
    one = created()
    with pytest.raises(ValueError):
        WorkSnapshot(revision=1, items=(one, one), updated_at=at(0))
    with pytest.raises(ValueError):
        WorkSnapshot(revision=0, items=(one,), updated_at=at(0))
    with pytest.raises(TypeError):
        WorkSnapshot(revision=1, items=[one], updated_at=at(0))  # type: ignore[arg-type]
    many = tuple(created(external_id=f"task-{index}") for index in range(MAX_WORK_ITEMS + 1))
    with pytest.raises(ValueError):
        WorkSnapshot(revision=1, items=many, updated_at=at(0))
    assert WorkSnapshot(revision=1, items=many[:MAX_WORK_ITEMS], updated_at=at(0)).revision == 1


# --- fil ---------------------------------------------------------------------


def test_observation_item_and_snapshot_round_trip_through_json():
    observation = obs(
        kind="agent",
        label="Explorer le dépôt",
        activity="Read · agent_tasks.py",
        summary="",
        model="modele-x",
        parent_external_id="task-0",
        link=WorkLink(work_id="work-1", correlation_id="corr-1"),
        progress_fraction=0.25,
        tool_uses=3,
        tokens=1200,
        background=True,
        started_at=at(-30),
    )
    wire = json.loads(json.dumps(observation.to_payload()))
    assert WorkObservation.from_payload(wire) == observation
    assert jsonable(observation) == observation.to_payload()

    item = created(status=WorkStatus.FAILED, error_class="provider_unavailable", summary="Source injoignable.")
    assert WorkItem.from_payload(json.loads(json.dumps(item.to_payload()))) == item

    snapshot = WorkSnapshot(revision=4, items=(item, created(external_id="task-2")), updated_at=at(1))
    assert WorkSnapshot.from_payload(json.loads(json.dumps(snapshot.to_payload()))) == snapshot
    assert jsonable(snapshot) == snapshot.to_payload()


def test_from_payload_drops_unknown_provider_fields():
    payload = obs().to_payload()
    payload.update(
        raw={"type": "system", "subtype": "task_progress", "usage": {"total_tokens": 9}},
        subagent_type="Explore",
        prompt="consigne complète du sous-agent",
        tool_use_id="toolu_01",
    )
    restored = WorkObservation.from_payload(payload)
    assert restored == obs()
    assert set(restored.to_payload()) == set(obs().to_payload())


@pytest.mark.parametrize(
    ("patch", "error"),
    [
        ({"status": "exploded"}, ValueError),
        ({"status": None}, ValueError),
        ({"progress_fraction": 2}, ValueError),
        ({"progress_fraction": "0.5"}, TypeError),
        ({"label": ["liste"]}, TypeError),
        ({"work_id": 7}, TypeError),
        ({"observed_at": None}, TypeError),
        ({"observed_at": "2026-09-11T14:00:00"}, ValueError),
        ({"background": "true"}, TypeError),
    ],
)
def test_from_payload_rejects_invalid_wire_values(patch, error):
    payload = obs().to_payload()
    payload.update(patch)
    with pytest.raises(error):
        WorkObservation.from_payload(payload)


def test_snapshot_from_payload_refuses_oversized_lists_before_decoding():
    payload = {"revision": 1, "items": [{}] * (MAX_WORK_ITEMS + 1), "updated_at": at(0).isoformat()}
    with pytest.raises(ValueError):
        WorkSnapshot.from_payload(payload)


def test_empty_wire_identifiers_mean_unknown():
    payload = obs().to_payload()
    payload.update(work_id="", correlation_id=None, parent_external_id="")
    restored = WorkObservation.from_payload(payload)
    assert restored.link == WorkLink()
    assert restored.parent_external_id is None


# --- identifiants : fournisseur ≠ cerveau ------------------------------------


def test_external_id_is_never_taken_for_a_work_id():
    # Même quand l'identifiant externe ou le libellé ressemblent à un work_id.
    item = created(external_id="work-1", label="work-2")
    assert item.link == WorkLink()
    assert item.link.known is False
    assert item.link.work_id is None


def test_explicit_link_maps_work_id_external_id_and_correlation():
    item = created(source="jobs", external_id="job-9", link=WorkLink(work_id="work-1", correlation_id="corr-1"))
    assert item.key == ("jobs", "job-9")
    assert item.link.work_id == "work-1"
    assert item.link.correlation_id == "corr-1"
    wire = item.to_payload()
    assert (wire["external_id"], wire["work_id"], wire["correlation_id"]) == ("job-9", "work-1", "corr-1")


def test_link_merge_completes_unknowns_and_never_rewrites_known_values():
    merged, conflicts = WorkLink(correlation_id="corr-1").merge(WorkLink(work_id="work-1"))
    assert merged == WorkLink(work_id="work-1", correlation_id="corr-1")
    assert conflicts == ()

    kept, conflicts = merged.merge(WorkLink(work_id="work-2", correlation_id="corr-1"))
    assert kept == merged
    assert conflicts == ("work_id",)


def test_late_link_is_applied_and_conflicting_link_is_reported_not_applied():
    item = created()
    linked = apply_observation(item, obs(observed_at=at(1), link=WorkLink(work_id="work-1")), revision=2)
    assert linked.outcome is ObservationOutcome.UPDATED
    assert linked.item.link.work_id == "work-1"

    contradicted = apply_observation(
        linked.item, obs(observed_at=at(2), link=WorkLink(work_id="work-9")), revision=3
    )
    assert contradicted.outcome is ObservationOutcome.DUPLICATE
    assert contradicted.item.link.work_id == "work-1"
    assert contradicted.conflicts == ("work_id",)


# --- ordre, doublons, terminalité --------------------------------------------


def test_first_observation_creates_the_item_with_its_start():
    item = created(started_at=at(-5), background=None)
    assert item.revision == 1
    assert item.started_at == at(-5)
    assert item.updated_at == at(0)
    assert item.ended_at is None
    assert item.background is False


def test_duplicate_observation_is_idempotent():
    item = created(activity="Read · a.py")
    again = apply_observation(item, obs(activity="Read · a.py"), revision=2)
    assert again.outcome is ObservationOutcome.DUPLICATE
    assert again.changed is False
    assert again.item is item

    # Même contenu constaté plus tard : pas de nouvelle révision.
    later = apply_observation(item, obs(activity="Read · a.py", observed_at=at(9)), revision=2)
    assert later.outcome is ObservationOutcome.DUPLICATE
    assert later.item.revision == 1


def test_update_merges_fields_and_takes_the_new_revision():
    item = created(kind="agent", label="Analyse", model="modele-x", tokens=10, activity="Read · a.py")
    update = apply_observation(item, obs(observed_at=at(3), activity="", tokens=40, tool_uses=2), revision=7)
    assert update.outcome is ObservationOutcome.UPDATED
    merged = update.item
    assert merged.revision == 7
    assert merged.updated_at == at(3)
    # Non observé cette fois : la valeur connue reste.
    assert (merged.kind, merged.label, merged.model) == ("agent", "Analyse", "modele-x")
    # L'activité décrit l'instant : vide, elle dit « rien en ce moment ».
    assert merged.activity == ""
    assert (merged.tokens, merged.tool_uses) == (40, 2)


def test_late_progress_never_rewinds_the_known_state():
    item = apply_observation(created(activity="étape 1"), obs(observed_at=at(5), activity="étape 2"), revision=2).item
    late = apply_observation(item, obs(observed_at=at(3), activity="étape 1 bis"), revision=3)
    assert late.outcome is ObservationOutcome.STALE
    assert late.item.activity == "étape 2"


def test_terminal_observation_ends_the_work_even_when_it_arrives_late():
    item = apply_observation(created(started_at=at(-10)), obs(observed_at=at(5), activity="encore"), revision=2).item
    done = apply_observation(
        item, obs(status=WorkStatus.COMPLETED, observed_at=at(4), summary="Trois messages à traiter."), revision=3
    )
    assert done.outcome is ObservationOutcome.UPDATED
    assert done.item.status is WorkStatus.COMPLETED
    assert done.item.ended_at == at(4)
    assert done.item.activity == ""
    assert done.item.updated_at == at(5)


def test_terminal_item_is_never_reopened_by_stale_or_late_observations():
    done = apply_observation(created(), obs(status=WorkStatus.FAILED, observed_at=at(2), error_class="timeout"), revision=2).item

    for status in (WorkStatus.RUNNING, WorkStatus.PENDING, WorkStatus.BLOCKED, WorkStatus.COMPLETED):
        update = apply_observation(done, obs(status=status, observed_at=at(9)), revision=3)
        assert update.outcome is ObservationOutcome.TERMINAL
        assert update.item is done


def test_same_terminal_status_may_only_enrich_description():
    done = apply_observation(created(), obs(status=WorkStatus.COMPLETED, observed_at=at(2)), revision=2).item
    enriched = apply_observation(
        done, obs(status=WorkStatus.COMPLETED, observed_at=at(3), summary="Résumé final.", tokens=900), revision=3
    )
    assert enriched.outcome is ObservationOutcome.UPDATED
    assert enriched.item.summary == "Résumé final."
    assert enriched.item.tokens == 900
    assert enriched.item.ended_at == at(2)

    stale = apply_observation(enriched.item, obs(status=WorkStatus.COMPLETED, observed_at=at(1), summary="vieux"), revision=4)
    assert stale.outcome is ObservationOutcome.STALE


def test_started_work_cannot_go_back_to_pending():
    update = apply_observation(created(), obs(status=WorkStatus.PENDING, observed_at=at(1)), revision=2)
    assert update.outcome is ObservationOutcome.INVALID_TRANSITION
    assert update.item.status is WorkStatus.RUNNING


def test_blocked_work_is_not_terminal_and_can_resume():
    blocked = apply_observation(created(), obs(status=WorkStatus.BLOCKED, observed_at=at(1), summary="Quel dossier ?"), revision=2).item
    assert not blocked.status.is_terminal and blocked.ended_at is None
    resumed = apply_observation(blocked, obs(observed_at=at(2)), revision=3)
    assert resumed.item.status is WorkStatus.RUNNING


def test_error_class_does_not_survive_into_another_status():
    failed = created(status=WorkStatus.FAILED, error_class="provider_unavailable")
    assert failed.error_class == "provider_unavailable"
    enriched = apply_observation(failed, obs(status=WorkStatus.FAILED, observed_at=at(1), summary="Injoignable."), revision=2)
    assert enriched.item.error_class == "provider_unavailable"


def test_start_is_the_earliest_known_and_parent_is_fixed_once_known():
    item = created(parent_external_id="parent-a")
    update = apply_observation(item, obs(observed_at=at(1), started_at=at(-20), parent_external_id="parent-b"), revision=2)
    assert update.item.started_at == at(-20)
    assert update.item.parent_external_id == "parent-a"
    assert update.conflicts == ("parent_external_id",)


def test_apply_observation_guards_its_own_preconditions():
    item = created()
    with pytest.raises(ValueError):
        apply_observation(item, obs(external_id="task-2"), revision=2)
    with pytest.raises(ValueError):
        apply_observation(item, obs(source="jobs"), revision=2)
    with pytest.raises(ValueError):
        apply_observation(item, obs(observed_at=at(1)), revision=1)


# --- neutralité fournisseur --------------------------------------------------


def test_claude_subtask_and_generic_job_share_the_same_contract():
    subtask = obs(
        source="claude",
        external_id="a1b2c3",
        kind="agent",
        label="Persist voice arch setting",
        activity="Edit · v2_config.py",
        model="modele-x",
        parent_external_id="toolu_parent",
        tool_uses=12,
        tokens=48_000,
        background=True,
        started_at=at(-60),
    )
    job = obs(
        source="jobs",
        external_id="5f0c-job",
        kind="mail_search",
        status=WorkStatus.RUNNING,
        label="Recherche des mails de Paul",
        summary="Messages trouvés ; vérification des réunions.",
        progress_fraction=0.4,
        link=WorkLink(work_id="work-1", correlation_id="corr-1"),
    )
    items = []
    for revision, observation in enumerate((subtask, job), start=1):
        update = apply_observation(None, observation, revision=revision)
        items.append(update.item)
        assert set(observation.to_payload()) == set(obs().to_payload())
    snapshot = WorkSnapshot(revision=2, items=tuple(items), updated_at=at(0))
    assert WorkSnapshot.from_payload(json.loads(json.dumps(snapshot.to_payload()))) == snapshot


@pytest.mark.parametrize("contract", [WorkObservation, WorkItem, WorkSnapshot, WorkLink])
def test_contracts_carry_no_provider_specific_or_reasoning_field(contract):
    for name in (f.name for f in dataclasses.fields(contract)):
        lowered = name.lower()
        assert not any(marker in lowered for marker in PROVIDER_MARKERS), f"{contract.__name__}.{name}"
        assert not any(marker in lowered for marker in REASONING_MARKERS), f"{contract.__name__}.{name}"


def test_contracts_are_immutable():
    item = created()
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.status = WorkStatus.COMPLETED  # type: ignore[misc]


# --- ports -------------------------------------------------------------------


class _FoldingStore:
    """Magasin minimal de référence : il n'applique que les règles pures.

    Montre la forme attendue de la tâche 11 — révision globale avancée
    seulement quand un élément change — sans la présumer davantage.
    """

    def __init__(self) -> None:
        self.revision = 0
        self.items: dict[tuple[str, str], WorkItem] = {}
        self.updated_at = T0

    async def observe(self, observation: WorkObservation) -> None:
        update = apply_observation(self.items.get(observation.key), observation, revision=self.revision + 1)
        if update.changed:
            self.revision = update.item.revision
            self.items[observation.key] = update.item
            self.updated_at = max(self.updated_at, update.item.updated_at)

    async def snapshot(self) -> WorkSnapshot:
        return WorkSnapshot(revision=self.revision, items=tuple(self.items.values()), updated_at=self.updated_at)


@pytest.mark.asyncio
async def test_ports_can_be_implemented_by_folding_the_pure_rules():
    store = _FoldingStore()
    sink: WorkObservationSink = store
    reader: WorkStateReader = store

    await sink.observe(obs())
    await sink.observe(obs())  # doublon : pas de révision
    await sink.observe(obs(observed_at=at(1), activity="Read · a.py"))
    await sink.observe(obs(status=WorkStatus.INTERRUPTED, observed_at=at(2)))
    await sink.observe(obs(observed_at=at(3)))  # ne rouvre pas

    snapshot = await reader.snapshot()
    assert snapshot.revision == 3
    (item,) = snapshot.items
    assert item.status is WorkStatus.INTERRUPTED
    assert item.revision == 3
