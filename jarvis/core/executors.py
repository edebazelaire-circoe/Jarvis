from __future__ import annotations

from typing import Any

from jarvis.domain.actions import ActionKind, ActionRequest
from jarvis.ports.board import BoardClient
from jarvis.ports.memory import MemoryBackend


def build_action_executors(memory: MemoryBackend, board: BoardClient):
    async def memory_search(action: ActionRequest) -> dict[str, Any]:
        hits = await memory.search(
            str(action.payload["query"]),
            int(action.payload.get("limit", 5)),
        )
        return {
            "hits": [
                {
                    "memory_id": hit.memory_id,
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "score": hit.score,
                }
                for hit in hits
            ]
        }

    async def memory_append(action: ActionRequest) -> dict[str, Any]:
        record = await memory.append_note(
            str(action.payload["title"]),
            str(action.payload["body"]),
        )
        return {
            "memory_id": record.memory_id,
            "title": record.title,
        }

    async def board_present(action: ActionRequest) -> dict[str, Any]:
        return await board.present(
            str(action.payload["title"]),
            str(action.payload["body"]),
            x=action.payload.get("x"),
            y=action.payload.get("y"),
        )

    return {
        ActionKind.MEMORY_SEARCH: memory_search,
        ActionKind.MEMORY_APPEND: memory_append,
        ActionKind.BOARD_PRESENT: board_present,
    }
