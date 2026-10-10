"""Scripted stand-ins for what a Remotion draft needs from Core (Remotion Slice 15): a compiler, the engine pin, the Board context.

`ScriptedCompiler` is NOT esbuild. It accepts any source whose entry module does not carry `BROKEN_MARKER` and refuses one that does with the
typed `RemotionCompileError` the real compiler raises (code, file, line, column). It exists so the unit tests of the planner (gate, assembly,
refusals, atomicity) need no Node; the real compiler is exercised by `tests/unit/test_presentation_studio_authoring_remotion_real.py` and by
`scripts/remotion_authoring_harness.py`, which never use this class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jarvis.domain.remotion_compile import CompileDiagnostic, CompileErrorCode, RemotionCompileError
from jarvis.domain.remotion_source import EnginePin

BROKEN_MARKER = "const broken = (;"
ENGINE = EnginePin("remotion", "4.0.534", "19.3.0", "a" * 64)


@dataclass(slots=True)
class FakeArtifact:
    cache_key: str
    reused: bool = False

    def to_public(self) -> dict[str, Any]:
        return {"cache_key": self.cache_key, "reused": self.reused, "duration_ms": 3, "files": [{"path": "scene.js", "bytes": 1200, "sha256": "0" * 64}]}


@dataclass
class ScriptedCompiler:
    """`unavailable`: the reason the runtime is not ready (None: ready). `calls`: the source digests it was asked to compile."""

    unavailable: str | None = None
    calls: list[str] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)

    def unavailable_reason(self) -> str | None:
        return self.unavailable

    def compile_scene(self, source: Any, *, minify: bool = True) -> FakeArtifact:
        if self.unavailable:
            raise RemotionCompileError(CompileErrorCode.RUNTIME_UNAVAILABLE, self.unavailable)
        text = source.module_texts()[source.block.entry]
        self.calls.append(source.digest)
        for number, line in enumerate(text.splitlines(), start=1):
            if BROKEN_MARKER in line:
                raise RemotionCompileError(CompileErrorCode.SOURCE_ERROR, "the scene has a syntax error", diagnostics=(
                    CompileDiagnostic(source.block.entry, number, line.index(BROKEN_MARKER) + 16, 'Expected ")" but found ";"'),))
        reused = source.digest in self.seen
        self.seen.add(source.digest)
        return FakeArtifact("scene-" + source.digest[:32], reused)


def engine_pin() -> EnginePin:
    return ENGINE


class _State:
    def __init__(self, value: str) -> None:
        self.value = value


@dataclass(slots=True)
class ScriptedLiveRefs:
    """Resolves a reference as usable when its Board is authorised and its locator is in `present`; records what it was asked."""

    present: frozenset[str] = frozenset()
    asked: list[tuple[str, ...]] = field(default_factory=list)
    authorised_seen: list[frozenset[str]] = field(default_factory=list)

    async def resolve_all(self, refs: Any, *, authorised_boards: Any, expected: Any = None) -> dict[str, Any]:
        self.authorised_seen.append(frozenset(authorised_boards))
        out = {}
        for ref in refs:
            self.asked.append((ref.name, ref.board_id, ref.locator))
            if ref.board_id not in authorised_boards:
                state = "not_authorised"
            elif ref.locator not in self.present:
                state = "missing"
            else:
                state = "ok"
            out[ref.name] = _Item(_State(state), state == "ok")
        return out


@dataclass(slots=True)
class _Item:
    state: _State
    usable: bool
