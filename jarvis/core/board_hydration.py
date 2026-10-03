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

from pathlib import Path

from jarvis.domain.board_memory import MEMORY_SUMMARY_NAME, BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath
from jarvis.domain.brain_context import (
    MAX_BRAIN_BOARD_MANIFEST_DEPTH, MAX_BRAIN_BOARD_MANIFEST_ENTRIES, MAX_BRAIN_BOARD_SUMMARY_BYTES,
    BrainBoardMemory, BrainBoardMemoryEntry,
)
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


def _code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    return str(getattr(code, "value", code) or BOARD_MEMORY_READ_FAILED)[:64]
