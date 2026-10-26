# Slice 05 — notes d'implémentation

Branche `task/jarvis-presentation-edition-v1-s05` (worktree `pev1c`), depuis `24d6d86a`. Le LOG de
la tâche n'est pas édité ici (worktree parallèle du Slice 03) : l'orchestrateur reprend ces notes.

## Conception

- **Une seule source** : `jarvis/domain/product_connectors.py`, `connector_policy(edition)` dérivée de
  l'édition du Slice 01 (`CONNECTOR_POLICIES` indexée par `ProductEdition`). Consommée par Core
  (`McpPluginService`), la route de statut et `jarvis-drive`.
- **Manifeste** : Google Drive, Recherche documentaire (suit Drive), Agenda CIRCOE (Google Agenda,
  compte à confirmer), Messagerie CIRCOE et IGuard en `contract_pending` (aucun endpoint, aucun nom
  d'outil). Tous `optional`.
- **États produit** : `ready`, `not_configured`, `needs_authorization`, `unavailable`, `disabled`,
  `contract_pending`, avec libellé et action sans jargon MCP. Route `GET /v1/edition/connectors`,
  relais `GET /api/edition/connectors` (Slice 07 : onboarding/santé ; la tâche
  `jarvis-connections-services-mcp-settings-ui` garde l'écran).
- **Politique `side_effect` à l'appel (E10)** : dans `McpPluginService.call` et `invoke`, avant
  arguments et réseau. `presentation` : `read` permis, `write` refusé
  `mcp_tool_confirmation_required`, `destructive`/non annoté refusé `mcp_tool_side_effect_refused`
  (403) ; outils refusés retirés de `GET /v1/mcp/tools` (`withheld_tool_count`). `full` inchangé.
- **Cadrage anti-injection** : `jarvis/domain/connector_content.py` (avis + marqueurs à jeton
  aléatoire par bloc, imitations neutralisées), appliqué en `presentation` aux résultats d'outils
  distants (Core) et à `drive_read` (`jarvis-drive`, qui reçoit désormais l'édition dans son
  `--mcp-config`).
- **Secrets (E3)** : `jarvis/runtime/local_secrets.py`. Actif si édition `presentation` ou produit
  installé. Clés API : entrées `sealed` + `hint` (DPAPI, entropie `jarvis-credentials-v1`), scellées
  à chaque `ControlCenter._write_settings` ; migration copie d'abord au démarrage du Control Center
  (sauvegarde scellée du fichier entier, jamais écrasée, relue ; valeurs scellées relues ; puis
  retrait du clair) ; `.env` du produit installé repris puis nettoyé. Jetons Google : `<jeton>.dpapi`
  (entropie `jarvis-google-oauth-v1`), copie d'abord. Coffre absent : rien migré, écriture d'un clair
  refusée 503 `credential_vault_unavailable`. Dev `full` : en clair comme avant, lit le scellé.
- **Drive** : source/export explicite, jamais canonique. Portées produit `drive.readonly` +
  `drive.file`, Agenda `calendar.events`. Changer de portée **redemande un consentement** (jeton
  existant aux portées complètes) ; dev inchangé.
- `DpapiSealer(entropy=…)` : paramètre ajouté, défaut inchangé (`jarvis-mcp-v1`).
- Aucune table, aucune migration de schéma.

## Écarts / décisions prises sans l'Humain (option recommandée)

- `confirm` refuse faute de canal de confirmation à l'appel en V1 (un canal lié à l'appel, non
  affirmable par l'appelant, est à concevoir ; la table ne changera pas).
- Recherche documentaire = recherche/lecture dans le Drive relié (aucun index local n'existe sous ce
  nom) ; à confirmer.
- Cadrage et filtrage seulement en `presentation` pour garder `full` à l'identique (consigne du
  contrat). Le cadrage pourrait être étendu à `full` plus tard.
- Route de statut non gardée (`READ_GUARDED_ROUTES`) comme `/api/boards/edition` : aucun secret ni
  adresse de plugin.
- Un produit installé lancé en `full` scelle quand même et prend les portées minimales.

## Entrées externes (bloquent seulement leur part)

- X1 IGuard : `docs/connectors/iguard.md` (gabarit + point de branchement `ConnectorSpec.plugin_match`).
- X2/E1 Messagerie CIRCOE : `docs/connectors/circoe-mail.md`.
- E1 Agenda : le compte CIRCOE est-il Google Workspace ?

## Risques

- Annotations MCP mensongères (`readOnlyHint` sur un outil qui écrit) non détectables.
- Le cadrage réduit l'injection, ne la supprime pas ; la ligne dure est le refus à l'appel.
- DPAPI CurrentUser ne protège pas contre un processus malveillant du même utilisateur.
- `SECURITY.md` § 23 et `docs/mcp/plugins.md` §8.2 : risque de conflit de fusion avec le Slice 03
  (même zone du fichier).
- Échec de construction du backend Drive/Agenda au démarrage de Core : comportement inchangé
  (`RuntimeError` au démarrage) ; un état `unavailable` actionnable pour ce cas reste à faire
  (Slice 07, santé).

## Tests

- Nouveaux : `tests/unit/test_product_connectors.py` (30), `tests/unit/test_local_secrets.py` (19).
- Existants relancés verts : mcp_plugin_service/domain/store, tools_gateway_mcp, drive, dpapi_sealer,
  credential_vault, mcp_secret_sentinel, product_edition, remote_mcp_adapter, mcp_protocol_routes,
  board_protocol, v2_calendar, control_center_mcp_plugins_api/js, mcp_oauth_adapter, mcp_http/endpoint
  policy, schema_migrations, memory_settings, settings_workbench, connections_settings_js, app,
  action_broker, v2_policy, workspace_mcp, prompt_registry, mcp_catalog, installed_product_root…
- Échecs présents avant cette Slice (non dus à elle) : `test_app::…tools_gateway_target…`,
  `test_brain_capability_parity` (`ui_intent_publish`), `test_control_center_mcp_api` (5 tests :
  `jarvis-display` compte 21 outils au lieu de 20, changement du Slice 02 `f239e91c`).
  `test_connections_settings_browser` (3 tests, `focus` sur un élément absent du DOM) : échoue
  aussi sur `24d6d86a` sans cette Slice (vérifié dans un worktree jetable, supprimé).

## À éprouver en runtime (bac à sable, jamais le JARVIS vivant)

1. Core + Control Center d'un bac à sable avec `JARVIS_PRODUCT_EDITION=presentation`, ports et
   `JARVIS_DATA_ROOT`/runtime propres : `GET /api/edition/connectors` (états), un
   `control-center-settings.json` avec une clé sentinelle en clair ⇒ scellé au démarrage, sauvegarde
   `.plain-backup.dpapi`, Voice démarre avec la clé.
2. Faux serveur MCP (`JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`) avec un outil lecture, un écriture, un non
   annoté renvoyant un texte hostile : `list_tools` ne montre que la lecture ; trace agent (`agent-
   trace-analysis`) : le cerveau lit le résultat cadré, ne tente pas l'écriture demandée par le
   texte ; s'il la tente, `mcp.plugin.tool_policy_refused` et rien n'est envoyé.
3. `jarvis-drive` en `presentation` avec un document hostile (compte de test) : `drive_read` cadré.
4. Passage d'un jeton Drive aux portées minimales : consentement redemandé, jeton `.dpapi`, plus de
   JSON en clair.
