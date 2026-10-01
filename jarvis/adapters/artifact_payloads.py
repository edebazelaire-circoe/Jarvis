"""Payloads des Artifacts sur disque (handoff session-context-recording, Slice 04).

`<data_root>/artifacts/<artifact_id>/<name>`, dérivé uniquement des ids et noms
validés par le domaine (`artifact_folder_path`, `check_payload_name`) : aucun
chemin n'est reçu en entrée. Contrat : `docs/artifacts.md` › *Payloads*.

- dossiers : défenses partagées avec les Contexts (`safe_folders`) — racine
  absolue, chaque composant inspecté, lien/jonction/point d'analyse refusé
  (`artifact_payload_unsafe`) ;
- écriture : toujours dans `<name>.partial`, puis `fsync` et renommage en
  `<name>` (`replace_with_retry`) : un fichier au nom final est un fichier
  complet. Un fichier final ou un `.partial` déjà présent n'est jamais écrasé
  (`artifact_payload_conflict`) ;
- arrêt brutal : le `.partial` reste ; `promote_partial` (reprise) le renomme
  en nom final pour un Artifact marqué `partial` par le registre ;
- suppression : seulement `remove_folder`, appelée par le service **après** le
  commit d'une suppression explicite. Aucune rétention automatique : ce n'est
  pas `runtime/scene-captures/` (D16).

Le dossier `artifacts/<id>` n'est pas synchronisé (`fsync` de dossier) : Windows
ne l'offre pas ; NTFS journalise les métadonnées, et la reprise sait traiter un
renommage perdu (le `.partial` est alors encore là).
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat

from jarvis.adapters import safe_folders
from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.artifacts import (
    ARTIFACTS_DIR, PARTIAL_SUFFIX, artifact_folder_path, check_payload_name, parse_payload_ref,
)
from jarvis.ports.artifacts import (
    PAYLOAD_CONFLICT, PAYLOAD_FAILED, PAYLOAD_UNSAFE, ArtifactPayloadError, PayloadInfo,
)

_CODES = {safe_folders.UNSAFE: PAYLOAD_UNSAFE, safe_folders.FAILED: PAYLOAD_FAILED}


def _file_size(path: Path) -> int | None:
    """Taille d'un fichier ordinaire ; `None` s'il manque ; refus s'il est un lien ou un dossier."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ArtifactPayloadError(PAYLOAD_FAILED, path, f"{type(exc).__name__}: {exc}") from exc
    if safe_folders.is_link(info) or not stat.S_ISREG(info.st_mode):
        raise ArtifactPayloadError(PAYLOAD_UNSAFE, path, "is not a regular file inside the artifact folder")
    return info.st_size


class FileArtifactSpool:
    """Écrivain en flux d'un payload (`ArtifactSpool`). Un seul écrivain par payload."""

    def __init__(self, partial: Path, final: Path) -> None:
        self._partial = partial
        self._final = final
        try:
            # "x" : jamais d'écrasement d'un `.partial` laissé par une vie précédente.
            self._handle = open(partial, "xb")
        except FileExistsError as exc:
            raise ArtifactPayloadError(PAYLOAD_CONFLICT, partial, "a partial payload is already there") from exc
        except OSError as exc:
            raise ArtifactPayloadError(PAYLOAD_FAILED, partial, f"{type(exc).__name__}: {exc}") from exc
        self._size = 0
        self._closed = False
        #: Vrai après `hand_over` : un encodeur externe écrit le `.partial` (Slice 07).
        self._external = False

    @property
    def path(self) -> Path:
        return self._partial

    @property
    def size(self) -> int:
        if self._external:
            try:
                # Taille mesurée : l'écrivain externe ne la rapporte pas. Fichier
                # disparu ou refusé : la dernière mesure reste (diagnostic seulement).
                self._size = os.stat(self._partial).st_size
            except OSError:
                pass
        return self._size

    def hand_over(self) -> Path:
        """Poignée Python fermée, `.partial` (vide) laissé à un écrivain externe ; rend son chemin."""

        if self._closed or self._size:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self._partial, "only a fresh open spool can be handed over")
        self.close()
        self._closed = False
        self._external = True
        return self._partial

    def _io(self, action, *args):  # noqa: ANN001, ANN202 - small private wrapper
        if self._closed:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self._partial, "spool is closed")
        if self._external and action != self._external_sync:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self._partial, "spool was handed over to an external writer")
        try:
            return action(*args)
        except OSError as exc:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self._partial, f"{type(exc).__name__}: {exc}") from exc

    def write(self, data: bytes) -> int:
        written = self._io(self._handle.write, data)
        self._size += written
        return written

    def write_at(self, offset: int, data: bytes) -> None:
        if type(offset) is not int or offset < 0 or offset + len(data) > self._size:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self._partial, "write_at must rewrite bytes already written")

        def rewrite() -> None:
            self._handle.seek(offset)
            self._handle.write(data)
            self._handle.seek(0, os.SEEK_END)

        self._io(rewrite)

    def sync(self) -> None:
        if self._external:
            self._io(self._external_sync)
            return

        def flush() -> None:
            self._handle.flush()
            os.fsync(self._handle.fileno())

        self._io(flush)

    def _external_sync(self) -> None:
        with open(self._partial, "rb+") as handle:
            os.fsync(handle.fileno())

    def finalize(self) -> int:
        """`fsync`, fermeture, puis `.partial` -> nom final. Un final déjà là : refus, le `.partial` reste."""

        self.sync()
        size = self.size
        self.close()
        if _file_size(self._final) is not None:
            raise ArtifactPayloadError(PAYLOAD_CONFLICT, self._final, "final payload already exists")
        try:
            replace_with_retry(self._partial, self._final)
        except OSError as exc:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self._final, f"{type(exc).__name__}: {exc}") from exc
        return size

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._external:
            return
        try:
            self._handle.close()
        except OSError as exc:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self._partial, f"{type(exc).__name__}: {exc}") from exc

    def __enter__(self) -> FileArtifactSpool:
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Sans `finalize`, le `.partial` reste : preuve pour la reprise, jamais effacée ici.
        self.close()


