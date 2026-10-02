"""Le contexte global de JARVIS : `<data_root>/CONTEXT_GLOBAL/`, géré par l'agent lui-même.

Le dossier appartient au PC, comme les bases (`docs/local-data.md`) : l'agent
y écrit librement, git ne le voit jamais. Il est créé une seule fois, depuis le
modèle versionné `jarvis/context_global_seed/`, puis n'est plus jamais
réinitialisé : un fichier que l'agent a supprimé reste supprimé.

`base_context.yaml` liste, dans l'ordre, les fichiers dont le contenu forme la
partie « contexte global » de la consigne système du cerveau, assemblée à
chaque lancement du CLI (`docs/context-global.md`). Tout le reste du dossier
(tâches en cours, captures, pense-bêtes…) n'est lu que sur demande.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import tempfile

GLOBAL_CONTEXT_DIR = "CONTEXT_GLOBAL"
MANIFEST_NAME = "base_context.yaml"
GLOBAL_CONTEXT_ENV = "JARVIS_GLOBAL_CONTEXT_DIR"
SEED_ROOT = Path(__file__).resolve().parent.parent / "context_global_seed"
#: Plafond du texte assemblé. La consigne passe en argument du CLI : la ligne de
#: commande Windows plafonne à 32 767 caractères, et le socle en prend déjà ~16 000.
MAX_ASSEMBLED_CHARS = 12000
MAX_MANIFEST_BYTES = 16384
MAX_MANIFEST_ENTRIES = 64
_TEXT_SUFFIXES = {".md", ".txt", ".yaml", ".yml"}


@dataclass(frozen=True)
class GlobalContext:
    root: Path
    text: str
    files: tuple[str, ...] = ()
    problems: tuple[str, ...] = field(default_factory=tuple)
    truncated: bool = False
    seeded: bool = False

    def prompt_variable(self) -> dict[str, object]:
        """La valeur passée au registre de consignes (`global_context`) : JSON simple."""
        return {"root": str(self.root), "text": self.text, "files": list(self.files),
                "problems": list(self.problems), "truncated": self.truncated}


def global_context_root(data_root: Path) -> Path:
    return Path(data_root).expanduser().resolve() / GLOBAL_CONTEXT_DIR


def seed_global_context(root: Path, seed: Path = SEED_ROOT) -> bool:
    """Créer le dossier depuis le modèle s'il n'existe pas ; ne touche jamais un dossier existant.

    Copie dans un dossier temporaire voisin puis renommage : un arrêt en cours
    de copie ne laisse pas un dossier à moitié rempli que l'on prendrait pour
    celui de l'agent.
    """
    root = Path(root)
    if root.exists():
        return False
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
    try:
        shutil.copytree(seed, staging / "seed")
        try:
            os.replace(staging / "seed", root)
        except OSError:
            if root.exists():  # Un autre lancement l'a créé entre-temps : on garde le sien.
                return False
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return True


class ManifestError(ValueError):
    pass


def parse_manifest(text: str) -> list[str]:
    """Le sous-ensemble YAML du manifeste : une liste `- fichier`, sous une clé `files:` facultative.

    Commentaires `#` et lignes vides permis, guillemets simples ou doubles
    autour d'un chemin aussi. Tout autre YAML est refusé plutôt que deviné :
    pas de dépendance PyYAML pour une liste de noms de fichiers.
    """
    entries: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "files:" and not entries:
            continue
        if not line.startswith("- "):
            raise ManifestError(f"ligne {number} : attendu « - fichier »")
        value = line[2:].strip()
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        entries.append(value)
    return entries


def _entry_path(root: Path, entry: str) -> tuple[Path | None, str]:
    """Le fichier désigné par une ligne du manifeste, ou la raison du refus."""
    if not entry.strip():
        return None, "entrée vide ignorée"
    name = entry.strip()
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, f"{name} : chemin hors du dossier refusé"
    path = (root / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        return None, f"{name} : chemin hors du dossier refusé"
    if path.name == MANIFEST_NAME:
        return None, f"{name} : le manifeste ne s'inclut pas lui-même"
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None, f"{name} : seuls les fichiers texte (.md, .txt, .yaml) s'assemblent"
    if not path.is_file():
        return None, f"{name} : fichier absent"
    return path, ""


def assemble_global_context(root: Path, *, max_chars: int = MAX_ASSEMBLED_CHARS) -> GlobalContext:
    """Lire le manifeste et assembler ses fichiers, dans l'ordre ; ne lève jamais pour un contenu fautif."""
    root = Path(root)
    manifest = root / MANIFEST_NAME
    problems: list[str] = []
    try:
        data = manifest.read_bytes()
        if len(data) > MAX_MANIFEST_BYTES:
            raise ValueError("manifeste trop long")
        entries = parse_manifest(data.decode("utf-8"))
    except FileNotFoundError:
        return GlobalContext(root, "", problems=(f"{MANIFEST_NAME} absent : aucun contexte global chargé",))
    except ManifestError as exc:
        return GlobalContext(root, "", problems=(f"{MANIFEST_NAME} illisible, {exc}",))
    except (OSError, ValueError, UnicodeError) as exc:
        return GlobalContext(root, "", problems=(f"{MANIFEST_NAME} illisible : {type(exc).__name__}",))
    if len(entries) > MAX_MANIFEST_ENTRIES:
        problems.append(f"{MANIFEST_NAME} : seules les {MAX_MANIFEST_ENTRIES} premières entrées sont lues")
        entries = entries[:MAX_MANIFEST_ENTRIES]

    sections: list[str] = []
    files: list[str] = []
    seen: set[Path] = set()
    used, truncated = 0, False
    for entry in entries:
        path, problem = _entry_path(root, entry)
        if path is None:
            problems.append(problem)
            continue
        if path in seen:
            continue
        seen.add(path)
        try:
            body = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            problems.append(f"{entry} : illisible ({type(exc).__name__})")
            continue
        body = "".join(char for char in body if char in "\n\t" or ord(char) >= 32)
        if not body:
            continue
        relative = path.relative_to(root.resolve()).as_posix()
        section = f"# {relative}\n{body}"
        room = max_chars - used - (2 if sections else 0)
        if len(section) > room:
            truncated = True
            if room > 200:
                sections.append(section[:room - 40].rstrip() + "\n[… coupé : plafond atteint]")
                files.append(relative)
            problems.append(f"plafond de {max_chars} caractères atteint à {relative}")
            break
        sections.append(section)
        files.append(relative)
        used += len(section) + (2 if len(sections) > 1 else 0)
    return GlobalContext(root, "\n\n".join(sections), tuple(files), tuple(problems), truncated)


