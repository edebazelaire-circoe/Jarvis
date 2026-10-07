"""La documentation du mot d'éveil dit ce que le code livre (jarvis-wake-word, Slice 08).

Contrôle documentaire léger, statique : il lit des sources et des pages, il n'importe
aucun module de `jarvis/`, il n'ouvre aucun micro. Il garde dans les deux sens :

- ce que `docs/OPERATIONS.md` cite (codes de refus, codes de panne, noms de traces,
  phrases de veille, défauts et bornes) existe dans le code ;
- ce que le code expose (les mêmes catégories) est documenté.

Un code, une trace ou une phrase ajoutés d'un côté sans l'autre font échouer ce test.
"""

from __future__ import annotations

import ast
import getpass
import json
import os
import re
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ROOT / "docs" / "OPERATIONS.md"
TASK = ROOT / "tasks" / "jarvis-wake-word"

SETTINGS_SOURCE = ROOT / "jarvis" / "runtime" / "wake_word_settings.py"
SETTINGS_UI = ROOT / "jarvis" / "runtime" / "control_center_wake_word.js"
REALTIME_AUDIO = ROOT / "jarvis" / "runtime" / "realtime_audio.py"
DETECTOR_SOURCES = (
    ROOT / "jarvis" / "adapters" / "wakeword_openwakeword.py",
    ROOT / "jarvis" / "adapters" / "wakeword_own_stream.py",
    ROOT / "jarvis" / "adapters" / "wakeword_shared_pcm.py",
    ROOT / "jarvis" / "adapters" / "wakeword_model_catalog.py",
)
TRACE_SOURCES = (
    *DETECTOR_SOURCES,
    ROOT / "jarvis" / "runtime" / "voice_v2.py",
    ROOT / "jarvis" / "runtime" / "presentation_runtime.py",
)

#: Diagnostics de LECTURE du bloc : ils ne refusent rien à l'écriture (les 13 refus
#: sont tout le reste des codes `wake_word_*` de `wake_word_settings.py`).
READ_DIAGNOSTICS = {"wake_word_block_malformed", "wake_word_stored_version_unreadable"}
#: Codes `wake_word_*` documentés qui ne vivent pas dans `wake_word_settings.py`.
OTHER_WAKE_WORD_CODES = {"wake_word_settings_invalid"}
#: Noms de module cités par la doc, pas des codes (`wake_word_settings.py`).
MODULE_NAMES = {"wake_word_settings", "wake_word_install", "wake_word_validation", "wake_word_disabled"}
#: Chaînes `wake_*` qui ne sont pas des codes de panne.
NOT_FAILURE_CODES = {"wake_word", "wake_toggle"}
#: Livrables annoncés avant d'exister (vide : l'outillage de la Slice 09 est livré).
PLANNED_FILES: set[str] = set()
EXPECTED_REFUSALS = 13
EXPECTED_SLEEP_PHRASES = {"jarvis mute", "jarvis stop listening", "jarvis arrete d ecouter"}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(_text(path))
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def _wake_sections() -> str:
    """Les trois sections du mot d'éveil de `OPERATIONS.md`, de leur titre au suivant."""

    text = _text(OPERATIONS)
    return _section(text, "### Mot d'éveil (bloc `wake_word`)", "### Expérimental")


def _diagnostic_section() -> str:
    return _section(_text(OPERATIONS), "### Diagnostic du mot d'éveil", "### Expérimental")


