// Point d'entrée logique `main` de la capacité Remotion (docs/remotion-runtime.md, docs/remotion-source.md).
// Copié dans le dossier runtime par l'installation ; lancé avec cwd = dossier runtime.
//   node runtime-host.mjs --probe            : vérifie que les paquets épinglés se chargent, imprime un JSON, sort.
//   node runtime-host.mjs --serve            : sonde puis écoute sur 127.0.0.1 (port éphémère) et sert GET /health.
//   node runtime-host.mjs --compile <req>    : compile UNE scène (ou le "host") en un bundle navigateur, sort. (Slice 05)
// Aucune variable secrète, aucun fichier hors du dossier runtime, aucune écoute hors boucle locale.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, renameSync, mkdirSync } from "node:fs";
import { join } from "node:path";
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
  // Charger réellement ce qui sert aux Slices 05/10 : le bundler, le Player et esbuild (compile le TSX) ; échoue si un binaire natif manque.
  await import("remotion");
  await import("@remotion/bundler");
  await import("@remotion/player");
  const esbuild = await import("esbuild");
  return { ok: true, node: process.version, platform: `${process.platform}-${process.arch}`, packages: found, esbuild: esbuild.version };
}

// ------------------------------------------------------------------ compilation (contrat : docs/remotion-source.md §5)
//
// Entrée : un fichier JSON `req`
//   { contract: 1, target: "scene"|"host", out_dir, entry, modules: {chemin: texte}, allowed_imports: [...], minify, digest }
// Sortie : `out_dir/<scene.js|host.js>` et `out_dir/result.json` ({ok: true, files} ou {ok: false, code, message, diagnostics}).
// Une scène est compilée dans un système de fichiers VIRTUEL : les seuls fichiers lisibles sont ceux de `modules`, les seuls
// modules « nus » sont ceux de `allowed_imports` (résolus vers les globaux de l'hôte `globalThis.__JARVIS_HOST__`). Rien
// n'est lu sur le disque, aucun `node_modules` de la scène n'existe.

const EXTENSIONS = [".tsx", ".ts", ".jsx", ".js", ".json"];
const LOADERS = { ".tsx": "tsx", ".ts": "ts", ".jsx": "jsx", ".js": "js", ".json": "json" };
const HOST_MODULES = ["react", "react/jsx-runtime", "react/jsx-dev-runtime", "react-dom", "react-dom/client", "remotion", "@remotion/player"];

function fail(code, message, diagnostics = []) {
  const error = new Error(message);
  error.compile = { code, message, diagnostics };
  return error;
}

function joinRelative(importerDir, specifier) {
  const parts = importerDir === "" ? [] : importerDir.split("/");
  for (const part of specifier.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (parts.length === 0) return null; // sort de la source
      parts.pop();
    } else parts.push(part);
  }
  return parts.join("/");
}

function virtualPlugin(modules, allowed) {
  return {
    name: "jarvis-virtual-source",
    setup(build) {
      build.onResolve({ filter: /.*/ }, (args) => {
        const spec = args.path;
        const importer = args.namespace === "jarvis" ? args.importer : "";
        if (spec.startsWith("./") || spec.startsWith("../")) {
          const dir = importer.includes("/") ? importer.slice(0, importer.lastIndexOf("/")) : "";
          const base = joinRelative(dir, spec);
          if (base === null) return { errors: [{ text: `import_escapes_source: "${spec}" leaves the scene source` }] };
          const candidates = [base, ...EXTENSIONS.map((e) => base + e), ...EXTENSIONS.map((e) => `${base}/index${e}`)];
          const found = candidates.find((c) => Object.prototype.hasOwnProperty.call(modules, c));
          if (!found) return { errors: [{ text: `import_unresolved: "${spec}" is not a module of this scene` }] };
          return { path: found, namespace: "jarvis" };
        }
        if (allowed.has(spec)) return { path: spec, namespace: "host" };
        return { errors: [{ text: `import_refused: "${spec}" is not available to scenes (allowed: ${[...allowed].join(", ")}); assets go in public/ and are read with staticFile()` }] };
      });
      build.onLoad({ filter: /.*/, namespace: "jarvis" }, (args) => {
        const dot = args.path.lastIndexOf(".");
        return { contents: modules[args.path], loader: LOADERS[args.path.slice(dot)] ?? "js" };
      });
      build.onLoad({ filter: /.*/, namespace: "host" }, (args) => ({
        contents: `var h = globalThis.__JARVIS_HOST__; if (!h || !h[${JSON.stringify(args.path)}]) throw new Error("Jarvis host module missing: " + ${JSON.stringify(args.path)}); module.exports = h[${JSON.stringify(args.path)}];`,
        loader: "js",
      }));
    },
  };
}

