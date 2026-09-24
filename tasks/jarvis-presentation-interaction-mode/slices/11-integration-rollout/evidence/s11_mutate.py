"""Slice 11 mutation harness. Byte-level, EOL-aware, diff-printing, control-carrying.

Seven ways a harness has lied in this task, and what is done about each:

1. pytest exits before collection      -> the baseline run is checked and printed.
2. red baseline read as "caught"       -> a red baseline aborts the whole run.
3. CRLF anchors matching nothing       -> read/write BYTES, join anchors with the
                                          target file's own EOL, and report
                                          "ANCHOR NOT APPLIED" rather than a survivor.
4. a mutation left on disk after a kill -> restore in a finally, verify by content.
5. one content marker per file          -> every mutation's diff --stat is printed.
6. `git diff --stat` blind to new files -> `git add -N` on untracked files first.
7. a lying "all caught" run             -> M00-CONTROL is cosmetic and MUST survive.

Usage:  python s11_mutate.py            # all mutations
        python s11_mutate.py M03 M07    # a subset
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Projects\jarvis\jarvis")
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

TESTS = [
    "tests/unit/test_presentation_integration.py",
    "tests/unit/test_presentation_response_policy.py",
    "tests/unit/test_presentation_speculative.py",
    "tests/unit/test_presentation_audio_capture.py",
]

NEW_FILES = [
    "jarvis/runtime/presentation_runtime.py",
    "jarvis/runtime/presentation_preparation.py",
    "tests/unit/test_presentation_integration.py",
]


def eol_of(data: bytes) -> bytes:
    return b"\r\n" if data.count(b"\r\n") > data.count(b"\n") / 2 else b"\n"


def read(path: str) -> bytes:
    return (ROOT / path).read_bytes()


def write(path: str, data: bytes) -> None:
    (ROOT / path).write_bytes(data)


def anchor(path: str, text: str) -> bytes:
    """Encode a multi-line anchor with the TARGET FILE's own line ending."""

    return text.replace("\n", eol_of(read(path)).decode()).encode("utf-8")


