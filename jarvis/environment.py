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


def parse_environment_lines(lines: list[str], *, path: Path | str = ".env") -> list[tuple[int, str, str]]:
    """Affectations `.env` littérales d'une ligne : `(index de ligne, nom, valeur)`, dans l'ordre du fichier.

    Seul parseur `.env` de JARVIS (chargement au démarrage, reprise des clés dans le coffre,
    `jarvis/runtime/local_secrets.py`). `export ` en tête accepté ; valeur entre guillemets simples ou
    doubles prise telle quelle (un `#` après le guillemet fermant est un commentaire) ; sans guillemets,
    ` #…` est un commentaire ; une valeur qui commence par `#` est vide. Toute ligne illisible lève
    `ConfigurationError` : le fichier entier est refusé, rien n'est appliqué à moitié.
    """
    out: list[tuple[int, str, str]] = []
    for index, raw in enumerate(lines):
        number = index + 1
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
        out.append((index, name, value))
    return out


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

    values: dict[str, str] = {name: value for _, name, value in parse_environment_lines(lines, path=path)}

    # Validate the whole file first so a malformed line cannot partly configure a run.
    for name, value in values.items():
        os.environ.setdefault(name, value)
