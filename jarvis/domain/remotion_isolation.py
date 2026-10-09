"""Gardes statiques d'une source Remotion non fiable (handoff jarvis-remotion-presentation-integration, Slice 06 ;
contrat `docs/remotion-isolation.md`).

Le code d'une scène (TSX/JS écrit par un agent ou importé d'un modèle) est **hostile par défaut**. La frontière de
sécurité est le bac à sable du navigateur (iframe `sandbox`, origine dédiée, CSP : `jarvis.domain.remotion_sandbox`) ;
ce module est la **première couche**, un filtre statique qui refuse tôt, avec un message utile, ce qu'une scène honnête
n'a aucune raison d'écrire. Il ne prétend pas être complet : un contenu qui l'évite (chaîne reconstruite, accès indirect)
est arrêté par la couche d'exécution, éprouvée séparément (`scripts/remotion_isolation_harness.py`).

Pur : aucune E/S. Branché dans `jarvis.domain.remotion_source.SOURCE_GUARDS`, donc appliqué à la publication **et** à
chaque relecture d'une version (`PrefabService.remotion_source`) : une version publiée avant une garde est refusée en
`invalid_definition` à la relecture, sans être réécrite (la source reste lisible pour le diagnostic).

Deux familles : le **texte des modules** (`scan_module`) et les **assets** (`scan_asset` : signature binaire, contenu actif
des SVG). Les modules sont analysés sur le texte brut, sans lexeur (un lexeur approximatif de JavaScript est lui-même
contournable) : une règle ne vise donc que des formes de code (`nom.`, `nom[`, `nom(`, valeur passée), pas le mot isolé,
pour ne pas refuser un titre de diapositive qui contient « document » ou « parent ».
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typage seulement (remotion_source importe ce module)
    from jarvis.domain.remotion_source import RemotionSource

#: Une ligne plus longue qu'ici n'est pas du code écrit pour être lu : refusée avant toute expression régulière.
MAX_LINE_CHARS = 50_000
#: Au plus ce nombre de constats par fichier (le reste est tu : le premier suffit à corriger).
MAX_FINDINGS_PER_FILE = 5

_NAME_END = r"(?![\w$])"
_BEFORE = r"(?<![\w$.])"

#: Noms du « monde » de la page : les atteindre, c'est atteindre le Control Center, le stockage ou le réseau.
_REALM = ("window", "globalThis", "self", "document", "parent", "top", "opener", "navigator", "location", "history",
          "localStorage", "sessionStorage", "indexedDB", "caches", "cookieStore")
_REALM_ALT = "|".join(_REALM)
#: Passés comme valeur : seulement les noms que personne ne nomme une variable locale (`top`, `parent`... le peuvent).
_REALM_VALUE_ALT = "window|globalThis|self|document|opener|navigator|localStorage|sessionStorage|indexedDB|caches|cookieStore"
_NETWORK = ("fetch", "XMLHttpRequest", "WebSocket", "WebTransport", "EventSource", "RTCPeerConnection", "sendBeacon")
_WORKERS = ("Worker", "SharedWorker", "ServiceWorker", "serviceWorker", "Worklet", "importScripts", "MessageChannel",
            "BroadcastChannel", "postMessage", "showOpenFilePicker", "showSaveFilePicker", "showDirectoryPicker")
_TAGS = "script|iframe|frame|frameset|embed|object|applet|link|meta|base"


@dataclass(frozen=True, slots=True)
class Rule:
    """Une règle de refus : `code` stable (testé et cité dans la doc), motif, explication d'une phrase."""

    code: str
    pattern: re.Pattern[str]
    why: str


def _rule(code: str, pattern: str, why: str, flags: int = 0) -> Rule:
    return Rule(code, re.compile(pattern, flags), why)