def _fold(value: str) -> str:
    base = unicodedata.normalize("NFKD", value.casefold())
    base = "".join(char for char in base if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", base).split())


# ----------------------------------------------------- codes du bloc `wake_word`


def _settings_codes() -> set[str]:
    return {value for value in _string_constants(SETTINGS_SOURCE) if re.fullmatch(r"wake_word_[a-z_]+", value)}


def test_the_code_has_thirteen_refusal_codes_and_two_read_diagnostics():
    codes = _settings_codes()
    assert READ_DIAGNOSTICS <= codes
    assert len(codes - READ_DIAGNOSTICS) == EXPECTED_REFUSALS, sorted(codes - READ_DIAGNOSTICS)


def test_every_code_of_the_settings_block_is_documented():
    documented = set(re.findall(r"wake_word_[a-z_]+", _wake_sections()))
    missing = _settings_codes() - documented
    assert not missing, f"codes du bloc wake_word absents de docs/OPERATIONS.md : {sorted(missing)}"


def test_every_wake_word_code_the_operations_page_cites_exists_in_the_code():
    cited = set(re.findall(r"wake_word_[a-z_]+", _wake_sections()))
    known = _settings_codes() | OTHER_WAKE_WORD_CODES
    # `wake_word_settings_invalid` vit dans app.py, pas dans le module des réglages.
    assert "wake_word_settings_invalid" in _string_constants(ROOT / "jarvis" / "app.py")
    unknown = cited - known - MODULE_NAMES
    assert not unknown, f"codes cités par la doc et absents du code : {sorted(unknown)}"


def test_the_settings_screen_translates_every_refusal_code():
    ui = _text(SETTINGS_UI)
    missing = {code for code in _settings_codes() if code not in ui}
    assert not missing, f"codes sans libellé dans l'écran des Réglages : {sorted(missing)}"


def test_the_documented_defaults_and_bounds_are_the_ones_in_the_code():
    constants = {}
    for node in ast.parse(_text(SETTINGS_SOURCE)).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant):
            constants[node.targets[0].id] = node.value.value
    assert constants["DEFAULT_ENABLED"] is False
    table = _section(_wake_sections(), "| Champ | Valeurs | Défaut |", "- **Lecture tolérante**")
    rows = {line.split("|")[1].strip(" `"): line for line in table.splitlines()[2:] if line.startswith("|")}
    assert "**`false`**" in rows["enabled"]
    assert f"`{constants['DEFAULT_SENSITIVITY']}`" in rows["sensitivity"]
    assert f"`{constants['DEFAULT_COOLDOWN_MS']}`" in rows["cooldown_ms"]
    assert f"de {constants['COOLDOWN_MS_MIN']} à 30 000" in rows["cooldown_ms"]
    assert constants["COOLDOWN_MS_MAX"] == 30000
    assert f"de {constants['SENSITIVITY_MIN']} à {constants['SENSITIVITY_MAX']}" in rows["sensitivity"]


# ------------------------------------------------------------- codes de panne


def _failure_codes() -> set[str]:
    codes: set[str] = set()
    for path in TRACE_SOURCES:
        codes |= {v for v in _string_constants(path) if re.fullmatch(r"wake_[a-z]+(_[a-z]+)*", v)}
    return {code for code in codes if code not in NOT_FAILURE_CODES and not code.startswith("wake_word")}


def test_every_failure_code_of_the_detectors_is_documented():
    documented = set(re.findall(r"wake_[a-z]+(?:_[a-z]+)*", _diagnostic_section()))
    missing = _failure_codes() - documented
    assert not missing, f"codes de panne absents de la section Diagnostic : {sorted(missing)}"


def test_every_failure_code_the_diagnostic_section_cites_exists_in_the_code():
    cited = {c for c in re.findall(r"wake_[a-z]+(?:_[a-z]+)*", _diagnostic_section()) if not c.startswith("wake_word")}
    unknown = cited - _failure_codes() - NOT_FAILURE_CODES
    assert not unknown, f"codes cités et absents du code : {sorted(unknown)}"


# ---------------------------------------------------------------------- traces

_TRACE_NAME = re.compile(r"wake\.[a-z_]+\.[a-z_]+|voice\.wake\.outcome|voice\.wake\b|voice\.connecting|wake_call_failed")


def _trace_names_in_code() -> set[str]:
    names: set[str] = set()
    for path in TRACE_SOURCES:
        for value in _string_constants(path):
            if _TRACE_NAME.fullmatch(value):
                names.add(value)
    return names


def test_the_trace_names_exist_and_are_documented_in_both_directions():
    in_code = _trace_names_in_code()
    assert {"wake.shared_pcm.detected", "wake.own_stream.detected", "voice.wake", "voice.wake.outcome",
            "voice.connecting", "wake.openwakeword.slow_inference"} <= in_code
    documented = set(_TRACE_NAME.findall(_wake_sections()))
    # `voice.wake` est aussi préfixe de `voice.wake.outcome` : la regex garde la forme longue d'abord.
    assert in_code - documented == set(), f"traces absentes de la doc : {sorted(in_code - documented)}"
    assert documented - in_code == set(), f"traces citées et absentes du code : {sorted(documented - in_code)}"


