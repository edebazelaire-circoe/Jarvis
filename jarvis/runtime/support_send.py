"""Envoi d'un paquet de support (V1.2 Slice 07, `docs/support-report.md` › *Envoi*).

Destination (HD-V12-02) : `DEFAULT_SUPPORT_EMAIL`, la SEULE occurrence de l'adresse dans le code, remplaçable par
`JARVIS_SUPPORT_EMAIL` (configuration du produit, `config\\.env`) puis par le réglage `support_email` du Control
Center (`resolve_destination`). Aucun envoi sans le clic « Envoyer » de l'utilisateur, consentement coché.

Transport (`JARVIS_SUPPORT_TRANSPORT`, `mapi` par défaut sous Windows) :

- `mapi` : brouillon dans la messagerie par défaut de l'utilisateur (Simple MAPI, `MAPISendMailW`, fenêtre de
  rédaction), le zip en pièce jointe. L'utilisateur relit puis envoie lui-même depuis SA messagerie. Choisi parce
  qu'il n'exige aucun secret de plus et passe la pièce jointe ; le connecteur Mail CIRCOE (Circuit Toolbox) classe
  l'envoi `destructive`, refusé à l'appel en V1 (`docs/product-connectors.md`), et ne prend pas de pièce jointe
  locale. Sans messagerie MAPI déclarée (`HKLM\\Software\\Clients\\Mail`), refus nommé `support_mail_client_missing`.
- `outbox` : destination de TEST locale (bac à sable, essais) : copie du zip et d'un `.eml.txt` dans
  `runtime\\support\\outbox\\`. N'envoie rien.
- `none` : aucun transport ; « Envoyer » est refusé, l'enregistrement manuel reste.

Un échec n'efface jamais le zip ; l'appelant propose l'enregistrement manuel.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Protocol

DEFAULT_SUPPORT_EMAIL = "e.debazelaire@circoe.com"
SUPPORT_EMAIL_ENV = "JARVIS_SUPPORT_EMAIL"
SUPPORT_EMAIL_SETTING = "support_email"
TRANSPORT_ENV = "JARVIS_SUPPORT_TRANSPORT"
TRANSPORTS = ("mapi", "outbox", "none")
OUTBOX_DIR = "outbox"
#: Au-delà, un zip n'est pas proposé à l'envoi par courriel (limite courante des messageries) : enregistrement manuel.
MAX_SEND_BYTES = 20 * 1024 * 1024
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")


class SupportSendError(RuntimeError):
    """Envoi refusé ou échoué : `code` stable, message en mots de produit, `detail` technique."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SendOutcome:
    status: str  # draft_opened | delivered_to_outbox
    message: str


class SupportTransport(Protocol):
    name: str

    def send(self, bundle: Path, *, to: str, subject: str, body: str) -> SendOutcome:
        """Remet le paquet ; `SupportSendError` en cas d'échec (le paquet reste sur le disque)."""
        ...


def valid_email(value: str) -> bool:
    return bool(_EMAIL.fullmatch(value or ""))


def resolve_destination(settings: Mapping[str, Any] | None, environ: Mapping[str, str]) -> str:
    """Réglage `support_email`, sinon `JARVIS_SUPPORT_EMAIL`, sinon `DEFAULT_SUPPORT_EMAIL` ; une valeur invalide est
    ignorée (la suivante sert)."""

    for value in (str((settings or {}).get(SUPPORT_EMAIL_SETTING) or "").strip(), str(environ.get(SUPPORT_EMAIL_ENV) or "").strip()):
        if valid_email(value):
            return value
    return DEFAULT_SUPPORT_EMAIL


def mail_text(bundle: Path, *, description: str) -> tuple[str, str]:
    subject = f"JARVIS : rapport de problème ({bundle.stem.removeprefix('jarvis-support-')})"
    body = ("Bonjour,\n\nVeuillez trouver en pièce jointe un paquet de diagnostic de JARVIS (rapport report.md, "
            "manifeste manifest.json, journaux et données masqués).\n\n"
            + (f"Description de l'utilisateur :\n{description.strip()}\n\n" if description.strip() else "")
            + "Envoyé depuis « Signaler un problème ».\n")
    return subject, body


