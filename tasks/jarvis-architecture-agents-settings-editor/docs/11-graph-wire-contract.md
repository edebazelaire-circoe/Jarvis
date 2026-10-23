# 11 - Graph wire contract (fixé par agent 0 avant la vague A)

Forme JSON commune à la Slice 01 (producteur) et à la Slice 04 (consommateur). La Slice 01 peut ajouter des
champs ; elle n'en renomme ni n'en retire aucun sans accord d'agent 0. Valeurs énumérées = chaînes stables.

## Lecture : `GET /api/architecture` (route montée par la Slice 07)

```json
{
  "schema_version": 1,
  "revision": "t-17",
  "voice_architecture": {"id": "duplex", "label": "Duplex", "settings_target": "architecture_compat"},
  "nodes": [
    {
      "id": "voice", "kind": "brain", "label": "Voice Brain", "brain_type": "voice_surface",
      "process": "voice", "system": true,
      "state": "active",
      "state_reason": "",
      "activation": {"mutable": false, "reason": "La surface vocale porte l'audio."},
      "configurable": true,
      "ports": [
        {"id": "audio_in", "direction": "in", "channel": "audio", "family": "audio"},
        {"id": "audio_out", "direction": "out", "channel": "audio", "family": "audio"},
        {"id": "delegate", "direction": "out", "channel": "request", "family": "brain_request"}
      ]
    }
  ],
  "connections": [
    {
      "id": "voice.delegate->core.request",
      "source": {"node": "voice", "port": "delegate"},
      "target": {"node": "core", "port": "request"},
      "channel": "request",
      "purpose": "Délégation des demandes au cerveau Core",
      "enabled": true,
      "mutability": "toggleable",
      "locked_reason": "",
      "impact_when_disabled": "La voix répond seule ; aucune action ni outil Core.",
      "applies": "next_turn",
      "pending": null,
      "governed_by": null,
      "binding": "voice_architecture.config.brain_orchestration"
    }
  ]
}
```

- `kind` : `brain` | `endpoint` (`audio_input`, `audio_output`… via `endpoint_type`) | `pool` (sous-agents).
- `state` : `active` | `inactive` | `shadow` | `unavailable` ; `state_reason` explique.
- `channel` : `audio` | `request` | `response` | `tool_call` | `event` | `speech`.
- `mutability` : `required_locked` | `toggleable` | `creatable_removable` | `governed` (lecture seule sur le
  graphe, `governed_by` = `{"kind": "brain_config", "node": "core", "field": "delegation"}`).
- `applies` : `live` | `next_turn` | `core_restart`. `pending` = `{"enabled": false, "applies": "core_restart"}`
  quand une valeur persistée attend un redémarrage (l'état `enabled` reste celui du runtime vivant).
- `binding` : identité du réglage runtime qui porte la liaison (jamais un état d'interface).

## Écriture : `POST /api/architecture/connections/{id}`

Corps : `{"base_revision": "t-17", "enabled": false}` ; création/suppression :
`POST /api/architecture/connections` `{"base_revision", "source", "target", "channel"}` et
`DELETE /api/architecture/connections/{id}?base_revision=…`.

Réponse : `200 {"ok": true, "snapshot": {…}}` (snapshot complet faisant foi) ou
`{"ok": false, "code": "…", "reason": "…", "snapshot": {…}}` avec `409 architecture_revision_stale`,
`423 connection_locked`, `422 connection_incompatible | connection_unknown | connection_governed`,
`500 architecture_apply_failed` (rien de persisté).

## Disposition (UI seule) : `GET/PUT /api/architecture/layout`

`{"revision": "l-3", "positions": {"voice": {"x": 120, "y": 80}}}` ; `PUT` avec `base_revision`.
Stockée à part, ne change jamais le runtime ; `409 layout_revision_stale`.
