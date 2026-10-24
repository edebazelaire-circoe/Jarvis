# Memory settings (backend model and persistence)

Slice 10a of `jarvis-memory-intelligence-knowledge`. Model: `jarvis/domain/memory_settings.py`
(dataclasses, defaults, combination rule). Persistence and description:
`jarvis/runtime/memory_settings.py`. Endpoints: Slice 10b below. Settings UI: Slice 05 of
`jarvis-settings-ui-reorganization` below (one settings section per field, served as `surface`).

## Storage

A new top-level key `memory` in `control-center-settings.json`. No new file and
no migration (D6). Secrets are never stored there; see Secrets.

## Entry points

| Function | Contract |
| --- | --- |
| `read_memory_settings(raw, environ=None)` | Tolerant. Effective settings (env > file > default). Never raises, whatever the file or env holds. |
| `stored_memory_settings(raw)` | File only, env ignored. Base of a write. |
| `effective_memory_settings(raw, environ=None)` | Per field `{value, source}`, source `default\|file\|env`; `downgraded` carries a compatibility code. |
| `validate_memory_settings_write(raw, stored=None)` | Strict, whole request. Raises `MemorySettingsError(code, message, field)`. Payload is a patch over `stored`. |
| `apply_memory_settings(settings, payload)` | Validate, then set `settings["memory"]`. On refusal `settings` is untouched. |
| `describe_memory_settings()` | Schema served to the UI: types, ranges, enums, defaults, env names, compatibility rules. The UI hard-codes none of it. |
| `memory_state(settings, environ=None)` | `values`, `effective`, `downgraded` (`{path: code}`), `secrets` (`has_secret` per leg). Never raises. |

## Schema

| Path | Type | Default | Range / values | Env |
| --- | --- | --- | --- | --- |
| `recall.enabled` | bool | `true` | | `JARVIS_MEMORY_RECALL_ENABLED` |
| `recall.max_items` | int | `6` | 1..10 | `JARVIS_MEMORY_RECALL_MAX_ITEMS` |
| `recall.timeout_ms` | int | `400` | 100..1500 | `JARVIS_MEMORY_RECALL_TIMEOUT_MS` |
| `semantic.enabled` | bool | `false` | | `JARVIS_MEMORY_SEMANTIC_ENABLED` |
| `semantic.provider` | enum | `none` | `none`, `openai` | `JARVIS_MEMORY_SEMANTIC_PROVIDER` |
| `semantic.allow_private` | bool | `false` | | `JARVIS_MEMORY_SEMANTIC_ALLOW_PRIVATE` |
| `consolidation.mode` | enum | `manual` | `manual`, `auto` | `JARVIS_MEMORY_CONSOLIDATION_MODE` |
| `consolidation.auto_min_confidence` | float | `0.8` | 0..1 | `JARVIS_MEMORY_CONSOLIDATION_AUTO_MIN_CONFIDENCE` |
| `consolidation.max_candidates_per_run` | int | `20` | 1..100 | `JARVIS_MEMORY_CONSOLIDATION_MAX_CANDIDATES_PER_RUN` |
| `tencent.enabled` | bool | `false` | | `JARVIS_MEMORY_TENCENT_ENABLED` |
| `tencent.url` | text | empty | http(s), max 512, no userinfo, query or fragment | `JARVIS_MEMORY_TENCENT_URL` |
| `tencent.service_id` | id | empty | short identifier, not a secret | `JARVIS_MEMORY_TENCENT_SERVICE_ID` |
| `tencent.allow_private` | bool | `false` | | `JARVIS_MEMORY_TENCENT_ALLOW_PRIVATE` |
| `knowledge.wiki_enabled` | bool | `true` | | `JARVIS_MEMORY_KNOWLEDGE_WIKI_ENABLED` |
| `knowledge.codegraph_enabled` | bool | `true` | | `JARVIS_MEMORY_KNOWLEDGE_CODEGRAPH_ENABLED` |
| `knowledge.skills_enabled` | bool | `true` | | `JARVIS_MEMORY_KNOWLEDGE_SKILLS_ENABLED` |

Defaults and ranges come from the domain module; the runtime table copies none.
Types are strict on write: a bool is not an int, `"3"` is not `3`.

## Precedence

Per field: environment variable, then file, then default. An empty or
unparsable variable is ignored (the file value stays). Integer variables are
ASCII digits only, at most 18 digits (optional sign). Env booleans accept
`1/true/yes/on` and `0/false/no/off`. A write never captures an env value into
the file.

