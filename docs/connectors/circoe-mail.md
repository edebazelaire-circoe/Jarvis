# Messagerie et Agenda CIRCOE — contrat d'intégration

**Statut : intégré par le runtime générique ; catalogue live à relever (phase B).** Correction de
l'audit du Slice 00 (amendement E1, qui concluait « aucun connecteur ») : la messagerie et l'agenda
CIRCOE passent par le plugin MCP distant **Circuit Toolbox**, déjà documenté et éprouvé hors
connexion dans [mcp/plugins.md](../mcp/plugins.md) §14 (cible de conformité, sans code propre au
fournisseur). Manifeste et politique : [product-connectors.md](../product-connectors.md) ›
*Messagerie et Agenda CIRCOE*.

| Champ | Valeur | Source |
| --- | --- | --- |
| Transport | MCP Streamable HTTP attendu ; seul le `401` est visible sans jeton | `mcp/plugins.md` §14 (phase B pour la confirmation) |
| Adresse (endpoint) | `https://circoetoolbox-server-production.up.railway.app/mcp` ; identifiant `circoetoolbox-server-production` | `mcp/plugins.md` l. 52-53, 133-134, §14 |
| Authentification | OAuth 2.1, découverte RFC 9728/8414, enregistrement dynamique, client public, PKCE S256, `authorization_code` seul (**pas de jeton de rafraîchissement**), aucun point de révocation | `mcp/plugins.md` §14, l. 371-383 |
| Portées | `mail calendar contacts` | `mcp/plugins.md` §14 |
| Identité serveur attendue | À FOURNIR (champ `name` d'`initialize`, phase B) ; l'appariement se fait sur l'endpoint exact | — |
| Inventaire d'outils | Outils `infomaniak.*` ; attesté : `infomaniak.calendar.list_events` (lecture, rappels d'agenda). **Catalogue complet et annotations : À FOURNIR (phase B, HV-07-01)** | `docs/agenda-reminders.md` |
| Risque lecture/écriture | Classement explicite `ConnectorSpec.tool_side_effects` pour le plugin apparié, le reste suit l'annotation (non annoté = destructeur) ; en `presentation` : lecture permise, écriture et envoi refusés en V1 | `product-connectors.md` |
| Sonde de santé | État du plugin dans le registre (`plugin_state`) : `initialize` + `tools/list` à la connexion | runtime générique |
| Onboarding | Ajouter l'adresse, consentement OAuth par l'utilisateur dans le navigateur (Slice 07 pour le produit) | runtime générique |
| Échecs attendus | Jeton échu sans rafraîchissement ⇒ `needs_authorization` (« Reconnecter ») ; serveur injoignable ⇒ `unavailable` | `mcp/plugins.md` §14 |
| Données sensibles | Courriels, rendez-vous, contacts : données personnelles ; contenu cadré comme donnée non fiable au bord du modèle | `product-connectors.md` › *Contenu non fiable* |

## Ce qui reste à fournir (phase B)

Connexion live par l'Humain (HV-07-01), dans un bac à sable : relever le `tools/list` réel (noms,
annotations), l'identité serveur, la forme des résultats ; puis appliquer la procédure de classement
de [product-connectors.md](../product-connectors.md) (une ligne de `tool_side_effects` par outil dont
l'annotation manque, avec sa preuve et un test). Rien n'est classé en lecture sans preuve.
