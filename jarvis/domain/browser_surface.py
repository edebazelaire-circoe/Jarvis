"""Surface de navigation du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S7, lot 07b).

Contrat : `docs/tool-brain-contracts.md` §15. **Aucun second système de fenêtres** : une surface *est* un objet de
scène `window` dont le prefab est `jarvis.browser@1` (`jarvis/prefabs/base/jarvis.browser/`). Son état de navigation
(historique, index, zoom, défilement) vit dans `payload.prefab.data`, donc dans la scène, qui reste le seul
propriétaire ; ce module est **pur** (aucune E/S) :

- identité : `surface_id_of(object_id)` -> `surf_<12 hexa>` (stable, opaque, dérivé de l'id de l'objet, jamais
  réutilisé puisque l'id d'un objet archivé ne l'est pas) ;
- lecture : `surfaces_of(snapshot)` (la liste que `UiState` et la perception exposent) ;
- sûreté d'URL : `check_surface_url` (http/https seulement, ni identifiants dans l'adresse, ni hôte local ou privé,
  même règle que `isAllowedUrl` du protocole de prefab côté page) ;
- plans : `plan_open`, `plan_history`, `plan_scroll`, `plan_zoom`, `plan_focus` -> une `SceneCommand` du cerveau
  (`PATCH_OBJECT` ou `UPSERT_OBJECT`), appliquée par `SceneService` (exécuteur du Tool Brain : `apply_if`) ou par
  le serveur MCP (`jarvis-display`) ; le réducteur et la validation du prefab par Core restent les juges.

Le cadre d'un prefab n'a pas de réseau (`default-src 'none'`) : la surface **présente** une adresse et sa trace de
navigation, l'utilisateur l'ouvre dans un onglet. Aucune page n'est chargée, donc rien à exfiltrer. La navigation
est de la présentation ; chercher ou lire le contenu d'une page reste le travail de Jarvis.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping
from urllib.parse import urlsplit

from jarvis.domain.scene import (
    MAX_LAYER, MAX_ORDER, MAX_TITLE_CHARS, Representation, SceneActor, SceneCommand, SceneObject, SceneObjectFields,
    SceneObjectKind, SceneOp, ScenePayload, ScenePrefabRef, SceneSnapshot, Visibility,
)

SURFACE_PREFAB_ID = "jarvis.browser"
SURFACE_PREFAB_VERSION = 1
SURFACE_CATEGORY = "browser"
SURFACE_ID_PREFIX = "surf_"
#: Les ids d'objets créés par le cerveau suivent `brain-<kind>-<hexa>` (`display_mcp.create_object`).
SURFACE_OBJECT_PREFIX = "brain-window-"

MAX_URL_CHARS = 2048
MAX_HISTORY = 32
MAX_LABEL_CHARS = 120
MAX_NOTE_CHARS = 4000
#: Zooms offerts (pourcentages) ; `zoom` de la donnée est borné 25..300 par le manifeste.
ZOOM_STEPS = (25, 50, 75, 100, 125, 150, 200, 300)
DEFAULT_ZOOM = 100
SCROLL_STEP = 25

SCROLL_DIRECTIONS = ("top", "bottom", "up", "down")
HISTORY_DIRECTIONS = ("back", "forward")
ZOOM_ACTIONS = ("in", "out", "reset")

# Codes de refus (communs au validateur, à l'exécuteur et au serveur MCP).
UNKNOWN_SURFACE = "unknown_surface"
UNSAFE_URL = "unsafe_url"
NO_HISTORY = "no_history"
INVALID_ARGUMENT = "invalid_argument"


class SurfaceError(ValueError):
    """Refus typé d'une opération de surface. `code` est celui que l'exécuteur et le validateur disent."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------ identité et lecture


def surface_id_of(object_id: str) -> str:
    """`surf_<12 hexa>` : opaque (ne laisse pas deviner l'id de scène), stable pour la vie de l'objet."""

    return SURFACE_ID_PREFIX + hashlib.sha256(object_id.encode("utf-8")).hexdigest()[:12]


def is_surface(item: SceneObject) -> bool:
    prefab = item.payload.prefab
    return item.kind is SceneObjectKind.WINDOW and prefab is not None and prefab.prefab_id == SURFACE_PREFAB_ID


@dataclass(frozen=True)
class SurfacePage:
    url: str
    label: str = ""