# ---------------------------------------------------------- phrases de veille


def _sleep_phrases() -> set[str]:
    tree = ast.parse(_text(REALTIME_AUDIO))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "SLEEP_COMMANDS":
            value = node.value
            assert isinstance(value, ast.Call), "SLEEP_COMMANDS doit rester un frozenset({...})"
            literal = ast.literal_eval(value.args[0])
            return {_fold(" ".join(words)) for words in literal}
    raise AssertionError("SLEEP_COMMANDS introuvable dans realtime_audio.py")


def test_the_sleep_phrases_of_the_code_are_the_three_documented_ones():
    phrases = _sleep_phrases()
    assert phrases == EXPECTED_SLEEP_PHRASES
    docs = _fold(_wake_sections())
    for phrase in phrases:
        assert phrase in docs, f"phrase de veille non documentée : {phrase}"
    assert not any("sleep" in p or "dormir" in p for p in phrases)


def test_the_documentation_does_not_promise_a_go_to_sleep_phrase():
    text = _wake_sections()
    at = text.index("go to sleep")
    assert "ne coupent pas" in text[at:at + 120], "la doc doit dire que « go to sleep » ne coupe pas la séance"


# --------------------------------------------------- fiches d'acceptation (HV)

HARDWARE = ROOT / "docs" / "HARDWARE_ACCEPTANCE.md"
STATUS = ROOT / "docs" / "ACCEPTANCE_STATUS.md"
MIC_JSON = TASK / "slices" / "09-human-microphone-validation" / "human-validation.json"


def _mic_ids() -> list[str]:
    data = json.loads(_text(MIC_JSON))
    return [item["id"] for item in data["checks"][0]["subchecks"]]


@pytest.mark.skipif(not MIC_JSON.exists(), reason="dossier du handoff archivé ailleurs")
def test_the_hardware_sheets_list_every_mic_check_and_mark_none_validated():
    ids = _mic_ids()
    assert len(ids) == 12 and ids[0].endswith("-a") and ids[-1].endswith("-l")
    hardware = _section(_text(HARDWARE), "## 12. Configurable wake word", "### 12.2 Result sheet")
    status = _section(_text(STATUS), "## Configurable wake word (openWakeWord): workstation status", "## Slice 11 evidence")
    for check in ids + ["HV-WAKEWORD-UI-01"]:
        for name, page in (("HARDWARE_ACCEPTANCE", hardware), ("ACCEPTANCE_STATUS", status)):
            row = next((line for line in page.splitlines() if line.startswith("| `" + check + "`")), None)
            assert row is not None, f"{check} absent de {name}"
            assert row.rstrip().endswith("**À FAIRE** |"), f"{check} dans {name} : statut inattendu"
    for forbidden in ("PASS", "validé", "VALIDATED"):
        assert forbidden not in status.replace("PASS automated", "")
    data = json.loads(_text(MIC_JSON))
    assert {s["status"] for s in data["checks"][0]["subchecks"]} == {"À FAIRE"}


# ------------------------------------------------- traçabilité des critères

HANDOFF = TASK / "HANDOFF.md"
TRACEABILITY = TASK / "docs" / "02-acceptance-traceability.md"


