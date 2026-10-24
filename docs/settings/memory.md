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
  `control_center_memory.js` (mounted since refonte-ui-settings Slice 06 in the Memory Center tab of the Settings,
  `mountMemoryCenter`; see « Memory Center » below).

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

## Memory Center (Slice 12 ; refonte-ui-settings, Slice 06)

**Maison unique : Reglages › Memoire & connaissances › onglet Memory Center** (section `memory_center`,
`save: 'readonly'`, maquette `tasks/refonte-ui-settings/references/ui/05-memory-center.png`). Module
`jarvis/runtime/control_center_memory.js` (`JarvisMemoryCenter.create(host, {tab, open, openDiagnostics})`, monte
par `mountMemoryCenter` dans `control_center.html`, CSS injectee `.mcw` / `.mc-*`, pictogrammes de
`JarvisMemorySettings.icon`). Plus de seconde copie : `#memoryCenterMount` et la vue « etendue » de Sessions & Boards
sont retires ; le bouton « Memory Center » de Sessions & Boards (`JarvisMemoryCenter.open(tab)`) ferme le
gestionnaire et ouvre cet onglet (`openSettingsTab('memory_center')`). Les tuiles de l onglet Memoire ouvrent
l onglet interne demande (Notes, Candidats, Test de rappel).

Composition (deux colonnes au-dela de 860 px de large, requete de conteneur ; une colonne en dessous, le rail
passe sous la surface de travail) :

| Zone | Contenu | Donnees |
| --- | --- | --- |
| Bandeau | identite + 4 statistiques : notes (« 200+ » au-dela d une page de 200), candidats en attente, sources de connaissances actives (nommees), index de rappel (Pret / En synchro / Indisponible / Injoignable) | `/api/memory/notes?limit=200`, `/api/memory/candidates?state=proposed`, `/api/memory/status` |
| Onglets internes | Notes, Candidats (pastille du nombre en attente), Connaissances, Test de rappel ; fleches, Debut, Fin | — |
| Notes (surface principale) | table dense : contenu (titre + extrait), niveau L0-L3, type, portee, retention (classe), date ; recherche (index lexical, pastille Derive), filtres niveau / retention / type / remplacees appliques des qu ils changent ; pagination de 10 (`limit=11` pour savoir s il y a une page suivante ; « sur N » seulement sans filtre et sous 200) ; une ligne ouvre la note dans un `<dialog>` (contenu canonique, dimensions, provenance, liens ; Echap la ferme sans fermer les Reglages) | `/api/memory/notes`, `/api/memory/search`, `/api/memory/notes/{id}` |
| Reglages essentiels | rappel, souvenirs par tour, recherche semantique, consolidation : **projections en lecture seule** de l etat enregistre, bouton « Modifier » vers l onglet Memoire | section `memory` de `/api/settings` |
| Rail : candidats | les 3 premiers candidats proposes, Accepter / Rejeter, « Voir les N candidats » | `/api/memory/candidates` |
| Rail : test de rappel | phrase, « Tester » (Entree), resultats dans l ordre rendu avec score et barre relative au meilleur | `/api/memory/recall-explain` |
| Rail : sante des index | une tuile par etage reel (lexical, semantique, Tencent, wiki, skills… : ce que Core declare) ; lien « Detail dans Avance › Diagnostics » | `/api/memory/status` |
| Onglet Candidats | file complete filtrable par etat, detail (corps, portee, retention, provenance, conflits) a la demande | `/api/memory/candidates/{id}` |
| Onglet Connaissances | sources declarees par Core et regles d acces par agent, lecture seule ; « Modifier » ouvre l onglet Connaissances | `/api/memory/status`, `/api/settings` |
| Onglet Test de rappel | le meme test avec « pourquoi », rang par etage, source, budget, durees, codes de degradation | `/api/memory/recall-explain` |

**Decisions de candidat.** Seule ecriture : `POST /api/memory/candidates/{id}/decision`. Deux temps : « Accepter » ou
« Rejeter » ouvre une confirmation dans la carte (focus sur « Confirmer ») ; la confirmation est **optimiste** : la
carte quitte la file et les compteurs tout de suite ; un refus de Core (404, 409 `memory_conflict_revision`, 403, 503)
la remet a sa place avec la raison reelle (`role="alert"`, journal `memory_center_decision_refused`). Les protections
de revision et de concurrence restent celles de Core. Echap ferme d abord la note ouverte, puis une confirmation, avant
de laisser le shell fermer les Reglages.

**Etats.** Chaque carte charge seule : chargement (spinner, arrete par `prefers-reduced-motion`), vide explicite,
erreur avec la raison reelle et « Réessayer ». Core muet : statistiques « — » / « Injoignable », jamais un chiffre.

**Ecarts voulus a la maquette** (aucune valeur de maquette n est codee) : pas de « taux de rappel » (Core n en
fournit pas : remplace par l etat de l index), pas de « connaissances cles » comptees (remplace par les sources
actives), retention affichee en classe (Long terme, Eternelle…) et non en pourcentage, pas de cases a cocher de
selection multiple (aucune action groupee n existe), reglages essentiels non modifiables sur place (une seule place
editable par reglage), tuile Tencent seulement si Core declare l etage. Canonique / Derive / Proposition : chaque zone
porte sa pastille ; aucun bouton de reconstruction d index (aucune route Core).

Tests : `tests/unit/test_control_center_memory_js.py` (node) et `tests/unit/test_memory_settings_browser.py` (vrai
Chrome, faux Core `tests/unit/_memory_center_fixture.py`).