#: (id, description, file, old, new). `old` and `new` are written with plain
#: "\n"; the harness re-joins them with the target file's own EOL.
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    ("M00-CONTROL", "cosmetic comment (MUST SURVIVE)",
     "jarvis/runtime/presentation_runtime.py",
     "#: Préfixe des lignes de trace de ce module.",
     "#: Prefixe des lignes de trace de ce module (controle cosmetique)."),

    ("M01", "entering PRESENTATION no longer suspends the SIMPLE wake stack",
     "jarvis/runtime/presentation_runtime.py",
     "        await self._suspend_simple()\n        session_id = new_session_id()",
     "        session_id = new_session_id()"),

    ("M02", "a failed entry no longer resumes the SIMPLE wake stack",
     "jarvis/runtime/presentation_runtime.py",
     "            await self._resume_simple()\n            return\n        self._stack = stack",
     "            return\n        self._stack = stack"),

    ("M03", "leaving PRESENTATION no longer retires the working set",
     "jarvis/runtime/presentation_runtime.py",
     "        self.store.retire(reason)",
     "        pass  # M03"),

    ("M04", "the staged-object ledger is never read at start",
     "jarvis/runtime/presentation_runtime.py",
     "                self.reclaimed = await self.stager.reclaim()",
     "                self.reclaimed = ()"),

    ("M05", "a corrupt ledger is silently treated as empty",
     "jarvis/runtime/presentation_runtime.py",
     '                "ledger_corrupt", "Registre des objets montés illisible : contenu inattendu",\n'
     '                level="error", code="presentation_ledger_corrupt", path=str(self.path),\n'
     "                bytes=len(raw),",
     '                "ledger_read", "Registre des objets montés lu",\n'
     '                level="info", code="presentation_ledger_read", path=str(self.path),\n'
     "                bytes=len(raw),"),

    ("M06", "the ledger forgets an object as soon as it is staged",
     "jarvis/runtime/presentation_runtime.py",
     "        object_id = await self._inner.stage_hidden(category=category, title=title, summary=summary)\n"
     "        self._ledger.add(object_id)",
     "        object_id = await self._inner.stage_hidden(category=category, title=title, summary=summary)"),

    ("M07", "the wake router never arms the addressed turn",
     "jarvis/runtime/presentation_runtime.py",
     "                turns.arm(value)\n                self.armed += 1",
     "                self.armed += 1"),

    ("M08", "the router keeps serving SIMPLE after a session starts",
     "jarvis/runtime/presentation_runtime.py",
     "        if stack is None or not stack.started or stack.stopped:\n            return self.simple\n        return stack.audio.lane",
     "        return self.simple"),

    ("M09", "the addressed-turn service gets its own clock, not the lane's",
     "jarvis/runtime/presentation_runtime.py",
     "        audio.lane.clock = self.clock",
     "        audio.lane.clock = time.perf_counter"),

    ("M10", "the ambient lane is built without the store as its sink",
     "jarvis/runtime/presentation_runtime.py",
     "            sink=store,\n            session_id=session_id,",
     "            sink=PresentationWorkingSetStore(),\n            session_id=session_id,"),

    ("M11", "a mode change no longer opens or closes a session",
     "jarvis/runtime/presentation_runtime.py",
     "            wanted = behaving_interaction_mode(mode) is InteractionMode.PRESENTATION",
     "            wanted = self._stack is not None"),

    ("M12", "REUNION is read as activatable",
     "jarvis/runtime/presentation_runtime.py",
     "            wanted = behaving_interaction_mode(mode) is InteractionMode.PRESENTATION",
     "            wanted = mode is not InteractionMode.ASSISTANT"),

    ("M13", "the diagnostics report drops the trigger latency",
     "jarvis/runtime/presentation_runtime.py",
     '            "trigger_latency_s": lane.get("last_delivery_latency_s") if isinstance(lane, dict) else None,',
     '            "trigger_latency_s": None,'),

    ("M14", "the runner sends every granted tool to the CLI, MCP names included",
     "jarvis/runtime/presentation_preparation.py",
     "        usable = tuple(name for name in granted if name in CLI_GRANTABLE_TOOLS)",
     "        usable = granted"),

    ("M15", "a job with no reachable tool still launches a sub-agent",
     "jarvis/runtime/presentation_preparation.py",
     "            return SpeculativeOutcome()\n        agent = self._agent_factory(tools)",
     "            pass\n        agent = self._agent_factory(tools)"),

    ("M16", "the runner trusts whatever claim id the model returns",
     "jarvis/runtime/presentation_preparation.py",
     "            if claim_id not in known or verdict is None:",
     "            if verdict is None:"),

    ("M17", "a finding may declare itself already staged",
     "jarvis/runtime/presentation_preparation.py",
     "                        title=_text(entry.get(\"title\"), MAX_TITLE_CHARS),",
     "                        title=_text(entry.get(\"title\"), MAX_TITLE_CHARS),\n"
     "                        stage_hidden=bool(entry.get(\"stage_hidden\")),"),

    ("M18", "the sub-agent is not closed when the answer is unusable",
     "jarvis/runtime/presentation_preparation.py",
     "        finally:\n            await self._close(agent, request)",
     "        finally:\n            pass"),

    ("M19", "a cited source is never recorded, so provenance is declared not verified",
     "jarvis/runtime/presentation_runtime.py",
     "        result = store.apply(observation)\n        return source_id if getattr(result, \"applied\", False) else None",
     "        return source_id"),

    ("M20", "the CLI allow-list accepts any tool name",
     "jarvis/runtime/claude_local.py",
     "    refused = sorted(name for name in names if name not in CLI_GRANTABLE_TOOLS)",
     "    refused = []"),

    ("M21", "the restricted profile sends --tools \"\" whatever the grant says",
     "jarvis/runtime/claude_local.py",
     '                restricted_args = ["--restricted", "--tools", ",".join(self.allowed_tools),',
     '                restricted_args = ["--restricted", "--tools", "",'),

    ("M22", "the speculative profile inherits the preparation tools",
     "jarvis/runtime/claude_local.py",
     "    if names and execution_profile != \"presentation_preparation\":\n        raise ValueError(\"only the presentation_preparation profile names CLI tools\")",
     "    pass"),

    ("M23", "the speech gate reclassifies instead of taking the addressed turn's situation",
     "jarvis/runtime/presentation_speech_gate.py",
     '        if isinstance(situation, PresentationSituation):\n            return self._retain(key, situation, "addressed_turn")',
     "        situation = None"),

    ("M24", "the scheduler speaks whatever kind the addressed turn returns",
     "jarvis/runtime/speech_scheduler.py",
     "        if getattr(outcome, \"speech_kind\", None) is not SpeechKind.QUESTION:",
     "        if False:"),

    ("M25", "the clarification is queued without Core's current source",
     "jarvis/runtime/speech_scheduler.py",
     "                provenance=SpeechProvenance.BRAIN,\n                source=source,",
     "                provenance=SpeechProvenance.BRAIN,"),

    ("M26", "the addressed turn is never concluded",
     "jarvis/runtime/speech_scheduler.py",
     "        finally:\n            turns.conclude(correlation_id)",
     "        finally:\n            pass"),

    ("M27", "a broken addressed turn stops the gate from classifying",
     "jarvis/runtime/speech_scheduler.py",
     "        plan = self._open_addressed_turn(text, correlation_id)\n"
     "        self.presentation.note_addressed_turn(",
     "        plan = self._open_addressed_turn(text, correlation_id)\n"
     "        return None and self.presentation.note_addressed_turn(") ,

    ("M28", "the mode observer never notifies its listeners",
     "jarvis/runtime/interaction_mode_observer.py",
     "        self._notify(mode)\n        return True",
     "        return True"),

    ("M29", "a listener failure cancels the remaining listeners",
     "jarvis/runtime/interaction_mode_observer.py",
     "                self._trace(\n                    IGNORED_KIND,",
     "                raise  # M29\n                self._trace(\n                    IGNORED_KIND,"),

    ("M30", "the runtime hands the bridge a shared input source outside PRESENTATION",
     "jarvis/runtime/voice_v2.py",
     "        if self.interaction_mode.mode is not InteractionMode.PRESENTATION:\n            return None",
     "        if False:\n            return None"),

    # Re-aimed after round 3: the first version moved the call only two lines,
    # to just after `mute()` and still BEFORE the two early returns, so it
    # changed nothing observable. The defect this guard exists for is the call
    # landing *after* those returns, beside `wakeword.close()` - which is where
    # a reader would naturally put it, and where a bad shutdown leaks the mic.
    ("M32", "the session is released after the early returns, so a bad shutdown keeps the room mic",
     "jarvis/runtime/voice_v2.py",
     "        if self.presentation is not None:\n"
     "            await self.presentation.aclose(\"voice_stopped\")\n"
     "        await self.mute(VoiceStopReason.SHUTDOWN)",
     "        await self.mute(VoiceStopReason.SHUTDOWN)"),

    ("M33", "the composition builds the runner even without an agent factory",
     "jarvis/runtime/presentation_runtime.py",
     "        ) if self.agent_factory is not None else None",
     "        ) if True else None"),

    ("M34", "a failed entry keeps the half-open session",
     "jarvis/runtime/presentation_runtime.py",
     "            await self._resume_simple()\n            return\n        self._stack = stack",
     "            await self._resume_simple()\n        self._stack = stack"),

    ("M31", "a session that has been stopped is still reported as live",
     "jarvis/runtime/presentation_runtime.py",
     "        return stack if stack is not None and stack.started and not stack.stopped else None",
     "        return stack"),
]


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, **kwargs)


