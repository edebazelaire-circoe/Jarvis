# Rappels d'agenda proactifs

JARVIS ne parlait que lorsqu'on lui parlait. Core relève maintenant l'agenda et
ouvre de lui-même un tour du cerveau pour rappeler les rendez-vous.

## Chaîne

```
control-center-settings.json (bloc agenda_reminders, relu à chaque évaluation)
  -> AgendaReminderService (jarvis/core/agenda_reminders.py), tick 30 s
       relecture de l'agenda toutes les `refresh_minutes` :
       McpPluginService.call(<plugin>.infomaniak.calendar.list_events)  [lecture seule]
       -> plan pur (jarvis/domain/agenda_reminders.py)
       -> BrainOrchestrator.wake_for_agenda(prompt)  [tour SYSTEM]
  -> le cerveau habille la phrase (Core n'en écrit aucune, Décision 14) ou se tait
```

L'outil est cherché par nom (`*calendar.list_events`) parmi les plugins actifs
et connectés ; aucun plugin calendrier : un diagnostic `core.agenda.fetch_failed`
(une fois), le dernier cache reste utilisé.

## Étapes d'un rendez-vous (chacune dite une fois)

`evening` (veille au soir, rendez-vous avant midi), `morning` (matin même),
`lead:N` (N minutes avant), `late` (« en cours / manqué », se tait si
l'utilisateur a parlé au cerveau depuis le dernier rappel de ce rendez-vous).
Seule l'étape échue la plus récente est annoncée ; les plus anciennes sont
consommées en silence. Rendez-vous en journée entière, annulés ou « disponible »
(non bloquants) : ignorés.

## Réglages (Control Center, onglet Agenda ; `settings_get` / `settings_set` : `agenda.<clé>`)

| Identifiant | Défaut | Rôle |
| --- | --- | --- |
| `agenda.enabled` | `true` | interrupteur général |
| `agenda.lead_minutes` | `30, 10` | rappels avant l'heure (1 à 4 valeurs, 1-1440) ; vide = aucun |
| `agenda.morning_time` | `07:45` | rappel du matin ; vide = aucun |
| `agenda.evening_time` | `19:00` | rappel de la veille ; vide = aucun |
| `agenda.late_minutes` | `5` | « en cours / manqué » après l'heure ; 0 = jamais |
| `agenda.refresh_minutes` | `10` | période de relecture de l'agenda (2-120) |

Tous agissent à chaud ; seul le démarrage de la boucle exige que Core ait été
relancé une fois avec ce code.

## Mémoire « déjà rappelé »

`<data_root>/agenda_reminders.json` : `{"<id>|<début>|<étape>": "<horodatage>"}`,
élagué à 3 jours. Pas de base, pas de migration : le perdre rejoue au pire un
rappel. Un rendez-vous déplacé change de clé et est rappelé à nouveau.

## Limites connues

- L'accusé est un tour adressé de l'utilisateur après le dernier rappel, pas une
  confirmation explicite : n'importe quelle parole vaut accusé pour l'étape `late`.
- Un rappel n'est pas dit si un tour du cerveau est en vol ou si aucune
  conversation n'écoute ; il est retenté toutes les 30 s tant qu'il n'est pas périmé.
- Un seul calendrier (celui par défaut du plugin).
