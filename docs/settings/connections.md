# Réglages : Connexions

**Statut :** contrat canonique (niveau 3 : section enregistrée + tests).
**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 07.
**S'appuie sur :** [`navigation-registry.md`](navigation-registry.md) (catégories, sections, alias),
[`settings-shell.md`](settings-shell.md) (montage, `destroy`, liens internes), le magasin de clés
`jarvis/runtime/credentials.py` (inchangé).

La catégorie `connections` gère les identifiants des fournisseurs, une carte par fournisseur. Elle remplace l'onglet
« API Keys » ; son ancien ID `keys` n'est plus un alias depuis la Slice 09 (aucun appelant) : on ouvre `providers`.

## 1. Section

| Section | Libellé | Enregistrée par | `save` | Alias |
| --- | --- | --- | --- | --- |
| `providers` (order 10) | Fournisseurs | `control_center.html` (`CONNECTIONS_SECTION`), rendu par `control_center_connections_settings.js` (`window.JarvisConnectionsSettings`) | `self` (pied caché) | `keys` |

Le module est inséré dans la page par `control_center.py` (`CONNECTIONS_SETTINGS_SCRIPT_FILE`).

## 2. Ce que montre une carte

La liste des fournisseurs, leur libellé, l'exemple de valeur (`placeholder`) et la note d'usage viennent de l'état servi
par le magasin (`credentials_state` : `providers`, `credentials`, `bindings`, `environment`), lu dans la lecture des
réglages à l'ouverture (`SET.data.credentials`), sinon par la route de lecture des clés. Aucune liste n'est copiée dans
la page : un fournisseur ajouté à `PROVIDERS` côté serveur a sa carte sans changer le front.

| Élément | Source | Règle |
| --- | --- | --- |
| Identité | `providers[].label` | titre de la carte, `id="connection_<fournisseur>"`, titre focalisable (`connection_<fournisseur>_title`) |
| Note d'usage (capacité JARVIS) | `providers[].hint` | affichée telle quelle ; absente si le serveur n'en donne pas |
| État | clés du fournisseur, `environment[<fournisseur>]` | « Clé enregistrée » (ok) ; sinon « Variable d'environnement » (avertissement) ; sinon « Non configuré » (neutre) — toujours un mot, jamais la couleur seule |
| Clé active | `credentials[].bound` | bouton radio coché + badge « Active » ; choisir une autre clé = liaison |
| Clés enregistrées | `credentials[]` (`name`, `hint`) | nom + indice `…abcd` ; « Remplacer la valeur », « Supprimer » |
| Retombée sur l'environnement | `environment[<fournisseur>]` (noms seulement) | « Utilise la variable … tant qu'aucune clé n'est enregistrée ici » ou, si une clé existe, « en réserve, la clé enregistrée passe avant » ; jamais la valeur |
| Ajouter une clé | formulaire nom + valeur (`type=password`) dans une divulgation | — |

Pas de sémantique OAuth : un fournisseur à clé API n'a ni « connexion » ni « déconnexion », seulement des clés rangées.

## 3. Écritures (routes et charges du magasin inchangées)

| Action | Requête | Charge, clé par clé |
| --- | --- | --- |
| Ajouter | POST, route d'enregistrement des clés | `{provider, name, value}` |
| Remplacer la valeur | POST, même route (mise à jour par `id`, déjà offerte par le magasin) | `{id, provider, name, value}` (le nom actuel, la nouvelle valeur) |
| Choisir la clé active | POST, route de liaison | `{provider, id}` |
| Supprimer | POST, route de suppression, après confirmation sur place (« Supprimer » / « Annuler ») | `{id}` |

Chaque réponse porte l'état complet : il remplace `SET.data.credentials` et vide les catalogues de modèles de la page
(une clé peut ouvrir un catalogue), même si la section a été quittée entre-temps (l'état est vrai côté serveur). Seule
une vue encore montée se redessine (`isCurrent`) : une réponse arrivée après un changement de section ou la fermeture
ne touche à rien.

Pendant une écriture, les commandes de la section sont désactivées et la région d'état dit ce qui se passe
(« Enregistrement de la clé OpenAI… »). Au-delà de 15 s sans réponse (`WAIT_MS`), la région d'erreur le dit, la
section rend la main et invite à relire l'état. `destroy` (changement de section ou de catégorie, fermeture) arrête ce
minuteur.

Focus après action : la nouvelle clé (ajout), la clé remplacée ou liée, le titre de la carte (suppression) ; le bouton
« Supprimer » de confirmation à l'ouverture de la confirmation, le bouton « Supprimer » d'origine après « Annuler ».

## 4. Secrets

- Le serveur ne renvoie jamais une valeur, seulement l'indice (`redact` : `…` + quatre derniers caractères) ; la page
  n'affiche que lui.
- Une valeur saisie est lue puis effacée de son champ **avant** l'envoi ; après un refus, le nom reste, la valeur est à
  recoller.
- Aucune valeur dans un message, un attribut, la console ou un journal : les journaux de la page
  (`connections_credential_written` info, `connections_credential_slow` avertissement, `connections_credential_failed`
  et `connections_read_failed` erreur) ne portent que l'action, le fournisseur, le code et le statut HTTP.
- Les variables d'environnement sont citées par leur nom.

## 5. Régions vivantes

`#connectionsStatus` (`role=status`, poli) : en cours et issue d'une action. `#connectionsError` (`role=alert`) : refus
du serveur avec son message réel (par exemple doublon de nom), attente dépassée. Vides, elles ne prennent pas de place.

## 6. Liens entrants

| Depuis | Lien | Atterrit |
| --- | --- | --- |
| `agents_models` › Agent principal (aide du modèle principal) | « Connexions › <fournisseur> » (`data-settings-open="providers"`, `data-settings-focus`) | section Fournisseurs, focus sur le titre de la carte du fournisseur du modèle |
| `memory_knowledge` › Recherche sémantique, Sources de connaissances (ligne du secret) | « Connexions » (`data-mem-open="providers"`) | section Fournisseurs |

Les messages du serveur qui demandent une clé (pile vocale sans clé, catalogue sans clé, mémoire) disent
« Réglages › Connexions ».

## 7. Tests

- `tests/unit/test_control_center_connections_settings_js.py` (node, vrai `credentials_state`) : une carte par
  fournisseur servi dans l'ordre du serveur, note = `hint`, états, clé active, retombée, aucun secret, champs valeur
  `password` vides, régions vivantes, confirmation, aucun fournisseur ni variable copiés dans le module.
- `tests/unit/test_connections_settings_browser.py` (vrai Chrome, vrai Control Center isolé) : navigation, ancien ID `keys` retiré, liens
  entrants, charges des quatre écritures figées clé par clé, fichier du runtime, aucune valeur dans le DOM, les champs
  ni les lectures, refus, réponse tardive (section quittée, fermeture), attente bornée et minuteur arrêté par `destroy`,
  débordement à 1920×1080, 1366×768, 100 % et 125 %.
- `tests/unit/test_control_center_settings_registry_js.py` (`SLICE_07_SECTIONS`, ID retirés),
  `tests/integration/test_settings_redesign_migration.py` (plus de `TABS`).
