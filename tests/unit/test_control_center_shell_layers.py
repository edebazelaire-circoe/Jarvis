"""Coque du Control Center : registre d'empilement, zones, jetons, commandes.

Contrat : `docs/control-center-shell.md` (handoff
`jarvis-board-orbital-ui-workspace-rail`, Slice 01). Ce fichier lit les
**vraies** feuilles — la page `control_center.html`, le `STYLE` du thème Cosmos
de `control_center_work.js` et la feuille de chaque module `control_center*.js`
— et les compare aux tableaux du document. Un `z-index` sans sa ligne, une
ligne sans son `z-index`, un rang propre au thème Cosmos, un jeton redéfini,
une commande de la page non mesurée par la scène : chacun fait échouer un test
qui le nomme.

La géométrie calculée (aucune commande ne se recouvre, la scène s'arrête contre
chacune) est vérifiée dans Chrome par la validation de la Slice 01 ; ce fichier
tient la partie statique, qui ne dépend d'aucun navigateur.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    CAPTURE_RAIL_SCRIPT_MARKER,
    ControlCenter,
    SCENE_PAGE_SCRIPT_MARKER,
    SHELL_SCRIPT_FILE,
    SHELL_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE_HTML = RUNTIME / "control_center.html"
WORK_JS = RUNTIME / "control_center_work.js"
SHELL_JS = RUNTIME / SHELL_SCRIPT_FILE
SHELL_DOC = ROOT / "docs" / "control-center-shell.md"

COSMOS = 'html[data-jarvis-theme="cosmos"]'
#: Surfaces de la coque dont un thème ne peut pas changer la place ni le rang.
SHELL_SURFACES = (
    ".topbar", ".state", "#boardsHud", ".dock", ".bgpills", "#bgPills", ".panel", ".live-banner",
    ".voicehint", ".chat-tab", ".board-drop-tray", "#boardsPanel", ".toasts", "#toolWheel",
    "#interactionModeHud", "#barehandsHud", "#barehandsPalette", "#captureRail", "#presentationRail",
)
GEOMETRY_PROPERTIES = (
    "position", "top", "right", "bottom", "left", "inset", "z-index", "transform", "width",
    "max-width", "flex-direction", "flex-wrap",
)


# ------------------------------------------------------------ lecture des feuilles

#: Commentaire CSS ou JS bloc. Le garde-fou `(?<![\w'"*/])` évite d'ouvrir un
#: « commentaire » dans une chaîne comme `'image/*'`.
_COMMENT = re.compile(r"(?<![\w'\"*/])/\*.*?\*/", re.S)
_OPEN, _CLOSE = "⟪", "⟫"


def _style_text(html: str) -> str:
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S))


def _sheet_source(path: Path) -> str:
    """Texte d'une feuille, interpolations `${…}` masquées pour que leurs
    accolades ne passent pas pour des blocs CSS, commentaires retirés."""

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = _style_text(text)
    text = re.sub(r"\$\{([^{}]*)\}", lambda m: _OPEN + m.group(1) + _CLOSE, text)
    return _COMMENT.sub("", text)


def _unmask(text: str) -> str:
    return text.replace(_OPEN, "${").replace(_CLOSE, "}")


def _sheets() -> list[Path]:
    return sorted(RUNTIME.glob("control_center*.js")) + [PAGE_HTML]


def z_rules(path: Path) -> list[tuple[str, str]]:
    """Chaque `z-index` de la feuille : (règle telle qu'écrite, valeur)."""

    source = _sheet_source(path)
    found = []
    for match in re.finditer(r"z-index:\s*([^;}\s!]+)", source):
        opening = source.rfind("{", 0, match.start())
        boundary = max(source.rfind(char, 0, opening) for char in "{}`")
        selector = " ".join(source[boundary + 1:opening].split())
        found.append((_unmask(selector), _unmask(match.group(1))))
    return found


def css_rules(css: str, context: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str, str]]:
    """Règles feuilles (contexte @media, sélecteur, corps) d'un texte CSS sans
    commentaires. `@keyframes` et `@property` sont ignorés."""

    rules = []
    depth, start, prelude_end = 0, 0, 0
    for index, char in enumerate(css):
        if char == "{":
            if depth == 0:
                prelude_end = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                prelude = " ".join(css[start:prelude_end].split())
                content = css[prelude_end + 1:index]
                if prelude.startswith(("@media", "@supports")):
                    rules += css_rules(content, context + (prelude,))
                elif not prelude.startswith("@"):
                    rules.append((context, prelude, content))
                start = index + 1
    return rules


