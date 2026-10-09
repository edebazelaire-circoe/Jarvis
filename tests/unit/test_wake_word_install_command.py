"""Slice 09 (jarvis-wake-word, Issue 002) - `python -m jarvis wake-word install|status`.

L'installation des trois modèles openWakeWord est une commande explicite. Rien
ici ne touche le réseau : `urllib.request.urlopen` est remplacé par un faux qui
sert des octets fabriqués, et toute tentative non prévue fait échouer le test.
Les modèles du catalogue sont remplacés par trois petits faux, sauf dans les
tests qui lisent le vrai catalogue pour son annonce (URL, tailles, licence).
"""

from __future__ import annotations

import asyncio
import hashlib
import getpass
import io
import json
import sys
import urllib.request
from pathlib import Path

import pytest

from jarvis import app
from jarvis.adapters import wakeword_model_catalog as catalog
from jarvis.runtime import wake_word_install

PAYLOADS = {
    "melspectrogram.onnx": b"mel-" * 40,
    "embedding_model.onnx": b"emb-" * 50,
    "hey_jarvis_v0.1.onnx": b"hey-" * 60,
}


def fake_specs() -> tuple[catalog.WakeModelSpec, ...]:
    return tuple(
        catalog.WakeModelSpec(
            key=key, filename=name, sha256=hashlib.sha256(PAYLOADS[name]).hexdigest(), size=len(PAYLOADS[name]), role=key,
        )
        for key, name in (("melspectrogram", "melspectrogram.onnx"), ("embedding", "embedding_model.onnx"),
                          ("hey_jarvis", "hey_jarvis_v0.1.onnx"))
    )


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self._stream.read(amount)