function classify(errors) {
  const diagnostics = errors.slice(0, 20).map((e) => ({
    file: e.location ? String(e.location.file).replace(/^jarvis:/, "") : "",
    line: e.location ? e.location.line : 0,
    column: e.location ? e.location.column : 0,
    text: String(e.text).slice(0, 300),
  }));
  const texts = errors.map((e) => String(e.text));
  if (texts.some((t) => /^import_(refused|escapes_source|unresolved)/.test(t))) {
    return fail("compile_import_refused", texts.find((t) => /^import_/.test(t)).slice(0, 300), diagnostics);
  }
  if (texts.some((t) => t.includes("No matching export") && t.includes('"default"'))) {
    return fail("compile_entry_invalid", "the entry module has no default export (export default the scene component)", diagnostics);
  }
  return fail("compile_source_error", diagnostics.length ? `${diagnostics[0].file}:${diagnostics[0].line}:${diagnostics[0].column} ${diagnostics[0].text}` : "the source does not compile", diagnostics);
}

async function build(esbuild, options) {
  try {
    return await esbuild.build(options);
  } catch (error) {
    if (error && Array.isArray(error.errors) && error.errors.length) throw classify(error.errors);
    throw error;
  }
}

async function compile(req) {
  if (req.contract !== 1) throw fail("compile_compiler_failed", `unsupported compile contract ${req.contract}`);
  const esbuild = await import("esbuild");
  const started = Date.now();
  const common = {
    bundle: true, write: false, format: "iife", platform: "browser", target: "es2020", logLevel: "silent", legalComments: "none",
    minify: req.minify !== false, define: { "process.env.NODE_ENV": '"production"' }, absWorkingDir: req.out_dir,
  };
  let name, result;
  if (req.target === "host") {
    // Un seul React, un seul Remotion, un seul Player pour toutes les scènes : exposés sur `globalThis.__JARVIS_HOST__`.
    const imports = HOST_MODULES.map((m, i) => `import * as m${i} from ${JSON.stringify(m)};`).join("\n");
    const table = HOST_MODULES.map((m, i) => `${JSON.stringify(m)}: m${i}`).join(", ");
    name = "host.js";
    result = await build(esbuild, { ...common, stdin: { contents: `${imports}\nglobalThis.__JARVIS_HOST__ = { ${table} };`, resolveDir: process.cwd(), sourcefile: "jarvis-host-entry.js", loader: "js" } });
  } else if (req.target === "scene") {
    const modules = req.modules;
    if (!modules || typeof modules !== "object" || !Object.prototype.hasOwnProperty.call(modules, req.entry)) {
      throw fail("compile_entry_invalid", "the entry module is not among the modules");
    }
    name = "scene.js";
    result = await build(esbuild, {
      ...common, jsx: "automatic", plugins: [virtualPlugin(modules, new Set(req.allowed_imports))], globalName: "JarvisScene",
      banner: { js: `/* jarvis-remotion-scene contract=1 digest=${String(req.digest).slice(0, 64)} */` },
      stdin: { contents: `export { default as component } from ${JSON.stringify("./" + req.entry)};`, resolveDir: "/", sourcefile: "jarvis-scene-entry.js", loader: "js" },
    });
  } else {
    throw fail("compile_compiler_failed", `unknown target ${req.target}`);
  }
  const text = result.outputFiles[0].text;
  mkdirSync(req.out_dir, { recursive: true });
  writeFileSync(join(req.out_dir, name), text);
  return { ok: true, files: [{ name, bytes: Buffer.byteLength(text) }], warnings: result.warnings.length, esbuild: esbuild.version, duration_ms: Date.now() - started };
}

async function compileMain(path) {
  const req = JSON.parse(readFileSync(path, "utf8"));
  let report;
  try {
    report = await compile(req);
  } catch (error) {
    report = { ok: false, ...(error && error.compile ? error.compile : { code: "compile_compiler_failed", message: String(error && error.message ? error.message : error).slice(0, 300), diagnostics: [] }) };
  }
  mkdirSync(req.out_dir, { recursive: true });
  writeFileSync(join(req.out_dir, "result.json.tmp"), JSON.stringify(report));
  renameSync(join(req.out_dir, "result.json.tmp"), join(req.out_dir, "result.json"));
  console.log(JSON.stringify({ ok: report.ok, code: report.code }));
  process.exit(report.ok ? 0 : 3);
}

const mode = process.argv[2];
if (mode === "--compile") {
  await compileMain(process.argv[3]);
}
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
    throw new Error("usage: runtime-host.mjs --probe | --serve | --compile <request.json>");
  }
} catch (error) {
  console.error(`probe_failed: ${error && error.message ? error.message : error}`);
  process.exit(2);
}