## Compatibility matrix

| When | Requires | Write (strict) | Read (tolerant) |
| --- | --- | --- | --- |
| `semantic.enabled` | `semantic.provider != none` | `memory_settings_semantic_needs_provider` | `semantic.enabled` forced `false` |
| `consolidation.mode = auto` | `semantic.enabled` | `memory_settings_auto_needs_semantic` | `consolidation.mode` forced `manual` |
| `tencent.enabled` | non-empty `tencent.url` | `memory_settings_tencent_needs_url` | `tencent.enabled` forced `false` |

Rules are checked in this order on the merged result, and also degrade in this
order on read (semantic first, because auto consolidation depends on it).
Disabling every optional leg leaves canonical memory usable.

## Error codes (stable)

`memory_settings_bad_payload`, `memory_settings_bad_section`,
`memory_settings_bad_type`, `memory_settings_out_of_range`,
`memory_settings_bad_enum`, `memory_settings_bad_url`,
`memory_settings_secret_refused`, plus the three compatibility codes above.
Messages carry the field path, never the offending value. A write raises only
`MemorySettingsError`; a payload nested deeper than 16 levels is refused with
`memory_settings_bad_payload`.

Slice 10b must surface `memory_state(...)["downgraded"]` (and the per-field
`downgraded` in `effective`) in its `status` section: it is the only signal that
a hand-edited file or an env var asked for an incompatible combination.

## Write semantics

- Whole-request: any invalid field refuses everything; nothing is written.
- Patch: absent fields keep their stored value. A write persists every known
  field of the block, normalised (url trimmed, confidence as float, defaults
  written explicitly), not only the fields sent. Env values are never captured:
  a write neither validates against nor persists the environment.
- Unknown top-level, section and nested keys are preserved (stored and sent).
- `has_secret` may be sent back by a UI round trip; it is dropped at any depth, never written.

## Secrets

Tokens live in `credentials` only: `semantic` uses provider `openai`, `tencent`
uses provider `tencent` (env fallback `JARVIS_TENCENT_TOKEN`). The `memory`
block refuses, at any depth and inside lists, a key whose words or stem name a
secret (token, secret, password, passwd, pwd, passphrase, auth, authorization,
bearer, credential, api/private/access/secret/ssh key; counters such as
`max_tokens` are allowed). It also refuses a URL carrying userinfo, and a URL
carrying a query string or fragment (`memory_settings_secret_refused`), since
those are where tokens end up. URLs also reject spaces and control characters
(`memory_settings_bad_url`). Payloads expose `secrets.<leg>.has_secret`
only, never a value or a hint.

## Loadouts (`memory.loadouts`, Slice 09)

Per-agent knowledge rules, owned by Slice 09 (resolver in
`jarvis/core/loadout_resolver.py`, contract in
[`../skills-and-loadouts.md`](../skills-and-loadouts.md)). Displayed by 10b, 11 and 12.
Not a flat field, so it is not in `schema.sections`; `describe_memory_settings()["loadouts"]`
serves its profiles, roles, field list and rule cap, and `memory_state()["loadouts"]` the
valid stored rules. No environment variable.

```json
{"memory": {"loadouts": {
  "code":          {"memory_scopes": ["shared", "project:jarvis"], "codegraph": true},
  "code:reviewer": {"memory_scopes": ["shared"], "skills": false}
}}}
```

| Part | Contract |
|---|---|
| key | `<profile>` or `<profile>:<role>`; profile in `desktop`, `code`, `fast`, `general`, `brain`; role in `coder`, `reviewer`, `research`. At most 20 rules |
| `memory_scopes` | list of `private`, `shared`, `board:<id>`, `project:<id>`; at most 64, no repeat. Default `[]` (a rule replaces the preset: say what is allowed) |
| `allow_private` | bool, default `false`. `private` in `memory_scopes` requires it |
| `wiki`, `codegraph`, `skills` | bool, default `true`: whether that kind is delivered |

Entry points: `read_loadout_policy(block) -> LoadoutPolicy` (tolerant, file only, never
raises) and the existing `apply_memory_settings` / `validate_memory_settings_write`.

- **Patch per key.** `{"loadouts": {"code": {"wiki": false}}}` changes only `wiki` of the
  stored `code` rule (a missing or corrupt rule starts from the defaults above). `null`
  removes the rule: the preset applies again. Keys and entries not in the request are
  kept exactly as stored, readable or not.
