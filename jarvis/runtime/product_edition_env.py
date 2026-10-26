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