class OutboxTransport:
    """Destination de test locale : rien ne quitte le poste."""

    name = "outbox"

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    def send(self, bundle: Path, *, to: str, subject: str, body: str) -> SendOutcome:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundle, self.folder / bundle.name)
            (self.folder / (bundle.stem + ".eml.txt")).write_text(
                f"To: {to}\nSubject: {subject}\nAttachment: {bundle.name}\n\n{body}", encoding="utf-8")
        except OSError as exc:
            raise SupportSendError("support_outbox_failed", "La boîte d'envoi de test n'a pas accepté le paquet.",
                                   f"{type(exc).__name__}: {exc}") from exc
        return SendOutcome("delivered_to_outbox", "Paquet déposé dans la boîte d'envoi de test (rien n'a quitté ce poste).")


class NoTransport:
    name = "none"

    def send(self, bundle: Path, *, to: str, subject: str, body: str) -> SendOutcome:
        raise SupportSendError("support_send_unconfigured", "Aucun moyen d'envoi n'est configuré sur ce poste.",
                               f"{TRANSPORT_ENV}=none")


class MapiTransport:
    """Brouillon dans la messagerie par défaut (Simple MAPI). Windows seulement ; appel bloquant (à lancer hors de la
    boucle). `api` : `(to, subject, body, path) -> code MAPI`, injectable par les tests."""

    name = "mapi"

    def __init__(self, *, api: Callable[[str, str, str, Path], int] | None = None,
                 client: Callable[[], str | None] | None = None) -> None:
        self._api = api or _mapi_send_mail
        self._client = client or default_mail_client

    def send(self, bundle: Path, *, to: str, subject: str, body: str) -> SendOutcome:
        client = self._client()
        if not client:
            raise SupportSendError("support_mail_client_missing",
                                   "Aucune messagerie par défaut n'est déclarée sur ce poste : enregistrez le paquet et "
                                   "joignez-le à un courriel.", "HKLM\\Software\\Clients\\Mail has no default")
        try:
            code = self._api(to, subject, body, bundle)
        except OSError as exc:
            raise SupportSendError("support_mapi_unavailable", "La messagerie n'a pas pu être ouverte.",
                                   f"{type(exc).__name__}: {exc}") from exc
        if code == 0:
            return SendOutcome("draft_opened", f"Brouillon ouvert dans {client} avec le paquet en pièce jointe : "
                                               "relisez-le puis envoyez-le depuis votre messagerie.")
        if code == MAPI_USER_ABORT:
            raise SupportSendError("support_send_cancelled", "Brouillon fermé sans envoi.", "MAPI_USER_ABORT")
        raise SupportSendError("support_mapi_failed", f"La messagerie {client} a refusé le brouillon.",
                               f"MAPISendMail = {code} ({MAPI_ERRORS.get(code, 'unknown')})")


def default_mail_client() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Clients\Mail") as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue  # intentional: no declaration in this hive, try the next one
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


MAPI_USER_ABORT = 1
MAPI_ERRORS = {1: "MAPI_USER_ABORT", 2: "MAPI_E_FAILURE", 3: "MAPI_E_LOGIN_FAILURE", 5: "MAPI_E_INSUFFICIENT_MEMORY",
               10: "MAPI_E_UNKNOWN_FLAGS", 11: "MAPI_E_ATTACHMENT_OPEN_FAILURE", 14: "MAPI_E_TOO_MANY_RECIPIENTS",
               15: "MAPI_E_ATTACHMENT_NOT_FOUND", 21: "MAPI_E_UNKNOWN_RECIPIENT", 25: "MAPI_E_BAD_RECIPTYPE",
               26: "MAPI_E_NOT_SUPPORTED"}
MAPI_LOGON_UI, MAPI_DIALOG, MAPI_DIALOG_MODELESS = 0x1, 0x8, 0x4