- **Whole-request, strict.** Unknown keys, unknown fields in a rule, wrong types, bad
  scopes, repeats and a private scope without `allow_private` refuse the request with
  nothing written (codes below). Rule fields are not preserved when unknown: a typo such as
  `allow_privat` must fail, not silently deny.
- **Tolerant read.** A stored rule that is corrupt, names an unknown key or breaks the
  private rule is ignored, so the built-in preset (which never gives private memory to a
  sub-agent) applies. Reading never raises.
- **Secrets.** The scan of the whole payload applies unchanged: a key such as `token` or
  `api_key` inside a rule is `memory_settings_secret_refused`.

New stable codes: `memory_settings_bad_loadout_key`, `memory_settings_bad_loadout`,
`memory_settings_bad_scope`, `memory_settings_private_needs_allow`
(`memory_settings_bad_type`, `memory_settings_out_of_range` and
`memory_settings_bad_section` also apply).

## Endpoints (Slice 10b)

Code: `jarvis/runtime/memory_relay.py`, registered in `jarvis/runtime/control_center.py`.

- `GET /api/settings` gains a `memory` section: `schema` (`describe_memory_settings`), `values` (file only),
  `effective` (value and source `default|file|env` per field, plus `downgraded` when a hand-edited incoherent
  combination was cut on read), `downgraded` (`{path: code}`), `secrets` (`has_secret` per leg, never a value),
  `loadouts`, and `status`.
- `status` is derived from the settings alone, no network: per leg `status` (`ok|disabled|unavailable`),
  `reason_code`, `reason`, `how_to_fix` (`lexical`, `recall`, `semantic`, `tencent`, `knowledge:wiki|codegraph|skills`),
  the `downgraded` map, `restart_required` (semantic and Tencent settings apply at the next Core start; recall,
  budgets and knowledge toggles apply at the next turn) and `live`.
- `POST /api/settings` with a `memory` patch validates the whole request, then writes atomically. A refusal is a
  400 with the stable code in the `X-Settings-Error-Code` header (`memory_settings_*`, journal
  `settings.agent.rejected`), and nothing is written.
- `GET /api/memory/{notes,notes/{id},search,status,recall-explain,candidates}` relays Core `/v1/memory/*` as is
  (read only, loopback guard on every method). `/api/memory/status` is the live per-leg state (sidecar
  unreachable, index syncing, wiki without sources).
- `memory.tencent.service_id` (identifier, empty: no `x-tdai-service-id` header) and `memory.tencent.allow_private`
  (default false) feed `register_retriever` and the mirror sink at Core start.
- Hooks served for Slices 11 and 12: `control_center_memory_settings.js` (`#memorySettingsMount`) and
  `control_center_memory.js` (`#memoryCenterMount`).

## Interface (Slice 11)

Historique : un onglet **Memoire** des Reglages, monte dans `#memorySettingsMount`. Remplace par la categorie
**Memoire & connaissances** (section suivante) ; le module, sa lecture et son correctif sont les memes.

## Reglages a six categories (jarvis-settings-ui-reorganization, Slice 05 ; refonte-ui-settings, Slices 05/06)

La categorie `memory_knowledge` (« Memoire & connaissances ») a **trois onglets**, maquette
`tasks/refonte-ui-settings/references/ui/04-memory-settings.png` : **Memoire** (section `recall`),
**Connaissances** (`knowledge_sources`) et **Memory Center** (`memory_center`). Les reglages d operateur vivent dans
**Avance & diagnostic › Memoire** (`memory_advanced`, groupe Architecture & compatibilite). Enregistrement :
`MEMORY_SECTIONS` et `installMemorySettingsSections` dans `control_center.html` ; Avance & diagnostic porte aussi la
partie **Memoire** de la section `diagnostics` (`registerSettingsDiagnostic`).

- **Destination servie par le serveur.** Chaque champ du schema porte `surface = {category, section}`
  (`SURFACE_SECTIONS` : section -> categorie, `_SURFACE` par section du bloc, `_FIELD_SURFACE` pour un champ qui
  s en ecarte, dans `memory_settings.py`) ; les loadouts aussi (`schema.loadouts.surface`). Une section du bloc sans
  destination leve `RuntimeError`. La page range les champs par `surface.section` : aucune liste de champs dans le
  navigateur. Valeurs, precedence env/fichier/defaut et charge utile inchangees.
