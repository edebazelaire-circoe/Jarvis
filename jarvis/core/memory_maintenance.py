from __future__ import annotations

from pathlib import Path
import shutil

MEMORY_CLASSES = ("short_term_memory", "long_term_memory", "traumatic_memory", "eternal_memory", "plastic_memory")


def ensure_memory_layout(root: Path) -> dict[str, Path]:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    paths = {name: root / name for name in MEMORY_CLASSES}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


class MemoryMaintenanceWorker:
    """Markdown-only consolidation MVP; protected classes are never auto-deleted."""

    def __init__(self, root: Path) -> None:
        self.paths = ensure_memory_layout(root)

    async def execute(self, job) -> dict[str, object]:
        del job
        promoted = 0
        for source in self.paths["short_term_memory"].glob("*.md"):
            text = source.read_text(encoding="utf-8")
            if "<!-- jarvis:retain -->" not in text:
                continue
            target = self.paths["long_term_memory"] / source.name
            if not target.exists():
                shutil.copy2(source, target)
                promoted += 1
        return {"promoted": promoted}

    async def cancel(self, job_id: str) -> None:
        del job_id
