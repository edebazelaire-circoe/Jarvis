"""Lecture unique de l'édition produit d'un processus JARVIS (`docs/product-edition.md` › *Selection*).

Core (`app.py`), le Control Center (consigne du cerveau, `--mcp-config`) et les serveurs MCP
(`jarvis-workspace`, `jarvis-console`) passent tous par `process_edition` : une seule règle, celle de
`resolve_product_edition` (valeur illisible = `ConfigurationError`, jamais `full` en silence).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from jarvis.domain.product_edition import ProductEdition, ProductEditionPolicy, resolve_product_edition
from jarvis.installation import detect_installation


def process_edition(environ: Mapping[str, str] | None = None, *, code_root=None) -> ProductEditionPolicy:
    """Politique de l'édition de ce processus.

    `JARVIS_PRODUCT_EDITION` d'abord ; sinon `presentation` pour un produit installé
    (marqueur `jarvis-product.json`, `jarvis/installation.py`), `full` pour un checkout.
    """

    env = os.environ if environ is None else environ
    installed = detect_installation(env, code_root=code_root).installed
    return resolve_product_edition(env, installed_default=ProductEdition.PRESENTATION if installed else None)


#: Marquage de `<html>` dans `control_center.html`, remplacé à chaque service de la page (Slice 08 presentation-edition,
#: `docs/control-center-shell.md` › *Product edition UI*). Non remplacé (page lue telle quelle), il ne vaut ni
#: `visible` ni `hidden` : la page garde alors ses surfaces, comme avant.
PAGE_EDITION_PLACEHOLDER = 'data-product-edition="__JARVIS_PRODUCT_EDITION__" data-developer-surfaces="__JARVIS_DEVELOPER_SURFACES__"'


def page_edition_markup(html: str, environ: Mapping[str, str] | None = None) -> str:
    """Pose l'édition de ce processus et ses surfaces de développement sur `<html>` (même politique que Core).

    Valeur illisible (`ConfigurationError`) : le marquage est retiré, la page le dit à la console et lit Core
    (`/api/boards/edition`), qui refuserait d'ailleurs de démarrer avec la même valeur.
    """

    try:
        policy = process_edition(environ)
    except Exception:  # noqa: BLE001 - argued: the page must still be served; Core is the authority and is read next
        return html.replace(PAGE_EDITION_PLACEHOLDER, 'data-product-edition="unreadable"')
    payload = policy.to_payload()
    return html.replace(PAGE_EDITION_PLACEHOLDER,
                        f'data-product-edition="{payload["edition"]}" data-developer-surfaces="{payload["developer_surfaces"]}"')
