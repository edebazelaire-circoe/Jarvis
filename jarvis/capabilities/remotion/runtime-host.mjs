// Point d'entrée logique `main` de la capacité Remotion (docs/remotion-runtime.md).
// Copié dans le dossier runtime par l'installation ; lancé avec cwd = dossier runtime.
//   node runtime-host.mjs --probe   : vérifie que les paquets épinglés se chargent, imprime un JSON, sort.
//   node runtime-host.mjs --serve   : sonde puis écoute sur 127.0.0.1 (port éphémère) et sert GET /health.
// Aucune variable secrète, aucun fichier hors du dossier runtime, aucune écoute hors boucle locale.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, renameSync } from "node:fs";
import http from "node:http";

const require = createRequire(import.meta.url);
const pinned = JSON.parse(readFileSync("package.json", "utf8")).dependencies;

async function probe() {
  const found = {};
  for (const [name, want] of Object.entries(pinned)) {
    const pkg = JSON.parse(readFileSync(require.resolve(`${name}/package.json`), "utf8"));
    if (pkg.version !== want) throw new Error(`${name}: installed ${pkg.version}, pinned ${want}`);
    found[name] = pkg.version;
  }
  // Charger réellement ce qui sert à Slice 05/10 : le bundler (compile le TSX) et le Player ; échoue si un binaire natif manque.
  await import("remotion");
  await import("@remotion/bundler");
  await import("@remotion/player");
  return { ok: true, node: process.version, platform: `${process.platform}-${process.arch}`, packages: found };
}

const mode = process.argv[2];
try {
  const report = await probe();
  if (mode === "--probe") {
    console.log(JSON.stringify(report));
  } else if (mode === "--serve") {
    const startedAt = new Date().toISOString();
    const server = http.createServer((req, res) => {
      if (req.method === "GET" && req.url === "/health") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ ...report, pid: process.pid, started_at: startedAt }));
      } else {
        res.writeHead(404).end();
      }
    });
    server.listen(0, "127.0.0.1", () => {
      const info = { pid: process.pid, port: server.address().port, started_at: startedAt };
      writeFileSync("worker.json.tmp", JSON.stringify(info));
      renameSync("worker.json.tmp", "worker.json");
    });
    for (const sig of ["SIGTERM", "SIGINT"]) process.on(sig, () => server.close(() => process.exit(0)));
  } else {
    throw new Error("usage: runtime-host.mjs --probe | --serve");
  }
} catch (error) {
  console.error(`probe_failed: ${error && error.message ? error.message : error}`);
  process.exit(2);
}