def declarations(body: str) -> dict[str, str]:
    out = {}
    for part in body.split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            out[name.strip()] = value.strip()
    return out


def page_css() -> str:
    return _COMMENT.sub("", _style_text(PAGE_HTML.read_text(encoding="utf-8")))


def cosmos_style() -> str:
    work = WORK_JS.read_text(encoding="utf-8")
    return _COMMENT.sub("", re.search(r"const STYLE=`(.*?)`;", work, re.S).group(1))


# ------------------------------------------------------------ lecture du document


def _doc_section(title: str) -> str:
    doc = SHELL_DOC.read_text(encoding="utf-8")
    start = doc.index(f"### {title}\n")
    end = doc.find("\n### ", start + 1)
    nxt = doc.find("\n## ", start + 1)
    end = min(x for x in (end, nxt, len(doc)) if x != -1)
    return doc[start:end]


def _table(section: str) -> list[list[str]]:
    rows = []
    for line in section.splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", " "}:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        rows.append([cell[1:-1] if cell.startswith("`") and cell.endswith("`") else cell for cell in cells])
    return rows[1:]  # sans l'en-tête


def page_layers() -> list[dict]:
    return [
        {"rank": int(rank), "surface": surface, "sheet": sheet, "rule": rule}
        for rank, surface, sheet, rule, _why in _table(_doc_section("Page layers"))
    ]


def contained_ranks() -> list[dict]:
    return [
        {"container": container, "sheet": sheet, "prefix": prefix}
        for container, sheet, prefix, _why in _table(_doc_section("Contained ranks"))
    ]


def rank_of(surface: str) -> int:
    ranks = {row["rank"] for row in page_layers() if row["surface"] == surface}
    assert len(ranks) == 1, (surface, ranks)
    return ranks.pop()


def shell_module() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = f"process.stdout.write(JSON.stringify(require({json.dumps(str(SHELL_JS))})))"
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------ registre


def test_every_rank_in_css_matches_the_registry():
    layers = page_layers()
    contained = contained_ranks()
    seen = set()
    stray = []
    for path in _sheets():
        for rule, value in z_rules(path):
            row = next((
                index for index, layer in enumerate(layers)
                if layer["sheet"] == path.name and layer["rule"] == rule
            ), None)
            if row is not None:
                assert str(layers[row]["rank"]) == value, (path.name, rule, value, layers[row]["rank"])
                seen.add(row)
                continue
            if any(c["sheet"] == path.name and rule.startswith(c["prefix"]) for c in contained):
                continue
            stray.append((path.name, rule, value))
    assert not stray, f"z-index sans ligne au registre de docs/control-center-shell.md : {stray}"
    unused = [layers[i] for i in range(len(layers)) if i not in seen]
    assert not unused, f"lignes du registre qu'aucune feuille ne déclare : {unused}"


def test_registry_lists_chat_drop_and_rail_dialog_ranks():
    ranks = {(row["sheet"], row["rule"]): row["rank"] for row in page_layers()}
    html = "control_center.html"
    rail = "control_center_presentation_rail.js"
    assert ranks[(html, ".chat-tab")] == 32
    assert ranks[(html, ".panel")] == 33  # `#chatPanel` est un `.panel`
    assert ranks[(html, ".board-drop::before")] == 21
    assert ranks[(html, ".board-drop-card")] == 34
    assert ranks[(html, ".board-drop-tray")] == 34
    assert ranks[(rail, "#${DOM.hostId}")] == 30
    assert ranks[(rail, "html.jvr-studio #${DOM.hostId}")] == 9100
    assert ranks[(rail, ".jvr-menu")] == 9300
    assert ranks[(rail, ".jvr-dialog-back")] == 9400
    assert ranks[(html, "#toolWheel")] == 30
    # Pas de rang « arbitrairement énorme » hors de ceux qui le sont par contrat
    # (Studio, flux Bare Hands, pointeur Bare Hands).
    for row in page_layers():
        assert row["rank"] <= 100 or row["rank"] >= 9000, row


