"""Profil vocal du propriétaire : un fichier JSON local, jamais dans Git.

Le profil ne garde que ce que le moteur exige pour juger : l'empreinte de
référence et de quoi vérifier qu'elle vient bien du même modèle. Aucun audio
d'enrôlement n'est conservé. L'empreinte est une donnée biométrique : elle ne
sort de ce module que vers le vérificateur, jamais vers un journal ni une
réponse HTTP — `OwnerVoiceProfile.metadata()` est la seule vue publique.

Chiffrement au repos : pas encore (question ouverte du journal des décisions).
Le fichier est écrit en 0600 quand le système le permet, sous le dossier
runtime ignoré par Git.
"""

from __future__ import annotations

import json
import math
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from jarvis.adapters.file_replace import replace_with_retry

PROFILE_SCHEMA = 1
PROFILE_KIND = "jarvis.owner_voice_profile"
#: Un profil vocal pèse quelques kilo-octets ; au-delà, ce n'en est pas un.
_MAX_PROFILE_BYTES = 256 * 1024
_MAX_DIM = 4096


class OwnerProfileError(Exception):
    """Profil absent ou inutilisable, avec un code stable pour l'interface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class OwnerVoiceProfile:
    """Profil enrôlé. `embedding` n'apparaît jamais dans `repr`."""

    profile_id: str
    engine: str
    model_id: str
    model_sha256: str
    embedding_dim: int
    sample_rate: int
    enrollment_ms: int
    segments: int
    created_at: str
    embedding: tuple[float, ...] = field(repr=False)
    consistency: float | None = None

    def __post_init__(self) -> None:
        for name in ("profile_id", "engine", "model_id", "model_sha256", "created_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("embedding_dim", "sample_rate", "enrollment_ms", "segments"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        if self.embedding_dim > _MAX_DIM or len(self.embedding) != self.embedding_dim:
            raise ValueError("embedding length does not match embedding_dim")
        if not all(isinstance(value, float) and math.isfinite(value) for value in self.embedding):
            raise ValueError("embedding must contain finite floats")
        if not any(self.embedding):
            raise ValueError("embedding has no direction")

    def metadata(self) -> dict[str, object]:
        """Ce qui peut s'afficher : tout sauf l'empreinte."""

        return {
            "profile_id": self.profile_id,
            "engine": self.engine,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "embedding_dim": self.embedding_dim,
            "sample_rate": self.sample_rate,
            "enrollment_ms": self.enrollment_ms,
            "segments": self.segments,
            "consistency": self.consistency,
            "created_at": self.created_at,
        }

    def incompatibility(self, *, model_sha256: str, embedding_dim: int, sample_rate: int) -> str | None:
        """Pourquoi ce profil ne peut pas servir avec ce modèle, ou `None`.

        Seul le modèle compte : une autre version de la bibliothèque qui charge
        les mêmes poids rend les mêmes empreintes.
        """

        if self.model_sha256 != model_sha256:
            return "enrôlé avec un autre modèle"
        if self.embedding_dim != int(embedding_dim):
            return f"empreinte de dimension {self.embedding_dim}, le modèle en rend {int(embedding_dim)}"
        if self.sample_rate != int(sample_rate):
            return f"enrôlé à {self.sample_rate} Hz, le modèle travaille à {int(sample_rate)} Hz"
        return None


def new_profile_id() -> str:
    return f"owner-{secrets.token_hex(4)}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def save_profile(path: Path, profile: OwnerVoiceProfile) -> None:
    """Écrire le profil atomiquement (fichier temporaire puis remplacement).

    Le remplacement est réessayé quand Windows refuse l'accès (antivirus ou
    indexeur qui tient la cible quelques millisecondes) ; jamais d'écriture
    en place, qui laisserait un profil biométrique à moitié écrit. Si le
    remplacement échoue quand même, le fichier temporaire est supprimé,
    l'ancien profil reste intact et l'erreur porte un code stable.
    """

    payload = {"schema": PROFILE_SCHEMA, "kind": PROFILE_KIND, **profile.metadata(), "embedding": list(profile.embedding)}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        replace_with_retry(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise OwnerProfileError(
            "owner_profile_write_failed",
            f"Profil vocal non enregistré ({path}) : {type(exc).__name__}. "
            "Fermez ce qui tient le fichier (antivirus, éditeur) et recommencez.",
        ) from None


def load_profile(path: Path) -> OwnerVoiceProfile:
    """Relire un profil ; toute anomalie devient une `OwnerProfileError` codée."""

    path = Path(path)
    if not path.is_file():
        raise OwnerProfileError("owner_profile_missing", f"Aucun profil vocal enrôlé ({path}).")
    try:
        if path.stat().st_size > _MAX_PROFILE_BYTES:
            raise ValueError("profile too large")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("kind") != PROFILE_KIND:
            raise ValueError("not an owner voice profile")
        if payload.get("schema") != PROFILE_SCHEMA:
            raise ValueError(f"unsupported schema {payload.get('schema')!r}")
        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("embedding must be a list")
        consistency = payload.get("consistency")
        return OwnerVoiceProfile(
            profile_id=payload.get("profile_id"),
            engine=payload.get("engine"),
            model_id=payload.get("model_id"),
            model_sha256=payload.get("model_sha256"),
            embedding_dim=payload.get("embedding_dim"),
            sample_rate=payload.get("sample_rate"),
            enrollment_ms=payload.get("enrollment_ms"),
            segments=payload.get("segments"),
            created_at=payload.get("created_at"),
            embedding=tuple(float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value for value in embedding),
            consistency=float(consistency) if isinstance(consistency, (int, float)) and not isinstance(consistency, bool) else None,
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        # Le message ne cite ni le contenu ni l'empreinte : seulement le fichier.
        raise OwnerProfileError(
            "owner_profile_corrupt",
            f"Profil vocal illisible ({path}) : {type(exc).__name__}. Supprimez-le et enrôlez-vous de nouveau.",
        ) from None


def delete_profile(path: Path) -> bool:
    """Supprimer le profil ; `False` s'il n'existait pas."""

    path = Path(path)
    removed = False
    for candidate in (path, path.with_name(path.name + ".tmp")):
        try:
            candidate.unlink()
            removed = removed or candidate == path
        except FileNotFoundError:
            continue
    return removed
