"""Worker d'enrichissement du Context actif (Slice 08 session-context) : modèle factice, bases temporaires.

Contrat : `docs/session-context.md` › *Enrichment worker*. Couvre : tour,
provenance, curseur durable, rejeu idempotent (mort entre `summary.md` et le
curseur), reprise après redémarrage, attente/coalescence, course au changement
de Context, bornes d'une longue transcription, révision d'un point ouvert,
fournisseur absent, délai, captures d'écran.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re

import pytest

from jarvis.core.context_enrichment import (
    CURSOR_FILE, MAX_BATCH_EVENTS, MAX_EVIDENCE_BYTES, MAX_LINE_CHARS, MAX_PROMPT_BYTES, MAX_SUMMARY_BYTES,
    SUMMARY_FILE, ContextEnrichmentWorker, EnrichmentCursor, normalize_summary,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactKind, ArtifactRelationKind, ArtifactState
from jarvis.ports.artifacts import RelationDirection
from jarvis.domain.session_activity import ActivityKind
from jarvis.ports.context_enrichment import (
    MODEL_TIMEOUT, MODEL_UNAVAILABLE, EnrichmentModelError, EnrichmentReply,
)
from jarvis.ports.session_context import ContextWorkspaceError


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.lines.append((kind, level, message, dict(data or {})))

    def of(self, kind: str) -> list[dict]:
        return [data for k, _, _, data in self.lines if k == kind]


class FakeModel:
    """Modèle sans outil scripté : `script(prompt, call)` rend le texte ; sinon fusion des puces sans doublon."""

    model = "fake-haiku"

    def __init__(self, script=None, *, supports_images: bool = True, cost: float = 0.002) -> None:
        self.script = script
        self.supports_images = supports_images
        self.cost = cost
        self.prompts: list[str] = []
        self.images: list[tuple] = []

    async def complete(self, prompt, *, timeout_s, images=()):
        self.prompts.append(prompt)
        self.images.append(images)
        if images:
            return EnrichmentReply(text="Un éditeur de code montre un test rouge.", model=self.model, cost_usd=self.cost)
        if self.script is not None:
            text = self.script(prompt, len(self.prompts))
            if asyncio.iscoroutine(text):
                text = await text
        else:
            text = merge_bullets(prompt)
        return EnrichmentReply(text=text, model=self.model, cost_usd=self.cost, duration_ms=12)


def section(prompt: str, title: str) -> str:
    match = re.search(re.escape(title) + r".*?:\n<<<\n(.*?)\n>>>", prompt, re.S)
    assert match, title
    return match.group(1)


def merge_bullets(prompt: str) -> str:
    """Résumé = puces du résumé précédent ∪ une puce par référence de preuve (ordre stable)."""

    previous = section(prompt, "RÉSUMÉ ACTUEL")
    bullets = [line for line in previous.splitlines() if line.startswith("- ")]
    for line in section(prompt, "NOUVELLES PREUVES").splitlines():
        ref = re.search(r"\[[^\]]+\]", line)
        bullet = f"- vu {ref.group(0)}" if ref else None
        if bullet and bullet not in bullets:
            bullets.append(bullet)
    return "# Travail\n" + "\n".join(bullets)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def core(tmp_path):
    app = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await app.start()
    await app.context_enrichment.close()  # la boucle de Core ne court pas pendant les pas manuels
    app.journal_for_tests = journal  # type: ignore[attr-defined]
    try:
        yield app
    finally:
        await app.stop()


def worker(core, model, clock, **kwargs) -> ContextEnrichmentWorker:
    return ContextEnrichmentWorker(core.sessions, core.artifacts, lambda: model, diagnostics=core.journal_for_tests,
                                   clock=clock, debounce_s=kwargs.pop("debounce_s", 0.0),
                                   max_delay_s=kwargs.pop("max_delay_s", 60.0),
                                   min_interval_s=kwargs.pop("min_interval_s", 0.0), **kwargs)


class Recording:
    """Un enregistrement audio et ses segments, injectés comme le fait `RecordingTranscriber`."""

    def __init__(self, core, view) -> None:
        self.core, self.view = core, view
        self.audio = None
        self.seq = 0

    async def open(self):
        ctx = self.view.context
        self.audio = await self.core.artifacts.create(
            kind=ArtifactKind.AUDIO_RECORDING, source="capture.audio", jarvis_session_id=ctx.jarvis_session_id,
            context_id=ctx.context_id, payload_name="audio.wav")
        return self

    async def say(self, text: str, *, start_ms: int | None = None):
        seq = self.seq
        self.seq += 1
        start = start_ms if start_ms is not None else seq * 5_000
        ctx = self.view.context
        return await self.core.artifacts.record_text(
            artifact_id=f"{self.audio.artifact_id}_seg{seq}", kind=ArtifactKind.TRANSCRIPT_SEGMENT, source="stt",
            text=text, jarvis_session_id=ctx.jarvis_session_id, context_id=ctx.context_id, started_at=None,
            ended_at=None, duration_ms=4_000,
            metadata={"audio_artifact_id": self.audio.artifact_id, "seq": seq, "start_ms": start,
                      "end_ms": start + 4_000},
            origins=((ArtifactRelationKind.TRANSCRIBED_FROM, self.audio.artifact_id),),
            event=(ActivityKind.TRANSCRIPT_SEGMENT_CREATED, {"seq": seq, "start_ms": start, "chars": len(text)}))


async def recording(core) -> Recording:
    return await Recording(core, await core.sessions.current_context()).open()


def folder(view) -> Path:
    return Path(view.workspace_path)


def cursor_of(view) -> dict | None:
    path = folder(view) / CURSOR_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------------ un tour


async def test_a_round_rewrites_summary_with_provenance_then_advances_the_durable_cursor(core):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    await rec.say("On commence la revue du module de paiement.")
    await rec.say("Le test d'intégration échoue encore.")
    w = worker(core, model, clock)
    assert await w.tick() == "round"
    view = rec.view
    summary = (folder(view) / SUMMARY_FILE).read_text(encoding="utf-8")
    audio = rec.audio.artifact_id
    assert f"[{audio}@00:00]" in summary and f"[{audio}@00:05]" in summary
    evidence = section(model.prompts[0], "NOUVELLES PREUVES")
    assert "(salle) On commence la revue" in evidence and f"[{audio}@00:05]" in evidence
    latest = await core.artifacts.latest_seq()
    assert cursor_of(view)["after_seq"] == latest and cursor_of(view)["context_id"] == view.context.context_id
    # Journal : ids, tailles, coût ; jamais le texte de la salle (D17).
    (round_,) = core.journal_for_tests.of("core.context_enrichment.round")
    assert round_["cost_usd"] == pytest.approx(0.002) and round_["n_segments"] == 2 and round_["to_seq"] == latest
    assert all("paiement" not in json.dumps(data, ensure_ascii=False) + message
               for _, _, message, data in core.journal_for_tests.lines)
    assert w.status()["rounds"] == 1 and w.status()["total_cost_usd"] == pytest.approx(0.002)
    assert await w.tick() == "idle" and len(model.prompts) == 1


async def test_nothing_interpretable_advances_the_cursor_without_a_model_call(core):
    clock, model = Clock(), FakeModel()
    view = await core.sessions.current_context()
    await core.artifacts.record(ActivityKind.TRANSCRIPT_PROJECTION_UPDATED, jarvis_session_id=view.context.jarvis_session_id,
                                context_id=view.context.context_id)
    w = worker(core, model, clock)
    assert await w.tick() == "skipped"
    assert model.prompts == [] and not (folder(view) / SUMMARY_FILE).exists()
    assert cursor_of(view)["after_seq"] == await core.artifacts.latest_seq()


# ------------------------------------------------------------------ attente et coalescence


async def test_debounce_coalesces_a_burst_into_one_round(core):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    w = worker(core, model, clock, debounce_s=15.0, max_delay_s=60.0)
    await rec.say("premier")
    assert await w.tick() == "waiting"
    clock.now += 5
    await rec.say("deuxième")
    assert await w.tick() == "waiting"
    clock.now += 14  # 14 s de calme depuis le dernier segment
    assert await w.tick() == "waiting"
    clock.now += 1
    assert await w.tick() == "round"
    assert len(model.prompts) == 1
    evidence = section(model.prompts[0], "NOUVELLES PREUVES")
    assert "premier" in evidence and "deuxième" in evidence


async def test_continuous_speech_still_lands_within_max_delay_and_rounds_are_spaced(core):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    w = worker(core, model, clock, debounce_s=15.0, max_delay_s=60.0, min_interval_s=30.0)
    outcomes = []
    for _ in range(7):  # un segment toutes les 10 s : jamais 15 s de calme
        await rec.say("encore")
        outcomes.append(await w.tick())
        clock.now += 10
    assert outcomes[:6] == ["waiting"] * 6 and outcomes[6] == "round"  # 60 s après la première preuve
    round_at = clock.now - 10
    await rec.say("après le tour")
    assert await w.tick() == "waiting"
    clock.now += 16  # 16 s de calme, mais 26 s seulement depuis le tour
    assert clock.now - round_at < 30 and await w.tick() == "waiting"
    clock.now += 4
    assert await w.tick() == "round"
    assert len(model.prompts) == 2


# ------------------------------------------------------------------ rejeu et reprise


async def test_a_crash_between_summary_and_cursor_replays_the_same_batch_without_duplication(core, monkeypatch):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    await rec.say("Le build échoue sur Windows.")
    await rec.say("On soupçonne le chemin trop long.")
    workspaces = core.sessions._workspaces
    real_write = workspaces.write_file
    failures = {"left": 1}

    def flaky(workspace, name, text):
        if name == CURSOR_FILE and failures["left"]:
            failures["left"] -= 1
            raise ContextWorkspaceError("context_workspace_failed", Path(workspace) / name, "disk full (simulated)")
        return real_write(workspace, name, text)

    monkeypatch.setattr(workspaces, "write_file", flaky)
    w = worker(core, model, clock)
    assert await w.tick() == "failed"
    view = rec.view
    first = (folder(view) / SUMMARY_FILE).read_text(encoding="utf-8")
    assert cursor_of(view) is None and w.status()["state"] == "backoff"
    assert await w.tick() == "backoff"
    # Mort entre les deux écritures : une nouvelle vie n'a pas la sortie gardée en mémoire.
    fresh = worker(core, model, clock)
    assert await fresh.tick() == "round"
    # Même lot rejoué, depuis un résumé qui le contient déjà : aucune puce en double.
    assert section(model.prompts[1], "NOUVELLES PREUVES") == section(model.prompts[0], "NOUVELLES PREUVES")
    assert section(model.prompts[1], "RÉSUMÉ ACTUEL") == first.strip()
    second = (folder(view) / SUMMARY_FILE).read_text(encoding="utf-8")
    bullets = [line for line in second.splitlines() if line.startswith("- ")]
    assert len(bullets) == len(set(bullets)) == 2 and second == first
    assert cursor_of(view)["after_seq"] == await core.artifacts.latest_seq()


async def test_a_refused_cursor_in_the_same_life_rewrites_the_kept_output_without_a_model_call(core, monkeypatch):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    await rec.say("Le build échoue sur Windows.")
    workspaces = core.sessions._workspaces
    real_write = workspaces.write_file
    failures = {"left": 1}

    def flaky(workspace, name, text):
        if name == CURSOR_FILE and failures["left"]:
            failures["left"] -= 1
            raise ContextWorkspaceError("context_workspace_failed", Path(workspace) / name, "disk full (simulated)")
        return real_write(workspace, name, text)

    monkeypatch.setattr(workspaces, "write_file", flaky)
    w = worker(core, model, clock)
    assert await w.tick() == "failed"
    first = (folder(rec.view) / SUMMARY_FILE).read_text(encoding="utf-8")
    clock.now += 31
    assert await w.tick() == "round" and len(model.prompts) == 1
    assert (folder(rec.view) / SUMMARY_FILE).read_text(encoding="utf-8") == first
    assert cursor_of(rec.view)["after_seq"] == await core.artifacts.latest_seq()


async def test_a_restarted_worker_resumes_from_the_cursor_file(core):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    await rec.say("avant le redémarrage")
    assert await worker(core, model, clock).tick() == "round"
    fresh = worker(core, model, clock)  # nouvelle vie : rien en mémoire
    assert await fresh.tick() == "idle" and len(model.prompts) == 1
    await rec.say("après le redémarrage")
    assert await fresh.tick() == "round"
    evidence = section(model.prompts[1], "NOUVELLES PREUVES")
    assert "après le redémarrage" in evidence and "avant le redémarrage" not in evidence


async def test_a_cursor_file_out_of_contract_restarts_from_the_context_birth(core):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    await rec.say("une phrase")
    (folder(rec.view) / CURSOR_FILE).write_text("{not json", encoding="utf-8")
    assert await worker(core, model, clock).tick() == "round"
    assert core.journal_for_tests.of("core.context_enrichment.cursor_reset")
    assert EnrichmentCursor.parse(json.dumps({"version": 1, "context_id": "jctx_other", "after_seq": 3}),
                                  rec.view.context.context_id) is None


# ------------------------------------------------------------------ frontière de Context


async def test_a_context_switch_during_the_model_call_writes_nothing_into_the_dormant_context(core):
    clock = Clock()
    rec = await recording(core)
    old = rec.view
    await rec.say("dans le premier Context")

    async def switch_then_answer(prompt, call):
        if call == 1:
            await core.sessions.create_context(title="Second")
        return merge_bullets(prompt)

    model = FakeModel(switch_then_answer)
    w = worker(core, model, clock)
    assert await w.tick() == "context_switched"
    assert not (folder(old) / SUMMARY_FILE).exists() and not (folder(old) / CURSOR_FILE).exists()
    assert core.journal_for_tests.of("core.context_enrichment.context_switched")
    new = await core.sessions.current_context()
    assert new.context.context_id != old.context.context_id
    # Le nouveau Context part de sa naissance : la parole d'avant ne lui appartient pas (D05).
    assert await w.tick() in {"idle", "skipped"}
    assert len(model.prompts) == 1 and not (folder(new) / SUMMARY_FILE).exists()
    # Parole pendant le second Context, puis retour au premier : seules ses preuves à lui.
    other = await Recording(core, new).open()
    await other.say("pendant le second Context")
    assert await w.tick() == "round"
    assert "pendant le second Context" in section(model.prompts[-1], "NOUVELLES PREUVES")
    await core.sessions.activate_context(old.context.context_id)
    assert await w.tick() == "round"
    evidence = section(model.prompts[-1], "NOUVELLES PREUVES")
    assert "dans le premier Context" in evidence and "pendant le second Context" not in evidence
    assert (folder(old) / SUMMARY_FILE).exists()


async def test_the_write_guard_refuses_a_dormant_context_under_the_transition_lock(core):
    first = await core.sessions.current_context()
    await core.sessions.create_context(title="B")
    assert await core.sessions.write_active_context_files(first.context.context_id, ((SUMMARY_FILE, "x"),)) is None
    assert not (folder(first) / SUMMARY_FILE).exists()


# ------------------------------------------------------------------ bornes


async def test_a_long_transcript_is_consumed_in_bounded_rounds_without_loss_or_duplicate(core):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    for index in range(130):
        await rec.say(f"phrase {index:03d} " + "bla " * 100)
    await rec.say("énorme " * 2_200)  # un segment de 15 400 caractères est coupé
    w = worker(core, model, clock)
    for _ in range(60):
        if await w.tick() == "idle":
            break
    assert w.status()["after_seq"] == await core.artifacts.latest_seq()
    seen: list[str] = []
    for prompt in model.prompts:
        assert len(prompt.encode("utf-8")) <= MAX_PROMPT_BYTES
        evidence = section(prompt, "NOUVELLES PREUVES")
        assert len(evidence.encode("utf-8")) <= MAX_EVIDENCE_BYTES + 2 * MAX_LINE_CHARS
        assert all(len(line) <= MAX_LINE_CHARS for line in evidence.splitlines())
        seen += re.findall(r"phrase (\d{3})", evidence)
    assert seen == [f"{i:03d}" for i in range(130)]
    assert len(model.prompts) >= 5
    assert any("énorme" in prompt for prompt in model.prompts)
    summary = (folder(rec.view) / SUMMARY_FILE).read_bytes()
    assert len(summary) <= MAX_SUMMARY_BYTES


async def test_a_backlog_page_full_does_not_wait_for_quiet(core):
    clock, model = Clock(), FakeModel()
    rec = await recording(core)
    for index in range(MAX_BATCH_EVENTS // 3 + 2):
        await rec.say(f"s{index}")
    w = worker(core, model, clock, debounce_s=999.0, max_delay_s=999.0)
    assert await w.tick() == "round"


def test_model_output_is_unfenced_and_clipped_on_whole_lines():
    text, clipped = normalize_summary("```markdown\n# T\n" + "\n".join(f"- ligne {i} " + "x" * 50 for i in range(80)) + "\n```")
    assert not text.startswith("```") and clipped and len(text.encode("utf-8")) <= MAX_SUMMARY_BYTES
    assert all(line.startswith(("# T", "- ligne")) for line in text.strip().splitlines())
    with pytest.raises(EnrichmentModelError):
        normalize_summary("  \n```\n```")


# ------------------------------------------------------------------ révision sémantique


async def test_later_evidence_moves_an_open_point_to_resolved(core):
    clock = Clock()
    rec = await recording(core)
    await rec.say("Le build Windows échoue, chemin trop long.")
    audio = rec.audio.artifact_id

    def scripted(prompt, call):
        if call == 1:
            return f"# Build\n## Points ouverts\n- Build Windows en échec (chemin trop long) [{audio}@00:00]"
        assert "Build Windows en échec" in section(prompt, "RÉSUMÉ ACTUEL")
        assert "c'est réglé" in section(prompt, "NOUVELLES PREUVES")
        return f"# Build\n## Résolu\n- Build Windows réparé : chemin raccourci [{audio}@00:00] [{audio}@00:05]"

    model = FakeModel(scripted)
    w = worker(core, model, clock)
    assert await w.tick() == "round"
    await rec.say("J'ai raccourci le chemin, le build passe, c'est réglé.")
    assert await w.tick() == "round"
    summary = (folder(rec.view) / SUMMARY_FILE).read_text(encoding="utf-8")
    assert "## Résolu" in summary and "## Points ouverts" not in summary
    # La preuve brute n'a pas bougé.
    segment = await core.artifacts.get(f"{audio}_seg0")
    assert segment.text == "Le build Windows échoue, chemin trop long."


# ------------------------------------------------------------------ fournisseur et délais


async def test_no_provider_leaves_the_worker_unavailable_and_the_cursor_untouched(core):
    clock = Clock()
    rec = await recording(core)
    await rec.say("parole")
    w = ContextEnrichmentWorker(core.sessions, core.artifacts, lambda: None, diagnostics=core.journal_for_tests,
                                clock=clock, debounce_s=0, min_interval_s=0)
    assert await w.tick() == "unavailable" and await w.tick() == "unavailable"
    assert w.status()["state"] == "unavailable" and w.status()["code"] == MODEL_UNAVAILABLE
    assert cursor_of(rec.view) is None and not (folder(rec.view) / SUMMARY_FILE).exists()
    assert len(core.journal_for_tests.of("core.context_enrichment.unavailable")) == 1


async def test_a_hanging_model_times_out_backs_off_and_keeps_the_evidence(core):
    clock = Clock()
    rec = await recording(core)
    await rec.say("parole")

    class Hanging(FakeModel):
        async def complete(self, prompt, *, timeout_s, images=()):
            await asyncio.sleep(3600)

    w = worker(core, Hanging(), clock, timeout_s=0.01)
    assert await w.tick() == "failed"
    assert w.status()["code"] == MODEL_TIMEOUT and w.status()["state"] == "backoff"
    assert cursor_of(rec.view) is None
    (failed,) = core.journal_for_tests.of("core.context_enrichment.failed")
    assert failed["code"] == MODEL_TIMEOUT and failed["retry_in_s"] == 30.0
    clock.now += 31
    w._model = lambda: FakeModel()
    assert await w.tick() == "round"


async def test_a_provider_error_is_said_with_its_own_cause(core):
    clock = Clock()
    rec = await recording(core)
    await rec.say("parole")

    class Broken(FakeModel):
        async def complete(self, prompt, *, timeout_s, images=()):
            raise EnrichmentModelError("enrichment_model_failed", "Credit balance is too low")

    w = worker(core, Broken(), clock)
    assert await w.tick() == "failed"
    (_, level, message, data) = next(line for line in core.journal_for_tests.lines
                                     if line[0] == "core.context_enrichment.failed")
    assert level == "error" and "Credit balance is too low" in message


# ------------------------------------------------------------------ captures d'écran


async def screenshot(core, view, data: bytes = b"\x89PNG fake"):
    ctx = view.context
    shot = await core.artifacts.create(kind=ArtifactKind.SCREENSHOT, source="capture.screen",
                                       jarvis_session_id=ctx.jarvis_session_id, context_id=ctx.context_id,
                                       payload_name="screenshot.png", mime_type="image/png")
    return await core.artifacts.store_payload(shot.artifact_id, data, width=10, height=10)


async def test_a_screenshot_gets_one_description_artifact_reused_on_replay(core):
    clock, model = Clock(), FakeModel()
    view = await core.sessions.current_context()
    shot = await screenshot(core, view)
    w = worker(core, model, clock)
    assert await w.tick() == "round"
    description = await core.artifacts.get(f"{shot.artifact_id}_desc")
    assert description.kind is ArtifactKind.DESCRIPTION and description.state is ArtifactState.COMPLETE
    assert description.text == "Un éditeur de code montre un test rouge."
    relations = await core.artifacts.relations(description.artifact_id, RelationDirection.ORIGINS)
    assert [(r.relation, r.origin_artifact_id) for r in relations] == [
        (ArtifactRelationKind.DESCRIBED_FROM, shot.artifact_id)]
    assert model.images[0][0].data == b"\x89PNG fake" and model.images[0][0].media_type == "image/png"
    evidence = section(model.prompts[1], "NOUVELLES PREUVES")
    assert f"[{shot.artifact_id}] capture d'écran (complete) : Un éditeur de code" in evidence
    # Rejeu du même lot : la description existe, aucun nouvel appel image.
    (folder(view) / CURSOR_FILE).unlink()
    replay = worker(core, model, clock)
    assert await replay.tick() == "round"
    assert sum(1 for images in model.images if images) == 1
    # L'Artifact de description, créé par le worker, n'est pas repris comme preuve nouvelle.
    assert "Un éditeur" in section(model.prompts[-1], "NOUVELLES PREUVES")
    assert section(model.prompts[-1], "NOUVELLES PREUVES").count("capture d'écran") == 1


async def test_a_model_without_vision_skips_the_description_with_a_status(core):
    clock, model = Clock(), FakeModel(supports_images=False)
    view = await core.sessions.current_context()
    shot = await screenshot(core, view)
    assert await worker(core, model, clock).tick() == "round"
    assert [d["code"] for d in core.journal_for_tests.of("core.context_enrichment.screenshot_skipped")] == [
        "screenshot_description_unsupported"]
    with pytest.raises(Exception):
        await core.artifacts.get(f"{shot.artifact_id}_desc")


# ------------------------------------------------------------------ boucle de Core


async def test_core_runs_the_worker_and_stops_it(tmp_path):
    model = FakeModel()
    app = JarvisCoreApplication(data_root=tmp_path, diagnostics=Journal(), context_enrichment=lambda: model)
    await app.start()
    try:
        assert app.context_enrichment.status()["state"] in {"idle", "waiting"}
    finally:
        await app.stop()
    assert app.context_enrichment.status()["state"] == "stopped"


def test_the_worker_and_the_folder_adapter_name_the_same_files():
    from jarvis.adapters import context_workspace

    assert (SUMMARY_FILE, CURSOR_FILE) == (context_workspace.SUMMARY_FILE, context_workspace.ENRICHMENT_CURSOR_FILE)
    assert {SUMMARY_FILE, CURSOR_FILE} <= context_workspace.KNOWN_FILES
    with pytest.raises(ValueError):
        context_workspace.write_context_file(Path("."), "notes.md", "x")
