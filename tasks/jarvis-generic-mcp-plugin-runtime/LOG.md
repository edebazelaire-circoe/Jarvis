# Execution log

Reserved for implementation agents. Record durable execution notes here as work is actually performed.

## 2026-09-30 — Slice 00 (agent 0)

- Handoff mirrored from Drive (39 files, JSON verified, Google-Doc escaping removed).
- Blind audit + resolved architecture (`docs/06-resolved-architecture.md`), `## Slice 00 contract` appended to SLICE 01–08.
- Baseline at `96a9396`: 322 unit failures from merge `b8c3ba1` losses → D0 fix branch `fix/main-merge-loss-2026-09-30` (in progress). Task branch to be rebased onto it before Slice 01.
- Decisions D0, D-TT, D1–D12, Q2, Q3 recorded in `slices/00-project-manager/READINESS.md`.

## 2026-09-30 — Slice 01 (implémenteur)

- Docs seulement : `docs/mcp/plugins.md` créé (contrat cible plugins + `jarvis-tools`, bornes et codes d'ARCH §5–§9), `docs/mcp/tool-contract.md` amendé (§1 ancres rafraîchies, barehands 16, ligne `jarvis-tools` ; §2 descripteur externe ; §3 ; §4.3 exception Codex + disponibilité plugin ; §5.3 ; §8 routes de gestion, aucune route d'exécution au CC).
- Écarts ARCH relevés (non corrigés, remontés à agent 0) : `CORE_ADAPTER_IMPORT_EXCEPTIONS` vit dans `tests/unit/test_v2_architecture.py:35`, pas `core/v2_app.py` ; la pose des cibles MCP par agent est `_configure_agent` (`control_center.py:1205`).
- `tests/unit/test_mcp_catalog.py` : erreur de collecte `READY_SETTLE_S` (D0, préexistant), aucun code touché.
- Rework QA (Slice 01) : EVIDENCE.md ; ancres historiques de tool-contract revérifiées ; E10 (révocation RFC 7009 best-effort), `stop()` ≤ 5 s, sens plugin d'`advertised` ; E9 corrigé en `codex_local.py:253-273` (ma lecture 252-272 était fausse).

## 2026-09-30 — Slice 02 (implémenteur)

- Livré : domaine `mcp_plugins` + `mcp_endpoint`, ports `mcp_plugins`, migration v4 (`jarvis_state.v4.sql`), `SQLiteMcpPluginRepository` (registre + blobs scellés), `DpapiSealer`/`UnavailableSealer`/`FakeSealer`, `CredentialVault`, `McpPluginService` (CRUD, identifiants statiques, disconnect/remove, reset `connecting`), routes Core `/v1/mcp/plugins*` + `LocalCoreClient`, câblage `v2_app` (+1 exception d'import) et `_run_core_v2` (sealer, `JARVIS_MCP_ALLOW_LOOPBACK_HTTP`).
- Base réelle `data/state/jarvis.sqlite3` en **v2** : preuve v3→v4 faite sur une copie passée d'abord en v3 (EVIDENCE §2). Base vivante jamais ouverte.
- Ajouts signalés (plugins.md mis à jour) : code `mcp_plugin_invalid` 400, codes magasin `mcp_plugin_store_*` 500, `localhost` classé bouclage, `tools` en dicts bornés jusqu'à la Slice 04, `disconnect` remet `auth_strategy=none`. `immediate_transaction` promu dans `sqlite_state` (réutilisé par les Boards).
- 12 assertions épinglées au schéma 3 (Boards, Conversation Events, e2e) suivent maintenant `_SCHEMA_VERSION`.
- Tests : 208 passed / 1 skipped (fichiers de la Slice + architecture + migrations) ; régressions Core : seul échec = `test_brain_delegation` (liste « not yours »).

## 2026-09-30 — Slice 03 (implémenteur)

- Livré : `PolicyTransport` (SSRF résolu, https, 4 Mio, pas de proxy d'env), `JarvisOAuthProvider`/`VaultTokenStorage` (sous-classe du SDK : échéance restaurée, non interactif, Q2, lecture RFC 9207, réenregistrement si `redirect_uri` change, révocation RFC 7009), `SdkRemoteMcpConnector` (Streamable HTTP, requêtes gardées, échecs réduits à un code), normalisation des outils (domaine), cycle de vie `McpPluginService` (tâche propriétaire, connect ≤ 20 s / 202, complete_oauth, reprise, list_changed, démarrage non interactif E12, stop ≤ 5 s, E10), routes `connect`/`refresh`/`oauth/callback`, câblage `_run_core_v2`, faux serveur MCP + AS.
- Écarts (plugins.md à jour) : `max_redirects=20` (httpx compte le flux OAuth comme redirections : 3 cassait tout OAuth) ; `connected` remis à `disconnected` au démarrage ; `plugin` dans les corps de connect ; une autorisation par connect explicite ; `ui_port` = env `JARVIS_UI_PORT`.
- Retour QA S2 item C traité ici (hôtes IPv4 déguisés, IPv4 embarquée dans IPv6, port 0, `%`).
- Piège de test : `sse_starlette` garde un drapeau d'arrêt global par processus ; le faux serveur le remet à zéro à chaque démarrage.
- Tests : 413 + 164 + 31 passed (EVIDENCE.md) ; sentinelle absente des 63 `trace.jsonl` du run.

## 2026-09-30 — Slice 02 rework QA (implémenteur de la Slice 03)

- A : `disconnect` d'un plugin `enabled=True` le laisse `True` (domaine, service, routes). B : un blob DPAPI scellé sans l'entropie `jarvis-mcp-v1` est refusé (Windows). C : traité dans la Slice 03 (`5b934da`). D : plugins.md §2.2 (création, déconnexion complète, `immediate_transaction`, `start()` ne lève pas) et `docs/state-model.md` (v4, `.v3.bak`, 3e utilisateur de `run_serialized`). E : refus de corps/requête `/v1/mcp/*` journalisés `mcp.plugin.refused` (route, code, `plugin_id` ; jamais le corps). F : noms de tests v3 → neutres.

## 2026-09-30 — Slice 04 (implémenteur)

- Livré : `domain/tool_relevance` (BM25F, synonymes FR/EN, racinisation enchaînée), `domain/tool_discovery` (≤ 5 recommandés, 16 Kio, réponse ≤ 24 576 o, curseur `{r,o,h}`, `too_large`), Core `external_tools` / `call` + routes `GET /v1/mcp/tools`, `POST /v1/mcp/tools/call`, passerelle `runtime/tools_gateway_mcp.py` (`tools-mcp`), `TOOLS` dans `SERVERS`, `merge_external` + `/api/mcp/tools` fusionné (Core 2 s, cache par révision).
- Budgets mesurés : deux outils 1 544 o, consignes 584 o ; `list_tools` réel 10,7–13,1 Ko. Recall@3 = 0,923 sur 26 intentions (deux ratés gardés et documentés).
- Écarts (plugins.md §13) : racinisation enchaînée, `recommended` en première page seulement, `e0` sans Core, `timeout_s` facultatif sur la route d'appel, `unchanged` ⇒ listes vides, masquage des paires `token=…` (fuite trouvée par le test de bout en bout).
- Tests amendés délibérément : méta-outil (C5), listes de serveurs du catalogue/CC (+`jarvis-tools`, +`plugins` sans Core), inspecteur JS (onglet Général non vide, copie « aucun outil de catalogue » corrigée).
- Tests : 579 + 151 + 165 + 32 + 88 passed (EVIDENCE.md) ; un flake de délai de la Slice 03 sous charge, repassé.