@pytest.mark.skipif(not HANDOFF.exists() or not TRACEABILITY.exists(), reason="dossier du handoff archivé ailleurs")
def test_the_traceability_table_has_one_row_per_handoff_acceptance_criterion():
    handoff = _text(HANDOFF)
    block = _section(handoff, "## Acceptance criteria", "## Non-goals")
    criteria = [line for line in block.splitlines() if line.startswith("- ")]
    table = _text(TRACEABILITY)
    rows = [line for line in table.splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(rows) == len(criteria) == 13
    for number, row in enumerate(rows, start=1):
        assert row.startswith(f"| {number} |")
        assert any(status in row for status in ("couvert", "à valider par le Human", "écart accepté")), row[:80]
    assert "**validé**" not in table.casefold() and "| validé |" not in table.casefold()


# ---------------------------------------------------------------- références


def _cited_paths(text: str) -> set[str]:
    found: set[str] = set()
    for token in re.findall(r"`([^`\n]+)`", text):
        token = token.split("::")[0].strip()
        if re.fullmatch(r"(?:jarvis|tests|scripts|docs|third_party|tasks)/[A-Za-z0-9_./-]+", token) and "*" not in token:
            found.add(token.rstrip("/"))
    return found


def test_the_files_the_new_sections_cite_exist():
    pages = [
        _wake_sections(),
        _text(ROOT / "docs" / "presentation-audio-capture.md"),
        _section(_text(HARDWARE), "## 12. Configurable wake word", "### 12.2 Result sheet"),
        _section(_text(STATUS), "## Configurable wake word (openWakeWord): workstation status", "## Slice 11 evidence"),
        _section(_text(ROOT / "docs" / "SECURITY.md"), "### 17. Configurable wake word", "## Residual risks"),
        _section(_text(ROOT / "third_party" / "README.md"), "## Wake word (openWakeWord)", "Run `python scripts/bootstrap"),
    ]
    for name in ("02-acceptance-traceability.md", "03-human-decisions.md"):
        if (TASK / "docs" / name).exists():
            pages.append(_text(TASK / "docs" / name))
    missing = sorted(p for page in pages for p in _cited_paths(page)
                     if not (ROOT / p).exists() and p not in PLANNED_FILES and "/..." not in p)
    assert not missing, f"fichiers cités et introuvables : {missing}"


# ------------------------------------------------------------ vocabulaire, vie privée

CANONICAL_PAGES = (
    "docs/OPERATIONS.md", "docs/ARCHITECTURE.md", "docs/interaction-mode.md", "docs/presentation-audio-capture.md",
    "docs/presentation-addressed-turn.md", "docs/SECURITY.md", "docs/ACCEPTANCE_STATUS.md", "docs/HARDWARE_ACCEPTANCE.md",
    "docs/conversation-events.md", "README.md", "third_party/README.md",
)


def test_the_canonical_pages_use_the_shipped_vocabulary():
    for relative in CANONICAL_PAGES:
        text = _text(ROOT / relative)
        assert "keyboard_f9" not in text, relative
        assert not re.search(r"wakeWord\.", text), relative


def test_the_licence_is_stated_identically_in_the_notice_and_the_operations_page():
    notice = _text(ROOT / "third_party" / "README.md")
    operations = _text(OPERATIONS)
    for text in (notice, operations):
        assert "CC BY-NC-SA 4.0" in text
        assert "Apache-2.0" in text
    assert "tests privés, non commercial" in notice
    assert "tests privés" in operations and "non commercial" in operations


def _machine_identities() -> set[str]:
    names = {getpass.getuser(), os.environ.get("USERNAME", ""), Path.home().name}
    return {n for n in names if len(n) >= 4 and n.casefold() not in {"jarvis", "user", "users", "admin", "runner", "public", "default"}}


def test_the_documents_of_this_slice_keep_no_home_path_and_no_user_name():
    files = []
    files += [TASK / "docs" / "02-acceptance-traceability.md", TASK / "docs" / "03-human-decisions.md", MIC_JSON,
              TASK / "Issues" / "002-no-model-install-command.md", TASK / "Issues" / "003-owner-count-not-readable-at-rest.md"]
    names = _machine_identities()
    texts = {path.name: _text(path) for path in files if path.exists()}
    texts["OPERATIONS (mot d'éveil)"] = _wake_sections()
    texts["HARDWARE_ACCEPTANCE §12"] = _section(_text(HARDWARE), "## 12. Configurable wake word", "### 12.2 Result sheet")
    texts["ACCEPTANCE_STATUS (mot d'éveil)"] = _section(
        _text(STATUS), "## Configurable wake word (openWakeWord): workstation status", "## Slice 11 evidence")
    texts["SECURITY §17"] = _section(_text(ROOT / "docs" / "SECURITY.md"), "### 17. Configurable wake word", "## Residual risks")
    texts["presentation-audio-capture"] = _text(ROOT / "docs" / "presentation-audio-capture.md")
    for label, text in texts.items():
        assert not re.search(r"[A-Za-z]:\\Users\\", text), f"{label} : chemin personnel"
        assert "/Users/" not in text and "/home/" not in text, f"{label} : chemin personnel"
        for name in names:
            assert not re.search(rf"\b{re.escape(name)}\b", text), f"{label} : nom d'utilisateur de la machine"


# ------------------------------------------------- outillage de la Slice 09

HARDWARE = ROOT / "docs" / "HARDWARE_ACCEPTANCE.md"
APP_SOURCE = ROOT / "jarvis" / "app.py"
INSTALL_SOURCE = ROOT / "jarvis" / "runtime" / "wake_word_install.py"
MEASURE_SCRIPT = ROOT / "scripts" / "measure_wake_word_validation.py"
DISABLED_SCRIPT = ROOT / "scripts" / "check_wake_word_disabled.py"
INSTALL_COMMAND = "python -m jarvis wake-word install"
STATUS_COMMAND = "python -m jarvis wake-word status"


def _installer_section() -> str:
    return _section(_text(OPERATIONS), "### Installer openWakeWord", "### Diagnostic du mot d'éveil")


def test_the_install_command_the_docs_cite_exists_in_the_command_line():
    assert {"wake-word"} <= _string_constants(APP_SOURCE)
    assert {"install", "status", "--yes"} <= _string_constants(INSTALL_SOURCE) | _string_constants(APP_SOURCE)
    for page in (_installer_section(), _section(_text(HARDWARE), "### 12.0 Common prerequisites", "### 12.1 Checklist")):
        assert INSTALL_COMMAND in page, "la commande d'installation n'est pas citée"
    assert STATUS_COMMAND in _installer_section()


def test_the_one_line_python_installation_is_no_longer_the_documented_way():
    for page in (_installer_section(), _section(_text(HARDWARE), "### 12.0 Common prerequisites", "### 12.1 Checklist")):
        assert 'python -c "from jarvis.adapters import wakeword_model_catalog' not in page


def test_the_install_section_states_what_the_command_downloads_and_how_it_fails():
    section = _installer_section()
    for fact in ("3 685 906", "CC BY-NC-SA 4.0", "--yes", "wake_model_download_failed", "wake_model_mismatch",
                 "wake_model_install_failed", "idempotent"):
        assert fact in section, fact


def test_the_measurement_tools_are_delivered_and_cited_by_the_acceptance_sheet():
    assert MEASURE_SCRIPT.is_file() and DISABLED_SCRIPT.is_file()
    sheet = _section(_text(HARDWARE), "## 12. Configurable wake word", "### 12.2 Result sheet")
    assert "scripts/measure_wake_word_validation.py" in sheet and "scripts/check_wake_word_disabled.py" in sheet
    assert "until it exists, count by hand" not in sheet


def test_every_subcheck_row_names_the_command_that_reads_its_proof():
    sheet = _section(_text(HARDWARE), "### 12.1 Checklist", "### 12.2 Result sheet")
    rows = [line for line in sheet.splitlines() if line.startswith("| `HV-WAKEWORD-MIC-01-")]
    assert len(rows) == 12
    commands = ("scripts/measure_wake_word_validation.py", "scripts/check_wake_word_disabled.py", STATUS_COMMAND)
    for row in rows:
        assert any(command in row for command in commands), row[:60]


def test_the_flags_the_docs_give_to_the_tools_exist_in_the_tools():
    for script in (MEASURE_SCRIPT, DISABLED_SCRIPT):
        source = _text(script)
        defined = set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source))
        pages = _text(OPERATIONS) + _text(HARDWARE)
        cited: set[str] = set()
        for line in pages.splitlines():
            if script.name in line:
                cited |= set(re.findall(r"(--[a-z0-9]+(?:-[a-z0-9]+)*)", line))
        assert cited <= defined, f"options citées et absentes de {script.name} : {sorted(cited - defined)}"


def test_the_issues_say_what_the_tooling_changed():
    two = _text(TASK / "Issues" / "002-no-model-install-command.md")
    three = _text(TASK / "Issues" / "003-owner-count-not-readable-at-rest.md")
    assert INSTALL_COMMAND in two and "Résolue" in two
    assert "check_wake_word_disabled.py" in three and "reste ouverte" in three.casefold()