def _mapi_send_mail(to: str, subject: str, body: str, path: Path) -> int:  # pragma: no cover - real mail client: HV check
    """`MAPISendMailW` (Windows 8+) : fenêtre de rédaction, sans fenêtre parente. Non modale si la messagerie le
    permet (`MAPI_DIALOG_MODELESS`), sinon modale (l'appel attend que l'utilisateur ferme le brouillon)."""

    import ctypes
    from ctypes import wintypes

    class RecipDesc(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("ulRecipClass", wintypes.ULONG), ("lpszName", wintypes.LPWSTR),
                    ("lpszAddress", wintypes.LPWSTR), ("ulEIDSize", wintypes.ULONG), ("lpEntryID", ctypes.c_void_p)]

    class FileDesc(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("flFlags", wintypes.ULONG), ("nPosition", wintypes.ULONG),
                    ("lpszPathName", wintypes.LPWSTR), ("lpszFileName", wintypes.LPWSTR), ("lpFileType", ctypes.c_void_p)]

    class Message(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("lpszSubject", wintypes.LPWSTR), ("lpszNoteText", wintypes.LPWSTR),
                    ("lpszMessageType", wintypes.LPWSTR), ("lpszDateReceived", wintypes.LPWSTR),
                    ("lpszConversationID", wintypes.LPWSTR), ("flFlags", wintypes.ULONG),
                    ("lpOriginator", ctypes.POINTER(RecipDesc)), ("nRecipCount", wintypes.ULONG),
                    ("lpRecips", ctypes.POINTER(RecipDesc)), ("nFileCount", wintypes.ULONG),
                    ("lpFiles", ctypes.POINTER(FileDesc))]

    mapi = ctypes.WinDLL("mapi32.dll")
    send = mapi.MAPISendMailW
    send.restype = wintypes.ULONG
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Message), wintypes.ULONG, wintypes.ULONG]
    recip = RecipDesc(0, 1, to, f"SMTP:{to}", 0, None)  # MAPI_TO
    attachment = FileDesc(0, 0, 0xFFFFFFFF, str(path), path.name, None)
    message = Message(0, subject, body, None, None, None, 0, None, 1, ctypes.pointer(recip), 1, ctypes.pointer(attachment))
    code = send(None, None, ctypes.byref(message), MAPI_LOGON_UI | MAPI_DIALOG | MAPI_DIALOG_MODELESS, 0)
    if code == 10:  # MAPI_E_UNKNOWN_FLAGS: this client has no modeless compose window
        code = send(None, None, ctypes.byref(message), MAPI_LOGON_UI | MAPI_DIALOG, 0)
    return int(code)


def transport_from_environment(environ: Mapping[str, str], *, runtime_root: Path) -> SupportTransport:
    """Le transport configuré (`JARVIS_SUPPORT_TRANSPORT`) ; une valeur inconnue vaut `none` (dit par `name`)."""

    choice = str(environ.get(TRANSPORT_ENV) or ("mapi" if sys.platform == "win32" else "none")).strip().lower()
    if choice == "mapi":
        return MapiTransport()
    if choice == "outbox":
        return OutboxTransport(runtime_root / "support" / OUTBOX_DIR)
    return NoTransport()


def describe_transport(transport: SupportTransport) -> dict[str, Any]:
    """Pour l'aperçu : nom, disponibilité, et la phrase qui dit ce que « Envoyer » fera."""

    describe = getattr(transport, "describe", None)
    if callable(describe):
        return dict(describe())
    if transport.name == "mapi":
        client = default_mail_client()
        return {"name": "mapi", "available": bool(client), "client": client,
                "label": f"un brouillon s'ouvre dans {client}, à relire puis envoyer" if client
                else "aucune messagerie par défaut : enregistrez le paquet et joignez-le à un courriel"}
    if transport.name == "outbox":
        return {"name": "outbox", "available": True, "label": "boîte d'envoi de test locale (rien ne quitte ce poste)"}
    return {"name": transport.name, "available": False, "label": "aucun moyen d'envoi configuré : enregistrez le paquet"}


__all__ = ["DEFAULT_SUPPORT_EMAIL", "MAX_SEND_BYTES", "MapiTransport", "NoTransport", "OutboxTransport", "SendOutcome",
           "SupportSendError", "SupportTransport", "describe_transport", "mail_text", "resolve_destination",
           "transport_from_environment", "valid_email"]