def pytest_green(label: str) -> bool:
    result = run([PY, "-m", "pytest", "-q", *TESTS, "-p", "no:randomly"], timeout=1800)
    tail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)"
    print(f"    [{label}] rc={result.returncode} :: {tail}")
    if "error" in tail.lower() and "passed" not in tail.lower():
        print("    !! pytest did not even collect; this run proves nothing")
    return result.returncode == 0


def diff_stat() -> str:
    return run(["git", "diff", "--stat"]).stdout.strip() or "(empty diff)"


def main() -> int:
    wanted = set(sys.argv[1:])
    print("== git add -N on new files (the sixth lie) ==")
    print(run(["git", "add", "-N", *NEW_FILES]).stderr.strip() or "ok")

    print("== baseline ==")
    if not pytest_green("BASELINE"):
        print("!! RED BASELINE - refusing to run. A mutation harness on red proves nothing.")
        return 2

    results: dict[str, str] = {}
    for identifier, description, path, old, new in MUTATIONS:
        if wanted and identifier not in wanted:
            continue
        original = read(path)
        old_bytes, new_bytes = anchor(path, old), anchor(path, new)
        count = original.count(old_bytes)
        print(f"\n-- {identifier}: {description}")
        if count != 1:
            print(f"    ANCHOR ({count}) -- NOT APPLIED. Not a survivor: a harness fault.")
            results[identifier] = "ANCHOR-FAILED"
            continue
        try:
            write(path, original.replace(old_bytes, new_bytes))
            applied = read(path)
            assert new_bytes in applied, "write claimed to succeed but the bytes are not there"
            print("    diff --stat:")
            for line in diff_stat().splitlines():
                print(f"      {line}")
            results[identifier] = "caught" if not pytest_green(identifier) else "SURVIVED"
        finally:
            write(path, original)
            assert read(path) == original, f"{path} was not restored"

    print("\n== verdict ==")
    survivors = [name for name, verdict in results.items()
                 if verdict == "SURVIVED" and name != "M00-CONTROL"]
    control = results.get("M00-CONTROL")
    for name, verdict in results.items():
        print(f"  {name:<12} {verdict}")
    if control is not None and control != "SURVIVED":
        print("!! THE CONTROL WAS REPORTED CAUGHT. This harness is lying; discard the run.")
        return 3
    print(f"\n{len(results)} mutations, {len(survivors)} survivors besides the control.")
    if survivors:
        print("SURVIVORS:", ", ".join(survivors))
    print("\n== tree check ==")
    print(diff_stat())
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
