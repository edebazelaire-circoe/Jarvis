from __future__ import annotations

import os
from pathlib import Path
import re

from jarvis.domain.errors import ConfigurationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_environment_file() -> Path:
    """`<dépôt>/.env` en développement ; `<maison du produit>/config/.env` pour un produit installé.

    Un produit installé ne lit jamais de `.env` dans le dossier du programme : rien de
    secret ni de canonique n'y vit (`docs/local-data.md` › *Produit installé*).
    """
    from jarvis.installation import detect_installation  # import tardif : `installation` ne dépend de rien ici

    installation = detect_installation()
    return installation.home.config / ".env" if installation.installed else PROJECT_ROOT / ".env"


def load_project_environment() -> None:
    """Load literal, single-line .env assignments without replacing the environment."""
    path = project_environment_file()
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        # The local .env is optional when configuration is supplied by the process.
        return
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError(f"Impossible de lire {path}") from exc

    values: dict[str, str] = {}
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            raise ConfigurationError(f"Affectation .env invalide : {path}, ligne {number}")

        if value.startswith(("'", '"')):
            quote = value[0]
            value, closing, suffix = value[1:].partition(quote)
            if not closing or (suffix.strip() and not suffix.lstrip().startswith("#")):
                raise ConfigurationError(f"Valeur .env invalide : {path}, ligne {number}")
        elif value.startswith("#"):
            value = ""
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[name] = value

    # Validate the whole file first so a malformed line cannot partly configure a run.
    for name, value in values.items():
        os.environ.setdefault(name, value)
