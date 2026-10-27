"""Cycle de vie produit de la voix : Off / Sleep / Active (`docs/voice-lifecycle.md`).

Une **projection**, pas une machine d'état de plus. Les états internes restent ceux qui existent :
le processus Voice (`VoiceLifecycleState` : `background`, `connecting`, `active`, `error`, publié chaque seconde
dans `.voice_runtime` avec le battement `.voice_heartbeat`) et le lanceur du produit (`launcher.json`). Ce module
y ajoute la seule chose qui manquait : **une préférence persistée** de l'utilisateur, le bloc
``voice_lifecycle`` à la racine de ``runtime/control-center-settings.json`` ::

    {"schema_version": 1, "preference": "sleep"}     # ou "off"

- ``sleep`` (défaut, bloc absent ou illisible) : le lanceur démarre Voice, qui attend en ``background`` avec le
  réveil armé (touche F9 toujours ; mot de réveil vocal si le bloc ``wake_word`` l'active et que le moteur est là) ;
- ``off`` : Voice n'est pas démarrée, ou est arrêtée ; aucun micro ni écouteur de réveil. Survit au redémarrage.

Qui lit quoi :

- le lanceur (`product_launcher.py`) : `launch_decision` avant de démarrer Voice, puis à chaque tour de veille
  (démarre ou arrête Voice à chaud) ;
- Voice (`jarvis/app.py`) : refuse de démarrer si ``off`` et s'arrête d'elle-même quand ``off`` apparaît
  (`run_until_released`, utile aussi sans lanceur) ;
- le Control Center : `project` pour `/api/status`, la route `/api/voice/lifecycle`, la préparation et la page
  « Mot d'éveil » (`wake_engine`).

Codes stables (`code`) : ``voice_off``, ``voice_provider_key_missing``, ``voice_configuration_invalid``,
``voice_crash_loop``, ``voice_not_launched``, ``voice_not_running``, ``voice_runtime_error``, ``voice_starting``,
``voice_stopping`` ; pour le moteur du mot de réveil : ``wake_package_missing``, ``wake_model_missing``,
``wake_model_mismatch``, ``wake_porcupine_key_missing``, ``wake_porcupine_package_missing``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
from typing import Any

SETTING_KEY = "voice_lifecycle"
SCHEMA_KEY = "schema_version"
SCHEMA_VERSION = 1
SETTINGS_FILE = "control-center-settings.json"

PREFERENCE_SLEEP = "sleep"
PREFERENCE_OFF = "off"
PREFERENCES = (PREFERENCE_SLEEP, PREFERENCE_OFF)
DEFAULT_PREFERENCE = PREFERENCE_SLEEP

STATE_OFF = "off"
STATE_SLEEP = "sleep"
STATE_ACTIVE = "active"
STATE_STARTING = "starting"
STATE_STOPPING = "stopping"
STATE_DEGRADED = "degraded"

VOICE_OFF = "voice_off"
VOICE_PROVIDER_KEY_MISSING = "voice_provider_key_missing"
VOICE_CONFIGURATION_INVALID = "voice_configuration_invalid"
VOICE_CRASH_LOOP = "voice_crash_loop"
VOICE_NOT_LAUNCHED = "voice_not_launched"
VOICE_NOT_RUNNING = "voice_not_running"
VOICE_RUNTIME_ERROR = "voice_runtime_error"
VOICE_STARTING = "voice_starting"
VOICE_STOPPING = "voice_stopping"

#: Ce que l'utilisateur lit pour chaque code (vouvoiement, sans jargon).
MESSAGES: Mapping[str, str] = {
    VOICE_OFF: "Voix coupée : aucun micro n'est ouvert. Le chat reste disponible.",
    VOICE_PROVIDER_KEY_MISSING: ("La voix ne peut pas démarrer : la clé du fournisseur vocal manque. Ajoutez-la dans "
                                 "Réglages › Connexions ; le chat fonctionne sans."),
    VOICE_CONFIGURATION_INVALID: ("La voix ne peut pas démarrer : sa configuration est illisible. Vérifiez Réglages › "
                                  "Avancé & diagnostic ; le chat fonctionne sans."),
    VOICE_CRASH_LOOP: ("La voix s'est arrêtée plusieurs fois de suite et n'est plus relancée. Coupez-la puis "
                       "rallumez-la pour réessayer ; le détail est dans le journal."),
    VOICE_NOT_LAUNCHED: "La voix n'est pas lancée sur ce poste (JARVIS_LAUNCH_VOICE=0).",
    VOICE_NOT_RUNNING: "La voix ne tourne pas : relancez JARVIS (ou Voice) pour l'utiliser.",
    VOICE_RUNTIME_ERROR: "La voix est en erreur. Elle revient en veille d'elle-même ; sinon, coupez-la puis rallumez-la.",
    VOICE_STARTING: "La voix démarre…",
    VOICE_STOPPING: "La voix s'arrête…",
}

WAKE_MESSAGES: Mapping[str, str] = {
    "wake_package_missing": ("Le moteur du mot de réveil (openWakeWord) n'est pas installé : seul F9 réveille "
                             "JARVIS."),
    "wake_model_missing": "Les modèles du mot de réveil ne sont pas installés : seul F9 réveille JARVIS.",
    "wake_model_mismatch": "Un modèle du mot de réveil est altéré : il est refusé, seul F9 réveille JARVIS.",
    "wake_porcupine_key_missing": "Porcupine n'a pas de clé Picovoice : seul F9 réveille JARVIS.",
    "wake_porcupine_package_missing": "Le paquet Porcupine n'est pas installé : seul F9 réveille JARVIS.",
}


class VoiceLifecycleError(ValueError):
    """Refus d'écriture de la préférence, avec un code stable (en-tête `X-Jarvis-Error-Code`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------- la préférence