class Network:
    """Remplace `urlopen` : sert `PAYLOADS` par nom de fichier, ou échoue comme on le lui dit."""

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.serve: dict[str, bytes | BaseException] = {}

    def __call__(self, request, timeout=None):  # noqa: ANN001
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.requested.append(url)
        name = url.rsplit("/", 1)[-1]
        answer = self.serve.get(name, PAYLOADS.get(name))
        if isinstance(answer, BaseException):
            raise answer
        if answer is None:
            raise AssertionError(f"URL inattendue : {url}")
        return FakeResponse(answer)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("accès réseau réel pendant un test")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def runtime(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def net(monkeypatch) -> Network:
    network = Network()
    monkeypatch.setattr(urllib.request, "urlopen", network)
    return network


@pytest.fixture
def small_catalog(monkeypatch) -> tuple[catalog.WakeModelSpec, ...]:
    specs = fake_specs()
    monkeypatch.setattr(catalog, "MODELS", specs)
    return specs


def run(*argv: str, answers: list[str] | None = None) -> tuple[int, str]:
    """Lance la vraie ligne de commande ; `answers` simule le clavier (vide : stdin fermé)."""

    out = io.StringIO()
    feed = iter(answers or [])

    def keyboard(prompt: str = "") -> str:
        out.write(prompt)
        try:
            return next(feed)
        except StopIteration:
            raise EOFError from None

    args = app._parser().parse_args(["wake-word", *argv])
    code = wake_word_install.run_cli(args, out=out, err=out, input_fn=keyboard)
    return code, out.getvalue()


def tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*"))


MODELS_DIR = "wake-word/models"


# ------------------------------------------------------------- la sous-commande


def test_the_subcommand_exists_with_install_and_status():
    args = app._parser().parse_args(["wake-word", "install", "--yes"])
    assert args.command == "wake-word" and args.wake_action == "install" and args.yes is True
    assert app._parser().parse_args(["wake-word", "status"]).wake_action == "status"
    with pytest.raises(SystemExit):
        app._parser().parse_args(["wake-word"])


def test_the_real_entry_point_dispatches_to_the_command(runtime, small_catalog, capsys):
    assert asyncio.run(app._amain(["wake-word", "status"])) == 1  # rien d'installé : pas prêt
    assert "absent" in capsys.readouterr().out


# ----------------------------------------------------------------------- status


def test_status_lists_each_model_absent_without_any_network(runtime, small_catalog):
    code, output = run("status")
    assert code == 1
    for spec in small_catalog:
        assert spec.filename in output
    assert output.count("wake_model_missing") == 3
    assert not (runtime / "wake-word").exists(), "status ne crée rien"


def test_status_says_verified_for_exact_files_and_altered_for_the_others(runtime, small_catalog):
    folder = runtime / MODELS_DIR
    folder.mkdir(parents=True)
    (folder / "melspectrogram.onnx").write_bytes(PAYLOADS["melspectrogram.onnx"])
    (folder / "embedding_model.onnx").write_bytes(b"x" * len(PAYLOADS["embedding_model.onnx"]))
    code, output = run("status")
    lines = {line.split()[0]: line for line in output.splitlines() if line.strip().startswith(tuple(PAYLOADS))}
    assert "vérifié" in lines["melspectrogram.onnx"]
    assert "wake_model_mismatch" in lines["embedding_model.onnx"]
    assert "wake_model_missing" in lines["hey_jarvis_v0.1.onnx"]
    assert code == 1


def test_status_is_ready_only_when_the_three_models_and_the_package_are_there(runtime, small_catalog, monkeypatch):
    folder = runtime / MODELS_DIR
    folder.mkdir(parents=True)
    for name, payload in PAYLOADS.items():
        (folder / name).write_bytes(payload)
    monkeypatch.setattr(wake_word_install, "package_installed", lambda: False)
    code, output = run("status")
    assert code == 1 and "wake_package_missing" in output and "3 sur 3" in output
    monkeypatch.setattr(wake_word_install, "package_installed", lambda: True)
    code, output = run("status")
    assert code == 0 and "prêt" in output.lower()


def test_status_json_is_machine_readable(runtime, small_catalog, monkeypatch):
    monkeypatch.setattr(wake_word_install, "package_installed", lambda: True)
    code, output = run("status", "--json")
    report = json.loads(output)
    assert code == 1 and report["ready"] is False and report["package_installed"] is True
    assert [m["state"] for m in report["models"]] == ["missing"] * 3
    assert report["models"][0]["code"] == "wake_model_missing"


def test_status_never_imports_the_wake_word_library(runtime, small_catalog):
    before = {name for name in ("openwakeword", "onnxruntime") if name in sys.modules}
    run("status")
    assert {name for name in ("openwakeword", "onnxruntime") if name in sys.modules} == before


# ---------------------------------------------------------------------- install


def test_install_announces_the_real_catalog_before_asking_and_downloads_nothing_if_declined(runtime):
    code, output = run("install", answers=["n"])
    assert code == 1
    assert "3 fichiers" in output and "3 685 906 octets" in output
    for spec in catalog.MODELS:
        assert spec.url in output and spec.filename in output
    assert "CC BY-NC-SA 4.0" in output and "usage privé" in output and "non commercial" in output
    assert "$JARVIS_RUNTIME_DIR/wake-word/models" in output
    assert "[o/N]" in output
    assert not (runtime / "wake-word").exists()


def test_install_without_a_keyboard_and_without_yes_asks_for_yes_and_downloads_nothing(runtime, net, small_catalog):
    code, output = run("install")
    assert code == 2 and "--yes" in output
    assert net.requested == [] and not (runtime / "wake-word").exists()


@pytest.mark.parametrize("answer", ["o", "O", "oui", "y", "yes"])
def test_install_downloads_after_a_yes_answer(runtime, net, small_catalog, answer):
    code, output = run("install", answers=[answer])
    assert code == 0, output
    assert len(net.requested) == 3
    for spec in small_catalog:
        assert (runtime / MODELS_DIR / spec.filename).read_bytes() == PAYLOADS[spec.filename]


@pytest.mark.parametrize("answer", ["", "n", "non", "peut-être"])
def test_anything_but_yes_declines(runtime, net, small_catalog, answer):
    code, _ = run("install", answers=[answer])
    assert code == 1 and net.requested == []


def test_install_with_yes_does_not_ask_and_verifies_size_and_sha256(runtime, net, small_catalog):
    code, output = run("install", "--yes")
    assert code == 0
    assert "[o/N]" not in output
    assert output.count("installé et vérifié") == 3 and "3 sur 3" in output
    assert tree(runtime) == sorted([
        "wake-word", "wake-word/models", *(f"{MODELS_DIR}/{s.filename}" for s in small_catalog)])


def test_install_is_idempotent_and_the_second_run_touches_no_network(runtime, net, small_catalog):
    assert run("install", "--yes")[0] == 0
    net.requested.clear()
    stamps = {p: p.stat().st_mtime_ns for p in (runtime / MODELS_DIR).iterdir()}
    code, output = run("install", "--yes")
    assert code == 0 and net.requested == [] and "déjà installés" in output
    assert {p: p.stat().st_mtime_ns for p in (runtime / MODELS_DIR).iterdir()} == stamps
    code, output = run("install")  # même sans --yes : rien à demander
    assert code == 0 and net.requested == [] and "[o/N]" not in output


def test_install_downloads_only_what_is_missing(runtime, net, small_catalog):
    folder = runtime / MODELS_DIR
    folder.mkdir(parents=True)
    (folder / "melspectrogram.onnx").write_bytes(PAYLOADS["melspectrogram.onnx"])
    code, output = run("install", "--yes")
    assert code == 0 and len(net.requested) == 2
    assert all("melspectrogram" not in url for url in net.requested)
    assert "2 fichiers" in output


def test_a_network_failure_is_said_with_its_stable_code_and_exits_non_zero(runtime, net, small_catalog):
    net.serve["embedding_model.onnx"] = OSError("réseau coupé")
    code, output = run("install", "--yes")
    assert code == 1
    assert "wake_model_download_failed" in output and "embedding_model.onnx" in output
    assert not (runtime / MODELS_DIR / "embedding_model.onnx").exists()
    assert not list((runtime / MODELS_DIR).glob("*.part"))
    # Le premier a été installé ; le réseau est coupé, on s'arrête là : "1 sur 3", le troisième n'est pas tenté.
    assert (runtime / MODELS_DIR / "melspectrogram.onnx").is_file() and "1 sur 3" in output
    assert len(net.requested) == 2 and not net.requested[-1].endswith("hey_jarvis_v0.1.onnx")


def test_a_wrong_hash_is_a_mismatch_and_installs_nothing(runtime, net, small_catalog):
    net.serve["hey_jarvis_v0.1.onnx"] = b"z" * len(PAYLOADS["hey_jarvis_v0.1.onnx"])
    code, output = run("install", "--yes")
    assert code == 1 and "wake_model_mismatch" in output
    assert not (runtime / MODELS_DIR / "hey_jarvis_v0.1.onnx").exists()
    assert not list((runtime / MODELS_DIR).glob("*.part"))


def test_a_truncated_download_is_a_mismatch_too(runtime, net, small_catalog):
    net.serve["melspectrogram.onnx"] = PAYLOADS["melspectrogram.onnx"][:-5]
    code, output = run("install", "--yes")
    assert code == 1 and "wake_model_mismatch" in output


def test_an_install_failure_is_said_with_its_code(runtime, net, small_catalog, monkeypatch):
    def refuse(source, target):  # noqa: ANN001
        raise PermissionError("verrouillé")

    monkeypatch.setattr(catalog, "replace_with_retry", refuse)
    code, output = run("install", "--yes")
    assert code == 1 and output.count("wake_model_install_failed") == 3
    assert not list((runtime / MODELS_DIR).glob("*.part"))


def test_an_unwritable_destination_is_an_install_failure_not_a_traceback(runtime, net, small_catalog):
    (runtime / "wake-word").write_text("un fichier à la place du dossier", encoding="utf-8")
    code, output = run("install", "--yes")
    assert code == 1 and "wake_model_install_failed" in output and "Traceback" not in output


def test_an_altered_file_is_reported_and_never_overwritten(runtime, net, small_catalog):
    folder = runtime / MODELS_DIR
    folder.mkdir(parents=True)
    altered = folder / "embedding_model.onnx"
    altered.write_bytes(b"altere")
    code, output = run("install", "--yes")
    assert code == 1
    assert "wake_model_mismatch" in output and altered.read_bytes() == b"altere"
    assert all("embedding" not in url for url in net.requested)
    assert "supprimez" in output.lower()


def test_install_writes_only_under_runtime_wake_word_models(runtime, net, small_catalog, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    before = tree(elsewhere)
    run("install", "--yes")
    assert tree(elsewhere) == before
    assert all(p.startswith("wake-word") for p in tree(runtime))
    assert not (runtime / "trace.jsonl").exists()


def test_install_downloads_nothing_at_import_or_when_building_the_parser():
    app._parser()
    # L'autouse `no_real_network` ferait lever ici ; le test passe donc si rien ne télécharge.
    assert wake_word_install.run_cli is not None


# ---------------------------------------------------------------- vie privée


def test_the_output_names_no_absolute_path_and_no_user(runtime, net, small_catalog):
    output = run("install", "--yes")[1] + run("status")[1] + run("install", answers=["n"])[1]
    assert str(runtime) not in output and getpass.getuser().lower() not in output.lower()
    assert str(Path.home()) not in output


# ------------------------------------------- rework QA : destination réelle et arrêt au premier échec réseau


def test_the_announced_destination_follows_the_default_runtime_folder(monkeypatch, small_catalog):
    monkeypatch.delenv("JARVIS_RUNTIME_DIR", raising=False)
    code, output = run("install", answers=["n"])
    assert code == 1 and "Destination : runtime/wake-word/models/" in output
    assert "$JARVIS_RUNTIME_DIR" not in output


def test_the_announced_destination_is_relative_to_the_repository_when_the_runtime_folder_is_inside_it(
    tmp_path, monkeypatch, small_catalog
):
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", "etat/rt")
    code, output = run("install", answers=["n"])
    assert code == 1 and "Destination : etat/rt/wake-word/models/" in output
    assert str(tmp_path) not in output
    code, output = run("status")
    assert "(etat/rt/wake-word/models)" in output
    assert json.loads(run("status", "--json")[1])["destination"] == "etat/rt/wake-word/models"


def test_an_absolute_runtime_folder_inside_the_repository_is_shown_relative(tmp_path, monkeypatch, small_catalog):
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "var" / "rt"))
    output = run("install", answers=["n"])[1]
    assert "Destination : var/rt/wake-word/models/" in output and str(tmp_path) not in output


