"""Assainissement et parametrage d'un travail de presentation avant promotion (handoff jarvis-interactive-presentation-studio, Slice 20).

Pur : aucun disque, aucun service. Le contrat est `docs/presentation-studio.md` > *Template and prefab promotion contract*.

Une promotion ne **copie jamais** un artefact de projet. Ce module fabrique, a partir d'une scene (pin + valeurs + controles) et de la
source de son prefab, un **candidat de prefab reutilisable** et un enregistrement de scene sans contenu de projet :

1. **Selection explicite** : chaque controle de la scene est soit une *dimension* (son reglage d'aspect est garde : couleur, nombre,
   booleen, enumeration), soit un *parametre* (le controle est garde, la valeur est neutralisee), soit abandonne. Rien n'est garde
   par defaut.
2. **Parametrage** : chaque feuille du schema d'entrees du prefab est classee `look` ou `content` (`leaf_role`). Une feuille de
   contenu perd sa valeur, son defaut et son exemple au profit d'un espace reserve (`placeholder`) ; une feuille d'aspect non
   choisie retrouve le defaut de la source.
3. **Detection** (`scan_*`) : identifiants de projet, chemins locaux, localisateurs de ressources du projet et chaines de contenu
   du projet encore presents dans la source ou le manifeste. Un resultat `blocking` interdit la promotion ; les messages portent
   des comptes et des chemins de schema, **jamais la valeur trouvee**.

La detection est une heuristique de depot (comparaison de chaines normalisees), pas une preuve : elle ne voit pas un contenu
reformule, decoupe ou code. La documentation le dit.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import copy
import re
from typing import Any

from jarvis.domain.prefab import (
    MAX_DESCRIPTION_CHARS, MAX_TITLE_CHARS, PrefabDefinitionError, parse_input_schema, validate_value,
)
from jarvis.domain.presentation_studio_scene import ControlGroup, StudioControl

#: Types dont la valeur est un reglage d'aspect (jamais une phrase de l'auteur).
LOOK_TYPES = frozenset({"number", "integer", "boolean", "color", "enum"})
#: Une chaine plus courte n'est pas cherchee dans la source (un mot de quatre lettres y est presque toujours un mot-cle).
MIN_TERM_CHARS = 4
MIN_WORD_TERM_CHARS = 6
MAX_TERMS = 400
#: Un `data:` plus grand que cela, dans la source, est un contenu embarque (avertissement, pas un refus).
DATA_URI_WARN_CHARS = 2048
MAX_FINDINGS = 40
#: Id provisoire d'un candidat avant deduplication : le service pose l'id definitif (`decorate_manifest`).
PENDING_ID = "studio-template.pending"

_PROJECT_ID = re.compile(
    r"\b(?:pst|psv|pss|psx|psc|psi|psa)_[0-9a-f]{6,}\b|\bpresentation-studio\.[a-z0-9][a-z0-9._-]*|"
    r"\buser-prefab-[0-9a-f]+|\bstudio-stage-[\w-]+", re.IGNORECASE)
_LOCAL_PATH = re.compile(
    r"\b[a-z]:[\\/]|(?:^|[\s\"'(=])/(?:users|home|var|etc|tmp|mnt|root)/|\.jarvis\b|file:/{2,3}|~[\\/]|\\\\[\w.-]+\\",
    re.IGNORECASE)
_EXTERNAL_URL = re.compile(r"(?:https?:)?//(?!www\.w3\.org/)[a-z0-9][\w.-]*\.[a-z]{2,}", re.IGNORECASE)
_DATA_URI = re.compile(r"data:[\w/+.-]+(?:;[\w=.-]+)*,[^\"')\s]{%d,}" % DATA_URI_WARN_CHARS)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Finding:
    """Un constat de promotion. `where` : `source.template`, `manifest`, `scene:<key>.controls`... ; `message` sans valeur."""

    code: str
    where: str
    message: str
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "where": self.where, "message": self.message, "blocking": self.blocking}


def normalise(text: str) -> str:
    return _SPACES.sub(" ", text.casefold()).strip()


def is_term(text: str) -> bool:
    """Une chaine de contenu assez specifique pour etre cherchee : 6 caracteres, ou 4 avec un espace ou un chiffre."""

    folded = normalise(text)
    if len(folded) < MIN_TERM_CHARS or not any(ch.isalnum() for ch in folded):
        return False
    return len(folded) >= MIN_WORD_TERM_CHARS or " " in folded or any(ch.isdigit() for ch in folded)


# ------------------------------------------------------------------ schema : feuilles, roles, espaces reserves


@dataclass(frozen=True, slots=True)
class Leaf:
    path: str  # `props.accent`, `data.items`...
    node: dict[str, Any]  # le noeud du manifeste COPIE (modifiable par l'appelant)

    @property
    def type(self) -> str:
        return str(self.node.get("type", ""))

    @property
    def root(self) -> str:
        return self.path.split(".", 1)[0]


def leaves(schema: dict[str, Any], root: str) -> Iterator[Leaf]:
    """Les feuilles d'un schema d'entree : tout noeud qui n'est pas un objet a proprietes (un tableau est une feuille)."""

    props = schema.get("properties") if schema.get("type") == "object" else None
    if not isinstance(props, dict):
        return
    for name, child in props.items():
        if not isinstance(child, dict):
            continue
        if child.get("type") == "object" and isinstance(child.get("properties"), dict):
            yield from leaves(child, f"{root}.{name}")
        else:
            yield Leaf(f"{root}.{name}", child)


