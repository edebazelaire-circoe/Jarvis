"""Registre des épinglages du Studio (handoff jarvis-interactive-presentation-studio, Slice 06).

Implémente le port `PrefabPinRegistry` (`jarvis/ports/prefabs.py`) que `PrefabService` interroge, **sous son verrou
d'écriture**, avant d'archiver une version de source de scène (`docs/prefabs.md` › *Retention of studio scene
sources*). Ce qu'il doit savoir, c'est **toute** version qu'un document, la scène vivante ou un cadre que l'hôte peut
recharger nomme encore. Quatre sources, unies par `CompositePinRegistry` (même mécanique que le port promet) :

| Source | Qui la tient | Quand elle bouge |
| --- | --- | --- |
| documents de variantes (Slices 02/04/05) : le pin de chaque scène **et** son `last_valid_pin` (Slice 06) | `PresentationStudioService`, **avant** d'écrire le fichier | à chaque écriture de variante |
| scène globale vivante : le bloc `prefab` de chaque objet actif (la fenêtre « stage », mais aussi toute fenêtre que l'hôte redessine ou recharge) | lue à la demande dans `SceneService.snapshot()` (mémoire) | à chaque commande de scène |
| retenues en vol (`hold`) : l'ancien et le nouveau pin d'un rechargement entre publication et confirmation | le service de rechargement | le temps d'une opération |
| sources ajoutées par les Slices suivantes (pile d'annulation 08, variantes 16/17, modèles 20) | `add_source(nom, fonction)` | à leur gré |

Règles tenues ici (conditions d'entrée de la Slice 06, `docs/prefabs.md`) :

- **Réponse en mémoire, sans verrou du Studio** : le registre tourne sous le verrou d'écriture des prefabs ; attendre
  le verrou du Studio (tenu par un écrivain qui attend les prefabs) serait un interblocage. L'index des variantes est
  un dictionnaire rempli au démarrage (`rebuild`) puis tenu à jour, jamais relu sur disque.
- **Fermé par défaut** : tant que l'index n'a pas été construit, ou qu'un document de variante était illisible à la
  construction (ses pins sont inconnus), `pinned_versions` lève et **rien n'est archivé** (`core.prefab.retention_failed`).
  Un document illisible n'est jamais traité comme « aucun épinglage ».
- **Enregistrer avant d'écrire** : le service de variantes appelle `register_variant` avec les pins du document à
  écrire avant de l'écrire ; en cas d'échec d'écriture il remet l'ensemble précédent (jamais moins protégé qu'avant).
- Chaque id demandé est une clé de la réponse (un id sans épinglage vaut un ensemble vide).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from jarvis.core.prefab_retention import CompositePinRegistry
from jarvis.ports.v2 import DiagnosticSink

Pin = tuple[str, int]
PinSource = Callable[[], Iterable[Pin]]


class _Fixed:
    """Une source de pins synchrone, mise au format du port."""

    def __init__(self, provider: Callable[[], Iterable[Pin]]) -> None:
        self._provider = provider

    async def pinned_versions(self, prefab_ids: Collection[str]) -> Mapping[str, frozenset[int]]:
        wanted = set(prefab_ids)
        found: dict[str, set[int]] = {prefab_id: set() for prefab_id in wanted}
        for prefab_id, version in self._provider():
            if prefab_id in wanted:
                found[prefab_id].add(version)
        return {prefab_id: frozenset(versions) for prefab_id, versions in found.items()}


class _LiveScene:
    """Les blocs `prefab` des objets actifs de la scène globale (lecture mémoire de `SceneService.snapshot`)."""

    def __init__(self, registry: StudioPinRegistry) -> None:
        self._registry = registry

    async def pinned_versions(self, prefab_ids: Collection[str]) -> Mapping[str, frozenset[int]]:
        scene = self._registry._scene
        found: dict[str, set[int]] = {prefab_id: set() for prefab_id in prefab_ids}
        if scene is None:
            raise RuntimeError("the live scene is not bound: its pins are unknown")
        snapshot = await scene.snapshot()  # raises when the scene is unavailable: nothing is archived
        for item in snapshot.objects:
            block = item.payload.prefab
            if block is not None and block.prefab_id in found:
                found[block.prefab_id].add(block.version)
        return {prefab_id: frozenset(versions) for prefab_id, versions in found.items()}


class StudioPinRegistry:
    """`PrefabPinRegistry` du Studio. Voir l'en-tête du module."""

    def __init__(self, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._diagnostics = diagnostics
        self._scene: Any = None
        self._variants: dict[tuple[str, str], frozenset[Pin]] = {}
        self._holds: dict[Pin, int] = {}
        self._extra: dict[str, PinSource] = {}
        self._ready = False
        self._degraded = ""
        self._composite = CompositePinRegistry(
            _Fixed(self._variant_pins), _Fixed(self._held_pins), _Fixed(self._extra_pins), _LiveScene(self))

    # ------------------------------------------------------------ liaison

    def bind_scene(self, scene: Any) -> None:
        """La scène globale (objet avec `async snapshot()`), liée après sa construction (`v2_app`)."""

        self._scene = scene

    def add_source(self, name: str, provider: PinSource) -> None:
        """Une source de pins d'une Slice suivante (pile d'annulation 08, variantes 16/17, modèles 20) : une fonction
        **synchrone et en mémoire** qui rend les `(id, version)` qu'elle tient encore."""

        if not name or name in self._extra:
            raise ValueError(f"pin source {name!r} is empty or already registered")
        self._extra[name] = provider

    # ------------------------------------------------------------ état d'index

    @property
    def ready(self) -> bool:
        return self._ready and not self._degraded

    def mark_ready(self) -> None:
        self._ready, self._degraded = True, ""

    async def rebuild(self, studio: Any) -> bool:
        """Construit l'index depuis les documents (`studio.pin_index()`, au demarrage de Core). Vrai si l'index est sain ;
        un document illisible le laisse **incomplet** (retention fermee, trace `error`), jamais « sans pin »."""

        try:
            index = await studio.pin_index()
        except Exception as exc:  # noqa: BLE001 - recorded: an unreadable store closes retention, it never opens it
            self.mark_degraded(f"{type(exc).__name__}: {exc}")
            return False
        self.clear_variants()
        for (presentation_id, variant_id), pins in index.items():
            self.register_variant(presentation_id, variant_id, pins)
        self.mark_ready()
        self._trace("core.presentation_studio.pins_ready", "Index des epinglages du Studio construit",
                    data={"variants": len(index), "pins": len({pin for pins in index.values() for pin in pins})})
        return True

    def mark_degraded(self, reason: str) -> None:
        """Un document était illisible à la construction : ses pins sont inconnus, donc rien ne s'archive tant que
        l'index n'est pas reconstruit sain."""

        self._degraded = reason[:300]
        self._trace("core.presentation_studio.pins_degraded", "Index des epinglages du Studio incomplet : rien ne sera archive",
                    level="error", data={"reason": self._degraded})

    def register_variant(self, presentation_id: str, variant_id: str, pins: Iterable[Pin]) -> frozenset[Pin]:
        """Remplace l'ensemble de la variante ; rend l'ensemble **précédent** (à remettre si l'écriture échoue)."""

        key = (presentation_id, variant_id)
        previous = self._variants.get(key, frozenset())
        self._variants[key] = frozenset(pins)
        return previous

    def restore_variant(self, presentation_id: str, variant_id: str, pins: frozenset[Pin]) -> None:
        if pins:
            self._variants[(presentation_id, variant_id)] = pins
        else:
            self._variants.pop((presentation_id, variant_id), None)

    def forget_presentation(self, presentation_id: str) -> None:
        for key in [key for key in self._variants if key[0] == presentation_id]:
            del self._variants[key]

    def clear_variants(self) -> None:
        self._variants.clear()

    # ------------------------------------------------------------ retenues en vol

    @contextmanager
    def hold(self, *pins: Pin) -> Iterator[None]:
        """Retient ces versions le temps d'un rechargement (entre la publication et la confirmation du montage)."""

        for pin in pins:
            self._holds[pin] = self._holds.get(pin, 0) + 1
        try:
            yield
        finally:
            for pin in pins:
                left = self._holds.get(pin, 1) - 1
                if left > 0:
                    self._holds[pin] = left
                else:
                    self._holds.pop(pin, None)

    # ------------------------------------------------------------ le port

    async def pinned_versions(self, prefab_ids: Collection[str]) -> Mapping[str, frozenset[int]]:
        if not self._ready:
            raise RuntimeError("the studio pin index is not built yet: its pins are unknown")
        if self._degraded:
            raise RuntimeError(f"the studio pin index is incomplete: {self._degraded}")
        answer = await self._composite.pinned_versions(prefab_ids)
        return {prefab_id: frozenset(answer.get(prefab_id, frozenset())) for prefab_id in prefab_ids}

    def stats(self) -> dict[str, int]:
        return {"variants": len(self._variants), "holds": len(self._holds), "sources": len(self._extra)}

    # ------------------------------------------------------------ sources

    def _variant_pins(self) -> Iterator[Pin]:
        for pins in tuple(self._variants.values()):
            yield from pins

    def _held_pins(self) -> Iterator[Pin]:
        yield from tuple(self._holds)

    def _extra_pins(self) -> Iterator[Pin]:
        for provider in tuple(self._extra.values()):
            yield from provider()

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a pin registration
            pass