def test_a_runtime_folder_outside_the_repository_is_named_by_its_variable_never_by_its_path(runtime, small_catalog):
    output = run("install", answers=["n"])[1]
    assert "Destination : $JARVIS_RUNTIME_DIR/wake-word/models/" in output
    assert str(runtime) not in output and "runtime/wake-word/models" not in output
    assert "$JARVIS_RUNTIME_DIR/wake-word/models" in run("status")[1]


def test_the_install_failure_message_names_the_real_destination(runtime, net, small_catalog):
    (runtime / "wake-word").write_text("un fichier à la place du dossier", encoding="utf-8")
    output = run("install", "--yes")[1]
    assert "wake_model_install_failed" in output and "$JARVIS_RUNTIME_DIR/wake-word/models" in output


def test_the_first_network_failure_stops_the_run_and_names_what_remains(runtime, net, small_catalog):
    net.serve["melspectrogram.onnx"] = OSError("réseau coupé")
    code, output = run("install", "--yes")
    assert code == 1
    assert len(net.requested) == 1, "un seul essai : pas trois attentes de 120 s"
    assert "wake_model_download_failed" in output
    assert "restent à installer" in output
    for remaining in ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"):
        assert remaining in output.split("restent à installer", 1)[1]
    assert "0 sur 3" in output and "Traceback" not in output


