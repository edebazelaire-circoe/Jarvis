"""Banc des preuves navigateur de l'explorateur de variantes (jarvis-interactive-presentation-studio, Slice 18).

Rien n'est simulé sauf l'écran sans tête : un VRAI Core (`JarvisCoreApplication` derrière le vrai `LocalProtocolServer`, racine de données et ports
à lui, jamais le Jarvis vivant), le VRAI Control Center qui sert la page et relaie vers lui, un VRAI Chrome piloté par CDP
(`tests/unit/_presentation_studio_explorer_browser.mjs`). Le prefab des scènes est un prefab `custom` publié par la vraie route `POST /v1/prefabs`
(`lab.dial`). Les variantes sont créées par la vraie opération de Core (`POST .../variants`), les contenus et directions artistiques sont
modifiés par les vraies routes (édition sémantique, `PUT art-direction`) : l'arbre que la page lit est celui que la voix produirait.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.unit.test_fullscreen_browser import _chrome
from tests.unit.test_presentation_studio_routes import AUTH, Core, variant_body

HARNESS = Path(__file__).resolve().parents[1] / "unit" / "_presentation_studio_explorer_browser.mjs"
PREFAB_ID = "lab.dial"
S1, S2, S3 = "pss_0000000000e1", "pss_0000000000e2", "pss_0000000000e3"
PREVIEW_OBJECT = "studio-explorer-preview"

TEMPLATE = """<section id="dial" class="dial">
  <p class="eyebrow" data-jv-text="props.kicker"></p>
  <h2 data-jv-text="props.title"></h2>
  <div class="orb" aria-hidden="true"></div>
  <p class="body" data-jv-text="data.body"></p>
