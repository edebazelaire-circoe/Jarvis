# Messagerie CIRCOE — gabarit de contrat d'intégration (entrée externe attendue, E1/X2)

**Statut : contrat non fourni.** Constat de l'audit (Slice 00, amendement E1) : le dépôt ne contient
**aucun** connecteur de messagerie (ni Gmail, ni IMAP, ni SMTP, ni Microsoft Graph). Le fournisseur,
le protocole et l'authentification sont une entrée externe. Rien n'est inventé ici ; la Messagerie
CIRCOE figure au manifeste ([product-connectors.md](../product-connectors.md)) en
`contract_pending` (« Bientôt disponible »), catégories prévues `mail.read` et `mail.send`.

Remarque : des tests du runtime MCP utilisent un outil fictif `send_mail` sur une adresse de
fixture ; ce n'est pas un connecteur CIRCOE et ne vaut pas contrat.

| Champ | Valeur | Source |
| --- | --- | --- |
| Fournisseur | À FOURNIR (Google Workspace, Microsoft 365, autre) | |
| Protocole / transport | À FOURNIR : API du fournisseur (adaptateur natif) ou serveur MCP (Streamable HTTP attendu) | |
| Adresse (endpoint) | À FOURNIR | |
| Authentification | À FOURNIR : OAuth du compte de l'utilisateur, portées minimales (lecture seule d'abord) | |
| Identité serveur attendue (si MCP) | À FOURNIR : `name` rendu par `initialize` | |
| Inventaire d'outils | À FOURNIR : lecture (chercher, lire), brouillon, envoi ; annotations de chacun | |
| Risque lecture/écriture | Envoi = écriture externe irréversible : confirmation obligatoire (politique `write` / `V2ActionBroker` `EXTERNAL`) | règle produit |
| Sonde de santé | À FOURNIR | |
| Onboarding | À FOURNIR : consentement par l'utilisateur, compte CIRCOE | |
| Échecs attendus | À FOURNIR (jeton révoqué, quota, boîte pleine) et leur état produit | |
| Données sensibles | Courriels = données personnelles ; contenu non fiable, cadré (`connector_content`) | règle produit |

## Point de branchement

- **Si MCP** : comme IGuard ([iguard.md](iguard.md) § *Point de branchement*) : `plugin_match`,
  `integration=remote_plugin`, runtime générique, politique `side_effect` à l'appel.
- **Si API native** (comme `google_calendar.py`) : un adaptateur sous `jarvis/adapters/`, des actions
  Core déclarées au `V2ActionBroker` (lecture `READ_ONLY`, envoi `EXTERNAL` + confirmation), jeton
  scellé par `google_oauth`/`local_secrets`, état lu par `connector_status` (nouveau fait dans
  `ConnectorFacts`).

Dans les deux cas : portées minimales, contenu cadré comme donnée non fiable, aucun envoi sans
confirmation de l'utilisateur.