def inspect_preference(settings: Mapping[str, Any]) -> tuple[str, str | None]:
    """(préférence qui s'applique, code du problème ou `None`). Ne lève jamais : au moindre doute, ``sleep``.

    Un bloc abîmé n'est pas une demande « off » : seule une valeur ``off`` lisible coupe la voix.
    """

    stored = settings.get(SETTING_KEY) if isinstance(settings, Mapping) else None
    if stored is None:
        return DEFAULT_PREFERENCE, None
    if not isinstance(stored, Mapping):
        return DEFAULT_PREFERENCE, "voice_lifecycle_block_malformed"
    version = stored.get(SCHEMA_KEY, SCHEMA_VERSION)
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        return DEFAULT_PREFERENCE, "voice_lifecycle_stored_version_unreadable"
    value = stored.get("preference", DEFAULT_PREFERENCE)
    if value not in PREFERENCES:
        return DEFAULT_PREFERENCE, "voice_lifecycle_preference_invalid"
    return value, None


def load_preference(settings: Mapping[str, Any]) -> str:
    return inspect_preference(settings)[0]


def apply_preference(settings: dict[str, Any], payload: Any) -> str:
    """Écriture stricte : ``{"preference": "off"|"sleep"}`` exactement ; ``settings`` n'est touché qu'en cas de succès."""

    if not isinstance(payload, Mapping) or set(payload) != {"preference"}:
        raise VoiceLifecycleError("voice_lifecycle_bad_payload", 'Attendu exactement {"preference": "off" | "sleep"}.')
    value = payload["preference"]
    if value not in PREFERENCES:
        raise VoiceLifecycleError("voice_lifecycle_preference_invalid",
                                  f"Préférence de voix inconnue : {str(value)[:20]!r} (off ou sleep).")
    stored = settings.get(SETTING_KEY)
    if isinstance(stored, Mapping):
        version = stored.get(SCHEMA_KEY, SCHEMA_VERSION)
        if isinstance(version, bool) or version != SCHEMA_VERSION:
            raise VoiceLifecycleError("voice_lifecycle_foreign_version",
                                      "La préférence enregistrée vient d'une autre version de JARVIS : rien n'est écrit.")
    settings[SETTING_KEY] = {SCHEMA_KEY: SCHEMA_VERSION, "preference": value}
    return value


