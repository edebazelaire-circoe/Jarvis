"""Modeles de presentation reutilisables : requetes de promotion et document stocke (handoff jarvis-interactive-presentation-studio, Slice 20).

Pur. Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract*.

**Il n'y a pas de second catalogue de prefabs.** Tout ce qui est du code reutilisable (la source d'une scene : manifeste, gabarit, style,
comportement) est publie dans la **bibliotheque partagee** par `PrefabService.save` (id `studio-template.<slug>[-n]`, origine `fork` de la
version de projet dont il derive). Le document ci-dessous (`ptp_<12 hex>`) est seulement la **composition** : quelles versions de la
bibliotheque, dans quel ordre, avec quelles valeurs neutres, quels controles et quelle direction artistique. Il ne contient aucune
definition de prefab (la cle inconnue est refusee), aucune valeur du projet et aucun identifiant de projet hors de `derived_from`.

Quatre genres : `presentation` (toute une variante), `scene`, `art_direction` (sections choisies d'un profil) et `motion` (la section
`motion` seule). La bibliotheque partagee ne sait porter que des prefabs : la direction artistique et le mouvement n'y ont pas de
representation, ils sont donc des genres du document de composition (jamais publies comme prefabs).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import re
import secrets
from typing import Any

from jarvis.domain.prefab import PrefabRef, canonical_json
from jarvis.domain.presentation_studio import PRESENTATION_ID, VARIANT_ID
from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode as C, _check_int, _check_title, _exact_keys, _fail, is_scene_id,
)
from jarvis.domain.presentation_studio_scene import SLUG, StudioScene
from jarvis.domain.presentation_studio_template_sanitize import DA_SECTIONS
from jarvis.domain.presentation_studio_variants import _check_stamp

SCHEMA_TEMPLATE = "jarvis.presentation_studio.template"
#: 1 : composition seule (scenes epinglees dans la bibliotheque). 2 (Slice 19) : le modele d'une presentation porte ses sources
#: **integrees** (`embedded`, par empreinte de contenu), une squelette de partition (`score`) et un bloc `catalog`. Un document s'ecrit
#: a la plus basse version qui l'exprime ; un lecteur qui ne connait que la version 1 refuse la 2 (`unsupported_schema_version`).
TEMPLATE_SCHEMA_VERSION = 2
#: Les cles qui n'existent qu'a partir de la version 2.
V2_KEYS = frozenset({"score", "embedded", "catalog"})
TEMPLATE_ID = re.compile(r"ptp_[0-9a-f]{12}\Z")
MAX_TEMPLATES = 512
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
#: Octets decodes (modules + assets) des sources integrees d'un modele ; au-dela, le constat `embedded_too_large` interdit la promotion.
MAX_EMBEDDED_BYTES = 1024 * 1024
MAX_LICENCE_ACKS = 8
MAX_DESCRIPTION = 600
MAX_TAGS = 8
MAX_LABEL = 40
NAMESPACE = "studio-template."
SLUG_TEMPLATE = re.compile(r"[a-z][a-z0-9-]{0,23}\Z")
TAG = re.compile(r"[a-z0-9][a-z0-9_-]{0,23}\Z")
MOTIF_MODES = ("strip", "keep")
CONTENT_HASH = re.compile(r"[0-9a-f]{64}\Z")


class TemplateKind(StrEnum):
    PRESENTATION = "presentation"
    SCENE = "scene"
    ART_DIRECTION = "art_direction"
    MOTION = "motion"


def new_template_id() -> str:
    return "ptp_" + secrets.token_hex(6)


def is_template_id(value: object) -> bool:
    return isinstance(value, str) and bool(TEMPLATE_ID.fullmatch(value))


def template_scene_id(template_id: str, index: int) -> str:
    """Un `pss_` stable de l'enregistrement (jamais l'id d'une scene du projet) : l'instanciation en donne des neufs."""

    return "pss_" + hashlib.sha256(f"{template_id}:{index}".encode()).hexdigest()[:12]


def prefab_id_for(slug: str, number: int | None) -> str:
    return f"{NAMESPACE}{slug}" if number is None else f"{NAMESPACE}{slug}-{number}"


# ------------------------------------------------------------------ requetes


def _line(name: str, value: object, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty) or value != value.strip() or not value.isprintable() or len(value) > limit:
        raise _fail(f"{name} must be one printable line of at most {limit} characters, without surrounding spaces")
    return value


def _id_list(name: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 32 or not all(isinstance(v, str) and SLUG.fullmatch(v) for v in value):
        raise _fail(f"{name} must be a list of at most 32 control ids")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class SceneSelection:
    """Le choix explicite pour une scene : `dimensions` (reglage d'aspect garde) et `parameters` (controle garde, valeur neutralisee).
    Les deux listes sont obligatoires (vides : une scene a l'aspect fixe, sans reglage expose)."""

    scene_id: str
    label: str
    dimensions: tuple[str, ...]
    parameters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DaSelection:
    sections: tuple[str, ...]
    keep_motifs: bool = False


@dataclass(frozen=True, slots=True)
class PromoteRequest:
    kind: TemplateKind
    actor: str
    title: str
    slug: str
    description: str
    tags: tuple[str, ...]
    #: `None` : mode decouverte du plan (aucune selection donnee) ; jamais accepte par `promote`.
    scenes: tuple[SceneSelection, ...] | None
    art_direction: DaSelection | None
    expected_revision: int | None
    #: Slice 19 : les licences (telles que le plan les montre) que l'utilisateur reconnait explicitement pour des sources amont a licence
    #: non redistribuable ou non declaree. Jamais un booleen aveugle : une chaine qui ne correspond a aucune licence du plan n'ouvre rien.
    licence_ack: tuple[str, ...] = ()
    #: Slice 19 : garder les assets (`public/**`) d'une source Remotion qui n'est pas un import intact (medias possibles du projet).
    keep_assets: bool = False


def parse_promote(raw: object, *, strict: bool) -> PromoteRequest:
    """Corps d'un plan (`strict=False` : la selection peut manquer, le plan decrit alors les candidats) ou d'une promotion (`strict`)."""

    data = _exact_keys(raw, "template promotion", {"kind", "title", "slug"},
                       frozenset({"actor", "description", "tags", "scenes", "art_direction", "expected_revision", "licence_ack",
                                  "keep_assets"}))
    try:
        kind = TemplateKind(data["kind"])
    except ValueError:
        raise _fail("kind must be presentation, scene, art_direction or motion") from None
    actor = data.get("actor", "user")
    if actor not in ("user", "brain"):
        raise _fail("actor must be 'user' or 'brain'")
    _check_title("title", data["title"])
    slug = data["slug"]
    if not isinstance(slug, str) or not SLUG_TEMPLATE.fullmatch(slug):
        raise _fail("slug must match [a-z][a-z0-9-]{0,23}")
    description = _line("description", data.get("description", ""), MAX_DESCRIPTION, empty=True)
    tags = data.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(isinstance(t, str) and TAG.fullmatch(t) for t in tags) \
            or len(set(tags)) != len(tags):
        raise _fail(f"tags must be at most {MAX_TAGS} distinct lowercase tokens")
    expected = data.get("expected_revision")
    if expected is not None:
        _check_int("expected_revision", expected, 1, 2**31 - 1)
    acks = data.get("licence_ack", [])
    if not isinstance(acks, list) or len(acks) > MAX_LICENCE_ACKS or len(set(acks)) != len(acks) \
            or not all(isinstance(a, str) and a and len(a) <= 64 and a == a.strip() and a.isprintable() for a in acks):
        raise _fail(f"licence_ack must be at most {MAX_LICENCE_ACKS} distinct licence names, as the plan shows them")
    keep_assets = data.get("keep_assets", False)
    if type(keep_assets) is not bool:
        raise _fail("keep_assets must be true or false")

    scenes: tuple[SceneSelection, ...] | None = None
    if "scenes" in data:
        rows = data["scenes"]
        if not isinstance(rows, list) or len(rows) > 64:
            raise _fail("scenes must be a list of at most 64 selections")
        picked = []
        for n, row in enumerate(rows):
            item = _exact_keys(row, f"scenes[{n}]", {"scene_id", "dimensions", "parameters"}, frozenset({"label"}))
            if not is_scene_id(item["scene_id"]):
                raise _fail(f"scenes[{n}].scene_id is not a scene id")
            picked.append(SceneSelection(item["scene_id"], _line(f"scenes[{n}].label", item.get("label", ""), MAX_LABEL, empty=True),
                                         _id_list(f"scenes[{n}].dimensions", item["dimensions"]),
                                         _id_list(f"scenes[{n}].parameters", item["parameters"])))
        if len({s.scene_id for s in picked}) != len(picked):
            raise _fail("scenes lists a scene twice")
        scenes = tuple(picked)
    da: DaSelection | None = None
    if data.get("art_direction") is not None:
        body = _exact_keys(data["art_direction"], "art_direction", {"sections"}, frozenset({"motifs"}))
        sections = body["sections"]
        if not isinstance(sections, list) or not sections or not all(s in DA_SECTIONS for s in sections) or len(set(sections)) != len(sections):
            raise _fail(f"art_direction.sections must be a non-empty list of distinct sections among {', '.join(DA_SECTIONS)}")
        motifs = body.get("motifs", "strip")
        if motifs not in MOTIF_MODES:
            raise _fail("art_direction.motifs must be 'strip' or 'keep'")
        da = DaSelection(tuple(sections), motifs == "keep")
    _check_shape(kind, scenes, da, strict=strict)
    return PromoteRequest(kind, actor, data["title"], slug, description, tuple(tags), scenes, da, expected, tuple(acks), keep_assets)


def _check_shape(kind: TemplateKind, scenes: tuple[SceneSelection, ...] | None, da: DaSelection | None, *, strict: bool) -> None:
    if kind is TemplateKind.SCENE and scenes is not None and len(scenes) != 1:
        raise _fail("a scene template names exactly one scene")
    if kind in (TemplateKind.ART_DIRECTION, TemplateKind.MOTION):
        if scenes:
            raise _fail(f"a {kind.value} template takes no scenes")
        if kind is TemplateKind.MOTION and da is not None:
            raise _fail("a motion template takes no art_direction selection (the motion section is implied)")
        if kind is TemplateKind.ART_DIRECTION and da is None and strict:
            raise PresentationStudioError(C.TEMPLATE_SELECTION_REQUIRED, "an art_direction template needs art_direction.sections")
    elif strict and scenes is None:
        raise PresentationStudioError(C.TEMPLATE_SELECTION_REQUIRED,
                                      "name the scenes with their dimensions and parameters (empty lists are an explicit choice); "
                                      "run the plan first to list the candidates")


@dataclass(frozen=True, slots=True)
class InstantiateRequest:
    actor: str
    title: str | None
    presentation_id: str | None
    variant_id: str | None
    expected_revision: int | None


def parse_instantiate(raw: object) -> InstantiateRequest:
    data = _exact_keys({} if raw is None else raw, "template instantiation", set(),
                       frozenset({"actor", "title", "presentation_id", "variant_id", "expected_revision"}))
    actor = data.get("actor", "user")
    if actor not in ("user", "brain"):
        raise _fail("actor must be 'user' or 'brain'")
    title = data.get("title")
    if title is not None:
        _check_title("title", title)
    for name, pattern in (("presentation_id", PRESENTATION_ID), ("variant_id", VARIANT_ID)):
        if data.get(name) is not None and not (isinstance(data[name], str) and pattern.fullmatch(data[name])):
            raise _fail(f"{name} is not a valid id")
    expected = data.get("expected_revision")
    if expected is not None:
        _check_int("expected_revision", expected, 1, 2**31 - 1)
    return InstantiateRequest(actor, title, data.get("presentation_id"), data.get("variant_id"), expected)


# ------------------------------------------------------------------ document


@dataclass(frozen=True, slots=True)
class TemplateScene:
    key: str
    label: str
    scene: StudioScene
    #: Slice 19 : empreinte (sha256 hex) de la source integree que cette scene emploie (`StudioTemplate.embedded`), ou `None` quand
    #: `scene.prefab` est une version de la bibliotheque partagee. Avec une source integree, `scene.prefab` n'est qu'un emplacement
    #: du modele (jamais resolu) ; l'instanciation publie une source propre a la presentation neuve.
    source: str | None = None


@dataclass(frozen=True, slots=True)
class StudioTemplate:
    template_id: str
    kind: TemplateKind
    title: str
    description: str
    tags: tuple[str, ...]
    scenes: tuple[TemplateScene, ...]
    #: `{sections: {name: dict}}` ou `None`.
    art_direction: Mapping[str, Any] | None
    #: Les controles gardes : `{scene_key, control_id, kind: dimension|parameter, role, type, group, label}`.
    parameters: tuple[Mapping[str, Any], ...]
    #: Les versions de la bibliotheque partagee que cette composition emploie (toutes hors du nom de projet `presentation-studio.`).
    prefabs: tuple[PrefabRef, ...]
    #: Compte de ce qui a ete retire (valeurs, defauts, references...), sans contenu.
    report: Mapping[str, Any]
    #: La seule trace du projet d'origine (ids, revision, versions de prefab). Jamais lue a l'instanciation.
    derived_from: Mapping[str, Any]
    created_by: str
    created_at: str
    revision: int = 1
    #: Slice 19 (document v2) : le squelette de partition (`{start_item_id, items, cues: [], sequences: [], recovery_points: []}` sur les
    #: emplacements `template_scene_id`), sans parole, sans repere, sans sequence ni valeur de controle ; `None` sans partition.
    score: Mapping[str, Any] | None = None
    #: Slice 19 (v2) : `{sha256: candidat}` : les sources de scene **privees a ce modele**, absentes de la bibliotheque partagee. Un
    #: candidat est `{manifest, template, style, behavior}` (HTML) ou `{manifest, sources, assets}` (Remotion).
    embedded: Mapping[str, Any] | None = None
    #: Slice 19 (v2) : le bloc de catalogue de l'enregistrement lui-meme : `type: presentation`, compatibilite par moteur, licences
    #: reconnues, amont. Meme vocabulaire que `catalog` d'un manifeste v3, jamais le catalogue d'un autre prefab.
    catalog: Mapping[str, Any] | None = None

    @property
    def schema_version(self) -> int:
        return 2 if (self.score is not None or self.embedded is not None or self.catalog is not None) else 1

    def to_document(self) -> dict[str, Any]:
        rows = []
        for s in self.scenes:
            row = {"key": s.key, "label": s.label, "scene": s.scene.to_dict()}
            if s.source is not None:
                row["source"] = s.source
            rows.append(row)
        body = {"schema": SCHEMA_TEMPLATE, "schema_version": self.schema_version, "template_id": self.template_id,
                "kind": self.kind.value, "title": self.title, "description": self.description, "tags": list(self.tags),
                "scenes": rows,
                "art_direction": None if self.art_direction is None else dict(self.art_direction),
                "parameters": [dict(p) for p in self.parameters], "prefabs": [p.to_dict() for p in self.prefabs],
                "report": dict(self.report), "derived_from": dict(self.derived_from), "created_by": self.created_by,
                "created_at": self.created_at, "revision": self.revision}
        if self.schema_version == 2:
            body.update({"score": None if self.score is None else dict(self.score),
                         "embedded": None if self.embedded is None else dict(self.embedded),
                         "catalog": None if self.catalog is None else dict(self.catalog)})
        return body

    def summary(self) -> dict[str, Any]:
        return {"template_id": self.template_id, "kind": self.kind.value, "title": self.title, "description": self.description,
                "tags": list(self.tags), "scene_count": len(self.scenes), "parameter_count": len(self.parameters),
                "has_art_direction": self.art_direction is not None, "prefabs": [p.to_dict() for p in self.prefabs],
                "has_score": self.score is not None, "embedded_sources": len(self.embedded or ()),
                "engine": None if self.catalog is None else dict(self.catalog.get("compatibility", {})),
                "created_at": self.created_at, "created_by": self.created_by}

    def canonical(self) -> str:
        return canonical_json(self.to_document())


_KEYS = {"schema", "schema_version", "template_id", "kind", "title", "description", "tags", "scenes", "art_direction",
         "parameters", "prefabs", "report", "derived_from", "created_by", "created_at", "revision"}


def parse_template(raw: object) -> StudioTemplate:
    """Document disque -> `StudioTemplate`. Une cle inconnue est refusee : aucun champ ne peut porter une definition de prefab."""

    if isinstance(raw, dict) and raw.get("schema") == SCHEMA_TEMPLATE and isinstance(raw.get("schema_version"), int) \
            and raw["schema_version"] > TEMPLATE_SCHEMA_VERSION:
        raise PresentationStudioError(C.UNSUPPORTED_SCHEMA_VERSION, "this template was written by a newer JARVIS")
    version = raw.get("schema_version") if isinstance(raw, dict) else None
    if type(version) is not int or version not in (1, TEMPLATE_SCHEMA_VERSION):
        raise _fail("template: unknown schema")
    data = _exact_keys(raw, "template", set(_KEYS), frozenset(V2_KEYS) if version == 2 else frozenset())
    if data["schema"] != SCHEMA_TEMPLATE:
        raise _fail("template: unknown schema")
    if not is_template_id(data["template_id"]):
        raise _fail("template_id is not a valid id")
    try:
        kind = TemplateKind(data["kind"])
    except ValueError:
        raise _fail("template kind is unknown") from None
    _check_title("title", data["title"])
    _line("description", data["description"], MAX_DESCRIPTION, empty=True)
    if not isinstance(data["tags"], list) or not all(isinstance(t, str) and TAG.fullmatch(t) for t in data["tags"]):
        raise _fail("template tags are malformed")
    rows = data["scenes"]
    if not isinstance(rows, list) or len(rows) > 64:
        raise _fail("template scenes must be a list of at most 64")
    scenes = []
    for n, row in enumerate(rows):
        item = _exact_keys(row, f"scenes[{n}]", {"key", "label", "scene"}, frozenset({"source"}) if version == 2 else frozenset())
        if not isinstance(item["key"], str) or not SLUG.fullmatch(item["key"]):
            raise _fail(f"scenes[{n}].key is malformed")
        source = item.get("source")
        if source is not None and not (isinstance(source, str) and CONTENT_HASH.fullmatch(source)):
            raise _fail(f"scenes[{n}].source is not a content hash")
        scenes.append(TemplateScene(item["key"], _line("label", item["label"], MAX_LABEL, empty=True),
                                    StudioScene.from_dict(item["scene"], f"template scene {item['key']}"), source))
    prefabs = []
    for entry in data["prefabs"] if isinstance(data["prefabs"], list) else ():
        prefabs.append(PrefabRef.from_dict(entry, "prefabs[]"))
    art = data["art_direction"]
    if art is not None:
        art = _exact_keys(art, "art_direction", {"sections"})
        if not isinstance(art["sections"], dict) or not art["sections"] or not set(art["sections"]) <= set(DA_SECTIONS):
            raise _fail("art_direction.sections is malformed")
    for name in ("parameters", "report", "derived_from"):
        if not isinstance(data[name], (list, dict)):
            raise _fail(f"{name} is malformed")
    if data["created_by"] not in ("user", "brain"):
        raise _fail("created_by is malformed")
    _check_stamp("created_at", data["created_at"])
    _check_int("revision", data["revision"], 1, 2**31 - 1)
    score, embedded, catalog = (_optional_object(data, name) for name in ("score", "embedded", "catalog"))
    if embedded is not None and (not all(isinstance(k, str) and CONTENT_HASH.fullmatch(k) and isinstance(v, dict)
                                        for k, v in embedded.items())
                                 or any(sc.source is not None and sc.source not in embedded for sc in scenes)):
        raise _fail("embedded sources are malformed or a scene names a source the record does not hold")
    if embedded is None and any(sc.source is not None for sc in scenes):
        raise _fail("a scene names an embedded source and the record holds none")
    return StudioTemplate(data["template_id"], kind, data["title"], data["description"], tuple(data["tags"]), tuple(scenes), art,
                          tuple(dict(p) for p in data["parameters"]), tuple(prefabs), data["report"], data["derived_from"],
                          data["created_by"], data["created_at"], data["revision"], score, embedded, catalog)


def _optional_object(data: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    value = data.get(name)
    if value is not None and not isinstance(value, dict):
        raise _fail(f"{name} is malformed")
    return value


def template_scene_dicts(template: StudioTemplate, new_id: Any) -> list[dict[str, Any]]:
    """Les scenes d'un modele prêtes pour une variante neuve : identifiants neufs, rien d'execution, aucun etat de revision."""

    out = []
    for item in template.scenes:
        wire = item.scene.to_dict()
        wire["scene_id"] = new_id()
        wire.pop("source_revision", None)
        wire.pop("last_valid_pin", None)
        wire.pop("scene_variants", None)
        out.append(wire)
    return out