def test_relative_order_of_the_old_registry_is_kept():
    scene = rank_of("#sceneLayer")
    assert scene == 20
    assert rank_of(".face") < scene and rank_of("#cosmosFace") < scene
    contained_only = {".face", "#cosmosFace", "#sceneLayer"}
    for row in page_layers():
        if row["surface"] not in contained_only:
            assert row["rank"] > scene, row
    assert rank_of(".topbar") <= rank_of(".dock") < rank_of(".panel") < rank_of(".live-banner") < rank_of("#boardsPanel")
    assert rank_of("#boardsPanel") < rank_of("#bgPills") < rank_of(".toasts") < rank_of(".cdialog-back")
    # Les sélecteurs (Board, mode, cycle Bare Hands) au rang commun, au-dessus du bandeau.
    for chooser in ("#boardsPanel", ".bh-hud-pop", ".im-pop"):
        assert rank_of(chooser) == 36 and rank_of(".live-banner") < rank_of(chooser) < rank_of("#bgPills")
    assert rank_of("#barehandsPalette") < rank_of("#barehandsHud") < rank_of(".bh-hud-pop")
    assert rank_of("#captureRail") == rank_of("#barehandsPalette")
    assert rank_of(".ctxmenu") < rank_of("#barehandsCards") < rank_of(".cdialog-back")
    views = {rank_of(view) for view in (".tl", ".tlab", ".mcpi", ".wsp", ".pfb")}
    assert len(views) == 1
    view = views.pop()
    for control in (".dock", ".panel", ".live-banner", "#bgPills", "#boardsPanel", "#chatTab"):
        assert rank_of(control) < view, control
    assert view < rank_of(".overlay") < rank_of(".toasts") < rank_of(".ctxmenu") < rank_of(".cdialog-back")
    assert (rank_of("#jvStudioExplorer") < rank_of("html.jvr-studio #presentationRail")
            < rank_of("html.jvx-run #interactionModeHud") < rank_of(".jvr-menu") < rank_of(".jvr-dialog-back"))
    assert max(row["rank"] for row in page_layers()) == rank_of("#jarvisHands") == 2147483000


def test_cosmos_overrides_no_shell_position_or_rank():
    offenders = []
    sources = [("control_center_work.js", rule) for rule in css_rules(cosmos_style())]
    sources += [("control_center.html", rule) for rule in css_rules(page_css()) if COSMOS in rule[1]]
    for sheet, (context, selector, body) in sources:
        for part in selector.split(","):
            if COSMOS not in part:
                continue
            subject = re.split(r"\s*[>+~]\s*|\s+", part.strip())[-1]
            if not any(re.search(re.escape(surface) + r"(?![\w-])", subject) for surface in SHELL_SURFACES):
                continue
            bad = sorted(set(declarations(body)) & set(GEOMETRY_PROPERTIES))
            if bad:
                offenders.append((sheet, context, part.strip(), bad))
    assert not offenders, f"le thème Cosmos place ou classe une surface de la coque : {offenders}"


def test_html_mirror_matches_the_registry():
    head = PAGE_HTML.read_text(encoding="utf-8").split("</style>", 1)[0]
    mirror = set()
    for rank, surfaces in re.findall(r"@shell-layer (\d+): ([^\n*]+)", head):
        for surface in surfaces.split(","):
            mirror.add((int(rank), surface.strip()))
    registry = {(row["rank"], row["surface"]) for row in page_layers()}
    assert mirror == registry, {"absents du miroir": registry - mirror, "en trop": mirror - registry}
    assert "docs/control-center-shell.md" in head


# ------------------------------------------------------------ commandes de la page


def _tags(html: str) -> list[dict[str, str]]:
    body = html.split("<body>", 1)[1].split("<script>", 1)[0]
    tags = []
    for match in re.finditer(r"<([a-zA-Z][\w-]*)((?:\s+[^\s>=]+(?:=\"[^\"]*\")?)*)\s*/?>", body):
        attrs = dict(
            (name, value or "")
            for name, value in re.findall(r"([^\s=]+)(?:=\"([^\"]*)\")?", match.group(2))
        )
        attrs["<tag>"] = match.group(1)
        tags.append(attrs)
    return tags


def _matches(tag: dict[str, str], selector: str) -> bool:
    simple = selector.split(">")[-1]
    if simple.startswith("#"):
        return tag.get("id") == simple[1:]
    return simple[1:] in tag.get("class", "").split()


