"""Documents de recherche durables dans le Dossier du Board (V1.2 Slice 04, jarvis-presentation-edition-v1-2).

Contrat : `docs/subagent-roles.md` › *12. Le document de recherche*, `docs/boards.md` › *Research documents*,
`docs/dossier.md`. Ce que ce fichier épingle :

- un document écrit selon le gabarit des rôles (`RESEARCH_DOCUMENT_TEMPLATE`) est relu par le lecteur de la
  Slice 03 (`parse_front_matter`, `decide`) et a toutes les sections du corps ;
- nom stable par sujet (`research_path`), sans doublon ni date ;
- mise à jour conditionnelle sur la vraie pile Core : `replace` + `expected_sha256`, conflit sans toucher au
  fichier ; une écriture qui échoue au moment de publier laisse la version précédente intacte ;
- le Dossier liste et affiche le document (titre = sujet, vérification, sources), sans copie ;
- consignes : petite recherche sans document, l'agent qui conclut l'écrit (jamais le cerveau), échec dit
  « Document non enregistré » ; le cerveau le relie sous Documents clés ; dossier de production et auteur partent
  des documents existants ; tout cela en `presentation` seulement (`full` inchangé).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from jarvis.adapters import board_memory_store
from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.domain.agent_capabilities import PRESENTATION_CAPABILITIES, UNCONFINED
from jarvis.domain.board_memory import BoardMemoryPath
from jarvis.domain.research_freshness import (
    RESEARCH_BODY_SECTIONS, FreshnessAction, Volatility, decide, is_research_path, missing_body_sections,
    parse_front_matter, research_path, research_slug,
)
from jarvis.domain.subagent_roles import (
    RESEARCH_DOCUMENT_TEMPLATE, RESEARCH_FRONT_MATTER_TEMPLATE, ROLES, role_brief, role_by_id,
)
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from jarvis.ports.board_memory import BoardMemoryUnavailable, WriteMode
from jarvis.runtime import claude_local, routing_hook
from jarvis.runtime.claude_local import render_brain_system_prompt
from jarvis.runtime.presentation_playbooks import (
    AUTHOR_PLAYBOOK, BRIEF_PLAYBOOK, RESEARCH_SOURCES_MARK, RESEARCH_SOURCES_NOTE, REVIEW_PLAYBOOK, with_playbook,
)
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_capture_api_protocol import core
from tests.unit.test_workspace_inspection_api import build

TODAY = date(2026, 10, 27)
V1 = "/v1/workspace"
DOC_PATH = "documents/research/remotion-vs-motion-canvas.md"

#: Un document tel que le gabarit le demande (sujet, deux sources dont une ratée, corps en sections).
DOCUMENT = """---
topic: Remotion ou Motion Canvas pour une vidéo de présentation
scope: licence, rendu, courbe d'apprentissage ; prix hors entreprise exclus
checked_at: 2026-10-27
volatility: medium
uncertainty: date de la prochaine version majeure de Motion Canvas
sources:
  - https://www.remotion.dev/docs/license | date: 2026-09-12 | checked: 2026-10-27
  - https://motioncanvas.io/docs/ | checked: 2026-10-27
  - https://www.remotion.dev/pricing | tried: 2026-10-27 | status: failed