- **Champs ordinaires vs champs d operateur.** Onglet Memoire : rappel (actif, souvenirs par tour), recherche
  semantique (active, fournisseur, memoire privee), consolidation (mode, seuil de confiance, candidats par passe).
  Avance › Memoire : `recall.timeout_ms` (delai brut en millisecondes) et tout le sidecar Tencent (URL, identifiant
  d instance, memoire privee, activation). Rien de cela n est retire : une seule place editable par champ.
- **Libelles servis.** Options et libelles viennent du schema (`Aucun` / `OpenAI` pour le fournisseur — les deux
  seuls existants —, `Manuelle` / `Automatique` pour la consolidation) ; le navigateur n en code aucun.
- **Une seule place editable par champ** (table ci-dessous, verifiee par
  `tests/unit/test_memory_settings_surface.py`).
- **Enregistrement.** Les onglets Memoire et Connaissances et la section Avance › Memoire portent la barre
  « Enregistrer la mémoire » (`save: 'self'`) : `{memory: {<section>: {<champ>: valeur}}}`, les seuls champs
  modifies. Le brouillon est partage le temps d une ouverture des Reglages (`memorySettingsStore`, une lecture) :
  une regle de compatibilite peut ramener un champ d un autre onglet (couper la recherche semantique remet la
  consolidation en manuelle) ; la barre le dit (« Enregistre aussi les changements en attente… ») et l envoi
  porte tout le brouillon. Barre collante en bas tant que le brouillon n est pas vide.
- **Moment d application** lu dans `status.restart_required` : la carte Recherche semantique dit « Au prochain
  démarrage de Core » ; avis « Redemarrage de Core necessaire pour … » tant qu un tel champ est en attente, puis
  rappel apres l enregistrement.
- **Etat vivant** (`loadLive` de `JarvisMemorySettings.create`) : une lecture par ouverture de `/api/memory/status`,
  `/api/memory/notes?limit=200` et `/api/memory/candidates?state=proposed&limit=200`. Il nourrit la ligne
  « Memoire canonique » du resume, les compteurs de l entree du Memory Center (« 200+ » au-dela d une page de 200)
  et l etat reel des sources. Core muet : « — indisponible », « Compteurs indisponibles : <raison reelle> », bouton « Réessayer », jamais un
  chiffre invente.
- **Cycle de vie.** Chaque montage cree une vue ; quitter la section l a detruite (`destroy`) : elle ne dessine plus
  rien et une reponse tardive est ignoree.
