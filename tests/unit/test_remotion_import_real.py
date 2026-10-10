"""Import RÉEL d'un modèle Remotion amont (Slice 18) : réseau GitHub, compilateur Node + esbuild, Player dans Chrome.

Opt-in, trois conditions : `JARVIS_REMOTION_IMPORT_NETWORK=1` (accès à codeload.github.com), `JARVIS_REMOTION_RUNTIME_DIR` (une
installation Remotion existante, jamais une de plus), Node et Chrome. Sans elles ces épreuves sont ignorées.

    JARVIS_REMOTION_IMPORT_NETWORK=1 python scripts/remotion_player_harness.py --test tests/unit/test_remotion_import_real.py \\
        --slice 18 --report real-import.json --runtime-dir <runtime/> --evidence <dossier de preuve>

Commits ÉPINGLÉS (jamais une branche) relevés le 2026-10-10 :

- `hongjiapeng/remotion-workflow-visualizer@730615b7` : MIT (fichier LICENSE), dépendances `remotion` + `react` : importable, compilé et
  joué ; propriétaire ajouté explicitement à la liste blanche (le réglage `remotion_import.allowed_owners`) ;
- `remotion-dev/template-empty@f9d71061`, `template-helloworld@04da7cc8` : `package.json` dit `UNLICENSED`, aucun fichier de licence,
  le README renvoie à la licence de Remotion : refusés `license_unlicensed` (la licence du moteur n'est pas celle du modèle) ;
- `remotion-dev/template-three@aa9cd28f` : fichier LICENSE = MIT mais `package.json` = `UNLICENSED` : l'auteur se contredit, `license_conflict` ;
- `remotion-dev/highlighter@c18ea3d4` : MIT mais dépend de `roughjs` / `@remotion/paths` : `dependency_refused` ;
- `lifeprompt-team/remotion-scenes@02c7a842` : MIT mais passe par `@remotion/google-fonts` : `dependency_refused`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

import pytest

from jarvis.adapters.https_upstream_fetcher import HttpsUpstreamFetcher
from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.core.remotion_import_service import RemotionImportService
from jarvis.domain.remotion_upstream import UpstreamRefusal
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.test_remotion_player_realpage_browser import SANDBOX, READY, record_evidence, run

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(
    os.environ.get("JARVIS_REMOTION_IMPORT_NETWORK") != "1" or RUNTIME is None or shutil.which("node") is None,
    reason="needs JARVIS_REMOTION_IMPORT_NETWORK=1, JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install) and node")

MIT_PROJECT = ("https://github.com/hongjiapeng/remotion-workflow-visualizer", "730615b75628acb2c22fcacd33e5b9c45f8eb010")
REFUSED = [
    ("https://github.com/remotion-dev/template-empty", "f9d71061a3c263bdcc01ac943fbc58fd51206d41", "license_unlicensed"),
    ("https://github.com/remotion-dev/template-helloworld", "04da7cc8402722a7c8fa496d810f0196fd092dd6", "license_unlicensed"),
    ("https://github.com/remotion-dev/template-three", "aa9cd28f063959547bb5fa5fd83208538cb5831b", "license_conflict"),
    ("https://github.com/remotion-dev/highlighter", "c18ea3d443a0f10028f46117bc7b14efb545a2e0", "dependency_refused"),
    ("https://github.com/lifeprompt-team/remotion-scenes", "02c7a84241da7010b5f59c420b0110aafd1d6f0d", "dependency_refused"),
]
#: Dépôts à plusieurs compositions : sans `composition_id` le plan le dit (refus typé) ; avec, il va jusqu'au vrai motif.
PICK = {"https://github.com/remotion-dev/highlighter": "Box", "https://github.com/lifeprompt-team/remotion-scenes": "TextShowcase"}
GIVEN = {"width": 1280, "height": 720, "fps": 30, "duration_in_frames": 300}
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


class AnyStudio:
    async def get(self, presentation_id):
        return object()


def service_for(prefabs, owners):
    return RemotionImportService(HttpsUpstreamFetcher(), prefabs, AnyStudio(), engine=shipped_engine_pin, allowed_owners=lambda: owners)


async def test_real_templates_from_github_are_refused_for_their_exact_reason(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        service = service_for(stack.core.prefabs, ("remotion-dev", "lifeprompt-team", "hongjiapeng"))
        outcome = []
        for url, sha, expected in REFUSED:
            ask = {"repo_url": url, "commit": sha, **({"composition_id": PICK[url]} if url in PICK else {}),
                   **({"composition": GIVEN} if "remotion-scenes" in url else {})}
            if "remotion-scenes" in url:  # the durations are computed in another module: the plan says so, the caller gives them
                with pytest.raises(UpstreamRefusal) as unresolved:
                    await service.plan({k: v for k, v in ask.items() if k != "composition"})
                assert unresolved.value.code == "composition_unresolved"
            if url in PICK:  # several compositions: without an id the plan says so (a typed refusal of its own)
                with pytest.raises(UpstreamRefusal) as ambiguous:
                    await service.plan({"repo_url": url, "commit": sha})
                assert ambiguous.value.code == "composition_ambiguous" and PICK[url] in ambiguous.value.details
            with pytest.raises(UpstreamRefusal) as caught:
                await service.plan(ask)
            outcome.append({"repo": url.removeprefix("https://github.com/"), "commit": sha, **caught.value.to_dict()})
            assert caught.value.code == expected, outcome[-1]
        # Hors liste blanche : aucune connexion n'est ouverte (le propriétaire n'est pas autorisé).
        strict = service_for(stack.core.prefabs, ("remotion-dev",))
        with pytest.raises(UpstreamRefusal) as caught:
            await strict.plan({"repo_url": "https://github.com/lifeprompt-team/remotion-scenes", "commit": REFUSED[-1][1]})
        assert caught.value.code == "origin_not_allowed"
        outcome.append({"repo": "lifeprompt-team/remotion-scenes", "allowlist": ["remotion-dev"], **caught.value.to_dict()})
        from jarvis.adapters.file_prefab_library import LIBRARY_DIR
        library = stack.data_root / LIBRARY_DIR
        listed = sorted(p.name for p in library.iterdir()) if library.exists() else []
        assert not [name for name in listed if name.startswith("presentation-studio.")], "a refusal publishes nothing"
        record_evidence("real_refusals", {"refusals": outcome, "published_after_refusals": 0})


async def test_a_real_mit_template_is_imported_compiled_and_rendered_in_the_sandbox_page(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        service = service_for(stack.core.prefabs, ("hongjiapeng",))
        planned = await service.plan({"repo_url": MIT_PROJECT[0], "commit": MIT_PROJECT[1]})
        assert planned["publishes"] is False and planned["plan"]["license"]["spdx"] == "MIT"
        # Une présentation réelle d'abord : l'import est limité à elle (le service vérifie qu'elle existe).
        await stack.publish("presentation-studio.p000000000001.s000000000001")
        scene = {"scene_id": "pss_000000000001", "prefab": {"id": "presentation-studio.p000000000001.s000000000001", "version": 1},
                 "title": "Dummy", "props": {"title": "Bonjour", "accent": "#3366ff"}, "data": {}, "controls": [], "anchors": []}
        pid, _ = await stack.presentation([scene])
        service = RemotionImportService(HttpsUpstreamFetcher(), stack.core.prefabs, stack.core.presentation_studio,
                                        engine=shipped_engine_pin, allowed_owners=lambda: ("hongjiapeng",), clock=lambda: NOW,
                                        diagnostics=stack.diagnostics)
        imported = await service.import_template({"repo_url": MIT_PROJECT[0], "commit": MIT_PROJECT[1], "presentation_id": pid})
        prefab = imported["prefab"]
        assert prefab["prefab_id"].startswith("presentation-studio.p") and imported["published_to_library"] is False
        assert pid.removeprefix("pst_")[:12] in prefab["prefab_id"]
        manifest = await stack.core.prefabs.manifest(prefab["prefab_id"], prefab["version"])
        view = manifest.catalog_view()
        assert view["license"] == "MIT" and view["upstream"]["commit"] == MIT_PROJECT[1] and view["upstream"]["archive_sha256"]
        # La compilation réelle (Node + esbuild du verrou) par le chemin du Player, puis la lecture dans le bac à sable.
        status, described = await stack.call("GET", f"/v1/remotion/player/{prefab['prefab_id']}/{prefab['version']}")
        assert status == 200 and described["kind"] == "remotion", described
        imported_scene = {"scene_id": "pss_000000000002", "prefab": {"id": prefab["prefab_id"], "version": prefab["version"]},
                          "title": "Importée", "props": {}, "data": {}, "controls": [], "anchors": []}
        pid2, _ = await stack.presentation([imported_scene], title="Import")
        status, started = await stack.start(pid2)
        assert status == 200 and started["state"]["phase"] == "playing", started
        shot = str(tmp_path / "imported.png")
        probe = ("(()=>{const s=document.querySelector('svg');return s?{svg:true,nodes:s.querySelectorAll('*').length,"
                 "texts:Array.from(s.querySelectorAll('text')).map(t=>t.textContent).filter(Boolean).slice(0,6),"
                 "sig:s.innerHTML.length+':'+s.innerHTML.slice(0,200).length,html:s.innerHTML.length}:{svg:false}})()")
        result = await run(stack.page_url, [
            {"wait": 500}, READY, {"wait": 1200},
            {"value": "first", "expr": probe, **SANDBOX},
            {"wait": 1500},
            {"value": "later", "expr": probe, **SANDBOX},
            {"value": "isolation", "expr": "(()=>{let t;try{t=parent.document.title}catch(e){t=e.name}return {parent:t,origin:self.origin}})()", **SANDBOX},
            {"shot": shot},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["first"]["svg"] is True and reads["first"]["nodes"] > 20, "the imported composition rendered real SVG content"
        assert reads["later"]["html"] != reads["first"]["html"], "the imported scene animates: its content changed between two samples"
        assert reads["isolation"] == {"parent": "SecurityError", "origin": "null"}, "it runs in the unprivileged sandbox frame"
        noise = [line for line in result["console"] if line.startswith("page error")] + result["errors"]
        assert not noise, noise
        assert Path(shot).stat().st_size > 3000
        record_evidence("real_import_render", {
            "upstream": f"hongjiapeng/remotion-workflow-visualizer@{MIT_PROJECT[1]}", "prefab": prefab,
            "plan": imported["plan"], "catalog_view": view, "player_descriptor_keys": sorted(described), "reads": reads,
            "kinds": sorted(set(stack.kinds()))}, shot)
        assert {"core.remotion_import.imported", "remotion.compile.done"} <= set(stack.kinds())
