# Slice 03 — preuve navigateur (runtime des prefabs)

## Montage

- L'extension Claude in Chrome n'était **pas connectée** pendant la Slice
  (`tabs_context_mcp` : « Browser extension is not connected »). La preuve a
  donc été faite dans un **vrai Chrome** (installé, `--headless=new`, profil jetable) piloté par CDP,
  même méthode que `tests/unit/_workspace_browser.mjs` : `browser_probe.mjs`.
- Core (`python -m jarvis core`, port 18993) et Control Center
  (`python -m jarvis control-center`, port 18994) lancés depuis le worktree
  `bpf`, `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` dans un scratch, visualiseur
  coupé. Les ports 17653/17654 (Jarvis vivant) n'ont pas été touchés. Les deux
  processus ont été arrêtés après le run.
- Bibliothèque de scratch : `test.counter@1` et `test.netprobe@1` publiés
  (`tests/fakes/prefabs.install_version`) — aucun code ne les nomme.
- Page **servie** par le CC (`/`), modules épissés par `ControlCenter.index`.
  Dans la page : `JarvisPrefabHost.createPrefabHost({fetchBundle:
  JarvisPrefabHost.bundleFetcher(fetch), mode:'preview', …})`, trois
  conteneurs de scratch, trois `mount`.

Relance : `node browser_probe.mjs http://127.0.0.1:18994/ "<chrome.exe>" .`

## Résultats (`browser-results.json`, `prefab-runtime.png`)

| Preuve | Observé |
| --- | --- |
| Relais réel | `GET /api/prefabs` 200 (deux lignes) ; `GET /api/prefabs` avec `Origin: null` → 403 `{"code": "forbidden_origin"}` (curl) |
| Paquet par le catalogue | les trois cadres montés depuis `/api/prefabs/{id}/1/bundle` ; `stats.bundles` = 2 (un paquet par version) |
| Attribut sandbox | `["allow-scripts", "allow-scripts", "allow-scripts"]` |
| CSP en tête | `srcdoc` commence par `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy"` (3/3) |
| Origine opaque | `location.origin` dans chaque cadre = `"null"` ; cadres hors processus (cibles `about:srcdoc` attachées) |
| CSP bloque `fetch` | journal du cadre : « Connecting to 'https://example.com/probe' violates the following Content Security Policy directive: "default-src 'none'" … blocked » ; sonde `fetch: blocked (TypeError)` ; `securitypolicyviolation` `connect-src https://example.com/probe` |
| `parent.document` | `parent.document: blocked (SecurityError)` |
| Stockage | `localStorage: blocked (SecurityError)` |
| Popup | `window.open` rend `null` ; journal : « Blocked opening … sandboxed frame whose 'allow-popups' permission is not set » |
| `eval` | `eval: blocked (EvalError)` + violation `script-src eval` |
| Bande d'erreur | `obj_crash` état `error`, bande « Prefab test.netprobe@1 failed: netprobe crash requested » + « Recharger » ; log `scene.prefab_error` (reason `frame`) ; la carte et les deux autres cadres restent utilisables |
| Resize | `onResize` : counter 99 px ; probe 163 → 265 px (la liste grandit après le rejet asynchrone du `fetch`) ; `iframe.style.height` suit |
| Thème / props | `--jv-accent` du cadre = la prop `accent` (`#6fe3a4`, `#ffb85c`, `#ff6b7d`) ; markdown `data.notes` rendu en gras (blocs de l'hôte) |
| Événement, vrai clic | clic CDP (événement de confiance) sur « +1 » : `{event: "incremented", payload: {count: 4}, basis: {count: 3}}` gardé localement (mode aperçu : `postedEvents` 0) ; notify `probed {count: 4}` aussi |

Limite assumée : la scène elle-même ne monte pas encore de cadre (Slice 04) ;
la preuve passe par des conteneurs de scratch de la page réelle, comme le
contrat de Slice le demande.