</section>
"""
STYLE = """html, body { margin: 0; padding: 0 !important; height: 100%; overflow: hidden; }
.dial { box-sizing: border-box; height: 100vh; display: grid; align-content: center; justify-items: start; gap: 14px; padding: 6vh 7vw;
  color: var(--jv-text); background: radial-gradient(120% 90% at 85% 10%, color-mix(in srgb, var(--jv-prop-accent, #6ee7ff) 30%, #05080b), #05080b 70%); }
.eyebrow { margin: 0; letter-spacing: .18em; text-transform: uppercase; font-size: 2.2vh; opacity: .75; }
h2 { margin: 0; font-size: 8vh; line-height: 1.05; max-width: 14ch; }
.orb { width: calc(14vh * var(--size, 1)); height: calc(14vh * var(--size, 1)); border-radius: 50%;
  background: linear-gradient(135deg, var(--jv-prop-accent, #6ee7ff), #a78bfa); box-shadow: 0 0 6vh color-mix(in srgb, var(--jv-prop-accent, #6ee7ff) 60%, transparent); }
.body { margin: 0; font-size: 3vh; opacity: .85; max-width: 32ch; }
"""
BEHAVIOR = """function paint() {
  var p = jarvis.props;
  document.documentElement.style.setProperty('--size', String(p.size === undefined ? 1 : p.size));
  document.documentElement.setAttribute('data-title', String(p.title || ''));
}
jarvis.on('init', paint);
jarvis.on('update', paint);
"""


def lab_manifest() -> dict:
    def prop(kind: str, description: str, **extra) -> dict:
        return {"type": kind, "description": description, **extra}

    return {
        "schema": "jarvis.prefab", "schema_version": 1, "id": PREFAB_ID, "version": 1, "title": "Cadran de laboratoire",
        "description": "Prefab de test de l'explorateur.", "family": "window", "tags": ["test", "explorateur"], "aliases": ["cadran"],
        "scene": {"kind": "window", "default_size": {"w": 40, "h": 24}},
        "inputs": {
            "props": {"type": "object", "properties": {
                "kicker": prop("string", "Le surtitre.", max_length=40, default=""),
                "title": prop("string", "Le titre.", max_length=60, default="Titre"),
                "accent": prop("color", "La couleur d'accent.", default="#6ee7ff"),
                "size": prop("number", "Taille de l'orbe.", min=0.5, max=2, default=1),
            }},
            "data": {"type": "object", "properties": {"body": prop("text", "Le texte courant.", max_length=200, default="")}},
        },
        "sample": {"props": {}, "data": {"body": "Exemple"}},
        "files": {"template": "template.html", "style": "style.css", "behavior": "behavior.js"},
    }


def _control(control_id: str, path: str, label: str, group: str, meaning: str, **bounds) -> dict:
    control = {"control_id": control_id, "path": path, "label": label, "group": group, "meaning": meaning}
    if bounds:
        control["bounds"] = bounds
    return control


CONTROLS = [
    _control("title", "props.title", "Titre", "content", "Le titre affiché en grand."),
    _control("kicker", "props.kicker", "Surtitre", "content", "Le surtitre."),
    _control("accent", "props.accent", "Couleur d'accent", "visual", "La couleur qui porte l'attention."),
    _control("size", "props.size", "Taille", "layout", "La taille de l'orbe.", min=0.6, max=1.8),
]


def scene_body(scene_id: str, title: str, kicker: str, body: str, *, section: str = "") -> dict:
    return {"scene_id": scene_id, "prefab": {"id": PREFAB_ID, "version": 1}, "title": title, "section": section,
            "props": {"kicker": kicker, "title": title, "accent": "#6ee7ff", "size": 1}, "data": {"body": body}, "controls": CONTROLS}


SCENES = [
    scene_body(S1, "Ouverture", "Cadran", "Un point de départ pour la discussion.", section="Début"),
    scene_body(S2, "Les chiffres", "Résultats", "Trois indicateurs, une seule histoire.", section="Corps"),
    scene_body(S3, "Conclusion", "Suite", "Ce que nous décidons aujourd'hui.", section="Fin"),
]

#: Le récit d'une présentation qui a évolué : (numéro, parent, titre, raison, accent). Le numéro 1 est la racine.
STORY = [
    (1, None, "Version initiale", "Premier jet, ton neutre.", "#6ee7ff"),
    (2, 1, "Ton sobre", "Moins d'effets, plus de blanc.", "#9fb4c7"),
    (3, 1, "Ton chaleureux", "Pour un public non technique.", "#ffb85c"),
    (4, 2, "Sobre, chiffres en tête", "Les chiffres avant le récit.", "#7fd1ae"),
    (5, 2, "Sobre, sans animation", "Version imprimable, aucun mouvement.", "#c4c9d4"),
    (6, 3, "Chaleureux, couleurs vives", "Test d'une palette saturée.", "#ff7a59"),
    (7, 6, "Couleurs vives, titre court", "Le titre tenait sur trois lignes.", "#ff5ca8"),
    (8, 3, "Chaleureux, récit client", "Histoire d'un client en ouverture.", "#e8c547"),
    (9, 8, "Récit client, version comité", "Même récit, plus de chiffres.", "#59d0ff"),
    (10, 1, "Contraste fort", "Pour la salle sans écran de bonne qualité.", "#f4f4f4"),
    (11, 10, "Contraste fort, sans dégradé", "Fond uni.", "#d6ff59"),
    (12, 1, "Piste vidéo", "Idée abandonnée à moitié : une séquence animée.", "#b388ff"),
]


class ExplorerRig:
    """`async with ExplorerRig(tmp_path) as rig` : Core + Control Center + une présentation de 3 scènes et 12 variantes (`rig.pid`, `rig.vids[n]`)."""

    def __init__(self, tmp_path: Path, *, variants: int | None = None, story: list | None = None) -> None:
        self.tmp_path = tmp_path
        self.core = Core(tmp_path)
        self.story = (story or STORY)[: variants] if variants else (story or STORY)
        self.vids: dict[int, str] = {}

    async def __aenter__(self) -> ExplorerRig:
        await self.core.__aenter__()
        stack = self.core.stack
        port = int(stack.core_url.rsplit(":", 1)[1])
        token_file = stack.tmp_path / "core.token"
        # What `jarvis/app.py` wires: the scene proxy (the page polls it) and the mode proxy (the HUD).
        stack.center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=port, token_file=token_file))
        stack.center.interaction_mode_view = CoreInteractionModeView(
            CoreInteractionModeTransport(host="127.0.0.1", port=port, token_file=token_file))
        await self.publish_prefab()
        self.pid = await self.new_presentation("Atelier du cadran")
        await self.grow(self.story)
        self.url = f"http://127.0.0.1:{stack.cc_port}/"
        return self

    async def __aexit__(self, *exc) -> None:
        await self.core.stack.center.scene_view.aclose()
        await self.core.__aexit__(*exc)

    @property
    def tree_dir(self) -> Path:
        """Toute la présentation sur disque : ce que « n'écrit rien » doit laisser identique."""

        return self.tmp_path / "data" / "presentations" / self.pid

    async def publish_prefab(self) -> None:
        candidate = {"manifest": lab_manifest(), "template": TEMPLATE, "style": STYLE, "behavior": BEHAVIOR}
        async with self.core.http.post(self.core.stack.core_url + "/v1/prefabs", headers=AUTH,
                                       json={"actor": "user", "candidate": candidate}) as response:
            body = await response.json(content_type=None)
            assert response.status == 201, body

    async def new_presentation(self, title: str) -> str:
        _, created = await self.core.call("POST", "", json={"title": title})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        vid = variant["variant_id"]
        status, saved = await self.core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, scenes=SCENES))
        assert status == 200, saved
        status, made = await self.core.call("POST", f"/{pid}/variants/{vid}/art-direction/fallback",
                                            json={"expected_variant_revision": saved["revision"]})
        assert status == 201, made
        self.vids[1] = vid
        return pid

    async def edit(self, vid: str, ops: list, *, actor: str = "brain") -> dict:
        _, variant = await self.core.call("GET", f"/{self.pid}/variants/{vid}")
        body = {"actor": actor, "mode": "commit", "basis": {"variant_revision": variant["revision"]}, "ops": ops}
        status, result = await self.core.call("POST", f"/{self.pid}/variants/{vid}/edits", json=body)
        assert status == 200 and result["status"] == "applied", result
        return result

    async def branch(self, parent: str, title: str, rationale: str = "", *, activate: bool = False, actor: str = "brain") -> dict:
        status, made = await self.core.call("POST", f"/{self.pid}/variants", json={
            "title": title, "rationale": rationale, "source_variant_id": parent, "activate": activate, "actor": actor})
        assert status == 201, made
        return made["node"]

    async def grow(self, story: list) -> None:
        """Les branches de `story`, dans l'ordre : une vraie création, puis un vrai réglage de contenu (titre et accent propres à la variante)."""

        for number, parent, title, rationale, accent in story:
            if parent is not None:
                node = await self.branch(self.vids[parent], title, rationale)
                assert node["variant_number"] == number, node
                self.vids[number] = node["variant_id"]
            await self.edit(self.vids[number], [
                {"op": "control.set", "scene_id": S1, "control_id": "title", "value": title[:60]},
                {"op": "control.set", "scene_id": S1, "control_id": "accent", "value": accent}])

    async def snapshot(self) -> dict:
        _, graph = await self.core.call("GET", f"/{self.pid}/graph?archived=1")
        return graph

    def variant_file(self, vid: str) -> Path:
        return self.tree_dir / "variants" / f"{vid}.json"


def drive_sync(url: str, plan: list, *, viewport: str = "1280x720", reduced_motion: bool = False, timeout: int = 300, ready: str | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    env = {**os.environ, "CDP_VIEWPORT": viewport}
    if reduced_motion:
        env["CDP_REDUCED_MOTION"] = "1"
    if ready:
        env["CDP_READY"] = ready
    done = subprocess.run([node, str(HARNESS), url, _chrome(), json.dumps(plan)], capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, check=False, env=env)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


async def drive(url: str, plan: list, **kwargs) -> dict:
    # The blocking subprocess runs in a thread so the event loop keeps serving Core and the Control Center.
    return await asyncio.to_thread(drive_sync, url, plan, **kwargs)