class FileArtifactPayloads:
    """`ArtifactPayloadStore` sur une racine de données (composition root : `v2_app`)."""

    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    def root(self) -> Path:
        return self._root.resolve() / ARTIFACTS_DIR

    def path_of(self, payload_ref: str) -> Path:
        artifact_id, name = parse_payload_ref(payload_ref)
        return self._root.resolve().joinpath(*artifact_folder_path(artifact_id).parts, name)

    def ensure_folder(self, artifact_id: str) -> Path:
        parts = artifact_folder_path(artifact_id).parts
        try:
            path, _created = safe_folders.ensure_folder_tree(self._root, parts)
        except safe_folders.SafeFolderError as exc:
            raise ArtifactPayloadError(_CODES[exc.kind], exc.path, exc.reason) from exc
        return path

    def _existing_folder(self, artifact_id: str) -> Path | None:
        try:
            return safe_folders.check_existing_tree(self._root, artifact_folder_path(artifact_id).parts)
        except safe_folders.SafeFolderError as exc:
            raise ArtifactPayloadError(_CODES[exc.kind], exc.path, exc.reason) from exc

    def open_spool(self, artifact_id: str, name: str) -> FileArtifactSpool:
        check_payload_name(name)
        # Dossier, nom et `.partial` sous la limite Windows, avant de créer le dossier.
        planned = self._root.resolve().joinpath(*artifact_folder_path(artifact_id).parts, f"{name}{PARTIAL_SUFFIX}")
        try:
            safe_folders.check_file_path(planned)
        except safe_folders.SafeFolderError as exc:
            raise ArtifactPayloadError(_CODES[exc.kind], exc.path, exc.reason) from exc
        folder = self.ensure_folder(artifact_id)
        final = folder / name
        if _file_size(final) is not None:
            raise ArtifactPayloadError(PAYLOAD_CONFLICT, final, "final payload already exists")
        return FileArtifactSpool(folder / f"{name}{PARTIAL_SUFFIX}", final)

    def write_payload(self, artifact_id: str, name: str, data: bytes) -> int:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("payload data must be bytes")
        spool = self.open_spool(artifact_id, name)
        try:
            spool.write(bytes(data))
            return spool.finalize()
        finally:
            spool.close()

    def inspect(self, artifact_id: str, name: str) -> PayloadInfo:
        check_payload_name(name)
        folder = self._existing_folder(artifact_id)
        if folder is None:
            return PayloadInfo(final_bytes=None, partial_bytes=None)
        return PayloadInfo(final_bytes=_file_size(folder / name),
                           partial_bytes=_file_size(folder / f"{name}{PARTIAL_SUFFIX}"))

    def read_range(self, artifact_id: str, name: str, offset: int, size: int) -> bytes:
        check_payload_name(name)
        if type(offset) is not int or type(size) is not int or offset < 0 or size < 0:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self.root() / artifact_id, "read_range needs offset/size >= 0")
        folder = self._existing_folder(artifact_id)
        if folder is None or size == 0:
            return b""
        # Final d'abord : `os.replace` est atomique, l'un des deux existe ; le
        # `.partial` peut disparaître entre les deux essais (renommage) -> final.
        for path in (folder / name, folder / f"{name}{PARTIAL_SUFFIX}", folder / name):
            if _file_size(path) is None:
                continue
            try:
                with open(path, "rb") as handle:
                    handle.seek(offset)
                    return handle.read(size)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ArtifactPayloadError(PAYLOAD_FAILED, path, f"{type(exc).__name__}: {exc}") from exc
        return b""

    def promote_partial(self, artifact_id: str, name: str) -> int:
        check_payload_name(name)
        folder = self._existing_folder(artifact_id)
        if folder is None:
            raise ArtifactPayloadError(PAYLOAD_FAILED, self.root() / artifact_id, "artifact folder is missing")
        partial, final = folder / f"{name}{PARTIAL_SUFFIX}", folder / name
        size = _file_size(partial)
        if size is None:
            raise ArtifactPayloadError(PAYLOAD_FAILED, partial, "no partial payload to promote")
        if _file_size(final) is not None:
            raise ArtifactPayloadError(PAYLOAD_CONFLICT, final, "final payload already exists")
        try:
            with open(partial, "rb+") as handle:
                os.fsync(handle.fileno())
            replace_with_retry(partial, final)
        except OSError as exc:
            raise ArtifactPayloadError(PAYLOAD_FAILED, partial, f"{type(exc).__name__}: {exc}") from exc
        return size

    def remove_folder(self, artifact_id: str) -> bool:
        """Retire le dossier de l'Artifact ; refuse un dossier qui serait un lien (rien n'est suivi)."""

        folder = self._existing_folder(artifact_id)
        if folder is None:
            return False
        for entry in os.scandir(folder):
            info = entry.stat(follow_symlinks=False)
            if safe_folders.is_link(info) or not stat.S_ISREG(info.st_mode):
                # Core n'écrit que des fichiers ordinaires ici : autre chose est
                # refusé plutôt que suivi ou effacé à l'aveugle.
                raise ArtifactPayloadError(PAYLOAD_UNSAFE, Path(entry.path), "unexpected entry in artifact folder")
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            raise ArtifactPayloadError(PAYLOAD_FAILED, folder, f"{type(exc).__name__}: {exc}") from exc
        return True