MODULE_RULES: tuple[Rule, ...] = (
    _rule("network_api", rf"{_BEFORE}(?:{'|'.join(_NETWORK)}){_NAME_END}(?=\s*[(.,;=)\]}}]|\s*$)|\.\s*sendBeacon\s*\(",
          "network APIs are forbidden: a scene has no network (read assets with staticFile)", re.M),
    _rule("code_execution", rf"{_BEFORE}(?:eval|Function|execScript){_NAME_END}(?=\s*[(.,;=)\]}}]|\s*$)",
          "eval/Function turn text into code and are forbidden", re.M),
    _rule("constructor_chain", r"\.\s*constructor\s*(?:\.\s*constructor|\()|\[\s*[\"'`]constructor[\"'`]\s*\]",
          "reaching the Function constructor through .constructor is forbidden"),
    _rule("dynamic_import", r"(?<![\w$.])import\s*\(|(?<![\w$.])require\s*\(|\bimport\.meta\b",
          "dynamic import()/require() is forbidden: only static relative imports and react/remotion are allowed"),
    _rule("string_timer", r"(?<![\w$.])(?:setTimeout|setInterval|setImmediate)\s*\(\s*[\"'`]",
          "a timer given a string runs it as code; pass a function"),
    _rule("worker_or_channel", rf"{_BEFORE}(?:{'|'.join(_WORKERS)}){_NAME_END}(?=\s*[(.,;=)\]}}]|\s*$)|\.\s*postMessage\s*\(",
          "workers, channels and postMessage are forbidden: the host owns the message channel", re.M),
    _rule("realm_access", rf"(?<![\w$.\-])(?:{_REALM_ALT})(?:\s*\??\.[A-Za-z_$]|\s*\[)",
          "window/document/parent/top/location/storage access is forbidden: use remotion hooks (useVideoConfig...) and inputProps"),
    _rule("realm_value", rf"[(,=\[:?&|]\s*(?:{_REALM_VALUE_ALT})\s*[),;\]}}]",
          "passing window/document/parent/top/location around as a value is forbidden"),
    _rule("realm_property", r"\.\s*(?:cookie|opener|contentWindow|contentDocument|defaultView|ownerDocument)\b(?!\s*:)",
          "cookie/opener/contentWindow access is forbidden"),
    _rule("popup_or_dialog", r"(?<![\w$.])(?:open|alert|confirm|prompt)\s*\(",
          "open()/alert()/prompt() are forbidden: a scene opens no window and asks nothing"),
    _rule("markup_tag", rf"(?<![\w$])<\s*(?:{_TAGS})(?=[\s/>])|createElement(?:NS)?\s*\([^)]*[\"'`](?:{_TAGS})[\"'`]",
          "script/iframe/object/embed/link/meta/base elements are forbidden", re.I),
    _rule("srcdoc", r"\bsrcDoc\b|\bsrcdoc\b", "srcdoc frames are forbidden"),
    _rule("inline_handler_string", r"\bon(?:click|dblclick|load|error|mouse\w*|focus\w*|blur|key\w*|submit|change|input|toggle|animation\w*|transition\w*"
                                  r"|begin|end|pointer\w*|touch\w*|drag\w*|drop|wheel|scroll|message|abort|resize|select|unload|popstate"
                                  r"|hashchange|pageshow)\s*=\s*\?[\"'`]",
          "string event-handler attributes are forbidden (pass a function)", re.I),
    _rule("active_url_scheme", r"(?:javascript|vbscript)\s*:|data\s*:\s*(?:text/html|application/xhtml|image/svg)",
          "javascript:, vbscript: and data: HTML/SVG URLs are forbidden", re.I),
    _rule("external_resource", r"\b(?:src|href|poster|xlinkHref|action|formAction|data)\s*[=:]\s*\{?\s*[\"'`]\s*(?:https?:)?//"
                               r"|url\(\s*[\"']?\s*(?:https?:)?//|@import\b",
          "external resources are forbidden: put the file in public/ and read it with staticFile()", re.I),
    _rule("obfuscated_name", r"\[\s*([\"'`])[^\"'`\n\]]*\1\s*\+\s*[\"'`]|(?<![\w$.])atob\s*\(",
          "building a property name from two string literals (or atob) is forbidden"),
    _rule("unbounded_loop", r"\bwhile\s*\(\s*(?:true|1|!0|!false)\s*\)|\bfor\s*\(\s*;\s*;\s*\)|\bdo\s*\{[^}]*\}\s*while\s*\(\s*(?:true|1)\s*\)",
          "unbounded loops are forbidden: animate from the frame number, never from a loop"),
)

_MODULE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def scan_module(path: str, text: str) -> list[str]:
    """Constats pour un module `src/**` : `chemin:ligne: règle - explication`. `.json` n'est jamais exécuté."""

    if not path.endswith(_MODULE_SUFFIXES):
        return []
    longest = max((len(line) for line in text.split("\n")), default=0)
    if longest > MAX_LINE_CHARS:
        return [f"{path}: a line has {longest} characters, at most {MAX_LINE_CHARS} (minified or generated code is refused)"]
    findings: list[str] = []
    for rule in MODULE_RULES:
        match = rule.pattern.search(text)
        if match:
            findings.append(f"{path}:{_line_of(text, match.start())}: {rule.code} - {rule.why}")
            if len(findings) >= MAX_FINDINGS_PER_FILE:
                break
    return findings


