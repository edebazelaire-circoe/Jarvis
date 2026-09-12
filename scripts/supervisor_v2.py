#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from collections import deque
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Un enfant qui meurt en boucle doit finir par se taire : relancer indéfiniment
# un crash natif noie le journal et masque la panne d'origine.
MAX_RESTARTS_PER_WINDOW = 5
RESTART_WINDOW_S = 120.0
# Au-delà de cette durée de vie, l'enfant est considéré comme sain et le
# backoff repart de zéro.
HEALTHY_UPTIME_S = 60.0
STDERR_TAIL_LINES = 40
# Une demande de rechargement arrive par un fichier, écrit par un autre
# processus : il faut aller la voir. Une seconde est invisible à l'usage et ne
# coûte rien.
RELOAD_POLL_S = 1.0


class Supervisor:
    def __init__(self, *, journal, runtime_root: Path) -> None:
        self.children: dict[str, asyncio.subprocess.Process] = {}
        self.stopping = False
        self.journal = journal
        self.runtime_root = runtime_root
        self._tails: dict[str, deque[str]] = {}
        self._pumps: dict[str, asyncio.Task[None]] = {}
        self._started_at: dict[str, float] = {}
        self._restarts: dict[str, list[float]] = {}
        self._backoff: dict[str, float] = {}

    async def spawn(self, role: str, *args: str) -> asyncio.subprocess.Process:
        # stderr est capturé plutôt qu'hérité : c'est le seul endroit où une
        # trace de mort brutale apparaît, et elle était jusqu'ici perdue avec la
        # console.
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "jarvis",
            *args,
            cwd=ROOT,
            env=os.environ.copy(),
            stderr=asyncio.subprocess.PIPE,
        )
        self.children[role] = process
        self._tails[role] = deque(maxlen=STDERR_TAIL_LINES)
        self._started_at[role] = asyncio.get_running_loop().time()
        previous = self._pumps.pop(role, None)
        if previous is not None:
            previous.cancel()
        self._pumps[role] = asyncio.create_task(self._pump_stderr(role, process), name=f"jarvis-{role}-stderr")
        self.journal.emit("supervisor.spawn", f"Processus « {role} » lancé", data={"role": role, "pid": process.pid})
        return process

    async def _pump_stderr(self, role: str, process: asyncio.subprocess.Process) -> None:
        """Tee la sortie d'erreur vers la console, un log par rôle et un tampon.

        Le tampon est ce qui permet de joindre les dernières lignes du mourant à
        l'entrée d'erreur du journal.
        """
        stream = process.stderr
        if stream is None:
            return
        log_path = self.runtime_root / "logs" / f"{role}.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = log_path.open("a", encoding="utf-8")
        except OSError:
            handle = None
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    return
                line = raw.decode("utf-8", errors="replace").rstrip()
                self._tails.setdefault(role, deque(maxlen=STDERR_TAIL_LINES)).append(line)
                print(f"[{role}] {line}", file=sys.stderr, flush=True)
                if handle is not None:
                    handle.write(line + "\n")
                    handle.flush()
        finally:
            if handle is not None:
                handle.close()

    async def _exit_report(self, role: str) -> dict[str, object]:
        """Réunir tout ce qui explique la mort d'un enfant."""
        from jarvis.runtime.crash_guard import describe_exit_code, tail, take_crash_log

        # Laisser le pump drainer les dernières lignes avant de lire le tampon.
        pump = self._pumps.pop(role, None)
        if pump is not None:
            try:
                await asyncio.wait_for(asyncio.shield(pump), timeout=2.0)
            except asyncio.TimeoutError:
                pump.cancel()
            except Exception:
                # Le tee stderr est un confort de diagnostic : son échec ne doit
                # pas empêcher de journaliser la mort de l'enfant.
                pass

        process = self.children.get(role)
        report: dict[str, object] = describe_exit_code(process.returncode if process is not None else None)
        report["role"] = role
        if process is not None:
            report["pid"] = process.pid
        crash_dump = take_crash_log(self.runtime_root, role)
        if crash_dump:
            report["traceback"] = tail(crash_dump)
        stderr_tail = "\n".join(self._tails.get(role) or ())
        if stderr_tail:
            report["stderr"] = stderr_tail
        return report

    def _may_restart(self, role: str) -> bool:
        now = asyncio.get_running_loop().time()
        history = [stamp for stamp in self._restarts.get(role, []) if now - stamp < RESTART_WINDOW_S]
        history.append(now)
        self._restarts[role] = history
        if len(history) <= MAX_RESTARTS_PER_WINDOW:
            return True
        self.journal.emit(
            "supervisor.giveup",
            f"Le processus « {role} » a échoué {len(history)} fois en {int(RESTART_WINDOW_S)} s ; relances suspendues.",
            level="error",
            data={"role": role, "code": "supervisor_restart_budget_exhausted", "failures": len(history)},
        )
        return False

    def _restart_delay(self, role: str) -> float:
        started = self._started_at.get(role)
        uptime = asyncio.get_running_loop().time() - started if started is not None else 0.0
        if uptime >= HEALTHY_UPTIME_S:
            self._backoff[role] = 1.0
        delay = self._backoff.get(role, 1.0)
        self._backoff[role] = min(delay * 2, 8.0)
        return delay

    async def wait_core_ready(self, *, timeout_s: float = 30.0) -> None:
        from jarvis.protocol.client import LocalCoreClient
        from jarvis.v2_config import V2Settings
        settings = V2Settings.load()
        deadline = asyncio.get_running_loop().time() + timeout_s
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            core = self.children.get("core")
            if core is not None and core.returncode is not None:
                report = await self._exit_report("core")
                self.journal.emit(
                    "supervisor.core_failed",
                    f"Core s'est arrêté avant d'être prêt : {report.get('label')}",
                    level="error",
                    data={**report, "code": "core_exit_before_ready"},
                )
                raise RuntimeError(f"Core exited before readiness with code {core.returncode}")
            if settings.token_file.exists():
                client = LocalCoreClient(host=settings.core_host, port=settings.core_port, token=settings.token_file.read_text(encoding="utf-8").strip())
                try:
                    if (await client.health()).get("ready"):
                        return
                except Exception as exc:
                    last_error = exc
                finally:
                    await client.close()
            await asyncio.sleep(0.25)
        self.journal.emit(
            "supervisor.core_timeout",
            f"Core n'a pas répondu prêt en {timeout_s:.0f} s",
            level="error",
            data={"role": "core", "code": "core_readiness_timeout", "last_error": str(last_error) if last_error else None},
        )
        raise RuntimeError(f"Core readiness timeout: {last_error or 'no healthy response'}")

    async def _ensure_role(self, role: str, *args: str) -> asyncio.subprocess.Process:
        current = self.children.get(role)
        if current is None or current.returncode is not None:
            return await self.spawn(role, *args)
        return current

    def _journal_exit(self, role: str, report: dict[str, object]) -> None:
        if self.stopping or not report.get("fatal"):
            self.journal.emit("supervisor.child_exit", f"Processus « {role} » terminé : {report.get('label')}", data=report)
            return
        self.journal.emit(
            "supervisor.child_failed",
            f"Le processus « {role} » s'est arrêté anormalement : {report.get('label')}",
            level="error",
            data={**report, "code": "supervisor_child_crash" if report.get("native_crash") else "supervisor_child_failed"},
        )

    async def _core_health(self) -> dict[str, object]:
        """L'avis de Core sur lui-même, une fois. Sert à conclure un déploiement."""
        from jarvis.protocol.client import LocalCoreClient
        from jarvis.v2_config import V2Settings

        settings = V2Settings.load()
        if not settings.token_file.exists():
            return {"ready": False, "error": "jeton de Core absent"}
        client = LocalCoreClient(
            host=settings.core_host,
            port=settings.core_port,
            token=settings.token_file.read_text(encoding="utf-8").strip(),
        )
        try:
            return dict(await client.health())
        finally:
            await client.close()

    def _deployments(self):  # noqa: ANN202 - le coordinateur, construit à la demande
        from jarvis.runtime.deployment import DeploymentCoordinator

        return DeploymentCoordinator(primary=ROOT, runtime_root=self.runtime_root, journal=self.journal)

    async def settle_deployment(self) -> None:
        """Conclure un déploiement laissé en cours par le redémarrage précédent.

        C'est ici qu'un déploiement devient vrai : Core vient de répondre prêt,
        donc le nouveau code tourne. S'il n'avait pas répondu, le coordinateur
        serait revenu à la révision qui marchait.
        """
        try:
            await self._deployments().finish(health=self._core_health)
        except Exception as exc:  # noqa: BLE001 - un déploiement ne fait pas tomber le service
            self.journal.emit(
                "deploy.settle_failed",
                f"Conclusion du déploiement impossible ({type(exc).__name__}) : le service continue.",
                level="error",
                data={"code": "deploy_settle_failed", "exception_type": type(exc).__name__},
            )

    async def _reload_requested(self) -> bool:
        try:
            return self._deployments().take_reload_request()
        except OSError:
            return False

    async def _reload(self) -> None:
        """Repartir sur le code présent sur le disque, état durable conservé.

        Le superviseur se remplace lui-même : c'est le seul moyen d'être sûr
        qu'aucun module Python de l'ancienne révision ne survit. Les enfants
        sont arrêtés proprement avant ; ce qu'ils ont écrit reste sur le disque,
        et c'est cet état qui fait la continuité, pas les processus.
        """
        self.journal.emit(
            "supervisor.reload",
            "Rechargement demandé : arrêt des enfants puis reprise sur le nouveau code.",
            data={"code": "supervisor_reload", "pid": os.getpid()},
        )
        await self.stop()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    async def run(self) -> int:
        self.journal.emit("supervisor.start", "Superviseur Jarvis démarré", data={"pid": os.getpid()})
        await self.spawn("core", "core")
        await self.wait_core_ready()
        await self.settle_deployment()
        await self._ensure_role("ui", "control-center")
        await self._ensure_role("voice", "voice")

        while not self.stopping:
            live = {role: process for role, process in self.children.items() if process.returncode is None}
            if "core" not in live:
                # Core est la seule dépendance dure : sa mort termine le
                # superviseur, avec son propre code de sortie.
                core = self.children.get("core")
                return int((core.returncode if core is not None else 1) or 1)
            waits = {
                role: asyncio.create_task(process.wait(), name=f"jarvis-{role}-wait")
                for role, process in live.items()
            }
            # Le réveil régulier sert à voir une demande de rechargement : elle
            # arrive par le disque, d'un autre processus, sans rien à écouter.
            done, pending = await asyncio.wait(
                set(waits.values()), timeout=RELOAD_POLL_S, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if not done:
                if await self._reload_requested():
                    await self._reload()
                continue
            completed = next(name for name, task in waits.items() if task in done)

            report = await self._exit_report(completed)
            self._journal_exit(completed, report)

            if completed == "core":
                return int(self.children["core"].returncode or 1)
            if self.stopping:
                break
            if not self._may_restart(completed):
                # Le rôle est abandonné mais le superviseur continue de veiller
                # sur les autres : une voix morte ne doit pas emporter l'UI.
                self.children.pop(completed, None)
                continue
            delay = self._restart_delay(completed)
            if completed == "voice":
                await asyncio.sleep(delay)
                await self.spawn("voice", "voice")
                continue
            if completed == "ui":
                await asyncio.sleep(delay)
                await self.spawn("ui", "control-center")
                continue

        return 0

    async def stop(self) -> None:
        self.stopping = True
        processes = tuple(self.children.values())
        for process in processes:
            if process.returncode is None:
                process.terminate()
        if processes:
            try:
                await asyncio.wait_for(asyncio.gather(*(p.wait() for p in processes), return_exceptions=True), 8)
            except asyncio.TimeoutError:
                for process in processes:
                    if process.returncode is None:
                        process.kill()
                await asyncio.gather(*(p.wait() for p in processes), return_exceptions=True)
        for pump in self._pumps.values():
            pump.cancel()
        await asyncio.gather(*self._pumps.values(), return_exceptions=True)
        self._pumps.clear()


async def main() -> int:
    from jarvis.environment import load_project_environment
    from jarvis.runtime.crash_guard import install_asyncio_crash_guard, install_crash_guard, report_fatal
    from jarvis.v2_config import V2Settings

    load_project_environment()
    runtime_root = V2Settings.load().runtime_root
    journal = install_crash_guard(runtime_root=runtime_root, role="supervisor")
    install_asyncio_crash_guard(asyncio.get_running_loop())

    supervisor = Supervisor(journal=journal, runtime_root=runtime_root)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(supervisor.stop()))
        except (NotImplementedError, RuntimeError):
            pass
    try:
        return await supervisor.run()
    except BaseException as exc:
        if not isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
            report_fatal(exc, context={"source": "supervisor"})
        raise
    finally:
        await supervisor.stop()
        journal.emit("supervisor.stop", "Superviseur Jarvis arrêté")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