def leaf_role(leaf: Leaf, control: StudioControl | None) -> str:
    """`look` (aspect, reutilisable tel quel) ou `content` (contenu du projet, neutralise). Un controle de groupe `content` ou un
    type de texte, d'URL, de tableau ou de donnees fait un contenu ; un controle visuel/mise en page/mouvement ou une propriete
    `props` de type scalaire non textuel fait un aspect."""

    if leaf.type not in LOOK_TYPES:
        return "content"
    if control is not None:
        return "content" if control.group is ControlGroup.CONTENT else "look"
    return "look" if leaf.root == "props" else "content"


def placeholder(node: Mapping[str, Any], name: str) -> Any:
    """Une valeur neutre valide pour ce noeud (jamais le contenu du projet) : `[nom]` pour un texte, le minimum pour un nombre."""

    kind = node.get("type")
    if kind in ("string", "text"):
        limit = int(node.get("max_length", 200 if kind == "string" else 2000))
        return f"[{name}]"[: max(limit, 1)]
    if kind in ("number", "integer"):
        low, high = node.get("min"), node.get("max")
        value = 0 if low is None else low
        if high is not None and value > high:
            value = high
        return int(value) if kind == "integer" else float(value)
    if kind == "boolean":
        return False
    if kind == "color":
        return "#808080"
    if kind == "enum":
        return node["values"][0]
    if kind == "url":
        return "https://example.com/"
    if kind == "array":
        count = int(node.get("min_items", 0))
        item = node.get("items")
        return [placeholder(item, name) for _ in range(count)] if isinstance(item, dict) and count else []
    if kind == "object":
        props = node.get("properties") or {}
        keys = node.get("required") or []
        return {key: placeholder(props[key], key) for key in keys if key in props}
    return None


def _get(tree: Mapping[str, Any], dotted: str) -> tuple[bool, Any]:
    current: Any = tree
    for key in dotted.split(".")[1:]:
        if not isinstance(current, Mapping) or key not in current:
            return False, None
        current = current[key]
    return True, current


def _put(tree: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")[1:]
    current = tree
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    current[keys[-1]] = value


# ------------------------------------------------------------------ detection


def _strings(value: Any, depth: int = 0) -> Iterator[str]:
    if depth > 12:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item, depth + 1)


def content_terms(values: Sequence[Any]) -> frozenset[str]:
    """Les chaines de contenu a ne pas retrouver dans une source : normalisees, bornees (`MAX_TERMS`)."""

    found: dict[str, None] = {}
    for value in values:
        for text in _strings(value):
            if is_term(text):
                found[normalise(text)] = None
                if len(found) >= MAX_TERMS:
                    return frozenset(found)
    return frozenset(found)


