"""La logique des outils « jarvis-remotion » (jarvis-remotion-presentation-integration, Slice 21), sans FastMCP.

**Une façade, jamais un propriétaire.** Chaque opération appelle la route de Core que les cartes du Control Center appellent déjà
(capacité locale, Studio, export, import, versions plus récentes) ; l'état reste à Core et la page reste le propriétaire de l'interface.
Six outils typés, un par domaine, des ids lus dans l'état (`docs/remotion-runtime.md` §13).

Règles qui tiennent ce module (chacune a un test, `tests/unit/test_remotion_mcp_*.py`) :

1. **Aucun paramètre de moteur, nulle part.** Le moteur (Remotion par défaut, Slidecar en expérience) ne se choisit que par l'utilisateur dans
   l'interface (`EngineSelectionPolicy`). Aucun outil n'envoie `engine`, aucun ne lit un moteur dans ses arguments.
2. **Un geste qui lance un processus, écrit ou publie part d'un tour adressé de l'utilisateur.** Installer / réparer, exporter, annuler un
   export, importer un modèle, essayer une version plus récente : la même attestation que le démarrage d'une présentation
   (`presentation_studio_turn.py`, `GET /api/presentation-studio/agent/turn`). Un tour que Core ouvre seul (réveil de fond, rappel) ou qui
   n'est pas adressé n'est pas attesté : refus `remotion_user_turn_required`, rien n'est envoyé à Core. `user_request` (les mots de
   l'utilisateur) est obligatoire en plus ; il n'est jamais journalisé.
3. **L'accusé « cette scène tourne sans le bac à sable » est à l'utilisateur seul.** `remotion_studio` n'appelle JAMAIS
   `POST .../studio/open` : il rend un pointeur vers la carte « Remotion · Studio » (bouton « Ouvrir le Studio », fenêtre de confirmation).
   Même règle pour la licence d'une version plus récente (`licence_ack`) : le cerveau ne la donne jamais, Core la refuse à tout acteur autre
   que `user` (défense en profondeur).
4. **Le modèle n'invente aucun id.** `job_id` (`rj_…`), `scene_id`, version : lus dans `remotion_status` / `presentation_inspect` ; un id mal
   formé ou inconnu est refusé avec les ids valides. Les révisions d'un export sont lues dans Core à l'appel, jamais tapées.
5. **Pas de Board, pas de portée bibliothèque.** Un export ne lit aucun Board (`authorised_boards` n'existe pas dans l'outil) ; un import reste
   propre à la présentation (`published_to_library: false`) et sa liste blanche de propriétaires est un réglage de l'utilisateur.
6. **Les échecs sont rendus tels quels** (code stable, phrase qui dit quoi faire, message de Core), sans parler d'un repli ni d'un autre moteur.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from jarvis.domain.presentation_studio_checks import is_scene_id
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.presentation_studio_mcp_support import MAX_LISTED, PresentationToolError, capped, clip, sentence_for
from jarvis.runtime.presentation_studio_mcp_tools import PresentationTools, _drop_none

JOB_ID = re.compile(r"rj_[0-9a-f]{12}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
#: Les seules clés de réglage d'export que le cerveau peut poser. `concurrency` (mémoire du poste) et tout le reste : à l'utilisateur.
EXPORT_SETTINGS = frozenset({"scene_id", "frame_start", "frame_end", "frame", "scale", "crf"})
EXPORT_FORMATS = ("mp4", "still", "pdf")
TARGETS = ("capability", "studio", "exports", "export")
MAX_WORDS = 200
CARD_PATH = "onglet « Plugins MCP » du Control Center, carte « Remotion · Studio »"
ENGINE_CARD = "carte « Présentations · moteur »"


class RemotionTools(PresentationTools):
    """Les six outils. Réutilise de `PresentationTools` seulement la plomberie (ids, attestation du tour, erreurs de Core, journal) ; ses
    douze outils ne sont pas exposés par ce serveur."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: Plans d'import lus dans ce processus : `clé de la demande -> jeton` (valable dix minutes, un seul `execute`).
        self._import_tokens: dict[tuple[str, ...], str] = {}

    # ------------------------------------------------------------------ socle : journal propre à ce serveur

    def _refuse(self, tool: str, code: str, message: str, **data: Any) -> PresentationToolError:
        self._emit("remotion_mcp.tool_failed", f"{tool} : {code}", level="warning", data={"tool": tool, "code": code, "source": "remotion_mcp", **data})
        valid = data.get("valid")
        hint = f" Valides : {json.dumps(valid, ensure_ascii=False, separators=(',', ':'))[:400]}" if valid else ""
        return PresentationToolError(code, f"Refus {code} : {message}{hint}")

    async def _run(self, tool: str, op: str, ids: Mapping[str, Any], body: Any) -> dict[str, Any]:
        started = self._clock()
        try:
            result = await body()
        except PresentationToolError as exc:
            self._emit("remotion_mcp.tool_failed", f"{tool}.{op} : {exc.code}", level="warning",
                       data={"tool": tool, "op": op, "code": exc.code, **{k: v for k, v in ids.items() if v is not None}})
            raise
        self._emit("remotion_mcp.tool", f"{tool}.{op}", data={
            "tool": tool, "op": op, "status": result.get("status"), "ms": round((self._clock() - started) * 1000),
            **{k: v for k, v in ids.items() if v is not None}})
        result.setdefault("op", op)
        return result

    async def _user_gate(self, tool: str, op: str, user_request: str | None) -> None:
        """Le geste part d'un tour adressé de l'utilisateur ET cite sa demande ; sinon rien n'est envoyé à Core."""

        if not clip(user_request, MAX_WORDS):
            raise self._refuse(tool, "remotion_user_request_required", sentence_for("remotion_user_request_required"), op=op)
        if not await self._addressed_user_turn():
            raise self._refuse(tool, "remotion_user_turn_required", sentence_for("remotion_user_turn_required"), op=op)

    # ------------------------------------------------------------------ lecture : santé, Studio, exports

    async def status(self, target: str, *, job_id: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._status(target, job_id)

        return await self._run("remotion_status", target, {"job_id": job_id}, body)

    async def _status(self, target: str, job_id: str | None) -> dict[str, Any]:
        tool = "remotion_status"
        if target == "capability":
            cap = (await self._c(lambda c: c.remotion_capability())).get("capability") or {}
            engine = await self._engine_facts()
            return self._ok(status=cap.get("status"), capability=self._capability_view(cap), engines=engine,
                            engine_by=f"l'utilisateur seul, {ENGINE_CARD} : jamais d'ici", untrusted=["capability.detail"])
        if target == "studio":
            studio = (await self._c(lambda c: c.remotion_studio_status())).get("studio") or {}
            return self._ok(status=studio.get("status"), studio=_drop_none({
                "status": studio.get("status"), "url": studio.get("url"), "composition": clip(studio.get("composition"), 60) or None,
                "idle_in_s": studio.get("idle_in_s"), "error": studio.get("last_error_code"),
                "detail": clip(studio.get("last_error_detail"), 200) or None,
                "modified_files": len((studio.get("work_copy") or {}).get("modified_files") or []) or None}),
                open_by=f"l'utilisateur seul ({CARD_PATH}, bouton « Ouvrir le Studio »)")
        if target == "exports":
            available = (await self._c(lambda c: c.remotion_render_availability())).get("render") or {}
            jobs = (await self._c(lambda c: c.remotion_render_jobs())).get("jobs") or []
            rows = [self._job_row(j) for j in jobs if isinstance(j, Mapping)]
            return self._ok(status="ready" if available.get("ready") else "not_ready",
                            render=_drop_none({"ready": bool(available.get("ready")), "reason": clip(available.get("reason"), 120) or None,
                                               "browser": clip(available.get("browser"), 60) or None}),
                            jobs=capped(rows, MAX_LISTED))
        if target == "export":
            if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
                raise self._refuse(tool, "invalid_id", "job_id mal formé : prends-le dans remotion_status (target exports).")
            job = (await self._c(lambda c: c.remotion_render_job(job_id))).get("job") or {}
            return self._ok(status=job.get("state"), job=self._job_row(job, full=True), untrusted=["job.error_detail"])
        raise self._refuse(tool, "unknown_target", f"target : {', '.join(TARGETS)}.")

    async def _engine_facts(self) -> dict[str, Any] | None:
        """Le moteur par défaut et l'état de chacun (lecture seule, meilleur effort : une panne ici ne masque pas la santé de la capacité)."""

        try:
            view = await self._core.call(lambda c: c.presentation_studio_engine())
        except Exception:  # noqa: BLE001 - argued: an engine facts read never hides the capability health the model asked for
            return None
        engines = view.get("engines") if isinstance(view.get("engines"), Mapping) else {}
        return _drop_none({"default": clip(view.get("default_engine"), 20) or None,
                           "ready": {str(k): bool(v.get("ready")) for k, v in engines.items() if isinstance(v, Mapping)} or None})

    @staticmethod
    def _capability_view(cap: Mapping[str, Any]) -> dict[str, Any]:
        return _drop_none({"status": cap.get("status"), "install": cap.get("install_status"), "process": cap.get("process_status"),
                           "health": cap.get("health"), "enabled": cap.get("enabled"),
                           "update_required": cap.get("update_required") or None, "error": cap.get("last_error_code"),
                           "detail": clip(cap.get("last_error_detail"), 200) or None,
                           "pinned": cap.get("pinned") or None})

    @staticmethod
    def _job_row(job: Mapping[str, Any], *, full: bool = False) -> dict[str, Any]:
        row = {"job_id": job.get("job_id"), "state": job.get("state"), "phase": job.get("phase"), "format": job.get("format"),
               "percent": job.get("percent"), "elapsed_s": job.get("elapsed_s"), "can_cancel": job.get("can_cancel"),
               "error": job.get("error_code"), "artifact_id": job.get("artifact_id")}
        if full:
            row.update(frames_done=job.get("frames_done"), frames_total=job.get("frames_total"), timeout_s=job.get("timeout_s"),
                       queue_position=job.get("queue_position"), size_bytes=job.get("size_bytes"),
                       detail=clip(job.get("error_detail"), 240) or None)
        return _drop_none(row)

    # ------------------------------------------------------------------ installer / réparer

    async def setup(self, op: str, *, user_request: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._setup(op, user_request)

        return await self._run("remotion_setup", op, {}, body)

    async def _setup(self, op: str, user_request: str | None) -> dict[str, Any]:
        tool = "remotion_setup"
        if op not in ("install", "repair"):
            raise self._refuse(tool, "unknown_op", "op : install ou repair.")
        await self._user_gate(tool, op, user_request)
        before = (await self._c(lambda c: c.remotion_capability())).get("capability") or {}
        state = before.get("status")
        if op == "install" and state in ("ready", "running"):
            return self._ok(status="already_ready", capability=self._capability_view(before),
                            note="Remotion est déjà installé et prêt : rien n'a été lancé.")
        if state == "installing":
            return self._ok(status="in_progress", capability=self._capability_view(before),
                            note="Une installation est déjà en cours : ne la relance pas, l'utilisateur la suit dans la carte.")
        answer = await self._c(lambda c: c.local_capability_action("remotion", op))
        after = answer.get("capability") or {}
        failed = after.get("status") in ("install_failed", "repair_needed", "crashed")
        return self._ok("say", status=after.get("status"), capability=self._capability_view(after),
                        say=("L'installation a échoué : " + clip(after.get("last_error_detail"), 120)) if failed
                        else f"{'Installation' if op == 'install' else 'Réparation'} de Remotion lancée ; elle se suit dans la carte « Remotion ».",
                        note="Ne boucle pas pour attendre : relis remotion_status (target capability) une fois si l'utilisateur le demande.",
                        untrusted=["capability.detail"])

    # ------------------------------------------------------------------ Studio : pointeur, jamais l'ouverture

    async def studio(self, *, presentation_id: str | None = None, variant_id: str | None = None, scene_id: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._studio_pointer(presentation_id, variant_id, scene_id)

        return await self._run("remotion_studio", "open", {"presentation_id": presentation_id, "scene_id": scene_id}, body)

    async def _studio_pointer(self, pid: str | None, vid: str | None, scene_id: str | None) -> dict[str, Any]:
        """N'appelle jamais `POST .../studio/open` : l'accusé de la scène hors bac à sable est un geste de l'utilisateur, dans la page."""

        tool = "remotion_studio"
        cap = (await self._c(lambda c: c.remotion_capability())).get("capability") or {}
        if cap.get("status") not in ("ready", "running"):
            return self._ok("say", status="runtime_not_ready", capability=self._capability_view(cap),
                            say="Remotion n'est pas prêt sur ce poste : il faut l'installer ou le réparer avant d'ouvrir le Studio.",
                            note="Propose-le ; remotion_setup seulement si l'utilisateur le demande.")
        scene: dict[str, Any] = {}
        if scene_id is not None:
            presentation_id = await self._presentation(tool, pid)
            variant_id = await self._variant(tool, presentation_id, vid)
            sid = self._scene(tool, scene_id)
            described = await self._c(lambda c: c.presentation_studio_scene_controls(presentation_id, variant_id, sid))
            scene = {"scene_id": sid, "prefab": described.get("prefab")}
        return self._ok("say", status="needs_user", where=CARD_PATH, scene=scene or None,
                        say="Pour ouvrir le Studio, clique sur « Ouvrir le Studio » dans la carte Remotion et confirme : cette scène y tourne hors du bac à sable.",
                        note="Tu ne peux pas ouvrir le Studio ni confirmer à sa place : l'accusé est à l'utilisateur seul. Dis où cliquer, une fois.")

    # ------------------------------------------------------------------ export

    async def export(self, op: str, *, format: str | None = None, settings: Mapping[str, Any] | None = None, presentation_id: str | None = None,
                     variant_id: str | None = None, job_id: str | None = None, user_request: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._export(op, format, settings, presentation_id, variant_id, job_id, user_request)

        return await self._run("remotion_export", op, {"presentation_id": presentation_id, "variant_id": variant_id, "job_id": job_id}, body)

    async def _export(self, op: str, fmt: str | None, settings: Mapping[str, Any] | None, pid: str | None, vid: str | None, job_id: str | None,
                      user_request: str | None) -> dict[str, Any]:
        tool = "remotion_export"
        if op == "cancel":
            if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
                raise self._refuse(tool, "invalid_id", "job_id mal formé : prends-le dans remotion_status (target exports).")
            await self._user_gate(tool, op, user_request)
            job = (await self._c(lambda c: c.remotion_render_cancel(job_id))).get("job") or {}
            return self._ok("say", status=job.get("state"), job=self._job_row(job), say="Annulation demandée pour cet export.")
        if op != "start":
            raise self._refuse(tool, "unknown_op", "op : start ou cancel.")
        if fmt not in EXPORT_FORMATS:
            raise self._refuse(tool, "invalid_format", "format : mp4 (vidéo), still (image) ou pdf.")
        chosen = dict(settings or {})
        stray = sorted(str(k)[:30] for k in chosen if k not in EXPORT_SETTINGS)
        if stray:
            raise self._refuse(tool, "invalid_setting", f"réglage(s) non permis au cerveau : {', '.join(stray[:5])} (permis : {', '.join(sorted(EXPORT_SETTINGS))}).")
        if "scene_id" in chosen:
            self._scene(tool, chosen["scene_id"])
        await self._user_gate(tool, op, user_request)
        presentation_id = await self._presentation(tool, pid)
        variant_id = await self._variant(tool, presentation_id, vid)
        view = await self._c(lambda c: c.presentation_studio_get(presentation_id))
        variant = next((v for v in view.get("variants") or [] if isinstance(v, Mapping) and v.get("variant_id") == variant_id), None)
        revision = (view.get("presentation") or {}).get("revision")
        if variant is None or type(revision) is not int or type(variant.get("revision")) is not int:
            raise self._refuse(tool, "presentation_studio_unknown_variant", sentence_for("presentation_studio_unknown_variant"))
        request: dict[str, Any] = {"format": fmt, "presentation_id": presentation_id, "variant_id": variant_id,
                                   "expected_presentation_revision": revision, "expected_variant_revision": variant["revision"]}
        if chosen:
            request["settings"] = chosen
        job = (await self._c(lambda c: c.remotion_render_create(request))).get("job") or {}
        return self._ok("say", status=job.get("state"), job=self._job_row(job), presentation_id=presentation_id, variant_id=variant_id,
                        revisions={"presentation": revision, "variant": variant["revision"]},
                        say="L'export est lancé ; il se suit dans la vue Artefacts du Board (phase, images, secondes).",
                        note="Aucun Board n'est lu dans cet export. Ne boucle pas pour attendre : remotion_status (target export, job_id) à la demande.")

    # ------------------------------------------------------------------ import d'un modèle amont

    async def import_template(self, op: str, *, repo_url: str | None = None, commit: str | None = None, composition_id: str | None = None,
                              subdir: str | None = None, title: str | None = None, presentation_id: str | None = None,
                              user_request: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._import(op, repo_url, commit, composition_id, subdir, title, presentation_id, user_request)

        return await self._run("remotion_import", op, {"presentation_id": presentation_id}, body)

    def _import_key(self, request: Mapping[str, Any]) -> tuple[str, ...]:
        digest = hashlib.sha256("\x1f".join(f"{k}={request[k]}" for k in sorted(request)).encode("utf-8")).hexdigest()[:24]
        return ("remotion_import", digest)

    async def _import(self, op: str, repo_url: str | None, commit: str | None, composition_id: str | None, subdir: str | None,
                      title: str | None, pid: str | None, user_request: str | None) -> dict[str, Any]:
        tool = "remotion_import"
        if op not in ("plan", "execute"):
            raise self._refuse(tool, "unknown_op", "op : plan ou execute.")
        if not isinstance(repo_url, str) or not repo_url.strip():
            raise self._refuse(tool, "invalid_request", "repo_url : l'adresse du dépôt donnée par l'utilisateur (https://github.com/…).")
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise self._refuse(tool, "commit_not_pinned", sentence_for("commit_not_pinned"))
        await self._user_gate(tool, op, user_request)
        request: dict[str, Any] = _drop_none({"repo_url": repo_url.strip(), "commit": commit, "composition_id": composition_id,
                                              "subdir": subdir, "title": title})
        if op == "plan":
            planned = await self._c(lambda c: c.remotion_import_plan(request))
            token = self.ledger.issue(*self._import_key(request), pid or "")
            self._import_tokens[self._import_key(request) + (pid or "",)] = token
            return self._ok(status="planned", plan=self._plan_view(planned.get("plan") or {}), publishes=False,
                            note="Rien n'est écrit. Si la licence et les dépendances conviennent à la demande de l'utilisateur : op execute, même demande.",
                            untrusted=["plan.license", "plan.warnings", "plan.origin.name"])
        presentation_id = await self._presentation(tool, pid)
        key = self._import_key(request) + (pid or "",)
        token = self._import_tokens.get(key)
        if token is None or not self.ledger.check(key[0], token, key[1], pid or ""):
            raise self._refuse(tool, "remotion_import_plan_first", sentence_for("remotion_import_plan_first"))
        request["presentation_id"] = presentation_id
        done = await self._c(lambda c: c.remotion_import(request))
        self._import_tokens.pop(key, None)
        prefab = done.get("prefab") if isinstance(done.get("prefab"), Mapping) else {}
        return self._ok("say", status="imported", presentation_id=presentation_id, scene_id=done.get("scene_id"),
                        prefab=_drop_none({"id": prefab.get("prefab_id"), "version": prefab.get("version")}),
                        published_to_library=bool(done.get("published_to_library")),
                        say="Le modèle est importé dans cette présentation (pas dans la bibliothèque partagée) ; la scène est à placer dans la variante.",
                        note="L'import ne pose pas la scène dans la variante. Le moteur n'est pas touché.")

    @staticmethod
    def _plan_view(plan: Mapping[str, Any]) -> dict[str, Any]:
        origin = plan.get("origin") if isinstance(plan.get("origin"), Mapping) else {}
        licence = plan.get("license") if isinstance(plan.get("license"), Mapping) else {}
        files = plan.get("files") if isinstance(plan.get("files"), Mapping) else {}
        return _drop_none({
            "origin": _drop_none({"name": clip(origin.get("name"), 80), "commit": origin.get("commit"), "subdir": clip(origin.get("subdir"), 80) or None}),
            "license": {str(k)[:24]: clip(v, 64) for k, v in list(licence.items())[:6] if isinstance(v, (str, bool, int))},
            "composition": plan.get("composition"),
            "dependencies": len(plan.get("dependencies") or []), "dropped_dependencies": len(plan.get("dropped_dependencies") or []) or None,
            "modules": len(files.get("modules") or []), "assets": len(files.get("assets") or []),
            "warnings": [clip(w, 120) for w in (plan.get("warnings") or [])[:5]] or None})

    # ------------------------------------------------------------------ versions plus récentes : avis et essai

    async def upgrades(self, op: str, *, presentation_id: str | None = None, variant_id: str | None = None, scene_id: str | None = None,
                       version: int | None = None, user_request: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._upgrades(op, presentation_id, variant_id, scene_id, version, user_request)

        return await self._run("remotion_upgrades", op, {"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id}, body)

    async def _upgrades(self, op: str, pid: str | None, vid: str | None, scene_id: str | None, version: int | None,
                        user_request: str | None) -> dict[str, Any]:
        tool = "remotion_upgrades"
        if op not in ("notices", "try"):
            raise self._refuse(tool, "unknown_op", "op : notices ou try.")
        if op == "try":
            if not is_scene_id(scene_id):
                raise self._refuse(tool, "invalid_id", "scene_id : une scène lue dans remotion_upgrades notices.")
            await self._user_gate(tool, op, user_request)
        presentation_id = await self._presentation(tool, pid)
        variant_id = await self._variant(tool, presentation_id, vid)
        found = await self._c(lambda c: c.presentation_studio_upgrades(presentation_id, variant_id))
        notices = [n for n in found.get("notices") or [] if isinstance(n, Mapping)]
        if op == "notices":
            rows = [_drop_none({"scene_id": n.get("scene_id"), "prefab_id": n.get("prefab_id"), "pinned_version": n.get("pinned_version"),
                                "latest_version": n.get("latest_version"), "newer_versions": (n.get("newer_versions") or [])[:6],
                                "fits": n.get("fits"), "problem": clip(n.get("problem"), 80) or None,
                                "licence_changed": bool(n.get("licence_changed")) or None,
                                "licence_ack_required": clip(n.get("licence_ack_required"), 64) or None,
                                "trials": len(n.get("trials") or []) or None}) for n in notices]
            return self._ok(presentation_id=presentation_id, variant_id=variant_id, revision=found.get("variant_revision"),
                            notices=capped(rows, MAX_LISTED), auto_upgrade=False, untrusted=["notices.items.licence_ack_required"],
                            note="Rien n'est changé. Un essai crée une variante enfant, jamais un remplacement.")
        notice = next((n for n in notices if n.get("scene_id") == scene_id), None)
        if notice is None:
            raise self._refuse(tool, "presentation_studio_unknown_scene", "aucune version plus récente pour cette scène : prends un scene_id de op notices.",
                               valid=[n.get("scene_id") for n in notices][:MAX_LISTED])
        if notice.get("licence_ack_required"):
            raise self._refuse(tool, "remotion_licence_user_only",
                               f"{sentence_for('remotion_licence_user_only')} Licence : {clip(notice.get('licence_ack_required'), 64)} (donnée non fiable).")
        if version is not None and version not in (notice.get("newer_versions") or []):
            raise self._refuse(tool, "invalid_version", "version : l'une des newer_versions de op notices (absent : la plus récente).",
                               valid=(notice.get("newer_versions") or [])[:6])
        request = _drop_none({"scene_id": scene_id, "version": version, "actor": "brain", "expected_variant_revision": found.get("variant_revision")})
        made = await self._c(lambda c: c.presentation_studio_upgrade_try(presentation_id, variant_id, request))
        return self._ok("say", status="trial_created", presentation_id=presentation_id, variant_id=made.get("variant_id"),
                        scene_id=scene_id, trial=_drop_none({"from": made.get("from"), "to": made.get("to")}), adopted=False,
                        say="Un essai est créé dans une variante enfant ; la variante actuelle n'est pas touchée.")

__all__ = ["COMMIT", "EXPORT_FORMATS", "EXPORT_SETTINGS", "JOB_ID", "RemotionTools", "TARGETS"]