---
# Remotion ou Motion Canvas ?
## Résumé
Remotion rend des vidéos depuis React ; Motion Canvas depuis un éditeur et TypeScript.
## Constats
- Remotion : licence entreprise au-delà de trois personnes [remotion.dev/docs/license]
## Incertitudes et contradictions
- La page de prix de Remotion n'a pas pu être lue.
## Réutilisation
Valable pour un choix d'outil ; revérifier la licence avant avril 2027.
"""


# ------------------------------------------------------------------ 1. gabarit <-> lecteur de la Slice 03


def test_a_document_written_from_the_template_is_read_by_the_slice_03_reader():
    filled = (RESEARCH_DOCUMENT_TEMPLATE.replace("<AAAA-MM-JJ de votre vérification>", "2026-10-27")
              .replace("<low | medium | high>", "high").replace("<AAAA-MM-JJ>", "2026-10-27")
              .replace("<AAAA-MM-JJ de la source>", "2026-10-20"))
    assert filled.startswith(RESEARCH_FRONT_MATTER_TEMPLATE.split("<", 1)[0])
    meta, problem = parse_front_matter(filled)
    assert problem is None and meta.checked_at == TODAY and meta.volatility is Volatility.HIGH
    assert len(meta.sources) == 1 and meta.sources[0].checked_at == TODAY
    assert decide(meta, today=TODAY, request="Quel outil choisir ?").action is FreshnessAction.REUSE
    assert missing_body_sections(filled) == ()
    # Un sujet de 40 jours, volatil, se rafraîchit : le gabarit porte une vraie date de vérification, pas un décor.
    assert decide(meta, today=date(2026, 12, 6)).action is FreshnessAction.FULL_REFRESH


def test_the_sample_document_gives_the_expected_freshness_and_sections():
    meta, problem = parse_front_matter(DOCUMENT)
    assert problem is None and meta.topic.startswith("Remotion ou Motion Canvas")
    assert [source.failed for source in meta.sources] == [False, False, True]
    decision = decide(meta, today=TODAY, request="Fais la présentation Remotion contre Motion Canvas")
    assert decision.action is FreshnessAction.REUSE and decision.unverifiable_sources == (
        "https://www.remotion.dev/pricing",)
    assert missing_body_sections(DOCUMENT) == ()
    assert missing_body_sections(DOCUMENT.replace("## Incertitudes et contradictions", "## Divers")) == (
        "Incertitudes et contradictions",)
    assert RESEARCH_BODY_SECTIONS == ("Résumé", "Constats", "Incertitudes et contradictions", "Réutilisation")


# ------------------------------------------------------------------ 2. nommage


@pytest.mark.parametrize(("topic", "slug"), [
    ("Remotion vs Motion Canvas", "remotion-vs-motion-canvas"),
    ("Modèles d'OpenAI disponibles", "modeles-d-openai-disponibles"),
    ("  Prix : Gamma, Synthesia & HeyGen (2026)  ", "prix-gamma-synthesia-heygen-2026"),
    ("Vélo électrique — marché", "velo-electrique-marche"),
])
def test_the_slug_is_stable_ascii_and_without_date_suffix(topic, slug):
    assert research_slug(topic) == slug == research_slug(topic.upper())
    assert research_path(topic) == f"documents/research/{slug}.md" and is_research_path(research_path(topic))


def test_a_long_topic_is_cut_on_a_word_and_an_empty_topic_is_refused():
    long_slug = research_slug("comparaison détaillée des outils de génération de vidéo par intelligence artificielle")
    assert len(long_slug) <= 60 and not long_slug.endswith("-") and long_slug.startswith("comparaison-detaillee")
    assert research_slug("x" * 80) == "x" * 60
    with pytest.raises(ValueError):
        research_path(" — ! ")


# ------------------------------------------------------------------ 3. mise à jour conditionnelle et échec d'écriture


async def _write(stack, board_id: str, content: str, mode: str, sha: str | None = None):
    body = {"path": DOC_PATH, "content": content, "mode": mode, "origin": "brain"}
    if sha is not None:
        body["expected_sha256"] = sha
    status, payload, _, _ = await core(stack, "POST", f"{V1}/boards/{board_id}/memory/write", json=body)
    return status, payload


async def _read(stack, board_id: str):
    _, payload, _, _ = await core(stack, "GET", f"{V1}/boards/{board_id}/memory/read", params={"path": DOC_PATH})
    return payload


async def test_a_refresh_updates_the_same_document_conditionally_and_a_conflict_touches_nothing(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        status, _ = await _write(stack, w.board_a, DOCUMENT, "create")
        assert status == 201
        status, refused = await _write(stack, w.board_a, DOCUMENT, "create")
        assert (status, refused["error"]["code"]) == (409, "memory_exists"), "un sujet, un fichier"
        sha = (await _read(stack, w.board_a))["sha256"]

        theirs = DOCUMENT.replace("Valable pour un choix d'outil", "Valable pour un choix d'outil (relu)")
        status, _ = await _write(stack, w.board_a, theirs, "replace", sha)
        assert status == 200
        refreshed = DOCUMENT.replace("checked_at: 2026-10-27", "checked_at: 2026-11-02")
        status, refused = await _write(stack, w.board_a, refreshed, "replace", sha)
        assert (status, refused["error"]["code"]) == (409, "memory_conflict")
        current = await _read(stack, w.board_a)
        assert current["text"] == theirs, "un remplacement périmé ne touche pas au document"

        merged = theirs.replace("checked_at: 2026-10-27", "checked_at: 2026-11-02")
        status, _ = await _write(stack, w.board_a, merged, "replace", current["sha256"])
        assert status == 200
        meta, _ = parse_front_matter((await _read(stack, w.board_a))["text"])
        assert meta.checked_at == date(2026, 11, 2)
        files = list((stack.data_root / "boards" / w.board_a / "memory" / "documents" / "research").iterdir())
        assert [path.name for path in files] == ["remotion-vs-motion-canvas.md"], "aucun doublon, aucun temporaire"


def test_a_write_that_fails_while_publishing_keeps_the_previous_version(tmp_path, monkeypatch):
    store = FileBoardMemoryStore(tmp_path)
    path = BoardMemoryPath.parse(DOC_PATH)
    store.write(DEFAULT_BOARD_ID, path, DOCUMENT, mode=WriteMode.CREATE)
    sha = store.read(DEFAULT_BOARD_ID, path).sha256

    def broken(_temporary, _target):
        raise PermissionError(13, "disque refusé")

    monkeypatch.setattr(board_memory_store, "replace_with_retry", broken)
    with pytest.raises(BoardMemoryUnavailable) as failed:
        store.write(DEFAULT_BOARD_ID, path, DOCUMENT.replace("2026-10-27", "2026-11-02"), mode=WriteMode.REPLACE,
                    expected_sha256=sha)
    assert "board_memory_failed" in str(failed.value), "la panne est dite avec son code"
    after = store.read(DEFAULT_BOARD_ID, path)
    assert after.text == DOCUMENT and after.sha256 == sha
    folder = tmp_path / "boards" / DEFAULT_BOARD_ID / "memory" / "documents" / "research"
    assert [item.name for item in folder.iterdir()] == ["remotion-vs-motion-canvas.md"], "temporaire retiré"


# ------------------------------------------------------------------ 4. le Dossier le liste et l'affiche


async def test_the_dossier_lists_and_shows_the_research_document_with_its_check(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        await stack.core.boards.switch(w.board_a)
        assert (await _write(stack, w.board_a, DOCUMENT, "create"))[0] == 201
        body = {"path": "documents/research/sans-entete.md", "content": "# Notes sans en-tête\n", "mode": "create"}
        assert (await core(stack, "POST", f"{V1}/boards/{w.board_a}/memory/write", json=body))[0] == 201

        status, listed, _, _ = await core(stack, "GET", f"{V1}/boards/{w.board_a}/dossier")
        assert status == 200
        rows = {row["entry_id"]: row for row in listed["entries"]}
        row = rows[f"memory:{DOC_PATH}"]
        assert row["title"] == "Remotion ou Motion Canvas ?", "le titre `#` du document"
        assert row["folder"] == "documents/research" and row["kind"] == "note"
        assert row["research"] == {"topic": "Remotion ou Motion Canvas pour une vidéo de présentation",
                                   "checked_at": "2026-10-27", "volatility": "medium", "sources": 3,
                                   "failed_sources": 1}
        bare = rows["memory:documents/research/sans-entete.md"]
        assert bare["title"] == "sans-entete" and bare["research"] == {"problem": "no_front_matter"}
        assert "research" not in rows["memory:notes/plan.md"], "seuls les documents de recherche"

        status, one, _, _ = await core(stack, "GET", f"{V1}/boards/{w.board_a}/dossier/entry",
                                       params={"id": f"memory:{DOC_PATH}"})
        assert status == 200 and one["entry"]["research"]["checked_at"] == "2026-10-27"

        status, shown, _, _ = await core(stack, "POST", f"{V1}/boards/{w.board_a}/dossier/present",
                                         json={"entry_id": f"memory:{DOC_PATH}"})
        assert status == 201, shown
        item = (await stack.core.scene.snapshot()).get_object(shown["object_id"])
        memory_file = stack.data_root / "boards" / w.board_a / "memory" / DOC_PATH
        assert item.payload.source_path == str(memory_file), "même source, rien de recopié"
        assert item.payload.title == "Remotion ou Motion Canvas ?", "même titre qu'au Dossier (I-004 M1)"


# ------------------------------------------------------------------ 5. consignes (presentation seulement)


def test_the_research_roles_get_the_document_rules_in_presentation_only():
    for role_id in ("research", "web-research", "research-lead"):
        brief = role_brief(role_by_id(role_id), capabilities=PRESENTATION_CAPABILITIES)
        assert RESEARCH_DOCUMENT_TEMPLATE in brief, role_id
        # Petite recherche : pas de document ; l'agent qui conclut l'écrit ; le cerveau jamais.
        assert "une question factuelle isolée (un prix, une date) se répond sans document" in brief
        assert "rendez-lui vos apports sans écrire de document" in brief and "Le cerveau ne l'écrit pas" in brief
        assert "Un sujet, un fichier" in brief and "expected_sha256" in brief
        assert "« Document non enregistré : <code> »" in brief and "ne dites jamais qu'il est enregistré" in brief
    lead = role_brief(role_by_id("research-lead"), capabilities=PRESENTATION_CAPABILITIES)
    assert "Vous écrivez vous-même le document de recherche, une fois les apports convergés" in lead
    for role in ROLES:
        for capabilities in (None, UNCONFINED):
            text = role_brief(role, capabilities=capabilities)
            assert "Document non enregistré" not in text and "## Réutilisation" not in text, role.id


def test_the_brain_links_key_research_documents_and_relays_a_failed_save_in_presentation_only():
    prompt = render_brain_system_prompt(PRESENTATION_CAPABILITIES)
    assert "ajoutez-le sous Documents clés de summary.md" in prompt
    assert "« Document non enregistré » dans un compte rendu" in prompt and "ne l'écrivez pas vous-même" in prompt
    assert "cite les chemins des documents de recherche du sujet" in prompt
    for text in (claude_local.BRAIN_SYSTEM_PROMPT, render_brain_system_prompt(UNCONFINED),
                 render_brain_system_prompt(None)):
        assert "Document non enregistré" not in text and "Documents clés de summary.md" not in text


def _charter(head: str, capabilities) -> str:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu-x",
             "tool_input": {"description": f"{head} Présentation", "prompt": f"{head} Consigne."}}
    return routing_hook.charter_input(event, capabilities=capabilities)["prompt"]


def test_the_production_brief_and_the_author_start_from_the_board_research_in_presentation_only():
    for head, playbook in (("[general] [presentation-brief]", BRIEF_PLAYBOOK),
                           ("[general] [presentation-author]", AUTHOR_PLAYBOOK)):
        confined = _charter(head, PRESENTATION_CAPABILITIES)
        assert confined.count(RESEARCH_SOURCES_MARK + "\n") == 1 and RESEARCH_SOURCES_NOTE in confined
        assert confined.index(playbook) < confined.index(RESEARCH_SOURCES_NOTE)
        for capabilities in (None, UNCONFINED):
            assert RESEARCH_SOURCES_MARK not in _charter(head, capabilities)
    assert RESEARCH_SOURCES_MARK not in _charter("[general] [presentation-review]", PRESENTATION_CAPABILITIES)
    assert "Ne relance pas une recherche qu'un de ces documents couvre" in RESEARCH_SOURCES_NOTE
    assert "documents/research/" in RESEARCH_SOURCES_NOTE
    # Sans édition, le playbook d'avant, octet pour octet ; jamais doublé.
    assert with_playbook("x", "presentation-review", research_sources=True) == f"x\n\n{REVIEW_PLAYBOOK}"
    assert with_playbook("x", "presentation-brief") == f"x\n\n{BRIEF_PLAYBOOK}"
    assert with_playbook(f"x\n\n{BRIEF_PLAYBOOK}", "presentation-brief", research_sources=True) is None


# ------------------------------------------------------------------ 6. le document réel écrit par une direction de recherche (trace S04)

REAL_DOC = Path(__file__).parents[1] / "fixtures" / "research" / "gamma-vs-pitch.md"


async def test_the_real_document_of_the_s04_trace_is_conform_fresh_and_titled_in_the_dossier(tmp_path):
    """Écrit par `[general] [research-lead]` au bac S04 : sujet écrit comme le nom du fichier, `#` humain."""

    text = REAL_DOC.read_text(encoding="utf-8")
    meta, problem = parse_front_matter(text)
    assert problem is None and missing_body_sections(text) == ()
    assert decide(meta, today=TODAY, request="Prépare le dossier de production sur Gamma contre Pitch").action \
        is FreshnessAction.REUSE
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        body = {"path": "documents/research/gamma-vs-pitch.md", "content": text, "mode": "create"}
        assert (await core(stack, "POST", f"{V1}/boards/{w.board_a}/memory/write", json=body))[0] == 201
        _, listed, _, _ = await core(stack, "GET", f"{V1}/boards/{w.board_a}/dossier")
        [row] = [e for e in listed["entries"] if e.get("path") == "documents/research/gamma-vs-pitch.md"]
        assert row["title"] == "Gamma vs Pitch : prix d'entrée, export PowerPoint, collaboration"
        assert row["research"]["topic"] == "gamma-vs-pitch" and row["research"]["checked_at"] == "2026-10-27"
        assert (row["research"]["sources"], row["research"]["failed_sources"]) == (8, 1)



# ------------------------------------------------------------------ 6. finitions du Dossier (V1.2 Slice 06, I-004)


def _long_header(sources: int) -> str:
    lines = ["---", "topic: gamma-vs-pitch", "checked_at: 2026-10-27", "volatility: high", "sources:"]
    lines += [f"  - https://example.com/une/longue/adresse/de/source/numero-{n:02d}?ref=abcdef | checked: 2026-10-27"
              for n in range(sources)]
    return "\n".join(lines) + "\n---\n"


def test_the_title_is_read_whole_or_not_at_all():
    from jarvis.domain.research_freshness import research_body_title

    doc = "---\ntopic: x\n---\n\n# Un titre assez long pour être coupé en plein mot\n\n## Résumé\nTexte.\n"
    assert research_body_title(doc, complete=True) == ("Un titre assez long pour être coupé en plein mot", False)
    cut = doc[:doc.index("pour") + 4]
    assert research_body_title(cut, complete=False) == (None, True), "une ligne coupée n'est jamais un titre"
    assert research_body_title("---\ntopic: x\n---\n", complete=False) == (None, True)
    assert research_body_title("---\ntopic: x\n---\nTexte sans titre\n", complete=False) == (None, False)
    assert research_body_title("# Pas d'en-tête\n", complete=True) == (None, False)


def test_the_board_preview_starts_with_the_summary():
    from jarvis.domain.research_freshness import research_preview_text

    assert research_preview_text(DOCUMENT).startswith("## Résumé"), research_preview_text(DOCUMENT)[:80]
    assert research_preview_text("# Notes sans en-tête\n") == "# Notes sans en-tête\n"


def test_the_scene_preview_of_a_research_document_hides_its_header(tmp_path):
    from jarvis.core.scene_file_watcher import _signature, _summary_for

    folder = tmp_path / "boards" / "b" / "memory" / "documents" / "research"
    folder.mkdir(parents=True)
    research = folder / "remotion-vs-motion-canvas.md"
    research.write_text(DOCUMENT, encoding="utf-8")
    other = tmp_path / "boards" / "b" / "memory" / "notes.md"
    other.write_text(DOCUMENT, encoding="utf-8")
    assert _summary_for(str(research), _signature(str(research))).startswith("## Résumé")
    assert _summary_for(str(other), _signature(str(other))).startswith("---"), "une autre note : inchangée"


async def test_a_header_close_to_the_head_bound_keeps_the_whole_title(tmp_path):
    """I-004 M2 : un en-tête qui frôle 2 Kio ; le titre `#` n'est ni coupé ni remplacé par le sujet."""

    title = "Gamma vs Pitch : prix d'entrée, export PowerPoint, collaboration"
    for sources in range(10, 30):
        header = _long_header(sources)
        if 1_990 < len(header.encode("utf-8")) < 2_048:
            break
    else:
        raise AssertionError("aucun en-tête près de 2 Kio")
    text = header + f"\n# {title}\n\n## Résumé\nTexte.\n"
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        await stack.core.boards.switch(w.board_a)
        body = {"path": "documents/research/gamma-vs-pitch.md", "content": text, "mode": "create"}
        assert (await core(stack, "POST", f"{V1}/boards/{w.board_a}/memory/write", json=body))[0] == 201
        status, listed, _, _ = await core(stack, "GET", f"{V1}/boards/{w.board_a}/dossier")
        assert status == 200
        row = next(r for r in listed["entries"] if r["entry_id"] == "memory:documents/research/gamma-vs-pitch.md")
        assert row["title"] == title