def load_global_context(root: Path) -> GlobalContext:
    """Créer le dossier au premier lancement, puis l'assembler. Appelé hors de la boucle (`to_thread`)."""
    seeded = seed_global_context(root)
    result = assemble_global_context(root)
    return GlobalContext(result.root, result.text, result.files, result.problems, result.truncated, seeded)


GLOBAL_CONTEXT_RULES = """\
CONTEXTE GLOBAL : TA MÉMOIRE DE DÉMARRAGE
Ton dossier de contexte global est {root} (aussi dans la variable d'environnement JARVIS_GLOBAL_CONTEXT_DIR). Il t'appartient : tu l'organises comme tu le juges utile.
- base_context.yaml liste, dans l'ordre, les fichiers assemblés dans cette consigne, juste après ces règles, au prochain démarrage de JARVIS. Tu peux ajouter, retirer, réordonner des entrées, créer, modifier ou supprimer ces fichiers : c'est ainsi que tu façonnes ton futur prompt initial. Un changement prend effet au prochain démarrage, pas dans la conversation en cours.
- Le reste du dossier n'est pas chargé : tâches en cours (current_task/), liste de choses à faire, pense-bêtes, captures, habitudes de l'utilisateur. Tu le lis quand c'est utile.
- Garde les fichiers chargés courts et à jour : le texte assemblé est plafonné à {limit} caractères, au-delà il est coupé. Ne mets jamais de secret (mot de passe, jeton) dans ce dossier.
- Écrire dans ce dossier est un travail comme un autre : confie-le à un sous-agent en lui donnant le chemin.
Ce qui suit vient de ce dossier ; les règles ci-dessus priment sur lui."""


def render_global_context_prompt(value: object) -> str:
    """Le bloc de consigne système ; vide quand aucun dossier n'est configuré (tests, autres profils)."""
    if not isinstance(value, dict) or not isinstance(value.get("root"), str) or not value["root"]:
        return ""
    text = value.get("text") if isinstance(value.get("text"), str) else ""
    rules = GLOBAL_CONTEXT_RULES.format(root=value["root"], limit=MAX_ASSEMBLED_CHARS)
    problems = [item for item in value.get("problems") or () if isinstance(item, str)]
    notice = ("\n[Problèmes à corriger dans le dossier : " + " ; ".join(problems) + "]") if problems else ""
    return rules + notice + ("\n\n" + text if text else "\n[Aucun fichier assemblé.]")
