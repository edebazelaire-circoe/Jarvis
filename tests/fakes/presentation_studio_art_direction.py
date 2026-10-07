"""Données déterministes de la direction artistique (Slice 09) : un profil complet, des chemins de feuilles à corrompre,
des chaînes hostiles, des signaux factices (ce qu'un agent rapporterait d'un projet, sans disque ni réseau).

`python -m tests.fakes.presentation_studio_art_direction` réécrit `tests/fixtures/presentation_studio/art_direction.v1.json`
(un document stocké au format v1 : il fige le schéma, il n'est pas régénéré par les tests).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jarvis.domain.presentation_studio_art_direction import ArtDirection, ArtDirectionProfile, parse_profile
from jarvis.domain.presentation_studio_art_direction_authoring import (
    ColorSignal, DesignSignals, FontSignal, SeedContext, generate_fallback_profile,
)
from jarvis.domain.presentation_working_set import ResourceKind, ResourceReference

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio" / "art_direction.v1.json"
PRESENTATION = "pst_" + "a" * 32
VARIANT = "psv_" + "b" * 32
AD_ID = "psd_000000000001"
STAMP = "2026-10-07T12:00:00.000000Z"

#: Valeurs qui ne sont ni une couleur, ni un entier, ni un membre d'un vocabulaire, ni un nom de famille simple.
#: Chacune contient au moins un caractère hors `[A-Za-z0-9 -]`, donc aucune n'est un nom de famille légal.
HOSTILE = (
    "url(http://evil.example/x.png)", "url(javascript:alert(1))", "expression(alert(1))", "@import 'https://evil.example/x.css'",
    "var(--jv-accent)", "var(--a, var(--a))", "javascript:alert(1)", "vbscript:msgbox(1)", "data:text/html,<script>alert(1)</script>",
    "#fff;background:url(x)", "#ffffff;}</style><script>alert(1)</script>", "}</style><script>alert(1)</script>",
    "</script><img src=x onerror=alert(1)>", "calc(1px + 1px)", "red; position:fixed", "\x00", "a\nb", "a\u202eb",
    "\u200b", "../../etc/passwd", "C:\\Windows\\system32", "{{7*7}}", "${7*7}", "'; DROP TABLE x; --", "<b>x</b>",
    "-moz-binding:url(x)", "behavior:url(x.htc)", "\ud800",
)
#: Fausses couleurs (aucune n'est `#rrggbb`).
NOT_COLORS = ("red", "rgb(0,0,0)", "rgba(0,0,0,.5)", "hsl(0,0%,0%)", "#fff", "#ffff", "#fffffff", "#ggg000", "transparent",
              "currentColor", "inherit", "#FFFFFF ", " #ffffff", "#ffffff\n", "0xffffff", "ffffff")


def base_profile() -> ArtDirectionProfile:
    return generate_fallback_profile(SeedContext(title="Base", tone=("sobre", "corporate")))


def base_dict() -> dict[str, Any]:
    return copy.deepcopy(base_profile().to_dict())


def full_dict() -> dict[str, Any]:
    """Un profil qui renseigne tout : sections, famille déclarée, deux références, accent_alt, un 2e dégradé."""

    doc = base_dict()
    doc["name"] = "Direction complete"
    doc["provenance"] = {"origin": "inferred", "sections": {"palette": "provided", "motion": "generated"},
                         "fallback": False, "confidence": 0.7, "notes": ["Palette taken from the brand sheet."]}
    doc["typography"]["heading"]["preferred"] = "Inter"
    doc["imagery"]["motifs"] = ["people", "daylight"]
    doc["references"] = [{"kind": "document", "locator": "doc:brand-guidelines", "title": "Brand guidelines"},
                         {"kind": "web_page", "locator": "https://example.com/design", "title": ""}]
    doc["palette"]["gradients"].append({
        "gradient_id": "halo", "kind": "radial", "angle": 0, "text_token": "text",
        "stops": [{"color": doc["palette"]["background"], "at": 0}, {"color": doc["palette"]["surface"], "at": 60},
                  {"color": doc["palette"]["background"], "at": 100}]})
    return doc


def set_path(doc: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Copie de `doc` où `path` (`a.b.0.c`) vaut `value`."""

    out = copy.deepcopy(doc)
    node: Any = out
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return out


def leaves(doc: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Chaque feuille (chemin, valeur) du document ; une liste vide ou un objet vide est une feuille."""

    if isinstance(doc, dict) and doc:
        return [pair for key, value in doc.items() for pair in leaves(value, f"{prefix}.{key}" if prefix else key)]
    if isinstance(doc, list) and doc:
        return [pair for n, value in enumerate(doc) for pair in leaves(value, f"{prefix}.{n}" if prefix else str(n))]
    return [(prefix, doc)]


def objects(doc: Any, prefix: str = "") -> list[str]:
    """Chemin de chaque objet JSON imbriqué (la racine est `""`)."""

    found: list[str] = []
    if isinstance(doc, dict):
        found.append(prefix)
        for key, value in doc.items():
            found += objects(value, f"{prefix}.{key}" if prefix else key)
    elif isinstance(doc, list):
        for n, value in enumerate(doc):
            found += objects(value, f"{prefix}.{n}" if prefix else str(n))
    return found


def document(profile: ArtDirectionProfile | None = None, *, revision: int = 1) -> dict[str, Any]:
    return ArtDirection(AD_ID, PRESENTATION, VARIANT, profile or parse_profile(full_dict()), revision, STAMP,
                        STAMP).to_document()


def signals_dark_brand() -> DesignSignals:
    """Ce qu'un agent rapporterait d'un dépôt au thème sombre, police serif, coins arrondis."""

    return DesignSignals(
        sources=(ResourceReference(ResourceKind.DOCUMENT, "doc:design-tokens", "Design tokens"),
                 ResourceReference(ResourceKind.WEB_PAGE, "https://example.com/brand", "")),
        colors=(ColorSignal("#0b1020", "background", 40), ColorSignal("#e8ecf4", "text", 30),
                ColorSignal("#ff7a00", "accent", 12), ColorSignal("#00c2a8", "unknown", 5),
                ColorSignal("#9aa4b8", "muted", 8)),
        fonts=(FontSignal("Playfair Display", "heading"), FontSignal("Inter", "body")),
        radii_px=(8, 12, 16), mentions=("launch", "keynote"))


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(document(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE}")
