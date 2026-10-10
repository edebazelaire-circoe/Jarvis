"""Promotion d'une source de scene : partie moteur, licence, provenance (handoff jarvis-remotion-presentation-integration, Slice 19).

Pur. Complete `presentation_studio_template_sanitize` (qui parametre le manifeste et detecte les fuites) pour ce que seule une source
**Remotion** (TSX) ou un bloc `catalog` ajoute. Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract* >
*Remotion-aware promotion*.

- **Source TSX** : lue comme du TEXTE, jamais executee. Les modules sont cherches (identifiants de projet, de Board et d'artefact, chemins
  locaux, contenu du projet) comme n'importe quelle source ; un constat est bloquant et le TSX n'est **jamais reecrit** automatiquement
  (une reecriture silencieuse de code serait une modification que personne n'a relue). Les parametres d'une source Remotion sont ses
  `inputs.props` / `inputs.data` : ils passent par le meme parametrage que ceux d'un prefab HTML.
- **Bloc `catalog` v3** : etiquete le moteur (`compatibility` natif pour le moteur de la source), garde pile, dependances, licence et amont.
  Une source qui n'a pas de bloc en recoit un derive (composition, Remotion natif, Slidecar non supporte), ecrit en v3.
- **Provenance** (Slice 18) : les clefs ecrites par l'importeur (`VERIFIED_UPSTREAM_KEYS`, `runtime_license`) ne survivent a une promotion que
  si les fichiers sont **exactement** ceux de l'import (`source_sha256` recalcule ici, jamais lu d'un rapport) ; une source modifiee perd
  ces clefs et la promotion le dit (`upstream_verification_dropped`) : elle ne sera jamais presentee comme verifiee.
- **Licence** : une source qui vient d'un amont (importe ou declare) dont la licence n'est pas redistribuable (hors `PERMITTED_LICENCES`)
  ou pas declaree n'est promue que si l'utilisateur reconnait cette licence par son nom (`licence_ack`).
"""

from __future__ import annotations

import base64
import copy
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.domain.prefab import canonical_json
from jarvis.domain.prefab_catalog import REMOTION_STACK, VERIFIED_UPSTREAM_KEYS
from jarvis.domain.presentation_studio_template_sanitize import Finding
from jarvis.domain.remotion_source import RemotionSource, source_digest
from jarvis.domain.remotion_upstream import PERMITTED_LICENCES

#: Ce que l'on montre quand un amont est cite sans licence.
LICENCE_NOT_DECLARED = "not-declared"
#: Champs d'identite d'un manifeste de candidat : la teneur d'une source ne les compte pas.
IDENTITY_KEYS = ("id", "title", "description", "tags")


def remotion_parts(source: RemotionSource) -> tuple[dict[str, str], dict[str, bytes]]:
    """`(modules {chemin: texte}, assets {chemin: octets})` d'une source lue (gardes de la Slice 06 passees a la lecture)."""

    assets = {path: source.files[path] for path in source.block.assets}
    return source.module_texts(), assets


def is_intact(source: RemotionSource, manifest: Mapping[str, Any]) -> bool:
    """Les fichiers sont-ils EXACTEMENT ceux de l'import (`catalog.upstream.source_sha256`) ? Recalcule ici, depuis les octets."""

    upstream = (manifest.get("catalog") or {}).get("upstream") or {}
    claimed = upstream.get("source_sha256")
    return bool(claimed) and source_digest(source.files) == claimed


def candidate_of(manifest: dict[str, Any], modules: Mapping[str, str], assets: Mapping[str, bytes]) -> dict[str, Any]:
    """Le candidat Remotion `{manifest, sources, assets}` (assets en base64) pour `PrefabService.save` / `parse_candidate`."""

    return {"manifest": manifest, "sources": dict(modules),
            "assets": {path: base64.b64encode(data).decode("ascii") for path, data in assets.items()}}


