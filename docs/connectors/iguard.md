# IGuard — gabarit de contrat d'intégration (entrée externe attendue, X1)

**Statut : contrat non fourni.** Rien de ce qui suit n'est inventé : chaque champ « À FOURNIR »
attend une source vérifiable (documentation d'IGuard, réponse de l'équipe, capture d'un
`initialize` réel). Tant que ce gabarit n'est pas rempli, IGuard figure au manifeste
([product-connectors.md](../product-connectors.md)) en `contract_pending` (« Bientôt disponible »)
et aucun code spécifique à IGuard n'existe.

Contrat générique réutilisé, non répété ici : [mcp/plugins.md](../mcp/plugins.md).

| Champ | Valeur | Source |
| --- | --- | --- |
| Transport | À FOURNIR (Streamable HTTP MCP attendu ; stdio seulement ⇒ décision ci-dessous) | |
| Adresse (endpoint) | À FOURNIR (`https://…`, publique : la politique d'adresses refuse le privé et le bouclage, `mcp/plugins.md` §4) | |
| Authentification | À FOURNIR : OAuth 2.1 découvert (RFC 9728/8414), ou jeton porteur, ou en-tête nommé | |
| Identité serveur attendue | À FOURNIR : `name` (et version minimale) rendus par `initialize` | |
| Inventaire d'outils | À FOURNIR : nom, rôle, annotations `readOnlyHint` / `destructiveHint` de chaque outil | |
| Catégories produit | À FOURNIR (`ToolCategory` existantes ou nouvelles, à ajouter au domaine) | |
| Risque lecture/écriture | À FOURNIR par outil ; la politique de l'édition s'applique telle quelle (écriture : confirmation, destruction : refus) | |
| Sonde de santé | À FOURNIR : `initialize` + `tools/list` suffisent-ils, ou un outil de santé dédié existe-t-il ? | |
| Onboarding | À FOURNIR : qui crée le compte, qui fournit l'URL, consentement OAuth par l'utilisateur ou jeton d'organisation | |
| Échecs attendus | À FOURNIR : codes/limites (quota, jeton révoqué, maintenance) et leur traduction en état produit | |
| Données sensibles | À FOURNIR : ce que les résultats peuvent contenir (données personnelles, secrets) | |

## Point de branchement (quand le contrat est rempli)

1. Renseigner `ConnectorSpec.plugin_match` de `iguard` dans `jarvis/domain/product_connectors.py`
   (`PluginMatch(endpoint_origin="https://…", server_name="…")`) et passer `integration` à
   `ConnectorIntegration.REMOTE_PLUGIN` ; remplir `categories`.
2. L'utilisateur (ou l'onboarding, Slice 07) ajoute le plugin par son URL : runtime générique,
   coffre DPAPI, OAuth/statique, catalogue, appel. L'état du connecteur se lit alors du plugin
   (`plugin_state`).
3. Tests de contrat : un faux serveur rejouant l'`initialize` et le `tools/list` réels (pas
   d'appel au service réel en test), refus des outils d'écriture/destruction en `presentation`,
   cadrage des résultats.

## Transport

- **Streamable HTTP** : runtime générique tel quel. Aucun code de transport propre à IGuard.
- **stdio seulement** : ne pas surcharger le connecteur distant. Choisir explicitement, avec
  l'Humain, entre un adaptateur stdio borné (processus enfant, pas d'accès disque/réseau hors
  besoin) et un pont HTTP local ou distant ; consigner la décision ici.