def scan_text(where: str, text: str, terms: frozenset[str], *, urls: bool = False) -> list[Finding]:
    """Identifiants de projet, chemins locaux, chaines de contenu du projet (bloquants), URL externes et `data:` volumineux
    (avertissements) dans un texte. Les messages portent des comptes."""

    found: list[Finding] = []
    n = len(_PROJECT_ID.findall(text))
    if n:
        found.append(Finding("project_identifier", where, f"{n} project identifier(s) (presentation, scene, variant or studio prefab ids)"))
    n = len(_LOCAL_PATH.findall(text))
    if n:
        found.append(Finding("local_path", where, f"{n} local path or local-resource reference(s)"))
    folded = normalise(text)
    n = sum(1 for term in terms if term in folded)
    if n:
        found.append(Finding("project_content", where, f"{n} string(s) of the project's own content still present"))
    if urls:
        n = len(_EXTERNAL_URL.findall(text))
        if n:
            found.append(Finding("external_url", where, f"{n} external URL(s) hard-coded in the source (kept; check they are generic)",
                                 blocking=False))
        n = len(_DATA_URI.findall(text))
        if n:
            found.append(Finding("embedded_asset", where, f"{n} large embedded data: asset(s) (kept; check they are not project media)",
                                 blocking=False))
    return found


def scan_value(where: str, value: Any, terms: frozenset[str]) -> list[Finding]:
    """Idem sur toutes les chaines d'une valeur JSON (manifeste, enregistrement de scene, direction artistique)."""

    return scan_text(where, "\n".join(_strings(value)), terms)


# ------------------------------------------------------------------ la scene -> un prefab reutilisable


class SelectionError(ValueError):
    """Une selection incoherente (controle inconnu, dimension qui n'est pas un reglage d'aspect...) : a corriger par l'appelant."""


@dataclass(frozen=True, slots=True)
class SceneBuild:
    """Resultat pour une scene. `candidate` : `{manifest, template, style, behavior}` (id/titre/version a poser par l'appelant) ;
    `props`/`data` : valeurs d'instance sans contenu ; `controls`, `anchors` : le sous-ensemble choisi ; `roles` : par controle
    garde `{kind: dimension|parameter, role: look|content, type}`."""

    candidate: dict[str, Any]
    props: dict[str, Any]
    data: dict[str, Any]
    controls: tuple[dict[str, Any], ...]
    anchors: tuple[dict[str, Any], ...]
    roles: dict[str, dict[str, str]]
    stripped: dict[str, int]
    findings: tuple[Finding, ...]


