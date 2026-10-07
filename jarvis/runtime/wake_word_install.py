"""`python -m jarvis wake-word install|status` - installer et lire les modèles openWakeWord (Issue 002).

Une action explicite de l'utilisateur, jamais au démarrage de Voice. `install`
appelle `wakeword_model_catalog.ensure_models` (taille et SHA-256 épinglés
vérifiés avant installation, remplacement atomique) après avoir dit ce qu'il va
télécharger et demandé confirmation (sauf `--yes`). `status` ne touche ni le
réseau ni la bibliothèque : il lit les fichiers.

Ne s'écrit que sous `<runtime>/wake-word/models/` (c'est la seule destination de
`ensure_models`). Les erreurs sont dites par les codes stables du catalogue :
`wake_model_download_failed`, `wake_model_mismatch`, `wake_model_install_failed`,
et `wake_model_missing` / `wake_package_missing` pour `status`.

Codes de sortie : 0 tout est en place, 1 échec ou refus, 2 confirmation
impossible (pas de clavier et pas de `--yes`).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TextIO

from jarvis.adapters import wakeword_model_catalog as catalog

#: Dossier d'installation, tel qu'on le dit à l'utilisateur (jamais son chemin absolu).
DESTINATION = "runtime/wake-word/models"
_YES = {"o", "oui", "y", "yes"}


@dataclass(frozen=True, slots=True)
class ModelState:
    spec: catalog.WakeModelSpec
    state: str  # verified | missing | mismatch
    code: str | None


def package_installed() -> bool:
    """L'extra `wakeword` est-il importable ? Sans l'importer."""

    try:
        return importlib.util.find_spec("openwakeword") is not None
    except (ImportError, ValueError):
        return False


def read_states() -> list[ModelState]:
    directory = catalog.default_model_dir()
    states = []
    for spec in catalog.MODELS:
        try:
            catalog.verify_spec(spec, directory)
        except catalog.WakeModelError as exc:
            states.append(ModelState(spec, "missing" if exc.code == "wake_model_missing" else "mismatch", exc.code))
        except OSError:
            states.append(ModelState(spec, "mismatch", "wake_model_mismatch"))
        else:
            states.append(ModelState(spec, "verified", None))
    return states


def _octets(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _mo(value: int) -> str:
    return f"{value / 1_000_000:.1f}".replace(".", ",")


def _status(states: list[ModelState], out: TextIO, *, as_json: bool) -> int:
    package = package_installed()
    verified = sum(1 for s in states if s.state == "verified")
    ready = verified == len(states) and package
    if as_json:
        report = {
            "ready": ready,
            "package_installed": package,
            "models": [{"file": s.spec.filename, "state": s.state, "code": s.code, "size": s.spec.size,
                        "sha256": s.spec.sha256} for s in states],
            "destination": DESTINATION,
        }
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return 0 if ready else 1
    out.write(f"Modèles openWakeWord ({DESTINATION}) :\n")
    for s in states:
        verdict = {
            "verified": "vérifié (taille et SHA-256)",
            "missing": f"absent ({s.code})",
            "mismatch": f"altéré ou incomplet ({s.code}) : supprimez-le puis relancez l'installation",
        }[s.state]
        out.write(f"  {s.spec.filename}  {verdict}\n")
    out.write(f"Modèles vérifiés : {verified} sur {len(states)}.\n")
    out.write("Paquet Python openwakeword : " + ("installé.\n" if package else
              'absent (wake_package_missing) : python -m pip install -e ".[wakeword]"\n'))
    if ready:
        out.write("Prêt : modèles vérifiés et paquet présent. Activez le mot d'éveil dans les Réglages puis redémarrez Voice.\n")
    else:
        out.write("Pas prêt. Installer les modèles : python -m jarvis wake-word install\n")
    return 0 if ready else 1


def _plan(todo: list[ModelState], out: TextIO) -> None:
    total = sum(s.spec.size for s in todo)
    noun = "fichier" if len(todo) == 1 else "fichiers"
    out.write(f"Téléchargement de {len(todo)} {noun}, {_octets(total)} octets (environ {_mo(total)} Mo) "
              f"depuis la publication amont v0.5.1 :\n")
    for s in todo:
        out.write(f"  {s.spec.filename}  {_octets(s.spec.size)} octets  {s.spec.url}\n")
        if s.state == "mismatch":
            out.write("    (déjà présent mais altéré : il ne sera PAS écrasé, l'installation le refusera)\n")
    out.write(f"Destination : {DESTINATION}/ (ignoré par Git). Rien d'autre n'est écrit.\n")
    out.write("Chaque fichier n'est installé qu'après vérification de sa taille et de son SHA-256 épinglés.\n")
    out.write("Licence des modèles : CC BY-NC-SA 4.0, usage privé non commercial ; "
              "le code d'openWakeWord est Apache-2.0 (voir third_party/README.md).\n")
    out.write("Aucun audio ne part : seuls ces fichiers de modèle sont reçus.\n")


def _install(out: TextIO, err: TextIO, input_fn: Callable[[str], str], *, yes: bool) -> int:
    states = read_states()
    todo = [s for s in states if s.state != "verified"]
    if not todo:
        out.write(f"Les {len(states)} modèles sont déjà installés et vérifiés : rien à télécharger.\n")
        return 0
    _plan(todo, out)
    if not yes:
        try:
            answer = input_fn("Télécharger maintenant ? [o/N] ")
        except (EOFError, OSError):
            err.write("\nConfirmation impossible sans clavier : relancez avec --yes pour accepter ce téléchargement.\n")
            return 2
        if answer.strip().casefold() not in _YES:
            out.write("Annulé : rien n'a été téléchargé.\n")
            return 1
    directory = catalog.default_model_dir()
    failures = 0
    for s in todo:
        try:
            catalog.ensure_models(directory, specs=[s.spec])
        except catalog.WakeModelError as exc:
            failures += 1
            err.write(f"  {s.spec.filename}  ÉCHEC {exc.code} : {exc}\n")
        except Exception as exc:  # noqa: BLE001 - dossier non inscriptible, disque plein : dit, jamais une trace brute
            failures += 1
            err.write(f"  {s.spec.filename}  ÉCHEC wake_model_install_failed : {type(exc).__name__} "
                      f"(destination {DESTINATION} non inscriptible ?)\n")
        else:
            out.write(f"  {s.spec.filename}  installé et vérifié\n")
    verified = sum(1 for s in read_states() if s.state == "verified")
    out.write(f"Modèles vérifiés : {verified} sur {len(states)}.\n")
    if failures:
        out.write("Installation incomplète : corrigez la cause ci-dessus puis relancez la commande (idempotente).\n")
        return 1
    out.write("Installation terminée. Étape suivante : python -m jarvis wake-word status\n")
    return 0


def run_cli(
    args: Any,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    input_fn: Callable[[str], str] = input,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    if args.wake_action == "status":
        return _status(read_states(), out, as_json=bool(getattr(args, "json", False)))
    if args.wake_action == "install":
        return _install(out, err, input_fn, yes=bool(getattr(args, "yes", False)))
    raise AssertionError(args.wake_action)