def embedded_bytes(candidate: Mapping[str, Any]) -> int:
    """Octets decodes d'un candidat (HTML : ses trois fichiers ; Remotion : modules + assets decodes)."""

    if "sources" in candidate:
        return (sum(len(t.encode("utf-8")) for t in candidate["sources"].values())
                + sum(len(v) * 3 // 4 for v in candidate["assets"].values()))
    return sum(len(str(candidate[part]).encode("utf-8")) for part in ("template", "style", "behavior"))


def content_hash(candidate: Mapping[str, Any]) -> str:
    """Empreinte de contenu d'une source integree : le candidat sans l'identite (id, titre, description, etiquettes)."""

    body = copy.deepcopy(dict(candidate))
    for key in IDENTITY_KEYS:
        body["manifest"].pop(key, None)
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def promotion_catalog(raw: Mapping[str, Any], *, remotion: bool, intact: bool, where: str) -> tuple[dict[str, Any], bool, list[Finding]]:
    """`(manifeste, verifie, constats)` : le manifeste promu avec son bloc `catalog` (v3). Un manifeste HTML sans bloc reste intact (v1).

    `verifie` : les clefs ecrites par l'importeur sont gardees, donc la publication doit passer par la porte de l'importeur
    (`verified_import`) ; vrai seulement si `intact`."""

    out = copy.deepcopy(dict(raw))
    findings: list[Finding] = []
    block = out.get("catalog")
    if block is None and not remotion:
        return out, False, findings
    if block is None:
        block = {"type": "composition", "compatibility": {"remotion": "native", "slidecar": "unsupported"},
                 "stack": list(REMOTION_STACK)}
    block = dict(block)
    engine = "remotion" if remotion else "slidecar"
    if (block.get("compatibility") or {}).get(engine) != "native":
        findings.append(Finding("engine_not_native", where, f"the source does not declare {engine} as native: only a native source is "
                                                            "usable in a presentation of that engine (declared, not usable)"))
    upstream = dict(block["upstream"]) if isinstance(block.get("upstream"), dict) else None
    claims = (upstream is not None and any(upstream.get(k) for k in VERIFIED_UPSTREAM_KEYS)) or bool(block.get("runtime_license"))
    verified = bool(claims) and intact
    if claims and not intact:
        for key in VERIFIED_UPSTREAM_KEYS:
            if upstream is not None:
                upstream.pop(key, None)
        block.pop("runtime_license", None)
        findings.append(Finding("upstream_verification_dropped", where,
                                "the files differ from the verified import: the origin stays as a declaration, never as verified",
                                blocking=False))
    if upstream is not None:
        block["upstream"] = upstream
    out["schema_version"] = 3
    out["catalog"] = block
    return out, verified, findings


def licence_of(manifest: Mapping[str, Any]) -> str | None:
    """La licence a reconnaitre pour cette source, ou `None` quand rien ne l'exige : un amont (importe ou declare) dont la licence
    n'est pas redistribuable ou pas declaree. Une source sans amont est le travail de l'utilisateur."""

    block = manifest.get("catalog") or {}
    upstream = block.get("upstream")
    if not isinstance(upstream, dict):
        return None
    licence = (block.get("license") or upstream.get("license") or "").strip()
    return None if licence in PERMITTED_LICENCES else (licence or LICENCE_NOT_DECLARED)


def licence_findings(licences: Mapping[str, Sequence[str]], acks: Sequence[str]) -> list[Finding]:
    """Un constat par licence a reconnaitre : bloquant tant qu'elle n'est pas nommee dans `acks`, informatif ensuite."""

    out: list[Finding] = []
    for licence, wheres in licences.items():
        where = ", ".join(wheres[:3])
        if licence in acks:
            out.append(Finding("licence_acknowledged", where, f"licence '{licence}' acknowledged by the user for the shared library",
                               blocking=False))
        else:
            out.append(Finding("licence_acknowledgement_required", where,
                               f"the upstream licence '{licence}' is not a redistributable one reviewed by Jarvis: to publish it to the shared "
                               f"library, name it in licence_ack: [\"{licence}\"]"))
    return out