def build_scene(*, manifest: Mapping[str, Any], files: Mapping[str, str], props: Mapping[str, Any], data: Mapping[str, Any],
                controls: Sequence[StudioControl], anchors: Sequence[Mapping[str, Any]], dimensions: Sequence[str],
                parameters: Sequence[str], terms: frozenset[str], key: str, title: str, description: str,
                tags: Sequence[str]) -> SceneBuild:
    """Voir l'en-tete du module. `manifest` est le manifeste brut de la version epinglee ; rien n'est modifie en place."""

    by_id = {c.control_id: c for c in controls}
    where = f"scene:{key}"
    for name, picked in (("dimensions", dimensions), ("parameters", parameters)):
        unknown = [c for c in picked if c not in by_id]
        if unknown:
            raise SelectionError(f"{where}.{name}: {len(unknown)} control id(s) are not controls of this scene")
        if len(set(picked)) != len(picked):
            raise SelectionError(f"{where}.{name} lists a control twice")
    both = set(dimensions) & set(parameters)
    if both:
        raise SelectionError(f"{where}: {len(both)} control(s) are listed both as dimension and as parameter")

    raw = copy.deepcopy(dict(manifest))
    inputs = raw["inputs"]
    values = {"props": dict(props), "data": dict(data)}
    sample: dict[str, dict[str, Any]] = {"props": {}, "data": {}}
    findings: list[Finding] = []
    stripped = {"content_values": 0, "defaults": 0, "look_reset": 0}
    bound = {c.path: c for c in controls}
    roles: dict[str, dict[str, str]] = {}

    for root in ("props", "data"):
        for leaf in leaves(inputs[root], root):
            control = bound.get(leaf.path)
            role = leaf_role(leaf, control)
            name = leaf.path.rsplit(".", 1)[1]
            chosen = control is not None and control.control_id in dimensions
            if control is not None and (chosen or control.control_id in parameters):
                kind = "dimension" if chosen else "parameter"
                if chosen and (leaf.type not in LOOK_TYPES or role != "look"):
                    raise SelectionError(
                        f"{where}: control {control.control_id} ({leaf.type}, group {control.group.value}) is project content, "
                        "not a reusable dimension: list it as a parameter or leave it out")
                roles[control.control_id] = {"kind": kind, "role": role, "type": leaf.type}
            if chosen:
                present, current = _get(values[root], leaf.path)
                if present:
                    leaf.node["default"] = current
                    _put(sample[root], leaf.path, current)
                elif "default" in leaf.node:
                    _put(sample[root], leaf.path, leaf.node["default"])
                else:
                    _put(sample[root], leaf.path, placeholder(leaf.node, name))
            elif role == "content":
                if "default" in leaf.node:
                    leaf.node["default"] = placeholder(leaf.node, name)
                    stripped["defaults"] += 1
                if _get(values[root], leaf.path)[0]:
                    stripped["content_values"] += 1
                _put(sample[root], leaf.path, placeholder(leaf.node, name))
            else:
                if _get(values[root], leaf.path)[0] and "default" in leaf.node and _get(values[root], leaf.path)[1] != leaf.node["default"]:
                    stripped["look_reset"] += 1
                _put(sample[root], leaf.path, leaf.node["default"] if "default" in leaf.node else placeholder(leaf.node, name))

    # Le manifeste d'une promotion ne porte ni les alias (ils nomment l'original) ni le titre, la description ou les etiquettes du
    # projet : ceux de l'appelant les remplacent (l'id definitif est pose par le service, qui deduplique d'abord).
    raw = decorate_manifest(raw, prefab_id=PENDING_ID, title=title, description=description, tags=tags)
    raw["aliases"] = []
    for root in ("props", "data"):
        try:
            schema = parse_input_schema(inputs[root], f"inputs.{root}")
            checked, problems = validate_value(schema, sample[root], root)
        except PrefabDefinitionError as exc:
            findings.append(Finding("placeholder_unfit", f"{where}.manifest", f"the neutral {root} do not fit the schema: {exc.errors[0][:120]}"))
            continue
        if problems:
            findings.append(Finding("placeholder_unfit", f"{where}.manifest",
                                    f"the neutral {root} do not fit the schema ({len(problems)} problem(s), first at "
                                    f"{problems[0].split(':')[0][:80]}): the source must declare a default for it"))
        else:
            sample[root] = checked
    raw["sample"] = {"props": sample["props"], "data": sample["data"]}

    kept = set(roles)
    kept_controls: list[dict[str, Any]] = []
    for control in controls:
        if control.control_id in kept:
            wire = control.to_dict()
            wire["default"] = None  # un defaut cure est une valeur du projet : le prefab porte le defaut
            kept_controls.append(wire)
    kept_anchors = [dict(a) for a in anchors if a.get("control_id") is None or a.get("control_id") in kept]
    stripped["controls_dropped"] = len(controls) - len(kept_controls)
    stripped["anchors_dropped"] = len(anchors) - len(kept_anchors)

    candidate = {"manifest": raw, "template": files["template"], "style": files["style"], "behavior": files["behavior"]}
    for part in ("template", "style", "behavior"):
        findings.extend(scan_text(f"{where}.source.{part}", candidate[part], terms, urls=True))
    findings.extend(scan_value(f"{where}.manifest", raw, terms))
    findings.extend(scan_value(f"{where}.controls", [kept_controls, kept_anchors], terms))
    return SceneBuild(candidate, sample["props"], sample["data"], tuple(kept_controls), tuple(kept_anchors), roles, stripped,
                      tuple(findings[:MAX_FINDINGS]))


