"""`speech.stale_supersession` v4 — la conversation accélérée, déclarée avant d'être au vert.

Test ROUGE de la Slice 01 (tâche `jarvis-voice-stale-speech-presentation`, T8),
que la Slice 04 doit faire passer.

v4 remplace, pour la suite, la moitié « réponse reportée » de v3 (décision du
19/09/2026) par la décision du 28/09/2026 : une formulation rédigée pour une
intention passée ne démarre jamais d'elle-même ; la réponse de l'intention
courante passe d'abord. Nouvelle métrique : `speech.stale_formulation_started_count`
(bloquante, `eq 0`).

**Publication (Slice 04).** Écrite par la Slice 01 hors du catalogue
(`tests/fixtures/testlab_unpublished/`), v4 est publiée par la Slice 04 dans
`jarvis/testlab/official/speech/stale_supersession.v4.json` avec son entrée de
verrou ; le scénario porte désormais un `expect.metric` sur la nouvelle métrique,
que le runner mesure. Seul le montage de ce test a changé (le catalogue officiel
au lieu d'une copie augmentée) ; ses assertions sont celles de la Slice 01.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from jarvis.runtime.journal import RuntimeJournal
from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.diagnostics import resolve_parameters
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runners import RunArtifacts, RunContext
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun
from jarvis.testlab.selftest import catalog_implementations
from jarvis.testlab.virtual.runners import StaleSupersessionRunner
from tests.fakes.testlab import CONFIG, ENVIRONMENT, NONCE, REVISION, T0

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "jarvis" / "testlab" / "official"
RUN_ID = format_run_id(T0, NONCE)
RUN_BUDGET_S = 120.0
NEW_METRIC = "speech.stale_formulation_started_count"


def catalog_with_v4(root: Path):
    """The official catalog, where v4 is published and locked (Slice 04). `root` is unused."""
    del root
    return load_catalog(OFFICIAL, implementations=catalog_implementations())


def run_context(tmp_path: Path, entry) -> RunContext:
    """A `RunContext` on a real run store, as `test_testlab_virtual_runners.build_context` builds one."""
    spec = entry.diagnostic
    parameters = resolve_parameters(spec.parameters, {})
    store = FilesystemTestRunStore(tmp_path / "store")
    store.create_run(TestRun(run_id=RUN_ID, diagnostic_id=spec.diagnostic_id, diagnostic_version=spec.version,
                             profile=ProfileName.VIRTUAL, status=RunStatus.QUEUED, created_at=T0,
                             code=CodeIdentity(REVISION, False), config_fingerprint=CONFIG,
                             diagnostic_fingerprint=spec.fingerprint(), parameters=parameters,
                             environment=ENVIRONMENT))
    runtime_dir, data_root = tmp_path / "runtime", tmp_path / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    context = RunContext(
        run_id=RUN_ID, diagnostic=spec, profile=ProfileName.VIRTUAL, parameters=parameters, overrides={},
        scenario=entry.manifest.scenario, runtime_dir=runtime_dir, data_root=data_root,
        artifacts=RunArtifacts(store, RUN_ID), cancelled=asyncio.Event(),
        deadline=asyncio.get_running_loop().time() + RUN_BUDGET_S, log=lambda message: None)
    return context


def started_speeches(context: RunContext) -> list[str]:
    """`speech_id` of every `voice.speech.started` line of the run's `trace.jsonl`, in order.

    Read from the run's runtime directory (the file the runner commits as its
    `trace.jsonl` artifact): the store only serves an artifact once the
    supervisor has recorded the run, which a direct runner call never does.
    """
    lines = RuntimeJournal(context.runtime_dir).trace_path.read_text(encoding="utf-8").splitlines()
    return [str(line["data"].get("speech_id")) for line in map(json.loads, lines)
            if line.get("kind") == "voice.speech.started"]


async def test_v4_of_stale_supersession_never_starts_an_answer_written_for_the_previous_question(tmp_path):
    """T8 — la scène « conversation accélérée » de v4, sur la pile virtuelle de production.

    Échoue d'abord sur le comportement lu dans la trace du run (qui a démarré),
    puis sur la mesure que la Slice 04 doit ajouter au runner.
    """
    catalog = catalog_with_v4(tmp_path / "catalog")
    entry = catalog.describe("speech.stale_supersession", 4)
    assert NEW_METRIC in entry.diagnostic.metric_index
    context = run_context(tmp_path / "run", entry)

    outcome = await StaleSupersessionRunner().run(context)
    metrics = dict(outcome.metrics)
    started = started_speeches(context)

    assert "old-result" not in started, (
        f"la réponse rédigée pour la question précédente a démarré sans réémission : démarrées = {started}")
    assert started[:1] == ["new-result"], f"la réponse fraîche n'a pas été servie d'abord : démarrées = {started}"
    assert metrics.get(NEW_METRIC) == 0, f"{NEW_METRIC} non mesurée ou non nulle : {metrics}"
    assert metrics["speech.latest_intent_delivered"] is True
    assert metrics["scenario.expectations_failed_count"] == 0