@dataclass(frozen=True)
class Surface:
    """Lecture d'une surface : ce que la scène en dit (jamais un état parallèle)."""

    surface_id: str
    object_id: str
    history: tuple[SurfacePage, ...]
    index: int
    zoom: int
    scroll: int
    visibility: Visibility
    representation: Representation

    @property
    def page(self) -> SurfacePage | None:
        return self.history[self.index] if self.history else None

    @property
    def visible(self) -> bool:
        return self.visibility is Visibility.VISIBLE

    def meta(self) -> dict[str, Any]:
        """Faits compacts d'une surface (sans contenu de page) : choix du manifeste et perception."""

        page = self.page
        return {"url": page.url if page else None, "host": host_of(page.url) if page else None,
                "position": self.index + 1 if page else 0, "pages": len(self.history), "zoom": self.zoom,
                "scroll": self.scroll, "visible": self.visible, "can_back": self.index > 0,
                "can_forward": self.index < len(self.history) - 1}


def _surface_of(item: SceneObject) -> Surface:
    prefab = item.payload.prefab
    assert prefab is not None
    data = prefab.data
    pages = tuple(SurfacePage(str(entry.get("url", "")), str(entry.get("label", "")))
                  for entry in data.get("history", ()) if isinstance(entry, Mapping))
    index = data.get("index", 0)
    index = index if isinstance(index, int) and 0 <= index < max(1, len(pages)) else 0
    return Surface(
        surface_id=surface_id_of(item.object_id), object_id=item.object_id, history=pages, index=index,
        zoom=data["zoom"] if isinstance(data.get("zoom"), int) else DEFAULT_ZOOM,
        scroll=data["scroll"] if isinstance(data.get("scroll"), int) else 0,
        visibility=item.visibility, representation=item.representation)


def surfaces_of(snapshot: SceneSnapshot | None) -> tuple[Surface, ...]:
    """Surfaces actives de la scène, par id (déterministe). Scène non servie : aucune."""

    if snapshot is None:
        return ()
    return tuple(sorted((_surface_of(item) for item in snapshot.objects if is_surface(item)),
                        key=lambda surface: surface.surface_id))


def find_surface(snapshot: SceneSnapshot, surface_id: object) -> Surface:
    for surface in surfaces_of(snapshot):
        if surface.surface_id == surface_id:
            return surface
    raise SurfaceError(UNKNOWN_SURFACE, f"{str(surface_id)[:80]} is not a current surface")


# ------------------------------------------------------------------ sûreté d'URL

_HOST_CHARS = re.compile(r"[a-z0-9.\-]+")
#: Formes numériques que le navigateur ramène à une IPv4 (`2130706433`, `0x7f.1`, `127.1`) : on ne les devine pas.
_AMBIGUOUS_NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|[0-9]+)(\.(0x[0-9a-f]+|[0-9]+))*")


def host_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _private_host(host: str) -> bool:
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return True
    if not _is_ip(host):
        return bool(_AMBIGUOUS_NUMERIC_HOST.fullmatch(host))
    address = ipaddress.ip_address(host)
    mapped = getattr(address, "ipv4_mapped", None)
    return not (mapped or address).is_global


def check_surface_url(url: object) -> str:
    """Adresse http(s) publique, sans identifiants ni caractère de contrôle ; rend l'adresse (schéma en minuscules).

    Refus (`unsafe_url`) : autre schéma (`javascript:`, `data:`, `file:`, `blob:`, `vbscript:`...), hôte absent,
    identifiants dans l'adresse (`user:pass@`), hôte local, privé, lien-local ou numérique ambigu, adresse trop
    longue. Même règle que `JarvisPrefabProtocol.isAllowedUrl` (le cadre refuserait de toute façon l'ouverture).
    """

    if not isinstance(url, str) or not url:
        raise SurfaceError(UNSAFE_URL, "url must be a non-empty string")
    if len(url) > MAX_URL_CHARS:
        raise SurfaceError(UNSAFE_URL, f"url exceeds {MAX_URL_CHARS} characters")
    if url != url.strip() or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        raise SurfaceError(UNSAFE_URL, "url must not contain spaces or control characters")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        parts.port  # noqa: B018 - lève ValueError pour un port hors bornes
    except ValueError:
        raise SurfaceError(UNSAFE_URL, "url is malformed") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise SurfaceError(UNSAFE_URL, "only http and https addresses are allowed")
    if not host or not parts.netloc:
        raise SurfaceError(UNSAFE_URL, "url has no host")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise SurfaceError(UNSAFE_URL, "url must not carry credentials")
    if not (_is_ip(host) or _HOST_CHARS.fullmatch(host)):
        raise SurfaceError(UNSAFE_URL, "url host is not a plain domain name or public address")
    if _private_host(host):
        raise SurfaceError(UNSAFE_URL, "local, private and link-local hosts are not allowed")
    return parts.scheme.lower() + url[len(parts.scheme):]