- **Alias.** `memory` (ancien onglet ; Memory Center › Reglages) ouvre `recall`. `semantic_retrieval` et
  `consolidation` (anciennes sections, fondues dans l onglet Memoire) ouvrent aussi `recall`
  ([`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md)).

### Onglet Memoire (vue `memory`)

Deux colonnes (une seule sous 720 px de large, requete de conteneur) :

| Carte | Contenu | Donnees |
| --- | --- | --- |
| Rappel | interrupteur, curseur « Souvenirs injectés par tour » (n / max) | `recall.enabled`, `recall.max_items` (bornes servies) |
| Consolidation | modes Manuelle / Automatique (Automatique indisponible sans recherche semantique), seuil de confiance (%), nombre maximum de candidats | `consolidation.*` |
| Recherche semantique | interrupteur, fournisseur, presence de la cle (jamais la valeur, lien Plugins & MCP › Fournisseurs), memoire privee | `semantic.*`, `secrets.semantic.has_secret`, `status.legs.semantic` |
| Resume du systeme memoire | Memoire canonique (etat vivant du `store`), Rappel (par mots / + semantique / desactive), Consolidation, Memoire privee (reste sur ce PC / envoyee a …) ; chaque ligne mene a sa carte ou au Memory Center | etat ENREGISTRE (`effective`, `status.legs`) + `/api/memory/status` |
| Ouvrir le Memory Center | tuiles Notes (nombre), Candidats (en attente), Test de rappel | etat vivant |
| Avance & diagnostic | bandeau secondaire : « Ouvrir les paramètres avancés » (Avance › Memoire), « Voir le diagnostic mémoire » | `status` (nombre de points a verifier) |

Ecarts voulus a la maquette : pas de **profil de rappel** Rapide / Equilibre / Approfondi (aucun reglage reel
derriere ; un preset decoratif est interdit par le contrat), le maximum du curseur est la borne servie (10, pas 20),
pas de ligne « Portees » inventee (remplacee par « Memoire privee », reelle) ; le resume est un etat, jamais une
seconde copie editable.

### Onglet Connaissances (vue `knowledge`)

Une carte par source (Wiki, Graphe de code, Skills) : interrupteur de preference et pastille d etat qui croise la
preference et l etat vivant de Core — **Actif** (Core la declare saine), **Désactivé**, **Indisponible** (aucun
fournisseur monte, comme le graphe de code tant qu aucun depot n est branche, ou etage degrade avec sa raison) ou
**État inconnu** (Core injoignable : jamais « Actif » par defaut). Puis les portees en langage produit (explicatif),
les regles d acces par agent en lecture seule (l editeur graphique des loadouts est hors champ) et un renvoi vers la
source externe Tencent (Avance › Memoire).

| Champ | Section |
| --- | --- |
| `recall.enabled` | `recall` · Mémoire |
| `recall.max_items` | `recall` · Mémoire |
| `recall.timeout_ms` | `memory_advanced` · Avancé › Mémoire |
| `semantic.enabled` | `recall` · Mémoire |
| `semantic.provider` | `recall` · Mémoire |
| `semantic.allow_private` | `recall` · Mémoire |
| `consolidation.mode` | `recall` · Mémoire |
| `consolidation.auto_min_confidence` | `recall` · Mémoire |
| `consolidation.max_candidates_per_run` | `recall` · Mémoire |
| `tencent.enabled` | `memory_advanced` · Avancé › Mémoire |
| `tencent.url` | `memory_advanced` · Avancé › Mémoire |
| `tencent.service_id` | `memory_advanced` · Avancé › Mémoire |
| `tencent.allow_private` | `memory_advanced` · Avancé › Mémoire |
| `knowledge.wiki_enabled` | `knowledge_sources` · Connaissances |
| `knowledge.codegraph_enabled` | `knowledge_sources` · Connaissances |
| `knowledge.skills_enabled` | `knowledge_sources` · Connaissances |
| `loadouts` (lecture seule) | `knowledge_sources` · Connaissances |

Section `memory_center` · Memory Center (`save: 'readonly'`) : voir « Memory Center » plus bas. Tests :
`tests/unit/test_control_center_memory_settings_js.py` (module et cycle de vie de la page),
`tests/unit/test_memory_settings_surface.py`, `tests/unit/test_control_center_settings_registry_js.py`
(alias), `tests/unit/test_memory_settings_browser.py` (vrai Chrome, faux Core `_memory_center_fixture.py`).

## Memory Center (Slice 12)

Guide d usage et decisions UX. Ouverture : bouton "Ouvrir le Memory Center" de la section Centre memoire (Memoire & connaissances), ou bouton "Memory Center" de Sessions & Boards (`JarvisMemoryCenter.open`, `control_center_memory.js`, monte dans `#memoryCenterMount`, il remplace les onglets du workspace tant qu il est ouvert ; Echap ferme d abord une confirmation, puis la vue). Cinq onglets : **Notes** (liste canonique, recherche = index derive, detail avec abstraction L0-L3, retention, type et portee sur des lignes separees, provenance, version, conflits, corps), **Candidats** (propositions non rappelees ; accepter/rejeter apres confirmation via `POST /api/memory/candidates/{id}/decision`, seule ecriture, relayee par `memory_relay.py`), **Sante des index** (`/api/memory/status`, chaque etage degrade explique avec son effet), **Connaissances** (Wiki/graphe/Skills et loadouts, lecture seule) et **Test de rappel** (`recall-explain`, "pourquoi rappelee", rien n est ecrit). Decisions : chaque zone porte une pastille Canonique / Derive / Proposition ; aucune action de reconstruction n est proposee (aucune route Core ne l expose). Les assets Wiki/Skills ne sont pas listes un a un : Core n expose que leur etat. Test : `tests/unit/test_control_center_memory_js.py`.

Le Memory Center est monte dans le gestionnaire Sessions & Boards mais repond lui-meme a ses `data-act` et `data-form` : le gestionnaire ignore les clics et envois qui viennent de `[data-memory-center]` (passe de finitions avant la Slice 10). Avant, chacun y etait aussi traite comme une action du gestionnaire, et le bouton "Ouvrir les reglages memoire" journalisait `workspace.unknown_action {"name":"settings"}`. Ce bouton est le seul appelant de l alias `memory` : il ouvre Memoire & connaissances > Rappel (`test_memory_settings_browser.py::test_the_memory_center_settings_button_opens_recall`).
