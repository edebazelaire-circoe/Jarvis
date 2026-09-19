"""The rollout gate: Category 2 never enters a normal release run.

Binding contract: `docs/testlab.md` ("Rollout gate"). The Test Lab is a runtime
subsystem, not a pytest family, and the decision recorded in that section is that the
default suite keeps its deterministic double tests (they are what stops the subsystem
from rotting) and can never reach a device, a provider, a human or the user's money.

That property does not rest on anyone's discipline. It rests on four things, and this
file is the assertion of each:

1. nothing in the default run sets a Test Lab opt-in, so the ambient grant is EMPTY and
   the supervisor's own reservation path refuses every profile past `virtual`;
2. every test that would open a device, call a provider, prompt a person or read the
   live journal is skipped unless its own switch is set - checked statically, so a new
   ungated one fails here rather than on somebody's workstation;
3. `scripts/verify_release.py` neither imports the Test Lab nor runs it; it runs the
   same `pytest -q` as everyone else, under the same empty environment;
4. importing the Test Lab's entry points costs no `sounddevice` and no provider client,
   so listing a run is not a reason for PortAudio to be loaded.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jarvis.testlab.composition import OPT_IN_ENV_NAMES, read_environment_grant
from jarvis.testlab.profiles import ProfileName, ResourceGrant, check_profile_permission
from jarvis.testlab.catalog import load_catalog
from jarvis.testlab.selftest import catalog_implementations

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS = REPO_ROOT / "tests"
DOCS = REPO_ROOT / "docs" / "testlab.md"
VERIFY_RELEASE = REPO_ROOT / "scripts" / "verify_release.py"

#: Switches only a test reads. They gate the files that touch this workstation for real;
#: the operator switches in `OPT_IN_ENV_NAMES` gate the SUBSYSTEM.
TEST_ONLY_SWITCHES = ("JARVIS_TESTLAB_AUDIO", "JARVIS_TESTLAB_AUDIO_PLAYBACK", "JARVIS_TESTLAB_REAL_SESSION")
GATED_SWITCHES = (*OPT_IN_ENV_NAMES, *TEST_ONLY_SWITCHES)


# ------------------------------------------------- 1. the ambient authority

def test_the_default_test_run_sets_no_test_lab_opt_in():
    """If this fails, something in the suite armed a real device, a real provider or a bill."""
    armed = {name: os.environ[name] for name in OPT_IN_ENV_NAMES if os.environ.get(name) not in (None, "")}
    assert armed == {}, f"the default suite must set no Test Lab opt-in, but found {sorted(armed)}"


def test_the_ambient_grant_authorizes_exactly_the_virtual_profile():
    """The grant is read from the PROCESS environment, so this IS what a run would get here."""
    grant, refusal = read_environment_grant(os.environ)
    assert grant == ResourceGrant(), "the ambient Test Lab grant must be empty in the default suite"
    assert refusal is None
    assert grant.max_cost_usd == 0


@pytest.mark.parametrize("profile", sorted(ProfileName, key=lambda item: item.value))
def test_only_the_free_profiles_are_reachable_without_an_opt_in(profile):
    """`virtual` and `audio` need nothing; every other profile is refused by the empty grant.

    This is the permission arithmetic the supervisor runs, not a restatement of it: the
    same `check_profile_permission` decides a real reservation.
    """
    entry = _catalog_profile(profile)
    if entry is None:
        pytest.skip(f"no published diagnostic declares {profile.value}")
    decision = check_profile_permission(entry, ResourceGrant())
    free = profile in (ProfileName.VIRTUAL, ProfileName.AUDIO)
    assert decision.allowed is free, (profile.value, [item.reason.value for item in decision.denials])


def _catalog_profile(profile: ProfileName):
    catalog = load_catalog(implementations=catalog_implementations())
    for entry in catalog.list_diagnostics():
        spec = entry.diagnostic.profiles.get(profile)
        if spec is not None:
            return spec
    return None


# --------------------------------------- 2. every expensive test is gated

#: Third-party libraries that ARE the outside world: importing one is how a test reaches
#: this workstation's sound hardware or a paid provider. Jarvis's own `realtime_audio`,
#: `audio_devices` and `openai_realtime` are deliberately NOT here - about fifty modules
#: import them and every one drives them with a double, so an import of them says nothing.
#: These four say something: there is no way to open PortAudio or call a provider without
#: one of them (or a native library nobody in this repository uses), and the Test Lab's
#: own entry points are proven below to load none of them.
DANGEROUS_IMPORTS = ("sounddevice", "pyaudio", "openai", "livekit")


def test_every_test_that_can_reach_a_device_or_a_provider_is_gated():
    """The property this gate actually claims, checked two ways, both by AST.

    A module is "expensive" when it imports one of `DANGEROUS_IMPORTS`, or when it reads a
    Test Lab switch from the process environment. An expensive module must REFUSE to run
    without a switch: a `pytest.mark.skipif` whose CONDITION reads the environment, or a
    `pytest.skip()` under an `if` that does. A module that reads a switch must be gated on
    THAT switch, not on some other condition.

    Why by AST and not by substring, which is what this check did until the Slice 12
    rework: the substring form matched four exact spellings of one accessor and then
    accepted any `skipif` anywhere in the file, so it missed single quotes, the name in a
    constant, `from os import getenv`, `"NAME" in os.environ`, a `skipif` guarding
    something else entirely - and, worst, a module that opens a device while naming no
    switch at all, which is the shape a new offender actually has.

    Stated limit, because a check should not claim more than it does: a switch name
    assembled at runtime (an f-string, a `join`) is not resolved. A module doing that to
    reach a device still has to import one of `DANGEROUS_IMPORTS`, which is caught.
    """
    offenders = [message
                 for path in sorted(TESTS.rglob("test_*.py"))
                 for message in gate_offences(path.read_text(encoding="utf-8-sig"),
                                              path.relative_to(REPO_ROOT).as_posix())]
    assert offenders == [], offenders


def gate_offences(source: str, where: str = "module") -> list[str]:
    """Why this module source is an ungated expensive test, or an empty list. Public: the
    probe table below runs the real function rather than a restatement of it."""
    tree = ast.parse(source, filename=where)
    constants = _module_constants(tree)
    gated = _gate_names(tree, constants)
    offences = []
    switches = _environment_names(tree, constants) & set(GATED_SWITCHES)
    if switches and not (switches & gated):
        offences.append(f"{where} reads {sorted(switches)} but no skip guard is conditioned on it")
    imported = _dangerous_imports(tree)
    if imported and not gated:
        offences.append(f"{where} imports {sorted(imported)} with no environment skip guard")
    return offences


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"`, so a switch held in a constant is still seen."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value.value
    return found


def _as_name(node: ast.AST | None, constants: Mapping[str, str]) -> str | None:
    """The string an expression denotes, whether written inline or held in a constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _environment_names(node: ast.AST, constants: Mapping[str, str]) -> set[str]:
    """Every literal key this subtree reads from the process environment, any spelling.

    Covers `os.environ[...]`, `os.environ.get(...)`, `os.getenv(...)`, a bare `getenv(...)`
    or `environ.get(...)` from `from os import ...`, and `"NAME" in os.environ`.
    """
    names: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Subscript) and _is_environ(item.value):
            names.update(filter(None, [_as_name(item.slice, constants)]))
        elif isinstance(item, ast.Compare) and isinstance(item.ops[0], ast.In):
            if any(_is_environ(right) for right in item.comparators):
                names.update(filter(None, [_as_name(item.left, constants)]))
        elif isinstance(item, ast.Call):
            attribute = item.func.attr if isinstance(item.func, ast.Attribute) else (
                item.func.id if isinstance(item.func, ast.Name) else None)
            reads = (attribute == "getenv"
                     or (attribute == "get" and isinstance(item.func, ast.Attribute)
                         and _is_environ(item.func.value)))
            if reads and item.args:
                names.update(filter(None, [_as_name(item.args[0], constants)]))
    return names


