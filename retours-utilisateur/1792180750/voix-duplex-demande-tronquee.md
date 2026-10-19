# Voix duplex : le cerveau ne reçoit que la fin (ou un morceau) de ce que dit l'utilisateur

Session JARVIS jsess_cb573e1f88b34a67ba02c180267c934b, conversation 1e319222-7d43-4f7b-acf1-dbd898a781e1, 2026-10-16 vers 20:20.
Retour : « T'as loupé quasiment tout mon message et c'est pas la première fois. »

## Constat

- Le mode actif n'est pas `continuous_brain` : le journal dit `voice.active ... "arch": "duplex"` (GPT-Live). Le cerveau n'a donc jamais reçu de transcription finale ; il reçoit le texte que le client reconstruit lui-même.
- Tours cerveau reçus (history/2026-10-16.jsonl, conversation_events) :
  - 20:20:08 : `cap... capables de... de trouver des... méthodes pour le sentir. Parce que... [...] comment on pourra implémenter tout ça` (82 mots). Commence au milieu d'une phrase. Le cerveau répond « Je n'ai pas bien saisi votre demande ».
  - 20:21:08 : `... seulement une partie... implémentation. Et euh... t'as loupé quasiment tout mon message [...]` (33 mots). Commence par « ... », au milieu d'une phrase.
- Récurrent : sur 589 tours `source=realtime` de l'historique, 14 commencent par `,` `.` ou `...` (ponctuation qui appartenait à un mot déjà perdu), dont 3 le 16/10 avant 20:00 (19:25:14, 19:27:21, 20:04:40). Beaucoup d'autres commencent en minuscule, au milieu d'une phrase (ex. 19:29:32 « ou... Je ne sais pas qui »).

## Mécanisme (établi dans le code, reproduit)

Le fil GPT-Live ne publie aucune fin d'entrée. `LiveFrontendSession` (jarvis/runtime/live_frontend_session.py) accumule les deltas de transcription dans `_request_deltas`, et la délégation du fournisseur (`session.delegation.created`) envoie ce tampon au cerveau (jarvis/runtime/live_delegation.py, `_dispatch_brain_turn` -> `pending_request_text()`). Le tampon est vidé de façon silencieuse dans trois cas :

1. **Un delta de transcription du modèle efface la demande en cours** (`_observe`, ligne ~472 : `AssistantTranscriptDelta and not self._request_held` -> `reset_pending_request()`). Le modèle duplex produit des sorties pendant que l'utilisateur parle (réflexes, « mm », reste d'une réponse coupée). Tout ce qui a été dit avant ce delta disparaît ; seule la suite part à la délégation.
2. **Plafond de 256 deltas / 8192 octets** (`MAX_REQUEST_DELTAS`, `MAX_REQUEST_UTF8`, `_note_request_delta`) : on retire les plus anciens. Un long monologue perd donc son début, sans trace. Le tour le plus long de l'historique fait 242 à 258 mots (19:29:32 et 19:30:58 le 16/10), au ras du plafond.
3. **`reset_pending_request()` dans le `finally` de `_dispatch_brain_turn`** : tout delta arrivé entre la lecture du texte (après 0,4 s de grâce) et la fin de la requête HTTP est effacé, et la suite d'une phrase dont la délégation est partie trop tôt (le fournisseur délègue pendant les « euh... » de l'utilisateur) ne part que dans la délégation suivante, sans son début.

Reproduction (script jetable, code inchangé, `_observe` appelé directement) :
- 7 deltas utilisateur, 1 delta modèle, 4 deltas utilisateur -> `pending_request_text()` = « la mise en oeuvre » (les 7 premiers mots perdus).
- 300 deltas utilisateur -> le texte commence à `mot44` et fait 256 mots.

## Preuves dans les journaux (corrélation, pas preuve directe)

Aucun delta brut n'est journalisé, donc on ne peut pas relire ce qu'a transcrit le fournisseur. Ce qu'on voit (runtime/trace.jsonl) :

- 20:21:08 : une sortie du modèle démarre à **20:20:53.9** (`voice.output_started`, `speech_id` nul = sortie spontanée du modèle), en plein milieu de la parole de l'utilisateur (`voice.barge_in_confirming` à 20:20:54.4, rejeté : « output_finished »). La délégation part à 20:21:08.8 avec un texte qui commence par « ... seulement une partie ». Concordant avec le cas 1 : ~17 s de parole (20:20:37 -> 20:20:54) effacées.
- 19:29:32 : sortie du modèle à 19:28:27.7 pendant que l'utilisateur parle ; la délégation de 19:29:32 commence par « ou... Je ne sais pas qui ».
- Mêmes motifs aux autres tours à ponctuation initiale : une sortie spontanée du modèle a eu lieu dans les secondes ou minutes précédentes sans délégation entre les deux.

## Ce qui n'est PAS établi

- **Le tour de 20:20:08** : aucune sortie du modèle visible entre 20:18:15 (barge-in, lecture coupée jusqu'à 20:20:15, 1155 blocs audio jetés) et la délégation de 20:20:08. Le début perdu (la phrase avant « cap... capables ») n'est expliqué ni par le cas 1 (à moins d'un delta de texte du modèle sans audio, que `_observe` verrait avant le filtre de lecture), ni par le plafond (82 mots seulement). Hypothèses restantes : delta modèle sans audio ; transcription d'entrée du fournisseur lacunaire pendant que la lecture est atténuée/coupée (barge-in 20:18:14) ; ou parole réellement entrecoupée de longs silences. Sans delta brut, impossible de trancher.
- Que le fournisseur ne rate jamais de mots lui-même (sa transcription d'entrée est un ASR séparé du modèle).

## Correctif proposé

1. Ne plus effacer la demande sur un delta du modèle. Fermer la demande uniquement quand elle est consommée par une délégation acceptée (ou après un silence utilisateur long), jamais sur une sortie du modèle. Le « hold » devient inutile.
2. Remplacer le tampon unique par des segments horodatés : une délégation envoie tout ce qui n'a pas encore été remis (curseur « remis jusqu'à N »), et `finally` n'avance que le curseur jusqu'à ce qui a été effectivement lu, jamais jusqu'à ce qui est arrivé depuis.
3. Plafond : lever à plusieurs milliers de deltas (le brain accepte déjà >1,3 ko) et, si on tronque, le dire (`voice.live.request_truncated` dans le journal et marqueur « [début tronqué] » dans le texte), jamais en silence.
4. Journaliser les deltas d'entrée agrégés par délégation (nombre, octets, mots perdus par reset/plafond) : sans cela le cas de 20:20:08 reste indémontrable et la prochaine perte aussi.
5. Test : rejouer la séquence user / modèle / user (voir la reproduction) et vérifier que le texte remis contient les 11 mots ; idem 300 deltas.

Fichiers : jarvis/runtime/live_frontend_session.py (`_observe`, `_note_request_delta`, `reset_pending_request`), jarvis/runtime/live_delegation.py (`_dispatch_brain_turn`), jarvis/adapters/openai_live_frontend.py (deltas, délégation).