def read_settings_file(runtime_root: Path) -> dict[str, Any]:
    """Le fichier de réglages, lecture tolérante (absent ou illisible : `{}`)."""

    try:
        value = json.loads((Path(runtime_root) / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def read_preference(runtime_root: Path) -> str:
    return load_preference(read_settings_file(runtime_root))


# ---------------------------------------------------------------------- la clé du fournisseur vocal


@dataclass(frozen=True, slots=True)
class ProviderKey:
    """La clé du fournisseur de la pile vocale choisie : présente, absente, ou configuration illisible."""

    present: bool
    provider: str | None = None
    label: str | None = None
    code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"present": self.present, "provider": self.provider, "label": self.label, "code": self.code}


def provider_key(settings: Mapping[str, Any]) -> ProviderKey:
    """Même chemin que Voice (`resolve_voice_composition` → pile → `credentials.secret_for`), sans rien ouvrir."""

    from jarvis.runtime import credentials as creds, voice_stack
    from jarvis.runtime.voice_composition import resolve_voice_composition

    try:
        stack = voice_stack.stack_spec(resolve_voice_composition(dict(settings)).stack_id)
        provider = creds.provider_spec(stack.credential_provider)
    except Exception as exc:  # noqa: BLE001 - capture: stable code; Voice would refuse the same configuration
        return ProviderKey(False, code=VOICE_CONFIGURATION_INVALID, label=type(exc).__name__)
    present = bool(creds.secret_for(dict(settings), stack.credential_provider))
    return ProviderKey(present, provider.id, provider.label, None if present else VOICE_PROVIDER_KEY_MISSING)


@dataclass(frozen=True, slots=True)
class LaunchDecision:
    """Ce que le lanceur fait de Voice : `start` vrai pour la démarrer, sinon `code` dit pourquoi elle est tenue."""

    start: bool
    code: str | None
    #: Vrai seulement pour ``off`` : une Voice qui tourne doit s'arrêter. Une clé retirée n'arrête rien.
    stop_running: bool = False


def launch_decision(settings: Mapping[str, Any], *, key: Callable[[Mapping[str, Any]], ProviderKey] = provider_key,
                    check_key: bool = True) -> LaunchDecision:
    if load_preference(settings) == PREFERENCE_OFF:
        return LaunchDecision(False, VOICE_OFF, stop_running=True)
    if not check_key:
        return LaunchDecision(True, None)
    checked = key(settings)
    if not checked.present:
        return LaunchDecision(False, checked.code or VOICE_PROVIDER_KEY_MISSING)
    return LaunchDecision(True, None)


# ---------------------------------------------------------------------- le moteur du mot de réveil


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def wake_engine(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que le réveil vocal peut faire sur ce poste, d'après le réglage ET les fichiers présents.

    Même politique que `simple_wake_word.simple_wake_backends` : openWakeWord si le bloc l'active ; sinon Porcupine si
    une clé existe ; sinon rien. `available` est vrai seulement si le moteur choisi a de quoi tourner (paquet,
    modèles vérifiés, clé). Ce n'est pas une mesure en direct : Voice peut encore échouer à l'ouverture du micro, ce que
    le journal dit (`wake.own_stream.failed`). La touche manuelle (F9) ne dépend de rien de cela.
    """

    from jarvis.runtime import credentials as creds, wake_word_settings

    block = wake_word_settings.load(settings)
    if block.enabled and block.provider == wake_word_settings.PROVIDER_OPENWAKEWORD:
        from jarvis.runtime import wake_word_install

        code = None
        if not wake_word_install.package_installed():
            code = "wake_package_missing"
        else:
            states = wake_word_install.read_states()
            if any(state.state == "mismatch" for state in states):
                code = "wake_model_mismatch"
            elif any(state.state != "verified" for state in states):
                code = "wake_model_missing"
        return {"configured": True, "provider": block.provider, "keyword": block.keyword, "available": code is None,
                "code": code, "message": WAKE_MESSAGES.get(code or "")}
    if creds.secret_for(dict(settings), "porcupine"):
        code = None if _module_present("pvporcupine") else "wake_porcupine_package_missing"
        return {"configured": True, "provider": wake_word_settings.PROVIDER_PORCUPINE, "keyword": "jarvis",
                "available": code is None, "code": code, "message": WAKE_MESSAGES.get(code or "")}
    if block.enabled:  # Porcupine demandé sans clé
        return {"configured": True, "provider": block.provider, "keyword": block.keyword, "available": False,
                "code": "wake_porcupine_key_missing", "message": WAKE_MESSAGES["wake_porcupine_key_missing"]}
    return {"configured": False, "provider": None, "keyword": None, "available": False, "code": None,
            "message": "Aucun mot de réveil vocal n'est activé : F9 réveille JARVIS."}


# ---------------------------------------------------------------------- la projection


def project(*, preference: str, voice_online: bool, runtime_state: str | None, launcher: Mapping[str, Any] | None,
            key: ProviderKey, wake: Mapping[str, Any], manual_key: str) -> dict[str, Any]:
    """L'état produit que l'interface affiche : jamais optimiste, toujours tiré des faits du serveur.

    `launcher` : ``{"managed": bool, "voice": {"held": code|None, "abandoned": bool, "running": bool} | None}``
    (`launcher.json` d'un lanceur vivant) ; `voice_online` et `runtime_state` : le battement de Voice.
    """

    managed = bool(launcher and launcher.get("managed"))
    role = (launcher or {}).get("voice") if managed else None
    code: str | None = None
    if preference == PREFERENCE_OFF:
        state, code = (STATE_STOPPING, VOICE_STOPPING) if voice_online else (STATE_OFF, VOICE_OFF)
    elif voice_online:
        if runtime_state in ("active", "connecting"):
            state = STATE_ACTIVE
        elif runtime_state == "error":
            state, code = STATE_DEGRADED, VOICE_RUNTIME_ERROR
        else:
            state = STATE_SLEEP
    elif managed and role is None:
        state, code = STATE_DEGRADED, VOICE_NOT_LAUNCHED
    elif isinstance(role, Mapping) and role.get("abandoned"):
        state, code = STATE_DEGRADED, VOICE_CRASH_LOOP
    elif isinstance(role, Mapping) and role.get("held") and role.get("held") != VOICE_OFF:
        state, code = STATE_DEGRADED, str(role.get("held"))
    elif not key.present:
        state, code = STATE_DEGRADED, key.code or VOICE_PROVIDER_KEY_MISSING
    elif managed:
        state, code = STATE_STARTING, VOICE_STARTING
    else:
        state, code = STATE_DEGRADED, VOICE_NOT_RUNNING
    wake_view = dict(wake)
    # Le réveil n'est « armé » que si Voice attend vraiment ; le mot vocal, en plus, seulement si son moteur est là.
    armed = state == STATE_SLEEP
    return {
        "schema_version": SCHEMA_VERSION,
        "preference": preference,
        "state": state,
        "code": code,
        "message": MESSAGES.get(code or "", ""),
        "managed": managed,
        "voice_online": voice_online,
        "runtime_state": runtime_state if voice_online else None,
        "provider_key": key.to_payload(),
        "wake": {"manual_key": manual_key.upper(), "manual_armed": armed,
                 "voice_word": {**wake_view, "armed": armed and bool(wake_view.get("available"))}},
    }


# ---------------------------------------------------------------------- Voice : rendre la main


STOP_REQUESTED = "stop_requested"
RELEASED_OFF = "voice_off"


async def wait_for_release(*, stop_file: Path | None, runtime_root: Path, poll_s: float = 0.5) -> str:
    """Rend la main quand le lanceur demande l'arrêt (fichier) ou quand l'utilisateur coupe la voix (préférence)."""

    while True:
        if stop_file is not None and stop_file.exists():
            return STOP_REQUESTED
        if read_preference(runtime_root) == PREFERENCE_OFF:
            return RELEASED_OFF
        await asyncio.sleep(poll_s)


async def run_until_released(main: Awaitable[Any], *, stop_file: Path | None, runtime_root: Path,
                             poll_s: float = 0.5) -> str | None:
    """Attend `main` ; s'arrête aussi à la demande d'arrêt ou à « voix coupée ». Rend la raison, ou `None` si `main`
    a fini seul. Une exception de `main` remonte ; la tâche restante est annulée et attendue (aucune orpheline)."""

    work = asyncio.ensure_future(main)
    watcher = asyncio.ensure_future(wait_for_release(stop_file=stop_file, runtime_root=runtime_root, poll_s=poll_s))
    try:
        done, _pending = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (work, watcher):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, watcher, return_exceptions=True)
    if work in done:
        work.result()
        return None
    return watcher.result()
