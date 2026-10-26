"""Lecture unique de l'édition produit d'un processus JARVIS (`docs/product-edition.md` › *Selection*).

Core (`app.py`), le Control Center (consigne du cerveau, `--mcp-config`) et les serveurs MCP
(`jarvis-workspace`, `jarvis-console`) passent tous par `process_edition` : une seule règle, celle de
`resolve_product_edition` (valeur illisible = `ConfigurationError`, jamais `full` en silence).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from jarvis.domain.product_edition import ProductEditionPolicy, resolve_product_edition


def process_edition(environ: Mapping[str, str] | None = None) -> ProductEditionPolicy:
    """Politique de l'édition de ce processus (`JARVIS_PRODUCT_EDITION`, défaut `full`)."""

    return resolve_product_edition(os.environ if environ is None else environ)
