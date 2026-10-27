"""Mémoire du Board d'un tour, lue bornée pour le bloc `board` (handoff board-memory-workspace-inspector, Slice 03).

R3 : le bloc `board` porte où est la mémoire du Board (`boards/<id>/memory`
et son chemin absolu), un manifeste borné (≤ 40 entrées, profondeur 2, noms
et tailles) et la tête de `summary.md` (casse ignorée, ≤ 2 048 octets). Jamais
un autre fichier, jamais un parcours du disque ici : tout passe par le magasin
(`BoardMemoryStore.tree` / `read`, Slice 02), qui refait ses défenses de chemin
à chaque appel. Synchrone (E/S disque) : l'appelant le lance dans un fil.

Politique d'échec : la mémoire est une commodité du tour, pas une condition.
Racine refusée ou disque en défaut → bloc dégradé (`error` = code stable), le
tour part avec le reste du Board. `summary.md` illisible (binaire, UTF-8
invalide…) → manifeste gardé, `summary_error`. Toute autre exception remonte
(défaut de code) : l'orchestrateur la trace et le tour part sans bloc `board`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from jarvis.domain.board_memory import MEMORY_SUMMARY_NAME, BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath
from jarvis.domain.brain_context import (
    MAX_BRAIN_BOARD_MANIFEST_DEPTH, MAX_BRAIN_BOARD_MANIFEST_ENTRIES, MAX_BRAIN_BOARD_SUMMARY_BYTES,
    BrainBoardMemory, BrainBoardMemoryEntry,
)
from jarvis.domain.research_freshness import (
    FRONT_MATTER_TOO_LONG, MAX_FRONT_MATTER_BYTES, MAX_RESEARCH_DOCS, MAX_RESEARCH_HEAD_BYTES, RESEARCH_DIR,
    ResearchDocStatus, ResearchMetadata, decide, is_research_path, matches_topic, parse_front_matter, recency_terms,
)

#: Entrées listées sous `documents/research/` pour choisir les documents du tour (au-delà : compté).
MAX_RESEARCH_TREE_ENTRIES = 200
from jarvis.ports.board_memory import BoardMemoryStore, BoardMemoryUnavailable, MemoryEntryKind

#: Code d'un échec disque non classé par le magasin.
BOARD_MEMORY_READ_FAILED = "board_memory_failed"


def read_board_memory(store: BoardMemoryStore, data_root: Path, board_id: str) -> BrainBoardMemory:
    """Le bloc mémoire du Board, borné ; dégradé (jamais levé) sur un refus ou une panne du magasin."""

    locator = store.memory_root_locator(board_id)
    path = str(Path(data_root).joinpath(*locator.split("/")))
    try:
        tree = store.tree(board_id, depth=MAX_BRAIN_BOARD_MANIFEST_DEPTH, max_entries=MAX_BRAIN_BOARD_MANIFEST_ENTRIES)
    except (BoardMemoryError, BoardMemoryUnavailable) as exc:
        return BrainBoardMemory(locator=locator, path=path, error=_code(exc))
    except OSError:
        return BrainBoardMemory(locator=locator, path=path, error=BOARD_MEMORY_READ_FAILED)
    entries = tuple(BrainBoardMemoryEntry(path=entry.path, kind=entry.kind.value,
                                          size=entry.size if entry.kind is MemoryEntryKind.FILE else None)
                    for entry in tree.entries)
    summary, clipped, summary_error = "", False, None
    try:
        # Lu par son nom, pas cherché dans le manifeste : un manifeste coupé à 40 entrées peut ne pas
        # l'atteindre. Le magasin ignore la casse (`Summary.md`) et rend un texte coupé sur un
        # caractère entier (le décodeur garde la fin incomplète).
        head = store.read(board_id, BoardMemoryPath.parse(MEMORY_SUMMARY_NAME), max_bytes=MAX_BRAIN_BOARD_SUMMARY_BYTES)
        summary, clipped = head.text, not head.eof
    except BoardMemoryError as exc:
        # intentional: pas de `summary.md`, c'est la convention facultative (R1), pas une panne.
        if exc.code is not BoardMemoryErrorCode.MEMORY_NOT_FOUND:
            summary_error = _code(exc)
    except BoardMemoryUnavailable as exc:
        summary_error = _code(exc)
    except OSError:
        summary_error = BOARD_MEMORY_READ_FAILED
    return BrainBoardMemory.bounded(locator=locator, path=path, entries=entries, more=tree.truncated,
                                    summary=summary, summary_clipped=clipped, summary_error=summary_error)


def with_board_research(memory: BrainBoardMemory, store: BoardMemoryStore, board_id: str, *, request: str | None,
                        today: date) -> tuple[BrainBoardMemory, int]:
    """`memory` complété des documents de `documents/research/` et de leur décision de fraîcheur (V1.2 Slice 03).

    Édition Presentation seulement (l'appelant décide). Au plus `MAX_RESEARCH_DOCS` fichiers `.md` (profondeur 2),
    ceux dont le nom parle du sujet du tour d'abord, puis les plus récents ; le surplus est compté
    (`research_unread`, dit au cerveau). Le front-matter seul sert : tête de `MAX_RESEARCH_HEAD_BYTES`, relue
    jusqu'à `MAX_FRONT_MATTER_BYTES` quand l'en-tête est plus long (reprise QA B1) ; au-delà, `front_matter_too_long`.
    La demande d'actualité ne vaut que pour les documents dont le sujet correspond au tour (`matches_topic`).
    Dossier absent : rien d'ajouté. Un document illisible est jugé `freshness_unknown` ; une panne du dossier
    lui-même laisse le bloc tel quel. Rend aussi le nombre de documents non lus.
    """

    if memory.error is not None:
        return memory, 0
    try:
        tree = store.tree(board_id, BoardMemoryPath.parse(RESEARCH_DIR), depth=2, max_entries=MAX_RESEARCH_TREE_ENTRIES)
    except (BoardMemoryError, BoardMemoryUnavailable, OSError):
        # intentional: pas de dossier de recherche (le cas courant) ou dossier illisible : la mémoire du tour suffit.
        return memory, 0
    files = [entry for entry in tree.entries
             if entry.kind is MemoryEntryKind.FILE and is_research_path(entry.path)]
    # Le sujet du tour d'abord (par le nom du fichier, sans lecture), puis les plus récents.
    files.sort(key=lambda entry: entry.modified_at, reverse=True)
    files.sort(key=lambda entry: not matches_topic(request, entry.path.rsplit("/", 1)[-1][:-3]))
    statuses: list[ResearchDocStatus] = []
    for entry in files[:MAX_RESEARCH_DOCS]:
        meta, problem = _read_front_matter(store, board_id, entry.path)
        on_topic = matches_topic(request, entry.path.rsplit("/", 1)[-1][:-3],
                                 meta.topic if meta else "", meta.scope if meta else "")
        statuses.append(ResearchDocStatus.from_decision(
            entry.path, meta, decide(meta, today=today, request=request, on_topic=on_topic),
            on_topic=on_topic, problem=problem))
    if not statuses:
        return memory, 0
    unread = max(0, len(files) - MAX_RESEARCH_DOCS) + (1 if tree.truncated else 0)
    return replace(memory, research=tuple(statuses), research_recency=recency_terms(request)[:8],
                   research_unread=unread), unread


def _read_front_matter(store: BoardMemoryStore, board_id: str, path: str) -> tuple[ResearchMetadata | None, str | None]:
    """Le front-matter d'un document : 2 Kio, puis relu jusqu'à `MAX_FRONT_MATTER_BYTES` s'il n'est pas fermé."""

    try:
        head = store.read(board_id, BoardMemoryPath.parse(path), max_bytes=MAX_RESEARCH_HEAD_BYTES)
        meta, problem = parse_front_matter(head.text, complete=head.eof)
        if problem == FRONT_MATTER_TOO_LONG:
            head = store.read(board_id, BoardMemoryPath.parse(path), max_bytes=MAX_FRONT_MATTER_BYTES)
            meta, problem = parse_front_matter(head.text, complete=head.eof)
    except (BoardMemoryError, BoardMemoryUnavailable, OSError, UnicodeDecodeError):
        return None, None
    return meta, problem


def _code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    return str(getattr(code, "value", code) or BOARD_MEMORY_READ_FAILED)[:64]