def test_every_declared_control_host_matches_control_selector():
    shell = shell_module()
    attribute = shell["CONTROL_ATTRIBUTE"]
    assert shell["CONTROL_SELECTOR"] == f"[{attribute}],#sceneLayer>.sc-status"
    tags = _tags(PAGE_HTML.read_text(encoding="utf-8"))
    hosts = shell["CONTROL_HOSTS"]
    for host in hosts:
        found = [tag for tag in tags if _matches(tag, host["selector"])]
        if host.get("slice") or host.get("createdBy"):
            assert not found or all(attribute in tag for tag in found), host
            continue
        assert len(found) == 1, (host, len(found))
        assert attribute in found[0], f"{host['selector']} n'est pas mesuré par la scène"
    marked = [tag for tag in tags if attribute in tag]
    for tag in marked:
        assert any(_matches(tag, host["selector"]) for host in hosts), f"commande hors contrat : {tag}"
    # Le rail des présentations crée son hôte : il y pose l'attribut lui-même.
    rail = (RUNTIME / "control_center_presentation_rail.js").read_text(encoding="utf-8")
    assert "setAttribute('data-shell-control','')" in rail
    # Les surfaces qui manquaient à l'ancienne liste de la scène sont mesurées.
    selectors = {host["selector"] for host in hosts}
    assert {"#interactionModeHud", "#chatTab", "#presentationRail", "#boardDropTray", "#toolWheel"} <= selectors
    # L'hôte de la roue est déclaré vide (aucun comportement avant la Slice 02).
    assert re.search(r'<div id="toolWheel" data-shell-control hidden></div>', PAGE_HTML.read_text(encoding="utf-8"))


def test_scene_and_capture_rail_read_the_shared_selector():
    shell = shell_module()
    scene = (RUNTIME / "control_center_scene_page.js").read_text(encoding="utf-8")
    rail = (RUNTIME / "control_center_capture_rail.js").read_text(encoding="utf-8")
    for source in (scene, rail):
        fallback = re.search(r"const SHELL_FALLBACK_SELECTOR='([^']+)'", source).group(1)
        assert fallback == shell["CONTROL_SELECTOR"]
        assert "JarvisShell" in source and "shell.missing" in source
    assert "const CONTROL_SELECTOR='" not in scene
    assert "const OBSTACLE_SELECTOR='" not in rail


async def test_the_shell_module_is_served_before_its_readers(tmp_path):
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert html.index(SHELL_SCRIPT_MARKER) < html.index(CAPTURE_RAIL_SCRIPT_MARKER)
    assert html.index(SHELL_SCRIPT_MARKER) < html.index(SCENE_PAGE_SCRIPT_MARKER)
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert SHELL_SCRIPT_MARKER not in served
    assert SHELL_JS.read_text(encoding="utf-8") in served


# ------------------------------------------------------------ jetons


def test_tokens_defined_once_and_reduced_motion_zeroes_durations():
    shell = shell_module()
    rules = css_rules(page_css())
    base = [declarations(body) for context, selector, body in rules if not context and selector == ":root"]
    defined: dict[str, list[str]] = {}
    for decl in base:
        for name, value in decl.items():
            if name.startswith(("--shell-", "--sem-")):
                defined.setdefault(name, []).append(value)
    assert {name: values for name, values in defined.items() if len(values) > 1} == {}
    assert {name: values[0] for name, values in defined.items()} == shell["TOKENS"]
    # Les redéfinitions responsives : exactement celles du contrat.
    responsive: dict[str, dict[str, str]] = {}
    reduced: dict[str, str] = {}
    for context, selector, body in rules:
        if not context or selector != ":root":
            continue
        shell_decl = {k: v for k, v in declarations(body).items() if k.startswith(("--shell-", "--sem-"))}
        if not shell_decl:
            continue
        media = context[-1]
        if "prefers-reduced-motion:reduce" in media.replace(" ", ""):
            reduced.update(shell_decl)
            continue
        width = re.search(r"max-width:\s*(\d+px)", media)
        assert width and len(context) == 1, (context, shell_decl)
        responsive.setdefault(f"max-width:{width.group(1)}", {}).update(shell_decl)
    assert responsive == shell["RESPONSIVE_TOKENS"]
    assert reduced == {name: "0ms" for name in shell["MOTION_TOKENS"]}
    # Aucun thème ni module ne redéfinit un jeton de la coque.
    for path in _sheets():
        if path == PAGE_HTML:
            continue
        source = _sheet_source(path)
        assert not re.search(r"--(?:shell|sem)-[\w-]+\s*:", source), path.name
    # Mouvement réduit et couleurs forcées : la règle de la coque existe.
    css = page_css()
    assert re.search(r":where\(\[data-shell-control\]\)[^{]*:focus-visible\{outline:var\(--shell-focus-w\) solid var\(--shell-focus\)", css)
    assert "@media(forced-colors:active)" in css