def _is_environ(node: ast.AST) -> bool:
    """`os.environ`, or a bare `environ` imported from `os`."""
    return ((isinstance(node, ast.Attribute) and node.attr == "environ")
            or (isinstance(node, ast.Name) and node.id == "environ"))


def _gate_names(tree: ast.Module, constants: Mapping[str, str]) -> set[str]:
    """Environment keys read INSIDE a skip condition. Empty means the module is not gated.

    Reading the condition and not the file is the whole point: a `skipif(node is None)`
    beside a test that opens the microphone gates nothing, and used to satisfy this check.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_skipif(node.func):
            conditions = [*node.args[:1], *(item.value for item in node.keywords if item.arg == "condition")]
            for condition in conditions:
                names |= _environment_names(condition, constants)
        elif isinstance(node, ast.If) and _calls_skip(node.body):
            names |= _environment_names(node.test, constants)
    return names


def _is_skipif(func: ast.AST) -> bool:
    return isinstance(func, ast.Attribute) and func.attr == "skipif"


def _calls_skip(body: list[ast.stmt]) -> bool:
    return any(isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr == "skip"
               for statement in body for item in ast.walk(statement))


def _dangerous_imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        found |= {item for item in DANGEROUS_IMPORTS
                  if any(name == item or name.startswith(item + ".") for name in names)}
    return found


# ----------------------------------------------- 3. the release path itself

def test_verify_release_neither_imports_nor_runs_the_test_lab():
    """The release gate runs the same `pytest -q` as everyone else, and nothing else.

    A line here that set an opt-in, or called `python -m jarvis.testlab`, would make every
    release take the user's microphone. The check is on the source, not on a run: this
    script runs the whole suite in one process and must never be executed by a test.
    """
    source = VERIFY_RELEASE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(VERIFY_RELEASE))
    imported = {name
                for node in ast.walk(tree)
                for name in ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                             else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])}
    assert not any(name.startswith("jarvis.testlab") for name in imported), imported
    assert "jarvis.testlab" not in source, "verify_release.py must not name the Test Lab"
    for switch in OPT_IN_ENV_NAMES:
        assert switch not in source, f"verify_release.py must not set {switch}"


def test_the_rollout_gate_is_documented_with_every_switch_it_covers():
    """The gate's switch list and the doc's table are the same set, both ways."""
    section = DOCS.read_text(encoding="utf-8").partition("<!-- testlab-rollout -->")[2] \
        .partition("<!-- /testlab-rollout -->")[0]
    assert section.strip(), "docs/testlab.md carries no rollout gate table"
    documented = {name for name in (*OPT_IN_ENV_NAMES, *TEST_ONLY_SWITCHES) if f"`{name}`" in section}
    assert documented == set(GATED_SWITCHES), sorted(set(GATED_SWITCHES) ^ documented)


# ----------------------------------- 4. importing the Test Lab is cheap

@pytest.mark.parametrize("module", ["jarvis.testlab.api", "jarvis.testlab.cli", "jarvis.testlab.composition"])
def test_importing_a_test_lab_entry_point_loads_no_device_or_provider_client(module):
    """In a FRESH interpreter, so nothing another test already imported can hide a regression.

    `sounddevice` opens PortAudio at import; `openai` and `httpx` are the provider stack.
    Neither belongs in the cost of listing a run, and the hardware profile imports its
    device module lazily (`TestLab._build_contention`) precisely so this holds.
    """
    probe = ("import importlib, sys; importlib.import_module(%r); "
             "print(sorted(name for name in ('sounddevice', 'openai', 'httpx') if name in sys.modules))" % module)
    result = subprocess.run([sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", f"{module} pulled {result.stdout.strip()}"


#: Probe modules the gate check is measured against, each written the way a real offender
#: (or a legitimate module) would be. Every `True` row was MISSED by the substring version
#: this file shipped with before the Slice 12 rework; the two `False` rows must stay quiet,
#: because a check that flags honest modules gets deleted by the first person it annoys.
GATE_PROBES = (
    ("double quotes, unguarded",
     'import os\nif os.environ.get("JARVIS_TESTLAB_AUDIO") == "1":\n    pass\n', True),
    ("single quotes, unguarded",
     "import os\nif os.environ.get('JARVIS_TESTLAB_AUDIO') == '1':\n    pass\n", True),
    ("the switch name held in a constant",
     'import os\nSWITCH = "JARVIS_TESTLAB_HARDWARE"\nvalue = os.environ.get(SWITCH)\n', True),
    ("from os import getenv",
     'from os import getenv\nvalue = getenv("JARVIS_TESTLAB_GUIDED")\n', True),
    ("membership instead of a read",
     'import os\nif "JARVIS_TESTLAB_LIVE" in os.environ:\n    pass\n', True),
    ("a subscript instead of .get",
     'import os\nvalue = os.environ["JARVIS_TESTLAB_AUDIO_ARTIFACTS"]\n', True),
    ("a skipif that guards something else entirely",
     'import os\nimport pytest\nimport shutil\n'
     'pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node absent")\n'
     'value = os.environ.get("JARVIS_TESTLAB_AUDIO")\n', True),
    ("opens a device and names no switch at all",
     "import sounddevice\n\n\ndef test_it():\n    sounddevice.query_devices()\n", True),
    ("gated on the switch it reads",
     'import os\nimport pytest\n'
     'pytestmark = pytest.mark.skipif(os.environ.get("JARVIS_TESTLAB_AUDIO") != "1", reason="opt-in")\n'
     'value = os.environ.get("JARVIS_TESTLAB_AUDIO")\n', False),
    ("gated by a pytest.skip() under an if",
     'import os\nimport pytest\n\n\ndef test_it():\n'
     '    if os.getenv("JARVIS_TESTLAB_HARDWARE") != "1":\n        pytest.skip("opt-in")\n', False),
    ("drives the sounddevice DOUBLE, so it reaches nothing",
     "from tests.fakes.sounddevice_double import FakeSoundDevice, install\n\n\n"
     "def test_it():\n    install(FakeSoundDevice())\n", False),
    ("reads an unrelated environment variable",
     'import os\nvalue = os.environ.get("JARVIS_LIVE_OPENAI")\n', False),
)


@pytest.mark.parametrize("label, source, expected", GATE_PROBES, ids=[item[0] for item in GATE_PROBES])
def test_the_gate_check_catches_what_it_claims_to(label, source, expected):
    offences = gate_offences(source, where=label)
    assert bool(offences) is expected, offences