def decorate_manifest(raw: dict[str, Any], *, prefab_id: str, title: str, description: str, tags: Sequence[str]) -> dict[str, Any]:
    """Pose l'identite du prefab promu (id neuf, titre, description generique + celle de l'auteur, etiquettes) sur le manifeste."""

    out = dict(raw)
    out["id"] = prefab_id
    out["title"] = title[:MAX_TITLE_CHARS]
    base = "Reusable scene promoted from a Presentation Studio presentation; content parameterized, project references removed."
    out["description"] = (f"{description} {base}" if description else base)[:MAX_DESCRIPTION_CHARS]
    out["tags"] = list(dict.fromkeys(["presentation-template", *tags]))[:16]
    return out


# ------------------------------------------------------------------ direction artistique


#: Les sections d'un profil que l'on peut promouvoir (`Section` de la DA ; `motion` est le « motif de mouvement »).
DA_SECTIONS = ("palette", "typography", "spacing", "shapes", "imagery", "dataviz", "motion")


def sanitize_da_sections(profile: Mapping[str, Any], sections: Sequence[str], *, keep_motifs: bool,
                         terms: frozenset[str]) -> tuple[dict[str, Any], dict[str, int], list[Finding]]:
    """Les sections choisies d'un profil de direction artistique, sans nom, provenance ni references de ressources. Les motifs
    (`imagery.motifs`, du texte libre) sont retires sauf demande explicite ; gardes, ils sont cherches parmi les termes du projet."""

    out: dict[str, Any] = {}
    counts = {"references_dropped": len(profile.get("references") or ()), "motifs_dropped": 0,
              "sections_dropped": len(DA_SECTIONS) - len(set(sections))}
    findings: list[Finding] = []
    for name in sections:
        section = copy.deepcopy(profile[name])
        if name == "imagery":
            if keep_motifs:
                findings.extend(scan_value("art_direction.imagery.motifs", section.get("motifs", []), terms))
            else:
                counts["motifs_dropped"] = len(section.get("motifs", []))
                section["motifs"] = []
        out[name] = section
    findings.extend(scan_value("art_direction", out, frozenset()))
    return out, counts, findings


def content_values(manifest: Mapping[str, Any], controls: Sequence[StudioControl], props: Mapping[str, Any],
                   data: Mapping[str, Any]) -> list[Any]:
    """Les valeurs d'instance des feuilles de **contenu** (pas les reglages d'aspect : `compact` est aussi un mot du code)."""

    bound = {c.path: c for c in controls}
    trees = {"props": dict(props), "data": dict(data)}
    found: list[Any] = []
    for root in ("props", "data"):
        for leaf in leaves(manifest["inputs"][root], root):
            if leaf_role(leaf, bound.get(leaf.path)) == "content":
                present, value = _get(trees[root], leaf.path)
                if present:
                    found.append(value)
    return found


def compose_profile(sections: Mapping[str, Any], name: str | None, base: Mapping[str, Any] | None = None) -> Any:
    """Un profil de direction artistique complet. Sans `base` : le profil de repli deterministe dont les `sections` sont remplacees,
    sans reference ni provenance du projet. Avec `base` (la direction artistique de la destination) : ses sections non choisies,
    son nom, ses references et sa provenance sont gardes, les sections choisies sont marquees `provided`. Leve
    `PresentationStudioError` si l'ensemble ne tient pas debout (contraste, vocabulaire)."""

    from jarvis.domain.presentation_studio_art_direction import ArtDirectionProfile
    from jarvis.domain.presentation_studio_art_direction_authoring import generate_fallback_profile

    document = copy.deepcopy(dict(base)) if base is not None else generate_fallback_profile().to_dict()
    document.update(copy.deepcopy(dict(sections)))
    if base is None:
        document["references"] = []
        document["provenance"] = {"origin": "provided", "sections": {}, "fallback": False, "confidence": 1.0,
                                  "notes": ["Instantiated from a reusable presentation template."]}
    else:
        marks = dict(document["provenance"].get("sections", {}))
        marks.update({section: "provided" for section in sections})
        document["provenance"] = {**document["provenance"], "sections": marks}
    if name is not None:
        document["name"] = name
    return ArtDirectionProfile.from_dict(document)