def test_after_a_network_failure_the_installed_files_are_not_listed_as_remaining(runtime, net, small_catalog):
    net.serve["hey_jarvis_v0.1.onnx"] = TimeoutError("trop lent")
    code, output = run("install", "--yes")
    assert code == 1 and len(net.requested) == 3
    remaining = output.split("restent à installer", 1)[1]
    assert "hey_jarvis_v0.1.onnx" in remaining
    assert "melspectrogram.onnx" not in remaining and "embedding_model.onnx" not in remaining
    assert "2 sur 3" in output


def test_a_rerun_after_the_network_returns_finishes_the_install(runtime, net, small_catalog):
    net.serve["embedding_model.onnx"] = OSError("réseau coupé")
    assert run("install", "--yes")[0] == 1
    del net.serve["embedding_model.onnx"]
    net.requested.clear()
    code, output = run("install", "--yes")
    assert code == 0 and len(net.requested) == 2 and "3 sur 3" in output


def test_a_corrupt_download_does_not_stop_the_other_files(runtime, net, small_catalog):
    net.serve["melspectrogram.onnx"] = b"z" * len(PAYLOADS["melspectrogram.onnx"])
    code, output = run("install", "--yes")
    assert code == 1 and "wake_model_mismatch" in output and len(net.requested) == 3
    assert "2 sur 3" in output and "restent à installer" not in output