# ------------------------------------------------------------------ plans


def _text(value: object, limit: int, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SurfaceError(INVALID_ARGUMENT, f"{name} must be a string")
    cleaned = "".join(char for char in value if char in "\n\t" or ord(char) >= 32).strip()
    if name == "label":
        cleaned = " ".join(cleaned.split())
    return cleaned[:limit]


def _ref(item: SceneObject, **changes: Any) -> ScenePrefabRef:
    prefab = item.payload.prefab
    assert prefab is not None
    return ScenePrefabRef(prefab.prefab_id, prefab.version, dict(prefab.props), {**prefab.data, **changes})


def _history_data(surface: Surface) -> list[dict[str, str]]:
    return [{"url": page.url, **({"label": page.label} if page.label else {})} for page in surface.history]


def _patch(item: SceneObject, ref: ScenePrefabRef, **fields: Any) -> SceneCommand:
    payload = replace(item.payload, prefab=ref, **({"title": fields.pop("title")} if "title" in fields else {}))
    return SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN, object_id=item.object_id,
                        fields=SceneObjectFields(payload=payload, **fields))


def _object(snapshot: SceneSnapshot, surface: Surface) -> SceneObject:
    item = snapshot.get_object(surface.object_id)
    if item is None:  # pragma: no cover - `find_surface` vient de ce même instantané
        raise SurfaceError(UNKNOWN_SURFACE, surface.surface_id)
    return item


def new_surface_object_id(opaque: str) -> str:
    return SURFACE_OBJECT_PREFIX + opaque


def plan_open(snapshot: SceneSnapshot, url: object, *, surface_id: str | None = None, label: object = None,
              note: object = None, new_opaque: str | None = None) -> SceneCommand:
    """Ouvrir `url` : dans `surface_id` (la page est ajoutée à l'historique, l'avant est coupé) ou dans une
    **nouvelle** surface (`new_opaque` : suffixe d'id fourni par l'appelant, jamais deviné ici).

    La surface devient visible et dépliée. Même adresse que la page courante : l'historique ne bouge pas.
    """

    address = check_surface_url(url)
    name = _text(label, MAX_LABEL_CHARS, "label")
    notes = _text(note, MAX_NOTE_CHARS, "note")
    entry = {"url": address, **({"label": name} if name else {})}
    title = (name or host_of(address))[:MAX_TITLE_CHARS]
    if surface_id is None:
        if not new_opaque:
            raise SurfaceError(INVALID_ARGUMENT, "a new surface needs an identifier suffix")
        ref = ScenePrefabRef(SURFACE_PREFAB_ID, SURFACE_PREFAB_VERSION, {},
                             {"history": [entry], "index": 0, "zoom": DEFAULT_ZOOM, "scroll": 0, "body": notes})
        fields = SceneObjectFields(kind=SceneObjectKind.WINDOW, category=SURFACE_CATEGORY,
                                   payload=ScenePayload(title=title, prefab=ref), representation=Representation.WINDOW,
                                   visibility=Visibility.VISIBLE)
        return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN,
                            object_id=new_surface_object_id(new_opaque), fields=fields)
    surface = find_surface(snapshot, surface_id)
    item = _object(snapshot, surface)
    current = surface.page
    if current is not None and current.url == address:
        trail, index, scroll = _history_data(surface), surface.index, surface.scroll
        if name:
            trail[index] = entry
    else:
        kept = _history_data(surface)[: surface.index + 1] if surface.history else []
        trail = (kept + [entry])[-MAX_HISTORY:]
        index, scroll = len(trail) - 1, 0
    changes: dict[str, Any] = {"history": trail, "index": index, "scroll": scroll}
    if note is not None:
        changes["body"] = notes
    return _patch(item, _ref(item, **changes), title=title, representation=Representation.WINDOW,
                  visibility=Visibility.VISIBLE)


