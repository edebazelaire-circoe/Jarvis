// Pilote Chrome DevTools Protocol du harnais d'isolation (Slice 06 de jarvis-remotion-presentation-integration).
// Appelé par scripts/remotion_isolation_harness.py : node remotion_isolation_cdp.mjs <port> <jobs.json> <out.json>
// Aucune dépendance : le WebSocket global de Node (>= 22). Un job = un onglet neuf :
//   { id, url, timeoutMs, doneExpr?, childProbe?, selfProbe?, settleMs? }
// Le pilote attend `doneExpr` dans la page de l'hôte, lit `window.__REPORT`, puis sonde, par le protocole (donc sans
// restriction d'origine), le cadre enfant (cible `iframe`) : ce que la scène hostile a réellement produit dans son document.
import { readFileSync, writeFileSync } from "node:fs";

const [port, jobsFile, outFile] = process.argv.slice(2);
const jobs = JSON.parse(readFileSync(jobsFile, "utf8"));

const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = () => reject(new Error("cannot reach Chrome DevTools")); });

let nextId = 1;
const pending = new Map();
const listeners = [];
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject, timer } = pending.get(message.id);
    clearTimeout(timer);
    pending.delete(message.id);
    message.error ? reject(new Error(message.error.message)) : resolve(message.result);
  } else if (message.method) {
    for (const listener of listeners) listener(message);
  }
};
function send(method, params = {}, sessionId, timeoutMs = 8000) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`timeout: ${method}`)); }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function evaluate(sessionId, expression, timeoutMs = 5000) {
  const started = Date.now();
  try {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId, timeoutMs);
    return { ok: true, value: result.result.value, exception: result.exceptionDetails ? result.exceptionDetails.text : null, ms: Date.now() - started };
  } catch (error) {
    return { ok: false, error: String(error.message), ms: Date.now() - started };
  }
}

const results = {};
for (const job of jobs) {
  const record = { crashed: [], targetsSeen: [], parent: null, child: null, self: null, notes: [], console: [] };
  const crashListener = (message) => {
    if (message.method === "Target.targetCrashed") record.crashed.push({ targetId: message.params.targetId, status: message.params.status });
    if (message.method === "Inspector.targetCrashed") record.crashed.push({ session: message.sessionId, status: "inspector" });
  };
  listeners.push(crashListener);
  // Console of the page AND of its (out-of-process) frames: what the browser itself says it refused.
  const consoleListener = (message) => {
    const p = message.params || {};
    let text = null;
    if (message.method === "Log.entryAdded" && ["error", "warning"].includes(p.entry.level)) text = `${p.entry.source}/${p.entry.level}: ${p.entry.text}`;
    if (message.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(p.type)) text = `console.${p.type}: ${(p.args || []).map((a) => a.value ?? a.description ?? "").join(" ")}`;
    if (message.method === "Runtime.exceptionThrown") text = `exception: ${(p.exceptionDetails.exception && p.exceptionDetails.exception.description) || p.exceptionDetails.text}`;
    if (text && record.console.length < 60) record.console.push(text.replace(/\s+/g, " ").slice(0, 260));
    if (message.method === "Target.attachedToTarget") {
      send("Log.enable", {}, message.params.sessionId).catch(() => {});
      send("Runtime.enable", {}, message.params.sessionId).catch(() => {});
      send("Runtime.runIfWaitingForDebugger", {}, message.params.sessionId).catch(() => {});
    }
  };
  listeners.push(consoleListener);
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);
  await send("Log.enable", {}, sessionId);
  await send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: true, flatten: true }, sessionId);
  await send("Page.navigate", { url: job.url }, sessionId);
  const started = Date.now();
  let done = false;
  while (Date.now() - started < job.timeoutMs) {
    await sleep(250);
    if (!job.doneExpr) { if (Date.now() - started >= (job.settleMs ?? 2500)) break; continue; }
    const probe = await evaluate(sessionId, job.doneExpr, 4000);
    if (probe.ok && probe.value === true) { done = true; break; }
    if (!probe.ok) record.notes.push(`parent probe failed after ${Date.now() - started} ms: ${probe.error}`);
  }
  record.done = done;
  record.elapsedMs = Date.now() - started;
  if (job.doneExpr) record.parent = await evaluate(sessionId, "JSON.stringify(window.__REPORT)", 5000);
  if (job.selfProbe) record.self = await evaluate(sessionId, job.selfProbe, 5000);
  if (job.childProbe) {
    const { targetInfos } = await send("Target.getTargets");
    const frames = targetInfos.filter((t) => t.type === "iframe" && t.url.includes(job.childUrlPart ?? "/page/"));
    record.targetsSeen = targetInfos.map((t) => ({ type: t.type, url: t.url.replace(/[?#].*$/, "").slice(0, 100) }));
    if (frames.length === 0) record.child = { absent: true };
    else {
      try {
        const attached = await send("Target.attachToTarget", { targetId: frames[0].targetId, flatten: true });
        record.child = await evaluate(attached.sessionId, job.childProbe, 4000);
        await send("Target.detachFromTarget", { sessionId: attached.sessionId }).catch(() => {});
      } catch (error) {
        record.child = { ok: false, error: String(error.message) };
      }
    }
  }
  listeners.splice(listeners.indexOf(crashListener), 1);
  listeners.splice(listeners.indexOf(consoleListener), 1);
  await send("Target.closeTarget", { targetId }).catch(() => {});
  results[job.id] = record;
}
writeFileSync(outFile, JSON.stringify(results, null, 2));
ws.close();