# ------------------------------------------------------------------ assets

def _riff(kind: bytes) -> Callable[[bytes], bool]:
    return lambda b: b[:4] == b"RIFF" and b[8:12] == kind


#: Signature attendue par extension : un fichier `.png` qui est du HTML est refusé (le service pose aussi `nosniff`).
ASSET_SIGNATURES: dict[str, Callable[[bytes], bool]] = {
    ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".gif": lambda b: b[:6] in (b"GIF87a", b"GIF89a"),
    ".webp": _riff(b"WEBP"),
    ".woff": lambda b: b.startswith(b"wOFF"),
    ".woff2": lambda b: b.startswith(b"wOF2"),
    ".ttf": lambda b: b[:4] in (b"\x00\x01\x00\x00", b"true", b"ttcf"),
    ".otf": lambda b: b.startswith(b"OTTO"),
    ".mp3": lambda b: b.startswith(b"ID3") or (len(b) > 1 and b[0] == 0xFF and b[1] & 0xE0 == 0xE0),
    ".wav": _riff(b"WAVE"),
    ".ogg": lambda b: b.startswith(b"OggS"),
    ".mp4": lambda b: b[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide"),
    ".webm": lambda b: b.startswith(b"\x1a\x45\xdf\xa3"),
}

#: Contenu actif d'un SVG : refusé (jamais « nettoyé » : une version publiée ne se réécrit pas, l'agent corrige).
SVG_RULES: tuple[Rule, ...] = (
    _rule("svg_script", r"<\s*script\b", "SVG <script> is forbidden", re.I),
    _rule("svg_foreign_content", r"<\s*(?:foreignObject|iframe|embed|object|audio|video|canvas|link|meta|handler|listener)\b",
          "SVG foreign/embedded content is forbidden", re.I),
    _rule("svg_event_handler", r"[\s\"'/]on[a-z]{3,}\s*=", "SVG event-handler attributes are forbidden", re.I),
    _rule("svg_active_url", r"(?:javascript|vbscript)\s*:|data\s*:\s*(?:text/html|application/xhtml|image/svg)",
          "javascript:/vbscript: and data: HTML/SVG URLs are forbidden in an SVG", re.I),
    _rule("svg_entity", r"<!\s*(?:ENTITY|DOCTYPE[^>]*\[)", "SVG entity declarations are forbidden", re.I),
    _rule("svg_external_reference", r"(?:xlink:)?href\s*=\s*[\"']\s*(?!#|data:image/(?:png|jpe?g|gif|webp);base64,)(?:[a-z][a-z0-9+.\-]*:|//)",
          "SVG references must be #fragments or embedded raster data: URLs", re.I),
    _rule("svg_css_url", r"url\(\s*[\"']?\s*(?!#|data:image/(?:png|jpe?g|gif|webp);base64,)(?:[a-z][a-z0-9+.\-]*:|//)|@import\b",
          "SVG CSS must not load external resources", re.I),
    _rule("svg_smil_script", r"attributeName\s*=\s*[\"']?\s*(?:xlink:)?(?:href|on[a-z]+)", "SVG animation of href/on* is forbidden", re.I),
)


def scan_asset(path: str, data: bytes) -> list[str]:
    """Constats pour un asset `public/**` : signature binaire, puis contenu actif d'un SVG."""

    extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if extension == ".svg":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return [f"{path}: svg_not_text - an SVG must be UTF-8 text"]
        if "<svg" not in text[:4096].lower():
            return [f"{path}: svg_not_svg - the file has no <svg> root"]
        found = [f"{path}:{_line_of(text, m.start())}: {rule.code} - {rule.why}"
                 for rule in SVG_RULES if (m := rule.pattern.search(text))]
        return found[:MAX_FINDINGS_PER_FILE]
    check = ASSET_SIGNATURES.get(extension)
    if check is not None and not check(data[:16]):
        return [f"{path}: asset_signature - the content is not a valid {extension} file (its header does not match the extension)"]
    return []


def isolation_guard(source: "RemotionSource") -> Iterable[str]:
    """Garde posée dans `SOURCE_GUARDS` : tous les constats de la source (modules puis assets), sans effet de bord."""

    findings: list[str] = []
    for path in source.block.modules:
        findings.extend(scan_module(path, source.files[path].decode("utf-8")))
    for path in source.block.assets:
        findings.extend(scan_asset(path, source.files[path]))
    return findings