def plan_history(snapshot: SceneSnapshot, surface_id: str, direction: object) -> SceneCommand:
    """`back` ou `forward` d'une page ; au bord de l'historique : `no_history` (rien n'est inventé)."""

    if direction not in HISTORY_DIRECTIONS:
        raise SurfaceError(INVALID_ARGUMENT, f"direction must be one of {list(HISTORY_DIRECTIONS)}")
    surface = find_surface(snapshot, surface_id)
    target = surface.index - 1 if direction == "back" else surface.index + 1
    if not 0 <= target < len(surface.history):
        raise SurfaceError(NO_HISTORY, f"no page to go {direction} to ({surface.index + 1}/{len(surface.history)})")
    item = _object(snapshot, surface)
    page = surface.history[target]
    return _patch(item, _ref(item, index=target, scroll=0), title=(page.label or host_of(page.url))[:MAX_TITLE_CHARS])


def plan_scroll(snapshot: SceneSnapshot, surface_id: str, direction: object) -> SceneCommand:
    """`top`, `bottom`, `up` ou `down` (un quart de la hauteur défilable) ; au bord : inchangé (duplicate)."""

    if direction not in SCROLL_DIRECTIONS:
        raise SurfaceError(INVALID_ARGUMENT, f"direction must be one of {list(SCROLL_DIRECTIONS)}")
    surface = find_surface(snapshot, surface_id)
    target = {"top": 0, "bottom": 100, "up": surface.scroll - SCROLL_STEP,
              "down": surface.scroll + SCROLL_STEP}[direction]
    item = _object(snapshot, surface)
    return _patch(item, _ref(item, scroll=max(0, min(100, target))))


def plan_zoom(snapshot: SceneSnapshot, surface_id: str, action: object) -> SceneCommand:
    """`in` / `out` : cran suivant de `ZOOM_STEPS` ; `reset` : 100 %. Au bout de l'échelle : inchangé (duplicate)."""

    if action not in ZOOM_ACTIONS:
        raise SurfaceError(INVALID_ARGUMENT, f"action must be one of {list(ZOOM_ACTIONS)}")
    surface = find_surface(snapshot, surface_id)
    if action == "reset":
        target = DEFAULT_ZOOM
    elif action == "in":
        target = next((step for step in ZOOM_STEPS if step > surface.zoom), surface.zoom)
    else:
        target = next((step for step in reversed(ZOOM_STEPS) if step < surface.zoom), surface.zoom)
    item = _object(snapshot, surface)
    return _patch(item, _ref(item, zoom=target))


def plan_focus(snapshot: SceneSnapshot, surface_id: str) -> SceneCommand:
    """Mettre la surface au premier plan : visible, dépliée, au-dessus de tout autre objet (couche puis ordre).

    Il n'existe pas d'opération « focus » dans le réducteur (`docs/prefabs.md`) : *focus* est la composition
    d'écran existante (visibilité, représentation, couche, ordre), en une seule commande.
    """

    surface = find_surface(snapshot, surface_id)
    item = _object(snapshot, surface)
    others = [(other.layer, other.order) for other in snapshot.objects if other.object_id != item.object_id
              and other.visibility is Visibility.VISIBLE]
    layer, order = item.layer, item.order
    if others and (layer, order) <= max(others):
        top_layer, top_order = max(others)
        if top_layer < MAX_LAYER:
            layer = top_layer + 1
        else:
            layer, order = MAX_LAYER, min(MAX_ORDER, top_order + 1)
    return SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN, object_id=item.object_id,
                        fields=SceneObjectFields(representation=Representation.WINDOW, visibility=Visibility.VISIBLE,
                                                 layer=layer, order=order))


__all__ = [
    "HISTORY_DIRECTIONS", "INVALID_ARGUMENT", "MAX_HISTORY", "NO_HISTORY", "SCROLL_DIRECTIONS", "SURFACE_CATEGORY",
    "SURFACE_PREFAB_ID", "SURFACE_PREFAB_VERSION", "Surface", "SurfaceError", "SurfacePage", "UNKNOWN_SURFACE",
    "UNSAFE_URL", "ZOOM_ACTIONS", "ZOOM_STEPS", "check_surface_url", "find_surface", "host_of", "is_surface",
    "new_surface_object_id", "plan_focus", "plan_history", "plan_open", "plan_scroll", "plan_zoom", "surface_id_of",
    "surfaces_of",
]
